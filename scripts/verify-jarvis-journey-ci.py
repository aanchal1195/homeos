"""M4A disposable full journey: photo -> fake vision -> owner -> JARVIS.

This is NOT a real vision accuracy test. The CI-only provider returns scripted
detections unrelated to pixels, while upload/media parsing/analysis persistence,
authorization, review, graph changes and conversational queries use real code.
"""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import httpx
import psycopg
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select

assert os.getenv("HOMEOS_TEST_MODE")=="true", "Never run on household data"
assert os.getenv("HOMEOS_MEMORY_ENABLED")=="true"
from app.main import app, SessionLocal, Member, Room, Asset, uid

root=Path(__file__).resolve().parent.parent
house=os.environ["HOMEOS_HOUSEHOLD_ID"]
token=os.environ["HOMEOS_API_TOKEN"]
port=18004
base=f"http://127.0.0.1:{port}"
os.environ["HOMEOS_MEMORY_INTERNAL_URL"]=base
os.environ["HOMEOS_MEMORY_SERVICE_TOKEN"]=token

with SessionLocal() as db:
    owner=db.scalar(select(Member).where(Member.household_id==house,Member.role=="owner"))
    staff=db.scalar(select(Member).where(Member.household_id==house,Member.role=="maid"))
    kitchen=db.scalar(select(Room).where(Room.household_id==house,Room.name=="Kitchen"))
    store=db.scalar(select(Room).where(Room.household_id==house,Room.name=="Store Room"))
    fridge=db.scalar(select(Asset).where(Asset.household_id==house,Asset.name=="Refrigerator"))
    assert owner and staff and kitchen and store and fridge
    owner_id,staff_id,kitchen_id,store_id,fridge_id=owner.id,staff.id,kitchen.id,store.id,fridge.id
    assert fridge.room_id==store_id, "M3E prior fixture should place refrigerator in Store Room"
    # Same asset category, different rooms; disambiguation must not pick the first.
    db.add(Asset(id=uid(),household_id=house,room_id=kitchen_id,
                 name="Ceiling Fan",asset_type="fixture",status="UNKNOWN"))
    db.add(Asset(id=uid(),household_id=house,room_id=store_id,
                 name="Ceiling Fan",asset_type="fixture",status="UNKNOWN"))
    db.commit()

client=TestClient(app)
owner={"X-Member-Id":owner_id}
staff={"X-Member-Id":staff_id}

def ask(text):
    response=client.post("/api/chat",headers=owner,json={"text":text})
    assert response.status_code==200,(text,response.text)
    return response.json()

def review(item,body,headers=owner):
    return client.post("/api/memory/visual/"+item["id"]+"/resolve",headers=headers,json=body)

with tempfile.TemporaryDirectory(prefix="homeos-m4a-ci-") as temporary:
    os.environ["HOMEOS_PRIVATE_MEMORY_MEDIA_ROOT"]=temporary
    env=os.environ.copy()
    env["PYTHONPATH"]=str(root/"services/memory")+os.pathsep+str(root/"scripts")
    env["DATABASE_URL"]=os.environ["MEMORY_DATABASE_URL"]
    env["PRIVATE_MEDIA_ROOT"]=temporary
    env["HOMEOS_VISION_API_KEY"]="CI_FAKE_VISION_ONLY"
    env["HOMEOS_VISION_MODEL"]="ci-scripted-no-real-inference"
    env["HOMEOS_TEST_MODE"]="true"
    log=Path(temporary)/"memory.log"
    with log.open("wb") as out:
        process=subprocess.Popen(
          [sys.executable,"-m","uvicorn","ci_fake_vision_app:app",
           "--host","127.0.0.1","--port",str(port)],
          cwd=root/"scripts",env=env,stdout=out,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("CI mock vision service unexpectedly exited")
                try:
                    if httpx.get(base+"/health",timeout=1,trust_env=False).status_code==200:
                        break
                except httpx.RequestError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("CI mock vision service failed health check")

            synced=client.post("/api/memory/sync",headers=owner)
            assert synced.status_code==200,synced.text
            records=client.get("/api/memory/visual/inspection-locations",headers=owner)
            assert records.status_code==200,records.text
            listed=records.json()["locations"]
            loc={x["name"]:x["id"] for x in listed}
            assert "Kitchen" in loc and "Store Room" in loc

            def photo(room):
                img=Image.new("RGB",(20,20),(60,140,90) if room=="Kitchen" else (100,75,155))
                data=io.BytesIO();img.save(data,format="PNG")
                raw=data.getvalue()
                uploaded=client.post("/api/memory/visual/inspection-upload",headers=owner,
                    data={"location_entity_id":loc[room]},
                    files={"file":("sample.png",raw,"image/png")})
                assert uploaded.status_code==200,uploaded.text
                ids=uploaded.json()
                assert ids["status"]=="UPLOADED"
                no_consent=client.post("/api/memory/visual/inspection-analyze",headers=owner,
                    json={"session_id":ids["session_id"],"media_id":ids["media_id"],
                          "consent_to_external_ai_processing":False})
                assert no_consent.status_code==422
                sent=client.post("/api/memory/visual/inspection-analyze",headers=owner,
                    json={"session_id":ids["session_id"],"media_id":ids["media_id"],
                          "consent_to_external_ai_processing":True})
                assert sent.status_code==200,sent.text
                assert sent.json()["status"]=="COMPLETED"
                assert sent.json()["summary"]["frames"]==1
                return raw,ids

            # 1. Actual private upload and inference pipeline with scripted detections.
            raw,first=photo("Kitchen")
            assert first["location"]=="Kitchen"
            queue=client.get("/api/memory/visual/pending",headers=owner)
            assert queue.status_code==200,queue.text
            findings=[x for x in queue.json()["observations"]
                if x["media_id"]==first["media_id"]]
            assert {x["label"] for x in findings}=={
                "electric kettle","bread toaster","refrigerator"},findings
            kettle=next(x for x in findings if x["label"]=="electric kettle")
            toaster=next(x for x in findings if x["label"]=="bread toaster")
            fridge_detection=next(x for x in findings if x["label"]=="refrigerator")
            preview=client.get("/api/memory/visual/"+kettle["id"]+"/evidence",headers=owner)
            assert preview.status_code==200 and preview.content==raw
            assert client.get("/api/memory/visual/"+kettle["id"]+"/evidence",
                              headers=staff).status_code==403

            # 2. Pending/unverified object is NOT available in authoritative memory.
            unknown=ask("Where did we put the electric kettle?")
            assert unknown["intent"]=="MEMORY_GROUNDED_UNKNOWN",unknown

            # 3. Owner explicitly names asset; staff cannot approve.
            payload={"decision":"REGISTER_ASSET","corrected_name":"Electric Kettle",
                     "location_entity_id":loc["Kitchen"],"asset_type":"appliance"}
            assert review(kettle,payload,staff).status_code==403
            approved=review(kettle,payload)
            assert approved.status_code==200,approved.text
            graph_kettle=approved.json()["graph_entity_id"]
            kettle_id=approved.json()["asset_id"]
            assert graph_kettle and kettle_id
            with SessionLocal() as db:
                asset=db.get(Asset,kettle_id)
                assert asset and asset.room_id==kitchen_id
            duplicate=review(kettle,payload)
            assert duplicate.status_code==409,duplicate.text

            rejected=review(toaster,{"decision":"REJECT","note":"False positive from fake detector"})
            assert rejected.status_code==200,rejected.text
            toaster_question=ask("Where is the bread toaster?")
            assert toaster_question["intent"]=="MEMORY_GROUNDED_UNKNOWN",toaster_question
            # A rejected/unknown subject must not borrow an older conversation ref.
            clarify=ask("Is it still there?")
            assert clarify["intent"]!="MEMORY_GROUNDED_ASSET_LOCATION",clarify

            # 4. A moved refrigerator uses the same transactional M2C+graph path.
            moved=review(fridge_detection,{"decision":"CONFIRM_LOCATION",
                "asset_id":fridge_id,"location_entity_id":loc["Kitchen"],
                "note":"Owner checked kitchen inspection"})
            assert moved.status_code==200,moved.text
            with SessionLocal() as db:
                assert db.get(Asset,fridge_id).room_id==kitchen_id
            move_answer=ask("Can you tell me where the refrigerator is located?")
            assert move_answer["intent"]=="MEMORY_GROUNDED_ASSET_LOCATION",move_answer
            assert "Kitchen" in move_answer["reply"],move_answer

            # 5. Natural paraphrases, persisted pronoun reference, and evidence.
            answer=ask("Where did we put the electric kettle?")
            assert answer["intent"]=="MEMORY_GROUNDED_ASSET_LOCATION",answer
            assert "Kitchen" in answer["reply"] and "Last recorded" in answer["reply"]
            hinglish=ask("Electric kettle kahan hai?")
            assert hinglish["intent"]=="MEMORY_GROUNDED_ASSET_LOCATION",hinglish
            assert "Kitchen" in hinglish["reply"],hinglish
            where_now=ask("And where is it now?")
            assert where_now["intent"]=="MEMORY_GROUNDED_ASSET_LOCATION",where_now
            assert "Electric Kettle" in where_now["reply"],where_now
            evidence=ask("When was it last verified?")
            assert evidence["intent"]=="MEMORY_GROUNDED_ASSET_HISTORY",evidence
            assert "Owner verified" in evidence["reply"],evidence
            contents=ask("What else is in that room?")
            assert contents["intent"]=="MEMORY_GROUNDED_ROOM_CONTENTS",contents
            assert "Electric Kettle" in contents["reply"],contents
            assert "Refrigerator" in contents["reply"],contents

            # 6. Two identically named fans may never be silently collapsed.
            ambiguous=ask("Where is the fan?")
            assert ambiguous["intent"]=="MEMORY_GROUNDED_AMBIGUOUS",ambiguous
            assert "Kitchen" in ambiguous["reply"] and "Store Room" in ambiguous["reply"]
            chosen=ask("The one in Kitchen?")
            assert chosen["intent"]=="MEMORY_GROUNDED_ASSET_LOCATION",chosen
            assert "Kitchen" in chosen["reply"],chosen

            # 7. Owner-only provenance includes real evidence and superseded locations.
            history=client.get("/api/memory/assets/"+graph_kettle+"/history",headers=owner)
            assert history.status_code==200,history.text
            assert any(entry["source_type"]=="OWNER" and entry["observation_id"]==kettle["id"]
                       for entry in history.json()["locations"]),history.text
            assert client.get("/api/memory/assets/"+graph_kettle+"/history",
                              headers=staff).status_code==403

            # 8. Another photo is processed, then owner moves the kettle to Store.
            _,second=photo("Store Room")
            current=client.get("/api/memory/visual/pending",headers=owner)
            finding=next(x for x in current.json()["observations"]
                         if x["media_id"]==second["media_id"] and x["label"]=="electric kettle")
            assert review(finding,{"decision":"CONFIRM_LOCATION","asset_id":kettle_id,
               "location_entity_id":loc["Store Room"]},staff).status_code==403
            relocation=review(finding,{"decision":"CONFIRM_LOCATION","asset_id":kettle_id,
                                 "location_entity_id":loc["Store Room"],
                                 "note":"Owner verified relocation"})
            assert relocation.status_code==200,relocation.text
            with SessionLocal() as db:
                assert db.get(Asset,kettle_id).room_id==store_id
            followup=ask("Where did we leave the electric kettle?")
            assert followup["intent"]=="MEMORY_GROUNDED_ASSET_LOCATION",followup
            assert "Store Room" in followup["reply"],followup
            stale=ask("Is it still there?")
            assert stale["intent"]=="MEMORY_GROUNDED_ASSET_LOCATION",stale
            assert "cannot confirm its live position" in stale["reply"],stale
            again=client.get("/api/memory/assets/"+graph_kettle+"/history",headers=owner)
            assert again.status_code==200,again.text
            timeline=again.json()["locations"]
            assert any(x["verification_status"]=="SUPERSEDED" for x in timeline),timeline
            assert timeline[0]["location_name"]=="Store Room",timeline
            assert len([x for x in timeline if x["source_type"]=="OWNER"])>=2,timeline

            # 9. No graph insertion from rejected findings; no data from fake pixels.
            with psycopg.connect(os.environ["MEMORY_DATABASE_URL"]) as con:
                rows=con.execute("""SELECT COUNT(*) FROM memory_entities WHERE
                   household_id=%s AND entity_type='ASSET' AND canonical_name='bread toaster'""",
                   (house,)).fetchone()[0]
                assert rows==0
                checked=con.execute("""SELECT COUNT(*) FROM memory_observations
                   WHERE household_id=%s AND media_id=%s AND status='REJECTED'""",
                   (house,first["media_id"])).fetchone()[0]
                assert checked==1
            print("PASS: private photo -> MOCK vision proposals -> owner correction/denial ->")
            print("      shared memory -> natural follow-ups / ambiguity / history -> moved asset")
            print("      IMPORTANT: detections were SCRIPTED, not image-model recognition.")
        except Exception:
            out.flush()
            print(log.read_text(errors="replace")[-6000:])
            raise
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)
