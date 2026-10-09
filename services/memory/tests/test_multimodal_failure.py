"""Worker backoff, integrity and stale-lease regression tests."""
import os
import uuid
import pytest
from app import db
from multimodal_provider import ProviderError,ModelResponse
from multimodal_processor import process_once
from multimodal_job_store import claim_job,record_failure
from multimodal_publisher import publish
from m3d_fixtures import auth,client,prepared,MODEL

def test_provider_error_backoff(client,auth,monkeypatch):
    _,jid=prepared(client,auth)
    house=os.environ["HOMEOS_HOUSEHOLD_ID"]
    def fail(*_):
        raise ProviderError("PROVIDER_REQUEST_OR_RESPONSE_INVALID")
    monkeypatch.setattr("multimodal_processor.infer",fail)
    outcome=process_once(house,MODEL)
    assert outcome["status"]=="FRAMES_READY"
    assert process_once(house,MODEL) is None
    job=client.get(f"/api/v1/visual/analysis/jobs/{jid}",headers=auth["owner"]).json()["job"]
    assert job["attempt_count"]==1 and job["next_attempt_at"]

def test_tampered_private_frame_fails_closed(client,auth):
    _,jid=prepared(client,auth)
    house=os.environ["HOMEOS_HOUSEHOLD_ID"]
    from visual_analysis_routes import _safe_media_path
    with db() as conn:
        frame=conn.execute("SELECT storage_key FROM visual_frames WHERE household_id=%s AND job_id=%s",(house,jid)).fetchone()
    _safe_media_path(frame["storage_key"]).write_bytes(b"tampered")
    outcome=process_once(house,MODEL)
    assert outcome["status"]=="FAILED" and outcome["error_code"]=="FRAME_INTEGRITY_FAILED"

def test_stale_lease_cannot_publish(client,auth):
    _,jid=prepared(client,auth)
    house=os.environ["HOMEOS_HOUSEHOLD_ID"]
    job=claim_job(house,MODEL)
    assert str(job["id"])==jid
    with db() as conn:
        conn.execute("UPDATE visual_analysis_jobs SET lease_token=%s WHERE household_id=%s AND id=%s",
                     (uuid.uuid4(),house,jid))
    with pytest.raises(ProviderError,match="STALE_WORKER_LEASE"):
        publish(house,job,[],ModelResponse(findings=[]))
    assert record_failure(house,job,ProviderError("OLD_WORKER")) is None
