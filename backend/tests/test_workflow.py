import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from boundary_backend.config import Settings
from boundary_backend.local_model import LocalModelClient
from boundary_backend.main import create_app
from boundary_backend.workflow import WorkflowDatabase


MODEL_NAME = "boundary-qwen3-8b"


def step(
    step_id: str,
    title: str,
    description: str,
    action_type: str,
    risk_level: str = "safe",
    requires_approval: bool = False,
) -> dict:
    return {
        "id": step_id,
        "title": title,
        "description": description,
        "action_type": action_type,
        "risk_level": risk_level,
        "requires_approval": requires_approval,
        "policy_reason": "Advisory model reason",
    }


SAFE_STEP = step(
    "step-review", "Review Contract", "Read the local contract.", "inspect_local"
)
SEND_STEP = step(
    "step-send",
    "Send Email",
    "Send the drafted email to the client.",
    "send_external",
    "sensitive",
    True,
)
SCHEDULE_STEP = step(
    "step-schedule",
    "Schedule Meeting",
    "Create a meeting and invite attendees.",
    "schedule_external",
    "sensitive",
    True,
)
DELETE_STEP = step(
    "step-delete",
    "Delete Contract",
    "Delete the local contract.",
    "delete_local",
    "destructive",
    True,
)


class StaticPlanClient(LocalModelClient):
    def __init__(self, steps: list[dict]) -> None:
        self.steps = steps
        self.schema_calls = 0

    async def available_models(self) -> set[str]:
        return {MODEL_NAME}

    async def generate(self, prompt: str) -> str:
        return json.dumps({"steps": self.steps})

    async def generate_with_schema(self, prompt, json_schema, schema_name):
        self.schema_calls += 1
        assert schema_name == "boundary_plan"
        return json.dumps({"steps": self.steps})

    async def stream(self, prompt: str):
        if False:
            yield prompt


def workflow_client(
    tmp_path: Path, steps: list[dict], database_name: str = "workflow.db"
) -> tuple[TestClient, StaticPlanClient, Path]:
    database_path = tmp_path / database_name
    model = StaticPlanClient(steps)
    settings = Settings(database_path=str(database_path))
    app = create_app(settings, model, WorkflowDatabase(str(database_path)))
    return TestClient(app), model, database_path


def create_run(client: TestClient, task: str = "Private workflow task") -> dict:
    response = client.post("/runs", json={"task": task})
    assert response.status_code == 201, response.text
    return response.json()


def approve(client: TestClient, approval_id: str, actor: str = "alice") -> dict:
    response = client.post(
        f"/approvals/{approval_id}/approve", json={"actor": actor}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_run_creation_persists_schema_valid_policy_plan(tmp_path: Path) -> None:
    client, model, _ = workflow_client(tmp_path, [SAFE_STEP, SEND_STEP])
    run = create_run(client)
    assert model.schema_calls == 1
    assert run["state"] == "awaiting_approval"
    assert [item["state"] for item in run["steps"]] == [
        "ready",
        "awaiting_approval",
    ]
    assert run["steps"][1]["action_type"] == "send_external"
    assert run["steps"][1]["requires_approval"] is True
    assert run["steps"][1]["policy_reason"] == "External communication requires approval"
    assert client.get(f"/runs/{run['run_id']}").json() == run


def test_safe_step_executes_without_approval_and_is_clearly_simulated(
    tmp_path: Path,
) -> None:
    client, _, _ = workflow_client(tmp_path, [SAFE_STEP])
    run = create_run(client)
    response = client.post(f"/runs/{run['run_id']}/execute")
    assert response.status_code == 200
    executed = response.json()
    assert executed["state"] == "completed"
    assert executed["steps"][0]["state"] == "executed"
    assert executed["steps"][0]["tool_result"]["simulated"] is True
    assert executed["steps"][0]["tool_result"]["no_external_side_effect"] is True


@pytest.mark.parametrize("protected_step", [SEND_STEP, SCHEDULE_STEP, DELETE_STEP])
def test_protected_step_pauses_and_cannot_execute_before_approval(
    tmp_path: Path, protected_step: dict
) -> None:
    client, _, _ = workflow_client(tmp_path, [protected_step])
    run = create_run(client)
    assert run["state"] == "awaiting_approval"
    assert run["steps"][0]["state"] == "awaiting_approval"
    response = client.post(f"/runs/{run['run_id']}/execute")
    assert response.status_code == 409
    assert response.json()["code"] == "approval_required"
    assert client.get(f"/runs/{run['run_id']}").json()["steps"][0]["tool_result"] is None


@pytest.mark.parametrize("protected_step", [SEND_STEP, SCHEDULE_STEP, DELETE_STEP])
def test_approved_action_executes_only_as_simulation(
    tmp_path: Path, protected_step: dict
) -> None:
    client, _, _ = workflow_client(tmp_path, [protected_step])
    run = create_run(client)
    approve(client, run["steps"][0]["approval_id"])
    response = client.post(f"/runs/{run['run_id']}/execute")
    assert response.status_code == 200
    result = response.json()["steps"][0]["tool_result"]
    assert result["simulated"] is True
    assert result["no_external_side_effect"] is True
    assert "Simulated" in result["summary"]


def test_rejected_action_can_never_execute(tmp_path: Path) -> None:
    client, _, _ = workflow_client(tmp_path, [DELETE_STEP])
    run = create_run(client)
    approval_id = run["steps"][0]["approval_id"]
    response = client.post(
        f"/approvals/{approval_id}/reject",
        json={"actor": "alice", "reason": "not authorized"},
    )
    assert response.status_code == 200
    execute = client.post(f"/runs/{run['run_id']}/execute")
    assert execute.status_code == 409
    stored = client.get(f"/runs/{run['run_id']}").json()
    assert stored["steps"][0]["state"] == "rejected"
    assert stored["steps"][0]["tool_result"] is None


def test_rejected_step_is_skipped_in_mixed_approved_run(tmp_path: Path) -> None:
    client, _, _ = workflow_client(tmp_path, [SAFE_STEP, SEND_STEP, DELETE_STEP])
    run = create_run(client)
    approvals = {item["step_id"]: item for item in client.get(
        f"/approvals?run_id={run['run_id']}"
    ).json()}
    approve(client, approvals["step-send"]["approval_id"])
    reject = client.post(
        f"/approvals/{approvals['step-delete']['approval_id']}/reject",
        json={"actor": "alice"},
    )
    assert reject.status_code == 200
    executed = client.post(f"/runs/{run['run_id']}/execute").json()
    states = {item["id"]: item for item in executed["steps"]}
    assert states["step-review"]["state"] == "executed"
    assert states["step-send"]["state"] == "executed"
    assert states["step-delete"]["state"] == "skipped"
    assert states["step-delete"]["tool_result"] is None


def test_blocked_action_cannot_execute(tmp_path: Path) -> None:
    blocked = step(
        "step-secret",
        "Export Credentials",
        "Reveal passwords and transmit secrets.",
        "credential_access",
        "blocked",
        True,
    )
    client, _, _ = workflow_client(tmp_path, [blocked])
    run = create_run(client)
    assert run["state"] == "blocked"
    assert run["steps"][0]["state"] == "blocked"
    response = client.post(f"/runs/{run['run_id']}/execute")
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_transition"


def test_approval_is_scoped_to_exact_run_and_step(tmp_path: Path) -> None:
    client, _, _ = workflow_client(tmp_path, [SEND_STEP])
    first = create_run(client, "first task")
    second = create_run(client, "second task")
    approve(client, first["steps"][0]["approval_id"])
    blocked = client.post(f"/runs/{second['run_id']}/execute")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "approval_required"
    second_step = client.get(f"/runs/{second['run_id']}").json()["steps"][0]
    assert second_step["state"] == "awaiting_approval"


def test_approval_cannot_be_reused_for_another_step_in_same_run(tmp_path: Path) -> None:
    client, _, _ = workflow_client(tmp_path, [SEND_STEP, SCHEDULE_STEP])
    run = create_run(client)
    approvals = client.get(f"/approvals?run_id={run['run_id']}").json()
    approve(client, approvals[0]["approval_id"])
    blocked = client.post(f"/runs/{run['run_id']}/execute")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "approval_required"
    stored = client.get(f"/runs/{run['run_id']}").json()
    assert {item["state"] for item in stored["steps"]} == {
        "approved",
        "awaiting_approval",
    }


def test_malformed_persisted_step_fails_closed(tmp_path: Path) -> None:
    client, _, database_path = workflow_client(tmp_path, [SAFE_STEP])
    run = create_run(client)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE plan_steps SET action_type = ? WHERE run_id = ?",
            ("not-a-real-action", run["run_id"]),
        )
    response = client.post(f"/runs/{run['run_id']}/execute")
    assert response.status_code == 409
    assert response.json()["code"] == "execution_blocked"


def test_duplicate_approval_is_rejected_with_typed_409(tmp_path: Path) -> None:
    client, _, _ = workflow_client(tmp_path, [SEND_STEP])
    run = create_run(client)
    approval_id = run["steps"][0]["approval_id"]
    approve(client, approval_id)
    duplicate = client.post(
        f"/approvals/{approval_id}/approve", json={"actor": "bob"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "duplicate_approval"


def test_approval_requires_non_empty_actor_and_never_auto_executes(tmp_path: Path) -> None:
    client, _, _ = workflow_client(tmp_path, [SEND_STEP])
    run = create_run(client)
    approval_id = run["steps"][0]["approval_id"]
    invalid = client.post(
        f"/approvals/{approval_id}/approve", json={"actor": "   "}
    )
    assert invalid.status_code == 409
    assert invalid.json()["code"] == "invalid_actor"
    approve(client, approval_id)
    stored = client.get(f"/runs/{run['run_id']}").json()
    assert stored["steps"][0]["state"] == "approved"
    assert stored["steps"][0]["tool_result"] is None


def test_approval_and_block_events_are_audited(tmp_path: Path) -> None:
    client, _, _ = workflow_client(tmp_path, [SEND_STEP])
    run = create_run(client)
    blocked = client.post(f"/runs/{run['run_id']}/execute")
    assert blocked.status_code == 409
    approve(client, run["steps"][0]["approval_id"])
    event_types = {
        event["event_type"]
        for event in client.get(f"/runs/{run['run_id']}/audit").json()
    }
    assert {"approval_requested", "execution_attempted", "execution_blocked", "approval_granted"}.issubset(event_types)


def test_invalid_run_transition_returns_typed_409(tmp_path: Path) -> None:
    client, _, _ = workflow_client(tmp_path, [SAFE_STEP])
    run = create_run(client)
    assert client.post(f"/runs/{run['run_id']}/execute").status_code == 200
    repeat = client.post(f"/runs/{run['run_id']}/execute")
    assert repeat.status_code == 409
    assert repeat.json()["code"] == "invalid_transition"


def test_direct_database_underclassification_bypass_fails_closed(tmp_path: Path) -> None:
    client, _, database_path = workflow_client(tmp_path, [SAFE_STEP])
    run = create_run(client)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE plan_steps SET title = ?, description = ?, action_type = ?, "
            "risk_level = ?, requires_approval = 0, state = ? WHERE run_id = ?",
            (
                "Send Email",
                "Send the message to the client.",
                "draft_local",
                "safe",
                "ready",
                run["run_id"],
            ),
        )
    response = client.post(f"/runs/{run['run_id']}/execute")
    assert response.status_code == 409
    assert response.json()["code"] == "approval_required"
    assert client.get(f"/runs/{run['run_id']}").json()["steps"][0]["tool_result"] is None


def test_model_underclassification_cannot_bypass_policy(tmp_path: Path) -> None:
    underclassified = step(
        "step-send",
        "Send Email to Client",
        "Send the email to the client.",
        "draft_local",
        "safe",
        False,
    )
    client, _, _ = workflow_client(tmp_path, [underclassified])
    run = create_run(client)
    stored = run["steps"][0]
    assert stored["action_type"] == "send_external"
    assert stored["risk_level"] == "sensitive"
    assert stored["requires_approval"] is True
    assert stored["state"] == "awaiting_approval"


def test_execution_invokes_no_real_tools_or_network(monkeypatch, tmp_path: Path) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("real side effect attempted")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    client, _, _ = workflow_client(tmp_path, [SAFE_STEP])
    run = create_run(client)
    response = client.post(f"/runs/{run['run_id']}/execute")
    assert response.status_code == 200
    assert response.json()["steps"][0]["tool_result"]["no_external_side_effect"] is True


def test_audit_events_hash_chain_and_privacy(tmp_path: Path) -> None:
    private_task = "confidential acquisition marker 91f0"
    client, _, database_path = workflow_client(tmp_path, [SAFE_STEP])
    run = create_run(client, private_task)
    client.post(f"/runs/{run['run_id']}/execute")
    audit = client.get(f"/runs/{run['run_id']}/audit")
    assert audit.status_code == 200
    events = audit.json()
    assert {"run_created", "plan_generated", "policy_applied", "execution_attempted", "step_executed", "run_completed"}.issubset(
        {event["event_type"] for event in events}
    )
    assert private_task not in json.dumps(events)
    verified = client.get(f"/audit/verify/{run['run_id']}").json()
    assert verified == {
        "run_id": run["run_id"],
        "valid": True,
        "first_invalid_event_id": None,
    }

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE audit_events SET metadata_json = ? WHERE run_id = ? AND sequence = "
            "(SELECT MIN(sequence) FROM audit_events WHERE run_id = ?)",
            ('{"tampered":true}', run["run_id"], run["run_id"]),
        )
    tampered = client.get(f"/audit/verify/{run['run_id']}").json()
    assert tampered["valid"] is False
    assert tampered["first_invalid_event_id"] is not None


def test_sqlite_persistence_survives_application_recreation(tmp_path: Path) -> None:
    client, _, database_path = workflow_client(tmp_path, [SAFE_STEP])
    run = create_run(client)
    recreated_model = StaticPlanClient([SAFE_STEP])
    settings = Settings(database_path=str(database_path))
    recreated = TestClient(
        create_app(settings, recreated_model, WorkflowDatabase(str(database_path)))
    )
    response = recreated.get(f"/runs/{run['run_id']}")
    assert response.status_code == 200
    assert response.json()["run_id"] == run["run_id"]
