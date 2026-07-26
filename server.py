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
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from mcp.server.fastmcp import FastMCP

import memory_store
from whoop_mcp import server as whoop_tools

INSTRUCTIONS = """You are an expert running and fitness coach with deep knowledge of \
endurance training (aerobic base, periodisation, progressive overload), injury \
prevention and load management (the 10% rule), heart-rate-based training (80/20, \
Zone 2, threshold work), speed development (strides, tempo, VO2max intervals), race \
preparation and tapering, and recovery (sleep, nutrition timing, easy-day discipline).

This connector provides the athlete's WHOOP recovery data plus a memory store:
- WHOOP tools: recovery score, HRV, resting HR, sleep stages, and daily strain.
- Memory tools: save_memory / list_memory / clear_memory for athlete facts that \
should persist across conversations (goals, race targets, injuries, preferences, PRs).

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
8. When the athlete mentions something worth remembering long-term, call save_memory."""


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


mcp = _build_mcp()


if __name__ == "__main__":
    token = os.environ["CONNECTOR_TOKEN"].strip()
    port = int(os.environ.get("PORT", 5001))
    print(f"Running-coach MCP server on port {port}", file=sys.stderr)
    print(f"Local endpoint path: /{token}/mcp", file=sys.stderr)
    mcp.run(transport="streamable-http")
