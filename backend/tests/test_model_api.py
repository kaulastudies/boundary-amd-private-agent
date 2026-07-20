import httpx
from fastapi.testclient import TestClient

from boundary_backend.config import Settings
from boundary_backend.local_model import VLLMLocalModelClient
from boundary_backend.main import create_app


MODEL_NAME = "boundary-qwen3-8b"


def app_client(handler) -> tuple[TestClient, httpx.AsyncClient]:
    async_http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model_client = VLLMLocalModelClient(
        "http://127.0.0.1:8000/v1",
        MODEL_NAME,
        2.0,
        http_client=async_http_client,
    )
    app = create_app(Settings(), model_client)
    return TestClient(app), async_http_client


def test_healthy_model_discovery() -> None:
    client, _ = app_client(
        lambda request: httpx.Response(200, json={"data": [{"id": MODEL_NAME}]})
    )
    response = client.get("/model/health")
    assert response.status_code == 200
    assert response.json() == {
        "model_name": MODEL_NAME,
        "available": True,
        "local_only": True,
    }


def test_unavailable_model_discovery() -> None:
    client, _ = app_client(
        lambda request: httpx.Response(200, json={"data": [{"id": "other-model"}]})
    )
    response = client.get("/model/health")
    assert response.status_code == 200
    assert response.json()["available"] is False


def test_valid_structured_plan() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": MODEL_NAME}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"steps":[{"id":"1","title":"Inspect",'
                                '"description":"Review the local files.",'
                                '"risk_level":"safe","requires_approval":false}]}'
                            )
                        }
                    }
                ]
            },
        )

    client, _ = app_client(handler)
    response = client.post("/agent/plan", json={"task": "Review this repository"})
    assert response.status_code == 200
    assert response.json()["steps"][0] == {
        "id": "1",
        "title": "Inspect",
        "description": "Review the local files.",
        "risk_level": "safe",
        "requires_approval": False,
    }


def test_malformed_plan_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": MODEL_NAME}]})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not valid JSON"}}]},
        )

    client, _ = app_client(handler)
    response = client.post("/agent/plan", json={"task": "Plan something"})
    assert response.status_code == 502
    assert response.json() == {"detail": "local model returned a malformed plan"}
