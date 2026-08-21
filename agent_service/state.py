from typing import Any, TypedDict

from .agents.common import data_limitations


class AnalysisState(TypedDict):
    appId: str
    goal: str
    analysisMode: str
    reviews: list[dict[str, Any]]
    collection: dict[str, Any]
    cleanReport: dict[str, Any]
    classifications: list[dict[str, Any]]
    findingsBeforeRevision: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    requirements: list[dict[str, Any]]
    tests: list[dict[str, Any]]
    validations: list[dict[str, Any]]
    revisions: list[dict[str, Any]]
    rejectedFindings: list[dict[str, Any]]
    dataLimitations: list[str]
    errors: list[dict[str, Any]]
    iteration: int
    criticPassed: bool
    criticNotes: str


def initial_state(request) -> AnalysisState:
    return {
        "appId": request.appId,
        "goal": request.goal,
        "analysisMode": request.analysisMode,
        "reviews": [review.model_dump() for review in request.reviews],
        "collection": request.collection,
        "cleanReport": request.cleanReport,
        "classifications": [],
        "findingsBeforeRevision": [],
        "findings": [],
        "requirements": [],
        "tests": [],
        "validations": [],
        "revisions": [],
        "rejectedFindings": [],
        # This is deterministic source metadata, not an LLM-generated conclusion.
        "dataLimitations": data_limitations({
            "reviews": [review.model_dump() for review in request.reviews],
            "collection": request.collection,
            "cleanReport": request.cleanReport,
        }),
        "errors": [],
        "iteration": 0,
        "criticPassed": False,
        "criticNotes": "",
    }
