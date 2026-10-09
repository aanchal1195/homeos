"""M3C integration tests for visual-analysis staging and worker boundaries."""
import io
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import app

@pytest.fixture
def auth():
    required=("DATABASE_URL","HOMEOS_API_TOKEN","HOMEOS_WORKER_TOKEN","HOMEOS_HOUSEHOLD_ID")
    if not all(os.environ.get(key) for key in required):
        pytest.skip("Missing dedicated integration configuration")
    return {
        "owner":{"Authorization":"Bearer "+os.environ["HOMEOS_API_TOKEN"]},
        "worker":{"Authorization":"Bearer "+os.environ["HOMEOS_WORKER_TOKEN"]},
    }

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVATE_MEDIA_ROOT",str(tmp_path))
    return TestClient(app)

def _room(client, owner):
    response=client.post("/api/v1/memory/entities",headers=owner,json={
        "entity_type":"ROOM","canonical_name":"M3C Room "+uuid.uuid4().hex[:12]})
    assert response.status_code==201,response.text
    return response.json()["id"]

def _png():
    image=Image.new("RGB",(32,24),color=(120,140,160))
    out=io.BytesIO()
    image.save(out,format="PNG")
    return out.getvalue()

def _session_media(client, owner):
    room_id=_room(client,owner)
    session=client.post("/api/v1/visual/sessions",headers=owner,json={
        "session_type":"WEEKLY_WALKTHROUGH","expected_location_id":room_id})
    assert session.status_code==201,session.text
    sid=session.json()["id"]
    upload=client.post("/api/v1/visual/media",headers=owner,files={
        "file":("room.png",_png(),"image/png")})
    assert upload.status_code==201,upload.text
    mid=upload.json()["id"]
    attached=client.post(f"/api/v1/visual/sessions/{sid}/media/{mid}",headers=owner)
    assert attached.status_code==201,attached.text
    return room_id,sid,mid

def test_owner_queues_worker_prepares_and_findings_remain_pending(client,auth):
    owner,worker=auth["owner"],auth["worker"]
    room_id,sid,mid=_session_media(client,owner)
    queued=client.post(f"/api/v1/visual/sessions/{sid}/analysis",headers=owner,json={
        "media_id":mid,"analyzer_name":"test-analyzer","analyzer_version":"1",
        "idempotency_key":"m3c-"+uuid.uuid4().hex})
    assert queued.status_code==201,queued.text
    job_id=queued.json()["id"]

    assert client.post(f"/api/v1/visual/analysis/jobs/{job_id}/prepare",
        headers=owner,json={"frame_count":1}).status_code==401

    prepared=client.post(f"/api/v1/visual/analysis/jobs/{job_id}/prepare",
        headers=worker,json={"frame_count":1})
    assert prepared.status_code==200,prepared.text
    assert prepared.json()["status"]=="FRAMES_READY"
    assert prepared.json()["frames"]==1

    details=client.get(f"/api/v1/visual/analysis/jobs/{job_id}",headers=owner)
    assert details.status_code==200,details.text
    frame_id=details.json()["frames"][0]["id"]
    assert details.json()["frames"][0]["width"]==32
    assert details.json()["frames"][0]["height"]==24

    published=client.post(f"/api/v1/visual/analysis/jobs/{job_id}/findings",
        headers=worker,json={"findings":[{
            "frame_id":frame_id,
            "finding_type":"POSSIBLE_WATER_DAMAGE",
            "summary":"Possible discoloration near sink",
            "severity":"MEDIUM","confidence":0.72,
            "subject_id":room_id,
            "payload":{"requires_human_review":True}
        }]})
    assert published.status_code==200,published.text
    observation_id=published.json()["findings"][0]["observation_id"]

    with_details=client.get(f"/api/v1/visual/analysis/jobs/{job_id}",headers=owner)
    assert with_details.json()["job"]["status"]=="COMPLETED"
    assert with_details.json()["findings"][0]["observation_id"]==observation_id

    # A completed analysis produces a proposal, never a confirmed graph assertion.
    from app import db
    with db() as conn:
        observation=conn.execute(
            "SELECT review_status FROM memory_observations WHERE household_id=%s AND id=%s",
            (os.environ["HOMEOS_HOUSEHOLD_ID"],observation_id)).fetchone()
        assert observation["review_status"]=="PENDING"

def test_queue_requires_media_attached_to_session_and_is_idempotent(client,auth):
    owner=auth["owner"]
    _,sid,mid=_session_media(client,owner)
    unattached_upload=client.post("/api/v1/visual/media",headers=owner,files={
        "file":("other.png",_png(),"image/png")})
    other_mid=unattached_upload.json()["id"]
    key="m3c-idempotent-"+uuid.uuid4().hex

    denied=client.post(f"/api/v1/visual/sessions/{sid}/analysis",headers=owner,json={
        "media_id":other_mid,"analyzer_name":"test","analyzer_version":"1",
        "idempotency_key":key})
    assert denied.status_code==422

    first=client.post(f"/api/v1/visual/sessions/{sid}/analysis",headers=owner,json={
        "media_id":mid,"analyzer_name":"test","analyzer_version":"1",
        "idempotency_key":key})
    second=client.post(f"/api/v1/visual/sessions/{sid}/analysis",headers=owner,json={
        "media_id":mid,"analyzer_name":"test","analyzer_version":"1",
        "idempotency_key":key})
    assert first.status_code==201
    assert second.status_code==201
    assert first.json()["id"]==second.json()["id"]

def test_worker_cannot_publish_finding_for_unrelated_room(client,auth):
    owner,worker=auth["owner"],auth["worker"]
    _,sid,mid=_session_media(client,owner)
    unrelated=_room(client,owner)
    queued=client.post(f"/api/v1/visual/sessions/{sid}/analysis",headers=owner,json={
        "media_id":mid,"analyzer_name":"test","analyzer_version":"1",
        "idempotency_key":"outside-"+uuid.uuid4().hex})
    job_id=queued.json()["id"]
    prepared=client.post(f"/api/v1/visual/analysis/jobs/{job_id}/prepare",
        headers=worker,json={"frame_count":1})
    assert prepared.status_code==200
    frame=client.get(f"/api/v1/visual/analysis/jobs/{job_id}",headers=owner).json()["frames"][0]["id"]
    result=client.post(f"/api/v1/visual/analysis/jobs/{job_id}/findings",
        headers=worker,json={"findings":[{
            "frame_id":frame,"finding_type":"CLUTTER","summary":"Test",
            "severity":"LOW","confidence":0.5,"subject_id":unrelated
        }]})
    assert result.status_code==422,result.text
