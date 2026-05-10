"""Mint an HS256 JWT for the master so we can curl protected endpoints
without a Phase 4 frontend.

    docker compose run --rm --entrypoint sh backend -c \
        "cd /app && python scripts/issue_jwt.py"

Prints the token to stdout. Pipe into curl:

    TOKEN=$(docker compose run --rm --entrypoint sh backend -c \
        "cd /app && python scripts/issue_jwt.py" | tail -1)
    curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/...

Default TTL 24h. Override with --ttl-hours N.
"""
import argparse
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.config import settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sub", default="master", help="JWT subject (user id)")
    parser.add_argument("--ttl-hours", type=int, default=24, help="Token TTL (hours)")
    args = parser.parse_args()

    if not settings.AUTH_SECRET:
        raise SystemExit("AUTH_SECRET not set in .env — can't sign a token")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": args.sub,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=args.ttl_hours)).timestamp()),
    }
    token = jwt.encode(payload, settings.AUTH_SECRET, algorithm="HS256")
    print(token)


if __name__ == "__main__":
    main()
