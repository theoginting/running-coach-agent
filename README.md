# Running Coach Agent

> Reads your recovery every morning and tells you exactly what to train today.

An autonomous coaching agent that turns live recovery and activity data into a daily training decision. It pulls **WHOOP** recovery and **Strava** activity through **MCP (Model Context Protocol)**, decides the day's training load, generates a coaching briefing, and schedules a follow-up reminder for the session.

Built as a personal project using an agentic development workflow (Claude Code), and used to drive a real training block ahead of a Half Dome summit.

## What it does

- **Pulls live data** — WHOOP recovery score and the latest Strava activity, each morning, via MCP tools (with retry / re-auth handling on token errors).
- **Decides the load** — a recovery-driven rules engine maps today's readiness to an adjusted session instead of a fixed plan:
  - **Green (67+):** full session
  - **Yellow (34–66):** volume capped ~70%, intensity held
  - **Red (≤33):** recovery day, mobility and walk only
- **Generates a briefing** — a readable daily summary with the recovery zone, target volume, last activity, and the exact session to run.
- **Schedules a reminder** — writes an ISO-8601 reminder for the session with context in the notes, so the day's plan surfaces at the right time.

## How it works

```
06:30 trigger  →  pull WHOOP + Strava (MCP)  →  decide load  →  render briefing  →  schedule reminder
```

The core decision lives in a small, testable load engine that takes a recovery score and the planned session, and returns an adjusted `LoadDecision` (zone, volume %, message). Everything downstream, the briefing and the reminder, reads from that single decision.

## Tech

| Area | Detail |
|------|--------|
| Language | Python |
| Integrations | WHOOP API, Strava API (via MCP) |
| Automation | Daily scheduled run + ISO-8601 reminder creation |
| Build workflow | Agentic (Claude Code) |

## Repo contents

- `running_coach_work_sample.html` — a one-page work sample showing the load-decision code, a generated daily briefing, and the scheduling/automation payload. Open it in a browser, or rename to `index.html` and enable GitHub Pages to host it as a live page.

## What I'd build next

The recovery-to-load engine is deliberately source-agnostic, so the natural next step is widening the inputs it reasons over:

- **Garmin integration** — pull training load, VO2 estimates, and HRV alongside WHOOP so the load decision isn't dependent on a single wearable.
- **Sleep as a first-class signal** — sleep duration relative to individual need was consistently the real limiter, so promote it from a note in the briefing to a weighted input in the decision itself.
- **Nutrition context** — fold in fueling and hydration data to flag days where under-recovery is a nutrition problem, not a training one.
- **Unified readiness score** — blend the signals above into a single readiness number the load engine reads from, so adding a new data source is a config change, not a rewrite.

## Notes

This is a personal project. Data integrations run against my own WHOOP and Strava accounts; no credentials or personal data are committed to this repo.
