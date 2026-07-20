"""Local service configuration."""

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = "BOUNDARY AMD DevMaster Track 2"
    model_path: str = Field(default="./models", description="Local model directory")
    remote_apis_enabled: bool = False
