"""M3F: owner-controlled photo inspection gateway for existing HomeOS.

The browser never gets HOMEOS_API_TOKEN. The server stores the photo privately
through the memory service. Separate affirmative consent is required before
sending image contents to the external vision provider.
"""
import os
import uuid
import httpx
from fastapi import Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.main import app, actor, db, require_owner
from app.memory_bridge import _uuid, _run, supported

ALLOWED_PHOTOS={"image/jpeg","image/png","image/webp"}
MAX_PHOTO_SIZE=15*1024*1024


def _ready(session:Session):
    if not supported(session):
        raise HTTPException(503,"Home Memory must be enabled and connected to PostgreSQL")
    if not os.getenv("HOMEOS_MEMORY_SERVICE_TOKEN"):
        raise HTTPException(503,"Private Home Memory service token is not configured")


def _service_request(method:str,path:str,*,body=None,files=None):
    """Only fixed internal paths constructed by this module reach the service."""
    base=os.getenv("HOMEOS_MEMORY_INTERNAL_URL","http://memory:8001").rstrip("/")
    headers={"Authorization":"Bearer "+os.environ["HOMEOS_MEMORY_SERVICE_TOKEN"]}
    timeout=httpx.Timeout(80.0,connect=5.0)
    try:
        with httpx.Client(timeout=timeout,trust_env=False) as client:
            if files is not None:
                response=client.request(method,base+path,headers=headers,files=files)
            else:
                response=client.request(method,base+path,headers=headers,json=body)
    except httpx.RequestError as exc:
        raise HTTPException(503,"Private Home Memory service is unavailable; start its Compose profile") from exc
    if response.status_code>=400:
        try:
            problem=response.json().get("detail")
        except (ValueError,AttributeError):
            problem=None
        description=str(problem)[:200] if problem else "Home Memory service request failed"
        raise HTTPException(response.status_code,description)
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(502,"Home Memory service returned invalid JSON") from exc


def _location(s:Session,house,location_id:uuid.UUID):
    row=_run(s,"""SELECT e.id,e.canonical_name,e.entity_type
         FROM memory_entities e
         JOIN memory_legacy_links l ON l.household_id=e.household_id AND l.entity_id=e.id
         WHERE e.household_id=:house AND e.id=:id AND e.status='ACTIVE'
           AND l.legacy_type IN ('floor','room','zone')
           AND e.entity_type IN ('ROOM','ZONE','SPACE','FLOOR')""",
         house=house,id=location_id).mappings().first()
    if not row:
        raise HTTPException(422,"Choose a registered, synchronized room or area")
    return row


@app.get("/api/memory/visual/inspection-locations")
def inspection_locations(m=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    _ready(s)
    house=_uuid(m.household_id)
    rows=_run(s,"""SELECT DISTINCT e.id,e.canonical_name,e.entity_type
       FROM memory_entities e
       JOIN memory_legacy_links l ON l.household_id=e.household_id AND l.entity_id=e.id
       WHERE e.household_id=:house AND e.status='ACTIVE'
         AND l.legacy_type IN ('floor','room','zone')
         AND e.entity_type IN ('ROOM','ZONE','SPACE','FLOOR')
       ORDER BY e.canonical_name""",house=house).mappings().all()
    return {"locations":[{"id":str(x["id"]),"name":x["canonical_name"],"type":x["entity_type"]} for x in rows]}


@app.post("/api/memory/visual/inspection-upload")
def inspection_upload(
    location_entity_id:uuid.UUID=Form(...),
    file:UploadFile=File(...),
    m=Depends(actor),s:Session=Depends(db),
):
    require_owner(m)
    _ready(s)
    house=_uuid(m.household_id)
    location=_location(s,house,location_entity_id)
    content_type=(file.content_type or "").lower()
    if content_type not in ALLOWED_PHOTOS:
        raise HTTPException(415,"Only JPEG, PNG or WebP photos are supported")
    # This limit is smaller than memory service's default 25 MiB limit.
    raw=file.file.read(MAX_PHOTO_SIZE+1)
    if not raw or len(raw)>MAX_PHOTO_SIZE:
        raise HTTPException(413,"Photo must be nonempty and at most 15 MiB")
    session=_service_request("POST","/api/v1/visual/sessions",
        body={"session_type":"INVENTORY_SCAN","expected_location_id":str(location_entity_id)})
    session_id=str(session["id"])
    media=_service_request("POST","/api/v1/visual/media",
        files={"file":((file.filename or "inspection-photo")[:100],raw,content_type)})
    media_id=str(media["id"])
    _service_request("POST",f"/api/v1/visual/sessions/{session_id}/media/{media_id}")
    return {"session_id":session_id,"media_id":media_id,"status":"UPLOADED",
            "location":location["canonical_name"],"bytes":len(raw),
            "message":"Photo stored privately. AI analysis has NOT started."}


class AnalyzeConsent(BaseModel):
    session_id:uuid.UUID
    media_id:uuid.UUID
    consent_to_external_ai_processing:bool


@app.post("/api/memory/visual/inspection-analyze")
def inspection_analyze(body:AnalyzeConsent,m=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    _ready(s)
    if body.consent_to_external_ai_processing is not True:
        raise HTTPException(422,"Explicit consent is required to send household images to an external AI provider")
    house=_uuid(m.household_id)
    attached=_run(s,"""SELECT vs.id,vs.expected_location_id FROM visual_sessions vs
       JOIN visual_session_media sm ON sm.household_id=vs.household_id AND sm.session_id=vs.id
       WHERE vs.household_id=:house AND vs.id=:session AND sm.media_id=:media
         AND vs.status='OPEN'""",
         house=house,session=body.session_id,media=body.media_id).mappings().first()
    if not attached:
        raise HTTPException(404,"Photo is not attached to an open household inspection")
    _location(s,house,attached["expected_location_id"])
    outcome=_service_request("POST",f"/api/v1/visual/sessions/{body.session_id}/analyze/{body.media_id}")
    return {"session_id":str(body.session_id),"media_id":str(body.media_id),
            "status":outcome.get("status"),"run_id":str(outcome.get("run_id")),
            "summary":outcome.get("summary",{}),
            "message":"AI proposals are ready for owner verification; no confirmed facts were changed."}
