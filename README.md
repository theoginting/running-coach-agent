# Running Coach (Claude connector)

An AI running coach you use from the **Claude app** (iOS, Android, desktop, web).
It combines two connectors in one conversation:

- **Strava** — via Strava's own [official MCP connector](https://support.strava.com/hc/en-us/articles/46190267796237-Strava-MCP-Connector) (activities, splits, pace, HR). Requires a Strava subscription.
- **Running Coach** (this project) — a small remote MCP server that adds your **WHOOP** recovery/sleep/strain data, a **memory** store, and the **coaching instructions** that tie it all together.

Claude talks to both connectors at once, so it can cross-reference your Strava
training load against your WHOOP recovery when it coaches you.

## Architecture

```
server.py                    ← remote MCP server (Streamable HTTP)
whoop_mcp/server.py          ← WHOOP tools   (register on the shared FastMCP)
whoop_mcp/whoop_client.py    ← WHOOP API v2 client + token refresh
memory_store.py              ← single-user fact memory (JSON file)
config.py                    ← WHOOP credentials + token management
whoop_auth.py                ← one-time WHOOP OAuth flow
```

Access is gated by a secret token in the URL path, so the connector URL is:

```
https://<your-host>/<CONNECTOR_TOKEN>/mcp
```

> Strava is **not** part of this server — it's a separate connector you add
> directly in the Claude app (see below).

## Tools this server exposes

| Tool | Description |
|---|---|
| `get_whoop_profile` | WHOOP profile |
| `get_whoop_recovery` | Recovery score, HRV, resting HR |
| `get_whoop_sleep` | Sleep stages, performance, efficiency |
| `get_whoop_strain` | Daily strain, energy, heart rate |
| `save_memory` / `list_memory` / `clear_memory` | Persist athlete facts across chats |
| `save_training_plan` | Store a dated training block and make it active |
| `get_training_plan` | Week-by-week overview, or every session in one week |
| `get_todays_session` | Today's prescribed session plus its week for context |
| `update_session` | Record how a session went, or how it was adapted |
| `list_training_plans` / `set_active_plan` / `delete_training_plan` | Manage stored blocks |

> WHOOP uses **API v2** (`/developer/v2/…`). The v1 API is no longer supported.

## Training plans

The server stores the plan; Claude does the reading, interviewing, and adapting.

**Two ways to start a block:**

1. **Bring an existing plan.** Upload or paste your training document in the Claude
   app ("here's my 12-week block, load it"). Claude reads it, converts it into dated
   sessions, confirms anything ambiguous (start date, units, race date), and saves it.
2. **Get interviewed.** Ask Claude to build one ("I want to break 1:35 for a half in
   October"). It asks about your goal and date, current volume, available days,
   injury history and constraints — cross-checking your real Strava history rather
   than relying on recall — then saves the block.

**Daily use.** Ask "what should I run today?". Claude pulls the prescribed session,
checks WHOOP recovery/sleep/strain and recent Strava load, and either confirms it or
adjusts it — cutting intensity on a low-recovery day, or greenlighting the hard
session when you're ready for it. Afterwards it records what you actually did with
`update_session`.

**Block-level adaptation.** When a pattern emerges over a week or two — repeatedly
missed sessions, sustained low recovery, rising resting HR, or fitness running ahead
of schedule — Claude explains the reasoning and saves a revised block. Previous plans
are kept, so you can compare or roll back.

Sessions keep the original prescription alongside `status` (`planned` / `completed` /
`modified` / `skipped`), what was actually done, and why — so adaptation decisions are
informed by real history, not just the current day's numbers.

Weeks are counted from the plan's first session (week 1 = days 0–6), so a block that
starts mid-week still numbers its weeks the way a written plan does.

## Prerequisites

- Python 3.11+
- A [WHOOP account](https://www.whoop.com) + developer app
- A **Strava subscription** (for Strava's official connector)
- The Claude app on a plan that supports custom connectors (Free = 1, Pro, Max, Team, Enterprise)
- A way to expose this server over public HTTPS (Fly.io for production, ngrok for testing)

## Setup

### 1. Install

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Connector secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put it in `.env` as `CONNECTOR_TOKEN`. Treat it like a password — it gates access to your data.

### 3. WHOOP app + auth

1. Create an app at [developer.whoop.com](https://developer.whoop.com/); set the redirect URI to exactly `http://localhost:8283/callback`.
2. Put `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` in `.env`.
3. Run `python whoop_auth.py` → completes OAuth, writes `.whoop_tokens.json`.

### 4. Run the server

```bash
python server.py
```

It listens on `PORT` (default 5001) at `/<CONNECTOR_TOKEN>/mcp`.

## Connecting from the Claude app

The Claude app reaches your server through Anthropic's backend, so it needs a
**public HTTPS URL** — `localhost` won't work.

### Add the Strava connector (official)

Follow Strava's guide: **Claude app → Settings → Connectors → add the Strava
connector → authorize with OAuth**. See
[Strava's help article](https://support.strava.com/hc/en-us/articles/46190267796237-Strava-MCP-Connector).

### Add the Running Coach connector (this server)

Expose the server, then in the Claude app: **Settings → Connectors → Add custom
connector**, and enter `https://<host>/<CONNECTOR_TOKEN>/mcp`. Leave OAuth fields
blank — the token in the URL is the auth.

**Quick test with ngrok:**

```bash
python server.py
ngrok http 5001
```

(Free ngrok URLs change on restart unless you have a reserved domain.)

### Production with Fly.io

Fly runs the server always-on with a stable HTTPS URL. A `shared-cpu-1x` / 256 MB
machine costs roughly **$2/month** (Fly no longer has a free tier for new accounts).

```bash
brew install flyctl
fly auth login
fly launch --no-deploy --copy-config   # uses the committed fly.toml
fly volumes create coach_data --size 1 --region sjc   # persists rotated tokens
```

Set secrets (these are not in the image — `.env` is excluded by `.dockerignore`):

```bash
fly secrets set \
  CONNECTOR_TOKEN="<your-secret>" \
  WHOOP_CLIENT_ID="<id>" \
  WHOOP_CLIENT_SECRET="<secret>" \
  WHOOP_ACCESS_TOKEN="<from .whoop_tokens.json>" \
  WHOOP_REFRESH_TOKEN="<from .whoop_tokens.json>" \
  WHOOP_TOKEN_EXPIRES_AT="<from .whoop_tokens.json>"
```

Then deploy and use the resulting URL as your connector:

```bash
fly deploy
```

```
https://<app-name>.fly.dev/<CONNECTOR_TOKEN>/mcp
```

`fly.toml` mounts a volume at `/data` and points `WHOOP_TOKENS_FILE` and
`MEMORY_FILE` there, so rotated WHOOP refresh tokens and saved memory survive
restarts and redeploys. `auto_stop_machines` is disabled so the connector never
hits a cold start.

### Alternative: Railway

A `Procfile` (`web: python server.py`) is included if you prefer Railway. Set the
same environment variables there. Note that Railway's filesystem is ephemeral, so
attach a volume and point `WHOOP_TOKENS_FILE` / `MEMORY_FILE` at it — otherwise
rotated WHOOP tokens are lost on every redeploy.

## Current deployment

The live instance runs on Fly.io:

| Setting | Value |
|---|---|
| App | `running-coach-mcp` |
| Host | `running-coach-mcp.fly.dev` |
| Region | `sjc` (San Jose) |
| Machine | `shared-cpu-1x`, 256 MB, always-on |
| Volume | `coach_data`, 1 GB, mounted at `/data` |
| Connector URL | `https://running-coach-mcp.fly.dev/<CONNECTOR_TOKEN>/mcp` |
| Cost | ~$2/month (machine) + ~$0.15/month (volume) |

Secrets are set with `fly secrets set` (never committed): `CONNECTOR_TOKEN`,
`WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, `WHOOP_ACCESS_TOKEN`,
`WHOOP_REFRESH_TOKEN`, `WHOOP_TOKEN_EXPIRES_AT`.

## Operations

```bash
fly status                 # is the machine running?
fly logs                   # live logs
fly deploy                 # ship code changes
fly secrets list           # names only, never values
fly machine restart <id>   # bounce the app
```

Health check — a wrong path must 404 and the real path must return `serverInfo`:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  https://running-coach-mcp.fly.dev/wrong/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"c","version":"1"}}}'
```

### Re-authenticating WHOOP

If the refresh token is ever revoked or expires, re-run the local OAuth flow and
push the new tokens up:

```bash
python whoop_auth.py       # writes .whoop_tokens.json
fly secrets set \
  WHOOP_ACCESS_TOKEN="..." WHOOP_REFRESH_TOKEN="..." WHOOP_TOKEN_EXPIRES_AT="..."
```

### Rotating the connector token

Generate a new `CONNECTOR_TOKEN`, run `fly secrets set CONNECTOR_TOKEN="..."`,
then update the connector URL in the Claude app — the path changes with the token.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Claude says WHOOP auth expired, refresh fails with **400** | WHOOP refresh tokens are **single-use and rotate on every refresh**. A stale in-memory or duplicated copy causes this. The client reloads tokens from disk before each refresh and locks around it; make sure `WHOOP_TOKENS_FILE` points at the persistent volume so rotations survive restarts. |
| WHOOP calls return **404** | Using the retired **v1** API. All paths must be `/developer/v2/…`, with sleep and workout under `/activity`. |
| `whoop_auth.py` fails or the browser errors | WHOOP requires a **`state` parameter (min 8 chars)** on the authorize request, and the app's redirect URI must be **exactly** `http://localhost:8283/callback`. |
| Connector shows disconnected / "session terminated" | The server or tunnel is down. On Fly, check `fly status` and `fly logs`. Locally, ngrok and `server.py` must both be running. |
| Strava tools return **403 `Application / Status / Inactive`** | Your personal Strava API app was deactivated. This project no longer calls the Strava API directly — use Strava's official MCP connector instead (needs a Strava subscription). |
| Tools list looks stale in the Claude app | Reconnect the connector (toggle off/on, or remove and re-add) so it re-reads the tool list. |

## Security notes

- Anyone with the full connector URL (host + token) can read your WHOOP data. Keep it secret; rotate `CONNECTOR_TOKEN` if it leaks.
- Never commit `.env`, `.whoop_tokens.json`, or `.memory.json` — all are gitignored.
- For stronger protection you can put the server behind OAuth 2.1 — not implemented here.
