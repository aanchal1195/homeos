"""Persist vision proposals as PENDING observations."""
from psycopg.types.json import Jsonb

def save_one(conn,house,job,row,frame,item):
    frame_id,timestamp,_=frame
    source="PHOTO" if row["content_type"].startswith("image/") else "VIDEO"
    ev=conn.execute(
        "INSERT INTO memory_evidence(household_id,source_type,source_ref) VALUES(%s,%s,%s) RETURNING id",
        (house,source,"multimodal-worker:"+str(job["id"]))).fetchone()["id"]
    payload={"finding_type":item.finding_type,"label":item.label,
             "summary":item.summary,"visible_condition":item.visible_condition,
             "severity":item.severity,"frame_index":item.frame_index,
             "requires_human_review":True}
    return ev,payload
