from ..llm import invoke_json
from ..errors import AgentRunError
from ..schemas import ClassificationResponse
from .common import dump_json, emit, reviews_for_prompt


STAGE = "评论分类"


async def classification_agent(state, llm, writer=None):
    emit(writer, "stage_started", STAGE, "开始按评论生成情感、主题和严重程度。")
    system = """
你是应用商店评论分析专家。只输出 JSON。
schema: {"classifications":[{"reviewId":"string","sentiment":"正向|混合|负向","theme":"string","severity":"高|中|低","rationale":"string"}]}
必须为输入中的每条 review 生成一条分类，reviewId 必须等于输入 review.id。
"""
    user = f"分析目标：{state['goal']}\n评论：{dump_json(reviews_for_prompt(state['reviews'], 500))}"
    parsed = await invoke_json(llm, stage=STAGE, system=system, user=user, response_model=ClassificationResponse, writer=writer)
    classifications = [item.model_dump() for item in parsed.classifications]
    expected_ids = {review["id"] for review in state["reviews"]}
    actual_ids = {item["reviewId"] for item in classifications}
    if actual_ids != expected_ids or len(classifications) != len(expected_ids):
        raise AgentRunError(
            "CLASSIFICATION_COVERAGE_FAILED",
            "评论分类结果未完整覆盖输入评论，或引用了不存在的评论 ID。",
            stage=STAGE,
            retryable=True,
        )
    emit(writer, "artifact", STAGE, "评论分类结果已生成。", {"classifications": classifications})
    emit(writer, "stage_completed", STAGE, f"完成 {len(classifications)} 条评论分类。")
    return {"classifications": classifications}
