from ..llm import invoke_json
from ..schemas import InsightResponse
from .common import dump_json, emit, reviews_for_prompt


STAGE = "洞察发现"


async def insight_agent(state, llm, writer=None):
    emit(writer, "stage_started", STAGE, "开始从评论分类中聚合证据洞察。")
    system = """
你是产品洞察分析师。只输出 JSON。
schema: {"findings":[{"id":"F-1","title":"string","summary":"string","evidenceIds":["review-id"],"supportCount":1,"confidence":"高|中|低","conflict":"string","version":"v0.1"}]}
规则：
1. 每条 finding 必须引用真实 review.id。
2. supportCount 必须等于 evidenceIds 数量。
3. 优先覆盖低评分、订阅/付费、易用性、稳定性、数据保留等问题。
4. 不要生成没有证据的 finding。
"""
    user = (
        f"分析目标：{state['goal']}\n"
        f"评论：{dump_json(reviews_for_prompt(state['reviews'], 500))}\n"
        f"分类：{dump_json(state['classifications'])}"
    )
    parsed = await invoke_json(llm, stage=STAGE, system=system, user=user, response_model=InsightResponse, writer=writer)
    findings = [item.model_dump() for item in parsed.findings]
    emit(writer, "artifact", STAGE, "洞察发现已生成。", {"insights": findings})
    emit(writer, "stage_completed", STAGE, f"完成 {len(findings)} 条洞察。")
    return {"findings": findings}


async def insight_revision_agent(state, llm, writer=None):
    emit(writer, "revision", STAGE, "证据审查未通过，开始修订洞察。", {"notes": state.get("criticNotes", "")})
    system = """
你是产品洞察修订专家。只输出 JSON。
schema: {"findings":[{"id":"F-1","title":"string","summary":"string","evidenceIds":["review-id"],"supportCount":1,"confidence":"高|中|低","conflict":"string","version":"v0.2 已修订"}]}
只基于真实评论证据修订。删除没有证据、证据不存在、支持数错误或过度泛化的 finding。
"""
    user = (
        f"分析目标：{state['goal']}\n"
        f"审查意见：{state.get('criticNotes', '')}\n"
        f"评论：{dump_json(reviews_for_prompt(state['reviews'], 500))}\n"
        f"原洞察：{dump_json(state['findings'])}"
    )
    parsed = await invoke_json(llm, stage=STAGE, system=system, user=user, response_model=InsightResponse, writer=writer)
    findings = [item.model_dump() for item in parsed.findings]
    revision = {
        "title": "洞察证据修订",
        "detail": "已根据 Evidence Critic 意见收敛或删除证据不足的洞察。",
        "stage": STAGE,
    }
    emit(writer, "artifact", STAGE, "洞察修订结果已生成。", {"insights": findings})
    return {"findings": findings, "iteration": state.get("iteration", 0) + 1, "revisions": state["revisions"] + [revision]}
