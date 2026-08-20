from ..errors import AgentRunError
from ..llm import invoke_json
from ..schemas import CriticResponse, ValidationResult
from .common import dump_json, emit


STAGE = "证据审查"


def deterministic_evidence_checks(state):
    review_ids = {review["id"] for review in state["reviews"]}
    validations = []
    problems = []
    for finding in state["findings"]:
        evidence_ids = finding.get("evidenceIds") or []
        missing = [review_id for review_id in evidence_ids if review_id not in review_ids]
        if not evidence_ids:
            problems.append(f"{finding.get('id')} 缺少证据。")
        if missing:
            problems.append(f"{finding.get('id')} 引用了不存在的评论 ID: {', '.join(missing)}。")
        if finding.get("supportCount") != len(evidence_ids):
            problems.append(f"{finding.get('id')} supportCount 与 evidenceIds 数量不一致。")

    if problems:
        validations.append(ValidationResult(type="error", title="洞察证据校验失败", detail=" ".join(problems), stage=STAGE))
    else:
        validations.append(ValidationResult(type="pass", title="洞察证据校验通过", detail="所有洞察均引用真实评论且支持数一致。", stage=STAGE))
    return not problems, validations, " ".join(problems)


async def evidence_critic(state, llm, writer=None):
    emit(writer, "stage_started", STAGE, "开始检查洞察证据、冲突和结论边界。")
    deterministic_passed, base_validations, base_notes = deterministic_evidence_checks(state)
    if not deterministic_passed:
        validations = [item.model_dump() for item in base_validations]
        for item in validations:
            emit(writer, "validation", STAGE, item["title"], item)
        return {"criticPassed": False, "criticNotes": base_notes, "validations": state["validations"] + validations}

    system = """
你是 Evidence Critic。只输出 JSON。
schema: {"passed":true,"validations":[{"type":"pass|error|revised","title":"string","detail":"string","stage":"证据审查"}],"revisionInstructions":"string|null"}
审查是否存在过度泛化、证据不足、与评论文本矛盾的问题。失败时给出可执行修订意见。
"""
    user = f"分析目标：{state['goal']}\n评论：{dump_json(state['reviews'])}\n洞察：{dump_json(state['findings'])}"
    parsed = await invoke_json(llm, stage=STAGE, system=system, user=user, response_model=CriticResponse, writer=writer)
    validations = [item.model_dump() for item in parsed.validations]
    for item in validations:
        emit(writer, "validation", STAGE, item["title"], item)
    emit(writer, "stage_completed", STAGE, "证据审查完成。", {"passed": parsed.passed})
    return {
        "criticPassed": parsed.passed,
        "criticNotes": parsed.revisionInstructions or "",
        "validations": state["validations"] + validations,
    }


async def critic_failure(state, writer=None):
    message = "洞察证据审查未通过，且已达到最大修订次数。"
    emit(writer, "error", STAGE, message, {"code": "EVIDENCE_VALIDATION_FAILED", "retryable": False})
    raise AgentRunError("EVIDENCE_VALIDATION_FAILED", message, stage=STAGE, retryable=False)
