"""CI-only M3E end-to-end tests against restored disposable PostgreSQL schema.

Requires prior verification scripts to create a household, owner and property.
Refuses to run unless HOMEOS_TEST_MODE=true.
"""
import hashlib
import io
import os
from pathlib import Path
import tempfile
import uuid

import psycopg
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select, text

assert os.getenv("HOMEOS_TEST_MODE") == "true", "Never run on household production data"
assert os.getenv("HOMEOS_MEMORY_ENABLED") == "true"
from app.main import app, SessionLocal, Member, Room, Asset

house=os.environ["HOMEOS_HOUSEHOLD_ID"]
url=os.environ["MEMORY_DATABASE_URL"]
client=TestClient(app)

with SessionLocal() as s:
    owner=s.scalar(select(Member).where(Member.household_id==house,Member.role=="owner"))
    kitchen=s.scalar(select(Room).where(Room.household_id==house,Room.name=="Kitchen"))
    refrigerator=s.scalar(select(Asset).where(Asset.household_id==house,Asset.name=="Refrigerator"))
    assert owner and kitchen and refrigerator
    owner_id=owner.id
    fridge_id=refrigerator.id
    kitchen_id=kitchen.id
    alternate=Room(household_id=house, name="Store Room",kind="store",
                   floor_id=kitchen.floor_id,floor=0)
    maid=Member(household_id=house,name="CI Maid",role="maid",language="hinglish")
    s.add_all([alternate,maid])
    s.commit()
    alternate_room_id=alternate.id
    maid_id=maid.id

headers={"X-Member-Id":owner_id}
staff={"X-Member-Id":maid_id}
r=client.post("/api/memory/sync",headers=headers)
assert r.status_code==200,r.text

def graph_link(typ,legacy):
    with psycopg.connect(url) as conn:
        row=conn.execute("""SELECT entity_id FROM memory_legacy_links
           WHERE household_id=%s AND legacy_type=%s AND legacy_id=%s""",
           (house,typ,legacy)).fetchone()
    assert row,(typ,legacy)
    return row[0]

kitchen_graph=graph_link("room",kitchen_id)
alternate_graph=graph_link("room",alternate_room_id)
fridge_graph=graph_link("asset",fridge_id)

image=Image.new("RGB",(9,9),color=(30,130,120))
buffer=io.BytesIO()
image.save(buffer,format="PNG")
data=buffer.getvalue()

with tempfile.TemporaryDirectory() as temporary:
    os.environ["HOMEOS_PRIVATE_MEMORY_MEDIA_ROOT"]=temporary

    def create_observations(location, labels, *, subject=None):
        media_id=uuid.uuid4()
        session_id=uuid.uuid4()
        run_id=uuid.uuid4()
        storage_key=f"{house}/{media_id}.png"
        path=Path(temporary)/storage_key
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
        ids=[]
        with psycopg.connect(url) as conn:
            with conn.transaction():
                conn.execute("""INSERT INTO visual_sessions(id,household_id,session_type,expected_location_id)
                   VALUES(%s,%s,'WEEKLY_WALKTHROUGH',%s)""",(session_id,house,location))
                conn.execute("""INSERT INTO memory_media
                   (id,household_id,sha256,storage_key,content_type,byte_size)
                   VALUES(%s,%s,%s,%s,'image/png',%s)""",
                   (media_id,house,hashlib.sha256(data).hexdigest(),storage_key,len(data)))
                conn.execute("""INSERT INTO visual_session_media(household_id,session_id,media_id)
                    VALUES(%s,%s,%s)""",(house,session_id,media_id))
                conn.execute("""INSERT INTO visual_analysis_runs
                  (id,household_id,session_id,media_id,status,provider,model_version)
                  VALUES(%s,%s,%s,%s,'COMPLETED','openai','CI-mock')""",
                  (run_id,house,session_id,media_id))
                for label in labels:
                    ev=conn.execute("""INSERT INTO memory_evidence(household_id,source_type,source_ref)
                       VALUES(%s,'PHOTO',%s) RETURNING id""",(house,str(media_id))).fetchone()[0]
                    oid=conn.execute("""INSERT INTO memory_observations
                        (household_id,subject_id,evidence_id,payload,confidence,
                         media_id,frame_timestamp_ms,model_version,analysis_run_id)
                        VALUES(%s,%s,%s,%s::jsonb,0.92,%s,0,'CI-mock',%s) RETURNING id""",
                        (house,subject,ev,'{"label":"'+label+'","description":"Possible item seen"}',
                         media_id,run_id)).fetchone()[0]
                    ids.append(oid)
        return ids

    microwave_id,reject_id,note_id=create_observations(
      kitchen_graph,["microwave","toaster","countertop mark"])
    moved_id=create_observations(alternate_graph,["refrigerator"],subject=fridge_graph)[0]

    denied=client.get("/api/memory/visual/pending",headers=staff)
    assert denied.status_code==403,denied.text
    pending=client.get("/api/memory/visual/pending",headers=headers)
    assert pending.status_code==200,pending.text
    findings=pending.json()["observations"]
    assert len(findings)==4,pending.text
    target=next(i for i in findings if i["id"]==str(microwave_id))
    assert target["inspected_location"]=="Kitchen"
    assert any(l["id"]==str(kitchen_graph) for l in target["locations"])
    assert not any(l["id"]==str(alternate_graph) for l in target["locations"])
    preview=client.get(f"/api/memory/visual/{microwave_id}/evidence",headers=headers)
    assert preview.status_code==200,preview.text
    assert preview.content==data
    assert client.get(f"/api/memory/visual/{microwave_id}/evidence",headers=staff).status_code==403

    # AI guesses cannot auto-register; owner MUST supply a verified name and location.
    missing_name=client.post(f"/api/memory/visual/{microwave_id}/resolve",headers=headers,
        json={"decision":"REGISTER_ASSET","location_entity_id":str(kitchen_graph)})
    assert missing_name.status_code==422,missing_name.text
    unrelated=client.post(f"/api/memory/visual/{microwave_id}/resolve",headers=headers,
        json={"decision":"REGISTER_ASSET","corrected_name":"Microwave",
              "location_entity_id":str(alternate_graph)})
    assert unrelated.status_code==422,unrelated.text
    assert client.post(f"/api/memory/visual/{microwave_id}/resolve",headers=staff,
        json={"decision":"REGISTER_ASSET","corrected_name":"Microwave",
              "location_entity_id":str(kitchen_graph)}).status_code==403

    registered=client.post(f"/api/memory/visual/{microwave_id}/resolve",headers=headers,
        json={"decision":"REGISTER_ASSET","corrected_name":"Microwave",
              "location_entity_id":str(kitchen_graph),"note":"Verified against photo"})
    assert registered.status_code==200,registered.text
    assert registered.json()["status"]=="ACCEPTED"
    assert registered.json()["graph_entity_id"]
    assert client.post(f"/api/memory/visual/{microwave_id}/resolve",headers=headers,
        json={"decision":"REGISTER_ASSET","corrected_name":"Microwave",
              "location_entity_id":str(kitchen_graph)}).status_code==409
    with SessionLocal() as s:
        added=s.scalars(select(Asset).where(Asset.household_id==house,Asset.name=="Microwave")).all()
        assert len(added)==1
        assert added[0].room_id==kitchen_id

    jarvis=client.post("/api/chat",headers=headers,json={"text":"Where is the microwave?"})
    assert jarvis.status_code==200,jarvis.text
    assert jarvis.json()["intent"]=="MEMORY_LOCATION"
    assert "Kitchen" in jarvis.json()["reply"]

    rejected=client.post(f"/api/memory/visual/{reject_id}/resolve",headers=headers,
        json={"decision":"REJECT","note":"Toaster was wrongly identified"})
    assert rejected.status_code==200,rejected.text
    assert rejected.json()["status"]=="REJECTED"
    noted=client.post(f"/api/memory/visual/{note_id}/resolve",headers=headers,
        json={"decision":"VERIFY_ONLY","note":"Visible but no change needed"})
    assert noted.status_code==200,noted.text

    moved=client.post(f"/api/memory/visual/{moved_id}/resolve",headers=headers,
        json={"decision":"CONFIRM_LOCATION","asset_id":fridge_id,
              "location_entity_id":str(alternate_graph),"note":"Moved fridge to Store Room"})
    assert moved.status_code==200,moved.text
    with SessionLocal() as s:
        fridge=s.get(Asset,fridge_id)
        assert fridge.room_id==alternate_room_id
    location=client.post("/api/chat",headers=headers,json={"text":"Where is the refrigerator?"})
    assert location.status_code==200,location.text
    assert location.json()["intent"]=="MEMORY_LOCATION"
    assert "Store Room" in location.json()["reply"]
    with psycopg.connect(url) as conn:
        with conn.cursor() as c:
            c.execute("""SELECT v.source_type FROM memory_assertions a
              JOIN memory_evidence v ON v.household_id=a.household_id AND v.id=a.evidence_id
              WHERE a.household_id=%s AND a.subject_id=%s
                AND a.predicate='LOCATED_IN' AND a.verification_status='CONFIRMED'
                AND a.valid_until IS NULL""",(house,fridge_graph))
            assert c.fetchone()[0]=="OWNER"
            c.execute("""SELECT decision FROM memory_visual_resolutions
                WHERE household_id=%s AND observation_id IN (%s,%s,%s,%s)""",
                (house,microwave_id,reject_id,note_id,moved_id))
            assert len(c.fetchall())==4
    final=client.get("/api/memory/visual/pending",headers=headers)
    assert final.status_code==200,final.text
    assert final.json()["observations"]==[]
print("M3E visual verification: owner-only evidence, correction, registration, rejection, and JARVIS updates passed.")
