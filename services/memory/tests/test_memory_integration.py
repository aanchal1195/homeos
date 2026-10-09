"""Integration smoke tests; run with a dedicated PostgreSQL test database."""
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from app import app

@pytest.fixture(scope="module")
def client():
    if not all(os.getenv(k) for k in ("DATABASE_URL","HOMEOS_API_TOKEN","HOMEOS_HOUSEHOLD_ID")):
        pytest.skip("PostgreSQL integration environment is not configured")
    return TestClient(app)

@pytest.fixture(scope="module")
def headers():
    return {"Authorization":"Bearer "+os.environ.get("HOMEOS_API_TOKEN","")}

def test_requires_authorization(client):
    assert client.get("/api/v1/memory/entities/search",params={"q":"fridge"}).status_code == 401

def test_entity_location_alias_and_provenance(client,headers):
    unique=uuid.uuid4().hex[:8]
    room=client.post("/api/v1/memory/entities",headers=headers,json={"entity_type":"ROOM","canonical_name":"Kitchen "+unique}).json()
    asset=client.post("/api/v1/memory/entities",headers=headers,json={"entity_type":"ASSET","canonical_name":"Refrigerator "+unique,"aliases":["fridge "+unique]}).json()
    assert "id" in room and "id" in asset
    result=client.post(f"/api/v1/memory/entities/{asset['id']}/location",headers=headers,json={
      "location_id":room["id"],"evidence":{"source_type":"OWNER","source_ref":"test-suite"},
      "idempotency_key":"location-"+unique})
    assert result.status_code==200,result.text
    assert result.json()["status"]=="updated"
    repeat=client.post(f"/api/v1/memory/entities/{asset['id']}/location",headers=headers,json={
      "location_id":room["id"],"evidence":{"source_type":"OWNER","source_ref":"test-suite"},
      "idempotency_key":"location-"+unique})
    assert repeat.json()["status"]=="already_applied"
    location=client.get(f"/api/v1/memory/entities/{asset['id']}/location",headers=headers).json()
    assert location["path"][0]["canonical_name"]=="Kitchen "+unique
    assert location["path"][0]["source_type"]=="OWNER"
    matches=client.get("/api/v1/memory/entities/search",headers=headers,params={"q":"fridge "+unique}).json()["matches"]
    assert len(matches)==1 and matches[0]["id"]==asset["id"]
    history=client.get(f"/api/v1/memory/entities/{asset['id']}/history",headers=headers).json()
    assert len(history["events"])==1

def test_untrusted_observation_cannot_mutate_location(client,headers):
    key=uuid.uuid4().hex[:8]
    entity=client.post("/api/v1/memory/entities",headers=headers,json={"entity_type":"ASSET","canonical_name":"Test Vacuum "+key}).json()
    room=client.post("/api/v1/memory/entities",headers=headers,json={"entity_type":"ROOM","canonical_name":"Test Store "+key}).json()
    result=client.post("/api/v1/memory/observations",headers=headers,json={
      "subject_id":entity["id"],"candidate_object_id":room["id"],"predicate":"LOCATED_IN",
      "evidence":{"source_type":"PHOTO","source_ref":"sample-image"},"confidence":0.99})
    assert result.status_code==201
    assert result.json()["status"]=="PENDING"
    location=client.get(f"/api/v1/memory/entities/{entity['id']}/location",headers=headers).json()
    assert location["path"]==[]
