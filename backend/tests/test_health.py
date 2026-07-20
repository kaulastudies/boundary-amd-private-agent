from fastapi.testclient import TestClient

from boundary_backend.config import Settings
from boundary_backend.local_model import LocalModelClient
from boundary_backend.main import create_app


class NoNetworkClient(LocalModelClient):
    async def available_models(self) -> set[str]:
        return {"boundary-qwen3-8b"}

    async def generate(self, prompt: str) -> str:
        raise AssertionError("generate should not be called by /health")

    async def stream(self, prompt: str):
        if False:
            yield prompt


def test_health_endpoint_reports_local_only_status() -> None:
    settings = Settings()
    app = create_app(settings, NoNetworkClient())
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "backend",
        "model": "boundary-qwen3-8b",
        "remote_apis_enabled": False,
    }
