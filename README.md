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

> WHOOP uses **API v2** (`/developer/v2/…`). The v1 API is no longer supported.

## Prerequisites

- Python 3.11+
- A [WHOOP account](https://www.whoop.com) + developer app
- A **Strava subscription** (for Strava's official connector)
- The Claude app on a plan that supports custom connectors (Free = 1, Pro, Max, Team, Enterprise)
- A way to expose this server over public HTTPS (Railway for production, ngrok for testing)

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

### Production with Railway

1. Push to GitHub and create a Railway project from the repo.
2. The `Procfile` runs `python server.py` as a **web** process. Railway injects `$PORT`.
3. In Railway → **Variables**, set:

   | Variable | Value |
   |---|---|
   | `CONNECTOR_TOKEN` | your secret |
   | `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` | from WHOOP |
   | `WHOOP_ACCESS_TOKEN` / `WHOOP_REFRESH_TOKEN` / `WHOOP_TOKEN_EXPIRES_AT` | from local `.whoop_tokens.json` |
   | `MEMORY_FILE` | optional: a path on a mounted volume (e.g. `/data/.memory.json`) |

   Run `whoop_auth.py` locally first, then copy the token values.
4. Add the connector in the Claude app using your Railway URL:
   `https://<app>.up.railway.app/<CONNECTOR_TOKEN>/mcp`

> Railway's filesystem is ephemeral. WHOOP token refreshes and memory written at
> runtime won't survive a redeploy unless you attach a volume and point
> `MEMORY_FILE` at it. Tokens are re-read from env vars on restart.

## Security notes

- Anyone with the full connector URL (host + token) can read your WHOOP data. Keep it secret; rotate `CONNECTOR_TOKEN` if it leaks.
- For stronger protection you can put the server behind OAuth 2.1 — not implemented here.
