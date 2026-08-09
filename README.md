---
title: Field Audit Intelligence
emoji: 🏌️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Field Audit Intelligence — BroadPeak AI Engineer Take-Home

> **This is a proof of concept, not a production system.** It demonstrates
> the agent design, guardrails, and interaction model end-to-end on one
> location and one brand. It intentionally skips things a real production
> deployment would need — see "Next steps" at the bottom — and the code is
> commented throughout with where corners were cut and why.

An AI-assisted field audit experience built for BroadPeak's franchise field
consultants. Given a checklist, free-text notes, and a written stand-in for
a photo, it produces evidence-grounded findings, cross-references recent
public reviews for the location, and drafts a franchisee-facing corrective
action plan — asking for clarification instead of guessing when the input
is too thin.

Demo location: **Wolf Creek Golf Club**, Atlanta, GA (a real BroadPeak
portfolio property, per the assessment brief).

## Uses Groq for inference

This POC calls Groq (`openai/gpt-oss-20b` for fast/cheap steps,
`openai/gpt-oss-120b` for judgment-heavy steps — see "Why these tools"
below) via Pydantic AI, chosen for speed and low cost so this can run as a
public, free-to-run live demo. Get a free key at
**https://console.groq.com/keys**.

## Architecture

```
┌─────────────────────┐        HTTP (localhost)       ┌──────────────────────────┐
│  Streamlit frontend  │ ─────────────────────────────▶│   FastAPI backend        │
│  (port 7860, public) │◀───────────────────────────── │   (port 8000, internal)  │
└─────────────────────┘                                └────────────┬─────────────┘
                                                                     │
                              ┌──────────────────────────────────────┼───────────────────────────┐
                              │                                      │                           │
                     ┌────────▼────────┐                   ┌─────────▼─────────┐        ┌─────────▼─────────┐
                     │  Pydantic AI     │                   │  ChromaDB (RAG)    │        │  Google Places API │
                     │  agents          │                   │  brand standards   │        │  (New) — reviews,  │
                     │  (Groq models)   │                   │  by brand+category │        │  with mock fallback│
                     └────────┬─────────┘                   └────────────────────┘        └─────────────────────┘
                              │
                     ┌────────▼─────────┐
                     │  SQLite           │
                     │  audits, findings,│
                     │  audit trail, ... │
                     └───────────────────┘
```

**Pipeline** (`backend/audit_service.py`):
1. **Clarification Agent** — decides if the raw input can support a
   defensible finding; if not, returns targeted follow-up questions instead
   of guessing.
2. **Findings Agent** — turns checklist + notes + retrieved brand standards
   into structured, evidence-cited findings with a severity and a
   self-rated confidence; low-confidence/ambiguous items are flagged
   `requires_human_review` rather than asserted.
3. **Review Correlation Agent** — summarizes recurring themes in recent
   (~90 day) negative Google reviews for the location and notes *plausible,
   hedged* links to audit categories — never a causal claim.
4. **Corrective Action Agent** — drafts a franchisee-facing action plan
   with deadlines scaled to severity and a collaborative cover message.

Every agent call's exact prompt and response is logged to the
`audit_trail` table and viewable in the UI, for explainability/defensibility.

## Why these tools

- **Pydantic AI + strict output types** (`backend/models.py`) force every
  agent response into a validated schema instead of freeform text — this is
  what makes findings renderable, auditable, and safe to hand to a
  franchisee.
- **ChromaDB** stores brand standards as small, retrievable documents keyed
  by brand + category, so the same agent code scales across BroadPeak
  brands with different standards (golf club, fast-casual, gifting, etc.)
  without a code change — see `backend/rag.py` and `backend/seed_data.py`.
- **SQLite** keeps the POC's persistence transparent and file-based; see
  "Next steps" below for the production path.
- **Model tiering** (`backend/config.py`, `backend/agents.py`): a fast/cheap
  model handles classification-style steps (clarification check, review
  summarization), a stronger model handles judgment-heavy steps (findings,
  corrective actions) — a real cost lever once this runs across hundreds of
  locations doing several LLM calls per visit.

## Handling the Places API's review-history limit

The Places API only ever returns a handful of the most recent reviews per
call — there's no way to page through full history. `backend/google_places.py`
addresses this by upserting every fetched review into a `review_snapshots`
table keyed by a stable hash of (author, text). Repeated audits over time
accumulate a longer effective review history than any single call returns,
and the "last ~3 months" filter is applied against that accumulated set, not
just the latest fetch.

## Mock mode

If `GOOGLE_MAPS_API_KEY` is not set, the app automatically serves clearly
labeled synthetic review data so the whole pipeline is demoable without live
credentials. This is surfaced in the API (`reviews_are_mocked`), the
database (`is_mock` column), and the UI (a visible banner) — never silently
presented as real.

If `GROQ_API_KEY` is not set, the AI endpoints return a clear 503
rather than failing silently or fabricating a response.

## Running locally

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # then fill in GROQ_API_KEY (required)
                                     # GOOGLE_MAPS_API_KEY is optional (mock fallback)

# Terminal 1 — backend
uvicorn backend.main:app --reload --port 8000

# Terminal 2 — frontend
streamlit run frontend/streamlit_app.py
```

Or via Docker (same image used for the HF Space):

```bash
docker build -t field-audit-intelligence .
docker run -p 7860:7860 \
  -e GROQ_API_KEY=gsk_... \
  -e GOOGLE_MAPS_API_KEY=... \
  field-audit-intelligence
# open http://localhost:7860
```

## Manual testing walkthrough (do this on your laptop)

1. **Get a free Groq key**: https://console.groq.com/keys → create a key,
   no credit card needed on the free tier.
2. **Set it up**: `cp .env.example .env`, paste the key into `GROQ_API_KEY=`.
   Leave `GOOGLE_MAPS_API_KEY` blank for now — the app runs fine in mock
   review mode, clearly labeled as such in the UI.
3. **Run it** using either the two-terminal method or the Docker method
   above, then open the Streamlit URL it prints (usually
   `http://localhost:8501` for the two-terminal method, or
   `http://localhost:7860` for Docker).
4. **Try the happy path**: pick Wolf Creek Golf Club, mark a couple of
   checklist items "fail" with a *specific* note (e.g. "cart path near hole
   7 has a 2-foot crack, guests routed around it"), leave others "pass",
   click **Run Pre-Check**. Specific notes should sail through to **Generate
   Audit Report** without a clarification detour.
5. **Try the thin-input path**: mark an item "fail" with a vague note like
   "floor looked a little dirty" and nothing else. Click **Run Pre-Check** —
   you should get bounced into a short follow-up-questions screen instead
   of a guessed finding. Answer (or explicitly check "proceed anyway") and
   confirm the resulting finding is flagged for human review if you left it
   unanswered.
6. **Check both audiences**: on the report screen, flip between
   **Consultant View** (confidence %, evidence, audit trail) and
   **Franchisee View** (clean letter + action table, no internal scoring).
7. **Check the review correlation**: with no Google key set, you'll see a
   "Demo mode" banner and synthetic review themes (pace of play, restroom
   cleanliness, cart paths) — some should show a *hedged* link to your
   findings, never a hard causal claim.
8. **Check explainability**: expand "Audit trail" in the Consultant View —
   every prompt sent to the model and its structured response should be
   there, per audit.
9. **Optional — live reviews**: add a real `GOOGLE_MAPS_API_KEY` (Places API
   enabled on it) and re-run an audit; the banner should disappear and
   themes should reflect real recent reviews for Wolf Creek Golf Club.

If step 4 or 5 errors instead of returning a result, check the terminal
running `uvicorn` for a traceback — the most likely causes are an invalid
`GROQ_API_KEY` or hitting the Groq free-tier rate limit (wait a minute and
retry).

## Deploying to Hugging Face Spaces (live demo)

1. Create a new Space → SDK: **Docker**.
2. Push this repo's contents to the Space's git remote (this `README.md`'s
   YAML frontmatter is the Space config — no extra setup needed).
3. Under **Settings → Variables and secrets**, add `GROQ_API_KEY`
   (required) and optionally `GOOGLE_MAPS_API_KEY`.
4. The Space builds the `Dockerfile` and serves the Streamlit UI on the
   port HF routes to automatically (7860). No other configuration needed —
   mock review mode means the demo is fully functional with just the one
   Groq secret set.

## Key design decisions (see the written summary for full rationale)

- **Primary user = the field consultant in the moment**, so the primary
  interface is a fast structured form, not a chatbot. The AI only drops
  into a conversational follow-up when it genuinely needs more detail to
  avoid guessing.
- **Two audiences, two views**: findings carry confidence scores, human-
  review flags, and raw evidence for the consultant; the franchisee view is
  clean, respectful, and action-oriented with none of that internal
  machinery exposed.
- **Nothing is asserted without evidence**: every finding must cite a real
  excerpt from the consultant's own input; thin or ambiguous input triggers
  a clarifying question or a `requires_human_review` flag, never a guess.
- **Review data is weighted honestly**: it's explicitly framed as a small,
  recency-biased sample that may *correlate* with a finding, never as proof.

## Next steps before this touches a real franchise location

- Swap SQLite → Postgres with real migrations for multi-tenant durability.
- Real photo upload + vision-model analysis instead of a text stand-in.
- A standards-authoring workflow (with versioning/approval) instead of
  hand-edited seed data, so franchise-ops teams can maintain brand
  standards without an engineer.
- Human-in-the-loop review UI for anything flagged `requires_human_review`
  before a report reaches a franchisee, with sign-off tracked in the audit
  trail.
- Rate limiting / cost monitoring per location given multiple LLM calls +
  an external API call per audit, and evaluation harness (golden audits)
  to catch prompt regressions before they reach the field.
