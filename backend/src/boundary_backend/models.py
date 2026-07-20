"""Typed API request and response models."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    task: str = Field(min_length=1, max_length=10_000)


class PlanStep(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    risk_level: RiskLevel
    requires_approval: bool

    @model_validator(mode="after")
    def sensitive_steps_require_approval(self) -> "PlanStep":
        if self.risk_level in {
            RiskLevel.sensitive,
            RiskLevel.destructive,
            RiskLevel.blocked,
        } and not self.requires_approval:
            raise ValueError(
                "sensitive, destructive, and blocked steps require approval"
            )
        return self


class PlanResponse(BaseModel):
    steps: list[PlanStep] = Field(min_length=1, max_length=50)
