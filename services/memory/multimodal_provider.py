"""Schema-validated multimodal provider adapter. No graph writes."""
import base64
import json
import os
import urllib.request
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class ProviderError(Exception):
    def __init__(self, code, retryable=True):
        super().__init__(code)
        self.code, self.retryable = code, retryable

class ModelFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame_index: int = Field(ge=0)
    finding_type: Literal["VISIBLE_OBJECT", "VISIBLE_CONDITION"]
    label: str = Field(min_length=2, max_length=100)
    summary: str = Field(min_length=1, max_length=500)
    visible_condition: str | None = Field(default=None, max_length=300)
    severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"] = "INFO"
    confidence: float = Field(ge=0, le=1)

class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    findings: list[ModelFinding] = Field(default_factory=list, max_length=100)
    inspection_notes: str = Field(default="", max_length=500)

MAX_RESPONSE_BYTES = 200_000
