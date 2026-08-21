from ..llm import invoke_json
from ..errors import AgentRunError
from ..schemas import ClassificationResponse
from .common import dump_json, emit, resolve_writer, reviews_for_prompt
from ..analysis_mode import focus_reviews, mode_instruction


STAGE = "评论分类"


async def classification_agent(state, llm, writer=None):
    writer = resolve_writer(writer)
    emit(writer, "stage_started", STAGE, "开始按评论生成情感、主题和严重程度。")
    mode = state.get("analysisMode", "negative")
    system = """
你是应用商店评论分析专家。只输出 JSON。
schema: {"classifications":[{"reviewId":"string","sentiment":"正向|混合|负向","theme":"string","severity":"高|中|低","rationale":"string"}]}
必须为输入中的每条 review 生成一条分类，reviewId 必须等于输入 review.id。
分类结果必须按照输入评论的顺序返回；分析模式会决定输入顺序。
所有自然语言字段必须使用简体中文：sentiment 只能使用正向、混合或负向；theme、severity、rationale 也必须为中文。即使原评论为英文或其他语言，也必须用中文归纳。
"""
    ordered_reviews = focus_reviews(state["reviews"], mode)
    ordered_reviews += [review for review in state["reviews"] if review not in ordered_reviews]
    user = (
        f"分析目标：{state['goal']}\n{mode_instruction(mode)}\n"
        f"评论：{dump_json(reviews_for_prompt(ordered_reviews, 500))}"
    )
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
    review_order = {review["id"]: index for index, review in enumerate(ordered_reviews)}
    classifications.sort(key=lambda item: review_order.get(item["reviewId"], len(review_order)))
    emit(writer, "artifact", STAGE, "评论分类结果已生成。", {"classifications": classifications})
    emit(writer, "stage_completed", STAGE, f"完成 {len(classifications)} 条评论分类。")
    return {"classifications": classifications}
