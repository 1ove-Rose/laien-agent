from typing import Any, TypedDict


class AnalysisState(TypedDict):
    appId: str
    goal: str
    reviews: list[dict[str, Any]]
    collection: dict[str, Any]
    cleanReport: dict[str, Any]
    classifications: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    requirements: list[dict[str, Any]]
    tests: list[dict[str, Any]]
    validations: list[dict[str, Any]]
    revisions: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    iteration: int
    criticPassed: bool
    criticNotes: str


def initial_state(request) -> AnalysisState:
    return {
        "appId": request.appId,
        "goal": request.goal,
        "reviews": [review.model_dump() for review in request.reviews],
        "collection": request.collection,
        "cleanReport": request.cleanReport,
        "classifications": [],
        "findings": [],
        "requirements": [],
        "tests": [],
        "validations": [],
        "revisions": [],
        "errors": [],
        "iteration": 0,
        "criticPassed": False,
        "criticNotes": "",
    }

