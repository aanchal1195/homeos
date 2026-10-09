"""Validate that a vision worker still owns the live job lease."""
from datetime import datetime,timezone
from multimodal_provider import ProviderError

def guard(conn,house,job):
    row=conn.execute(
        """SELECT j.status,j.lease_token,j.lease_expires_at,j.media_id,
                  j.analyzer_name,j.analyzer_version,s.expected_location_id,m.content_type
           FROM visual_analysis_jobs j
           JOIN visual_sessions s ON s.household_id=j.household_id AND s.id=j.session_id
           JOIN memory_media m ON m.household_id=j.household_id AND m.id=j.media_id
           WHERE j.household_id=%s AND j.id=%s FOR UPDATE OF j""",
        (house,job["id"])).fetchone()
    if not row:
        raise ProviderError("JOB_NOT_FOUND",retryable=False)
    if row["status"]=="COMPLETED":
        return row
    if (row["status"]!="ANALYZING" or row["lease_token"]!=job["lease_token"]
        or row["lease_expires_at"]<=datetime.now(timezone.utc)):
        raise ProviderError("STALE_WORKER_LEASE",retryable=False)
    return row
