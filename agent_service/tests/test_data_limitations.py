from agent_service.agents.common import data_limitations


def test_file_import_limitations_disclose_scope_and_cleaning_loss():
    limitations = data_limitations({
        "reviews": [{"id": "r1"}] * 25,
        "collection": {"provider": "file-import", "importedCount": 30},
        "cleanReport": {"removedCount": 5},
    })

    text = " ".join(limitations)
    assert "上传文件" in text
    assert "30" in text
    assert "25" in text
    assert "5" in text
    assert "待验证假设" in text


def test_apple_limitations_disclose_short_collection_and_stale_cache():
    limitations = data_limitations({
        "reviews": [{"id": "r1"}] * 50,
        "collection": {
            "provider": "apple-rss",
            "requestedCount": 100,
            "collectedCount": 60,
            "staleCache": True,
            "warnings": ["第 2 页请求失败，已返回前 60 条评论。"],
        },
        "cleanReport": {"removedCount": 10},
    })

    text = " ".join(limitations)
    assert "请求 100 条" in text
    assert "实际获取 60 条" in text
    assert "有限样本" in text
    assert "过期缓存" in text
    assert "第 2 页请求失败" in text
