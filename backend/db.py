"""
db.py
=====
SQLite persistence layer.

Design choice: plain `sqlite3` + small helper functions instead of a full
ORM. For a 3-5 hour POC this keeps the schema fully visible in one file
(easy for a reviewer to audit) while still giving us:
  - a durable, queryable audit trail (every prompt/response the agent
    produced, for defensibility -- see "audit trail" question in the brief)
  - a review_snapshots table that lets us accumulate review history over
    time even though the Places API only ever returns a handful of the
    most recent reviews per call (see google_places.py for the write-up
    on this constraint).

In a production, multi-tenant version of this system this file would be
swapped for a proper Postgres schema + migrations (Alembic) — noted in the
"Next Steps" section of the written summary.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from backend.config import settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with row access by column name."""
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS locations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    brand           TEXT NOT NULL,
    address         TEXT NOT NULL,
    place_id        TEXT,                 -- Google Places place_id, resolved lazily
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_sessions (
    id                  TEXT PRIMARY KEY,      -- uuid4
    location_id         INTEGER NOT NULL REFERENCES locations(id),
    consultant_name     TEXT NOT NULL,
    status              TEXT NOT NULL,          -- draft | clarifying | completed
    free_text_notes     TEXT,
    photo_description   TEXT,
    overall_summary     TEXT,
    franchisee_message  TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checklist_responses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id    TEXT NOT NULL REFERENCES audit_sessions(id),
    category    TEXT NOT NULL,
    question    TEXT NOT NULL,
    response    TEXT NOT NULL,      -- pass | fail | na
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS clarifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id    TEXT NOT NULL REFERENCES audit_sessions(id),
    question    TEXT NOT NULL,
    answer      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id                TEXT NOT NULL REFERENCES audit_sessions(id),
    category                TEXT NOT NULL,
    finding_summary         TEXT NOT NULL,
    severity                TEXT NOT NULL,      -- low | medium | high | critical
    confidence              REAL NOT NULL,      -- 0..1, model self-rated
    requires_human_review   INTEGER NOT NULL,   -- 0/1
    supporting_evidence     TEXT NOT NULL,       -- verbatim excerpt from consultant input
    standard_reference      TEXT
);

CREATE TABLE IF NOT EXISTS corrective_actions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id                TEXT NOT NULL REFERENCES audit_sessions(id),
    finding_id              INTEGER REFERENCES findings(id),
    action_text             TEXT NOT NULL,
    suggested_deadline_days INTEGER NOT NULL,
    owner                   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id     INTEGER NOT NULL REFERENCES locations(id),
    review_key      TEXT NOT NULL,      -- stable hash of author+text, for de-dup across fetches
    author_name     TEXT,
    rating          INTEGER,
    publish_time    TEXT,               -- ISO time reported by Google, if available
    review_text     TEXT,
    is_mock         INTEGER NOT NULL DEFAULT 0,
    fetched_at      TEXT NOT NULL,
    UNIQUE(location_id, review_key)
);

CREATE TABLE IF NOT EXISTS review_insights (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id            TEXT NOT NULL REFERENCES audit_sessions(id),
    theme               TEXT NOT NULL,
    mention_count       INTEGER NOT NULL,
    example_snippet     TEXT,
    linked_categories   TEXT,               -- JSON list
    linkage_confidence  TEXT NOT NULL,      -- low | medium | high
    linkage_note        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_trail (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id    TEXT NOT NULL REFERENCES audit_sessions(id),
    step_name   TEXT NOT NULL,      -- e.g. "clarification_check", "findings_agent"
    model_used  TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    response    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

def upsert_location(name: str, brand: str, address: str, place_id: str | None = None) -> int:
    with get_conn() as conn:
        cur = conn.execute("SELECT id FROM locations WHERE name = ? AND address = ?", (name, address))
        row = cur.fetchone()
        if row:
            if place_id:
                conn.execute("UPDATE locations SET place_id = ? WHERE id = ?", (place_id, row["id"]))
            return row["id"]
        cur = conn.execute(
            "INSERT INTO locations (name, brand, address, place_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, brand, address, place_id, _now()),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid


def get_location(location_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
        return dict(row) if row else None


def list_locations() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM locations ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def set_location_place_id(location_id: int, place_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE locations SET place_id = ? WHERE id = ?", (place_id, location_id))


# ---------------------------------------------------------------------------
# Audit sessions
# ---------------------------------------------------------------------------

def create_audit_session(audit_id: str, location_id: int, consultant_name: str,
                          free_text_notes: str, photo_description: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO audit_sessions
               (id, location_id, consultant_name, status, free_text_notes,
                photo_description, created_at, updated_at)
               VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)""",
            (audit_id, location_id, consultant_name, free_text_notes, photo_description, _now(), _now()),
        )


def update_audit_status(audit_id: str, status: str, overall_summary: str | None = None,
                         franchisee_message: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE audit_sessions
               SET status = ?, overall_summary = COALESCE(?, overall_summary),
                   franchisee_message = COALESCE(?, franchisee_message), updated_at = ?
               WHERE id = ?""",
            (status, overall_summary, franchisee_message, _now(), audit_id),
        )


def get_audit_session(audit_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM audit_sessions WHERE id = ?", (audit_id,)).fetchone()
        return dict(row) if row else None


def list_audit_sessions() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM audit_sessions ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Checklist responses
# ---------------------------------------------------------------------------

def save_checklist_responses(audit_id: str, items: list[dict[str, Any]]) -> None:
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO checklist_responses (audit_id, category, question, response, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            [(audit_id, i["category"], i["question"], i["response"], i.get("notes")) for i in items],
        )


def get_checklist_responses(audit_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM checklist_responses WHERE audit_id = ?", (audit_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Clarifications
# ---------------------------------------------------------------------------

def save_clarification_questions(audit_id: str, questions: list[str]) -> None:
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO clarifications (audit_id, question, answer, created_at) VALUES (?, ?, NULL, ?)",
            [(audit_id, q, _now()) for q in questions],
        )


def save_clarification_answer(audit_id: str, question: str, answer: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE clarifications SET answer = ? WHERE audit_id = ? AND question = ? AND answer IS NULL",
            (answer, audit_id, question),
        )


def get_clarifications(audit_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM clarifications WHERE audit_id = ?", (audit_id,)).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Findings & corrective actions
# ---------------------------------------------------------------------------

def save_findings(audit_id: str, findings: list[dict[str, Any]]) -> list[int]:
    ids = []
    with get_conn() as conn:
        for f in findings:
            cur = conn.execute(
                """INSERT INTO findings
                   (audit_id, category, finding_summary, severity, confidence,
                    requires_human_review, supporting_evidence, standard_reference)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (audit_id, f["category"], f["finding_summary"], f["severity"], f["confidence"],
                 int(f["requires_human_review"]), f["supporting_evidence"], f.get("standard_reference")),
            )
            ids.append(cur.lastrowid)
    return ids


def get_findings(audit_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM findings WHERE audit_id = ?", (audit_id,)).fetchall()
        return [dict(r) for r in rows]


def save_corrective_actions(audit_id: str, actions: list[dict[str, Any]]) -> None:
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO corrective_actions
               (audit_id, finding_id, action_text, suggested_deadline_days, owner)
               VALUES (?, ?, ?, ?, ?)""",
            [(audit_id, a.get("finding_id"), a["action_text"], a["suggested_deadline_days"], a["owner"])
             for a in actions],
        )


def get_corrective_actions(audit_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM corrective_actions WHERE audit_id = ?", (audit_id,)).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Review snapshots (accumulated review history)
# ---------------------------------------------------------------------------

def upsert_review_snapshots(location_id: int, reviews: list[dict[str, Any]], is_mock: bool) -> None:
    """
    Insert-or-ignore each review by a stable key (author+text hash-ish key
    supplied by caller). This is how we build a longer effective review
    history than any single Places API call returns -- see google_places.py.
    """
    with get_conn() as conn:
        for r in reviews:
            conn.execute(
                """INSERT OR IGNORE INTO review_snapshots
                   (location_id, review_key, author_name, rating, publish_time,
                    review_text, is_mock, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (location_id, r["review_key"], r.get("author_name"), r.get("rating"),
                 r.get("publish_time"), r.get("review_text"), int(is_mock), _now()),
            )


def get_review_snapshots(location_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM review_snapshots WHERE location_id = ? ORDER BY publish_time DESC",
            (location_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Review insights (LLM-derived themes, tied to a specific audit run)
# ---------------------------------------------------------------------------

def save_review_insights(audit_id: str, themes: list[dict[str, Any]]) -> None:
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO review_insights
               (audit_id, theme, mention_count, example_snippet, linked_categories,
                linkage_confidence, linkage_note)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(audit_id, t["theme"], t["mention_count"], t.get("example_snippet"),
              json.dumps(t.get("linked_categories", [])), t["linkage_confidence"], t["linkage_note"])
             for t in themes],
        )


def get_review_insights(audit_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM review_insights WHERE audit_id = ?", (audit_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["linked_categories"] = json.loads(d["linked_categories"] or "[]")
            out.append(d)
        return out


# ---------------------------------------------------------------------------
# Audit trail (explainability log)
# ---------------------------------------------------------------------------

def log_audit_trail(audit_id: str, step_name: str, model_used: str, prompt: str, response: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO audit_trail (audit_id, step_name, model_used, prompt, response, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (audit_id, step_name, model_used, prompt, response, _now()),
        )


def get_audit_trail(audit_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_trail WHERE audit_id = ? ORDER BY id", (audit_id,)
        ).fetchall()
        return [dict(r) for r in rows]
