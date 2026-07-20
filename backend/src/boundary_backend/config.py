"""Local service configuration and endpoint safety validation."""

import ipaddress
import os
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

DEFAULT_MODEL_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_MODEL_NAME = "boundary-qwen3-8b"
DEFAULT_MODEL_TIMEOUT_SECONDS = 30.0


class InvalidModelEndpointError(ValueError):
    """Raised when a model endpoint is not demonstrably local."""


def validate_local_model_url(value: str) -> str:
    """Validate and normalize a loopback or private-address HTTP URL."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise InvalidModelEndpointError("model URL scheme must be http or https")
    if not parsed.hostname:
        raise InvalidModelEndpointError("model URL must include a hostname")
    if parsed.username or parsed.password:
        raise InvalidModelEndpointError("model URL must not contain credentials")
    try:
        parsed.port
    except ValueError as exc:
        raise InvalidModelEndpointError("model URL contains an invalid port") from exc
    if parsed.query or parsed.fragment:
        raise InvalidModelEndpointError("model URL must not contain a query or fragment")

    hostname = parsed.hostname.lower()
    if hostname != "localhost":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise InvalidModelEndpointError(
                "model URL must use localhost or an explicit private IP address"
            ) from exc
        if not (address.is_loopback or address.is_private or address.is_link_local):
            raise InvalidModelEndpointError(
                "model URL address must be loopback, private, or link-local"
            )
    return value.rstrip("/")


class Settings(BaseModel):
    app_name: str = "BOUNDARY AMD DevMaster Track 2"
    model_base_url: str = DEFAULT_MODEL_BASE_URL
    model_name: str = DEFAULT_MODEL_NAME
    model_timeout_seconds: float = Field(
        default=DEFAULT_MODEL_TIMEOUT_SECONDS, gt=0, le=600
    )
    remote_apis_enabled: bool = False

    @field_validator("model_base_url")
    @classmethod
    def model_endpoint_must_be_local(cls, value: str) -> str:
        return validate_local_model_url(value)

    @classmethod
    def from_environment(cls) -> "Settings":
        raw_timeout = os.getenv(
            "BOUNDARY_MODEL_TIMEOUT_SECONDS", str(DEFAULT_MODEL_TIMEOUT_SECONDS)
        )
        return cls(
            model_base_url=os.getenv(
                "BOUNDARY_MODEL_BASE_URL", DEFAULT_MODEL_BASE_URL
            ),
            model_name=os.getenv("BOUNDARY_MODEL_NAME", DEFAULT_MODEL_NAME),
            model_timeout_seconds=float(raw_timeout),
        )
