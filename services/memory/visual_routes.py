"""Private photo/video upload and evidence coverage for HomeOS memory.
M3B does not perform AI inference; observations must be reviewed separately.
"""
import hashlib
import os
import pathlib
import secrets
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from app import db, identity, need_entity

router = APIRouter(prefix="/api/v1/visual", tags=["Visual memory"])
ALLOWED = {"image/jpeg", "image/png", "image/webp", "video/mp4", "video/quicktime"}
EXT = {"image/jpeg":"jpg", "image/png":"png", "image/webp":"webp",
       "video/mp4":"mp4", "video/quicktime":"mov"}
MAX_DEFAULT = 25 * 1024 * 1024

def max_bytes():
    return min(int(os.getenv("MAX_MEDIA_BYTES",str(MAX_DEFAULT))), 200*1024*1024)

def signature_matches(data: bytes, mime: str) -> bool:
    if mime == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/webp":
        return len(data)>12 and data[:4]==b"RIFF" and data[8:12]==b"WEBP"
    if mime in ("video/mp4","video/quicktime"):
        return len(data)>=12 and data[4:8]==b"ftyp"
    return False

class SessionIn(BaseModel):
    session_type: Literal["WEEKLY_WALKTHROUGH","TASK_VERIFICATION","INVENTORY_SCAN","ISSUE_REPORT","ASSET_REGISTRATION"]
    expected_location_id: uuid.UUID

class CoverageIn(BaseModel):
    location_id: uuid.UUID
    coverage_status: Literal["NOT_OBSERVED","PARTIAL","OBSERVED","UNVERIFIED"]
    media_id: uuid.UUID | None = None
    notes: str | None = None

def need_session(conn, house, sid):
    s=conn.execute("SELECT * FROM visual_sessions WHERE household_id=%s AND id=%s",(house,sid)).fetchone()
    if s is None: raise HTTPException(404,"Visual session not found")
    return s

@router.post("/sessions",status_code=201)
def create_session(body: SessionIn, house=Depends(identity)):
    with db() as conn:
        entity=need_entity(conn,house,body.expected_location_id)
        if entity["entity_type"] not in ("ROOM","SPACE","ZONE","FLOOR"):
            raise HTTPException(422,"Session must belong to a registered location")
        row=conn.execute("""INSERT INTO visual_sessions(household_id,session_type,expected_location_id)
                VALUES(%s,%s,%s) RETURNING id,status""",
                (house,body.session_type,body.expected_location_id)).fetchone()
        return row

@router.post("/media",status_code=201)
async def upload(file: UploadFile=File(...), house=Depends(identity)):
    mime=(file.content_type or "").lower()
    if mime not in ALLOWED:
        raise HTTPException(415,"Unsupported media type")
    cap=max_bytes()
    # Read bounded bytes to avoid unbounded memory allocations.
    blob=await file.read(cap+1)
    if not blob or len(blob)>cap: raise HTTPException(413,"Empty or oversized file")
    if not signature_matches(blob,mime): raise HTTPException(415,"Content signature does not match declared media type")
    digest=hashlib.sha256(blob).hexdigest()
    media_id=uuid.uuid4()
    # Relative, non-user-controlled storage path; file names are never trusted.
    key=f"{house}/{media_id.hex}.{EXT[mime]}"
    root=pathlib.Path(os.getenv("PRIVATE_MEDIA_ROOT","/srv/memory/private_media"))
    path=root / key
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:
        with open(path,"xb") as handle:
            handle.write(blob)
        os.chmod(path,0o600)
        with db() as conn:
            conn.execute("""INSERT INTO memory_media
               (id,household_id,sha256,storage_key,content_type,byte_size,original_filename)
               VALUES(%s,%s,%s,%s,%s,%s,%s)""",
               (media_id,house,digest,key,mime,len(blob),(file.filename or "")[:255]))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"id":media_id,"content_type":mime,"bytes":len(blob),"sha256":digest}

@router.post("/sessions/{session_id}/media/{media_id}",status_code=201)
def attach_media(session_id:uuid.UUID,media_id:uuid.UUID,house=Depends(identity)):
    with db() as conn:
        session=need_session(conn,house,session_id)
        if session["status"]!="OPEN": raise HTTPException(409,"Session closed")
        exists=conn.execute("SELECT id FROM memory_media WHERE household_id=%s AND id=%s",(house,media_id)).fetchone()
        if not exists: raise HTTPException(404,"Media not found")
        conn.execute("""INSERT INTO visual_session_media(household_id,session_id,media_id)
         VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""",(house,session_id,media_id))
        return {"session_id":session_id,"media_id":media_id}

@router.post("/sessions/{session_id}/coverage")
def coverage(session_id:uuid.UUID,body:CoverageIn,house=Depends(identity)):
    with db() as conn:
        session=need_session(conn,house,session_id)
        if session["status"]!="OPEN": raise HTTPException(409,"Session closed")
        need_entity(conn,house,body.location_id)
        if body.media_id:
            attached=conn.execute("""SELECT 1 FROM visual_session_media
              WHERE household_id=%s AND session_id=%s AND media_id=%s""",
              (house,session_id,body.media_id)).fetchone()
            if not attached: raise HTTPException(422,"Evidence must be attached to session")
        result=conn.execute("""INSERT INTO visual_coverage(household_id,session_id,location_id,coverage_status,evidence_media_id,notes)
          VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(household_id,session_id,location_id)
          DO UPDATE SET coverage_status=excluded.coverage_status,evidence_media_id=excluded.evidence_media_id,
             notes=excluded.notes,recorded_at=now()
          RETURNING id,coverage_status""",
          (house,session_id,body.location_id,body.coverage_status,body.media_id,body.notes)).fetchone()
        return result

@router.get("/sessions/{session_id}")
def session_details(session_id:uuid.UUID,house=Depends(identity)):
    with db() as conn:
        s=need_session(conn,house,session_id)
        media=conn.execute("""SELECT m.id,m.content_type,m.byte_size,m.created_at
            FROM visual_session_media sm JOIN memory_media m ON m.id=sm.media_id AND m.household_id=sm.household_id
            WHERE sm.household_id=%s AND sm.session_id=%s""",(house,session_id)).fetchall()
        covers=conn.execute("""SELECT location_id,coverage_status,evidence_media_id,notes
            FROM visual_coverage WHERE household_id=%s AND session_id=%s""",(house,session_id)).fetchall()
        return {"session":s,"media":media,"coverage":covers}
