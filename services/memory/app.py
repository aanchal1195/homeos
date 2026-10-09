"""HomeOS M3A memory API. Single-household owner-token bootstrap; not production IAM."""
import os
import re
import uuid
from contextlib import contextmanager
from typing import Literal
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

app = FastAPI(title="HomeOS Memory M3A", version="0.1.0")
ALIASES = {"fridge": "refrigerator", "ro": "water purifier", "washer": "washing machine",
           "geyser": "water heater", "vacuum": "vacuum cleaner"}
TYPES = {"HOME","FLOOR","ROOM","SPACE","ZONE","ASSET","STORAGE","ITEM","PERSON","STAFF","VENDOR","TASK","ISSUE","DOCUMENT","EVENT"}

def identity(authorization: str | None = Header(default=None)):
    from secrets import compare_digest
    secret = os.getenv("HOMEOS_API_TOKEN", "")
    household = os.getenv("HOMEOS_HOUSEHOLD_ID", "")
    if not secret or not household or not authorization or not authorization.startswith("Bearer ") or not compare_digest(authorization[7:], secret):
        raise HTTPException(401, "Unauthorized")
    try:
        return str(uuid.UUID(household))
    except ValueError:
        raise HTTPException(503, "Invalid server household configuration")

@contextmanager
def db():
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        with conn.transaction():
            yield conn

def name_key(name: str):
    s = re.sub(r"[^\w\s]", " ", name.casefold()).strip()
    return " ".join(s.split())

class EntityIn(BaseModel):
    entity_type: str
    canonical_name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    attributes: dict = Field(default_factory=dict)

class EvidenceIn(BaseModel):
    source_type: Literal["OWNER","STAFF_MESSAGE","TASK","INSPECTION","PHOTO","VIDEO","DOCUMENT","SYSTEM"]
    source_ref: str | None = None

class LocationIn(BaseModel):
    location_id: uuid.UUID
    evidence: EvidenceIn
    idempotency_key: str = Field(min_length=8, max_length=200)

class ObservationIn(BaseModel):
    subject_id: uuid.UUID | None = None
    candidate_object_id: uuid.UUID | None = None
    predicate: str | None = None
    evidence: EvidenceIn
    payload: dict = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)

class QueryIn(BaseModel):
    query: str = Field(min_length=1,max_length=500)

def need_entity(conn, household, eid):
    row = conn.execute("SELECT id,entity_type,canonical_name FROM memory_entities WHERE household_id=%s AND id=%s AND status='ACTIVE'", (household,eid)).fetchone()
    if row is None:
        raise HTTPException(404,"Entity not found")
    return row

def evidence_insert(conn,household,e):
    return conn.execute("INSERT INTO memory_evidence(household_id,source_type,source_ref) VALUES(%s,%s,%s) RETURNING id",
                        (household,e.source_type,e.source_ref)).fetchone()["id"]

@app.get("/health")
def health():
    return {"status":"ok"}

@app.post("/api/v1/memory/entities",status_code=201)
def create_entity(body: EntityIn, household=Depends(identity)):
    if body.entity_type not in TYPES:
        raise HTTPException(422,"Unknown entity type")
    with db() as conn:
        row = conn.execute("INSERT INTO memory_entities(household_id,entity_type,canonical_name,attributes) VALUES(%s,%s,%s,%s) RETURNING id",
                           (household,body.entity_type,body.canonical_name.strip(),Jsonb(body.attributes))).fetchone()
        eid=row["id"]
        for alias in set(a.strip() for a in body.aliases if a.strip()):
            conn.execute("INSERT INTO memory_aliases(household_id,entity_id,alias) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",(household,eid,alias))
        return {"id":eid,"name":body.canonical_name}

def find(conn,household,term):
    normalized = name_key(ALIASES.get(name_key(term),term))
    rows=conn.execute("""SELECT DISTINCT e.id,e.entity_type,e.canonical_name
      FROM memory_entities e LEFT JOIN memory_aliases a ON a.entity_id=e.id AND a.household_id=e.household_id
      WHERE e.household_id=%s AND e.status='ACTIVE'
      AND (lower(e.canonical_name)=%s OR lower(a.alias)=%s OR lower(e.canonical_name) LIKE %s)
      ORDER BY e.canonical_name LIMIT 30""",(household,normalized,normalized,"%"+normalized+"%")).fetchall()
    return rows

@app.get("/api/v1/memory/entities/search")
def search(q:str,household=Depends(identity)):
    if not q.strip():
        raise HTTPException(422,"q required")
    with db() as conn:
        return {"matches":find(conn,household,q)}

@app.post("/api/v1/memory/entities/{entity_id}/location")
def set_location(entity_id:uuid.UUID,body:LocationIn,household=Depends(identity)):
    with db() as conn:
        # Idempotency prevents creating duplicate movement events and assertions.
        existing=conn.execute("SELECT payload FROM memory_events WHERE household_id=%s AND idempotency_key=%s",
                              (household,body.idempotency_key)).fetchone()
        if existing:
            return {"status":"already_applied","event":existing["payload"]}
        subject=need_entity(conn,household,entity_id)
        location=need_entity(conn,household,body.location_id)
        if subject["id"]==location["id"] or location["entity_type"] not in ("HOME","FLOOR","ROOM","SPACE","ZONE","STORAGE"):
            raise HTTPException(422,"Invalid location")
        # Serialize concurrent updates of the same physical entity.
        conn.execute("SELECT id FROM memory_entities WHERE household_id=%s AND id=%s FOR UPDATE",(household,entity_id))
        prior=conn.execute("""SELECT id,object_id FROM memory_assertions WHERE household_id=%s AND subject_id=%s
                              AND predicate='LOCATED_IN' AND verification_status='CONFIRMED' AND valid_until IS NULL FOR UPDATE""",
                           (household,entity_id)).fetchone()
        if prior and prior["object_id"]==body.location_id:
            return {"status":"unchanged","location_id":body.location_id}
        evidence=evidence_insert(conn,household,body.evidence)
        if prior:
            conn.execute("""UPDATE memory_assertions SET valid_until=now(),verification_status='SUPERSEDED'
                         WHERE household_id=%s AND id=%s""",(household,prior["id"]))
        assertion=conn.execute("""INSERT INTO memory_assertions
            (household_id,subject_id,predicate,object_id,evidence_id,verification_status,supersedes_id)
            VALUES(%s,%s,'LOCATED_IN',%s,%s,'CONFIRMED',%s) RETURNING id""",
            (household,entity_id,body.location_id,evidence,prior["id"] if prior else None)).fetchone()
        payload={"from":str(prior["object_id"]) if prior else None,"to":str(body.location_id),"assertion_id":str(assertion["id"])}
        conn.execute("""INSERT INTO memory_events(household_id,event_type,subject_id,payload,idempotency_key)
                       VALUES(%s,'LOCATION_CHANGED',%s,%s,%s)""",
                     (household,entity_id,Jsonb(payload),body.idempotency_key))
        return {"status":"updated","event":payload}

@app.get("/api/v1/memory/entities/{entity_id}/location")
def get_location(entity_id:uuid.UUID,household=Depends(identity)):
    with db() as conn:
        entity=need_entity(conn,household,entity_id)
        paths=[]
        cursor=entity_id
        visited={cursor}
        for _ in range(12):
            row=conn.execute("""SELECT e.id,e.canonical_name,e.entity_type,a.recorded_at,v.source_type,v.source_ref
              FROM memory_assertions a JOIN memory_entities e ON e.id=a.object_id AND e.household_id=a.household_id
              JOIN memory_evidence v ON v.id=a.evidence_id AND v.household_id=a.household_id
              WHERE a.household_id=%s AND a.subject_id=%s AND a.predicate IN ('LOCATED_IN','PART_OF')
              AND a.verification_status='CONFIRMED' AND a.valid_until IS NULL ORDER BY
              CASE WHEN a.predicate='LOCATED_IN' THEN 0 ELSE 1 END LIMIT 1""",(household,cursor)).fetchone()
            if not row or row["id"] in visited: break
            visited.add(row["id"])
            paths.append(row)
            cursor=row["id"]
        return {"entity":entity,"path":paths}

@app.post("/api/v1/memory/observations",status_code=201)
def add_observation(body:ObservationIn,household=Depends(identity)):
    with db() as conn:
        for eid in (body.subject_id,body.candidate_object_id):
            if eid: need_entity(conn,household,eid)
        ev=evidence_insert(conn,household,body.evidence)
        oid=conn.execute("""INSERT INTO memory_observations
          (household_id,subject_id,candidate_object_id,predicate,evidence_id,payload,confidence)
          VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
          (household,body.subject_id,body.candidate_object_id,body.predicate,ev,Jsonb(body.payload),body.confidence)).fetchone()["id"]
        return {"id":oid,"status":"PENDING"}

@app.get("/api/v1/memory/entities/{entity_id}/history")
def history(entity_id:uuid.UUID,household=Depends(identity)):
    with db() as conn:
        need_entity(conn,household,entity_id)
        return {"events":conn.execute("""SELECT event_type,payload,occurred_at FROM memory_events
          WHERE household_id=%s AND subject_id=%s ORDER BY occurred_at DESC LIMIT 100""",(household,entity_id)).fetchall()}

@app.post("/api/v1/memory/query")
def query(body:QueryIn,household=Depends(identity)):
    phrase=body.query.strip()
    # Restrict v0.1 natural language to known read-only shapes; never let text generate SQL.
    count=re.search(r"(?:how many|kitne|kitni)\s+(bedrooms?|bathrooms?|rooms?)",phrase,re.I)
    with db() as conn:
        if count:
            kind=count.group(1).casefold().rstrip("s")
            if kind == "room":
                sql="SELECT count(*) AS n FROM memory_entities WHERE household_id=%s AND entity_type='ROOM' AND status='ACTIVE'"
                params=(household,)
            else:
                sql="SELECT count(*) AS n FROM memory_entities WHERE household_id=%s AND entity_type='ROOM' AND status='ACTIVE' AND lower(canonical_name) LIKE %s"
                params=(household,"%"+kind+"%")
            n=conn.execute(sql,params).fetchone()["n"]
            return {"answer_type":"COUNT","count":n,"entity_type":kind,"source":"MEMORY_GRAPH"}
        term=re.sub(r"^(?:where is|where's|find|locate)\s+(?:the\s+)?","",phrase,flags=re.I).strip(" ?.")
        term=re.sub(r"\s+(?:kahan hai|kaha hai|kidhar hai)\s*\??$","",term,flags=re.I)
        matches=find(conn,household,term)
        if not matches:
            return {"answer_type":"NOT_REGISTERED","query":term,"matches":[]}
        if len(matches)>1:
            return {"answer_type":"AMBIGUOUS","matches":matches}
        eid=matches[0]["id"]
    return get_location(eid,household)

from graph_routes import router as graph_router
app.include_router(graph_router)
