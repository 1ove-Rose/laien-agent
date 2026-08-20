import pytest
import asyncio

from agent_service.agents.critic import deterministic_evidence_checks
from agent_service.agents.traceability import traceability_validator
from agent_service.errors import AgentRunError


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


def test_traceability_validator_passes_valid_chain():
    result = asyncio.run(traceability_validator(base_state()))

    assert result["validations"][0]["type"] == "pass"


def test_traceability_validator_rejects_broken_chain():
    state = base_state()
    state["tests"][0]["requirementId"] = "missing"

    with pytest.raises(AgentRunError) as exc:
        asyncio.run(traceability_validator(state))

    assert exc.value.code == "TRACEABILITY_VALIDATION_FAILED"
