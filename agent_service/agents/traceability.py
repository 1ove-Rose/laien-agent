from ..errors import AgentRunError
from .common import emit, resolve_writer


STAGE = "追溯验证"


async def traceability_validator(state, writer=None):
    writer = resolve_writer(writer)
    positive_only = state.get("analysisMode") == "positive"
    emit(
        writer,
        "stage_started",
        STAGE,
        "开始验证 Review -> Finding 链路。" if positive_only else "开始验证 Review -> Finding -> Requirement -> TestCase 链路。",
    )
    review_ids = {review["id"] for review in state["reviews"]}
    finding_ids = {finding["id"] for finding in state["findings"]}
    finding_map = {finding["id"]: finding for finding in state["findings"]}
    requirement_ids = {requirement["id"] for requirement in state["requirements"]}
    problems = []

    for finding in state["findings"]:
        for review_id in finding.get("evidenceIds", []):
            if review_id not in review_ids:
                problems.append(f"{finding.get('id')} 引用不存在评论 {review_id}")
        for review_id in finding.get("conflictEvidenceIds", []):
            if review_id not in review_ids:
                problems.append(f"{finding.get('id')} 引用不存在冲突评论 {review_id}")
        if finding.get("supportCount") != len(finding.get("evidenceIds", [])):
            problems.append(f"{finding.get('id')} 支持数不一致")

    for requirement in state["requirements"]:
        if requirement.get("sourceFindingId") not in finding_ids:
            problems.append(f"{requirement.get('id')} 缺少有效 sourceFindingId")
        elif finding_map[requirement["sourceFindingId"]].get("status") == "rejected":
            problems.append(f"{requirement.get('id')} 引用了已拒绝 finding")

    for test in state["tests"]:
        if test.get("requirementId") not in requirement_ids:
            problems.append(f"{test.get('id')} 缺少有效 requirementId")
        if test.get("sourceFindingId") not in finding_ids:
            problems.append(f"{test.get('id')} 缺少有效 sourceFindingId")
        elif test.get("sourceFindingId") != next((item.get("sourceFindingId") for item in state["requirements"] if item.get("id") == test.get("requirementId")), None):
            problems.append(f"{test.get('id')} 的 finding 与 requirement 链路不一致")

    if problems:
        detail = "；".join(problems)
        emit(writer, "validation", STAGE, "追溯链路校验失败", {"type": "error", "title": "追溯链路校验失败", "detail": detail, "stage": STAGE})
        raise AgentRunError("TRACEABILITY_VALIDATION_FAILED", "追溯链路校验失败。", stage=STAGE, retryable=False)

    unsupported_hypotheses = [
        finding for finding in state["findings"]
        if finding.get("status") == "hypothesis" and not finding.get("evidenceIds")
    ]
    if unsupported_hypotheses:
        validation = {
            "type": "revised",
            "title": "追溯验证通过（含无证据假设）",
            "detail": (
                f"引用关系有效；{len(unsupported_hypotheses)} 条洞察没有 Review 支持，"
                "已明确标记为假设并沿 Requirement -> TestCase 链路传递。"
            ),
            "stage": STAGE,
        }
    else:
        validation = {
            "type": "pass",
            "title": "端到端追溯验证",
            "detail": (
                f"{len(state['findings'])} 条 Review -> Finding 产品优点证据链验证通过。"
                if positive_only
                else f"{len(state['tests'])} 条 Review -> Finding -> Requirement -> TestCase 链路验证通过。"
            ),
            "stage": STAGE,
        }
    emit(writer, "validation", STAGE, validation["title"], validation)
    emit(writer, "stage_completed", STAGE, "追溯链路验证通过。")
    return {"validations": state["validations"] + [validation]}
