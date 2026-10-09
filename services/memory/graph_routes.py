"""Typed graph relationships; no arbitrary SQL or unverified visual promotion."""
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from psycopg.types.json import Jsonb
from app import db, identity, need_entity, evidence_insert, EvidenceIn

router=APIRouter(prefix="/api/v1/memory")

class EdgeIn(BaseModel):
    subject_id: uuid.UUID
    object_id: uuid.UUID
    predicate: Literal["PART_OF","CONTAINS","STORED_IN","ADJACENT_TO","ABOVE","CONNECTS_TO","HAS_ISSUE","ASSIGNED_TO","SERVICED_BY","RELATED_TO"]
    evidence: EvidenceIn

@router.post("/relationships",status_code=201)
def create_edge(body:EdgeIn,household=Depends(identity)):
    with db() as conn:
        subject=need_entity(conn,household,body.subject_id)
        obj=need_entity(conn,household,body.object_id)
        if subject["id"]==obj["id"]:
            raise HTTPException(422,"Self-relationships not allowed")
        if body.predicate == "PART_OF":
            # Restrict containment edges to prevent recursive graph corruption.
            if subject["entity_type"] not in ("FLOOR","ROOM","SPACE","ZONE","ASSET","STORAGE","ITEM"):
                raise HTTPException(422,"Invalid containment subject")
            ancestor=body.object_id
            visited=set()
            while ancestor and ancestor not in visited:
                if ancestor == body.subject_id: raise HTTPException(409,"Containment cycle")
                visited.add(ancestor)
                row=conn.execute("""SELECT object_id FROM memory_assertions WHERE household_id=%s
                 AND subject_id=%s AND predicate='PART_OF' AND verification_status='CONFIRMED'
                 AND valid_until IS NULL LIMIT 1""",(household,ancestor)).fetchone()
                ancestor=row["object_id"] if row else None
        ev=evidence_insert(conn,household,body.evidence)
        aid=conn.execute("""INSERT INTO memory_assertions
         (household_id,subject_id,object_id,predicate,evidence_id,verification_status)
         VALUES(%s,%s,%s,%s,%s,'CONFIRMED') RETURNING id""",
         (household,body.subject_id,body.object_id,body.predicate,ev)).fetchone()["id"]
        return {"id":aid,"status":"CONFIRMED"}

@router.get("/locations/{location_id}/contents")
def contents(location_id:uuid.UUID,household=Depends(identity)):
    with db() as conn:
        need_entity(conn,household,location_id)
        rows=conn.execute("""SELECT e.id,e.canonical_name,e.entity_type,a.predicate
          FROM memory_assertions a JOIN memory_entities e ON e.id=a.subject_id AND e.household_id=a.household_id
          WHERE a.household_id=%s AND a.object_id=%s AND a.predicate IN ('LOCATED_IN','PART_OF','STORED_IN')
          AND a.verification_status='CONFIRMED' AND a.valid_until IS NULL
          AND e.status='ACTIVE' ORDER BY e.canonical_name""",(household,location_id)).fetchall()
        return {"contents":rows}

@router.get("/entities/{entity_id}/relationships")
def relationships(entity_id:uuid.UUID,household=Depends(identity)):
    with db() as conn:
        need_entity(conn,household,entity_id)
        edges=conn.execute("""SELECT id,subject_id,object_id,predicate,verification_status,
                   valid_from,valid_until,recorded_at
          FROM memory_assertions WHERE household_id=%s AND (subject_id=%s OR object_id=%s)
          ORDER BY recorded_at DESC LIMIT 200""",(household,entity_id,entity_id)).fetchall()
        return {"relationships":edges}

class ReviewIn(BaseModel):
    decision: Literal["ACCEPTED","REJECTED"]

@router.post("/observations/{observation_id}/review")
def review(observation_id:uuid.UUID,body:ReviewIn,household=Depends(identity)):
    with db() as conn:
        row=conn.execute("""UPDATE memory_observations SET status=%s
          WHERE id=%s AND household_id=%s AND status='PENDING'
          RETURNING id,status""",(body.decision,observation_id,household)).fetchone()
        if not row: raise HTTPException(404,"Pending observation not found")
        # Acceptance does NOT mutate authoritative graph facts.
        return row
