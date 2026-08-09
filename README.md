# Field Audit Intelligence

AI-assisted field audit application for franchise compliance visits.

This is a **traditional FastAPI web application**. FastAPI serves both:

- the HTML/CSS/JavaScript frontend
- the JSON API used by the frontend

The app is deployed as a single service on **Render**.

---

## Tech Stack

- **FastAPI**
- **Vanilla HTML/CSS/JS frontend**
- **Pydantic AI**
- **Groq LLM**
- **SQLite**
- **ChromaDB**
- **Google Places API** optional, with mock fallback

---

## Application Workflow

1. Consultant selects a location.
2. Consultant fills out the audit checklist.
3. The app checks whether the input is specific enough.
4. If needed, the AI asks follow-up clarification questions.
5. The app generates:
   - audit findings
   - review correlation insights
   - franchisee-facing corrective action plan
6. Every AI prompt and response is stored in the audit trail.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Serves frontend |
| GET | `/health` | Health check |
| GET | `/locations` | Lists seeded locations |
| POST | `/audits/clarify` | Checks audit input and asks clarification questions if needed |
| POST | `/audits/run` | Runs full audit pipeline |
| GET | `/audits/{audit_id}` | Returns completed audit |
| GET | `/audits/{audit_id}/trail` | Returns AI prompt/response audit trail |
| GET | `/audits` | Lists audit sessions |

---

## Local Setup

### 1. Create virtual environment

```bash
python -m venv venv