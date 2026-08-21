from agent_service.analysis_mode import focus_reviews, mode_instruction, resolve_analysis_mode


def test_high_rating_goal_selects_positive_mode():
    assert resolve_analysis_mode("关注高分评论") == "positive"
    assert "产品优点" in mode_instruction("positive")


def test_low_rating_goal_selects_negative_mode():
    assert resolve_analysis_mode("关注低分评论和用户痛点") == "negative"


def test_mixed_goal_is_balanced():
    assert resolve_analysis_mode("关注高分优点和低分问题") == "balanced"


def test_positive_focus_is_sorted_high_to_low_and_excludes_low_ratings():
    reviews = [
        {"id": "r3", "rating": 3},
        {"id": "r1", "rating": 5},
        {"id": "r2", "rating": 4},
    ]
    assert [review["id"] for review in focus_reviews(reviews, "positive")] == ["r1", "r2"]
