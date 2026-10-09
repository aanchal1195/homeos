"""Durable job leases and private frame integrity for M3D vision workers."""
import hashlib
import uuid
from app import db
from multimodal_provider import ProviderError
from visual_analysis_routes import _safe_media_path

MAX_FRAMES=12
MAX_FRAME_BYTES=2_000_000
MAX_TOTAL_BYTES=12_000_000
MAX_ATTEMPTS=3

def claim_job(house,model):
    with db() as conn:
        row=conn.execute(
            """SELECT id FROM visual_analysis_jobs
               WHERE household_id=%s AND analyzer_name='openai' AND analyzer_version=%s
                 AND attempt_count<%s
                 AND ((status='FRAMES_READY' AND
                      (next_attempt_at IS NULL OR next_attempt_at<=now()))
                   OR (status='ANALYZING' AND lease_expires_at<now()))
               ORDER BY requested_at,id FOR UPDATE SKIP LOCKED LIMIT 1""",
            (house,model,MAX_ATTEMPTS)).fetchone()
        if not row:
            return None
        return conn.execute(
            """UPDATE visual_analysis_jobs SET status='ANALYZING',
                 attempt_count=attempt_count+1,lease_token=%s,
                 lease_expires_at=now()+interval '300 seconds',
                 started_at=coalesce(started_at,now()),
                 error_code=NULL,error_detail=NULL
               WHERE household_id=%s AND id=%s
               RETURNING id,session_id,media_id,attempt_count,lease_token""",
            (uuid.uuid4(),house,row["id"])).fetchone()

def read_frames(house,job):
    with db() as conn:
        loc=conn.execute(
            """SELECT e.canonical_name FROM visual_analysis_jobs j
               JOIN visual_sessions s ON s.household_id=j.household_id AND s.id=j.session_id
               JOIN memory_entities e ON e.household_id=s.household_id AND e.id=s.expected_location_id
               WHERE j.household_id=%s AND j.id=%s""",
            (house,job["id"])).fetchone()
        rows=conn.execute(
            """SELECT id,frame_timestamp_ms,storage_key,sha256,byte_size
               FROM visual_frames WHERE household_id=%s AND job_id=%s
               ORDER BY frame_timestamp_ms,id""",
            (house,job["id"])).fetchall()
    if not loc or not 1<=len(rows)<=MAX_FRAMES:
        raise ProviderError("INVALID_JOB_FRAMES",retryable=False)
    total=0
    frames=[]
    for row in rows:
        if not 0<row["byte_size"]<=MAX_FRAME_BYTES:
            raise ProviderError("FRAME_SIZE_INVALID",retryable=False)
        try:
            path=_safe_media_path(row["storage_key"])
            if not path.is_file():
                raise ProviderError("FRAME_MISSING",retryable=False)
            data=path.read_bytes()
        except (OSError,ValueError) as exc:
            raise ProviderError("FRAME_UNREADABLE",retryable=False) from exc
        total+=len(data)
        if (len(data)!=row["byte_size"] or total>MAX_TOTAL_BYTES or
                hashlib.sha256(data).hexdigest()!=row["sha256"]):
            raise ProviderError("FRAME_INTEGRITY_FAILED",retryable=False)
        frames.append((row["id"],row["frame_timestamp_ms"],data))
    return loc["canonical_name"],frames

def record_failure(house,job,error):
    retry=error.retryable and job["attempt_count"]<MAX_ATTEMPTS
    delay=min(60*2**(job["attempt_count"]-1),600)
    with db() as conn:
        row=conn.execute(
            """UPDATE visual_analysis_jobs
               SET status=CASE WHEN %s THEN 'FRAMES_READY' ELSE 'FAILED' END,
                 next_attempt_at=CASE WHEN %s THEN now()+(%s*interval '1 second') ELSE NULL END,
                 lease_token=NULL,lease_expires_at=NULL,
                 finished_at=CASE WHEN %s THEN NULL ELSE now() END,
                 error_code=%s,error_detail=NULL
               WHERE household_id=%s AND id=%s AND status='ANALYZING'
                 AND lease_token=%s RETURNING status""",
            (retry,retry,delay,retry,error.code,house,job["id"],job["lease_token"])
        ).fetchone()
    return row["status"] if row else None
