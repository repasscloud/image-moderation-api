import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from app.config import Settings
from app.errors import APIError
from app.logging_config import configure_logging
from app.middleware import ScanGuard, SanitizedErrors
from app.routes import health, scans
from app.services.scanner import Scanner


def create_app(settings: Settings | None = None, engines=None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inference")
        scanner = Scanner(settings, engines)
        app.state.settings, app.state.scanner, app.state.executor = settings, scanner, executor
        await asyncio.wrap_future(executor.submit(scanner.load))
        try:
            yield
        finally:
            # Queue cleanup behind any in-flight native work, then join the executor.
            await asyncio.wrap_future(executor.submit(scanner.close))
            await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)

    app = FastAPI(
        title="Image Moderation API",
        version="1.0.0",
        lifespan=lifespan,
        description="Objective model predictions and known-content matching. No moderation decisions.",
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    app.add_middleware(ScanGuard, settings=settings)
    app.add_middleware(SanitizedErrors)
    app.include_router(health.router)
    app.include_router(scans.router)

    @app.exception_handler(APIError)
    async def api_error(request: Request, exc: APIError):
        return JSONResponse(exc.body(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            APIError(422, "validation_error", "Request validation failed.").body(), status_code=422
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(
            APIError(exc.status_code, "http_error", "Request could not be processed.").body(),
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logging.getLogger("moderation").error("Unexpected request failure.")
        return JSONResponse(
            APIError(500, "internal_error", "Request could not be processed.").body(), status_code=500
        )

    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "description": "Required on scan endpoints when API_KEY is configured.",
        }
        return schema

    app.openapi = openapi
    return app
