"""
models.py
=========
All Pydantic models used by the app, split into two conceptual groups:

1. "Agent output" models — these are passed as `output_type` to Pydantic AI
   agents. The LLM is forced (via tool-call/schema validation) to return
   data matching these shapes. This is our main defense against a "wall of
   text" response that's hard to render, audit, or make defensible to a
   franchisee.

2. "API" models — request/response shapes for the FastAPI endpoints that
   the Streamlit frontend (or any other client) talks to.

Keeping these together in one file makes the contract between agents <->
API <-> frontend easy to review in one place for a POC of this size.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
ChecklistResult = Literal["pass", "fail", "na"]
LinkageConfidence = Literal["low", "medium", "high"]


# ---------------------------------------------------------------------------
# Agent output models
# ---------------------------------------------------------------------------

class ClarificationCheck(BaseModel):
    """Output of the Clarification Agent: decides whether the raw audit
    input is specific enough to support findings, or whether the model
    would be guessing."""

    is_sufficient: bool = Field(
        description="True only if every 'fail' or ambiguous checklist item has enough "
                    "detail (who/what/where/how bad) to write a defensible finding."
    )
    missing_info: list[str] = Field(
        default_factory=list,
        description="Short bullet list of what specific detail is missing, per item.",
    )
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Concrete, answerable questions to ask the consultant. Empty if is_sufficient=True.",
    )
    reasoning: str = Field(description="One or two sentences on why this input is/isn't sufficient.")


class Finding(BaseModel):
    """A single, evidence-grounded audit finding."""

    category: str = Field(description="Audit category this finding belongs to.")
    finding_summary: str = Field(description="Neutral, factual statement of what was observed.")
    severity: Severity = Field(description="Risk/severity classification.")
    confidence: float = Field(ge=0.0, le=1.0, description="Model's self-rated confidence, 0-1.")
    requires_human_review: bool = Field(
        description="True if a human auditor should confirm this before it goes to the franchisee "
                    "(e.g. thin evidence, high severity, or judgment call on ambiguous standards)."
    )
    supporting_evidence: str = Field(
        description="Verbatim or near-verbatim excerpt from the consultant's own input that supports "
                    "this finding. Must NOT introduce facts not present in the input."
    )
    standard_reference: str | None = Field(
        default=None, description="The brand standard this finding relates to, if one was retrieved."
    )


class FindingsReport(BaseModel):
    """Output of the Findings Agent."""

    findings: list[Finding]
    overall_summary: str = Field(description="2-3 sentence neutral summary of the visit for internal use.")


class ReviewTheme(BaseModel):
    """A recurring theme detected across recent negative/low-rating reviews."""

    theme: str = Field(description="Short label for the recurring theme, e.g. 'Slow pace of play'.")
    mention_count: int = Field(description="How many of the supplied reviews raised this theme.")
    example_snippet: str | None = Field(
        default=None, description="A short paraphrased (not verbatim-quoted) example."
    )
    linked_categories: list[str] = Field(
        default_factory=list, description="Audit categories this theme plausibly relates to, if any."
    )
    linkage_confidence: LinkageConfidence = Field(
        description="How confident the link between this review theme and an audit category is."
    )
    linkage_note: str = Field(
        description="One sentence stating the link as a *correlation*, never asserting the review "
                    "caused or proves the audit finding."
    )


class ReviewInsights(BaseModel):
    """Output of the Review Correlation Agent."""

    themes: list[ReviewTheme]
    overall_sentiment_summary: str
    caveat: str = Field(
        description="Mandatory caveat about sample size / recency limits of the review data used."
    )


class CorrectiveAction(BaseModel):
    """A single, franchisee-facing corrective action."""

    finding_ref: int | None = Field(default=None, description="Index into the findings list, if tied to one.")
    action_text: str = Field(description="Clear, specific, constructive action for the franchisee to take.")
    suggested_deadline_days: int = Field(description="Suggested days to resolve, based on severity.")
    owner: str = Field(description="Who should own this, e.g. 'General Manager', 'Grounds crew lead'.")


class CorrectiveActionPlan(BaseModel):
    """Output of the Corrective Action Agent."""

    actions: list[CorrectiveAction]
    franchisee_message: str = Field(
        description="A short, respectful cover message to the franchisee framing the plan as "
                    "collaborative, not punitive."
    )


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------

class ChecklistItemIn(BaseModel):
    category: str
    question: str
    response: ChecklistResult
    notes: str = ""


class AuditInputRequest(BaseModel):
    location_id: int
    consultant_name: str
    checklist: list[ChecklistItemIn]
    free_text_notes: str = ""
    photo_description: str = ""


class ClarificationAnswer(BaseModel):
    question: str
    answer: str


class RunAuditRequest(AuditInputRequest):
    audit_id: str | None = Field(
        default=None, description="If continuing a session that already went through clarification."
    )
    clarification_answers: list[ClarificationAnswer] = Field(default_factory=list)
    proceed_despite_gaps: bool = Field(
        default=False,
        description="Consultant explicitly acknowledges thin input and wants to proceed anyway; "
                    "any remaining findings will be forced to requires_human_review=True.",
    )


class LocationOut(BaseModel):
    id: int
    name: str
    brand: str
    address: str
    place_id: str | None = None


class AuditReportOut(BaseModel):
    audit_id: str
    status: str
    location: LocationOut
    consultant_name: str
    findings: list[Finding]
    overall_summary: str
    review_insights: ReviewInsights | None = None
    reviews_are_mocked: bool
    corrective_actions: list[CorrectiveAction]
    franchisee_message: str
