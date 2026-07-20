"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { boundaryApi, BoundaryApiError } from "@/lib/api";
import type {
  Approval,
  AuditEvent,
  AuditVerification,
  Health,
  ModelHealth,
  Run,
  RunStep,
} from "@/lib/types";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { RiskBadge } from "@/components/risk-badge";

const EXAMPLE_TASK = "Review a confidential contract, identify delivery risks, draft an email, send it to the client, delete the original contract, and schedule a meeting.";
const TERMINAL_STATES = new Set(["completed", "failed", "rejected", "blocked"]);

type PendingConfirmation =
  | { kind: "execute" }
  | { kind: "approval"; approval: Approval; decision: "approve" | "reject"; step: RunStep };

function shortId(value: string | null | undefined): string {
  return value ? `${value.slice(0, 8)}…` : "—";
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function userMessage(error: unknown): string {
  if (error instanceof BoundaryApiError) {
    if (error.status === 409) return `Workflow conflict (${error.code}): ${error.message} Review the Approval Inbox before trying again.`;
    return error.message;
  }
  return "The local request could not be completed. Check that the backend and model are running.";
}

function StatePill({ state }: { state: string }) {
  return <span className="state-pill">State: {state.replaceAll("_", " ")}</span>;
}

function StepCard({ step, index }: { step: RunStep; index: number }) {
  return (
    <article className={`step-card step-${step.risk_level}`} data-testid="plan-step">
      <div className="step-index" aria-label={`Step ${index + 1}`}>{String(index + 1).padStart(2, "0")}</div>
      <div className="step-content">
        <div className="step-heading">
          <div>
            <p className="mono-label">{step.action_type}</p>
            <h3>{step.title}</h3>
          </div>
          <RiskBadge risk={step.risk_level} />
        </div>
        <p className="step-description">{step.description}</p>
        <div className="step-meta">
          <StatePill state={step.state} />
          <span className="approval-label">
            {step.requires_approval ? "🔒 Explicit approval required" : "◇ No approval required"}
          </span>
        </div>
        <div className="policy-note">
          <strong>Policy:</strong> {step.policy_reason}
        </div>
        {step.tool_result && (
          <div className="simulation-result" data-testid="simulation-result">
            <div className="simulation-title"><span aria-hidden="true">▣</span> Simulation recorded</div>
            <p>{step.tool_result.summary}</p>
            <div className="simulation-flags">
              <code>simulated=true</code>
              <code>no_external_side_effect=true</code>
            </div>
          </div>
        )}
      </div>
    </article>
  );
}

export function ControlCenter() {
  const [task, setTask] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [verification, setVerification] = useState<AuditVerification | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [modelHealth, setModelHealth] = useState<ModelHealth | null>(null);
  const [actor, setActor] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<PendingConfirmation | null>(null);
  const refreshInFlight = useRef(false);

  const refreshStatus = useCallback(async () => {
    const [backend, model] = await Promise.allSettled([
      boundaryApi.health(),
      boundaryApi.modelHealth(),
    ]);
    setHealth(backend.status === "fulfilled" ? backend.value : null);
    setModelHealth(model.status === "fulfilled" ? model.value : null);
    if (backend.status === "rejected") setError("Local backend unavailable. Start FastAPI on port 8080 and retry.");
  }, []);

  const refreshRun = useCallback(async (runId: string, quiet = false) => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    try {
      const [nextRun, nextApprovals, nextAudit, nextVerification] = await Promise.all([
        boundaryApi.getRun(runId),
        boundaryApi.approvals(runId),
        boundaryApi.audit(runId),
        boundaryApi.verifyAudit(runId),
      ]);
      setRun(nextRun);
      setApprovals(nextApprovals);
      setAudit(nextAudit);
      setVerification(nextVerification);
    } catch (caught) {
      if (!quiet) setError(userMessage(caught));
    } finally {
      refreshInFlight.current = false;
    }
  }, []);

  useEffect(() => { void refreshStatus(); }, [refreshStatus]);
  useEffect(() => {
    if (!run || TERMINAL_STATES.has(run.state)) return;
    const timer = window.setInterval(() => void refreshRun(run.run_id, true), 3_000);
    return () => window.clearInterval(timer);
  }, [run, refreshRun]);

  const approvalSteps = useMemo(() => {
    const byId = new Map(run?.steps.map((step) => [step.id, step]) ?? []);
    return approvals.map((approval) => ({ approval, step: byId.get(approval.step_id) })).filter(
      (item): item is { approval: Approval; step: RunStep } => Boolean(item.step),
    );
  }, [approvals, run]);

  async function submitTask(event: React.FormEvent) {
    event.preventDefault();
    if (!task.trim()) { setError("Enter a task before creating a plan."); return; }
    setBusy(true); setError(null); setNotice(null);
    try {
      const created = await boundaryApi.createRun(task.trim());
      setRun(created);
      await refreshRun(created.run_id);
      setNotice("Safe plan created. No actions were executed.");
    } catch (caught) {
      setError(userMessage(caught));
    } finally { setBusy(false); }
  }

  async function decideApproval(approval: Approval, decision: "approve" | "reject") {
    if (!actor.trim()) { setError("Enter the actor making this approval decision."); return; }
    setBusy(true); setError(null); setNotice(null);
    try {
      await boundaryApi.decideApproval(approval.approval_id, decision, {
        actor: actor.trim(),
        ...(reason.trim() ? { reason: reason.trim() } : {}),
      });
      await refreshRun(approval.run_id);
      setNotice(`Approval ${decision === "approve" ? "granted" : "rejected"}. Nothing executed automatically.`);
      setReason("");
    } catch (caught) { setError(userMessage(caught)); }
    finally { setBusy(false); setConfirmation(null); }
  }

  function requestDecision(approval: Approval, step: RunStep, decision: "approve" | "reject") {
    if (!actor.trim()) { setError("Enter the actor making this approval decision."); return; }
    if (step.risk_level === "destructive") {
      setConfirmation({ kind: "approval", approval, decision, step });
    } else {
      void decideApproval(approval, decision);
    }
  }

  async function executeRun() {
    if (!run) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const executed = await boundaryApi.executeRun(run.run_id);
      setRun(executed);
      await refreshRun(run.run_id);
      setNotice("Simulation complete. No external side effects occurred.");
    } catch (caught) { setError(userMessage(caught)); }
    finally { setBusy(false); setConfirmation(null); }
  }

  function resetView() {
    setTask(""); setRun(null); setApprovals([]); setAudit([]); setVerification(null);
    setActor(""); setReason(""); setNotice("View reset. Backend runs and audit records were not deleted."); setError(null);
  }

  const dialog = confirmation?.kind === "approval"
    ? {
        title: `${confirmation.decision === "approve" ? "Approve" : "Reject"} destructive action?`,
        description: `${confirmation.step.title} is classified destructive. This records a decision only; no action executes automatically.`,
        confirmLabel: confirmation.decision === "approve" ? "Confirm approval" : "Confirm rejection",
        tone: "danger" as const,
        action: () => void decideApproval(confirmation.approval, confirmation.decision),
      }
    : {
        title: "Run simulated execution?",
        description: "All tools are simulations. No email, calendar event, deletion, payment, upload, publication, share, or command will occur.",
        confirmLabel: "Run simulations",
        tone: "default" as const,
        action: () => void executeRun(),
      };

  return (
    <main className="control-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">B</div>
          <div><p className="brand-name">BOUNDARY</p><p className="brand-tagline">AI That Asks Before It Acts</p></div>
        </div>
        <div className="header-status" aria-label="System summary">
          <span>● Local-only</span><span>◇ Radeon target</span><span>{modelHealth?.available ? "● Model ready" : "○ Model check"}</span>
        </div>
        <button className="button button-ghost" onClick={resetView} type="button">Reset View</button>
      </header>

      <section className="safety-ribbon" aria-label="Safety guarantees">
        <span>Planning does not execute actions.</span>
        <span>Sensitive actions pause for explicit approval.</span>
        <span>All current tool operations are simulated.</span>
        <span>Task data and workflow state remain local.</span>
      </section>

      {(notice || error) && <div className={error ? "alert alert-error" : "alert alert-success"} role={error ? "alert" : "status"}>{error ?? notice}</div>}

      <div className="dashboard-grid">
        <div className="primary-column">
          <section className="panel composer-panel" aria-labelledby="composer-title">
            <p className="eyebrow">01 · Define intent</p>
            <h1 id="composer-title">Create a safe, reviewable plan</h1>
            <p className="panel-intro">Describe the outcome. BOUNDARY will plan locally, classify every action, and stop before protected work.</p>
            <form onSubmit={submitTask}>
              <label className="field-label" htmlFor="task">Task</label>
              <textarea
                id="task"
                onChange={(event) => setTask(event.target.value)}
                placeholder="What should BOUNDARY plan?"
                rows={6}
                value={task}
              />
              <div className="composer-actions">
                <button className="button button-ghost" onClick={() => setTask(EXAMPLE_TASK)} type="button">Use demo task</button>
                <button className="button button-primary" disabled={busy} type="submit">{busy ? "Planning locally…" : "Create Safe Plan"}</button>
              </div>
              <p className="form-help">Planning calls the local Qwen3-8B model. It does not invoke tools.</p>
            </form>
          </section>

          {run && (
            <section className="panel run-panel" aria-labelledby="run-title">
              <div className="section-heading">
                <div><p className="eyebrow">02 · Policy-normalized plan</p><h2 id="run-title">Run {shortId(run.run_id)}</h2></div>
                <StatePill state={run.state} />
              </div>
              <div className="step-list">{run.steps.map((step, index) => <StepCard index={index} key={step.id} step={step} />)}</div>
              <div className="execution-box">
                <div><h3>Simulation controls</h3><p>No real external or destructive action can occur. Pending protected steps will return a typed conflict.</p></div>
                <button className="button button-primary" disabled={busy || TERMINAL_STATES.has(run.state)} onClick={() => setConfirmation({ kind: "execute" })} type="button">Execute simulations</button>
              </div>
            </section>
          )}

          {run && (
            <section className="panel timeline-panel" aria-labelledby="timeline-title">
              <div className="section-heading"><div><p className="eyebrow">04 · Tamper-evident record</p><h2 id="timeline-title">Run timeline</h2></div><span className="event-count">{audit.length} events</span></div>
              <ol className="timeline">
                {audit.map((event) => (
                  <li key={event.event_id}>
                    <div className="timeline-dot" aria-hidden="true" />
                    <div className="timeline-event">
                      <div><strong>{event.event_type.replaceAll("_", " ")}</strong><time dateTime={event.timestamp_utc}>{formatTime(event.timestamp_utc)}</time></div>
                      <p>Actor: {event.actor} · {event.previous_state ?? "start"} → {event.new_state ?? "unchanged"}</p>
                      {(event.action_type || event.risk_level) && <p>{event.action_type ?? "run"} · {event.risk_level ?? "system"}</p>}
                      {event.policy_reason && <p>{event.policy_reason}</p>}
                      <div className="hash-row"><code>prev {shortId(event.previous_event_hash)}</code><code>hash {shortId(event.event_hash)}</code></div>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>

        <aside className="side-column" aria-label="Control Center status and approvals">
          <section className="panel status-panel" aria-labelledby="status-title">
            <p className="eyebrow">System status</p><h2 id="status-title">Local inference fabric</h2>
            <div className="status-card"><span className={health ? "status-light online" : "status-light"} aria-hidden="true" /><div><strong>{health ? "Backend online" : "Backend unavailable"}</strong><p>FastAPI · port 8080</p></div></div>
            <div className="status-card"><span className={modelHealth?.available ? "status-light online" : "status-light"} aria-hidden="true" /><div><strong>Qwen3-8B via local vLLM</strong><p>{modelHealth?.available ? `Available · ${modelHealth.model_name}` : "Model unavailable or unchecked"}</p></div></div>
            <div className="status-card"><span className="status-icon" aria-hidden="true">GPU</span><div><strong>AMD Radeon Cloud GPU</strong><p>Configured execution target</p></div></div>
            <div className="status-facts"><span>Local-only inference</span><span>Remote APIs {health?.remote_apis_enabled === false ? "disabled" : "not verified"}</span><span>No analytics or tracking</span></div>
          </section>

          <section className="panel approval-panel" aria-labelledby="approval-title">
            <div className="section-heading"><div><p className="eyebrow">03 · Human boundary</p><h2 id="approval-title">Approval Inbox</h2></div><span className="count-badge">{approvalSteps.length}</span></div>
            {!run && <p className="empty-state">Create a run to see protected actions.</p>}
            {run && approvalSteps.length === 0 && <p className="empty-state">No pending approvals for this run.</p>}
            {approvalSteps.length > 0 && (
              <div className="decision-fields">
                <label className="field-label" htmlFor="actor">Decision actor</label>
                <input id="actor" onChange={(event) => setActor(event.target.value)} placeholder="Your name or role" value={actor} />
                <label className="field-label" htmlFor="reason">Reason <span>(optional)</span></label>
                <input id="reason" maxLength={500} onChange={(event) => setReason(event.target.value)} placeholder="Short decision note" value={reason} />
              </div>
            )}
            <div className="approval-list">
              {approvalSteps.map(({ approval, step }) => (
                <article className="approval-card" key={approval.approval_id}>
                  <RiskBadge risk={step.risk_level} />
                  <h3>{step.title}</h3><p className="mono-label">{step.action_type}</p><p>{step.policy_reason}</p>
                  <dl><div><dt>Run</dt><dd>{shortId(approval.run_id)}</dd></div><div><dt>Step</dt><dd>{shortId(approval.step_id)}</dd></div><div><dt>Status</dt><dd>{approval.status}</dd></div></dl>
                  <div className="approval-actions">
                    <button className="button button-approve" disabled={busy} onClick={() => requestDecision(approval, step, "approve")} type="button">Approve</button>
                    <button className="button button-reject" disabled={busy} onClick={() => requestDecision(approval, step, "reject")} type="button">Reject</button>
                  </div>
                </article>
              ))}
            </div>
          </section>

          {run && (
            <section className={`panel verification-panel ${verification && !verification.valid ? "verification-invalid" : ""}`} aria-labelledby="verification-title">
              <p className="eyebrow">Audit verification</p>
              <h2 id="verification-title">{verification?.valid ? "✓ Audit chain verified" : verification ? "⚠ Tamper warning" : "Verifying audit chain…"}</h2>
              {verification?.valid && <><p><code>valid=true</code></p><p>{audit.length} linked events verified locally.</p></>}
              {verification && !verification.valid && <><p><code>valid=false</code></p><p>First invalid event: {shortId(verification.first_invalid_event_id)}</p></>}
            </section>
          )}

          <section className="privacy-card"><span aria-hidden="true">◈</span><div><strong>Local by design</strong><p>Task data and workflow state remain on the local BOUNDARY stack. No remote AI provider is configured.</p></div></section>
        </aside>
      </div>

      <footer><strong>No external side effects occurred.</strong> Current tools produce simulation records only.</footer>

      <ConfirmationDialog
        confirmLabel={dialog.confirmLabel}
        description={dialog.description}
        onCancel={() => setConfirmation(null)}
        onConfirm={dialog.action}
        open={confirmation !== null}
        title={dialog.title}
        tone={dialog.tone}
      />
    </main>
  );
}
