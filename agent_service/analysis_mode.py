"""Turn the natural-language goal into a deterministic workflow mode."""

import re


POSITIVE_TERMS = (
    "高分", "好评", "正向", "优点", "优势", "满意", "认可", "成功经验",
    "positive", "high rating", "strength", "strengths", "best experience",
)
NEGATIVE_TERMS = (
    "低分", "差评", "负向", "问题", "缺陷", "痛点", "抱怨", "故障",
    "negative", "low rating", "issue", "issues", "complaint", "pain point",
)


def _contains_term(text: str, terms: tuple[str, ...]) -> bool:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    return any(term.casefold() in normalized for term in terms)


def resolve_analysis_mode(goal: str) -> str:
    """Return positive, negative, or balanced without relying on an LLM."""
    positive = _contains_term(goal, POSITIVE_TERMS)
    negative = _contains_term(goal, NEGATIVE_TERMS)
    if positive and not negative:
        return "positive"
    if negative and not positive:
        return "negative"
    return "balanced"


def mode_instruction(mode: str) -> str:
    if mode == "positive":
        return "当前模式：高分/正向分析。优先使用 4-5 分评论，分析用户认可的能力、产品优点、满意体验和可保留或扩展的成功经验；不要把低分问题作为主要洞察。"
    if mode == "negative":
        return "当前模式：低分/问题分析。优先使用 1-3 分评论，分析用户痛点、缺陷、故障和流失风险。"
    return "当前模式：综合分析。根据分析目标同时关注正向价值和负向问题，不预设单一评分方向。"


def focus_reviews(reviews: list[dict], mode: str) -> list[dict]:
    """Select evidence candidates and order them deterministically for prompts."""
    if mode == "positive":
        selected = [review for review in reviews if int(review.get("rating", 0)) >= 4]
        return sorted(selected, key=lambda review: (-int(review.get("rating", 0)), review.get("createdAt") or "", review.get("id") or ""))
    if mode == "negative":
        selected = [review for review in reviews if int(review.get("rating", 0)) <= 3]
        return sorted(selected, key=lambda review: (int(review.get("rating", 0)), review.get("createdAt") or "", review.get("id") or ""))
    return sorted(reviews, key=lambda review: (-int(review.get("rating", 0)), review.get("createdAt") or "", review.get("id") or ""))
