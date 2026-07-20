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


class ActionType(str, Enum):
    inspect_local = "inspect_local"
    analyze_local = "analyze_local"
    draft_local = "draft_local"
    write_local = "write_local"
    send_external = "send_external"
    schedule_external = "schedule_external"
    share_external = "share_external"
    upload_external = "upload_external"
    publish_external = "publish_external"
    delete_local = "delete_local"
    overwrite_local = "overwrite_local"
    execute_command = "execute_command"
    financial_action = "financial_action"
    credential_access = "credential_access"
    unsupported = "unsupported"


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=10_000, strict=True)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, strict=True)
    title: str = Field(min_length=1, max_length=200, strict=True)
    description: str = Field(min_length=1, max_length=2_000, strict=True)
    action_type: ActionType
    risk_level: RiskLevel
    requires_approval: bool = Field(strict=True)
    policy_reason: str = Field(min_length=1, max_length=200, strict=True)


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[PlanStep] = Field(min_length=1, max_length=50)
