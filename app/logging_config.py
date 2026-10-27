import json
import logging
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Only our controlled event messages are logged; never exception text/tracebacks.
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "event": record.getMessage(),
            }
        )


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    log = logging.getLogger("moderation")
    log.handlers = [handler]
    log.setLevel(level)
    log.propagate = False
    # Third-party HTTP diagnostics can include URLs/authorization details.
    for name in ("httpx", "httpcore", "huggingface_hub", "transformers"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
