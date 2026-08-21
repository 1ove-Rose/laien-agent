import pytest
import asyncio

from agent_service.agents.critic import (
    apply_critic_decisions,
    decisions_resolve_review,
    deterministic_evidence_checks,
    finalize_invalid_as_hypotheses,
    finalize_unresolved_as_hypotheses,
)
from agent_service.agents.traceability import traceability_validator
from agent_service.errors import AgentRunError
from agent_service.schemas import FindingDecision


def base_state():
    return {
        "reviews": [{"id": "r1"}, {"id": "r2"}],
        "findings": [{"id": "F-1", "evidenceIds": ["r1"], "supportCount": 1}],
        "requirements": [{"id": "REQ-1", "sourceFindingId": "F-1"}],
        "tests": [{"id": "TC-1", "requirementId": "REQ-1", "sourceFindingId": "F-1"}],
        "validations": [],
    }


def test_critic_rejects_missing_review_id():
    state = base_state()
    state["findings"][0]["evidenceIds"] = ["missing"]
    passed, validations, notes = deterministic_evidence_checks(state)

    assert passed is False
    assert validations[0].type == "error"
    assert "不存在" in notes


def test_critic_rejects_missing_conflict_review_id():
    state = base_state()
    state["findings"][0]["conflictEvidenceIds"] = ["missing-conflict"]
    passed, validations, notes = deterministic_evidence_checks(state)

    assert passed is False
    assert validations[0].type == "error"
    assert "冲突证据" in notes


def test_conflict_statement_without_ids_is_left_for_semantic_critic():
    state = base_state()
    state["findings"][0]["conflict"] = "评论之间存在相反反馈。"

    passed, _, notes = deterministic_evidence_checks(state)

    assert passed is True
    assert notes == ""


def test_traceability_validator_passes_valid_chain():
    result = asyncio.run(traceability_validator(base_state()))

    assert result["validations"][0]["type"] == "pass"


def test_traceability_validator_rejects_broken_chain():
    state = base_state()
    state["tests"][0]["requirementId"] = "missing"

    with pytest.raises(AgentRunError) as exc:
        asyncio.run(traceability_validator(state))

    assert exc.value.code == "TRACEABILITY_VALIDATION_FAILED"


def test_critic_can_mark_unsupported_finding_as_hypothesis_for_downstream_use():
    state = base_state()
    findings, rejected = apply_critic_decisions(
        state,
        [FindingDecision(findingId="F-1", action="hypothesis", reason="只有一条评论支持，仍需产品验证。")],
    )

    assert findings[0]["status"] == "hypothesis"
    assert "产品验证" in findings[0]["statusReason"]
    assert rejected == []


def test_critic_adds_conflict_ids_to_processed_findings_only():
    state = base_state()
    findings, rejected = apply_critic_decisions(
        state,
        [FindingDecision(
            findingId="F-1",
            action="hypothesis",
            reason="支持和反对反馈并存。",
            conflictEvidenceIds=["r2"],
        )],
    )

    assert findings[0]["conflictEvidenceIds"] == ["r2"]
    assert state["findings"][0].get("conflictEvidenceIds") is None
    assert rejected == []


def test_critic_keeps_rejected_finding_as_hypothesis():
    state = base_state()
    findings, rejected = apply_critic_decisions(
        state,
        [FindingDecision(findingId="F-1", action="reject", reason="评论内容与该结论不匹配。")],
    )

    assert findings[0]["status"] == "hypothesis"
    assert "完全不受评论证据支持" in findings[0]["statusReason"]
    assert rejected == []


def test_invalid_finding_is_sanitized_and_kept_as_hypothesis_after_revision():
    state = base_state()
    state["findings"][0].update(
        evidenceIds=["missing"],
        conflictEvidenceIds=["r2", "missing-conflict"],
        supportCount=1,
    )

    findings, changed = finalize_invalid_as_hypotheses(state, "修订后仍无有效支持证据。")

    assert changed == ["F-1"]
    assert findings[0]["status"] == "hypothesis"
    assert findings[0]["evidenceIds"] == []
    assert findings[0]["supportCount"] == 0
    assert findings[0]["conflictEvidenceIds"] == ["r2"]


def test_hypothesis_decision_resolves_a_failed_global_review():
    findings = [{"id": "F-1"}, {"id": "F-2"}]
    decisions = [
        FindingDecision(findingId="F-1", action="accept", reason="证据充分。"),
        FindingDecision(findingId="F-2", action="hypothesis", reason="仅有一条弱证据。"),
    ]

    assert decisions_resolve_review(findings, decisions, model_passed=False) is True


def test_revise_decision_requires_a_revision_round():
    findings = [{"id": "F-1"}]
    decisions = [FindingDecision(findingId="F-1", action="revise", reason="结论过度泛化。")]

    assert decisions_resolve_review(findings, decisions, model_passed=False) is False


def test_unresolved_finding_becomes_hypothesis_after_revision_limit():
    findings = [{"id": "F-1", "status": "revised", "statusReason": ""}]
    decisions = [FindingDecision(findingId="F-1", action="revise", reason="仍只有单条证据。")]
    finalized, changed = finalize_unresolved_as_hypotheses(findings, decisions, "")

    assert changed == ["F-1"]
    assert finalized[0]["status"] == "hypothesis"
    assert "单条证据" in finalized[0]["statusReason"]
