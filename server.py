"""Running-coach remote MCP server.

Exposes WHOOP data and a small memory store as MCP tools over Streamable HTTP,
so the Claude apps (iOS / Android / desktop / web) can connect to it as a custom
connector. Strava is provided separately by Strava's own official MCP connector.

Access is gated by a secret token embedded in the URL path: the server only
mounts the MCP endpoint at /<CONNECTOR_TOKEN>/mcp, so the full connector URL is

    https://<your-host>/<CONNECTOR_TOKEN>/mcp

Run locally:
    python server.py
    # then expose it publicly, e.g.:  ngrok http 5001

Deploy: see README. Railway sets $PORT automatically.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from mcp.server.fastmcp import FastMCP

import memory_store
import training_plan
from whoop_mcp import server as whoop_tools

INSTRUCTIONS = """You are an expert running and fitness coach with deep knowledge of \
endurance training (aerobic base, periodisation, progressive overload), injury \
prevention and load management (the 10% rule), heart-rate-based training (80/20, \
Zone 2, threshold work), speed development (strides, tempo, VO2max intervals), race \
preparation and tapering, and recovery (sleep, nutrition timing, easy-day discipline).

This connector provides the athlete's WHOOP recovery data, a memory store, and \
their training plan:
- WHOOP tools: recovery score, HRV, resting HR, sleep stages, and daily strain.
- Memory tools: save_memory / list_memory / clear_memory for athlete facts that \
should persist across conversations (goals, race targets, injuries, preferences, PRs).
- Training plan tools: save_training_plan, get_training_plan, get_todays_session, \
update_session, list_training_plans, set_active_plan, delete_training_plan.

The athlete's running/training history comes from the separate Strava connector \
(activities, splits, pace, heart rate). Use both together: cross-reference Strava \
training load against WHOOP recovery and sleep.

How to coach:
1. Fetch the relevant data FIRST — give data-driven advice, not generic advice.
2. Be specific: reference actual runs, dates, distances, and paces from Strava.
3. Look at recent trends (last 4–8 weeks), and cross-reference Strava load against \
WHOOP recovery/sleep before recommending hard sessions.
4. Flag injury/overtraining risk proactively: volume spikes, too many hard days, \
low recovery paired with high strain, declining pace at rising HR.
5. Apply the 10% rule; build speed only on a solid aerobic base; keep ~80% of runs easy.
6. Give concrete workout targets (e.g. "6×800m at 4:10/km, 90s rest").
7. Use the athlete's measurement preference (metric/imperial).
8. When the athlete mentions something worth remembering long-term, call save_memory.

Building a training plan — two intake paths:
A. The athlete uploads or pastes an existing plan (a training document, spreadsheet \
text, or notes). Read it, convert it into dated sessions, confirm your reading of \
anything ambiguous (start date, race date, units), then call save_training_plan.
B. No plan yet — interview them. Ask about: goal event and date, current weekly \
volume and longest recent run, days per week available and which days, recent PRs, \
injury history and niggles, and terrain/equipment constraints. Check Strava for \
actual current fitness rather than trusting recall, and check memory for known facts. \
Then build the block and call save_training_plan.
When generating sessions, give every session a concrete date so the plan is calendar-\
anchored, and include easy/recovery and rest days explicitly — not just the hard ones.

Adapting the plan:
- For "what should I run today", call get_todays_session, then check WHOOP recovery \
and recent Strava load before confirming or adjusting it.
- Adjust the DAY when recovery/sleep/strain disagree with the prescription: low \
recovery (<34) or poor sleep means cut intensity or swap to easy/rest; strong \
recovery (>67) means the session can proceed as written or slightly harder.
- Adjust the BLOCK when a pattern emerges over 1–2 weeks (repeatedly missed sessions, \
sustained low recovery, rising resting HR, or fitness ahead of schedule). Explain the \
reasoning, then save a revised plan.
- After a session is done or changed, call update_session to record status, what was \
actually done, and why. This history is what makes later adaptation informed — the \
original prescription is preserved alongside it."""


def _build_mcp() -> FastMCP:
    token = os.environ.get("CONNECTOR_TOKEN", "").strip()
    if not token:
        sys.exit(
            "CONNECTOR_TOKEN is not set. Add a long random secret to .env — it gates "
            "access to your data and forms part of the connector URL "
            "(https://<host>/<CONNECTOR_TOKEN>/mcp)."
        )

    port = int(os.environ.get("PORT", 5001))
    mcp = FastMCP(
        "running-coach",
        instructions=INSTRUCTIONS,
        host="0.0.0.0",
        port=port,
        # Mount the MCP endpoint behind the secret token so only requests that
        # know the token can reach it.
        streamable_http_path=f"/{token}/mcp",
        # Stateless is simpler and more robust for a remote, single-user connector.
        stateless_http=True,
    )

    whoop_tools.register(mcp)
    _register_memory(mcp)
    _register_training_plan(mcp)
    return mcp


def _register_memory(mcp: FastMCP) -> None:
    @mcp.tool()
    def save_memory(fact: str) -> str:
        """Save an important, athlete-specific fact to long-term memory so it
        persists across conversations: goals, race targets, injury history,
        training preferences, schedule constraints, personal bests, or
        measurement preference. Do not save generic training advice."""
        return json.dumps({"facts": memory_store.save_fact(fact)})

    @mcp.tool()
    def list_memory() -> str:
        """List everything currently remembered about the athlete."""
        return json.dumps({"facts": memory_store.list_facts()})

    @mcp.tool()
    def clear_memory() -> str:
        """Forget all stored facts about the athlete."""
        memory_store.clear()
        return json.dumps({"facts": []})


def _register_training_plan(mcp: FastMCP) -> None:
    @mcp.tool()
    def save_training_plan(
        name: str,
        goal: str,
        sessions: list,
        race_date: str = "",
        notes: str = "",
    ) -> str:
        """Save a training block and make it the active plan. Use this after
        reading a training plan the athlete provided, or after interviewing them
        to build one.

        `sessions` is a list of objects, one per training day, each with:
          date (required, "YYYY-MM-DD"), type (e.g. easy/long/tempo/intervals/rest/
          cross), description (the prescription, e.g. "6x800m @ 4:10/km, 90s rest"),
          distance_km (number, optional), intensity (easy/moderate/hard, optional).
        Include rest and recovery days explicitly. Week numbers are derived from
        the dates. Saving a new plan does not delete previous ones."""
        try:
            return json.dumps(
                training_plan.save_plan(
                    name=name,
                    goal=goal,
                    sessions=sessions,
                    race_date=race_date or None,
                    notes=notes or None,
                )
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def get_training_plan(week: int = 0) -> str:
        """Get the active training plan. By default returns a week-by-week
        overview (goal, race date, weekly session counts and volume). Pass a week
        number to get every session in that week with its status and any recorded
        adaptation."""
        plan = training_plan.get_active()
        if not plan:
            return json.dumps(
                {"error": "No active training plan. Create one with save_training_plan."}
            )
        if week:
            sessions = training_plan.get_week(plan, week)
            if not sessions:
                return json.dumps({"error": f"Plan has no week {week}."})
            return json.dumps({"plan": plan["name"], "week": week, "sessions": sessions})
        return json.dumps(training_plan.summarise(plan))

    @mcp.tool()
    def get_todays_session(day: str = "") -> str:
        """Get the session scheduled for today (or for `day`, "YYYY-MM-DD") from
        the active plan, with the surrounding week for context. Check WHOOP
        recovery and recent Strava load before confirming or adjusting it."""
        plan = training_plan.get_active()
        if not plan:
            return json.dumps(
                {"error": "No active training plan. Create one with save_training_plan."}
            )
        target = day.strip() or date.today().isoformat()
        session = training_plan.get_session_on(plan, target)
        if not session:
            return json.dumps(
                {
                    "date": target,
                    "session": None,
                    "note": "Nothing scheduled on this date (rest day or outside the block).",
                    "plan": plan["name"],
                    "race_date": plan["race_date"],
                }
            )
        return json.dumps(
            {
                "date": target,
                "plan": plan["name"],
                "goal": plan["goal"],
                "race_date": plan["race_date"],
                "session": session,
                "week": training_plan.get_week(plan, session["week"]),
            }
        )

    @mcp.tool()
    def update_session(
        day: str,
        status: str = "",
        actual: str = "",
        notes: str = "",
    ) -> str:
        """Record how a session went or how it was adapted, on the active plan.

        status: planned | completed | modified | skipped
        actual: what was actually done (e.g. "5km easy instead of intervals")
        notes: why it changed (e.g. "WHOOP recovery 28, resting HR up 6bpm")
        The original prescription is preserved — this only annotates it."""
        try:
            return json.dumps(
                training_plan.update_session(
                    day=day,
                    status=status or None,
                    actual=actual or None,
                    notes=notes or None,
                )
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def list_training_plans() -> str:
        """List all stored training plans and show which one is active."""
        return json.dumps({"plans": training_plan.list_plans()})

    @mcp.tool()
    def set_active_plan(plan_id: str) -> str:
        """Switch the active training plan by its id (see list_training_plans)."""
        try:
            return json.dumps(training_plan.set_active(plan_id))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def delete_training_plan(plan_id: str) -> str:
        """Permanently delete a stored training plan by its id."""
        try:
            training_plan.delete_plan(plan_id)
            return json.dumps({"deleted": plan_id, "plans": training_plan.list_plans()})
        except Exception as e:
            return json.dumps({"error": str(e)})


mcp = _build_mcp()


if __name__ == "__main__":
    token = os.environ["CONNECTOR_TOKEN"].strip()
    port = int(os.environ.get("PORT", 5001))
    print(f"Running-coach MCP server on port {port}", file=sys.stderr)
    print(f"Local endpoint path: /{token}/mcp", file=sys.stderr)
    mcp.run(transport="streamable-http")
