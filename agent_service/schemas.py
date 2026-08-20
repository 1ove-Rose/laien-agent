from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from .errors import AgentRunError


class Review(BaseModel):
    id: str
    appId: str
    country: str = "us"
    rating: int = Field(ge=1, le=5)
    version: str = "unknown"
    title: str = ""
    text: str
    author: str = ""
    authorUrl: str = ""
    createdAt: str | None = None
    sourceUrl: str = ""
    sourceType: str = "apple-rss"
    fetchedAt: str | None = None
    fingerprint: str | None = None
    cleanStatus: str | None = None
    normalizationVersion: str | None = None


class Classification(BaseModel):
    reviewId: str
    sentiment: str
    theme: str
    severity: str
    rationale: str


class Finding(BaseModel):
    id: str
    title: str
    summary: str
    evidenceIds: list[str]
    supportCount: int
    confidence: str
    conflict: str = ""
    version: str = "v0.1"

    @field_validator("supportCount")
    @classmethod
    def support_count_cannot_be_negative(cls, value):
        if value < 0:
            raise ValueError("supportCount must be non-negative")
        return value


class Requirement(BaseModel):
    id: str
    title: str
    priority: str
    sourceFindingId: str
    acceptance: str
    version: str = "v0.1"


class TestCase(BaseModel):
    id: str
    title: str
    requirementId: str
    sourceFindingId: str
    steps: str
    expected: str
    version: str = "v0.1"


class ValidationResult(BaseModel):
    type: Literal["pass", "error", "revised"]
    title: str
    detail: str
    stage: str


class RevisionRecord(BaseModel):
    title: str
    detail: str
    stage: str


class ClassificationResponse(BaseModel):
    classifications: list[Classification]


class InsightResponse(BaseModel):
    findings: list[Finding]


class CriticResponse(BaseModel):
    passed: bool
    validations: list[ValidationResult]
    revisionInstructions: str | None = None


class RequirementsResponse(BaseModel):
    requirements: list[Requirement]


class TestCasesResponse(BaseModel):
    tests: list[TestCase]


class AnalysisRunRequest(BaseModel):
    appId: str
    goal: str = Field(min_length=1, max_length=2000)
    reviews: list[Review]
    collection: dict[str, Any] = Field(default_factory=dict)
    cleanReport: dict[str, Any] = Field(default_factory=dict)

    @field_validator("appId")
    @classmethod
    def app_id_must_be_numeric(cls, value):
        if not str(value).isdigit():
            raise ValueError("appId must be numeric")
        return str(value)

    @field_validator("reviews")
    @classmethod
    def reviews_must_be_present(cls, value):
        if not value:
            raise ValueError("reviews cannot be empty")
        if len(value) > 500:
            raise ValueError("reviews cannot exceed 500 items")
        return value

    @classmethod
    def from_payload(cls, payload):
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise AgentRunError(
                "INVALID_AGENT_INPUT",
                "多 Agent 分析输入无效。",
                stage="输入校验",
                retryable=False,
                cause=exc,
            ) from exc


class RunEvent(BaseModel):
    type: Literal[
        "stage_started",
        "stage_completed",
        "validation",
        "revision",
        "artifact",
        "retry",
        "error",
        "completed",
    ]
    stage: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)

