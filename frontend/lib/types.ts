export type RiskLevel = "safe" | "review" | "sensitive" | "destructive" | "blocked";

export type ActionType =
  | "inspect_local"
  | "analyze_local"
  | "draft_local"
  | "write_local"
  | "send_external"
  | "schedule_external"
  | "share_external"
  | "upload_external"
  | "publish_external"
  | "delete_local"
  | "overwrite_local"
  | "execute_command"
  | "financial_action"
  | "credential_access"
  | "unsupported";

export type RunState =
  | "planned"
  | "awaiting_approval"
  | "approved"
  | "rejected"
  | "executing"
  | "completed"
  | "failed"
  | "blocked";

export type StepState =
  | "planned"
  | "ready"
  | "awaiting_approval"
  | "approved"
  | "rejected"
  | "executed"
  | "failed"
  | "blocked"
  | "skipped";

export interface Health {
  status: "ok";
  service: string;
  model: string;
  remote_apis_enabled: false;
}

export interface ModelHealth {
  model_name: string;
  available: boolean;
  local_only: true;
}

export interface SimulatedToolResult {
  simulated: true;
  no_external_side_effect: true;
  summary: string;
  artifact_type: string;
}

export interface RunStep {
  id: string;
  title: string;
  description: string;
  action_type: ActionType;
  risk_level: RiskLevel;
  requires_approval: boolean;
  policy_reason: string;
  state: StepState;
  approval_id: string | null;
  tool_result: SimulatedToolResult | null;
}

export interface Run {
  run_id: string;
  state: RunState;
  steps: RunStep[];
}

export type ApprovalStatus = "pending" | "approved" | "rejected";

export interface Approval {
  approval_id: string;
  run_id: string;
  step_id: string;
  status: ApprovalStatus;
  actor: string | null;
  reason: string | null;
}

export interface ApprovalDecision {
  actor: string;
  reason?: string;
}

export interface AuditEvent {
  event_id: string;
  timestamp_utc: string;
  run_id: string;
  step_id: string | null;
  event_type: string;
  actor: string;
  previous_state: string | null;
  new_state: string | null;
  action_type: string | null;
  risk_level: string | null;
  policy_reason: string | null;
  metadata: Record<string, unknown>;
  previous_event_hash: string | null;
  event_hash: string;
}

export interface AuditVerification {
  run_id: string;
  valid: boolean;
  first_invalid_event_id: string | null;
}

export interface ApiErrorBody {
  code: string;
  message: string;
}
