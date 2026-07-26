"""Training plan storage for the running coach.

A plan is a flat, dated list of sessions plus goal metadata. Claude produces the
sessions — either by reading a training document the athlete uploads, or by
interviewing them — and this module persists them, groups them into weeks, and
tracks how each session actually went so the plan can be adapted over time.

The original prescription is never overwritten: adaptations are recorded on the
session (status / actual / notes) alongside the planned target, so the coach can
see intent versus reality across a block.

Storage is a JSON file; set TRAINING_PLANS_FILE to put it on a mounted volume.
"""
import json
import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
PLANS_FILE = Path(
    os.environ.get("TRAINING_PLANS_FILE", PROJECT_ROOT / ".training_plans.json")
)

# Status values a session can take. "planned" is the default until the athlete
# reports back or the coach adapts it.
STATUSES = ("planned", "completed", "modified", "skipped")


def _load() -> dict:
    if not PLANS_FILE.exists():
        return {"active_plan_id": None, "plans": {}}
    try:
        data = json.loads(PLANS_FILE.read_text())
        data.setdefault("active_plan_id", None)
        data.setdefault("plans", {})
        return data
    except (json.JSONDecodeError, OSError):
        return {"active_plan_id": None, "plans": {}}


def _write(data: dict) -> None:
    PLANS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLANS_FILE.write_text(json.dumps(data, indent=2))


def _parse_date(value: str) -> str:
    """Normalise a date to ISO YYYY-MM-DD, raising a clear error if malformed."""
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValueError(f"Invalid date {value!r} — expected YYYY-MM-DD")


def _coerce_sessions(sessions) -> list[dict]:
    """Accept a list of dicts or a JSON string, and normalise each session."""
    if isinstance(sessions, str):
        sessions = json.loads(sessions)
    if not isinstance(sessions, list) or not sessions:
        raise ValueError("sessions must be a non-empty list")

    out = []
    for s in sessions:
        if not isinstance(s, dict):
            raise ValueError(f"each session must be an object, got {type(s).__name__}")
        if not s.get("date"):
            raise ValueError("each session needs a 'date' (YYYY-MM-DD)")
        out.append(
            {
                "date": _parse_date(s["date"]),
                "type": (s.get("type") or "run").strip(),
                "description": (s.get("description") or "").strip(),
                "distance_km": s.get("distance_km"),
                "intensity": s.get("intensity"),
                "status": "planned",
                "actual": None,
                "notes": None,
            }
        )
    out.sort(key=lambda s: s["date"])
    return out


def _week_index(session_date: str, start: str) -> int:
    """1-based training week containing session_date, counted from the plan start.

    Weeks run from the plan's first session (week 1 = days 0–6), not from the
    calendar Monday — so a block that starts mid-week still numbers its weeks the
    way a written training plan does, and an uploaded "Week 1" maps to week 1.
    """
    d0 = date.fromisoformat(start)
    d = date.fromisoformat(session_date)
    return ((d - d0).days // 7) + 1


def save_plan(
    name: str,
    goal: str,
    sessions,
    race_date: str | None = None,
    notes: str | None = None,
) -> dict:
    """Store a new plan and make it active. Returns a summary."""
    parsed = _coerce_sessions(sessions)
    start = parsed[0]["date"]
    end = parsed[-1]["date"]
    for s in parsed:
        s["week"] = _week_index(s["date"], start)

    plan = {
        "id": uuid.uuid4().hex[:8],
        "name": name.strip(),
        "goal": goal.strip(),
        "race_date": _parse_date(race_date) if race_date else None,
        "notes": (notes or "").strip() or None,
        "start_date": start,
        "end_date": end,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sessions": parsed,
    }

    data = _load()
    data["plans"][plan["id"]] = plan
    data["active_plan_id"] = plan["id"]
    _write(data)
    return summarise(plan)


def get_active() -> dict | None:
    data = _load()
    pid = data.get("active_plan_id")
    return data["plans"].get(pid) if pid else None


def summarise(plan: dict) -> dict:
    """Compact plan overview — week-by-week totals rather than every session."""
    weeks: dict[int, dict] = {}
    for s in plan["sessions"]:
        w = weeks.setdefault(
            s["week"], {"week": s["week"], "sessions": 0, "planned_km": 0.0, "done": 0}
        )
        w["sessions"] += 1
        if isinstance(s.get("distance_km"), (int, float)):
            w["planned_km"] += float(s["distance_km"])
        if s["status"] in ("completed", "modified"):
            w["done"] += 1

    return {
        "id": plan["id"],
        "name": plan["name"],
        "goal": plan["goal"],
        "race_date": plan["race_date"],
        "start_date": plan["start_date"],
        "end_date": plan["end_date"],
        "notes": plan.get("notes"),
        "total_weeks": max((s["week"] for s in plan["sessions"]), default=0),
        "total_sessions": len(plan["sessions"]),
        "weeks": [weeks[k] for k in sorted(weeks)],
    }


def get_week(plan: dict, week: int) -> list[dict]:
    return [s for s in plan["sessions"] if s["week"] == week]


def get_session_on(plan: dict, day: str) -> dict | None:
    return next((s for s in plan["sessions"] if s["date"] == day), None)


def update_session(
    day: str,
    status: str | None = None,
    actual: str | None = None,
    notes: str | None = None,
) -> dict:
    """Record how a session went, or how it was adapted. Preserves the original
    prescription — only status/actual/notes change."""
    day = _parse_date(day)
    if status and status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")

    data = _load()
    pid = data.get("active_plan_id")
    plan = data["plans"].get(pid) if pid else None
    if not plan:
        raise ValueError("No active training plan.")

    session = next((s for s in plan["sessions"] if s["date"] == day), None)
    if not session:
        raise ValueError(f"No session scheduled on {day}.")

    if status:
        session["status"] = status
    if actual is not None:
        session["actual"] = actual.strip() or None
    if notes is not None:
        session["notes"] = notes.strip() or None

    _write(data)
    return session


def list_plans() -> list[dict]:
    data = _load()
    active = data.get("active_plan_id")
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "goal": p["goal"],
            "race_date": p["race_date"],
            "start_date": p["start_date"],
            "end_date": p["end_date"],
            "active": p["id"] == active,
        }
        for p in data["plans"].values()
    ]


def set_active(plan_id: str) -> dict:
    data = _load()
    if plan_id not in data["plans"]:
        raise ValueError(f"No plan with id {plan_id}.")
    data["active_plan_id"] = plan_id
    _write(data)
    return summarise(data["plans"][plan_id])


def delete_plan(plan_id: str) -> None:
    data = _load()
    if plan_id not in data["plans"]:
        raise ValueError(f"No plan with id {plan_id}.")
    del data["plans"][plan_id]
    if data.get("active_plan_id") == plan_id:
        data["active_plan_id"] = next(iter(data["plans"]), None)
    _write(data)
