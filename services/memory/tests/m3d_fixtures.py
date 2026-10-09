"""M3D integration helpers reuse the existing visual worker test fixtures."""
import uuid
from test_visual_analysis_integration import auth, client, _session_media

MODEL="gpt-4.1-mini"

def prepared(client,auth):
    owner,worker=auth["owner"],auth["worker"]
    room,sid,mid=_session_media(client,owner)
    queued=client.post(f"/api/v1/visual/sessions/{sid}/analysis",headers=owner,json={
        "media_id":mid,"analyzer_name":"openai","analyzer_version":MODEL,
        "idempotency_key":"m3d-"+uuid.uuid4().hex})
    assert queued.status_code==201,queued.text
    jid=queued.json()["id"]
    ready=client.post(f"/api/v1/visual/analysis/jobs/{jid}/prepare",
        headers=worker,json={"frame_count":1})
    assert ready.status_code==200,ready.text
    return room,jid
