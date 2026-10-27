from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

EngineName = Literal["nudenet", "nsfw", "arachnid"]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class Detection(BaseModel):
    label: str = Field(alias="class")
    score: float
    box: list[int] = Field(min_length=4, max_length=4)


class EngineResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["completed", "failed", "disabled", "not_requested"]
    inference_time_ms: float | None = None
    error: ErrorDetail | None = None
    detections: list[Detection] | None = None
    classification: str | bool | None = Field(
        None, description="Freepik library boolean or verbatim Shield classification string."
    )
    is_nsfw: bool | None = None
    probabilities: list[dict[str, float]] | None = Field(
        None,
        description="Freepik original cumulative score dictionaries; not an exclusive class distribution.",
    )
    pdq_quality: int | None = None
    match_type: str | None = None
    raw: dict[str, Any] | None = None


class ScanResponse(BaseModel):
    scan_id: UUID
    status: Literal["completed", "partial", "failed"]
    filename: str | None
    processing_time_ms: float
    results: dict[EngineName, EngineResult]


class Readiness(BaseModel):
    ready: bool
    engines: dict[EngineName, Literal["ready", "failed", "disabled"]]
