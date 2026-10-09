"""M4A evidence timeline for assets in the existing HomeOS owner interface."""
import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from app.main import app, actor, db, require_owner
from app.memory_bridge import _run, _uuid, supported


@app.get("/api/memory/assets/{entity_id}/history")
def owner_asset_history(entity_id:uuid.UUID,m=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    if not supported(s):
        raise HTTPException(503,"Home Memory requires configured PostgreSQL")
    house=_uuid(m.household_id)
    entity=_run(s,"""SELECT id,canonical_name,entity_type,status FROM memory_entities
       WHERE household_id=:house AND id=:id AND entity_type IN ('ASSET','ITEM')
       AND status='ACTIVE'""",house=house,id=entity_id).mappings().first()
    if not entity:raise HTTPException(404,"Registered asset not found")
    edges=_run(s,"""SELECT a.id,a.predicate,a.verification_status,a.recorded_at,
       a.valid_from,a.valid_until,
       e.canonical_name AS location_name,e.id AS location_id,
       v.source_type,v.source_ref,v.recorded_at AS evidence_time
       FROM memory_assertions a
       JOIN memory_entities e ON e.household_id=a.household_id AND e.id=a.object_id
       JOIN memory_evidence v ON v.household_id=a.household_id AND v.id=a.evidence_id
       WHERE a.household_id=:house AND a.subject_id=:id
       AND a.predicate IN ('LOCATED_IN','STORED_IN')
       AND a.verification_status IN ('CONFIRMED','SUPERSEDED')
       ORDER BY a.recorded_at DESC,a.id DESC LIMIT 35""",
       house=house,id=entity_id).mappings().all()
    events=_run(s,"""SELECT event_type,occurred_at,payload
       FROM memory_events WHERE household_id=:house AND subject_id=:id
       ORDER BY occurred_at DESC LIMIT 35""",house=house,id=entity_id).mappings().all()
    def observation_of(reference):
        if not reference or not reference.startswith("visual-review:"):
            return None
        try:return str(uuid.UUID(reference.removeprefix("visual-review:")))
        except ValueError:return None
    return {"asset":{"id":str(entity["id"]),"name":entity["canonical_name"]},
            "locations":[{
              "location_name":edge["location_name"],
              "location_id":str(edge["location_id"]),
              "verification_status":edge["verification_status"],
              "source_type":edge["source_type"],
              "source_ref":edge["source_ref"],
              "observation_id":observation_of(edge["source_ref"]),
              "recorded_at":edge["recorded_at"].isoformat(),
              "valid_until":edge["valid_until"].isoformat() if edge["valid_until"] else None,
            } for edge in edges],
            "events":[{
              "type":e["event_type"],"occurred_at":e["occurred_at"].isoformat(),
              "from":(e["payload"] or {}).get("from"),
              "to":(e["payload"] or {}).get("to"),
              "observation_id":(e["payload"] or {}).get("observation_id")
            } for e in events],
            "disclaimer":"Recorded and verified history only; not a live location sensor."}
