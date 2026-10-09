"""Disposable PostgreSQL end-to-end check: JARVIS chat uses confirmed Home Memory."""
import os
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app, SessionLocal, Member

assert os.getenv("HOMEOS_TEST_MODE") == "true", "Do not run against household production data"
assert os.getenv("HOMEOS_MEMORY_ENABLED") == "true"
house=os.environ["HOMEOS_HOUSEHOLD_ID"]
with SessionLocal() as session:
    owner=session.scalar(select(Member).where(Member.household_id==house,Member.role=="owner"))
    assert owner is not None,"Seeded owner identity not found"
    owner_id=owner.id

client=TestClient(app)
headers={"X-Member-Id":owner_id}

for phrase in ("Where is the refrigerator?","fridge kahan hai?"):
    response=client.post("/api/chat",headers=headers,json={"text":phrase})
    assert response.status_code==200,response.text
    fact=response.json()
    assert fact["intent"]=="MEMORY_LOCATION",fact
    assert "Kitchen" in fact["reply"],fact
unknown=client.post("/api/chat",headers=headers,json={"text":"Where is the microwave?"})
assert unknown.status_code==200,unknown.text
assert unknown.json()["intent"]=="MEMORY_NOT_REGISTERED",unknown.json()
overview=client.get("/api/memory/overview",headers=headers)
assert overview.status_code==200,overview.text
assert overview.json()["counts"].get("ASSET",0)>=1
print("JARVIS verified: English/Hinglish registered location and unknown asset stay grounded.")
