"""Typed API request and response models."""

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class RunState(str, Enum):
    planned = "planned"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    rejected = "rejected"
    executing = "executing"
    completed = "completed"
    failed = "failed"
    blocked = "blocked"


class StepState(str, Enum):
    planned = "planned"
    ready = "ready"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    rejected = "rejected"
    executed = "executed"
    failed = "failed"
    blocked = "blocked"
    skipped = "skipped"


class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


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

    @model_validator(mode="after")
    def step_ids_must_be_unique(self) -> "PlanResponse":
        identifiers = [step.id for step in self.steps]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("plan step ids must be unique")
        return self


class SimulatedToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulated: Literal[True] = True
    no_external_side_effect: Literal[True] = True
    summary: str = Field(min_length=1, max_length=500)
    artifact_type: str = Field(min_length=1, max_length=100)


class RunStepResponse(PlanStep):
    state: StepState
    approval_id: Optional[str] = None
    tool_result: Optional[SimulatedToolResult] = None


class RunResponse(BaseModel):
    run_id: str
    state: RunState
    steps: list[RunStepResponse]


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(min_length=1, max_length=200, strict=True)
    reason: Optional[str] = Field(default=None, max_length=500)


class ApprovalResponse(BaseModel):
    approval_id: str
    run_id: str
    step_id: str
    status: ApprovalStatus
    actor: Optional[str] = None
    reason: Optional[str] = None


class ConflictResponse(BaseModel):
    code: str
    message: str


class AuditEventResponse(BaseModel):
    event_id: str
    timestamp_utc: str
    run_id: str
    step_id: Optional[str] = None
    event_type: str
    actor: str
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    action_type: Optional[str] = None
    risk_level: Optional[str] = None
    policy_reason: Optional[str] = None
    metadata: dict[str, Any]
    previous_event_hash: Optional[str] = None
    event_hash: str


class AuditVerifyResponse(BaseModel):
    run_id: str
    valid: bool
    first_invalid_event_id: Optional[str] = None
