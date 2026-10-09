"""CI-ONLY isolated vision provider substitution.

Never included in the HomeOS Docker images. No external network model requests.
Refuses startup unless disposable test mode and the literal CI sentinel are set.
"""
import json
import os

assert os.getenv("HOMEOS_TEST_MODE")=="true", "CI mock must never run on a real household"
assert os.getenv("HOMEOS_VISION_API_KEY")=="CI_FAKE_VISION_ONLY", "CI mock credential sentinel required"

from app import app
import vision_analysis


def scripted_infer(encoded,context):
    """Detections are synthetic; the JPEG contents are intentionally NOT recognized."""
    room=json.loads(context).get("expected_location","")
    if "Kitchen" in room:
        labels=("electric kettle","bread toaster","refrigerator")
    elif "Store Room" in room:
        labels=("electric kettle",)
    else:
        labels=()
    return vision_analysis.VisionResult(
        detections=[
            vision_analysis.Detection(
                label=label,description="Synthetic CI detection; not inferred from pixels",
                confidence=0.89)
            for label in labels
        ],
        inspection_notes="Synthetic CI fixture; not a real visual recognition result")


vision_analysis.infer=scripted_infer
