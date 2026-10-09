"""Owner review of visual observations. M2C operational assets remain authoritative.

One transaction updates operational records, evidence-backed graph assertions,
review decisions and audit. No vision model output is automatically promoted.
"""
import json
import os
from pathlib import Path
import uuid
from typing import Literal

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.main import app, actor, db, require_owner, audit, Asset, Room, Zone, uid
from app.memory_bridge import supported, project, _run, _uuid


class VisualDecision(BaseModel):
    decision: Literal["REJECT", "VERIFY_ONLY", "REGISTER_ASSET", "CONFIRM_LOCATION"]
    corrected_name: str | None = Field(default=None, min_length=2, max_length=120)
    location_entity_id: uuid.UUID | None = None
    asset_id: str | None = Field(default=None, max_length=80)
    asset_type: Literal["appliance", "furniture", "fixture", "equipment", "other"] = "appliance"
    note: str = Field(default="", max_length=600)


def _require_review_tables(s: Session):
    if not supported(s):
        raise HTTPException(503, "Home Memory PostgreSQL integration is not enabled")
    available = _run(s, "SELECT to_regclass('public.memory_visual_resolutions')").scalar_one()
    if not available:
        raise HTTPException(503, "Home Memory migration 005_visual_review.sql is required")


def _verified_descendant(s: Session, house, root, candidate) -> bool:
    if root == candidate:
        return True
    return bool(_run(s, """WITH RECURSIVE places(id,path) AS (
      SELECT CAST(:root AS uuid), ARRAY[CAST(:root AS uuid)]
      UNION ALL
      SELECT a.subject_id, places.path || a.subject_id
      FROM memory_assertions a JOIN places ON a.object_id=places.id
      JOIN memory_entities e ON e.id=a.subject_id AND e.household_id=a.household_id
      WHERE a.household_id=:house AND a.predicate IN ('PART_OF','LOCATED_IN')
       AND a.verification_status='CONFIRMED' AND a.valid_until IS NULL
       AND e.status='ACTIVE' AND NOT a.subject_id=ANY(places.path)
    ) SELECT 1 FROM places WHERE id=:candidate LIMIT 1""",
      root=root, house=house, candidate=candidate).first())


def _mapped_location(s: Session, house, location_id):
    row = _run(s, """SELECT l.legacy_type,l.legacy_id,e.canonical_name
      FROM memory_legacy_links l
      JOIN memory_entities e ON e.id=l.entity_id AND e.household_id=l.household_id
      WHERE l.household_id=:house AND l.entity_id=:id
      AND l.legacy_type IN ('room','zone') AND e.status='ACTIVE'""",
      house=house,id=location_id).mappings().first()
    if not row:
        raise HTTPException(422,"Location must be a synchronized M2C room or zone")
    return row


def _location_for_asset(s, m, mapped):
    if mapped["legacy_type"] == "room":
        room = s.get(Room, mapped["legacy_id"])
        if not room or room.household_id != m.household_id:
            raise HTTPException(422,"Selected room is not active in this household")
        return room.id, None
    zone = s.get(Zone, mapped["legacy_id"])
    if not zone or zone.household_id != m.household_id:
        raise HTTPException(422,"Selected zone is not active in this household")
    room = s.get(Room, zone.room_id)
    if not room or room.household_id != m.household_id:
        raise HTTPException(422,"Zone does not belong to an active room")
    return room.id, zone.id


def _visual_observation(s, house, observation_id, *, lock=False):
    # Only evidence attached to an inspected media analysis can update house records.
    # A model-provided expected_location_id in its payload is never authoritative.
    return _run(s, """SELECT o.id,o.status,o.media_id,o.subject_id,o.payload,o.confidence,
      o.frame_timestamp_ms,o.model_version,src.source_type,
      vs.expected_location_id,room.canonical_name AS inspected_location,
      l.legacy_id AS matched_legacy_asset_id
      FROM memory_observations o
      JOIN memory_evidence src ON src.id=o.evidence_id AND src.household_id=o.household_id
      LEFT JOIN visual_analysis_runs r ON r.id=o.analysis_run_id AND r.household_id=o.household_id
      LEFT JOIN visual_analysis_findings f ON f.observation_id=o.id AND f.household_id=o.household_id
      LEFT JOIN visual_analysis_jobs j ON j.id=f.job_id AND j.household_id=f.household_id
      JOIN visual_sessions vs ON vs.id=COALESCE(r.session_id,j.session_id)
        AND vs.household_id=o.household_id
      JOIN visual_session_media sm ON sm.household_id=o.household_id
        AND sm.session_id=vs.id AND sm.media_id=o.media_id
      JOIN memory_entities room ON room.id=vs.expected_location_id AND room.household_id=o.household_id
      LEFT JOIN memory_legacy_links l ON l.entity_id=o.subject_id
        AND l.household_id=o.household_id AND l.legacy_type='asset'
      WHERE o.household_id=:house AND o.id=:observation
        AND o.media_id IS NOT NULL AND src.source_type IN ('PHOTO','VIDEO')
      """ + (" FOR UPDATE OF o" if lock else ""),
      house=house,observation=observation_id).mappings().first()


def _allowed_locations(s, house, inspected_id):
    records = _run(s, """WITH RECURSIVE places(id,path) AS (
      SELECT CAST(:root AS uuid), ARRAY[CAST(:root AS uuid)]
      UNION ALL
      SELECT a.subject_id, places.path || a.subject_id FROM memory_assertions a
      JOIN places ON a.object_id=places.id
      WHERE a.household_id=:house AND a.predicate IN ('PART_OF','LOCATED_IN')
        AND a.verification_status='CONFIRMED' AND a.valid_until IS NULL
        AND NOT a.subject_id=ANY(places.path)
    )
    SELECT l.entity_id,l.legacy_type,l.legacy_id,e.canonical_name
    FROM memory_legacy_links l
    JOIN memory_entities e ON e.household_id=l.household_id AND e.id=l.entity_id
    WHERE l.household_id=:house AND l.legacy_type IN ('room','zone')
      AND l.entity_id IN (SELECT id FROM places) AND e.status='ACTIVE'
    ORDER BY CASE WHEN l.legacy_type='room' THEN 0 ELSE 1 END,e.canonical_name""",
       house=house,root=inspected_id).mappings().all()
    return [{"id":str(x["entity_id"]),"name":x["canonical_name"],"type":x["legacy_type"]}
            for x in records]


@app.get("/api/memory/visual/pending")
def pending_visual_reviews(m=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    _require_review_tables(s)
    house=_uuid(m.household_id)
    rows=_run(s, """SELECT o.id,o.subject_id,o.media_id,o.payload,o.confidence,
      o.frame_timestamp_ms,o.model_version,o.observed_at,
      vs.expected_location_id,loc.canonical_name AS inspected_location,
      l.legacy_id AS matched_legacy_asset_id
      FROM memory_observations o
      JOIN memory_evidence src ON src.id=o.evidence_id AND src.household_id=o.household_id
      LEFT JOIN visual_analysis_runs r ON r.id=o.analysis_run_id AND r.household_id=o.household_id
      LEFT JOIN visual_analysis_findings f ON f.observation_id=o.id AND f.household_id=o.household_id
      LEFT JOIN visual_analysis_jobs j ON j.id=f.job_id AND j.household_id=f.household_id
      JOIN visual_sessions vs ON vs.id=COALESCE(r.session_id,j.session_id)
         AND vs.household_id=o.household_id
      JOIN visual_session_media sm ON sm.household_id=o.household_id
         AND sm.session_id=vs.id AND sm.media_id=o.media_id
      JOIN memory_entities loc ON loc.id=vs.expected_location_id AND loc.household_id=o.household_id
      LEFT JOIN memory_legacy_links l ON l.entity_id=o.subject_id AND l.household_id=o.household_id
         AND l.legacy_type='asset'
      WHERE o.household_id=:house AND o.status='PENDING'
        AND o.media_id IS NOT NULL AND src.source_type IN ('PHOTO','VIDEO')
      ORDER BY o.observed_at DESC,o.id DESC LIMIT 60""",house=house).mappings().all()
    locations={}
    items=[]
    for row in rows:
        root=row["expected_location_id"]
        if root not in locations:
            locations[root]=_allowed_locations(s,house,root)
        payload=row["payload"] or {}
        label=str(payload.get("label") or payload.get("finding_type") or "Unidentified visual finding")
        desc=str(payload.get("description") or payload.get("summary") or "")[:300]
        items.append({
           "id":str(row["id"]),"label":label[:120],"description":desc,
           "confidence":float(row["confidence"]) if row["confidence"] is not None else None,
           "media_id":str(row["media_id"]),"frame_timestamp_ms":row["frame_timestamp_ms"],
           "model_version":row["model_version"],
           "inspected_location":row["inspected_location"],
           "expected_location_id":str(root),
           "matched_legacy_asset_id":row["matched_legacy_asset_id"],
           "locations":locations[root],
           "observed_at":row["observed_at"].isoformat(),
        })
    assets=s.query(Asset).filter(Asset.household_id==m.household_id).order_by(Asset.name).limit(300).all()
    return {"observations":items,"assets":[{"id":a.id,"name":a.name} for a in assets]}


def _confirm_asset_location(s,house,entity_id,location_id,observation_id,m):
    # Serialize updates to this asset; temporal supersession remains auditable.
    _run(s, """SELECT id FROM memory_entities WHERE household_id=:house AND id=:id FOR UPDATE""",
         house=house,id=entity_id).first()
    old=_run(s, """SELECT id,object_id,valid_from FROM memory_assertions WHERE
       household_id=:house AND subject_id=:id AND predicate='LOCATED_IN'
       AND verification_status='CONFIRMED' AND valid_until IS NULL
       FOR UPDATE""",house=house,id=entity_id).mappings().first()
    ref=f"visual-review:{observation_id}"
    ev=_run(s, """INSERT INTO memory_evidence(household_id,source_type,source_ref,metadata)
       VALUES(:house,'OWNER',:ref,CAST(:meta AS jsonb)) RETURNING id""",
       house=house,ref=ref,meta=json.dumps({"reviewer_member_id":m.id,"observation_id":str(observation_id)})).scalar_one()
    if not old or old["object_id"] != location_id:
        if old:
            _run(s, """UPDATE memory_assertions SET verification_status='SUPERSEDED',
               valid_until=GREATEST(clock_timestamp(),valid_from + interval '1 microsecond')
               WHERE household_id=:house AND id=:id""",house=house,id=old["id"])
        _run(s, """INSERT INTO memory_assertions
           (household_id,subject_id,predicate,object_id,evidence_id,verification_status,supersedes_id)
           VALUES(:house,:subject,'LOCATED_IN',:location,:ev,'CONFIRMED',:previous)""",
           house=house,subject=entity_id,location=location_id,ev=ev,
           previous=old["id"] if old else None)
    detail={"observation_id":str(observation_id),"from":str(old["object_id"]) if old else None,
            "to":str(location_id),"reviewer_member_id":m.id,
            "same_location":bool(old and old["object_id"]==location_id)}
    _run(s, """INSERT INTO memory_events
       (household_id,event_type,subject_id,payload,idempotency_key)
       VALUES(:house,'VISUAL_LOCATION_VERIFIED',:subject,CAST(:payload AS jsonb),:key)""",
       house=house,subject=entity_id,payload=json.dumps(detail),key=ref)


@app.post("/api/memory/visual/{observation_id}/resolve")
def resolve_visual_review(observation_id:uuid.UUID,body:VisualDecision,
                          m=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    _require_review_tables(s)
    house=_uuid(m.household_id)
    obs=_visual_observation(s,house,observation_id,lock=True)
    if not obs or obs["status"]!="PENDING":
        raise HTTPException(409,"Observation is unavailable or has already been reviewed")
    resolved_asset=None
    graph_entity=None
    location_id=None
    if body.decision in ("REGISTER_ASSET","CONFIRM_LOCATION"):
        if not body.location_entity_id:
            raise HTTPException(422,"Select a verified room or zone")
        location_id=body.location_entity_id
        if not _verified_descendant(s,house,obs["expected_location_id"],location_id):
            raise HTTPException(422,"Selected location is outside the inspection")
        mapped=_mapped_location(s,house,location_id)
        room_id,zone_id=_location_for_asset(s,m,mapped)
        if body.decision=="REGISTER_ASSET":
            # Explicit owner-entered name; AI label alone cannot register a new asset.
            name=(body.corrected_name or "").strip()
            if len(name)<2:
                raise HTTPException(422,"Enter and verify the asset name")
            asset=Asset(id=uid(),household_id=m.household_id,room_id=room_id,
                        zone_id=zone_id,name=name,asset_type=body.asset_type,status="OK")
            s.add(asset)
            s.flush()
            project(s,m.household_id)
        else:
            if not body.asset_id:
                raise HTTPException(422,"Select an existing registered asset")
            asset=s.get(Asset,body.asset_id)
            if not asset or asset.household_id!=m.household_id:
                raise HTTPException(404,"Asset not found in this household")
            asset.room_id=room_id
            asset.zone_id=zone_id
            s.flush()
            # If this is an old unlinked asset, establish its graph link first.
            existing=_run(s, """SELECT entity_id FROM memory_legacy_links
               WHERE household_id=:house AND legacy_type='asset' AND legacy_id=:legacy""",
               house=house,legacy=asset.id).scalar_one_or_none()
            if existing is None:
                project(s,m.household_id)
        graph_entity=_run(s, """SELECT entity_id FROM memory_legacy_links
            WHERE household_id=:house AND legacy_type='asset' AND legacy_id=:legacy""",
            house=house,legacy=asset.id).scalar_one_or_none()
        if graph_entity is None:
            raise HTTPException(409,"Asset must be synchronized to Home Memory before review")
        _confirm_asset_location(s,house,graph_entity,location_id,observation_id,m)
        # Replicate the newly verified operational location without overwriting the owner.
        project(s,m.household_id)
        resolved_asset=asset.id
    _run(s, """UPDATE memory_observations SET status=:status,review_reason=:reason
       WHERE household_id=:house AND id=:id AND status='PENDING'""",
       status="REJECTED" if body.decision=="REJECT" else "ACCEPTED",
       reason=body.note or body.decision,house=house,id=observation_id)
    _run(s, """INSERT INTO memory_visual_resolutions
       (household_id,observation_id,reviewer_member_id,decision,
        asset_legacy_id,graph_entity_id,location_entity_id,corrected_name,review_note)
       VALUES(:house,:observation,:reviewer,:decision,:asset,:entity,:location,:name,:note)""",
       house=house,observation=observation_id,reviewer=m.id,
       decision=body.decision,asset=resolved_asset,entity=graph_entity,
       location=location_id,name=(body.corrected_name or "").strip() or None,
       note=body.note)
    audit(s,m,"memory.visual.review",f"{observation_id}:{body.decision}")
    s.commit()
    return {"observation_id":str(observation_id),"decision":body.decision,
            "status":"REJECTED" if body.decision=="REJECT" else "ACCEPTED",
            "asset_id":resolved_asset,"graph_entity_id":str(graph_entity) if graph_entity else None,
            "location_entity_id":str(location_id) if location_id else None}

@app.get("/api/memory/visual/{observation_id}/evidence")
def read_visual_evidence(observation_id:uuid.UUID,m=Depends(actor),s:Session=Depends(db)):
    """Owner-only authenticated media access. Raw media never gets a public URL."""
    require_owner(m)
    _require_review_tables(s)
    house=_uuid(m.household_id)
    obs=_visual_observation(s,house,observation_id)
    if not obs:
        raise HTTPException(404,"Visual observation evidence not found")
    media=_run(s, """SELECT storage_key,content_type,byte_size FROM memory_media
      WHERE household_id=:house AND id=:id""",house=house,id=obs["media_id"]).mappings().first()
    if not media:
        raise HTTPException(404,"Media metadata not found")
    if media["content_type"] not in ("image/jpeg","image/png","image/webp","video/mp4","video/quicktime"):
        raise HTTPException(415,"Unsupported media")
    root=Path(os.getenv("HOMEOS_PRIVATE_MEMORY_MEDIA_ROOT","/srv/homeos/private_memory_media")).resolve()
    path=(root / media["storage_key"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404,"Private evidence file unavailable; mount read-only memory media storage")
    return FileResponse(path,media_type=media["content_type"],
        headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff",
                 "Content-Disposition":"inline; filename=evidence"})
