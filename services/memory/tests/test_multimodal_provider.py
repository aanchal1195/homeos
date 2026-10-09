"""Provider output is validated before it can become a memory observation."""
import io
import json
import uuid
import pytest
from pydantic import ValidationError
from multimodal_provider import ModelResponse,ProviderError,infer,make_payload

class FakeResponse:
    def __init__(self,data):
        self.buffer=io.BytesIO(data)
    def __enter__(self):
        return self
    def __exit__(self,*_):
        return False
    def read(self,n):
        return self.buffer.read(n)

def test_provider_requires_frame_reference_and_bounded_confidence():
    with pytest.raises(ValidationError):
        ModelResponse.model_validate({"findings":[{
            "frame_index":0,"finding_type":"VISIBLE_OBJECT",
            "label":"sink","summary":"Sink","confidence":1.2}]})

def test_provider_rejects_hallucinated_frame_index(monkeypatch):
    monkeypatch.setenv("HOMEOS_VISION_API_KEY","fake-test-key")
    response={"choices":[{"message":{"content":json.dumps({"findings":[{
        "frame_index":7,"finding_type":"VISIBLE_OBJECT","label":"sink",
        "summary":"Visible sink","confidence":0.7}]})}}]}
    monkeypatch.setattr("multimodal_provider.urllib.request.urlopen",
        lambda *_args,**_kwargs:FakeResponse(json.dumps(response).encode()))
    with pytest.raises(ProviderError,match="PROVIDER_FRAME_INDEX_INVALID"):
        infer("Kitchen",[(uuid.uuid4(),0,b"jpeg-test")],"gpt-4.1-mini")

def test_provider_payload_marks_image_text_untrusted():
    body=make_payload("Kitchen",[(uuid.uuid4(),100,b"jpeg-test")],"gpt-4.1-mini")
    assert "untrusted" in body["messages"][0]["content"]
    assert "Frame 0 at 100 ms"==body["messages"][1]["content"][1]["text"]
