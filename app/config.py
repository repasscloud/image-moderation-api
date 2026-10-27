from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
