import json


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


def emit(writer, event_type, stage, message, data=None):
    if writer:
        writer({"type": event_type, "stage": stage, "message": message, "data": data or {}})

