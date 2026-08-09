
"""
FastAPI app for Field Audit Intelligence.

The FastAPI application serves both:
1. The vanilla HTML/CSS/JS frontend
2. The JSON API used by that frontend

Workflow:

1. GET  /locations
2. POST /audits/clarify
3. POST /audits/run
4. GET  /audits/{id}
5. GET  /audits/{id}/trail
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import audit_service, db, seed_data
from backend.config import settings
from backend.models import (
    AuditInputRequest,
    AuditReportOut,
    LocationOut,
    RunAuditRequest,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    seed_data.seed_all()
    yield


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="BroadPeak Field Audit Intelligence API",
    description=(
        "AI-assisted field audit findings, review correlation, "
        "and corrective action plans."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

# Since the frontend is served by this same FastAPI application,
# CORS is not actually required for normal production use.
#
# Keeping it open is useful during development if you later run the
# frontend separately.


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

# Serve CSS, JavaScript, images, etc.
app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="static",
)


@app.get("/", include_in_schema=False)
async def frontend():
    return FileResponse(FRONTEND_DIR / "index.html")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_configured": settings.llm_is_configured,
        "reviews_are_mocked": settings.reviews_are_mocked,
    }


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

@app.get(
    "/locations",
    response_model=list[LocationOut],
)
def list_locations() -> list[LocationOut]:
    return [
        LocationOut(**loc)
        for loc in db.list_locations()
    ]


# ---------------------------------------------------------------------------
# Audit clarification
# ---------------------------------------------------------------------------

@app.post("/audits/clarify")
async def clarify(req: AuditInputRequest) -> dict:

    if not settings.llm_is_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "GROQ_API_KEY is not configured on this deployment. "
                "Set it as a secret to enable the AI pipeline."
            ),
        )

    audit_id, check = await audit_service.run_clarification(req)

    return {
        "audit_id": audit_id,
        "clarification": check.model_dump(),
    }


# ---------------------------------------------------------------------------
# Run full audit
# ---------------------------------------------------------------------------

@app.post(
    "/audits/run",
    response_model=AuditReportOut,
)
async def run_audit(
    req: RunAuditRequest,
) -> AuditReportOut:

    if not settings.llm_is_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "GROQ_API_KEY is not configured on this deployment. "
                "Set it as a secret to enable the AI pipeline."
            ),
        )

    try:
        return await audit_service.run_full_audit(req)

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# Get completed audit
# ---------------------------------------------------------------------------

@app.get(
    "/audits/{audit_id}",
    response_model=AuditReportOut,
)
async def get_audit(
    audit_id: str,
) -> AuditReportOut:

    report = await audit_service.get_report(audit_id)

    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Audit not found",
        )

    return report


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

@app.get("/audits/{audit_id}/trail")
def get_trail(
    audit_id: str,
) -> list[dict]:

    return db.get_audit_trail(audit_id)


# ---------------------------------------------------------------------------
# Audit list
# ---------------------------------------------------------------------------

@app.get("/audits")
def list_audits() -> list[dict]:
    return db.list_audit_sessions()


# ---------------------------------------------------------------------------
# Local development
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        server_header=False,
        # reload=True,
    )
