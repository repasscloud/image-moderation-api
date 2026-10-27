import secrets
from app.config import Settings
from app.errors import APIError


def authenticate(settings: Settings, header: str | None) -> None:
    if settings.api_key is None:
        return
    scheme, _, value = (header or "").partition(" ")
    # Compare bytes to support non-ASCII configured secrets without TypeError.
    valid = secrets.compare_digest(value.encode(), settings.api_key.get_secret_value().encode())
    if scheme.lower() != "bearer" or not valid:
        raise APIError(401, "unauthorized", "A valid Bearer token is required.")
