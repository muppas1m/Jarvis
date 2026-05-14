"""
One-time Google OAuth refresh-token bootstrap.

Phase 2 Task 2.1. Run this once on the host (NOT inside Docker — it opens a
browser and binds a local-loopback port that Google redirects to). The flow:

  1. Reads the OAuth client config from `backend/secrets/google_credentials.json`
     (downloaded from the GCP Console: APIs & Services → Credentials → OAuth
     2.0 Client IDs → Desktop app → Download JSON).
  2. Opens your default browser to Google's consent screen requesting Gmail
     and Calendar scopes.
  3. After you consent, Google redirects to a short-lived local-loopback URL
     and the script captures the token exchange.
  4. Prints the refresh token. Paste it into `.env` as `GOOGLE_REFRESH_TOKEN`.

Refresh tokens are long-lived (180 days for Google when not rotated). You
should only need to re-run this when you rotate scopes, revoke access, or
the token expires from disuse.

## Prereqs

  - `backend/secrets/google_credentials.json` exists. Create the directory
    if missing: `mkdir -p backend/secrets/`.
  - The OAuth client in GCP is type "Desktop app" so `run_local_server`
    works without a public redirect URI.
  - Gmail API and Calendar API are enabled in the same GCP project as the
    OAuth client.
  - Conda env active: `conda activate jarvis`. The script's deps
    (google-auth-oauthlib, google-api-python-client) are in
    `backend/pyproject.toml` and installed by the env.

## Run

From anywhere (the script resolves its paths from `__file__`):

    conda activate jarvis
    python /path/to/repo/backend/scripts/google_oauth.py

A browser window opens. Consent. The script prints the refresh token.

## After

Paste the printed line into `.env` (replacing any existing
`GOOGLE_REFRESH_TOKEN=...` line). The Phase 2 Gmail watch + tool calls
will pick it up via `app.config.settings.GOOGLE_REFRESH_TOKEN`.
"""
from __future__ import annotations

import sys
from pathlib import Path

# CWD-independent: resolve the credentials path relative to the repo root
# rather than process CWD. Means you can run this script from anywhere.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CREDENTIALS_PATH = REPO_ROOT / "backend" / "secrets" / "google_credentials.json"

# Phase 2 scopes — Gmail (read/modify/send via gmail.modify + gmail.send)
# and Calendar (full read/write). Bundled in one consent prompt to avoid a
# second consent dance when Calendar tools land later in Phase 2.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]


def main() -> int:
    # Lazy import — google_auth_oauthlib is heavy and only needed in this
    # one-shot script, not at agent runtime.
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "ERROR: google-auth-oauthlib not installed.\n"
            "  Activate the conda env first: conda activate jarvis",
            file=sys.stderr,
        )
        return 1

    # Honor settings.GOOGLE_CREDENTIALS_PATH if importable; fall back to the
    # repo-root-relative default so the script also works from a clean checkout
    # before settings are wired.
    creds_path: Path
    try:
        from app.config import settings  # noqa: WPS433 — runtime import on purpose
        configured = Path(settings.GOOGLE_CREDENTIALS_PATH)
        creds_path = configured if configured.is_absolute() else REPO_ROOT / configured
    except Exception:
        creds_path = DEFAULT_CREDENTIALS_PATH

    if not creds_path.exists():
        print(
            f"ERROR: OAuth credentials file not found at {creds_path}\n\n"
            f"Steps to fix:\n"
            f"  1. mkdir -p {creds_path.parent}\n"
            f"  2. Download the OAuth 2.0 Client ID JSON from GCP Console\n"
            f"     (APIs & Services -> Credentials -> Desktop app)\n"
            f"  3. Save it as: {creds_path}\n"
            f"  4. Re-run this script.",
            file=sys.stderr,
        )
        return 1

    print(f"Using credentials: {creds_path}")
    print(f"Requesting scopes:")
    for s in SCOPES:
        print(f"  - {s}")
    print()
    print("Opening browser for consent...")
    print("(If the browser doesn't open automatically, the URL will be printed below.)")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    if not creds.refresh_token:
        # Google only returns a refresh_token on first consent for a given
        # client+scope combo. If you've consented before and didn't revoke,
        # subsequent runs return access_token only.
        print(
            "\nERROR: no refresh_token returned. This usually means you've "
            "already consented for this OAuth client + these scopes. Either:\n"
            "  - Revoke access at https://myaccount.google.com/permissions\n"
            "    and re-run, OR\n"
            "  - Re-use the refresh_token from your previous run.",
            file=sys.stderr,
        )
        return 1

    print("=" * 60)
    print("REFRESH TOKEN — paste the line below into .env:")
    print("=" * 60)
    print()
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print()
    print("=" * 60)
    print("Done. Restart the backend after updating .env so the new")
    print("token is picked up by app.config.settings.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
