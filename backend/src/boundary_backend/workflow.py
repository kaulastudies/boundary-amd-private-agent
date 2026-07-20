"""Persistent workflow state, approval guard, audit chain, and simulated tools."""

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from .models import (
    ActionType,
    ApprovalStatus,
    PlanResponse,
    PlanStep,
    RiskLevel,
    RunState,
    StepState,
)
from .policy import RISK_ORDER, enforce_action_policy


class WorkflowConflictError(Exception):
    """A requested workflow operation violates deterministic state policy."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


RUN_TRANSITIONS = {
    RunState.planned: {RunState.awaiting_approval, RunState.executing, RunState.blocked},
    RunState.awaiting_approval: {RunState.approved, RunState.rejected},
    RunState.approved: {RunState.executing},
    RunState.rejected: set(),
    RunState.executing: {RunState.completed, RunState.failed},
    RunState.completed: set(),
    RunState.failed: set(),
    RunState.blocked: set(),
}

STEP_TRANSITIONS = {
    StepState.planned: {
        StepState.ready,
        StepState.awaiting_approval,
        StepState.blocked,
    },
    StepState.ready: {StepState.executed, StepState.failed},
    StepState.awaiting_approval: {StepState.approved, StepState.rejected},
    StepState.approved: {StepState.executed, StepState.failed},
    StepState.rejected: {StepState.skipped},
    StepState.executed: set(),
    StepState.failed: set(),
    StepState.blocked: set(),
    StepState.skipped: set(),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _transition_run(previous: RunState, new: RunState) -> None:
    if new not in RUN_TRANSITIONS[previous]:
        raise WorkflowConflictError(
            "invalid_transition",
            f"run cannot transition from {previous.value} to {new.value}",
        )


def _transition_step(previous: StepState, new: StepState) -> None:
    if new not in STEP_TRANSITIONS[previous]:
        raise WorkflowConflictError(
            "invalid_transition",
            f"step cannot transition from {previous.value} to {new.value}",
        )


def _simulated_tool(step: PlanStep) -> dict[str, Any]:
    summaries = {
        ActionType.inspect_local: ("Synthetic local inspection completed", "inspection"),
        ActionType.analyze_local: ("Synthetic local analysis completed", "analysis"),
        ActionType.draft_local: (
            "Synthetic draft stored locally; no message was sent",
            "draft",
        ),
        ActionType.write_local: ("Simulated local write recorded", "local_write"),
        ActionType.send_external: (
            "Simulated email send recorded; no email was sent",
            "simulated_email",
        ),
        ActionType.schedule_external: (
            "Simulated meeting scheduled; no calendar was modified",
            "simulated_meeting",
        ),
        ActionType.share_external: (
            "Simulated external share recorded; no data was shared",
            "simulated_share",
        ),
        ActionType.upload_external: (
            "Simulated upload recorded; no data was uploaded",
            "simulated_upload",
        ),
        ActionType.publish_external: (
            "Simulated publication recorded; no content was published",
            "simulated_publication",
        ),
        ActionType.delete_local: (
            "Simulated deletion recorded in sandbox; no file was deleted",
            "simulated_deletion",
        ),
        ActionType.overwrite_local: (
            "Simulated overwrite recorded; no file was changed",
            "simulated_overwrite",
        ),
        ActionType.execute_command: (
            "Simulated command recorded; no command was executed",
            "simulated_command",
        ),
        ActionType.financial_action: (
            "Simulated financial action recorded; no transaction occurred",
            "simulated_financial_action",
        ),
    }
    if step.action_type not in summaries:
        raise WorkflowConflictError("execution_blocked", "action is blocked by policy")
    summary, artifact_type = summaries[step.action_type]
    return {
        "simulated": True,
        "no_external_side_effect": True,
        "summary": summary,
        "artifact_type": artifact_type,
    }


class WorkflowDatabase:
    """SQLite-backed workflow store with deterministic schema initialization."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._lock = threading.RLock()
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            task TEXT NOT NULL,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plan_steps (
            run_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            action_type TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            requires_approval INTEGER NOT NULL,
            policy_reason TEXT NOT NULL,
            state TEXT NOT NULL,
            PRIMARY KEY (run_id, step_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        );
        CREATE TABLE IF NOT EXISTS approval_requests (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (run_id, step_id),
            FOREIGN KEY (run_id, step_id) REFERENCES plan_steps(run_id, step_id)
        );
        CREATE TABLE IF NOT EXISTS approval_decisions (
            decision_id TEXT PRIMARY KEY,
            approval_id TEXT NOT NULL UNIQUE,
            decision TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT,
            decided_at TEXT NOT NULL,
            FOREIGN KEY (approval_id) REFERENCES approval_requests(approval_id)
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            timestamp_utc TEXT NOT NULL,
            run_id TEXT NOT NULL,
            step_id TEXT,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            previous_state TEXT,
            new_state TEXT,
            action_type TEXT,
            risk_level TEXT,
            policy_reason TEXT,
            metadata_json TEXT NOT NULL,
            previous_event_hash TEXT,
            event_hash TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_audit_run_sequence
            ON audit_events(run_id, sequence);
        CREATE TABLE IF NOT EXISTS simulated_tool_results (
            result_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (run_id, step_id),
            FOREIGN KEY (run_id, step_id) REFERENCES plan_steps(run_id, step_id)
        );
        """
        with self._connect() as connection:
            connection.executescript(schema)

    @staticmethod
    def _audit_hash_payload(values: dict[str, Any]) -> str:
        canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _append_audit(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        event_type: str,
        actor: str,
        step_id: Optional[str] = None,
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        step: Optional[PlanStep] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        previous_row = connection.execute(
            "SELECT event_hash FROM audit_events WHERE run_id = ? "
            "ORDER BY sequence DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        previous_hash = previous_row["event_hash"] if previous_row else None
        event_id = str(uuid.uuid4())
        timestamp = _utc_now()
        safe_metadata = metadata or {}
        values = {
            "event_id": event_id,
            "timestamp_utc": timestamp,
            "run_id": run_id,
            "step_id": step_id,
            "event_type": event_type,
            "actor": actor,
            "previous_state": previous_state,
            "new_state": new_state,
            "action_type": step.action_type.value if step else None,
            "risk_level": step.risk_level.value if step else None,
            "policy_reason": step.policy_reason if step else None,
            "metadata": safe_metadata,
            "previous_event_hash": previous_hash,
        }
        event_hash = self._audit_hash_payload(values)
        connection.execute(
            """
            INSERT INTO audit_events (
                event_id, timestamp_utc, run_id, step_id, event_type, actor,
                previous_state, new_state, action_type, risk_level, policy_reason,
                metadata_json, previous_event_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                timestamp,
                run_id,
                step_id,
                event_type,
                actor,
                previous_state,
                new_state,
                values["action_type"],
                values["risk_level"],
                values["policy_reason"],
                json.dumps(safe_metadata, sort_keys=True, separators=(",", ":")),
                previous_hash,
                event_hash,
            ),
        )

    def create_run(self, task: str, plan: PlanResponse) -> str:
        run_id = str(uuid.uuid4())
        now = _utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO runs (run_id, task, state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, task, RunState.planned.value, now, now),
            )
            self._append_audit(
                connection,
                run_id,
                "run_created",
                "system",
                new_state=RunState.planned.value,
                metadata={"step_count": len(plan.steps)},
            )
            self._append_audit(
                connection,
                run_id,
                "plan_generated",
                "local_model",
                metadata={"step_count": len(plan.steps)},
            )
            awaiting = 0
            ready = 0
            blocked = 0
            for ordinal, step in enumerate(plan.steps):
                if step.risk_level == RiskLevel.blocked or step.action_type in {
                    ActionType.credential_access,
                    ActionType.unsupported,
                }:
                    state = StepState.blocked
                    blocked += 1
                elif step.requires_approval or RISK_ORDER[step.risk_level] >= RISK_ORDER[RiskLevel.sensitive]:
                    state = StepState.awaiting_approval
                    awaiting += 1
                else:
                    state = StepState.ready
                    ready += 1
                connection.execute(
                    """
                    INSERT INTO plan_steps (
                        run_id, step_id, ordinal, title, description, action_type,
                        risk_level, requires_approval, policy_reason, state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        step.id,
                        ordinal,
                        step.title,
                        step.description,
                        step.action_type.value,
                        step.risk_level.value,
                        int(step.requires_approval),
                        step.policy_reason,
                        state.value,
                    ),
                )
                if state == StepState.awaiting_approval:
                    approval_id = str(uuid.uuid4())
                    connection.execute(
                        "INSERT INTO approval_requests "
                        "(approval_id, run_id, step_id, status, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            approval_id,
                            run_id,
                            step.id,
                            ApprovalStatus.pending.value,
                            now,
                        ),
                    )
                    self._append_audit(
                        connection,
                        run_id,
                        "approval_requested",
                        "system",
                        step.id,
                        StepState.planned.value,
                        StepState.awaiting_approval.value,
                        step,
                        {"approval_id": approval_id},
                    )
            self._append_audit(
                connection,
                run_id,
                "policy_applied",
                "system",
                metadata={
                    "ready_steps": ready,
                    "approval_steps": awaiting,
                    "blocked_steps": blocked,
                },
            )
            if awaiting:
                new_state = RunState.awaiting_approval
                _transition_run(RunState.planned, new_state)
            elif ready:
                new_state = RunState.planned
            else:
                new_state = RunState.blocked
                _transition_run(RunState.planned, new_state)
            connection.execute(
                "UPDATE runs SET state = ?, updated_at = ? WHERE run_id = ?",
                (new_state.value, _utc_now(), run_id),
            )
        return run_id

    @staticmethod
    def _step_from_row(row: sqlite3.Row) -> PlanStep:
        return PlanStep(
            id=row["step_id"],
            title=row["title"],
            description=row["description"],
            action_type=row["action_type"],
            risk_level=row["risk_level"],
            requires_approval=bool(row["requires_approval"]),
            policy_reason=row["policy_reason"],
        )

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            run = connection.execute(
                "SELECT run_id, state FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                return None
            rows = connection.execute(
                """
                SELECT s.*, a.approval_id, r.result_json
                FROM plan_steps s
                LEFT JOIN approval_requests a
                  ON a.run_id = s.run_id AND a.step_id = s.step_id
                LEFT JOIN simulated_tool_results r
                  ON r.run_id = s.run_id AND r.step_id = s.step_id
                WHERE s.run_id = ? ORDER BY s.ordinal
                """,
                (run_id,),
            ).fetchall()
            return {
                "run_id": run["run_id"],
                "state": run["state"],
                "steps": [
                    {
                        **self._step_from_row(row).model_dump(mode="json"),
                        "state": row["state"],
                        "approval_id": row["approval_id"],
                        "tool_result": json.loads(row["result_json"])
                        if row["result_json"]
                        else None,
                    }
                    for row in rows
                ],
            }

    def list_approvals(self, run_id: Optional[str] = None) -> list[dict[str, Any]]:
        query = """
            SELECT a.approval_id, a.run_id, a.step_id, a.status,
                   d.actor, d.reason
            FROM approval_requests a
            LEFT JOIN approval_decisions d ON d.approval_id = a.approval_id
            WHERE a.status = ?
        """
        parameters: list[Any] = [ApprovalStatus.pending.value]
        if run_id:
            query += " AND a.run_id = ?"
            parameters.append(run_id)
        query += " ORDER BY a.created_at, a.approval_id"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, parameters).fetchall()]

    def decide_approval(
        self, approval_id: str, decision: ApprovalStatus, actor: str, reason: Optional[str]
    ) -> dict[str, Any]:
        if decision not in {ApprovalStatus.approved, ApprovalStatus.rejected}:
            raise WorkflowConflictError("invalid_decision", "approval decision is invalid")
        actor = actor.strip()
        if not actor:
            raise WorkflowConflictError("invalid_actor", "actor must be non-empty")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT a.*, s.state AS step_state, s.title, s.description,
                       s.action_type, s.risk_level, s.requires_approval, s.policy_reason,
                       r.state AS run_state
                FROM approval_requests a
                JOIN plan_steps s ON s.run_id = a.run_id AND s.step_id = a.step_id
                JOIN runs r ON r.run_id = a.run_id
                WHERE a.approval_id = ?
                """,
                (approval_id,),
            ).fetchone()
            if row is None:
                raise KeyError(approval_id)
            if row["status"] != ApprovalStatus.pending.value:
                raise WorkflowConflictError(
                    "duplicate_approval", "approval has already been decided"
                )
            previous_step = StepState(row["step_state"])
            new_step = (
                StepState.approved
                if decision == ApprovalStatus.approved
                else StepState.rejected
            )
            _transition_step(previous_step, new_step)
            now = _utc_now()
            connection.execute(
                "UPDATE approval_requests SET status = ? WHERE approval_id = ?",
                (decision.value, approval_id),
            )
            connection.execute(
                "INSERT INTO approval_decisions "
                "(decision_id, approval_id, decision, actor, reason, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), approval_id, decision.value, actor, reason, now),
            )
            connection.execute(
                "UPDATE plan_steps SET state = ? WHERE run_id = ? AND step_id = ?",
                (new_step.value, row["run_id"], row["step_id"]),
            )
            step = self._step_from_row(row)
            self._append_audit(
                connection,
                row["run_id"],
                "approval_granted"
                if decision == ApprovalStatus.approved
                else "approval_rejected",
                actor,
                row["step_id"],
                previous_step.value,
                new_step.value,
                step,
                {"reason_provided": bool(reason)},
            )
            pending = connection.execute(
                "SELECT COUNT(*) AS count FROM approval_requests "
                "WHERE run_id = ? AND status = ?",
                (row["run_id"], ApprovalStatus.pending.value),
            ).fetchone()["count"]
            if pending == 0:
                approved = connection.execute(
                    "SELECT COUNT(*) AS count FROM approval_requests "
                    "WHERE run_id = ? AND status = ?",
                    (row["run_id"], ApprovalStatus.approved.value),
                ).fetchone()["count"]
                ready = connection.execute(
                    "SELECT COUNT(*) AS count FROM plan_steps "
                    "WHERE run_id = ? AND state = ?",
                    (row["run_id"], StepState.ready.value),
                ).fetchone()["count"]
                run_new = RunState.approved if approved or ready else RunState.rejected
                run_previous = RunState(row["run_state"])
                _transition_run(run_previous, run_new)
                connection.execute(
                    "UPDATE runs SET state = ?, updated_at = ? WHERE run_id = ?",
                    (run_new.value, now, row["run_id"]),
                )
            return {
                "approval_id": approval_id,
                "run_id": row["run_id"],
                "step_id": row["step_id"],
                "status": decision.value,
                "actor": actor,
                "reason": reason,
            }

    def execute_run(self, run_id: str, actor: str = "user") -> None:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise KeyError(run_id)
            run_state = RunState(run["state"])
            self._append_audit(
                connection,
                run_id,
                "execution_attempted",
                actor,
                previous_state=run_state.value,
                metadata={"mode": "simulated"},
            )
            if run_state not in {RunState.planned, RunState.approved}:
                self._append_audit(
                    connection,
                    run_id,
                    "execution_blocked",
                    "guard",
                    previous_state=run_state.value,
                    new_state=run_state.value,
                    metadata={"reason": "run_state_not_executable"},
                )
                connection.commit()
                code = (
                    "approval_required"
                    if run_state == RunState.awaiting_approval
                    else "invalid_transition"
                )
                raise WorkflowConflictError(code, "run is not eligible for execution")

            rows = connection.execute(
                "SELECT * FROM plan_steps WHERE run_id = ? ORDER BY ordinal", (run_id,)
            ).fetchall()
            guarded: list[tuple[sqlite3.Row, PlanStep]] = []
            for row in rows:
                state = StepState(row["state"])
                try:
                    step = self._step_from_row(row)
                except ValidationError as exc:
                    self._append_audit(
                        connection,
                        run_id,
                        "execution_blocked",
                        "guard",
                        row["step_id"],
                        state.value,
                        state.value,
                        metadata={"reason": "malformed_persisted_step"},
                    )
                    connection.commit()
                    raise WorkflowConflictError(
                        "execution_blocked", "persisted step failed validation"
                    ) from exc
                normalized = enforce_action_policy(PlanResponse(steps=[step])).steps[0]
                if normalized != step:
                    connection.execute(
                        """
                        UPDATE plan_steps SET action_type = ?, risk_level = ?,
                            requires_approval = ?, policy_reason = ?
                        WHERE run_id = ? AND step_id = ?
                        """,
                        (
                            normalized.action_type.value,
                            normalized.risk_level.value,
                            int(normalized.requires_approval),
                            normalized.policy_reason,
                            run_id,
                            normalized.id,
                        ),
                    )
                    self._append_audit(
                        connection,
                        run_id,
                        "policy_applied",
                        "execution_guard",
                        normalized.id,
                        state.value,
                        state.value,
                        normalized,
                        {"guard_reclassified": True},
                    )
                step = normalized
                if state in {StepState.rejected, StepState.blocked}:
                    guarded.append((row, step))
                    continue
                protected = (
                    step.requires_approval
                    or RISK_ORDER[step.risk_level] >= RISK_ORDER[RiskLevel.sensitive]
                )
                if protected:
                    approval = connection.execute(
                        "SELECT status FROM approval_requests "
                        "WHERE run_id = ? AND step_id = ?",
                        (run_id, step.id),
                    ).fetchone()
                    if approval is None or approval["status"] != ApprovalStatus.approved.value:
                        self._append_audit(
                            connection,
                            run_id,
                            "execution_blocked",
                            "guard",
                            step.id,
                            state.value,
                            state.value,
                            step,
                            {"reason": "explicit_approval_missing"},
                        )
                        connection.commit()
                        raise WorkflowConflictError(
                            "approval_required",
                            "protected step lacks approval for this run and step",
                        )
                    if state != StepState.approved:
                        connection.commit()
                        raise WorkflowConflictError(
                            "invalid_transition", "approved action has stale step state"
                        )
                elif state != StepState.ready:
                    connection.commit()
                    raise WorkflowConflictError(
                        "invalid_transition", "safe action is not ready"
                    )
                guarded.append((row, step))

            _transition_run(run_state, RunState.executing)
            connection.execute(
                "UPDATE runs SET state = ?, updated_at = ? WHERE run_id = ?",
                (RunState.executing.value, _utc_now(), run_id),
            )
            for row, step in guarded:
                state = StepState(row["state"])
                if state == StepState.rejected:
                    _transition_step(state, StepState.skipped)
                    connection.execute(
                        "UPDATE plan_steps SET state = ? WHERE run_id = ? AND step_id = ?",
                        (StepState.skipped.value, run_id, step.id),
                    )
                    continue
                if state == StepState.blocked:
                    continue
                result = _simulated_tool(step)
                _transition_step(state, StepState.executed)
                connection.execute(
                    "INSERT INTO simulated_tool_results "
                    "(result_id, run_id, step_id, result_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        run_id,
                        step.id,
                        json.dumps(result, sort_keys=True, separators=(",", ":")),
                        _utc_now(),
                    ),
                )
                connection.execute(
                    "UPDATE plan_steps SET state = ? WHERE run_id = ? AND step_id = ?",
                    (StepState.executed.value, run_id, step.id),
                )
                self._append_audit(
                    connection,
                    run_id,
                    "step_executed",
                    "simulator",
                    step.id,
                    state.value,
                    StepState.executed.value,
                    step,
                    {"simulated": True, "no_external_side_effect": True},
                )
            _transition_run(RunState.executing, RunState.completed)
            connection.execute(
                "UPDATE runs SET state = ?, updated_at = ? WHERE run_id = ?",
                (RunState.completed.value, _utc_now(), run_id),
            )
            self._append_audit(
                connection,
                run_id,
                "run_completed",
                "system",
                previous_state=RunState.executing.value,
                new_state=RunState.completed.value,
                metadata={"execution_mode": "simulated"},
            )

    def audit_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE run_id = ? ORDER BY sequence", (run_id,)
            ).fetchall()
            return [
                {
                    "event_id": row["event_id"],
                    "timestamp_utc": row["timestamp_utc"],
                    "run_id": row["run_id"],
                    "step_id": row["step_id"],
                    "event_type": row["event_type"],
                    "actor": row["actor"],
                    "previous_state": row["previous_state"],
                    "new_state": row["new_state"],
                    "action_type": row["action_type"],
                    "risk_level": row["risk_level"],
                    "policy_reason": row["policy_reason"],
                    "metadata": json.loads(row["metadata_json"]),
                    "previous_event_hash": row["previous_event_hash"],
                    "event_hash": row["event_hash"],
                }
                for row in rows
            ]

    def verify_audit(self, run_id: str) -> tuple[bool, Optional[str]]:
        events = self.audit_events(run_id)
        previous_hash = None
        for event in events:
            stored_hash = event.pop("event_hash")
            if event["previous_event_hash"] != previous_hash:
                return False, event["event_id"]
            calculated = self._audit_hash_payload(event)
            if calculated != stored_hash:
                return False, event["event_id"]
            previous_hash = stored_hash
        return True, None
