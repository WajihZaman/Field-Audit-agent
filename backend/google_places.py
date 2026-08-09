"""
google_places.py
=================
Thin client around the Places API (New) for pulling a location's recent
public reviews, plus a persistent "snapshot" cache and a clearly-labeled
mock fallback for demoing without live credentials.

--- The constraint the assessment explicitly calls out ---
The Places API only ever returns a handful (Google caps this at 5) of the
"most relevant" or "most recent" reviews per Place Details call -- there is
no way to page through a location's full review history via the API. A
naive implementation would therefore only ever see a tiny, possibly
non-representative slice of feedback, and would forget everything it saw
the previous week.

Design response, implemented below:
  1. Every audit run fetches the current top reviews and UPSERTS them into
     a local `review_snapshots` table, keyed by a stable hash of
     (author, review text). Duplicate reviews across repeated fetches are
     silently ignored; genuinely new reviews accumulate.
  2. Over weeks/months of recurring audits, this snapshot table becomes a
     longer effective review history than any single API call could give
     us -- without needing a paid, higher-tier review-history product.
  3. We always filter down to "last ~3 months" using whatever publish
     timestamps we have, from the accumulated snapshot table, not just the
     latest fetch.
  4. The mock data path (used automatically when GOOGLE_MAPS_API_KEY is
     unset) is clearly flagged everywhere it surfaces -- in the DB
     (`is_mock` column), the API response (`reviews_are_mocked`), and the
     UI -- so nobody mistakes demo data for a real signal.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend import db
from backend.config import settings

FIELD_MASK = "id,displayName,reviews,rating,userRatingCount"


def _review_key(author: str, text: str) -> str:
    raw = f"{author}::{text}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:24]


async def resolve_place_id(name: str, address: str) -> str | None:
    """Resolve a place_id from a name/address via Text Search (New)."""
    if not settings.google_maps_api_key:
        return None
    url = f"{settings.google_places_base_url}/places:searchText"
    headers = {
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json={"textQuery": f"{name} {address}"})
        resp.raise_for_status()
        data = resp.json()
    places = data.get("places", [])
    return places[0]["id"] if places else None


async def _fetch_live_reviews(place_id: str) -> list[dict[str, Any]]:
    url = f"{settings.google_places_base_url}/places/{place_id}"
    headers = {
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    out = []
    for r in data.get("reviews", []):
        author = (r.get("authorAttribution") or {}).get("displayName", "Anonymous")
        text = (r.get("text") or {}).get("text", "")
        out.append(
            {
                "review_key": _review_key(author, text),
                "author_name": author,
                "rating": r.get("rating"),
                "publish_time": r.get("publishTime"),
                "review_text": text,
            }
        )
    return out


def _mock_reviews() -> list[dict[str, Any]]:
    """
    Synthetic, clearly-fictional review data for demo purposes only, shaped
    like what a golf-club listing's recent reviews might look like. This is
    NOT scraped or copied real review text -- it exists purely so the POC
    is fully runnable end-to-end without a Google Maps API key.

    Themes are deliberately written so at least some plausibly connect to
    a golf-course audit checklist (pace of play, restroom cleanliness,
    cart-path condition) to demonstrate the review-correlation step.
    """
    now = datetime.now(timezone.utc)
    raw = [
        (5, 60, "Course conditions were fantastic and the staff at check-in were friendly and quick."),
        (2, 20, "Waited almost five hours for 18 holes, group in front of us was never managed by a ranger."),
        (4, 45, "Great layout and challenging back nine. Pro shop staff were helpful."),
        (1, 10, "Restrooms near the turn were out of paper towels and pretty dirty by early afternoon."),
        (3, 75, "Cart paths near hole 7 are cracked and rough, could use repaving."),
        (2, 15, "Slow pace of play again, no marshal in sight the entire back nine."),
        (5, 5, "Beautiful views and the grill had a solid turkey sandwich after the round."),
        (2, 30, "Bunkers were in rough shape, sand was thin and hard in several spots."),
    ]
    out = []
    for rating, days_ago, text in raw:
        author = f"Guest{abs(hash(text)) % 9999}"
        publish_time = (now - timedelta(days=days_ago)).isoformat()
        out.append(
            {
                "review_key": _review_key(author, text),
                "author_name": author,
                "rating": rating,
                "publish_time": publish_time,
                "review_text": text,
            }
        )
    return out


async def get_recent_reviews(location_id: int, place_name: str, address: str,
                              place_id: str | None) -> tuple[list[dict[str, Any]], bool]:
    """
    Fetch (live or mock), cache into review_snapshots, then return the
    accumulated set of reviews from the last ~3 months for this location.

    Returns (reviews, is_mock).
    """
    is_mock = settings.reviews_are_mocked

    if is_mock:
        fresh = _mock_reviews()
    else:
        if not place_id:
            resolved = await resolve_place_id(place_name, address)
            if resolved:
                db.set_location_place_id(location_id, resolved)
                place_id = resolved
        fresh = await _fetch_live_reviews(place_id) if place_id else []

    db.upsert_review_snapshots(location_id, fresh, is_mock=is_mock)

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    accumulated = db.get_review_snapshots(location_id)

    def _in_window(r: dict[str, Any]) -> bool:
        pt = r.get("publish_time")
        if not pt:
            return True  # keep undated reviews rather than silently dropping them
        try:
            dt = datetime.fromisoformat(pt.replace("Z", "+00:00"))
        except ValueError:
            return True
        return dt >= cutoff

    recent = [r for r in accumulated if _in_window(r)]
    return recent, is_mock
