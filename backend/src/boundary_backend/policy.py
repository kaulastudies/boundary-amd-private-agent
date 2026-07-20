"""Deterministic, monotonic action policy for generated plans."""

import re
from dataclasses import dataclass
from typing import Optional

from .models import ActionType, PlanResponse, PlanStep, RiskLevel


@dataclass(frozen=True)
class ActionPolicy:
    risk_level: RiskLevel
    requires_approval: bool
    reason: str


RISK_ORDER = {
    RiskLevel.safe: 0,
    RiskLevel.review: 1,
    RiskLevel.sensitive: 2,
    RiskLevel.destructive: 3,
    RiskLevel.blocked: 4,
}

ACTION_POLICIES = {
    ActionType.inspect_local: ActionPolicy(
        RiskLevel.safe, False, "Local read-only operation"
    ),
    ActionType.analyze_local: ActionPolicy(
        RiskLevel.safe, False, "Local analysis operation"
    ),
    ActionType.draft_local: ActionPolicy(
        RiskLevel.safe, False, "Local drafting operation"
    ),
    ActionType.write_local: ActionPolicy(
        RiskLevel.review, True, "Local modification requires approval"
    ),
    ActionType.send_external: ActionPolicy(
        RiskLevel.sensitive, True, "External communication requires approval"
    ),
    ActionType.schedule_external: ActionPolicy(
        RiskLevel.sensitive, True, "Calendar modification requires approval"
    ),
    ActionType.share_external: ActionPolicy(
        RiskLevel.sensitive, True, "External sharing requires approval"
    ),
    ActionType.upload_external: ActionPolicy(
        RiskLevel.sensitive, True, "External upload requires approval"
    ),
    ActionType.publish_external: ActionPolicy(
        RiskLevel.sensitive, True, "External publication requires approval"
    ),
    ActionType.delete_local: ActionPolicy(
        RiskLevel.destructive, True, "Destructive file operation requires approval"
    ),
    ActionType.overwrite_local: ActionPolicy(
        RiskLevel.destructive, True, "Destructive overwrite requires approval"
    ),
    ActionType.execute_command: ActionPolicy(
        RiskLevel.sensitive, True, "Command execution requires approval"
    ),
    ActionType.financial_action: ActionPolicy(
        RiskLevel.sensitive, True, "Financial action requires approval"
    ),
    ActionType.credential_access: ActionPolicy(
        RiskLevel.blocked, True, "Credential or secret handling is blocked"
    ),
    ActionType.unsupported: ActionPolicy(
        RiskLevel.blocked, True, "Unsupported action is blocked"
    ),
}

_CREDENTIAL_EXPORT = re.compile(
    r"\b(expose|reveal|export|transmit|send|share)\b.{0,80}"
    r"\b(passwords?|credentials?|private keys?|secrets?|access tokens?)\b",
    re.IGNORECASE,
)
_DESTRUCTIVE = re.compile(
    r"\b(delete|purge|overwrite|revoke|permanently remove|erase)\b",
    re.IGNORECASE,
)
_FINANCIAL = re.compile(
    r"\b(pay|payment|purchase|buy|transfer funds?|subscribe|subscription)\b",
    re.IGNORECASE,
)
_SEND_EXTERNAL = re.compile(
    r"\b(send|transmit|deliver|dispatch|notify)\b.{0,100}"
    r"\b(email|message|notification|document|file|data|client|customer|recipient)\b",
    re.IGNORECASE,
)
_SCHEDULE_EXTERNAL = re.compile(
    r"\b(schedule|create|book|set up)\b.{0,80}"
    r"\b(meeting|appointment|calendar event|invite)\b",
    re.IGNORECASE,
)
_SHARE_EXTERNAL = re.compile(
    r"\bshare\b.{0,80}\b(document|file|data|report|contract|externally|client)\b",
    re.IGNORECASE,
)
_UPLOAD_EXTERNAL = re.compile(
    r"\bupload\b|\b(call|invoke)\b.{0,40}\b(external )?api\b",
    re.IGNORECASE,
)
_PUBLISH_EXTERNAL = re.compile(
    r"\b(publish|post)\b.{0,80}\b(content|article|report|publicly|website|social)\b",
    re.IGNORECASE,
)
_DRAFT_LOCAL = re.compile(
    r"\b(draft|compose|prepare)\b.{0,80}\b(email|message|text|letter|response)\b",
    re.IGNORECASE,
)
_ANALYZE_LOCAL = re.compile(
    r"\b(analy[sz]e|summari[sz]e|compare|evaluate)\b", re.IGNORECASE
)
_INSPECT_LOCAL = re.compile(
    r"\b(inspect|review|read|examine)\b", re.IGNORECASE
)


def _semantic_action(step: PlanStep) -> Optional[ActionType]:
    text = f"{step.title}\n{step.description}"
    if _CREDENTIAL_EXPORT.search(text):
        return ActionType.credential_access
    if _DESTRUCTIVE.search(text):
        if re.search(r"\boverwrite\b", text, re.IGNORECASE):
            return ActionType.overwrite_local
        return ActionType.delete_local
    if _FINANCIAL.search(text):
        return ActionType.financial_action
    if _SCHEDULE_EXTERNAL.search(text):
        return ActionType.schedule_external
    if _SEND_EXTERNAL.search(text):
        return ActionType.send_external
    if _SHARE_EXTERNAL.search(text):
        return ActionType.share_external
    if _UPLOAD_EXTERNAL.search(text):
        return ActionType.upload_external
    if _PUBLISH_EXTERNAL.search(text):
        return ActionType.publish_external
    if _DRAFT_LOCAL.search(text):
        return ActionType.draft_local
    if _ANALYZE_LOCAL.search(text):
        return ActionType.analyze_local
    if _INSPECT_LOCAL.search(text):
        return ActionType.inspect_local
    return None


def _authoritative_action(step: PlanStep) -> ActionType:
    """Use semantics only when they cannot weaken the typed action policy."""
    semantic_action = _semantic_action(step)
    if semantic_action is None:
        return step.action_type
    typed_risk = ACTION_POLICIES[step.action_type].risk_level
    semantic_risk = ACTION_POLICIES[semantic_action].risk_level
    if RISK_ORDER[semantic_risk] >= RISK_ORDER[typed_risk]:
        return semantic_action
    return step.action_type


def enforce_action_policy(plan: PlanResponse) -> PlanResponse:
    """Normalize action policy without ever lowering model-declared risk."""
    normalized_steps = []
    for step in plan.steps:
        action_type = _authoritative_action(step)
        policy = ACTION_POLICIES[action_type]
        risk_level = max(
            (step.risk_level, policy.risk_level), key=lambda risk: RISK_ORDER[risk]
        )
        requires_approval = (
            step.requires_approval
            or policy.requires_approval
            or RISK_ORDER[risk_level] >= RISK_ORDER[RiskLevel.sensitive]
        )
        reason = policy.reason
        if RISK_ORDER[step.risk_level] > RISK_ORDER[policy.risk_level]:
            reason = "Higher model-declared risk preserved by backend policy"
        normalized_steps.append(
            step.model_copy(
                update={
                    "action_type": action_type,
                    "risk_level": risk_level,
                    "requires_approval": requires_approval,
                    "policy_reason": reason,
                }
            )
        )
    return plan.model_copy(update={"steps": normalized_steps})
