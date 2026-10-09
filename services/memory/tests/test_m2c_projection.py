"""PostgreSQL M2C projection contract: safe first import, idempotence and owner conflict."""
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from app import app, db

@pytest.fixture
def sample():
    if not all(os.environ.get(n) for n in ("DATABASE_URL","HOMEOS_API_TOKEN","HOMEOS_HOUSEHOLD_ID")):
        pytest.skip("Memory PostgreSQL test configuration is unavailable")
    house=os.environ["HOMEOS_HOUSEHOLD_ID"]
    parts=[str(uuid.uuid4()) for _ in range(6)]
    hid,pid,fid,rid,rid2,aid=parts
    with db() as conn:
        # CI runs memory migrations but does not contain the separate M2C application.
        # Create the minimum legacy schema needed by this integration contract.
        conn.execute("CREATE TABLE IF NOT EXISTS households (id varchar(50) PRIMARY KEY)")
        conn.execute("""CREATE TABLE IF NOT EXISTS properties
          (id varchar(50) PRIMARY KEY,household_id varchar(50),name text,property_type text,address_label text)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS floors
          (id varchar(50) PRIMARY KEY,household_id varchar(50),property_id varchar(50),
          name text,kind text,sort_order integer)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS rooms
          (id varchar(50) PRIMARY KEY,household_id varchar(50),name text,kind text,floor_id varchar(50))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS zones
          (id varchar(50) PRIMARY KEY,household_id varchar(50),name text,kind text,room_id varchar(50))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS assets
          (id varchar(50) PRIMARY KEY,household_id varchar(50),name text,asset_type text,
           status text,next_service text,room_id varchar(50),zone_id varchar(50))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS memory_legacy_links
          (household_id uuid NOT NULL,legacy_type varchar(32) NOT NULL,
           legacy_id varchar(64) NOT NULL,entity_id uuid NOT NULL,
           PRIMARY KEY(household_id,legacy_type,legacy_id))""")
        conn.execute("INSERT INTO households(id) VALUES(%s) ON CONFLICT DO NOTHING",(house,))
        conn.execute("INSERT INTO properties VALUES(%s,%s,%s,%s,%s)",(pid,house,"House "+hid,"independent_house",""))
        conn.execute("INSERT INTO floors VALUES(%s,%s,%s,%s,%s,%s)",(fid,house,pid,"Ground Floor "+hid,"floor",0))
        conn.execute("INSERT INTO rooms VALUES(%s,%s,%s,%s,%s)",(rid,house,"Kitchen "+hid,"kitchen",fid))
        conn.execute("INSERT INTO rooms VALUES(%s,%s,%s,%s,%s)",(rid2,house,"Storage "+hid,"store",fid))
        conn.execute("INSERT INTO assets VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                     (aid,house,"Refrigerator "+hid,"appliance","OK",None,rid,None))
    return {"house":house,"asset":aid,"kitchen":rid,"storage":rid2}

def test_m2c_projection_idempotence_and_conflict(sample):
    house=sample["house"]
    client=TestClient(app)
    h={"Authorization":"Bearer "+os.environ["HOMEOS_API_TOKEN"]}
    assert client.post("/api/v1/memory/import/m2c").status_code==401
    first=client.post("/api/v1/memory/import/m2c",headers=h)
    assert first.status_code==200,first.text
    counts=first.json()["counts"]
    assert counts["created"]>=5
    assert counts["relationships_changed"]>=4
    repeat=client.post("/api/v1/memory/import/m2c",headers=h)
    assert repeat.status_code==200,repeat.text
    assert repeat.json()["counts"].get("created",0)==0
    assert repeat.json()["counts"].get("relationships_changed",0)==0
    with db() as conn:
        ids={row["legacy_id"]:row["entity_id"] for row in conn.execute(
          "SELECT legacy_id,entity_id FROM memory_legacy_links WHERE household_id=%s",(house,)).fetchall()}
    eid=ids[sample["asset"]]
    other_location=ids[sample["storage"]]
    original_location=ids[sample["kitchen"]]
    record=client.get(f"/api/v1/memory/entities/{eid}/location",headers=h)
    assert record.status_code==200
    assert record.json()["path"][0]["id"]==str(original_location)
    # Simulate owner overriding a projected location. Legacy backfill must NOT erase it.
    changed=client.post(f"/api/v1/memory/entities/{eid}/location",headers=h,json={
      "location_id":str(other_location),
      "evidence":{"source_type":"OWNER","source_ref":"confirmed-relocation"},
      "idempotency_key":"test-"+uuid.uuid4().hex})
    assert changed.status_code==200,changed.text
    conflict=client.post("/api/v1/memory/import/m2c",headers=h)
    assert conflict.status_code==200,conflict.text
    assert conflict.json()["counts"].get("conflicts_proposed")==1
    another=client.post("/api/v1/memory/import/m2c",headers=h)
    assert another.status_code==200,another.text
    assert another.json()["counts"].get("conflicts_proposed",0)==0
    current=client.get(f"/api/v1/memory/entities/{eid}/location",headers=h).json()
    assert current["path"][0]["id"]==str(other_location)
