"""FastAPI application entry point."""

import logging

from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .config import Settings
from .local_model import (
    LocalModelClient,
    MalformedModelResponseError,
    ModelConnectionError,
    ModelTimeoutError,
    ModelUnavailableError,
    VLLMLocalModelClient,
)
from .models import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    ApprovalStatus,
    AuditEventResponse,
    AuditVerifyResponse,
    ConflictResponse,
    HealthResponse,
    ModelHealthResponse,
    PlanRequest,
    PlanResponse,
    RunResponse,
)
from .policy import enforce_action_policy
from .workflow import WorkflowConflictError, WorkflowDatabase

logger = logging.getLogger(__name__)


def _plan_prompt(task: str) -> str:
    return (
        "Create a concise execution plan for the user task below. Plan only; do not "
        "execute tools or claim actions were performed. Return one JSON object with a "
        "'steps' array. Every step must contain exactly: id, title, description, "
        "action_type, risk_level, requires_approval, policy_reason. action_type must "
        "use the provided schema taxonomy. risk_level must be one of safe, review, "
        "sensitive, destructive, blocked. Distinguish local drafting from sending, "
        "and suggesting a meeting time from scheduling it. policy_reason must be a "
        "short non-sensitive category explanation. Do not include reasoning or fields "
        f"outside the requested plan.\n\nUser task:\n{task}"
    )


def _validation_summary(exc: ValidationError) -> str:
    """Return field/type diagnostics without values, prompts, or model output."""
    summaries = []
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "root"
        summaries.append(f"field={location} type={error.get('type', 'unknown')}")
    return "; ".join(summaries[:5]) or "field=root type=unknown"


async def _generate_plan(
    model_client: LocalModelClient, task: str
) -> PlanResponse:
    prompt = _plan_prompt(task)
    schema = PlanResponse.model_json_schema()
    validation_summary = ""
    for attempt in range(2):
        request_prompt = prompt
        if attempt == 1:
            request_prompt += (
                "\n\nThe previous JSON failed validation. Correct it using only this "
                f"diagnostic: {validation_summary}. Return a fresh complete plan."
            )
        raw_plan = await model_client.generate_with_schema(
            request_prompt, schema, "boundary_plan"
        )
        try:
            return enforce_action_policy(PlanResponse.model_validate_json(raw_plan))
        except ValidationError as exc:
            validation_summary = _validation_summary(exc)
            logger.warning(
                "local plan validation failed on attempt %d: %s",
                attempt + 1,
                validation_summary,
            )
    raise MalformedModelResponseError(
        "local model produced a semantically invalid plan after one repair attempt"
    )


def create_app(
    settings_override: Optional[Settings] = None,
    model_client_override: Optional[LocalModelClient] = None,
    database_override: Optional[WorkflowDatabase] = None,
) -> FastAPI:
    settings = settings_override or Settings.from_environment()
    model_client = model_client_override or VLLMLocalModelClient(
        base_url=settings.model_base_url,
        model_name=settings.model_name,
        timeout_seconds=settings.model_timeout_seconds,
    )
    database = database_override or WorkflowDatabase(settings.database_path)
    application = FastAPI(title=settings.app_name, version="0.3.0")
    application.state.database = database

    @application.exception_handler(WorkflowConflictError)
    async def workflow_conflict_handler(request, exc: WorkflowConflictError):
        response = ConflictResponse(code=exc.code, message=exc.message)
        return JSONResponse(status_code=409, content=response.model_dump())

    async def generate_current_plan(task: str) -> PlanResponse:
        configured_models = await model_client.available_models()
        if settings.model_name not in configured_models:
            raise ModelUnavailableError(
                f"configured local model '{settings.model_name}' is unavailable"
            )
        return await _generate_plan(model_client, task)

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(
            service="backend",
            model=settings.model_name,
            remote_apis_enabled=settings.remote_apis_enabled,
        )

    @application.get(
        "/model/health", response_model=ModelHealthResponse, tags=["model"]
    )
    async def model_health() -> ModelHealthResponse:
        try:
            available = settings.model_name in await model_client.available_models()
        except ModelTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except (ModelConnectionError, ModelUnavailableError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except MalformedModelResponseError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return ModelHealthResponse(
            model_name=settings.model_name,
            available=available,
        )

    @application.post("/agent/plan", response_model=PlanResponse, tags=["agent"])
    async def plan(request: PlanRequest) -> PlanResponse:
        try:
            return await generate_current_plan(request.task)
        except ModelTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except (ModelConnectionError, ModelUnavailableError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except MalformedModelResponseError as exc:
            raise HTTPException(
                status_code=502, detail="local model returned a malformed plan"
            ) from exc

    @application.post("/runs", response_model=RunResponse, status_code=201, tags=["workflow"])
    async def create_run(request: PlanRequest) -> RunResponse:
        try:
            generated_plan = await generate_current_plan(request.task)
        except ModelTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except (ModelConnectionError, ModelUnavailableError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except MalformedModelResponseError as exc:
            raise HTTPException(
                status_code=502, detail="local model returned a malformed plan"
            ) from exc
        run_id = database.create_run(request.task, generated_plan)
        stored = database.get_run(run_id)
        if stored is None:  # pragma: no cover - fail closed on storage corruption
            raise HTTPException(status_code=500, detail="run persistence failed")
        return RunResponse.model_validate(stored)

    @application.get("/runs/{run_id}", response_model=RunResponse, tags=["workflow"])
    async def get_run(run_id: str) -> RunResponse:
        stored = database.get_run(run_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="run not found")
        return RunResponse.model_validate(stored)

    @application.get(
        "/approvals", response_model=list[ApprovalResponse], tags=["workflow"]
    )
    async def list_approvals(
        run_id: Optional[str] = Query(default=None),
    ) -> list[ApprovalResponse]:
        return [
            ApprovalResponse.model_validate(item)
            for item in database.list_approvals(run_id)
        ]

    def decide(
        approval_id: str, request: ApprovalDecisionRequest, status: ApprovalStatus
    ) -> ApprovalResponse:
        try:
            result = database.decide_approval(
                approval_id, status, request.actor, request.reason
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval not found") from exc
        return ApprovalResponse.model_validate(result)

    @application.post(
        "/approvals/{approval_id}/approve",
        response_model=ApprovalResponse,
        tags=["workflow"],
    )
    async def approve(
        approval_id: str, request: ApprovalDecisionRequest
    ) -> ApprovalResponse:
        return decide(approval_id, request, ApprovalStatus.approved)

    @application.post(
        "/approvals/{approval_id}/reject",
        response_model=ApprovalResponse,
        tags=["workflow"],
    )
    async def reject(
        approval_id: str, request: ApprovalDecisionRequest
    ) -> ApprovalResponse:
        return decide(approval_id, request, ApprovalStatus.rejected)

    @application.post(
        "/runs/{run_id}/execute", response_model=RunResponse, tags=["workflow"]
    )
    async def execute_run(run_id: str) -> RunResponse:
        try:
            database.execute_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        stored = database.get_run(run_id)
        if stored is None:  # pragma: no cover
            raise HTTPException(status_code=500, detail="run persistence failed")
        return RunResponse.model_validate(stored)

    @application.get(
        "/runs/{run_id}/audit",
        response_model=list[AuditEventResponse],
        tags=["audit"],
    )
    async def audit(run_id: str) -> list[AuditEventResponse]:
        if database.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        return [
            AuditEventResponse.model_validate(event)
            for event in database.audit_events(run_id)
        ]

    @application.get(
        "/audit/verify/{run_id}", response_model=AuditVerifyResponse, tags=["audit"]
    )
    async def verify_audit(run_id: str) -> AuditVerifyResponse:
        if database.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        valid, invalid_event = database.verify_audit(run_id)
        return AuditVerifyResponse(
            run_id=run_id,
            valid=valid,
            first_invalid_event_id=invalid_event,
        )

    return application


app = create_app()
