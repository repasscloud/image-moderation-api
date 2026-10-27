import logging
import time
from uuid import uuid4
from app.config import Settings
from app.engines.base import Engine
from app.errors import APIError, EngineError
from app.services.images import validate_image

NAMES = ("nudenet", "nsfw", "arachnid")
log = logging.getLogger("moderation")


class Scanner:
    def __init__(self, settings: Settings, engines: dict[str, Engine] | None = None):
        self.settings = settings
        self.enabled = {
            "nudenet": settings.enable_nudenet,
            "nsfw": settings.enable_nsfw,
            "arachnid": settings.arachnid_enabled,
        }
        if engines is None:
            from app.engines.nudenet_engine import NudeNetEngine
            from app.engines.nsfw_engine import NSFWEngine
            from app.engines.arachnid_engine import ArachnidEngine

            factories = {"nudenet": NudeNetEngine, "nsfw": NSFWEngine, "arachnid": ArachnidEngine}
            engines = {name: factory(settings) for name, factory in factories.items() if self.enabled[name]}
        self.engines = engines
        self.ready = dict.fromkeys(NAMES, False)

    def load(self) -> None:
        if not self.settings.api_key:
            log.warning("API authentication is disabled.")
            log.warning("Do not expose this service to the public internet.")
        if bool(self.settings.arachnid_api_username) != bool(self.settings.arachnid_api_password):
            log.warning("Project Arachnid disabled: both credentials are required.")
        for name in NAMES:
            if not self.enabled[name]:
                log.info("%s disabled (not configured).", name)
                continue
            try:
                self.engines[name].load()
                self.ready[name] = True
                log.info("%s enabled and ready.", name)
            except Exception:
                log.error("%s initialization failed.", name)

    def select(self, requested: str | None) -> list[str]:
        if requested is None:
            names = [name for name in NAMES if self.enabled[name]]
        else:
            names = list(dict.fromkeys(part.strip() for part in requested.split(",")))
            if any(name not in NAMES for name in names):
                raise APIError(422, "invalid_engine", "Select nudenet, nsfw or arachnid.")
            if any(not self.enabled[name] for name in names):
                raise APIError(422, "engine_disabled", "An explicitly requested engine is disabled.")
        if not names:
            raise APIError(503, "no_engines", "No scanning engines are enabled.")
        return names

    def scan(self, data: bytes, filename: str | None, selected: list[str]) -> dict:
        started = time.monotonic()
        validate_image(data, self.settings)
        results = {}
        for name in NAMES:
            if not self.enabled[name]:
                results[name] = {"status": "disabled"}
            elif name not in selected:
                results[name] = {"status": "not_requested"}
            else:
                before = time.monotonic()
                try:
                    if not self.ready[name]:
                        raise EngineError("engine_unavailable", "Engine is not ready.")
                    output = self.engines[name].scan(data)
                    results[name] = {**output, "status": "completed"}
                except Exception as exc:
                    code, message = (
                        (exc.code, exc.message)
                        if isinstance(exc, EngineError)
                        else ("inference_failed", "Engine inference failed.")
                    )
                    results[name] = {"status": "failed", "error": {"code": code, "message": message}}
                    log.warning("%s scan failed (%s).", name, code)
                results[name]["inference_time_ms"] = round((time.monotonic() - before) * 1000, 3)
        successes = sum(results[n]["status"] == "completed" for n in selected)
        status = "completed" if successes == len(selected) else "partial" if successes else "failed"
        return {
            "scan_id": str(uuid4()),
            "status": status,
            "filename": filename,
            "processing_time_ms": round((time.monotonic() - started) * 1000, 3),
            "results": results,
        }

    def close(self) -> None:
        for name, engine in self.engines.items():
            if self.enabled[name]:
                try:
                    engine.close()
                except Exception:
                    log.warning("%s shutdown failed.", name)
