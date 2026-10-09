"""M5 isolated, scripted-model guided media -> owner review -> memory -> JARVIS.

Authentic FastAPI/SQLAlchemy/PostgreSQL/memory graph services are exercised.
The vision model is SCRIPTED; no pixels are recognized by a real provider.
Never run with actual household data.
"""
import io
import os
import tempfile

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

assert os.getenv("HOMEOS_TEST_MODE")=="true", "CI-only synthetic household"
assert os.getenv("HOMEOS_MEMORY_ENABLED")=="true"
os.environ["HOMEOS_GUIDED_SETUP_AI_ENABLED"]="true"
os.environ["HOMEOS_GUIDED_SETUP_API_KEY"]="CI_SCRIPTED_NO_NETWORK"
from app.main import app,SessionLocal,Member,Room,Asset
from app import guided_setup
from app.memory_bridge import _run,_uuid

house=os.environ["HOMEOS_HOUSEHOLD_ID"]
client=TestClient(app)
with SessionLocal() as s:
    owner=s.scalar(select(Member).where(
        Member.household_id==house,Member.role=="owner"))
    staff=s.scalar(select(Member).where(
        Member.household_id==house,Member.role=="maid"))
    room=s.scalar(select(Room).where(
        Room.household_id==house,Room.name=="Kitchen"))
    assert owner and staff and room
    owner_id,staff_id,room_id=owner.id,staff.id,room.id
owner_headers={"X-Member-Id":owner_id}
staff_headers={"X-Member-Id":staff_id}

with tempfile.TemporaryDirectory(prefix="guided-ci-private-") as private:
    os.environ["HOMEOS_GUIDED_MEDIA_ROOT"]=private
    img=Image.new("RGB",(80,65),(60,140,95))
    image=io.BytesIO();img.save(image,format="PNG");raw=image.getvalue()
    called=[]
    def mocked_infer(record,path):
        called.append(record.id)
        assert path.read_bytes()==raw
        return guided_setup.VisionReadout.model_validate({
           "findings":[
             {"kind":"ASSET","name":"Countertop Coffee Grinder",
              "room_hint":"Kitchen","asset_type":"appliance",
              "evidence_summary":"SCRIPTED test finding; not inferred from pixels"},
             {"kind":"ASSET","name":"Unseen Robot",
              "room_hint":"Kitchen","asset_type":"equipment",
              "evidence_summary":"SCRIPTED false positive to reject"},
           ],
           "unresolved":["Back of cupboard not visible"],
           "suggested_next_capture":"Take a second photograph from the doorway."
        })
    guided_setup._infer=mocked_infer
    result=client.post("/api/guided/upload",headers=owner_headers,
        data={"media_kind":"ROOM_PHOTO","room_id":room_id,"room_hint":"Kitchen"},
        files={"file":("synthetic.png",raw,"image/png")})
    assert result.status_code==201,result.text
    eid=result.json()["evidence"]["id"]
    assert not called
    forbidden=client.post("/api/guided/analyze",headers=staff_headers,json={
        "evidence_id":eid,"consent_to_external_ai_processing":True})
    assert forbidden.status_code==403
    not_consented=client.post("/api/guided/analyze",headers=owner_headers,json={
        "evidence_id":eid,"consent_to_external_ai_processing":False})
    assert not_consented.status_code==422
    assert not called
    completed=client.post("/api/guided/analyze",headers=owner_headers,json={
        "evidence_id":eid,"consent_to_external_ai_processing":True})
    assert completed.status_code==200,completed.text
    assert called==[eid]
    suggestions=completed.json()["evidence"]["suggestions"]
    assert len(suggestions)==2
    with SessionLocal() as s:
        # Proposal text alone must not create authoritative assets.
        assert not s.scalar(select(Asset.id).where(
            Asset.household_id==house,
            Asset.name=="Countertop Coffee Grinder"))
    false_suggestion=next(x for x in suggestions if x["name"]=="Unseen Robot")
    actual=next(x for x in suggestions if x["name"]=="Countertop Coffee Grinder")
    rejected=client.post(f"/api/guided/evidence/{eid}/decide",headers=owner_headers,
       json={"suggestion_id":false_suggestion["id"],"decision":"REJECT"})
    assert rejected.status_code==200,rejected.text
    assert not rejected.json()["applied_id"]
    with SessionLocal() as s:
        assert not s.scalar(select(Asset.id).where(
            Asset.household_id==house,Asset.name=="Unseen Robot"))
    approved=client.post(f"/api/guided/evidence/{eid}/decide",headers=owner_headers,
       json={"suggestion_id":actual["id"],"decision":"ACCEPT",
             "corrected_name":"Countertop Coffee Grinder","room_id":room_id})
    assert approved.status_code==200,approved.text
    aid=approved.json()["applied_id"]
    assert aid
    assert client.post(f"/api/guided/evidence/{eid}/decide",
       headers=owner_headers,json={"suggestion_id":actual["id"],
            "decision":"ACCEPT","room_id":room_id}).status_code==409
    with SessionLocal() as s:
        asset=s.get(Asset,aid)
        assert asset and asset.name=="Countertop Coffee Grinder"
        assert asset.room_id==room_id
        graph=_run(s,"""SELECT entity_id FROM memory_legacy_links WHERE
            household_id=:house AND legacy_type='asset' AND legacy_id=:legacy""",
            house=_uuid(house),legacy=aid).scalar_one()
        current=_run(s,"""SELECT a.object_id,a.verification_status,v.source_type,v.source_ref
            FROM memory_assertions a
            JOIN memory_evidence v ON v.household_id=a.household_id AND v.id=a.evidence_id
            WHERE a.household_id=:house AND a.subject_id=:asset
              AND a.predicate='LOCATED_IN' AND a.verification_status='CONFIRMED'
              AND a.valid_until IS NULL""",
            house=_uuid(house),asset=graph).mappings().one()
        assert current["source_type"]=="OWNER",current
        assert current["source_ref"]==f"guided-setup:{eid}:{actual['id']}",current
        entry=_run(s,"""SELECT event_type FROM memory_events
            WHERE household_id=:house AND subject_id=:id
              AND event_type='GUIDED_ASSET_VERIFIED'""",
            house=_uuid(house),id=graph).scalar_one()
        assert entry=="GUIDED_ASSET_VERIFIED"
    # The existing memory-history API surfaces the provenance.
    timeline=client.get(f"/api/memory/assets/{graph}/history",headers=owner_headers)
    assert timeline.status_code==200,timeline.text
    assert any(x["source_ref"].startswith("guided-setup:") and
               x["source_type"]=="OWNER" for x in timeline.json()["locations"])
    answer=client.post("/api/chat",headers=owner_headers,
          json={"text":"Where did we put the Countertop Coffee Grinder?"})
    assert answer.status_code==200,answer.text
    assert "Kitchen" in answer.json()["reply"],answer.json()
    assert client.get("/api/guided/evidence/"+eid+"/media",
                      headers=staff_headers).status_code==403
    print("PASS M5: private PNG -> scripted proposals -> owner reject/accept ->")
    print("real PostgreSQL + OWNER evidence -> existing JARVIS grounded retrieval.")
    print("NOTE: no real model/image recognition or browser used.")
