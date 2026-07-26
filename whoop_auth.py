"""Run this once to authenticate with your Whoop account.

Usage:
    python whoop_auth.py
"""
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from config import get_config

REDIRECT_PORT = 8283
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
SCOPE = "read:recovery read:sleep read:cycles read:workout read:profile offline"


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    error: str | None = None
    done: bool = False

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/callback":
            params = parse_qs(parsed.query)
            _CallbackHandler.code = params.get("code", [None])[0]
            _CallbackHandler.state = params.get("state", [None])[0]
            _CallbackHandler.error = params.get("error", [None])[0]
            _CallbackHandler.done = True
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Whoop authentication complete! You can close this window.</h1></body></html>"
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args, **kwargs):
        pass


def authenticate():
    config = get_config()

    if not config.whoop_client_id or not config.whoop_client_secret:
        raise SystemExit(
            "WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET are not set in .env. "
            "Create an app at https://developer.whoop.com/ first."
        )

    # WHOOP requires a `state` parameter (min 8 chars) on the auth request as a
    # CSRF guard; the request is rejected without it.
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": config.whoop_client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
    }
    auth_url = f"{AUTH_URL}?{urlencode(params)}"

    print("Opening browser for Whoop authorization...")
    webbrowser.open(auth_url)
    print(f"If the browser didn't open, visit:\n{auth_url}\n")

    server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    print("Waiting for authorization callback...")

    while not _CallbackHandler.done:
        server.handle_request()

    if _CallbackHandler.error:
        raise SystemExit(f"WHOOP authorization failed: {_CallbackHandler.error}")
    if _CallbackHandler.state != state:
        raise SystemExit("WHOOP authorization failed: state mismatch (possible CSRF).")
    code = _CallbackHandler.code
    if not code:
        raise SystemExit("WHOOP authorization failed: no code returned.")

    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": config.whoop_client_id,
            "client_secret": config.whoop_client_secret,
        },
    )
    resp.raise_for_status()
    data = resp.json()

    config.update_whoop_tokens(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=int(time.time()) + data.get("expires_in", 3600),
    )

    print("\nWhoop authentication complete!")
    print("Tokens saved to .whoop_tokens.json")
    print("\nThe running coach will now have access to your recovery and sleep data.")


if __name__ == "__main__":
    authenticate()
