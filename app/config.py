from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    api_key: SecretStr | None = None
    arachnid_api_username: SecretStr | None = None
    arachnid_api_password: SecretStr | None = None
    host: str = "0.0.0.0"
    port: int = Field(8080, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    enable_nudenet: bool = True
    enable_nsfw: bool = True
    max_image_size_mb: int = Field(20, ge=1, le=100)
    max_image_pixels: int = Field(40_000_000, ge=1, le=100_000_000)
    max_image_dimension: int = Field(8192, ge=1, le=16384)
    max_concurrent_scans: int = Field(1, ge=1, le=4)
    upload_timeout_seconds: float = Field(30, gt=0, le=300)
    scan_timeout_seconds: float = Field(120, gt=0, le=600)
    arachnid_timeout_seconds: float = Field(15, gt=0, le=60)
    nudenet_confidence_threshold: float = Field(0, ge=0, le=1)
    model_cache: Path = Path("model-cache")
    nsfw_dtype: Literal["float32", "bfloat16"] = "float32"
    enable_docs: bool = True
    enable_processing: bool = False
    clamav_host: str = "clamav"
    clamav_port: int = Field(3310, ge=1, le=65535)
    clamav_timeout_seconds: float = Field(30, gt=0, le=120)
    clamav_max_signature_age_hours: int = Field(72, ge=1, le=168)
    processing_min_side: int = Field(200, ge=1, le=8192)
    processing_max_output_mb: int = Field(20, ge=1, le=40)
    processing_drain_file: Path = Path("/run/processor-control/drain")

    @model_validator(mode="after")
    def processing_configuration(self):
        if self.enable_processing and (
            not self.api_key
            or len(self.api_key.get_secret_value()) < 32
            or not self.arachnid_enabled
            or not self.enable_nudenet
            or not self.enable_nsfw
        ):
            raise ValueError("Processing requires authentication and all mandatory engines")
        return self

    allowed_image_hosts: Annotated[tuple[str, ...], NoDecode] = ()
    url_download_timeout_seconds: float = Field(30, gt=0, le=120)

    @field_validator("allowed_image_hosts", mode="before")
    @classmethod
    def validate_hosts(cls, value: str | tuple[str, ...]) -> tuple[str, ...]:
        import ipaddress
        import re

        if isinstance(value, (tuple, list)):
            value = ",".join(value)
        if not isinstance(value, str):
            raise ValueError("Invalid allowed image hostnames")
        if not value.strip():
            return ()
        hosts = []
        for part in value.split(","):
            host = part.strip().lower()
            try:
                host = host.encode("idna").decode("ascii")
            except UnicodeError:
                raise ValueError("Invalid allowed image hostname") from None
            if (
                len(host) > 253
                or "." not in host
                or any(
                    not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in host.split(".")
                )
            ):
                raise ValueError(
                    "Use comma-separated exact DNS hostnames without schemes, ports or wildcards"
                )
            try:
                ipaddress.ip_address(host)
            except ValueError:
                hosts.append(host)
            else:
                raise ValueError("Use DNS hostnames, not IP addresses")
        return tuple(dict.fromkeys(hosts))

    @field_validator("api_key", "arachnid_api_username", "arachnid_api_password", mode="before")
    @classmethod
    def blank_secret(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def arachnid_enabled(self) -> bool:
        return self.arachnid_api_username is not None and self.arachnid_api_password is not None

    @property
    def max_image_bytes(self) -> int:
        return self.max_image_size_mb * 1024 * 1024
