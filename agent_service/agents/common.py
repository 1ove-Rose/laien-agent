import json


def resolve_writer(writer=None):
    if writer is not None:
        return writer
    try:
        from langgraph.config import get_stream_writer
        return get_stream_writer()
    except (ImportError, RuntimeError):
        return None


def dump_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def reviews_for_prompt(reviews, limit=120):
    return [
        {
            "id": review.get("id"),
            "rating": review.get("rating"),
            "version": review.get("version"),
            "title": review.get("title", ""),
            "text": review.get("text", "")[:900],
            "createdAt": review.get("createdAt"),
        }
        for review in reviews[:limit]
    ]


def data_limitations(state):
    reviews = state.get("reviews", [])
    collection = state.get("collection", {}) or {}
    report = state.get("cleanReport", {}) or {}
    limitations = []
    count = len(reviews)
    provider = collection.get("provider")

    if provider == "file-import":
        imported = collection.get("importedCount", collection.get("requestedCount"))
        if imported is not None:
            limitations.append(
                f"本次分析仅基于上传文件中的 {imported} 条原始记录和清洗后的 {count} 条评论；"
                "文件覆盖范围由上传者决定，不能代表全量用户。"
            )
        else:
            limitations.append(f"本次分析仅基于导入文件中清洗后的 {count} 条评论，数据覆盖范围由上传文件决定，不能代表全量用户。")
    elif provider == "apple-rss":
        requested = collection.get("requestedCount")
        collected = collection.get("collectedCount", count)
        if requested and collected < requested:
            limitations.append(
                f"Apple App Store RSS 本次请求 {requested} 条评论，实际获取 {collected} 条，"
                f"清洗后用于分析 {count} 条；结论仅覆盖该公开样本。"
            )
        else:
            limitations.append(
                f"本次仅使用 Apple App Store RSS 获取并清洗后的 {count} 条公开评论；"
                "RSS 结果不等同于全量用户反馈。"
            )
    else:
        limitations.append(
            f"本次仅使用当前请求提供并清洗后的 {count} 条评论；未提供完整的数据来源或覆盖范围信息，不能代表全量用户。"
        )

    if count < 30:
        limitations.append(f"清洗后样本量为 {count} 条，样本量较少；单条或冲突证据只能作为待验证假设。")
    elif count < 100:
        limitations.append(f"清洗后样本量为 {count} 条，仍属于有限样本；不应据此推断用户总体比例、市场覆盖或因果关系。")
    if report.get("removedCount", 0):
        limitations.append(
            f"清洗阶段移除了 {report['removedCount']} 条记录（空正文、非法评分或重复），"
            "这些记录未进入后续分析。"
        )
    for warning in collection.get("warnings", []) or []:
        limitations.append(str(warning))
    if collection.get("staleCache"):
        limitations.append("本次使用了过期缓存数据，结果可能未反映最新评论。")
    return limitations


def data_limitations_instruction(state):
    limitations = data_limitations(state)
    return (
        "数据限制：" + "；".join(limitations)
        + "。不得编造未提供的评论、用户规模、比例、地域覆盖、时间趋势或因果结论；"
        "结论必须限定在现有证据范围内，并在证据不足时明确写为假设。"
    )


def emit(writer, event_type, stage, message, data=None):
    writer = resolve_writer(writer)
    if writer:
        writer({"type": event_type, "stage": stage, "message": message, "data": data or {}})
