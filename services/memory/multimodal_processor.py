"""Process one leased vision job, with sanitized retryable failure states."""
import logging
from multimodal_provider import ProviderError, infer
from multimodal_job_store import claim_job, read_frames, record_failure
from multimodal_worker import publish

LOG=logging.getLogger("homeos.multimodal")

def process_once(house,model):
    job=claim_job(house,model)
    if job is None:
        return None
    try:
        location,frames=read_frames(house,job)
        response=infer(location,frames,model)
        result=publish(house,job,frames,response)
        return {"job_id":str(job["id"]),"status":result["status"],
                "findings":len(response.findings)}
    except ProviderError as exc:
        status=record_failure(house,job,exc)
        LOG.warning("Job %s: %s (%s)",job["id"],exc.code,status)
        return {"job_id":str(job["id"]),"status":status,"error_code":exc.code}
    except Exception:
        status=record_failure(house,job,ProviderError("WORKER_PROCESSING_FAILED"))
        LOG.exception("Job %s failed",job["id"])
        return {"job_id":str(job["id"]),"status":status,
                "error_code":"WORKER_PROCESSING_FAILED"}
