import logging
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

logger = logging.getLogger(__name__)

from config import get_config

# Serialise token refreshes across concurrent requests. WHOOP refresh tokens are
# single-use and rotate on every refresh, so two overlapping refreshes would
# invalidate each other.
_REFRESH_LOCK = threading.Lock()

# WHOOP API v2. The v1 API (…/developer/v1/…) is no longer supported, so all
# paths live under /developer/v2 and the sleep/workout resources moved under
# /activity. See https://developer.whoop.com/docs/developing/v1-v2-migration/
_SCOPES = "read:recovery read:sleep read:cycles read:workout read:profile offline"

# v2 collection endpoints cap `limit` at 25.
_MAX_LIMIT = 25


def _start_iso(days: int) -> str:
    """ISO-8601 timestamp `days` ago, used as the `start` filter for collections."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


class WhoopClient:
    BASE_URL = "https://api.prod.whoop.com/developer/v2"
    TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

    def __init__(self):
        self._config = get_config()

    def _refresh_if_needed(self):
        with _REFRESH_LOCK:
            # Pick up any rotation done by another process/request before deciding
            # whether we still need to refresh — avoids refreshing with a stale
            # (already-rotated) token, which WHOOP rejects with a 400.
            self._config.reload_whoop_tokens()
            if time.time() > self._config.whoop_token_expires_at - 300:
                self._refresh()

    def _refresh(self):
        try:
            resp = httpx.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._config.whoop_refresh_token,
                    "client_id": self._config.whoop_client_id,
                    "client_secret": self._config.whoop_client_secret,
                    "scope": _SCOPES,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._config.update_whoop_tokens(
                access_token=data["access_token"],
                # WHOOP rotates the refresh token; fall back to the existing one
                # if a new one isn't returned.
                refresh_token=data.get("refresh_token", self._config.whoop_refresh_token),
                expires_at=int(time.time()) + data.get("expires_in", 3600),
            )
        except Exception as e:
            logger.error("Whoop token refresh failed: %s", e)
            raise RuntimeError(f"Whoop token refresh failed: {e}") from e

    def _get(self, path: str, **params) -> dict | list:
        self._refresh_if_needed()
        resp = httpx.get(
            f"{self.BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self._config.whoop_access_token}"},
            params={k: v for k, v in params.items() if v is not None},
        )
        resp.raise_for_status()
        return resp.json()

    def _collection(self, path: str, days: int) -> dict:
        """Fetch a v2 collection filtered to roughly the last `days` days."""
        limit = max(1, min(days, _MAX_LIMIT))
        return self._get(path, limit=limit, start=_start_iso(days))

    def get_profile(self) -> dict:
        return self._get("/user/profile/basic")

    def get_recovery(self, days: int = 7) -> dict:
        return self._collection("/recovery", days)

    def get_sleep(self, days: int = 7) -> dict:
        return self._collection("/activity/sleep", days)

    def get_cycles(self, days: int = 7) -> dict:
        return self._collection("/cycle", days)

    def get_workouts(self, days: int = 7) -> dict:
        return self._collection("/activity/workout", days)
