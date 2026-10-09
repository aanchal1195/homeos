"""M3B integration coverage: private uploads, status and evidence gating."""
import io
from PIL import Image
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from app import app

@pytest.fixture
def auth():
    if not all(os.environ.get(key) for key in ("DATABASE_URL","HOMEOS_API_TOKEN","HOMEOS_HOUSEHOLD_ID")):
        pytest.skip("Missing dedicated integration database and token")
    return {"Authorization":"Bearer "+os.environ["HOMEOS_API_TOKEN"]}

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVATE_MEDIA_ROOT",str(tmp_path))
    return TestClient(app)

def room(client,auth):
    r=client.post("/api/v1/memory/entities",headers=auth,json={
      "entity_type":"ROOM","canonical_name":"Inspection Test "+uuid.uuid4().hex[:12]})
    assert r.status_code==201,r.text
    return r.json()["id"]

def test_upload_auth_and_media_type_validation(client,auth):
    assert client.post("/api/v1/visual/media",files={"file":("test.png",b"garbage","image/png")}).status_code==401
    response=client.post("/api/v1/visual/media",headers=auth,files={"file":("test.png",b"garbage","image/png")})
    assert response.status_code==415,response.text
    response=client.post("/api/v1/visual/media",headers=auth,files={"file":("test.txt",b"plain text","text/plain")})
    assert response.status_code==415,response.text

def test_guided_session_upload_coverage(client,auth):
    rid=room(client,auth)
    response=client.post("/api/v1/visual/sessions",headers=auth,json={
      "session_type":"WEEKLY_WALKTHROUGH","expected_location_id":rid})
    assert response.status_code==201,response.text
    sid=response.json()["id"]
    # Use a valid encoded image, not a header-only fake.
    image=Image.new("RGB",(2,2),color=(150,150,150))
    out=io.BytesIO()
    image.save(out,format="PNG")
    png=out.getvalue()
    uploaded=client.post("/api/v1/visual/media",headers=auth,files={"file":("kitchen.png",png,"image/png")})
    assert uploaded.status_code==201,uploaded.text
    mid=uploaded.json()["id"]
    unattached=client.post(f"/api/v1/visual/sessions/{sid}/coverage",headers=auth,json={
       "location_id":rid,"coverage_status":"PARTIAL","media_id":mid})
    assert unattached.status_code==422,unattached.text
    attached=client.post(f"/api/v1/visual/sessions/{sid}/media/{mid}",headers=auth)
    assert attached.status_code==201,attached.text
    coverage=client.post(f"/api/v1/visual/sessions/{sid}/coverage",headers=auth,json={
       "location_id":rid,"coverage_status":"PARTIAL","media_id":mid,
       "notes":"Cabinet under sink not inspected"})
    assert coverage.status_code==200,coverage.text
    details=client.get(f"/api/v1/visual/sessions/{sid}",headers=auth)
    assert details.status_code==200
    assert len(details.json()["media"])==1
    assert details.json()["coverage"][0]["coverage_status"]=="PARTIAL"
    assert "not inspected" in details.json()["coverage"][0]["notes"]

def test_cross_household_location_cannot_be_used(client,auth):
    nonexistent=uuid.uuid4()
    response=client.post("/api/v1/visual/sessions",headers=auth,json={
        "session_type":"ISSUE_REPORT","expected_location_id":str(nonexistent)})
    assert response.status_code==404
