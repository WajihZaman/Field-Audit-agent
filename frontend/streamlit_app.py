"""
streamlit_app.py
================
Field Audit Intelligence -- consultant-facing UI.

INTERACTION MODEL (deliberate design choice, see written summary for the
full rationale):

  A structured checklist form is the PRIMARY interface, because the primary
  user in the moment of use is a field consultant standing at a location
  who needs speed and completeness, not an open-ended chat. A free-form
  chatbot for the whole audit would be slower and less reliable for that
  user.

  The system drops into a short CONVERSATIONAL follow-up -- a handful of
  targeted questions -- only when the AI genuinely can't write a defensible
  finding from what was given (e.g. "floor looked a little dirty"). This
  keeps the speed of a form for the 80% of clean cases, while still
  preventing the model from guessing on the ambiguous 20%.

  After the report is generated, the UI splits into a CONSULTANT VIEW
  (confidence scores, human-review flags, raw evidence, full audit trail --
  built for someone who needs to defend the finding) and a FRANCHISEE VIEW
  (clean, respectful, action-oriented -- built for someone who needs to
  act on it), because those two audiences need different things from the
  same underlying data.
"""

from __future__ import annotations

import html
import os

import httpx
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_INTERNAL_URL", "http://127.0.0.1:8000")

CHECKLIST_TEMPLATE = [
    {
        "category": "Course Conditions",
        "questions": [
            "Greens are mowed/rolled with no visible scalping",
            "Bunkers have even, adequately raked sand with no standing water",
            "Cart paths are free of major cracks or potholes",
        ],
    },
    {
        "category": "Clubhouse & Facility Cleanliness",
        "questions": [
            "Restrooms are stocked and visibly clean",
            "Locker rooms are free of trash / standing water / odor",
            "Pro shop and common areas are clean and clutter-free",
        ],
    },
    {
        "category": "Safety & Risk",
        "questions": [
            "Lightning protocol signage is posted and staff can explain it",
            "Hazard areas are clearly marked",
            "Golf carts passed today's safety check",
        ],
    },
    {
        "category": "Guest Service & Staff Standards",
        "questions": [
            "Pace of play is being actively managed",
            "Staff are in uniform and greeted guests promptly",
        ],
    },
    {
        "category": "Brand & Signage Compliance",
        "questions": [
            "Exterior/interior signage uses the current brand template",
        ],
    },
    {
        "category": "Food & Beverage Operations",
        "questions": [
            "Food holding temps and date-labeling meet standard",
            "Menu pricing / offerings match the approved brand menu",
        ],
    },
]

SEVERITY_COLOR = {
    "critical": "#8B0000",
    "high": "#D9534F",
    "medium": "#E0A800",
    "low": "#5B8C5A",
}


def api(method: str, path: str, **kwargs):
    with httpx.Client(timeout=60) as client:
        resp = client.request(method, f"{BACKEND_URL}{path}", **kwargs)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except (ValueError, AttributeError):
            detail = resp.text
        raise RuntimeError(f"{resp.status_code}: {detail}")
    return resp.json()


def init_state():
    defaults = {
        "stage": "intake",       # intake -> clarifying -> report
        "audit_id": None,
        "clarification": None,
        "clar_answers": {},
        "report": None,
        "location_id": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def reset_audit():
    for k in ("stage", "audit_id", "clarification", "clar_answers", "report"):
        st.session_state.pop(k, None)
    init_state()


def badge(text: str, color: str) -> str:
    return (
        f'<span style="background:{color};color:white;padding:2px 8px;'
        f'border-radius:10px;font-size:0.8em;font-weight:600">{html.escape(text)}</span>'
    )


def render_intake(location_id: int, consultant_name: str):
    st.subheader("1. Field Audit Checklist")
    st.caption(
        "Structured checklist for speed. Mark anything that fails and add a specific note -- "
        "the more concrete the note, the less likely you'll be asked a follow-up question."
    )

    checklist_payload = []
    for section in CHECKLIST_TEMPLATE:
        with st.expander(section["category"], expanded=False):
            for q in section["questions"]:
                key = f"resp::{section['category']}::{q}"
                cols = st.columns([3, 1])
                with cols[0]:
                    st.write(q)
                with cols[1]:
                    response = st.radio(
                        "Result", ["pass", "fail", "na"], horizontal=True,
                        key=key, label_visibility="collapsed",
                    )
                note = ""
                if response == "fail":
                    note = st.text_input(
                        "What specifically did you observe? (where, how bad, vs. standard)",
                        key=f"note::{section['category']}::{q}",
                    )
                checklist_payload.append(
                    {"category": section["category"], "question": q, "response": response, "notes": note}
                )

    st.subheader("2. Free-Text Notes")
    free_text = st.text_area(
        "Anything else worth noting about the visit overall?",
        key="free_text_notes", height=100,
    )

    st.subheader("3. Photo Description")
    st.caption("Stand-in for an attached photo in this POC -- describe what a photo would show.")
    photo_desc = st.text_area("Describe the photo", key="photo_description", height=80)

    if st.button("Run Pre-Check", type="primary"):
        with st.spinner("Checking whether the input is specific enough to write findings on..."):
            try:
                result = api(
                    "POST", "/audits/clarify",
                    json={
                        "location_id": location_id,
                        "consultant_name": consultant_name,
                        "checklist": checklist_payload,
                        "free_text_notes": free_text,
                        "photo_description": photo_desc,
                    },
                )
            except RuntimeError as e:
                st.error(str(e))
                return
        st.session_state.audit_id = result["audit_id"]
        st.session_state.clarification = result["clarification"]
        st.session_state.stage = "clarifying" if not result["clarification"]["is_sufficient"] \
            and result["clarification"]["clarifying_questions"] else "ready_to_run"
        st.rerun()


def render_clarifying(location_id: int, consultant_name: str):
    clar = st.session_state.clarification
    st.subheader("A quick follow-up before we finalize findings")
    st.info(clar["reasoning"])
    st.caption(
        "The AI flagged these as too thin to turn into a defensible finding on their own. "
        "Answer what you can -- anything left blank will be marked for manager review rather than guessed at."
    )

    for q in clar["clarifying_questions"]:
        st.session_state.clar_answers[q] = st.text_input(q, key=f"clar::{q}")

    proceed_anyway = st.checkbox(
        "I don't have more detail to add -- proceed anyway "
        "(unanswered items will be flagged for manager review, not asserted as fact)"
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Submit Answers & Generate Report", type="primary"):
            _run_audit(location_id, consultant_name, proceed_anyway)
    with col2:
        if st.button("Start Over"):
            reset_audit()
            st.rerun()


def _run_audit(location_id: int, consultant_name: str, proceed_anyway: bool):
    answers = [{"question": q, "answer": a} for q, a in st.session_state.clar_answers.items() if a]
    with st.spinner("Generating findings, pulling recent reviews, and drafting the corrective plan..."):
        try:
            report = api(
                "POST", "/audits/run",
                json={
                    "location_id": location_id,
                    "consultant_name": consultant_name,
                    "checklist": [],  # already persisted against this audit_id
                    "audit_id": st.session_state.audit_id,
                    "clarification_answers": answers,
                    "proceed_despite_gaps": proceed_anyway,
                },
            )
        except RuntimeError as e:
            st.error(str(e))
            return
    st.session_state.report = report
    st.session_state.stage = "report"
    st.rerun()


def render_ready_to_run(location_id: int, consultant_name: str):
    st.success("Input looks specific enough to generate findings.")
    if st.button("Generate Audit Report", type="primary"):
        _run_audit(location_id, consultant_name, proceed_anyway=False)
    if st.button("Back to Checklist"):
        reset_audit()
        st.rerun()


def render_report():
    report = st.session_state.report
    st.success(f"Audit report ready · {report['location']['name']}")

    if report["reviews_are_mocked"]:
        st.warning(
            "**Demo mode:** no live Google Maps API key is configured on this deployment, so the "
            "review data below is synthetic sample data, not real Wolf Creek reviews. "
            "Set `GOOGLE_MAPS_API_KEY` to pull live data.",
            icon="ℹ️",
        )

    tab_consultant, tab_franchisee = st.tabs(["Consultant View", "Franchisee View"])

    with tab_consultant:
        st.markdown(f"**Overall summary:** {report['overall_summary']}")
        st.markdown("### Findings")
        if not report["findings"]:
            st.info("No compliance issues identified this visit.")
        for f in report["findings"]:
            color = SEVERITY_COLOR.get(f["severity"], "#888")
            review_flag = " " + badge("NEEDS HUMAN REVIEW", "#6c757d") if f["requires_human_review"] else ""
            st.markdown(
                f"{badge(f['severity'].upper(), color)}{review_flag} &nbsp; "
                f"**{f['category']}** &nbsp; · &nbsp; confidence: {f['confidence']:.0%}",
                unsafe_allow_html=True,
            )
            st.write(f["finding_summary"])
            with st.expander("Evidence & standard reference"):
                st.write(f"**Evidence:** {f['supporting_evidence']}")
                if f.get("standard_reference"):
                    st.write(f"**Standard:** {f['standard_reference']}")
            st.divider()

        if report.get("review_insights"):
            st.markdown("### Public Review Correlation")
            st.caption(report["review_insights"]["caveat"])
            for t in report["review_insights"]["themes"]:
                conf_color = {"low": "#999", "medium": "#E0A800", "high": "#D9534F"}[t["linkage_confidence"]]
                st.markdown(
                    f"**{t['theme']}** ({t['mention_count']} mentions) "
                    + badge(f"link: {t['linkage_confidence']}", conf_color),
                    unsafe_allow_html=True,
                )
                st.caption(t["linkage_note"])
                if t.get("linked_categories"):
                    st.write("Related categories: " + ", ".join(t["linked_categories"]))

        with st.expander("Audit trail (full prompts/responses for every AI step)"):
            try:
                trail = api("GET", f"/audits/{report['audit_id']}/trail")
                for entry in trail:
                    st.markdown(f"**{entry['step_name']}** · `{entry['model_used']}` · {entry['created_at']}")
                    st.code(entry["prompt"], language="text")
                    st.code(entry["response"], language="json")
            except RuntimeError as e:
                st.error(str(e))

    with tab_franchisee:
        st.markdown("#### A note from your BroadPeak field team")
        st.write(report["franchisee_message"])

        if report["findings"]:
            st.markdown("#### Corrective Action Plan")
            rows = []
            for a in report["corrective_actions"]:
                rows.append(
                    {
                        "Action": a["action_text"],
                        "Owner": a["owner"],
                        "Suggested deadline": f"{a['suggested_deadline_days']} days",
                    }
                )
            st.table(rows)
        else:
            st.write("No corrective actions needed this visit -- nice work.")

        if report.get("review_insights") and report["review_insights"]["themes"]:
            st.markdown("#### What guests have been saying recently")
            st.caption(report["review_insights"]["caveat"])
            for t in report["review_insights"]["themes"]:
                st.write(f"- **{t['theme']}** — {t['linkage_note']}")

    if st.button("Start a New Audit"):
        reset_audit()
        st.rerun()


def main():
    st.set_page_config(page_title="BroadPeak Field Audit Intelligence", page_icon="🏌️", layout="wide")
    init_state()

    st.title("🏌️ Field Audit Intelligence")
    st.caption("BroadPeak Investment Group · AI-assisted field audit proof of concept")

    try:
        health = api("GET", "/health")
    except RuntimeError as e:
        st.error(f"Cannot reach backend API at {BACKEND_URL}: {e}")
        st.stop()

    if not health["llm_configured"]:
        st.error(
            "`GROQ_API_KEY` is not configured on this deployment. The AI pipeline "
            "(clarification, findings, review correlation, corrective actions) cannot run until "
            "it's set as a secret. The rest of the UI is browsable in the meantime."
        )

    try:
        locations = api("GET", "/locations")
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    if not locations:
        st.error("No locations seeded yet.")
        st.stop()

    with st.sidebar:
        st.header("Audit Setup")
        loc_labels = {loc["id"]: f"{loc['name']} — {loc['address']}" for loc in locations}
        location_id = st.selectbox(
            "Location", options=list(loc_labels.keys()), format_func=lambda i: loc_labels[i],
        )
        
        if location_id is None:
            st.stop()

        
        consultant_name = st.text_input("Consultant name", value="Jordan Rivera")
        st.divider()
        st.caption(f"Backend: {BACKEND_URL}")
        st.caption(f"Review data: {'Mock / demo' if health['reviews_are_mocked'] else 'Live Google Places'}")
        if st.button("Reset session"):
            reset_audit()
            st.rerun()

    st.session_state.location_id = location_id

    stage = st.session_state.stage
    if stage == "intake":
        render_intake(location_id, consultant_name)
    elif stage == "clarifying":
        render_clarifying(location_id, consultant_name)
    elif stage == "ready_to_run":
        render_ready_to_run(location_id, consultant_name)
    elif stage == "report":
        render_report()


if __name__ == "__main__":
    main()
