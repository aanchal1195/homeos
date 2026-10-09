"""Successful and empty multimodal jobs must remain review-only."""
import os
from app import db
from multimodal_provider import ModelResponse
from multimodal_processor import process_once
from m3d_fixtures import auth,client,prepared,MODEL

def test_frame_grounded_findings_are_pending(client,auth,monkeypatch):
    room,jid=prepared(client,auth)
    house=os.environ["HOMEOS_HOUSEHOLD_ID"]
    with db() as conn:
        before=conn.execute("SELECT count(*) AS n FROM memory_assertions WHERE household_id=%s",(house,)).fetchone()["n"]
    result=ModelResponse(findings=[{"frame_index":0,"finding_type":"VISIBLE_OBJECT",
        "label":"refrigerator","summary":"Refrigerator visible","confidence":0.83}])
    monkeypatch.setattr("multimodal_processor.infer",lambda *_:result)
    outcome=process_once(house,MODEL)
    assert outcome["status"]=="COMPLETED" and outcome["findings"]==1
    details=client.get(f"/api/v1/visual/analysis/jobs/{jid}",headers=auth["owner"]).json()
    oid=details["findings"][0]["observation_id"]
    with db() as conn:
        obs=conn.execute("SELECT status,subject_id,frame_timestamp_ms,payload FROM memory_observations WHERE household_id=%s AND id=%s",(house,oid)).fetchone()
        after=conn.execute("SELECT count(*) AS n FROM memory_assertions WHERE household_id=%s",(house,)).fetchone()["n"]
    assert obs["status"]=="PENDING" and str(obs["subject_id"])==room
    assert obs["frame_timestamp_ms"]==0
    assert obs["payload"]["requires_human_review"] is True
    assert before==after

def test_empty_result_completes_without_false_observations(client,auth,monkeypatch):
    _,jid=prepared(client,auth)
    monkeypatch.setattr("multimodal_processor.infer",lambda *_:ModelResponse(findings=[]))
    outcome=process_once(os.environ["HOMEOS_HOUSEHOLD_ID"],MODEL)
    assert outcome["status"]=="COMPLETED" and outcome["findings"]==0
    details=client.get(f"/api/v1/visual/analysis/jobs/{jid}",headers=auth["owner"]).json()
    assert details["findings"]==[]
