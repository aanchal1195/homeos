"""CI-only M3F proof: existing HomeOS -> real private memory HTTP service.

Uses a disposable PostgreSQL service and an isolated temporary photo directory.
No live provider key, external requests, production data, or deployed containers.
"""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

import httpx
import psycopg
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select

assert os.getenv("HOMEOS_TEST_MODE")=="true", "Never run photo tests against household production"
assert os.getenv("HOMEOS_MEMORY_ENABLED")=="true"
assert os.environ["HOMEOS_HOUSEHOLD_ID"]
from app.main import app, Member, Room, SessionLocal

repo=Path(__file__).resolve().parent.parent
port=18001
base=f"http://127.0.0.1:{port}"
house=os.environ["HOMEOS_HOUSEHOLD_ID"]
token=os.environ["HOMEOS_API_TOKEN"]
os.environ["HOMEOS_MEMORY_SERVICE_TOKEN"]=token
os.environ["HOMEOS_MEMORY_INTERNAL_URL"]=base

with SessionLocal() as s:
    owner=s.scalar(select(Member).where(Member.household_id==house,Member.role=="owner"))
    staff=s.scalar(select(Member).where(Member.household_id==house,Member.role=="maid"))
    kitchen=s.scalar(select(Room).where(Room.household_id==house,Room.name=="Kitchen"))
    assert owner and staff and kitchen
    owner_id,staff_id,kitchen_id=owner.id,staff.id,kitchen.id
client=TestClient(app)
owner_headers={"X-Member-Id":owner_id}
staff_headers={"X-Member-Id":staff_id}

with tempfile.TemporaryDirectory(prefix="homeos-ci-private-") as temporary:
    env=os.environ.copy()
    env["DATABASE_URL"]=os.environ["MEMORY_DATABASE_URL"]
    env["PYTHONPATH"]=str(repo/"services/memory")
    env["PRIVATE_MEDIA_ROOT"]=temporary
    env["HOMEOS_VISION_API_KEY"]=""  # CI must never disclose images to an external provider.
    # Memory service is started as a separate process because both apps use an app module.
    with open(Path(temporary)/"memory-service.log","wb") as logfile:
        service=subprocess.Popen(
            [sys.executable,"-m","uvicorn","app:app","--host","127.0.0.1","--port",str(port)],
            cwd=repo/"services/memory",env=env,stdout=logfile,stderr=subprocess.STDOUT)
        try:
            for attempt in range(80):
                if service.poll() is not None:
                    raise RuntimeError("Private memory service exited before ready")
                try:
                    result=httpx.get(base+"/health",timeout=1.0,trust_env=False)
                    if result.status_code==200:break
                except httpx.RequestError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Private memory service did not become ready")

            # Owner-only scope. Browser identity never receives private bearer token.
            assert client.get("/api/memory/visual/inspection-locations",
                headers=staff_headers).status_code==403
            locations=client.get("/api/memory/visual/inspection-locations",
                headers=owner_headers)
            assert locations.status_code==200,locations.text
            linked=locations.json()["locations"]
            assert linked
            kitchen_entity=next((loc for loc in linked if loc["name"]=="Kitchen"),None)
            assert kitchen_entity,kitchen_entity
            kitchen_graph=kitchen_entity["id"]
            assert kitchen_entity["type"]=="ROOM"
            bad=client.post("/api/memory/visual/inspection-upload",headers=owner_headers,
                data={"location_entity_id":kitchen_graph},
                files={"file":("secret.txt",b"not an image","text/plain")})
            assert bad.status_code==415,bad.text

            image=Image.new("RGB",(24,24),(90,135,170))
            buffer=io.BytesIO()
            image.save(buffer,format="PNG")
            raw=buffer.getvalue()

            denied=client.post("/api/memory/visual/inspection-upload",headers=staff_headers,
                data={"location_entity_id":kitchen_graph},
                files={"file":("room.png",raw,"image/png")})
            assert denied.status_code==403,denied.text

            with psycopg.connect(os.environ["MEMORY_DATABASE_URL"]) as conn:
                before=conn.execute("""SELECT COUNT(*) FROM memory_observations
                    WHERE household_id=%s""",(house,)).fetchone()[0]

            uploaded=client.post("/api/memory/visual/inspection-upload",headers=owner_headers,
                data={"location_entity_id":kitchen_graph},
                files={"file":("kitchen.png",raw,"image/png")})
            assert uploaded.status_code==200,uploaded.text
            info=uploaded.json()
            assert info["status"]=="UPLOADED"
            assert info["location"]=="Kitchen"
            sid,mid=info["session_id"],info["media_id"]
            with psycopg.connect(os.environ["MEMORY_DATABASE_URL"]) as conn:
                link=conn.execute("""SELECT m.storage_key,vs.expected_location_id
                    FROM visual_session_media sm
                    JOIN visual_sessions vs ON vs.id=sm.session_id AND vs.household_id=sm.household_id
                    JOIN memory_media m ON m.id=sm.media_id AND m.household_id=sm.household_id
                    WHERE sm.household_id=%s AND sm.session_id=%s AND sm.media_id=%s""",
                    (house,sid,mid)).fetchone()
                assert link
                assert str(link[1])==kitchen_graph
                assert (Path(temporary)/link[0]).read_bytes()==raw

            # User must explicitly consent AFTER the private upload.
            no_consent=client.post("/api/memory/visual/inspection-analyze",
                headers=owner_headers,
                json={"session_id":sid,"media_id":mid,"consent_to_external_ai_processing":False})
            assert no_consent.status_code==422,no_consent.text
            denied_consent=client.post("/api/memory/visual/inspection-analyze",
                headers=staff_headers,
                json={"session_id":sid,"media_id":mid,"consent_to_external_ai_processing":True})
            assert denied_consent.status_code==403,denied_consent.text
            unknown=client.post("/api/memory/visual/inspection-analyze",headers=owner_headers,
                json={"session_id":str(uuid.uuid4()),"media_id":mid,
                      "consent_to_external_ai_processing":True})
            assert unknown.status_code==404,unknown.text

            # Configured privacy gate: no external vision token, so analysis cannot proceed.
            not_configured=client.post("/api/memory/visual/inspection-analyze",
                headers=owner_headers,json={"session_id":sid,"media_id":mid,
                 "consent_to_external_ai_processing":True})
            assert not_configured.status_code==503,not_configured.text
            with psycopg.connect(os.environ["MEMORY_DATABASE_URL"]) as conn:
                after=conn.execute("""SELECT COUNT(*) FROM memory_observations
                    WHERE household_id=%s""",(house,)).fetchone()[0]
            assert before==after,"Photo upload or failed analysis should not invent observations"
            print("M3F owner photo upload, private evidence, consent and disabled-provider safety passed")
        except Exception:
            logfile.flush()
            print((Path(temporary)/"memory-service.log").read_text(errors="replace")[-6000:])
            raise
        finally:
            service.terminate()
            try:
                service.wait(timeout=10)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait(timeout=5)
