"""Run the opt-in HomeOS multimodal worker separately from FastAPI."""
import argparse
import logging
import os
import time
import uuid
from multimodal_processor import process_once

LOG=logging.getLogger("homeos.multimodal")

def main():
    parser=argparse.ArgumentParser(description="HomeOS private multimodal worker")
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--poll-seconds",type=float,default=3)
    args=parser.parse_args()
    if args.poll_seconds<1:
        parser.error("--poll-seconds must be >= 1")
    if not os.getenv("HOMEOS_VISION_API_KEY"):
        parser.error("HOMEOS_VISION_API_KEY is required")
    logging.basicConfig(level=logging.INFO)
    house=str(uuid.UUID(os.environ["HOMEOS_HOUSEHOLD_ID"]))
    model=os.getenv("HOMEOS_VISION_MODEL","gpt-4.1-mini")
    while True:
        outcome=process_once(house,model)
        if outcome:
            LOG.info("Job %s: %s",outcome["job_id"],outcome["status"])
        if args.once:
            break
        if not outcome:
            time.sleep(args.poll_seconds)

if __name__=="__main__":
    main()
