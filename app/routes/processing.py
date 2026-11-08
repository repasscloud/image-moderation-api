import asyncio
import json
import secrets
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartParser, MultiPartException

from app.errors import APIError
from app.services.processing import process

router = APIRouter()


class ProcessingJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocolVersion: Literal[1]
    jobId: UUID
    imageId: UUID
    sourceSha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["profile", "album", "chat"]

    @field_validator("protocolVersion", mode="before")
    @classmethod
    def strict_protocol(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported protocol version")
        return value


def multipart_result(manifest, variants):
    boundary = "result-" + secrets.token_hex(24)
    parts = []
    payloads = [
        (
            "manifest",
            "application/json",
            json.dumps(manifest, allow_nan=False, separators=(",", ":")).encode(),
        )
    ]
    payloads += [(name, "image/webp", value) for name, value in variants.items()]
    for name, content_type, value in payloads:
        header = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
        if name != "manifest":
            header += f'; filename="{name}.webp"'
        parts.extend([(header + f"\r\nContent-Type: {content_type}\r\n\r\n").encode(), value, b"\r\n"])
    parts.append(f"--{boundary}--\r\n".encode())
    return Response(
        b"".join(parts),
        media_type=f"multipart/form-data; boundary={boundary}",
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/v1/process",
    response_class=Response,
    responses={
        200: {
            "description": "Manifest JSON field plus zero or two bounded WebP file parts",
            "content": {"multipart/form-data": {"schema": {"type": "string", "format": "binary"}}},
        },
        401: {"description": "Missing or invalid processor authentication"},
        409: {"description": "Source digest mismatch"},
        413: {"description": "Input or output resource limit exceeded"},
        415: {"description": "Unsupported image format or animation"},
        422: {"description": "Invalid job/form or image too small"},
        503: {"description": "Draining or capacity unavailable"},
        504: {"description": "Processing deadline exceeded; capacity retained until completion"},
    },
    openapi_extra={
        "security": [{"BearerAuth": []}],
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file", "job"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "job": {
                                "type": "string",
                                "description": "Strict ProcessingJob JSON, protocolVersion 1",
                            },
                        },
                    }
                }
            },
        },
    },
)
async def processing(request: Request):
    settings = request.app.state.settings
    if not settings.enable_processing:
        raise APIError(404, "not_found", "Processing is not enabled.")
    if settings.processing_drain_file.exists():
        raise APIError(503, "draining", "Processor is draining; retry later.")
    parser = MultiPartParser(request.headers, request.stream(), max_files=1, max_fields=1, max_part_size=4096)
    parser.spool_max_size = settings.max_image_bytes + 65536
    try:
        form = await parser.parse()
    except (MultiPartException, ValueError):
        raise APIError(400, "invalid_multipart", "Expected file and job fields.") from None
    try:
        if (
            len(form.multi_items()) != 2
            or set(form) != {"file", "job"}
            or not isinstance(form.get("file"), UploadFile)
            or not isinstance(form.get("job"), str)
        ):
            raise APIError(422, "invalid_upload", "Expected one file and one job field.")
        try:
            job = ProcessingJob.model_validate_json(form["job"])
        except (ValidationError, ValueError):
            raise APIError(422, "invalid_job", "Processing job is invalid.") from None
        data = await form["file"].read(settings.max_image_bytes + 1)
        if len(data) > settings.max_image_bytes:
            raise APIError(413, "image_too_large", "Image exceeds the upload limit.")
    finally:
        await form.close()
    future = request.app.state.executor.submit(
        process, data, job, request.app.state.scanner, request.app.state.malware, settings
    )
    request.scope["scan_future"] = future
    wrapped = asyncio.wrap_future(future)
    wrapped.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
    try:
        manifest, variants = await asyncio.wait_for(asyncio.shield(wrapped), settings.scan_timeout_seconds)
    except TimeoutError:
        raise APIError(
            504, "scan_timeout", "Processing timed out; capacity remains occupied until work finishes."
        ) from None
    return multipart_result(manifest, variants)
