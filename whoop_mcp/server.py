"""WHOOP tools for the running-coach MCP server.

Tool functions are defined at module level and attached to a shared FastMCP
instance via register(mcp), so Strava and WHOOP tools can be served from a
single remote MCP server (see server.py).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from whoop_mcp.whoop_client import WhoopClient

_client: WhoopClient | None = None


def get_client() -> WhoopClient:
    global _client
    if _client is None:
        _client = WhoopClient()
    return _client


def _not_authed() -> str:
    return json.dumps({"error": "Whoop not authenticated. Run: python whoop_auth.py"})


def _is_authed() -> bool:
    from config import get_config
    cfg = get_config()
    return bool(cfg.whoop_access_token and cfg.whoop_refresh_token)


def get_whoop_profile() -> str:
    """Get the athlete's Whoop profile: first name, last name, email."""
    if not _is_authed():
        return _not_authed()
    try:
        return json.dumps(get_client().get_profile())
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_whoop_recovery(days: int = 7) -> str:
    """Get the athlete's recent Whoop recovery scores.

    Returns up to `days` days of recovery data, most recent first. Each record includes:
    - recovery_score: 0–100, overall readiness to perform
    - resting_heart_rate: bpm
    - hrv_rmssd_milli: HRV in milliseconds — key indicator of nervous system recovery
    - spo2_percentage: blood oxygen saturation
    - skin_temp_celsius: skin temperature
    - score_state: SCORED | PENDING_SLEEP | INCOMPLETE

    Use this to assess whether the athlete is ready for a hard workout or needs more rest.
    A recovery score below 33 (red) suggests recovery; 34–66 (yellow) moderate effort;
    67–100 (green) optimal for hard training."""
    if not _is_authed():
        return _not_authed()
    try:
        data = get_client().get_recovery(days=days)
        records = data.get("records", [])
        cleaned = []
        for r in records:
            score = r.get("score") or {}
            cleaned.append({
                "cycle_id": r.get("cycle_id"),
                "sleep_id": r.get("sleep_id"),
                "created_at": r.get("created_at"),
                "score_state": r.get("score_state"),
                "recovery_score": score.get("recovery_score"),
                "resting_heart_rate": score.get("resting_heart_rate"),
                "hrv_rmssd_milli": score.get("hrv_rmssd_milli"),
                "spo2_percentage": score.get("spo2_percentage"),
                "skin_temp_celsius": score.get("skin_temp_celsius"),
            })
        return json.dumps(cleaned)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_whoop_sleep(days: int = 7) -> str:
    """Get the athlete's recent Whoop sleep data.

    Returns up to `days` nights of sleep data, most recent first. Each record includes:
    - start / end: ISO 8601 timestamps
    - nap: true if this is a nap rather than main sleep
    - sleep_performance_percentage: 0–100, overall sleep quality
    - sleep_efficiency_percentage: time asleep / time in bed
    - sleep_consistency_percentage: regularity of sleep timing
    - respiratory_rate: breaths per minute (elevated = stress/illness signal)
    - stage_summary: time (ms) in light, slow-wave (deep), REM, and awake stages
    - sleep_needed.baseline_milli: optimal sleep need in ms

    Deep sleep and REM are the most restorative stages. Use this alongside recovery
    to understand if poor recovery is sleep-related."""
    if not _is_authed():
        return _not_authed()
    try:
        data = get_client().get_sleep(days=days)
        records = data.get("records", [])
        cleaned = []
        for r in records:
            score = r.get("score") or {}
            stages = score.get("stage_summary") or {}
            needed = score.get("sleep_needed") or {}
            cleaned.append({
                "id": r.get("id"),
                "start": r.get("start"),
                "end": r.get("end"),
                "nap": r.get("nap"),
                "score_state": r.get("score_state"),
                "sleep_performance_percentage": score.get("sleep_performance_percentage"),
                "sleep_efficiency_percentage": score.get("sleep_efficiency_percentage"),
                "sleep_consistency_percentage": score.get("sleep_consistency_percentage"),
                "respiratory_rate": score.get("respiratory_rate"),
                "stage_summary": {
                    "total_in_bed_time_milli": stages.get("total_in_bed_time_milli"),
                    "total_awake_time_milli": stages.get("total_awake_time_milli"),
                    "total_light_sleep_time_milli": stages.get("total_light_sleep_time_milli"),
                    "total_slow_wave_sleep_time_milli": stages.get("total_slow_wave_sleep_time_milli"),
                    "total_rem_sleep_time_milli": stages.get("total_rem_sleep_time_milli"),
                    "disturbance_count": stages.get("disturbance_count"),
                },
                "sleep_needed_baseline_milli": needed.get("baseline_milli"),
            })
        return json.dumps(cleaned)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_whoop_strain(days: int = 7) -> str:
    """Get the athlete's recent Whoop daily strain scores from physiological cycles.

    Returns up to `days` days of cycle data, most recent first. Each record includes:
    - start / end: ISO 8601 timestamps for the cycle day
    - strain: 0–21 cardiovascular strain score for the day
    - kilojoule: total energy expenditure
    - average_heart_rate / max_heart_rate: bpm

    Strain measures cumulative cardiovascular load. High strain days (>14) paired
    with low recovery scores signal overtraining risk.
    Use alongside recovery data to spot trends in training load vs. readiness."""
    if not _is_authed():
        return _not_authed()
    try:
        data = get_client().get_cycles(days=days)
        records = data.get("records", [])
        cleaned = []
        for r in records:
            score = r.get("score") or {}
            cleaned.append({
                "id": r.get("id"),
                "start": r.get("start"),
                "end": r.get("end"),
                "score_state": r.get("score_state"),
                "strain": score.get("strain"),
                "kilojoule": score.get("kilojoule"),
                "average_heart_rate": score.get("average_heart_rate"),
                "max_heart_rate": score.get("max_heart_rate"),
            })
        return json.dumps(cleaned)
    except Exception as e:
        return json.dumps({"error": str(e)})


_TOOLS = (
    get_whoop_profile,
    get_whoop_recovery,
    get_whoop_sleep,
    get_whoop_strain,
)


def register(mcp: FastMCP) -> None:
    """Attach all WHOOP tools to the given FastMCP instance."""
    for fn in _TOOLS:
        mcp.tool()(fn)
