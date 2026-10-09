"""M3C integration tests with a deterministic fake model; no external AI calls in CI."""
import io
import os
import uuid
from PIL import Image
import pytest
from fastapi.testclient import TestClient
from app import app
import vision_analysis as vision

@pytest.fixture
def api(tmp_path,monkeypatch):
    for key in ("DATABASE_URL","HOMEOS_API_TOKEN","HOMEOS_HOUSEHOLD_ID"):
        if not os.getenv(key): pytest.skip("Integration database not configured")
    monkeypatch.setenv("PRIVATE_MEDIA_ROOT",str(tmp_path))
    monkeypatch.setenv("HOMEOS_VISION_API_KEY","test-never-sent")
    return TestClient(app),{"Authorization":"Bearer "+os.environ["HOMEOS_API_TOKEN"]}

def entity(client,headers,kind,name):
    r=client.post("/api/v1/memory/entities",headers=headers,
        json={"entity_type":kind,"canonical_name":name})
    assert r.status_code==201,r.text
    return r.json()["id"]

def create_photo(client,headers,room_id):
    s=client.post("/api/v1/visual/sessions",headers=headers,json={
        "session_type":"WEEKLY_WALKTHROUGH","expected_location_id":room_id})
    assert s.status_code==201,s.text
    sid=s.json()["id"]
    im=Image.new("RGB",(4,4),(100,120,140))
    out=io.BytesIO()
    im.save(out,format="PNG")
    u=client.post("/api/v1/visual/media",headers=headers,
        files={"file":("kitchen.png",out.getvalue(),"image/png")})
    assert u.status_code==201,u.text
    mid=u.json()["id"]
    a=client.post(f"/api/v1/visual/sessions/{sid}/media/{mid}",headers=headers)
    assert a.status_code==201,a.text
    return sid,mid

def test_image_observations_are_pending_and_analysis_is_idempotent(api,monkeypatch):
    client,headers=api
    tag=uuid.uuid4().hex[:9]
    room=entity(client,headers,"ROOM","Kitchen "+tag)
    fridge=entity(client,headers,"ASSET","refrigerator")
    moved=client.post(f"/api/v1/memory/entities/{fridge}/location",headers=headers,json={
        "location_id":room,"evidence":{"source_type":"OWNER","source_ref":"onboarding"},
        "idempotency_key":"registered-"+tag})
    assert moved.status_code==200,moved.text
    sid,mid=create_photo(client,headers,room)
    monkeypatch.setattr(vision,"infer",lambda encoded,context:
        vision.VisionResult(detections=[
            vision.Detection(label="refrigerator",description="Visible appliance",confidence=0.96),
            vision.Detection(label="toaster",description="Small appliance",confidence=0.73)]))
    result=client.post(f"/api/v1/visual/sessions/{sid}/analyze/{mid}",headers=headers)
    assert result.status_code==200,result.text
    assert result.json()["summary"]["observations"]==2
    repeat=client.post(f"/api/v1/visual/sessions/{sid}/analyze/{mid}",headers=headers)
    assert repeat.status_code==200
    assert repeat.json()["run_id"]==result.json()["run_id"]
    with vision.db() as conn:
        rows=conn.execute("""SELECT status,subject_id,payload->>'label' label
          FROM memory_observations WHERE household_id=%s AND analysis_run_id=%s ORDER BY label""",
          (os.environ["HOMEOS_HOUSEHOLD_ID"],result.json()["run_id"])).fetchall()
    assert len(rows)==2
    assert all(x["status"]=="PENDING" for x in rows)
    assert next(x for x in rows if x["label"]=="refrigerator")["subject_id"]==uuid.UUID(fridge)
    assert next(x for x in rows if x["label"]=="toaster")["subject_id"] is None
    current=client.get(f"/api/v1/memory/entities/{fridge}/location",headers=headers).json()
    assert current["path"][0]["id"]==room

def test_provider_required_and_unattached_media_rejected(api,monkeypatch):
    client,headers=api
    room=entity(client,headers,"ROOM","Test room "+uuid.uuid4().hex[:9])
    sid,mid=create_photo(client,headers,room)
    monkeypatch.delenv("HOMEOS_VISION_API_KEY")
    off=client.post(f"/api/v1/visual/sessions/{sid}/analyze/{mid}",headers=headers)
    assert off.status_code==503
    monkeypatch.setenv("HOMEOS_VISION_API_KEY","test")
    missing=client.post(f"/api/v1/visual/sessions/{sid}/analyze/{uuid.uuid4()}",headers=headers)
    assert missing.status_code==404

def test_video_sampling_limits_frames_and_handles_failed_samples(monkeypatch,tmp_path):
    path=tmp_path/"sample.mp4"
    path.write_bytes(b"not-a-real-video")
    calls=[]
    class Result:
        stdout=b"fake-image"
    def runner(args,**kw):
        calls.append(args)
        if len(calls)==2: raise subprocess.CalledProcessError(1,args)
        return Result()
    import subprocess
    monkeypatch.setattr(vision.subprocess,"run",runner)
    monkeypatch.setattr(vision,"encode_image",lambda raw:"encoded")
    images=vision.frames(path,"video/mp4")
    assert len(calls)==3 and [x[0] for x in images]==[0,10000]
