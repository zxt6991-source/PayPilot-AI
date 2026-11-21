from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import ANCHOR

Country = Literal["DE", "GB", "SG"]
Method = Literal["Klarna", "Card", "PayPal"]
Channel = Literal["Android", "Web", "iOS"]
Period = Literal["24h", "7d", "30d"]
Dimension = Literal["channel", "app_version", "payment_method", "country_code"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Filters(Strict):
    country_code: Country | None = None
    payment_method: Method | None = None
    channel: Channel | None = None
    period: Period = "24h"
    app_version: Literal["2.4", "2.5", "web"] | None = None
    as_of: datetime = ANCHOR

    @field_validator("as_of")
    @classmethod
    def valid_snapshot(cls, value):
        if value.tzinfo is None or value > ANCHOR:
            raise ValueError("需要带时区且不晚于数据快照的时间")
        return value


class Scope(Filters):
    country_code: Country = "DE"
    payment_method: Method = "Klarna"


class CreateTask(Strict):
    question: str = Field(min_length=1, max_length=1500)
    filters: Filters = Field(default_factory=Filters)
    dataset_version: Literal["demo-v1"] = "demo-v1"


class Message(Strict):
    run_id: str
    question: str = Field(min_length=1, max_length=1500)
    filters: Filters = Field(default_factory=Filters)


class Feedback(Strict):
    run_id: str
    report_id: str
    rating: Literal["helpful", "unhelpful"]
    issue_tags: list[str] = Field(default_factory=list, max_length=8)
    note: str = Field(default="", max_length=1000)


class CitationClaim(Strict):
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class Hypothesis(CitationClaim):
    confidence_label: Literal["NEEDS_VERIFICATION"]


class ReportMetrics(Strict):
    current_psr: float | None = Field(ge=0, le=1)
    baseline_psr: float | None = Field(ge=0, le=1)
    delta_pp: float | None = Field(ge=-100, le=100)
    valid_attempts: int = Field(ge=0)
    successful_attempts: int = Field(ge=0)
    failed_attempts: int = Field(ge=0)
    evidence_ids: list[str] = Field(min_length=1)


class DiagnosisReport(Strict):
    schema_version: Literal["report-v1"]
    report_id: str
    run_id: str
    dataset_version: Literal["demo-v1"]
    environment: Literal["DEMO"]
    status: Literal["HYPOTHESIS_ONLY"]
    scope: Filters
    metrics: ReportMetrics | None
    findings: list[CitationClaim]
    hypotheses: list[Hypothesis]
    citations: list[str]
    actions: list[str]
    uncertainties: list[str]
