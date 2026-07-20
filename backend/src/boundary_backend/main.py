"""FastAPI application entry point."""

from fastapi import FastAPI

from .config import Settings
from .models import HealthResponse

settings = Settings()
app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    return HealthResponse(
        service="backend",
        remote_apis_enabled=settings.remote_apis_enabled,
    )
