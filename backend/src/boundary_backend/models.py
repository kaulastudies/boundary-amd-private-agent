"""Typed API request and response models."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    model: str
    remote_apis_enabled: Literal[False] = False


class ModelHealthResponse(BaseModel):
    model_name: str
    available: bool
    local_only: Literal[True] = True


class RiskLevel(str, Enum):
    safe = "safe"
    review = "review"
    sensitive = "sensitive"
    destructive = "destructive"
    blocked = "blocked"


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=10_000, strict=True)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, strict=True)
    title: str = Field(min_length=1, max_length=200, strict=True)
    description: str = Field(min_length=1, max_length=2_000, strict=True)
    risk_level: RiskLevel
    requires_approval: bool = Field(strict=True)


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[PlanStep] = Field(min_length=1, max_length=50)
