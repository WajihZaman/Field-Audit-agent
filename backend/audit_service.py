"""
audit_service.py
=================
Orchestrates one full audit run:

  checklist + notes
        |
        v
  [1] Clarification Agent  --(insufficient)--> return questions to consultant
        |  (sufficient, or consultant chose to proceed anyway)
        v
  [2] Findings Agent  (+ RAG-retrieved brand standards per category)
        v
  [3] Review Correlation Agent  (+ Google Places reviews, live or mock)
        v
  [4] Corrective Action Agent
        v
  persisted AuditReport, with every prompt/response logged for explainability

This module is intentionally the only place that knows the *order* of the
pipeline -- agents.py, rag.py, google_places.py, and db.py each stay
narrowly scoped so they're easy to test/replace independently.
"""

from __future__ import annotations

import uuid
from typing import cast

from backend import agents, db, google_places, rag
from backend.config import settings
from backend.models import (
    AuditInputRequest,
    AuditReportOut,
    ClarificationCheck,
    CorrectiveActionPlan,  # <-- ADD THIS
    FindingsReport,  # <-- ADD THIS
    LocationOut,
    ReviewInsights,
    RunAuditRequest,
)


def _build_checklist_block(items: list[dict]) -> str:
    lines = []
    for i in items:
        note = f" | consultant note: {i['notes']}" if i.get("notes") else ""
        lines.append(f"- [{i['category']}] {i['question']} -> {i['response'].upper()}{note}")
    return "\n".join(lines) if lines else "(no checklist items provided)"


def _build_clarification_block(qas: list[dict]) -> str:
    if not qas:
        return "(no clarifying questions were needed / answered)"
    lines = [f"- Q: {qa['question']}\n  A: {qa.get('answer') or '(not answered)'}" for qa in qas]
    return "\n".join(lines)


async def run_clarification(req: AuditInputRequest) -> tuple[str, ClarificationCheck]:
    """
    Creates a new draft audit session, persists the raw input, and runs the
    Clarification Agent against it. Returns (audit_id, ClarificationCheck)
    so the caller (API layer) can decide whether to surface follow-up
    questions to the consultant before findings are generated.
    """
    audit_id = str(uuid.uuid4())
    db.create_audit_session(
        audit_id=audit_id,
        location_id=req.location_id,
        consultant_name=req.consultant_name,
        free_text_notes=req.free_text_notes,
        photo_description=req.photo_description,
    )
    checklist_items = [i.model_dump() for i in req.checklist]
    db.save_checklist_responses(audit_id, checklist_items)

    prompt = (
        "CHECKLIST RESPONSES:\n"
        f"{_build_checklist_block(checklist_items)}\n\n"
        "CONSULTANT FREE-TEXT NOTES:\n"
        f"{req.free_text_notes or '(none provided)'}\n\n"
        "PHOTO DESCRIPTION (written stand-in for an attached photo):\n"
        f"{req.photo_description or '(none provided)'}\n\n"
        "Decide whether this is sufficient to write defensible findings."
    )
    # result = await agents.get_clarification_agent().run(prompt)
    # check: ClarificationCheck = result.output
    
    # result = await agents.get_clarification_agent().run(prompt)
    # check = result.output
    
    result = await agents.run_with_retry(agents.get_clarification_agent(), prompt)
    check = cast(ClarificationCheck, result.output)

    db.log_audit_trail(audit_id, "clarification_check", settings.model_fast, prompt, check.model_dump_json())

    if not check.is_sufficient and check.clarifying_questions:
        db.save_clarification_questions(audit_id, check.clarifying_questions)
        db.update_audit_status(audit_id, "clarifying")
    else:
        db.update_audit_status(audit_id, "draft")

    return audit_id, check


async def run_full_audit(req: RunAuditRequest) -> AuditReportOut:
    """
    Runs (or resumes) a full audit: findings -> review correlation ->
    corrective actions -> persisted report.
    """
    location = db.get_location(req.location_id)
    if location is None:
        raise ValueError(f"Unknown location_id={req.location_id}")

    # Reuse an existing draft session if we have one (e.g. from a prior
    # clarification round); otherwise start fresh.
    if req.audit_id and db.get_audit_session(req.audit_id):
        audit_id = req.audit_id
        checklist_items = db.get_checklist_responses(audit_id)
        if not checklist_items:
            checklist_items = [i.model_dump() for i in req.checklist]
            db.save_checklist_responses(audit_id, checklist_items)
    else:
        audit_id = str(uuid.uuid4())
        db.create_audit_session(
            audit_id=audit_id,
            location_id=req.location_id,
            consultant_name=req.consultant_name,
            free_text_notes=req.free_text_notes,
            photo_description=req.photo_description,
        )
        checklist_items = [i.model_dump() for i in req.checklist]
        db.save_checklist_responses(audit_id, checklist_items)

    for qa in req.clarification_answers:
        db.save_clarification_answer(audit_id, qa.question, qa.answer)
    clarifications = db.get_clarifications(audit_id)

    # ---- [2] Findings Agent ------------------------------------------------
    categories = sorted({i["category"] for i in checklist_items}) or ["General"]
    standards_blocks = []
    for cat in categories:
        snippets = rag.retrieve_standards(location["brand"], cat, k=2)
        if snippets:
            standards_blocks.append(f"[{cat}]\n" + "\n".join(f"  - {s}" for s in snippets))
    standards_text = "\n".join(standards_blocks) if standards_blocks else "(no brand standards retrieved)"

    findings_prompt = (
        f"LOCATION: {location['name']} ({location['brand']}), {location['address']}\n\n"
        "CHECKLIST RESPONSES:\n"
        f"{_build_checklist_block(checklist_items)}\n\n"
        "CONSULTANT FREE-TEXT NOTES:\n"
        f"{req.free_text_notes or '(none provided)'}\n\n"
        "PHOTO DESCRIPTION:\n"
        f"{req.photo_description or '(none provided)'}\n\n"
        "CLARIFYING Q&A WITH CONSULTANT:\n"
        f"{_build_clarification_block(clarifications)}\n\n"
        "RELEVANT BRAND STANDARDS (retrieved):\n"
        f"{standards_text}\n\n"
        "Write structured findings now, following your system rules."
    )
    # findings_result = await agents.get_findings_agent().run(findings_prompt)
    # findings_report = findings_result.output
    
    # findings_result = await agents.get_findings_agent().run(findings_prompt)
    # findings_report: FindingsReport = findings_result.output
    
    findings_result = await agents.run_with_retry(agents.get_findings_agent(), findings_prompt)
    findings_report = cast(FindingsReport, findings_result.output)
    
    db.log_audit_trail(audit_id, "findings_agent", settings.model_strong, findings_prompt,
                        findings_report.model_dump_json())

    # If the consultant explicitly chose to proceed despite unresolved gaps,
    # force every finding to human review rather than silently trusting them.
    unresolved = any(c["answer"] in (None, "") for c in clarifications)
    if req.proceed_despite_gaps and unresolved:
        for f in findings_report.findings:
            f.requires_human_review = True

    findings_dicts = [f.model_dump() for f in findings_report.findings]
    db_finding_ids = db.save_findings(audit_id, findings_dicts)

    # ---- [3] Review Correlation Agent --------------------------------------
    reviews, is_mock = await google_places.get_recent_reviews(
        location_id=location["id"],
        place_name=location["name"],
        address=location["address"],
        place_id=location.get("place_id"),
    )
    negative_reviews = [r for r in reviews if (r.get("rating") or 5) <= 3]
    reviews_prompt = (
        f"AUDIT CATEGORIES THIS VISIT: {', '.join(categories)}\n\n"
        f"RECENT REVIEWS CONSIDERED (last ~90 days, {'MOCK/DEMO data' if is_mock else 'live Google data'}, "
        f"{len(negative_reviews)} of {len(reviews)} are 3 stars or below):\n"
        + "\n".join(
            f"- ({r.get('rating', '?')}\u2605) {r.get('review_text', '')}" for r in negative_reviews
        )
        + ("\n(no reviews at or below 3 stars in this window)" if not negative_reviews else "")
        + "\n\nSummarize recurring themes and note any plausible (never certain) links to the "
          "audit categories above."
    )
    # review_result = await agents.get_review_agent().run(reviews_prompt)
    # review_insights = review_result.output
    
    # review_result = await agents.get_review_agent().run(reviews_prompt)
    # review_insights: ReviewInsights = review_result.output  # Explicit type annotation
    
    review_result = await agents.run_with_retry(agents.get_review_agent(), reviews_prompt)
    review_insights = cast(ReviewInsights, review_result.output)
    
    db.log_audit_trail(audit_id, "review_agent", settings.model_fast, reviews_prompt,
                        review_insights.model_dump_json())
    db.save_review_insights(audit_id, [t.model_dump() for t in review_insights.themes])

    # ---- [4] Corrective Action Agent ---------------------------------------
    if findings_report.findings:
        findings_for_prompt = "\n".join(
            f"[{idx}] ({f.severity}, confidence={f.confidence:.2f}, "
            f"human_review={'YES' if f.requires_human_review else 'no'}) "
            f"{f.category}: {f.finding_summary} | evidence: {f.supporting_evidence}"
            for idx, f in enumerate(findings_report.findings)
        )
        corrective_prompt = (
            f"LOCATION: {location['name']} ({location['brand']})\n\n"
            f"CONFIRMED FINDINGS:\n{findings_for_prompt}\n\n"
            "Write the corrective action plan now, following your system rules. "
            "Use the bracketed index as finding_ref."
        )
        # corrective_result = await agents.get_corrective_action_agent().run(corrective_prompt)
        # action_plan = corrective_result.output
        
        # corrective_result = await agents.get_corrective_action_agent().run(corrective_prompt)
        # action_plan: CorrectiveActionPlan = corrective_result.output  # Explicit type annotation
        
        corrective_result = await agents.run_with_retry(agents.get_corrective_action_agent(), corrective_prompt)
        action_plan = cast(CorrectiveActionPlan, corrective_result.output)
        
        db.log_audit_trail(audit_id, "corrective_action_agent", settings.model_strong,
                            corrective_prompt, action_plan.model_dump_json())
    else:
        # from backend.models import CorrectiveActionPlan
        action_plan = CorrectiveActionPlan(
            actions=[],
            franchisee_message=(
                f"Great news -- no compliance issues were identified during this visit to "
                f"{location['name']}. Thank you for maintaining brand standards."
            ),
        )

    action_dicts = []
    for a in action_plan.actions:
        finding_db_id = None
        if a.finding_ref is not None and 0 <= a.finding_ref < len(db_finding_ids):
            finding_db_id = db_finding_ids[a.finding_ref]
        d = a.model_dump()
        d["finding_id"] = finding_db_id
        action_dicts.append(d)
    db.save_corrective_actions(audit_id, action_dicts)

    db.update_audit_status(
        audit_id, "completed",
        overall_summary=findings_report.overall_summary,
        franchisee_message=action_plan.franchisee_message,
    )

    return AuditReportOut(
        audit_id=audit_id,
        status="completed",
        location=LocationOut(**{k: location[k] for k in ("id", "name", "brand", "address", "place_id")}),
        consultant_name=req.consultant_name,
        findings=findings_report.findings,
        overall_summary=findings_report.overall_summary,
        review_insights=review_insights,
        reviews_are_mocked=is_mock,
        corrective_actions=action_plan.actions,
        franchisee_message=action_plan.franchisee_message,
    )


async def get_report(audit_id: str) -> AuditReportOut | None:
    """Reconstruct a completed AuditReportOut from persisted DB rows."""
    session = db.get_audit_session(audit_id)
    if not session:
        return None
    
    
    location = db.get_location(session["location_id"])
    if location is None:           # <-- ADD THIS GUARD CLAUSE
        return None                # <-- ADD THIS GUARD CLAUSE

    
    findings_rows = db.get_findings(audit_id)
    actions_rows = db.get_corrective_actions(audit_id)
    insight_rows = db.get_review_insights(audit_id)

    from backend.models import CorrectiveAction, Finding, ReviewInsights, ReviewTheme

    findings = [
        Finding(
            category=r["category"], finding_summary=r["finding_summary"], severity=r["severity"],
            confidence=r["confidence"], requires_human_review=bool(r["requires_human_review"]),
            supporting_evidence=r["supporting_evidence"], standard_reference=r["standard_reference"],
        )
        for r in findings_rows
    ]
    actions = [
        CorrectiveAction(
            finding_ref=None, action_text=r["action_text"],
            suggested_deadline_days=r["suggested_deadline_days"], owner=r["owner"],
        )
        for r in actions_rows
    ]
    review_insights = None
    if insight_rows:
        review_insights = ReviewInsights(
            themes=[
                ReviewTheme(
                    theme=r["theme"], mention_count=r["mention_count"], example_snippet=r["example_snippet"],
                    linked_categories=r["linked_categories"], linkage_confidence=r["linkage_confidence"],
                    linkage_note=r["linkage_note"],
                )
                for r in insight_rows
            ],
            overall_sentiment_summary="(reconstructed from saved themes)",
            caveat="Review sample is small and recency-biased; see themes for detail.",
        )

    return AuditReportOut(
        audit_id=audit_id,
        status=session["status"],
        location=LocationOut(**{k: location[k] for k in ("id", "name", "brand", "address", "place_id")}),
        consultant_name=session["consultant_name"],
        findings=findings,
        overall_summary=session["overall_summary"] or "",
        review_insights=review_insights,
        reviews_are_mocked=settings.reviews_are_mocked,
        corrective_actions=actions,
        franchisee_message=session["franchisee_message"] or "",
    )
