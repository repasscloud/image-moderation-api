import asyncio
from pathlib import PurePosixPath
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartParser, MultiPartException
from app.errors import APIError
from app.schemas import ErrorResponse, ScanResponse

router = APIRouter()
BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "engines": {
                            "type": "string",
                            "description": "Comma-separated: nudenet,nsfw,arachnid. Only on /v1/scan.",
                        },
                    },
                }
            }
        },
    },
    "security": [{"BearerAuth": []}, {}],
}
ERRORS = {code: {"model": ErrorResponse} for code in (400, 401, 408, 413, 415, 422, 500, 503, 504)}

ERRORS[502] = {"model": ScanResponse}


async def perform_scan(request: Request, engine: str | None = None):
    settings = request.app.state.settings
    scanner = request.app.state.scanner
    parser = MultiPartParser(request.headers, request.stream(), max_files=1, max_fields=1, max_part_size=4096)
    # All admitted bodies are bounded before parsing; keep spooled files in memory.
    parser.spool_max_size = settings.max_image_bytes + 65536
    try:
        form = await parser.parse()
    except (MultiPartException, ValueError):
        raise APIError(
            400, "invalid_multipart", "Expected one multipart file and optional engines field."
        ) from None
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile) or any(key not in {"file", "engines"} for key in form):
            raise APIError(422, "invalid_upload", "Provide exactly one file field named file.")
        requested = form.get("engines")
        if requested is not None and (not isinstance(requested, str) or engine is not None):
            raise APIError(422, "invalid_engine", "Engine selection is only supported on /v1/scan.")
        selected = scanner.select(engine if engine is not None else requested)
        data = await upload.read(settings.max_image_bytes + 1)
        if len(data) > settings.max_image_bytes:
            raise APIError(413, "image_too_large", "Image exceeds the upload limit.")
        # Return a bounded basename, but do not log it or accept it as a path.
        filename = PurePosixPath((upload.filename or "").replace("\\", "/")).name[:255] or None
    finally:
        await form.close()
    future = request.app.state.executor.submit(scanner.scan, data, filename, selected)
    request.scope["scan_future"] = future
    wrapped = asyncio.wrap_future(future)
    # Consume late exceptions after a timeout/disconnect without logging their contents.
    wrapped.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
    try:
        result = await asyncio.wait_for(asyncio.shield(wrapped), timeout=settings.scan_timeout_seconds)
    except TimeoutError:
        raise APIError(
            504, "scan_timeout", "Scan timed out; capacity remains occupied until inference finishes."
        ) from None
    return JSONResponse(result, status_code=502 if result["status"] == "failed" else 200)


@router.post("/v1/scan", response_model=ScanResponse, responses=ERRORS, openapi_extra=BODY)
async def scan(request: Request):
    return await perform_scan(request)


@router.post("/v1/scan/nudenet", response_model=ScanResponse, responses=ERRORS, openapi_extra=BODY)
async def scan_nudenet(request: Request):
    return await perform_scan(request, "nudenet")


@router.post("/v1/scan/nsfw", response_model=ScanResponse, responses=ERRORS, openapi_extra=BODY)
async def scan_nsfw(request: Request):
    return await perform_scan(request, "nsfw")


@router.post("/v1/scan/arachnid", response_model=ScanResponse, responses=ERRORS, openapi_extra=BODY)
async def scan_arachnid(request: Request):
    return await perform_scan(request, "arachnid")
