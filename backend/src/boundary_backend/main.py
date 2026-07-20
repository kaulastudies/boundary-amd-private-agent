"""FastAPI application entry point."""

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
)


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
    application = FastAPI(title=settings.app_name, version="0.2.0")

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
            raw_plan = await model_client.generate(_plan_prompt(request.task))
            return PlanResponse.model_validate_json(raw_plan)
        except ModelTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except (ModelConnectionError, ModelUnavailableError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (MalformedModelResponseError, ValidationError) as exc:
            raise HTTPException(
                status_code=502, detail="local model returned a malformed plan"
            ) from exc

    return application


app = create_app()
