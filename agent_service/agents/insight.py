from ..llm import invoke_json
from ..schemas import InsightResponse
from .common import data_limitations, data_limitations_instruction, dump_json, emit, resolve_writer, reviews_for_prompt
from ..analysis_mode import focus_reviews, mode_instruction


STAGE = "洞察发现"


def ordered_reviews_for_insight(reviews, mode):
    focused = focus_reviews(reviews, mode)
    focused_ids = {review.get("id") for review in focused}
    return focused + [review for review in reviews if review.get("id") not in focused_ids]


async def insight_agent(state, llm, writer=None):
    writer = resolve_writer(writer)
    emit(writer, "stage_started", STAGE, "开始从评论分类中聚合证据洞察。")
    mode = state.get("analysisMode", "negative")
    system = """
你是产品洞察分析师。只输出 JSON。
schema: {"findings":[{"id":"F-1","title":"string","summary":"string","evidenceIds":["review-id"],"supportCount":1,"confidence":"高|中|低","conflict":"string","conflictEvidenceIds":["review-id"],"version":"v0.1"}]}
规则：
1. 每条 finding 必须引用真实 review.id。
2. supportCount 必须等于 evidenceIds 数量。
3. 根据分析模式选择证据方向；不要把固定的问题清单当成每次分析的必选项。
4. 不要生成没有证据的 finding。
5. status 固定为 validated；是否修订、假设或拒绝由证据审查节点决定。
6. title、summary、conflict、confidence 和 version 必须使用简体中文。即使证据评论为英文或其他语言，也必须翻译和归纳为中文；仅保留 review.id 原样不翻译。
7. conflictEvidenceIds 必须列出与该洞察结论相矛盾的真实 review.id；它们不计入 supportCount。没有冲突时返回空数组 []，不要编造 ID。
8. 证据候选评论包含不同评分的完整样本；必须比较支持评论和反向评论，发现正反反馈不一致时列出冲突评论 ID。
"""
    ordered_reviews = ordered_reviews_for_insight(state["reviews"], mode)
    user = (
        f"分析目标：{state['goal']}\n{mode_instruction(mode)}\n"
        f"{data_limitations_instruction(state)}\n"
        f"证据候选评论：{dump_json(reviews_for_prompt(ordered_reviews, 500))}\n"
        f"分类：{dump_json(state['classifications'])}"
    )
    parsed = await invoke_json(llm, stage=STAGE, system=system, user=user, response_model=InsightResponse, writer=writer)
    findings = [{**item.model_dump(), "status": "validated", "statusReason": "等待证据审查。"} for item in parsed.findings]
    limitations = state.get("dataLimitations") or data_limitations(state)
    emit(
        writer,
        "artifact",
        STAGE,
        "洞察发现已生成。",
        {"insights": findings, "insightVersion": "before-revision", "dataLimitations": limitations},
    )
    emit(writer, "stage_completed", STAGE, f"完成 {len(findings)} 条洞察。")
    return {"findingsBeforeRevision": findings, "findings": findings, "dataLimitations": limitations}


async def insight_revision_agent(state, llm, writer=None):
    writer = resolve_writer(writer)
    emit(writer, "revision", STAGE, "证据审查未通过，开始修订洞察。", {"notes": state.get("criticNotes", "")})
    mode = state.get("analysisMode", "negative")
    system = """
你是产品洞察修订专家。只输出 JSON。
schema: {"findings":[{"id":"F-1","title":"string","summary":"string","evidenceIds":["review-id"],"supportCount":1,"confidence":"高|中|低","conflict":"string","conflictEvidenceIds":["review-id"],"version":"v0.2 已修订"}]}
只基于真实评论证据修订。删除没有证据、证据不存在、支持数错误或过度泛化的 finding。
修订范围仅限于被 Evidence Critic 标出的冲突或证据边界问题；没有冲突且不需要修订的 finding 应保持原内容。
保留的 finding 必须使用真实 review.id；status 由系统标记为 revised。
title、summary、conflict、confidence 和 version 必须使用简体中文；仅保留 review.id 原样不翻译。
conflictEvidenceIds 必须只包含真实且与结论冲突的 review.id；没有冲突时返回空数组 []。
"""
    ordered_reviews = ordered_reviews_for_insight(state["reviews"], mode)
    user = (
        f"分析目标：{state['goal']}\n{mode_instruction(mode)}\n"
        f"{data_limitations_instruction(state)}\n"
        f"审查意见：{state.get('criticNotes', '')}\n"
        f"评论：{dump_json(reviews_for_prompt(ordered_reviews, 500))}\n"
        f"原洞察：{dump_json(state['findings'])}"
    )
    parsed = await invoke_json(llm, stage=STAGE, system=system, user=user, response_model=InsightResponse, writer=writer)
    source_findings = state.get("findings", [])
    parsed_map = {item.id: item.model_dump() for item in parsed.findings}
    findings = []
    for source in source_findings:
        if source.get("status") != "revised":
            findings.append(source)
            continue
        finding = parsed_map.get(source.get("id"), source.copy())
        finding["conflictEvidenceIds"] = list(dict.fromkeys(
            (source.get("conflictEvidenceIds") or []) + (finding.get("conflictEvidenceIds") or [])
        ))
        findings.append({**finding, "status": "revised", "statusReason": "已按冲突证据审查意见修订。"})
    revision = {
        "title": "洞察证据修订",
        "detail": "已根据 Evidence Critic 意见收敛或删除证据不足的洞察。",
        "stage": STAGE,
    }
    emit(writer, "artifact", STAGE, "洞察修订结果已生成。", {"insights": findings, "insightVersion": "after-revision"})
    return {"findings": findings, "iteration": state.get("iteration", 0) + 1, "revisions": state["revisions"] + [revision]}
