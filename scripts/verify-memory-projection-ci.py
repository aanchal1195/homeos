"""Disposable CI-only smoke test against the REAL M2C Alembic schema + memory SQL.
Refuses to seed a DB unless HOMEOS_TEST_MODE=true. Never run on production.
"""
import os
import uuid
import psycopg
from fastapi.testclient import TestClient
# The M2C Alembic job uses a SQLAlchemy URL. Direct psycopg queries need a libpq URL.
os.environ["DATABASE_URL"] = os.environ["MEMORY_DATABASE_URL"]
from app import app

assert os.getenv("HOMEOS_TEST_MODE") == "true", "Disposable test databases only"
url = os.environ["MEMORY_DATABASE_URL"]
house = os.environ["HOMEOS_HOUSEHOLD_ID"]
uid = lambda: str(uuid.uuid4())
property_id, floor_id, room_id, asset_id, owner_id = [uid() for _ in range(5)]

with psycopg.connect(url) as conn:
    with conn.transaction():
        conn.execute("INSERT INTO households(id,name,setup_completed) VALUES(%s,%s,true)",(house,"Integration CI House"))
        conn.execute("INSERT INTO members(id,household_id,name,role,language) VALUES(%s,%s,%s,%s,%s)",
                     (owner_id,house,"CI Owner","owner","hinglish"))
        conn.execute("""INSERT INTO properties(id,household_id,name,property_type,address_label)
                        VALUES(%s,%s,%s,%s,%s)""",
                     (property_id,house,"CI property","independent_house",""))
        conn.execute("""INSERT INTO floors(id,household_id,property_id,name,sort_order,kind)
                        VALUES(%s,%s,%s,%s,0,'floor')""",
                     (floor_id,house,property_id,"Ground Floor"))
        conn.execute("""INSERT INTO rooms(id,household_id,floor_id,floor,name,kind)
                        VALUES(%s,%s,%s,0,%s,'kitchen')""",
                     (room_id,house,floor_id,"Kitchen"))
        conn.execute("""INSERT INTO assets(id,household_id,room_id,name,status,asset_type)
                        VALUES(%s,%s,%s,'Refrigerator','OK','appliance')""",
                     (asset_id,house,room_id))

client=TestClient(app)
headers={"Authorization":"Bearer "+os.environ["HOMEOS_API_TOKEN"]}
first=client.post("/api/v1/memory/import/m2c",headers=headers)
assert first.status_code == 200,first.text
assert first.json()["counts"]["created"] == 4,first.text
repeat=client.post("/api/v1/memory/import/m2c",headers=headers)
assert repeat.status_code == 200,repeat.text
assert repeat.json()["counts"].get("created",0)==0,repeat.text
assert repeat.json()["counts"].get("relationships_changed",0)==0,repeat.text
with psycopg.connect(url) as conn:
    row=conn.execute("""SELECT m.id FROM memory_entities m
       JOIN memory_legacy_links l ON l.entity_id=m.id AND l.household_id=m.household_id
       WHERE l.household_id=%s AND l.legacy_type='asset' AND l.legacy_id=%s""",
       (house,asset_id)).fetchone()
assert row,"No graph entity created for registered refrigerator"
location=client.get(f"/api/v1/memory/entities/{row[0]}/location",headers=headers)
assert location.status_code == 200,location.text
assert location.json()["path"][0]["canonical_name"]=="Kitchen",location.text
print("Real-schema M2C -> Home Memory import verified and idempotent.")
