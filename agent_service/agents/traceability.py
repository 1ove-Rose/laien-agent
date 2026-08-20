from ..errors import AgentRunError
from .common import emit


STAGE = "追溯验证"


async def traceability_validator(state, writer=None):
    emit(writer, "stage_started", STAGE, "开始验证 Review -> Finding -> Requirement -> TestCase 链路。")
    review_ids = {review["id"] for review in state["reviews"]}
    finding_ids = {finding["id"] for finding in state["findings"]}
    requirement_ids = {requirement["id"] for requirement in state["requirements"]}
    problems = []

    for finding in state["findings"]:
        for review_id in finding.get("evidenceIds", []):
            if review_id not in review_ids:
                problems.append(f"{finding.get('id')} 引用不存在评论 {review_id}")
        if finding.get("supportCount") != len(finding.get("evidenceIds", [])):
            problems.append(f"{finding.get('id')} 支持数不一致")

    for requirement in state["requirements"]:
        if requirement.get("sourceFindingId") not in finding_ids:
            problems.append(f"{requirement.get('id')} 缺少有效 sourceFindingId")

    for test in state["tests"]:
        if test.get("requirementId") not in requirement_ids:
            problems.append(f"{test.get('id')} 缺少有效 requirementId")
        if test.get("sourceFindingId") not in finding_ids:
            problems.append(f"{test.get('id')} 缺少有效 sourceFindingId")

    if problems:
        detail = "；".join(problems)
        emit(writer, "validation", STAGE, "追溯链路校验失败", {"type": "error", "title": "追溯链路校验失败", "detail": detail, "stage": STAGE})
        raise AgentRunError("TRACEABILITY_VALIDATION_FAILED", "追溯链路校验失败。", stage=STAGE, retryable=False)

    validation = {
        "type": "pass",
        "title": "端到端追溯验证",
        "detail": f"{len(state['tests'])} 条 Review -> Finding -> Requirement -> TestCase 链路验证通过。",
        "stage": STAGE,
    }
    emit(writer, "validation", STAGE, validation["title"], validation)
    emit(writer, "stage_completed", STAGE, "追溯链路验证通过。")
    return {"validations": state["validations"] + [validation]}
