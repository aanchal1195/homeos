"""M3D: owner-invoked, additive projection from the M2C virtual house.

The M2C operational tables remain authoritative. No graph fact is created
from an AI observation. Never overwrite an OWNER-confirmed location on sync.
Requires M2C Alembic revision 0004_memory_links and memory migrations 001-004
to have been installed in the SAME PostgreSQL database.
"""
import uuid
from collections import Counter
from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from app import db, identity

router=APIRouter(prefix="/api/v1/memory",tags=["M2C integration"])

READS={
 "property":("SELECT id,name,property_type,address_label FROM properties WHERE household_id=%s","HOME"),
 "floor":("SELECT id,name,kind,sort_order,property_id FROM floors WHERE household_id=%s","FLOOR"),
 "room":("SELECT id,name,kind,floor_id FROM rooms WHERE household_id=%s","ROOM"),
 "zone":("SELECT id,name,kind,room_id FROM zones WHERE household_id=%s","ZONE"),
 "asset":("SELECT id,name,asset_type,status,next_service,room_id,zone_id FROM assets WHERE household_id=%s","ASSET"),
}
def require_m2c(conn,house):
    present=conn.execute("""SELECT
      to_regclass('public.properties') AS property,
      to_regclass('public.memory_legacy_links') AS mapping""").fetchone()
    if not present["property"] or not present["mapping"]:
        raise HTTPException(409,"M2C database tables and revision 0004_memory_links are required")
    found=conn.execute("SELECT 1 FROM households WHERE id=%s",(house,)).fetchone()
    if not found:
        raise HTTPException(404,"Configured household does not exist in M2C")

def entity_for(conn,house,table,row,entity_type,stats):
    if table=="floor" and row["kind"]!="floor":
        entity_type="SPACE"
    legacy=str(row["id"])
    attributes={"origin":"M2C","legacy_type":table,"legacy_id":legacy}
    for key in ("kind","property_type","address_label","sort_order","asset_type","status","next_service"):
        if key in row and row[key] is not None:
            attributes[key]=row[key]
    old=conn.execute("""SELECT entity_id FROM memory_legacy_links WHERE
        household_id=%s AND legacy_type=%s AND legacy_id=%s""",
        (house,table,legacy)).fetchone()
    if old:
        entity_id=old["entity_id"]
        conn.execute("""UPDATE memory_entities SET canonical_name=%s,entity_type=%s,
          attributes=attributes || %s,status='ACTIVE' WHERE household_id=%s AND id=%s""",
          (row["name"],entity_type,Jsonb(attributes),house,entity_id))
        stats["updated"]+=1
    else:
        entity_id=conn.execute("""INSERT INTO memory_entities
          (household_id,entity_type,canonical_name,attributes)
          VALUES(%s,%s,%s,%s) RETURNING id""",
          (house,entity_type,row["name"],Jsonb(attributes))).fetchone()["id"]
        conn.execute("""INSERT INTO memory_legacy_links
          (household_id,legacy_type,legacy_id,entity_id)
          VALUES(%s,%s,%s,%s)""",(house,table,legacy,entity_id))
        stats["created"]+=1
    stats[entity_type]+=1
    return entity_id

def project_edge(conn,house,source_id,predicate,target_id,source_key,stats):
    if source_id==target_id:return
    current=conn.execute("""SELECT a.id,a.object_id,e.source_type,e.source_ref
       FROM memory_assertions a JOIN memory_evidence e
       ON e.household_id=a.household_id AND e.id=a.evidence_id
       WHERE a.household_id=%s AND a.subject_id=%s AND a.predicate=%s
       AND a.verification_status='CONFIRMED' AND a.valid_until IS NULL
       FOR UPDATE OF a""",(house,source_id,predicate)).fetchall()
    if len(current)==1 and current[0]["object_id"]==target_id:
        return
    # A verified owner's claim takes precedence over a derived M2C projection.
    if any(row["source_type"] != "SYSTEM" or not (row["source_ref"] or "").startswith("M2C:")
           for row in current):
        ev=conn.execute("""INSERT INTO memory_evidence(household_id,source_type,source_ref)
            VALUES(%s,'SYSTEM',%s) RETURNING id""",(house,source_key)).fetchone()["id"]
        already=conn.execute("""SELECT 1 FROM memory_observations WHERE
           household_id=%s AND subject_id=%s AND predicate=%s AND candidate_object_id=%s
           AND status='PENDING' AND payload->>'reason'='M2C graph projection conflicts with verified memory'
           LIMIT 1""",(house,source_id,predicate,target_id)).fetchone()
        if not already:
            conn.execute("""INSERT INTO memory_observations
                (household_id,subject_id,predicate,candidate_object_id,evidence_id,payload)
                VALUES(%s,%s,%s,%s,%s,%s)""",(house,source_id,predicate,target_id,ev,
                Jsonb({"reason":"M2C graph projection conflicts with verified memory","source":source_key})))
            stats["conflicts_proposed"]+=1
        return
    for row in current:
        conn.execute("""UPDATE memory_assertions SET verification_status='SUPERSEDED',valid_until=now()
          WHERE household_id=%s AND id=%s""",(house,row["id"]))
    evidence=conn.execute("""INSERT INTO memory_evidence(household_id,source_type,source_ref)
       VALUES(%s,'SYSTEM',%s) RETURNING id""",(house,source_key)).fetchone()["id"]
    aid=conn.execute("""INSERT INTO memory_assertions
      (household_id,subject_id,predicate,object_id,evidence_id,verification_status,supersedes_id)
      VALUES(%s,%s,%s,%s,%s,'CONFIRMED',%s) RETURNING id""",
      (house,source_id,predicate,target_id,evidence,current[0]["id"] if len(current)==1 else None)
    ).fetchone()["id"]
    if predicate=="LOCATED_IN":
        conn.execute("""INSERT INTO memory_events
           (household_id,event_type,subject_id,payload,idempotency_key)
           VALUES(%s,'LOCATION_PROJECTED',%s,%s,%s)
           ON CONFLICT (household_id,idempotency_key) DO NOTHING""",
           (house,source_id,Jsonb({"location_id":str(target_id),"source":"M2C"}),f"M2C:location:{aid}"))
    stats["relationships_changed"]+=1

@router.post("/import/m2c")
def import_m2c(house=Depends(identity)):
    """Explicit owner API-token controlled import; data preserved on repeat runs."""
    with db() as conn:
        require_m2c(conn,house)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",("homeos:memory:"+house,))
        loaded={}
        refs={}
        stats=Counter()
        for table,(statement,kind) in READS.items():
            rows=conn.execute(statement,(house,)).fetchall()
            loaded[table]=rows
            for row in rows:
                refs[(table,str(row["id"]))]=entity_for(conn,house,table,row,kind,stats)
        def edge(table,row,pred,parent_kind,parent_key):
            child=refs.get((table,str(row["id"])))
            parent=refs.get((parent_kind,str(row[parent_key]))) if row.get(parent_key) else None
            if child and parent:
                project_edge(conn,house,child,pred,parent,f"M2C:{table}:{row['id']}",stats)
        for row in loaded["floor"]:edge("floor",row,"PART_OF","property","property_id")
        for row in loaded["room"]:edge("room",row,"PART_OF","floor","floor_id")
        for row in loaded["zone"]:edge("zone",row,"PART_OF","room","room_id")
        for row in loaded["asset"]:
            if row["zone_id"] and ("zone",str(row["zone_id"])) in refs:
                edge("asset",row,"LOCATED_IN","zone","zone_id")
            else:
                edge("asset",row,"LOCATED_IN","room","room_id")
        return {"household_id":house,"counts":dict(stats),"mode":"M2C_OPERATIONAL_PROJECTION"}
