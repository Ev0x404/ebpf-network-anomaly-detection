from pydantic import BaseModel, Field
from typing import Any


class ServiceStatus(BaseModel):
    name: str
    running: bool
    detail: str | None = None


class ReportItem(BaseModel):
    name: str
    path: str
    size_bytes: int
    modified_at: float
    preview: str | None = None


class DetectionItem(BaseModel):
    timestamp: str | None = None
    src_ip: str | None = None
    type: str | None = None
    severity: str | None = None
    score: float | None = None
    detail: str | None = None
    raw: dict[str, Any] | None = None


class DetectedIpItem(BaseModel):
    src_ip: str
    count: int
    first_seen: str | None = None
    last_seen: str | None = None
    max_severity: str | None = None
    latest_type: str | None = None
    latest_score: float | None = None
    latest_detail: str | None = None
    types: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str
    model: str | None = None


class ChatResponse(BaseModel):
    response: str
    model: str


class TestCatalogItem(BaseModel):
    id: str
    name: str
    description: str
    command: str


class TestRunRequest(BaseModel):
    test_id: str


class TestRunResponse(BaseModel):
    success: bool
    stdout: str
    stderr: str
    return_code: int
