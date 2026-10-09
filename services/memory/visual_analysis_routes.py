"""M3C visual-analysis pipeline.

Owner APIs queue and inspect jobs. A separate worker token prepares bounded image
frames and publishes structured findings. Findings are staged as PENDING memory
observations; this module never mutates confirmed graph assertions.
"""
import hashlib
import io
import os
import pathlib
import subprocess
import uuid
from secrets import compare_digest
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from PIL import Image, ImageOps, UnidentifiedImageError
from psycopg.types.json import Jsonb

from app import db, identity, need_entity, evidence_insert

router = APIRouter(prefix="/api/v1/visual", tags=["Visual analysis"])

MAX_FRAME_COUNT = 12
DEFAULT_FRAME_COUNT = 6
MAX_FRAME_EDGE = 1600

def worker_identity(authorization: str | None = Header(default=None)):
    token = os.getenv("HOMEOS_WORKER_TOKEN", "")
    household = os.getenv("HOMEOS_HOUSEHOLD_ID", "")
    if not token or token == os.getenv("HOMEOS_API_TOKEN") or not household or not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Unauthorized worker")
    if not compare_digest(authorization[7:], token):
        raise HTTPException(401, "Unauthorized worker")
    try:
        return str(uuid.UUID(household))
    except ValueError:
        raise HTTPException(503, "Invalid server household configuration")

class AnalysisRequest(BaseModel):
    media_id: uuid.UUID
    analyzer_name: str = Field(min_length=1, max_length=100)
    analyzer_version: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=200)

class PrepareRequest(BaseModel):
    frame_count: int = Field(default=DEFAULT_FRAME_COUNT, ge=1, le=MAX_FRAME_COUNT)

class FindingIn(BaseModel):
    frame_id: uuid.UUID
    finding_type: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1000)
    severity: Literal["INFO","LOW","MEDIUM","HIGH","CRITICAL"] = "INFO"
    confidence: float = Field(ge=0, le=1)
    subject_id: uuid.UUID | None = None
    candidate_object_id: uuid.UUID | None = None
    predicate: str | None = Field(default=None, max_length=100)
    payload: dict = Field(default_factory=dict)

class FindingsIn(BaseModel):
    findings: list[FindingIn] = Field(min_length=1, max_length=100)

def _need_job(conn, house, job_id, *, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    row = conn.execute(
        "SELECT * FROM visual_analysis_jobs WHERE household_id=%s AND id=%s" + suffix,
        (house, job_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Analysis job not found")
    return row

def _need_session(conn, house, session_id):
    row = conn.execute(
        "SELECT * FROM visual_sessions WHERE household_id=%s AND id=%s",
        (house, session_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Visual session not found")
    return row

def _private_root():
    return pathlib.Path(os.getenv("PRIVATE_MEDIA_ROOT", "/srv/memory/private_media"))

def _safe_media_path(storage_key: str):
    root = _private_root().resolve()
    path = (root / storage_key).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(500, "Invalid media storage path")
    return path

def _encode_frame(img: Image.Image) -> tuple[bytes, int, int]:
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_FRAME_EDGE, MAX_FRAME_EDGE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue(), img.width, img.height

def _write_frame(house: str, job_id: uuid.UUID, timestamp_ms: int, data: bytes):
    frame_id = uuid.uuid4()
    key = f"{house}/frames/{job_id.hex}/{frame_id.hex}.jpg"
    path = _safe_media_path(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, "xb") as handle:
        handle.write(data)
    os.chmod(path, 0o600)
    return frame_id, key, path, hashlib.sha256(data).hexdigest()

def _image_frame(path: pathlib.Path):
    try:
        with Image.open(path) as img:
            return _encode_frame(img)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise RuntimeError("IMAGE_DECODE_FAILED")

def _video_duration_seconds(path: pathlib.Path) -> float:
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True, text=True,
        )
        duration = float(probe.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
        raise RuntimeError("VIDEO_PROBE_FAILED")
    if duration <= 0 or duration > 6 * 60 * 60:
        raise RuntimeError("VIDEO_DURATION_INVALID")
    return duration

def _video_frame(path: pathlib.Path, timestamp_seconds: float):
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-ss", f"{timestamp_seconds:.3f}", "-i", str(path), "-frames:v", "1",
             "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        raise RuntimeError("VIDEO_FRAME_EXTRACTION_FAILED")
    if not result.stdout:
        raise RuntimeError("VIDEO_FRAME_EXTRACTION_FAILED")
    try:
        with Image.open(io.BytesIO(result.stdout)) as img:
            return _encode_frame(img)
    except (UnidentifiedImageError, OSError, ValueError):
        raise RuntimeError("VIDEO_FRAME_DECODE_FAILED")

def _is_descendant(conn, house, root_id, candidate_id):
    if root_id == candidate_id:
        return True
    return bool(conn.execute(
        """WITH RECURSIVE children(id,path) AS (
          SELECT %s::uuid, ARRAY[%s::uuid]
          UNION ALL
          SELECT a.subject_id, children.path || a.subject_id
          FROM memory_assertions a JOIN children ON a.object_id=children.id
          WHERE a.household_id=%s AND a.predicate IN ('PART_OF','LOCATED_IN')
            AND a.verification_status='CONFIRMED' AND a.valid_until IS NULL
            AND NOT a.subject_id = ANY(children.path)
        ) SELECT 1 FROM children WHERE id=%s LIMIT 1""",
        (root_id, root_id, house, candidate_id),
    ).fetchone())

@router.post("/sessions/{session_id}/analysis", status_code=201)
def queue_analysis(session_id: uuid.UUID, body: AnalysisRequest, house=Depends(identity)):
    with db() as conn:
        session = _need_session(conn, house, session_id)
        if session["status"] not in ("OPEN", "SUBMITTED"):
            raise HTTPException(409, "Session is not available for analysis")
        attached = conn.execute(
            """SELECT 1 FROM visual_session_media
               WHERE household_id=%s AND session_id=%s AND media_id=%s""",
            (house, session_id, body.media_id),
        ).fetchone()
        if not attached:
            raise HTTPException(422, "Media must be attached to the session")
        existing = conn.execute(
            """SELECT id,status,session_id,media_id,analyzer_name,analyzer_version FROM visual_analysis_jobs
               WHERE household_id=%s AND idempotency_key=%s""",
            (house, body.idempotency_key),
        ).fetchone()
        if existing:
            if (existing["session_id"] != session_id or existing["media_id"] != body.media_id
                or existing["analyzer_name"] != body.analyzer_name.strip()
                or existing["analyzer_version"] != body.analyzer_version.strip()):
                raise HTTPException(409, "Idempotency key already belongs to a different analysis")
            return {"id": existing["id"], "status": existing["status"]}
        row = conn.execute(
            """INSERT INTO visual_analysis_jobs
               (household_id,session_id,media_id,analyzer_name,analyzer_version,idempotency_key)
               VALUES(%s,%s,%s,%s,%s,%s) RETURNING id,status""",
            (house, session_id, body.media_id, body.analyzer_name.strip(),
             body.analyzer_version.strip(), body.idempotency_key),
        ).fetchone()
        return row

@router.get("/analysis/jobs/{job_id}")
def get_analysis(job_id: uuid.UUID, house=Depends(identity)):
    with db() as conn:
        job = _need_job(conn, house, job_id)
        frames = conn.execute(
            """SELECT id,frame_timestamp_ms,width,height,byte_size,sha256,created_at
               FROM visual_frames WHERE household_id=%s AND job_id=%s
               ORDER BY frame_timestamp_ms""",
            (house, job_id),
        ).fetchall()
        findings = conn.execute(
            """SELECT id,frame_id,observation_id,finding_type,summary,severity,confidence,created_at
               FROM visual_analysis_findings WHERE household_id=%s AND job_id=%s
               ORDER BY created_at""",
            (house, job_id),
        ).fetchall()
        return {"job": job, "frames": frames, "findings": findings}

@router.post("/analysis/jobs/{job_id}/prepare")
def prepare_frames(job_id: uuid.UUID, body: PrepareRequest, house=Depends(worker_identity)):
    created_paths: list[pathlib.Path] = []
    try:
        with db() as conn:
            job = _need_job(conn, house, job_id, lock=True)
            if job["status"] == "FRAMES_READY":
                count = conn.execute(
                    "SELECT count(*) AS n FROM visual_frames WHERE household_id=%s AND job_id=%s",
                    (house, job_id),
                ).fetchone()["n"]
                return {"job_id": job_id, "status": "FRAMES_READY", "frames": count}
            if job["status"] != "QUEUED":
                raise HTTPException(409, f"Job cannot be prepared from {job['status']}")
            media = conn.execute(
                "SELECT * FROM memory_media WHERE household_id=%s AND id=%s",
                (house, job["media_id"]),
            ).fetchone()
            if not media:
                raise HTTPException(404, "Media not found")
            conn.execute(
                """UPDATE visual_analysis_jobs SET status='PROCESSING',started_at=now(),
                   error_code=NULL,error_detail=NULL WHERE household_id=%s AND id=%s""",
                (house, job_id),
            )

        media_path = _safe_media_path(media["storage_key"])
        if not media_path.is_file():
            raise RuntimeError("MEDIA_FILE_MISSING")

        frames: list[tuple[int, bytes, int, int]] = []
        if media["content_type"].startswith("image/"):
            data, width, height = _image_frame(media_path)
            frames.append((0, data, width, height))
        else:
            duration = _video_duration_seconds(media_path)
            count = min(body.frame_count, MAX_FRAME_COUNT)
            # Midpoints avoid over-weighting intro/outro frames and bound processing cost.
            for index in range(count):
                ts = duration * ((index + 0.5) / count)
                data, width, height = _video_frame(media_path, ts)
                frames.append((int(ts * 1000), data, width, height))

        persisted = []
        for timestamp_ms, data, width, height in frames:
            frame_id, key, path, digest = _write_frame(house, job_id, timestamp_ms, data)
            created_paths.append(path)
            persisted.append((frame_id, timestamp_ms, key, digest, len(data), width, height))

        with db() as conn:
            _need_job(conn, house, job_id, lock=True)
            for frame_id, timestamp_ms, key, digest, size, width, height in persisted:
                conn.execute(
                    """INSERT INTO visual_frames
                       (id,household_id,job_id,media_id,frame_timestamp_ms,storage_key,sha256,byte_size,width,height)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (frame_id, house, job_id, media["id"], timestamp_ms, key, digest,
                     size, width, height),
                )
            conn.execute(
                """UPDATE visual_analysis_jobs SET status='FRAMES_READY'
                   WHERE household_id=%s AND id=%s""",
                (house, job_id),
            )
        return {"job_id": job_id, "status": "FRAMES_READY", "frames": len(persisted)}
    except HTTPException:
        raise
    except Exception as exc:
        for path in created_paths:
            path.unlink(missing_ok=True)
        code = str(exc)[:100] if str(exc) else "FRAME_PREPARATION_FAILED"
        with db() as conn:
            conn.execute(
                """UPDATE visual_analysis_jobs
                   SET status='FAILED',finished_at=now(),error_code=%s,error_detail=%s
                   WHERE household_id=%s AND id=%s""",
                (code, repr(exc)[:1000], house, job_id),
            )
        raise HTTPException(422, f"Frame preparation failed: {code}")

@router.post("/analysis/jobs/{job_id}/findings")
def publish_findings(job_id: uuid.UUID, body: FindingsIn, house=Depends(worker_identity)):
    with db() as conn:
        job = _need_job(conn, house, job_id, lock=True)
        if job["status"] == "COMPLETED":
            existing = conn.execute(
                "SELECT count(*) AS n FROM visual_analysis_findings WHERE household_id=%s AND job_id=%s",
                (house, job_id),
            ).fetchone()["n"]
            return {"job_id": job_id, "status": "COMPLETED", "findings": existing}
        if job["status"] != "FRAMES_READY":
            raise HTTPException(409, "Frames must be prepared before findings are published")
        session = _need_session(conn, house, job["session_id"])
        media = conn.execute(
            "SELECT content_type FROM memory_media WHERE household_id=%s AND id=%s",
            (house, job["media_id"]),
        ).fetchone()
        source_type = "PHOTO" if media["content_type"].startswith("image/") else "VIDEO"

        inserted = []
        for finding in body.findings:
            frame = conn.execute(
                """SELECT id,frame_timestamp_ms FROM visual_frames
                   WHERE household_id=%s AND job_id=%s AND id=%s""",
                (house, job_id, finding.frame_id),
            ).fetchone()
            if not frame:
                raise HTTPException(422, "Finding frame does not belong to this job")
            subject_id = finding.subject_id or session["expected_location_id"]
            need_entity(conn, house, subject_id)
            if not _is_descendant(conn, house, session["expected_location_id"], subject_id):
                raise HTTPException(422, "Finding subject is outside the inspected location")
            if finding.candidate_object_id:
                need_entity(conn, house, finding.candidate_object_id)

            evidence = type("Evidence", (), {
                "source_type": source_type,
                "source_ref": f"visual-analysis:{job_id}",
            })()
            evidence_id = evidence_insert(conn, house, evidence)
            payload = dict(finding.payload)
            payload.update({
                "finding_type": finding.finding_type,
                "summary": finding.summary,
                "severity": finding.severity,
            })
            observation_id = conn.execute(
                """INSERT INTO memory_observations
                   (household_id,subject_id,candidate_object_id,predicate,evidence_id,payload,
                    confidence,media_id,frame_timestamp_ms,model_version)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (house, subject_id, finding.candidate_object_id, finding.predicate,
                 evidence_id, Jsonb(payload), finding.confidence, job["media_id"],
                 frame["frame_timestamp_ms"],
                 f"{job['analyzer_name']}:{job['analyzer_version']}"),
            ).fetchone()["id"]
            finding_id = conn.execute(
                """INSERT INTO visual_analysis_findings
                   (household_id,job_id,frame_id,observation_id,finding_type,summary,severity,confidence)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (house, job_id, frame["id"], observation_id, finding.finding_type,
                 finding.summary, finding.severity, finding.confidence),
            ).fetchone()["id"]
            inserted.append({"id": finding_id, "observation_id": observation_id})

        conn.execute(
            """UPDATE visual_analysis_jobs SET status='COMPLETED',finished_at=now()
               WHERE household_id=%s AND id=%s""",
            (house, job_id),
        )
        return {"job_id": job_id, "status": "COMPLETED", "findings": inserted}
