import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ControlCenter } from "@/components/control-center";
import { boundaryApi, BoundaryApiError } from "@/lib/api";
import type { Approval, AuditEvent, Run, RunStep } from "@/lib/types";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    boundaryApi: {
      health: vi.fn(),
      modelHealth: vi.fn(),
      createRun: vi.fn(),
      getRun: vi.fn(),
      approvals: vi.fn(),
      decideApproval: vi.fn(),
      executeRun: vi.fn(),
      audit: vi.fn(),
      verifyAudit: vi.fn(),
    },
  };
});

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const APPROVAL_ID = "22222222-2222-4222-8222-222222222222";

function runStep(overrides: Partial<RunStep> = {}): RunStep {
  return {
    id: "step-review",
    title: "Review Contract",
    description: "Read the local contract.",
    action_type: "inspect_local",
    risk_level: "safe",
    requires_approval: false,
    policy_reason: "Local read-only operation",
    state: "ready",
    approval_id: null,
    tool_result: null,
    ...overrides,
  };
}

function testRun(steps: RunStep[] = [runStep()], state: Run["state"] = "planned"): Run {
  return { run_id: RUN_ID, state, steps };
}

function approval(stepId: string): Approval {
  return {
    approval_id: APPROVAL_ID,
    run_id: RUN_ID,
    step_id: stepId,
    status: "pending",
    actor: null,
    reason: null,
  };
}

const auditEvent: AuditEvent = {
  event_id: "33333333-3333-4333-8333-333333333333",
  timestamp_utc: "2026-07-20T10:00:00+00:00",
  run_id: RUN_ID,
  step_id: null,
  event_type: "run_created",
  actor: "system",
  previous_state: null,
  new_state: "planned",
  action_type: null,
  risk_level: null,
  policy_reason: null,
  metadata: {},
  previous_event_hash: null,
  event_hash: "abcdef1234567890",
};

function defaults(run: Run = testRun()) {
  vi.mocked(boundaryApi.health).mockResolvedValue({
    status: "ok", service: "backend", model: "boundary-qwen3-8b", remote_apis_enabled: false,
  });
  vi.mocked(boundaryApi.modelHealth).mockResolvedValue({
    model_name: "boundary-qwen3-8b", available: true, local_only: true,
  });
  vi.mocked(boundaryApi.createRun).mockResolvedValue(run);
  vi.mocked(boundaryApi.getRun).mockResolvedValue(run);
  vi.mocked(boundaryApi.approvals).mockResolvedValue([]);
  vi.mocked(boundaryApi.audit).mockResolvedValue([auditEvent]);
  vi.mocked(boundaryApi.verifyAudit).mockResolvedValue({
    run_id: RUN_ID, valid: true, first_invalid_event_id: null,
  });
  vi.mocked(boundaryApi.executeRun).mockResolvedValue(run);
  vi.mocked(boundaryApi.decideApproval).mockResolvedValue({
    approval_id: APPROVAL_ID, run_id: RUN_ID, step_id: run.steps[0].id,
    status: "approved", actor: "judge", reason: null,
  });
}

async function createDashboardRun() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Use demo task" }));
  await user.click(screen.getByRole("button", { name: "Create Safe Plan" }));
  await screen.findByText(`Run ${RUN_ID.slice(0, 8)}…`);
  return user;
}

beforeEach(() => defaults());
afterEach(() => cleanup());

describe("BOUNDARY Control Center", () => {
  it("renders the dashboard, local-only status, and truthful safety wording", async () => {
    render(<ControlCenter />);
    expect(screen.getByRole("heading", { name: "Create a safe, reviewable plan" })).toBeInTheDocument();
    expect(screen.getByText("AI That Asks Before It Acts")).toBeInTheDocument();
    expect(screen.getByText("Planning does not execute actions.")).toBeInTheDocument();
    expect(screen.getByText("No external side effects occurred.")).toBeInTheDocument();
    await screen.findByText("Backend online");
    expect(screen.getByText("Qwen3-8B via local vLLM")).toBeInTheDocument();
    expect(screen.getByText("Local-only inference")).toBeInTheDocument();
    expect(screen.getByText("Remote APIs disabled")).toBeInTheDocument();
  });

  it("submits the demo task and renders ordered policy and risk labels", async () => {
    const sensitive = runStep({
      id: "step-send", title: "Send Email", description: "Send the draft.",
      action_type: "send_external", risk_level: "sensitive", requires_approval: true,
      policy_reason: "External communication requires approval", state: "awaiting_approval",
      approval_id: APPROVAL_ID,
    });
    const run = testRun([runStep(), sensitive], "awaiting_approval");
    defaults(run);
    vi.mocked(boundaryApi.approvals).mockResolvedValue([approval(sensitive.id)]);
    render(<ControlCenter />);
    await createDashboardRun();
    expect(boundaryApi.createRun).toHaveBeenCalledWith(expect.stringContaining("confidential contract"));
    expect(screen.getAllByTestId("plan-step")).toHaveLength(2);
    expect(screen.getByText("Safe · local/read-only")).toBeInTheDocument();
    expect(screen.getAllByText("Sensitive · approval required").length).toBeGreaterThan(0);
    expect(screen.getAllByText("External communication requires approval").length).toBeGreaterThan(0);
  });

  it.each(["approve", "reject"] as const)("supports the %s decision flow", async (decision) => {
    const protectedStep = runStep({
      id: "step-send", title: "Send Email", action_type: "send_external",
      risk_level: "sensitive", requires_approval: true, state: "awaiting_approval",
      approval_id: APPROVAL_ID, policy_reason: "External communication requires approval",
    });
    const run = testRun([protectedStep], "awaiting_approval");
    defaults(run);
    vi.mocked(boundaryApi.approvals).mockResolvedValue([approval(protectedStep.id)]);
    render(<ControlCenter />);
    const user = await createDashboardRun();
    await user.type(screen.getByLabelText("Decision actor"), "judge");
    await user.click(screen.getByRole("button", { name: decision === "approve" ? "Approve" : "Reject" }));
    await waitFor(() => expect(boundaryApi.decideApproval).toHaveBeenCalledWith(
      APPROVAL_ID, decision, { actor: "judge" },
    ));
    expect(await screen.findByText(/Nothing executed automatically/)).toBeInTheDocument();
  });

  it("requires explicit confirmation for destructive approval", async () => {
    const destructive = runStep({
      id: "step-delete", title: "Delete Contract", action_type: "delete_local",
      risk_level: "destructive", requires_approval: true, state: "awaiting_approval",
      approval_id: APPROVAL_ID, policy_reason: "Destructive file operation requires approval",
    });
    const run = testRun([destructive], "awaiting_approval");
    defaults(run);
    vi.mocked(boundaryApi.approvals).mockResolvedValue([approval(destructive.id)]);
    render(<ControlCenter />);
    const user = await createDashboardRun();
    await user.type(screen.getByLabelText("Decision actor"), "judge");
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByRole("dialog", { name: "Approve destructive action?" })).toBeInTheDocument();
    expect(boundaryApi.decideApproval).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    await waitFor(() => expect(boundaryApi.decideApproval).toHaveBeenCalled());
  });

  it("shows a typed conflict when execution is blocked by pending approval", async () => {
    const pending = testRun([runStep({ state: "awaiting_approval", requires_approval: true })], "awaiting_approval");
    defaults(pending);
    vi.mocked(boundaryApi.executeRun).mockRejectedValue(
      new BoundaryApiError(409, "approval_required", "Run is not eligible for execution."),
    );
    render(<ControlCenter />);
    const user = await createDashboardRun();
    await user.click(screen.getByRole("button", { name: "Execute simulations" }));
    expect(screen.getByText(/No email, calendar event, deletion/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run simulations" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Approval Inbox/);
  });

  it("renders simulated results without implying a real side effect", async () => {
    const completed = testRun([runStep({
      state: "executed",
      tool_result: {
        simulated: true,
        no_external_side_effect: true,
        summary: "Simulated email send recorded; no email was sent",
        artifact_type: "simulated_email",
      },
    })], "completed");
    defaults(completed);
    render(<ControlCenter />);
    await createDashboardRun();
    expect(screen.getByText("simulated=true")).toBeInTheDocument();
    expect(screen.getByText("no_external_side_effect=true")).toBeInTheDocument();
    expect(screen.getByText(/no email was sent/i)).toBeInTheDocument();
  });

  it.each([
    { valid: true, heading: "✓ Audit chain verified" },
    { valid: false, heading: "⚠ Tamper warning" },
  ])("renders audit verification state $valid", async ({ valid, heading }) => {
    vi.mocked(boundaryApi.verifyAudit).mockResolvedValue({
      run_id: RUN_ID,
      valid,
      first_invalid_event_id: valid ? null : "44444444-4444-4444-8444-444444444444",
    });
    render(<ControlCenter />);
    await createDashboardRun();
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByText(`valid=${String(valid)}`)).toBeInTheDocument();
  });

  it("handles an unavailable backend without exposing internals", async () => {
    vi.mocked(boundaryApi.health).mockRejectedValue(new BoundaryApiError(503, "backend_unavailable", "offline"));
    render(<ControlCenter />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Local backend unavailable");
    expect(screen.getByText("Backend unavailable")).toBeInTheDocument();
  });
});
