from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.schemas import Readiness

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=Readiness, responses={503: {"model": Readiness}})
def ready(request: Request):
    scanner = request.app.state.scanner
    engines = {
        name: "disabled" if not enabled else "ready" if scanner.ready[name] else "failed"
        for name, enabled in scanner.enabled.items()
    }
    is_ready = all(state != "failed" for state in engines.values())
    return JSONResponse({"ready": is_ready, "engines": engines}, status_code=200 if is_ready else 503)


@router.get("/v1/engines")
def engines(request: Request) -> dict:
    scanner = request.app.state.scanner
    return {
        "engines": {
            name: {"enabled": enabled, "ready": scanner.ready[name]}
            for name, enabled in scanner.enabled.items()
        }
    }
