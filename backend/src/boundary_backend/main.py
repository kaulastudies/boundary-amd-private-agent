"""FastAPI application entry point."""

import logging

from typing import Optional

from fastapi import FastAPI, HTTPException
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
    HealthResponse,
    ModelHealthResponse,
    PlanRequest,
    PlanResponse,
    RiskLevel,
)

logger = logging.getLogger(__name__)
PROTECTED_RISK_LEVELS = {
    RiskLevel.sensitive,
    RiskLevel.destructive,
    RiskLevel.blocked,
}


def _plan_prompt(task: str) -> str:
    return (
        "Create a concise execution plan for the user task below. Plan only; do not "
        "execute tools or claim actions were performed. Return one JSON object with a "
        "'steps' array. Every step must contain exactly: id, title, description, "
        "risk_level, requires_approval. risk_level must be one of safe, review, "
        "sensitive, destructive, blocked. sensitive, destructive, and blocked steps "
        "must set requires_approval to true. Do not include reasoning or any fields "
        f"outside the requested plan.\n\nUser task:\n{task}"
    )


def _validation_summary(exc: ValidationError) -> str:
    """Return field/type diagnostics without values, prompts, or model output."""
    summaries = []
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "root"
        summaries.append(f"field={location} type={error.get('type', 'unknown')}")
    return "; ".join(summaries[:5]) or "field=root type=unknown"


def _enforce_approval_policy(plan: PlanResponse) -> PlanResponse:
    """Make backend approval policy authoritative over model output."""
    corrected_steps = []
    for step in plan.steps:
        requires_approval = (
            True if step.risk_level in PROTECTED_RISK_LEVELS else step.requires_approval
        )
        corrected_steps.append(
            step.model_copy(update={"requires_approval": requires_approval})
        )
    return plan.model_copy(update={"steps": corrected_steps})


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
            return _enforce_approval_policy(PlanResponse.model_validate_json(raw_plan))
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
) -> FastAPI:
    settings = settings_override or Settings.from_environment()
    model_client = model_client_override or VLLMLocalModelClient(
        base_url=settings.model_base_url,
        model_name=settings.model_name,
        timeout_seconds=settings.model_timeout_seconds,
    )
    application = FastAPI(title=settings.app_name, version="0.2.1")

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
            configured_models = await model_client.available_models()
            if settings.model_name not in configured_models:
                raise ModelUnavailableError(
                    f"configured local model '{settings.model_name}' is unavailable"
                )
            return await _generate_plan(model_client, request.task)
        except ModelTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except (ModelConnectionError, ModelUnavailableError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except MalformedModelResponseError as exc:
            raise HTTPException(
                status_code=502, detail="local model returned a malformed plan"
            ) from exc

    return application


app = create_app()
