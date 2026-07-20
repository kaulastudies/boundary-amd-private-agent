import type {
  Approval,
  ApprovalDecision,
  AuditEvent,
  AuditVerification,
  Health,
  ModelHealth,
  Run,
} from "@/lib/types";

export class BoundaryApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "BoundaryApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/boundary/${path}`, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
      cache: "no-store",
    });
  } catch {
    throw new BoundaryApiError(
      503,
      "frontend_network_error",
      "The local Control Center server is unavailable.",
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new BoundaryApiError(
      502,
      "malformed_response",
      "The local service returned an unreadable response.",
    );
  }
  if (!response.ok) {
    const code = isRecord(payload) && typeof payload.code === "string"
      ? payload.code
      : `http_${response.status}`;
    const message = isRecord(payload) && typeof payload.message === "string"
      ? payload.message
      : "The local request could not be completed.";
    throw new BoundaryApiError(response.status, code, message);
  }
  return payload as T;
}

export const boundaryApi = {
  health: () => request<Health>("health"),
  modelHealth: () => request<ModelHealth>("model/health"),
  createRun: (task: string) => request<Run>("runs", {
    method: "POST",
    body: JSON.stringify({ task }),
  }),
  getRun: (runId: string) => request<Run>(`runs/${encodeURIComponent(runId)}`),
  approvals: (runId?: string) => request<Approval[]>(
    `approvals${runId ? `?run_id=${encodeURIComponent(runId)}` : ""}`,
  ),
  decideApproval: (
    approvalId: string,
    decision: "approve" | "reject",
    input: ApprovalDecision,
  ) => request<Approval>(
    `approvals/${encodeURIComponent(approvalId)}/${decision}`,
    { method: "POST", body: JSON.stringify(input) },
  ),
  executeRun: (runId: string) => request<Run>(
    `runs/${encodeURIComponent(runId)}/execute`,
    { method: "POST", body: "{}" },
  ),
  audit: (runId: string) => request<AuditEvent[]>(
    `runs/${encodeURIComponent(runId)}/audit`,
  ),
  verifyAudit: (runId: string) => request<AuditVerification>(
    `audit/verify/${encodeURIComponent(runId)}`,
  ),
};
