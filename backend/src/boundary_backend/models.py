"""API response models."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    model: Literal["not-configured"] = "not-configured"
    remote_apis_enabled: Literal[False] = False
