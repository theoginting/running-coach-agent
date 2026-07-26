import json
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent

load_dotenv(PROJECT_ROOT / ".env")

# Where rotated WHOOP tokens are persisted. Override with WHOOP_TOKENS_FILE so
# deployments can point this at a mounted volume (e.g. /data/.whoop_tokens.json)
# — WHOOP rotates the refresh token on every refresh, so this file must survive
# restarts or the app loses access until re-authenticated.
WHOOP_TOKENS_FILE = Path(
    os.environ.get("WHOOP_TOKENS_FILE", PROJECT_ROOT / ".whoop_tokens.json")
)


class Config:
    def __init__(self):
        self.whoop_client_id = os.environ.get("WHOOP_CLIENT_ID", "")
        self.whoop_client_secret = os.environ.get("WHOOP_CLIENT_SECRET", "")
        self._load_whoop_tokens()

    def _load_whoop_tokens(self):
        if WHOOP_TOKENS_FILE.exists():
            data = json.loads(WHOOP_TOKENS_FILE.read_text())
            self.whoop_access_token = data.get("access_token")
            self.whoop_refresh_token = data.get("refresh_token")
            self.whoop_token_expires_at = data.get("expires_at", 0)
        else:
            self.whoop_access_token = os.environ.get("WHOOP_ACCESS_TOKEN")
            self.whoop_refresh_token = os.environ.get("WHOOP_REFRESH_TOKEN")
            self.whoop_token_expires_at = int(os.environ.get("WHOOP_TOKEN_EXPIRES_AT") or 0)

    def reload_whoop_tokens(self):
        """Re-read tokens from disk so a long-running process picks up refresh-token
        rotations performed by another process or a previous run. WHOOP rotates the
        refresh token on every refresh, so a stale in-memory copy causes 400s."""
        if WHOOP_TOKENS_FILE.exists():
            self._load_whoop_tokens()

    def update_whoop_tokens(self, access_token: str, refresh_token: str, expires_at: int):
        self.whoop_access_token = access_token
        self.whoop_refresh_token = refresh_token
        self.whoop_token_expires_at = expires_at
        WHOOP_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        WHOOP_TOKENS_FILE.write_text(
            json.dumps(
                {"access_token": access_token, "refresh_token": refresh_token, "expires_at": expires_at},
                indent=2,
            )
        )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
