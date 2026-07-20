import pytest

from boundary_backend.models import PlanResponse, RiskLevel
from boundary_backend.policy import enforce_action_policy


def make_plan(
    title: str,
    description: str,
    action_type: str,
    risk_level: str = "safe",
    requires_approval: bool = False,
) -> PlanResponse:
    return PlanResponse.model_validate(
        {
            "steps": [
                {
                    "id": "step-1",
                    "title": title,
                    "description": description,
                    "action_type": action_type,
                    "risk_level": risk_level,
                    "requires_approval": requires_approval,
                    "policy_reason": "Model supplied reason is advisory",
                }
            ]
        }
    )


@pytest.mark.parametrize(
    ("title", "description", "action_type", "expected_action"),
    [
        ("Review Contract", "Read the local document.", "inspect_local", "inspect_local"),
        ("Analyze Contract", "Summarize its local content.", "analyze_local", "analyze_local"),
        ("Draft Email", "Compose an email without sending it.", "draft_local", "draft_local"),
        ("Suggest Meeting Time", "Propose times without booking.", "analyze_local", "analyze_local"),
    ],
)
def test_local_no_side_effect_actions_remain_low_risk(
    title: str, description: str, action_type: str, expected_action: str
) -> None:
    step = enforce_action_policy(
        make_plan(title, description, action_type)
    ).steps[0]
    assert step.action_type.value == expected_action
    assert step.risk_level in {RiskLevel.safe, RiskLevel.review}
    assert step.requires_approval is False
    assert step.policy_reason


@pytest.mark.parametrize(
    ("title", "description", "model_action", "expected_action", "reason"),
    [
        (
            "Send Email to Client",
            "Send the completed email to the client.",
            "draft_local",
            "send_external",
            "External communication requires approval",
        ),
        (
            "Schedule Meeting",
            "Create a meeting and invite attendees.",
            "analyze_local",
            "schedule_external",
            "Calendar modification requires approval",
        ),
        (
            "Share Contract",
            "Share the document with the client.",
            "inspect_local",
            "share_external",
            "External sharing requires approval",
        ),
        (
            "Upload Report",
            "Upload data to the external portal.",
            "draft_local",
            "upload_external",
            "External upload requires approval",
        ),
        (
            "Publish Article",
            "Publish content on the website.",
            "draft_local",
            "publish_external",
            "External publication requires approval",
        ),
    ],
)
def test_external_semantics_override_safe_model_classification(
    title: str,
    description: str,
    model_action: str,
    expected_action: str,
    reason: str,
) -> None:
    step = enforce_action_policy(
        make_plan(title, description, model_action, "safe", False)
    ).steps[0]
    assert step.action_type.value == expected_action
    assert step.risk_level == RiskLevel.sensitive
    assert step.requires_approval is True
    assert step.policy_reason == reason


@pytest.mark.parametrize(
    ("title", "description", "expected_action"),
    [
        ("Delete Contract", "Delete the local contract.", "delete_local"),
        ("Overwrite Contract", "Overwrite the existing local file.", "overwrite_local"),
        ("Purge Records", "Permanently remove the records.", "delete_local"),
    ],
)
def test_destructive_semantics_are_authoritative(
    title: str, description: str, expected_action: str
) -> None:
    step = enforce_action_policy(
        make_plan(title, description, "inspect_local", "safe", False)
    ).steps[0]
    assert step.action_type.value == expected_action
    assert step.risk_level == RiskLevel.destructive
    assert step.requires_approval is True
    assert "Destructive" in step.policy_reason


def test_financial_action_cannot_be_safe() -> None:
    step = enforce_action_policy(
        make_plan(
            "Make Payment", "Transfer funds for the purchase.", "analyze_local"
        )
    ).steps[0]
    assert step.action_type.value == "financial_action"
    assert step.risk_level == RiskLevel.sensitive
    assert step.requires_approval is True
    assert step.policy_reason == "Financial action requires approval"


def test_secret_export_is_blocked_even_when_model_marks_it_safe() -> None:
    step = enforce_action_policy(
        make_plan(
            "Export Credentials",
            "Reveal passwords and transmit secrets.",
            "draft_local",
        )
    ).steps[0]
    assert step.action_type.value == "credential_access"
    assert step.risk_level == RiskLevel.blocked
    assert step.requires_approval is True
    assert step.policy_reason == "Credential or secret handling is blocked"


@pytest.mark.parametrize("protected_risk", ["sensitive", "destructive", "blocked"])
def test_protected_model_risks_are_never_downgraded(protected_risk: str) -> None:
    step = enforce_action_policy(
        make_plan(
            "Review Local File",
            "Read the local document only.",
            "inspect_local",
            protected_risk,
            False,
        )
    ).steps[0]
    assert step.risk_level.value == protected_risk
    assert step.requires_approval is True
    assert step.policy_reason == "Higher model-declared risk preserved by backend policy"


def test_model_cannot_weaken_typed_external_action_with_draft_wording() -> None:
    step = enforce_action_policy(
        make_plan(
            "Draft Email",
            "Prepare text locally without sending.",
            "send_external",
            "safe",
            False,
        )
    ).steps[0]
    assert step.action_type.value == "send_external"
    assert step.risk_level == RiskLevel.sensitive
    assert step.requires_approval is True
