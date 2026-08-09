"""
main.py
=======
FastAPI app for Field Audit Intelligence.

Endpoints are intentionally small and composable -- the Streamlit frontend
(or any other client, e.g. a future mobile app) drives the workflow by
calling these in sequence:

  1. GET  /locations                 -> pick a location
  2. POST /audits/clarify            -> submit raw input, get back either
                                         "sufficient" or clarifying questions
  3. POST /audits/run                -> (re)submit with any answers, get the
                                         full structured audit report
  4. GET  /audits/{id}               -> re-fetch a completed report
  5. GET  /audits/{id}/trail         -> explainability: every prompt/response
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend import audit_service, db, seed_data
from backend.config import settings
from backend.models import (
    AuditInputRequest,
    AuditReportOut,
    LocationOut,
    RunAuditRequest,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    seed_data.seed_all()
    yield


app = FastAPI(
    title="BroadPeak Field Audit Intelligence API",
    description="AI-assisted field audit findings, review correlation, and corrective action plans.",
    version="0.1.0",
    lifespan=lifespan,
)

# Wide-open CORS is fine for this single-purpose POC (Streamlit frontend
# calling a backend that lives in the same container / trusted network).
# A production deployment would restrict this to the known frontend origin.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_configured": settings.llm_is_configured,
        "reviews_are_mocked": settings.reviews_are_mocked,
    }


@app.get("/locations", response_model=list[LocationOut])
def list_locations() -> list[LocationOut]:
    return [LocationOut(**loc) for loc in db.list_locations()]


@app.post("/audits/clarify")
async def clarify(req: AuditInputRequest) -> dict:
    if not settings.llm_is_configured:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is not configured on this deployment. "
                   "Set it as a secret to enable the AI pipeline.",
        )
    audit_id, check = await audit_service.run_clarification(req)
    return {"audit_id": audit_id, "clarification": check.model_dump()}


@app.post("/audits/run", response_model=AuditReportOut)
async def run_audit(req: RunAuditRequest) -> AuditReportOut:
    if not settings.llm_is_configured:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is not configured on this deployment. "
                   "Set it as a secret to enable the AI pipeline.",
        )
    try:
        return await audit_service.run_full_audit(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/audits/{audit_id}", response_model=AuditReportOut)
async def get_audit(audit_id: str) -> AuditReportOut:
    report = await audit_service.get_report(audit_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Audit not found")
    return report


@app.get("/audits/{audit_id}/trail")
def get_trail(audit_id: str) -> list[dict]:
    return db.get_audit_trail(audit_id)


@app.get("/audits")
def list_audits() -> list[dict]:
    return db.list_audit_sessions()


if __name__ == "__main__":
    import uvicorn

    from backend.config import settings
    
    uvicorn.run(
        "backend.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        server_header=False,
        reload=True,
    )