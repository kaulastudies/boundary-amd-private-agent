import json
import os
import subprocess
from typing import Any, Callable

import httpx
from fastapi.testclient import TestClient

from boundary_backend.config import Settings
from boundary_backend.local_model import VLLMLocalModelClient
from boundary_backend.main import create_app


MODEL_NAME = "boundary-qwen3-8b"
VALID_PLAN = {
    "steps": [
        {
            "id": "step-1",
            "title": "Inspect",
            "description": "Review the local files.",
            "risk_level": "safe",
            "requires_approval": False,
        }
    ]
}


def completion(content: Any) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        200, json={"choices": [{"message": {"content": text}}]}
    )


def app_client(
    plan_responses: list[Any],
    advertised_models: list[str] | None = None,
    inspect_request: Callable[[httpx.Request], None] | None = None,
) -> tuple[TestClient, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    queued_plans = list(plan_responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if inspect_request is not None:
            inspect_request(request)
        if request.url.path.endswith("/models"):
            models = advertised_models if advertised_models is not None else [MODEL_NAME]
            return httpx.Response(200, json={"data": [{"id": item} for item in models]})
        if request.url.path.endswith("/chat/completions") and queued_plans:
            return completion(queued_plans.pop(0))
        raise AssertionError(f"unexpected local request: {request.method} {request.url}")

    async_http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model_client = VLLMLocalModelClient(
        "http://127.0.0.1:8000/v1",
        MODEL_NAME,
        2.0,
        http_client=async_http_client,
    )
    app = create_app(Settings(), model_client)
    return TestClient(app), requests


def plan_request(client: TestClient) -> httpx.Response:
    return client.post("/agent/plan", json={"task": "Review this repository"})


def test_healthy_model_discovery() -> None:
    client, _ = app_client([])
    response = client.get("/model/health")
    assert response.status_code == 200
    assert response.json() == {
        "model_name": MODEL_NAME,
        "available": True,
        "local_only": True,
    }


def test_unavailable_model_discovery() -> None:
    client, _ = app_client([], advertised_models=["other-model"])
    response = client.get("/model/health")
    assert response.status_code == 200
    assert response.json()["available"] is False


def test_valid_schema_constrained_plan() -> None:
    payloads = []

    def inspect(request: httpx.Request) -> None:
        assert request.url.host == "127.0.0.1"
        assert "authorization" not in request.headers
        if request.url.path.endswith("/chat/completions"):
            payloads.append(json.loads(request.content))

    client, requests = app_client([VALID_PLAN], inspect_request=inspect)
    response = plan_request(client)

    assert response.status_code == 200
    assert response.json() == VALID_PLAN
    assert len(payloads) == 1
    response_format = payloads[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "boundary_plan"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"]["required"] == ["steps"]
    assert all(request.url.host == "127.0.0.1" for request in requests)


def test_numeric_step_id_is_repaired() -> None:
    invalid = {"steps": [{**VALID_PLAN["steps"][0], "id": 1}]}
    client, requests = app_client([invalid, VALID_PLAN])
    response = plan_request(client)
    assert response.status_code == 200
    assert response.json() == VALID_PLAN
    assert sum(request.url.path.endswith("/chat/completions") for request in requests) == 2


def test_invalid_risk_level_is_rejected_after_one_repair() -> None:
    invalid = {"steps": [{**VALID_PLAN["steps"][0], "risk_level": "critical"}]}
    client, requests = app_client([invalid, invalid])
    response = plan_request(client)
    assert response.status_code == 502
    assert response.json() == {"detail": "local model returned a malformed plan"}
    assert sum(request.url.path.endswith("/chat/completions") for request in requests) == 2


def test_sensitive_false_is_deterministically_corrected() -> None:
    sensitive = {
        "steps": [
            {
                **VALID_PLAN["steps"][0],
                "risk_level": "sensitive",
                "requires_approval": False,
            }
        ]
    }
    client, requests = app_client([sensitive])
    response = plan_request(client)
    assert response.status_code == 200
    assert response.json()["steps"][0]["requires_approval"] is True
    assert sum(request.url.path.endswith("/chat/completions") for request in requests) == 1


def test_missing_steps_is_rejected() -> None:
    client, requests = app_client([{}, {}])
    response = plan_request(client)
    assert response.status_code == 502
    assert len(requests) == 3  # one discovery and exactly two generations


def test_markdown_wrapped_json_is_rejected() -> None:
    wrapped = f"```json\n{json.dumps(VALID_PLAN)}\n```"
    client, requests = app_client([wrapped, wrapped])
    response = plan_request(client)
    assert response.status_code == 502
    assert len(requests) == 3


def test_repair_succeeds_with_sanitized_diagnostic() -> None:
    client, requests = app_client([{"steps": []}, VALID_PLAN])
    response = plan_request(client)
    assert response.status_code == 200
    repair_request = json.loads(requests[-1].content)
    repair_prompt = repair_request["messages"][1]["content"]
    assert "field=steps" in repair_prompt
    assert "type=too_short" in repair_prompt
    assert "{\"steps\"" not in repair_prompt


def test_repair_fails_and_never_attempts_a_third_generation() -> None:
    client, requests = app_client([{"steps": []}, {"steps": []}])
    response = plan_request(client)
    assert response.status_code == 502
    generations = [
        request for request in requests if request.url.path.endswith("/chat/completions")
    ]
    assert len(generations) == 2


def test_validation_logs_are_sanitized(caplog) -> None:
    private_task = "private customer task marker 7f91"
    client, _ = app_client([{"steps": []}, {"steps": []}])
    with caplog.at_level("WARNING", logger="boundary_backend.main"):
        response = client.post("/agent/plan", json={"task": private_task})
    assert response.status_code == 502
    assert "field=steps" in caplog.text
    assert "type=too_short" in caplog.text
    assert private_task not in caplog.text
    assert '{"steps"' not in caplog.text


def test_planning_does_not_execute_tools_or_make_remote_requests(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("planning attempted local tool execution")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    client, requests = app_client([VALID_PLAN])
    assert plan_request(client).status_code == 200
    assert {request.url.path for request in requests} == {
        "/v1/models",
        "/v1/chat/completions",
    }
    assert all(request.url.host == "127.0.0.1" for request in requests)
    assert all("authorization" not in request.headers for request in requests)
