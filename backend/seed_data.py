"""
seed_data.py
============
Seeds one demo location -- Wolf Creek Golf Club, the real BroadPeak
portfolio property named in the assessment brief -- plus a small set of
brand standards tailored to a golf & hospitality property rather than a
generic retail checklist.

Note on the checklist categories: a golf club audit looks quite different
from, say, a fast-casual restaurant audit (BroadPeak's Roti brand) or a
gifting-franchise storefront (Edible Arrangements). Rather than force one
generic "franchise checklist" onto every brand, this file demonstrates the
intended pattern: each brand gets its own tailored categories and standards
text in the RAG store, and `audit_service.py` looks up only what's relevant
to the categories present in a given audit -- no code change needed to
onboard a new brand, just new rows here (or, in production, a standards
CMS).

Run standalone with `python -m backend.seed_data`, or it's called
automatically on backend startup (idempotent -- safe to re-run).
"""

from __future__ import annotations

from backend import db, rag

WOLF_CREEK_BRAND = "Wolf Creek Golf Club"

WOLF_CREEK_LOCATION = {
    "name": "Wolf Creek Golf Club",
    "brand": WOLF_CREEK_BRAND,
    "address": "3000 Union Rd SW, Atlanta, GA 30331",
    # place_id intentionally left None -- resolved lazily via Text Search
    # the first time a real Google Maps API key is configured.
    "place_id": None,
}

WOLF_CREEK_STANDARDS = [
    {
        "category": "Course Conditions",
        "text": (
            "Greens must be mowed and rolled to a consistent stimp speed with no visible scalping. "
            "Bunkers must have evenly raked, adequately depthed sand with no standing water or bare "
            "patches. Cart paths must be free of major cracking, potholes, or trip hazards. Tee boxes "
            "and fairways must show consistent turf health with no large dead or bare zones."
        ),
    },
    {
        "category": "Clubhouse & Facility Cleanliness",
        "text": (
            "Restrooms (clubhouse and on-course) must be stocked with soap, paper towels/dryers, and "
            "toilet paper at all times, and visibly cleaned/inspected at least every 2 hours during "
            "operating hours. Locker rooms must be free of trash, standing water, and mildew odor. "
            "Pro shop and clubhouse common areas must be swept/vacuumed and free of clutter."
        ),
    },
    {
        "category": "Safety & Risk",
        "text": (
            "Lightning detection protocol must be posted and staff trained on horn signals and shelter "
            "locations. Cart paths and crossing points near roads must have clear signage. Golf carts "
            "must pass a daily safety check (brakes, seatbelts if equipped) before being released to "
            "guests. Hazard areas (water, steep drop-offs) must be marked per brand signage standards."
        ),
    },
    {
        "category": "Guest Service & Staff Standards",
        "text": (
            "Pace of play must be actively managed by a marshal/ranger during peak hours; groups "
            "falling more than 15 minutes behind pace must be proactively assisted. Staff must be in "
            "brand uniform, greet guests within 30 seconds of arrival at check-in, and communicate any "
            "pace-of-play or course-condition issues transparently rather than let guests discover them."
        ),
    },
    {
        "category": "Brand & Signage Compliance",
        "text": (
            "All exterior and interior signage must use current brand logo, colors, and approved "
            "wayfinding templates. Outdated or damaged signage must be replaced, not patched. Scorecards "
            "and printed materials must reflect the current brand template version."
        ),
    },
    {
        "category": "Food & Beverage Operations",
        "text": (
            "Halfway house and grill service must follow standard food-safety holding temperatures and "
            "visible date-labeling on prepped items. Beverage cart service must run at the frequency "
            "specified for the day's expected play volume. Menu pricing and offerings displayed must "
            "match the current approved brand menu."
        ),
    },
]


def seed_all() -> int:
    """Idempotent seed. Returns the location_id."""
    db.init_db()
    location_id = db.upsert_location(
        name=WOLF_CREEK_LOCATION["name"],
        brand=WOLF_CREEK_LOCATION["brand"],
        address=WOLF_CREEK_LOCATION["address"],
        place_id=WOLF_CREEK_LOCATION["place_id"],
    )
    rag.add_standards(WOLF_CREEK_BRAND, WOLF_CREEK_STANDARDS)
    return location_id


if __name__ == "__main__":
    loc_id = seed_all()
    print(f"Seeded Wolf Creek Golf Club as location_id={loc_id}")
