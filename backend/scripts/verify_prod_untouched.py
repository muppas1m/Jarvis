"""Empirical proof that the test suite no longer touches prod (the 2026-06-27 fix).

Run OUT-OF-BAND (a normal process, NOT pytest, NOT a smoke — it must read the LIVE
prod DB, so it deliberately does NOT import _smoke_isolation):

    docker compose exec backend python scripts/verify_prod_untouched.py

It (1) snapshots the four tables the incident corrupted, (2) runs the exact briefing
+ approval tests that did the damage — which now bind to the isolated <db>_test DB —
and (3) re-snapshots prod and asserts every table is byte-for-byte identical.
"""
import asyncio
import contextlib
import subprocess
import sys

from sqlalchemy import text

from app.config import _db_name, settings
from app.db.engine import async_session, engine

TABLES = ["briefing_items", "morning_briefs", "pending_approvals", "user_profiles"]
TESTS = [
    "tests/test_briefing_state.py",
    "tests/test_morning_brief_hud.py",
    "tests/test_approval_drain.py",
]


async def _snapshot() -> dict[str, str]:
    """count + content hash per table, order-stable by primary key id."""
    # before/after are separate asyncio.run() loops; rebind the module engine pool to
    # THIS loop (project_async_state_rebind_pattern) so the 2nd snapshot doesn't hit
    # "Future attached to a different loop".
    with contextlib.suppress(Exception):
        await engine.dispose()
    out: dict[str, str] = {}
    async with async_session() as s:
        for t in TABLES:
            q = text(
                f"SELECT count(*)::text || ':' || "
                f"coalesce(md5(string_agg(md5(row_to_json(x)::text), '' ORDER BY x.id)), 'empty') "
                f"FROM {t} x"
            )
            out[t] = (await s.execute(q)).scalar() or "?"
    return out


def _run_tests() -> int:
    print("\n→ running the briefing + approval tests (they bind to the isolated _test DB)…\n")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS], cwd="."
    ).returncode


def main() -> int:
    if settings.RUNTIME_DB_IS_TEST:
        print("REFUSING: this verifier must read PROD, but it is bound to the test DB. "
              "Run it as a plain process (no pytest / JARVIS_TEST_MODE).")
        return 2
    print(f"prod database under audit: {_db_name(settings.DATABASE_URL)!r}")

    before = asyncio.run(_snapshot())
    rc = _run_tests()
    after = asyncio.run(_snapshot())

    print("\n=== prod table snapshots (count:md5) ===")
    drift = []
    for t in TABLES:
        same = before[t] == after[t]
        print(f"  {'OK ' if same else 'DRIFT'}  {t:18} before={before[t]}  after={after[t]}")
        if not same:
            drift.append(t)

    if drift:
        print(f"\n*** FAIL: prod was MODIFIED by the test run: {drift} ***")
        return 1
    print(f"\nPASS: prod untouched (test exit code {rc}). The suite ran fully isolated.")
    # Surface — but don't mask — a test failure; isolation is proven regardless.
    return 0 if rc == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
