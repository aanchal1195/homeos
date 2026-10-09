"""Create pending observation and link it to an analysis frame."""
from psycopg.types.json import Jsonb

def persist(conn,house,job,row,frame,item,evidence,payload):
    frame_id,timestamp,_=frame
    oid=conn.execute(
        """INSERT INTO memory_observations
           (household_id,subject_id,predicate,evidence_id,payload,confidence,
            media_id,frame_timestamp_ms,model_version)
           VALUES(%s,%s,'RELATED_TO',%s,%s,%s,%s,%s,%s) RETURNING id""",
        (house,row["expected_location_id"],evidence,Jsonb(payload),item.confidence,
         row["media_id"],timestamp,row["analyzer_name"]+":"+row["analyzer_version"])
    ).fetchone()["id"]
    conn.execute(
        """INSERT INTO visual_analysis_findings
           (household_id,job_id,frame_id,observation_id,finding_type,summary,severity,confidence)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
        (house,job["id"],frame_id,oid,item.finding_type,item.summary,item.severity,item.confidence))
