"""Complete leased jobs atomically, without changing confirmed graph assertions."""
from app import db
from multimodal_provider import ProviderError
from multimodal_lease import guard
from multimodal_persist import save_one
from multimodal_observation import persist

def publish(house,job,frames,response):
    with db() as conn:
        row=guard(conn,house,job)
        if row["status"]=="COMPLETED":
            return {"status":"COMPLETED","already_completed":True}
        for item in response.findings:
            if item.frame_index>=len(frames):
                raise ProviderError("PROVIDER_FRAME_INDEX_INVALID")
            frame=frames[item.frame_index]
            ev,payload=save_one(conn,house,job,row,frame,item)
            persist(conn,house,job,row,frame,item,ev,payload)
        conn.execute(
            """UPDATE visual_analysis_jobs SET status='COMPLETED',finished_at=now(),
                 lease_token=NULL,lease_expires_at=NULL,error_code=NULL,error_detail=NULL
               WHERE household_id=%s AND id=%s""",
            (house,job["id"]))
    return {"status":"COMPLETED","findings":len(response.findings)}
