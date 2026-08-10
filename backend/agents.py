"""
agents.py
=========
The four Pydantic AI agents that make up the audit pipeline. Each agent has
one narrow job, a strict structured output type (see models.py), and an
explicit system prompt that encodes the guardrails called out in the brief:
never assert a violation the input doesn't support, flag uncertainty for a
human instead of guessing, and keep the franchisee-facing tone constructive.

Model tiering (cost/latency):
  - `clarification_agent` and `review_agent` use the FAST model: their job
    is closer to classification/summarization than open-ended judgment.
  - `findings_agent` and `corrective_action_agent` use the STRONG model:
    these outputs are what a franchisee will actually be held to, so we
    spend more compute on getting the judgment calls right.

Every agent call is logged verbatim (prompt + response) via
`backend.db.log_audit_trail` by the caller in `audit_service.py`, so any
finding or action can be traced back to exactly what the model was shown
and what it said.
"""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider

from backend.config import settings
from backend.models import (
    ClarificationCheck,
    CorrectiveActionPlan,
    FindingsReport,
    ReviewInsights,
)


def _model(model_name: str) -> GroqModel:
    return GroqModel(model_name, provider=GroqProvider(api_key=settings.groq_api_key))


# NOTE ON LAZY CONSTRUCTION:
# Building a GroqModel eagerly at import time raises immediately if
# GROQ_API_KEY isn't set -- which would crash the whole FastAPI app on
# startup (including harmless endpoints like /health and /locations) any
# time the key isn't configured yet. Each agent is therefore built lazily,
# on first actual use, and cached. `backend/main.py` already returns a
# clear 503 from the audit endpoints when no key is configured, so in
# practice these are only constructed once a key is present.
_agent_cache: dict[str, Agent] = {}


def _get_agent(name: str, model_name: str, output_type, system_prompt: str) -> Agent:
    if name not in _agent_cache:
        _agent_cache[name] = Agent(
            model=_model(model_name), output_type=output_type, system_prompt=system_prompt, retries={"output": 3},
        )
    return _agent_cache[name]


async def run_with_retry(agent: Agent, prompt: str, max_attempts: int = 3):
    """
    Workaround for a pydantic-ai gap (open as of pydantic-ai-slim 2.27.0):
    Groq's `output_parse_failed` error -- the model emits a malformed
    `final_result` tool call that even Groq's own parser can't read -- isn't
    recognized by pydantic-ai's Groq error handler (which only matches
    `code == 'tool_use_failed'`). That means it bypasses the `retries=`
    setting entirely and raises immediately. We catch that specific case
    here and retry the same prompt ourselves.

    Any other error (bad API key, rate limit, network issue, etc.) is
    re-raised immediately -- we only retry the one known parse-failure
    signature.
    """
    last_exc: ModelHTTPError | None = None
    for attempt in range(max_attempts):
        try:
            return await agent.run(prompt)
        except ModelHTTPError as e:
            body = e.body if isinstance(e.body, dict) else {}
            code = body.get("error", {}).get("code")
            if e.status_code == 400 and code in ("output_parse_failed", "tool_use_failed"):
                last_exc = e
                print(f"[groq-retry] {code} on attempt {attempt + 1}/{max_attempts}, retrying...")
                continue
            raise
         
    assert last_exc is not None  # every loop iteration above either returned or set last_exc
    
    raise last_exc

# ---------------------------------------------------------------------------
# 1. Clarification Agent
# ---------------------------------------------------------------------------
CLARIFICATION_SYSTEM_PROMPT = """
You are a careful field-audit quality gate for franchise compliance visits.

You will be shown a consultant's raw checklist responses, free-text notes,
and a written stand-in for a photo. Your ONLY job is to decide whether this
input has enough concrete detail to support a specific, defensible finding
for each item marked "fail" or that reads as ambiguous/thin (e.g. "floor
looked a little dirty", "seemed slow today").

Rules:
- Do NOT write findings yourself. Do NOT guess at severity or cause.
- Treat vague quantifiers ("a little", "kind of", "seemed") as insufficient
  on their own -- ask for what specifically was observed, where, and how it
  compares to the standard.
- If checklist items are marked "pass" or "na" with no notes, that is fine
  and needs no clarification.
- Only ask questions a consultant standing at the location could actually
  answer quickly (avoid open-ended or research-y questions).
- If everything is already specific and concrete, set is_sufficient=True and
  return an empty question list -- do not invent busywork questions.
"""

def get_clarification_agent() -> Agent:
    return _get_agent("clarification", settings.model_fast, ClarificationCheck, CLARIFICATION_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# 2. Findings Agent
# ---------------------------------------------------------------------------
FINDINGS_SYSTEM_PROMPT = """
You are an AI assistant supporting (not replacing) a trained field
compliance consultant for a franchise brand. You turn a consultant's raw
audit input into structured findings.

Hard rules -- violating any of these is a serious failure:
1. Every finding's `supporting_evidence` must be a real excerpt of what the
   consultant actually wrote or the checklist response given to you. Never
   invent details, locations, dates, or facts not present in the input.
2. If the input for an item is thin, ambiguous, or you are inferring beyond
   what's stated, set `requires_human_review=True` and lower `confidence`
   accordingly. It is always better to flag for a human than to assert.
3. Only write a finding for checklist items marked "fail" or for free-text
   notes that describe a concrete standards issue. Do not manufacture
   findings for items marked "pass".
4. severity should reflect real-world risk: "critical" = safety/legal
   exposure requiring near-immediate action; "high" = clear standards
   violation visible to guests; "medium" = notable but contained issue;
   "low" = minor/cosmetic.
5. When brand standard text is provided below, reference the specific
   standard in `standard_reference`. If no relevant standard was retrieved,
   leave it null rather than inventing one.
6. Keep `finding_summary` neutral and factual -- describe what was
   observed, not blame or speculation about why it happened.
"""

def get_findings_agent() -> Agent:
    return _get_agent("findings", settings.model_strong, FindingsReport, FINDINGS_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# 3. Review Correlation Agent
# ---------------------------------------------------------------------------
REVIEW_SYSTEM_PROMPT = """
You analyze a small set of recent public customer reviews (mostly
lower-rated ones) for one location and summarize recurring themes.

Hard rules:
1. This is a SMALL, recency-biased sample (the Places API only exposes a
   handful of recent reviews) -- never claim it is statistically
   representative of overall guest sentiment.
2. When a review theme plausibly relates to one of the given audit
   categories, say so as a *correlation*, using hedged language ("may
   relate to", "is consistent with"), never as proof or causation. Reviews
   never "confirm" or "prove" an audit finding.
3. If reviews and audit findings show no relationship, do not force one --
   leave `linked_categories` empty for that theme.
4. Do not quote reviews verbatim at length; paraphrase themes.
5. Always fill in `caveat` with a short, honest statement about the sample
   size / recency limitation, for display to the reader.
"""

def get_review_agent() -> Agent:
    return _get_agent("review", settings.model_fast, ReviewInsights, REVIEW_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# 4. Corrective Action Agent
# ---------------------------------------------------------------------------
CORRECTIVE_SYSTEM_PROMPT = """
You write franchisee-facing corrective action plans from a list of
confirmed audit findings. The franchisee is a business partner, not a
subordinate being punished -- tone matters as much as content.

Rules:
1. Each action must be concrete and specific enough to close out (what to
   fix, roughly how), not vague ("improve cleanliness").
2. Suggested deadlines scale with severity as a starting point:
   critical -> 1-3 days, high -> 7-14 days, medium -> 21-30 days,
   low -> 45-60 days. You may adjust within reason if the action clearly
   needs more or less time, but stay in a sensible range.
3. `owner` should be a role at the location (e.g. "General Manager",
   "Grounds Crew Lead"), not a named individual.
4. `franchisee_message` should be warm, specific, and collaborative --
   acknowledge what's working before the corrective items, and frame this
   as a shared standard, not a gotcha. Never use accusatory language.
5. Do not introduce any new findings here -- only act on what you were
   given.
"""

def get_corrective_action_agent() -> Agent:
    return _get_agent("corrective_action", settings.model_strong, CorrectiveActionPlan, CORRECTIVE_SYSTEM_PROMPT)
