import uvicorn
from pydantic import ValidationError
from app.config import Settings


def main() -> None:
    try:
        settings = Settings()
    except ValidationError:
        # Pydantic's default exception text includes raw input values.
        raise SystemExit("Invalid service configuration; check documented settings.") from None
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=1,
        access_log=False,
        log_level=settings.log_level.lower(),
        timeout_keep_alive=5,
        timeout_graceful_shutdown=600,
        limit_concurrency=32,
    )


if __name__ == "__main__":
    main()
