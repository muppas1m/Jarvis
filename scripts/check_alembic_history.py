"""
Migration-history linter — fail loudly when alembic's revision graph drifts
from the expected linear sequence.

The plan locks specific revision IDs (`001_initial_schema`, `002_langgraph_checkpoints`,
`003_email_tables`, `004_documents`, `005_browser_audit`, `006_messaging_tables`)
and their down_revision wiring. autogenerate happily picks random hashes
when you forget to rename, and a wrong down_revision creates a divergent
graph that quietly skips migrations.

This script:
  - Scans backend/alembic/versions/*.py for `revision = "..."` and
    `down_revision = "..."` declarations.
  - Asserts the chain matches the EXPECTED_CHAIN below in order.
  - Asserts no orphan/branching revisions exist.
  - Returns exit 0 on green, 1 on any drift.

Run manually:
    python scripts/check_alembic_history.py

Wire as a pre-commit hook (see .pre-commit-config.yaml).

Update EXPECTED_CHAIN whenever a new migration legitimately lands.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSIONS_DIR = REPO_ROOT / "backend" / "alembic" / "versions"

# The authoritative sequence. Update when a migration is added.
# (revision_id, expected_down_revision_or_None_for_base)
EXPECTED_CHAIN: list[tuple[str, str | None]] = [
    ("001_initial_schema",          None),
    ("002_langgraph_checkpoints",   "001_initial_schema"),
    # Phase 2 onward — uncomment as each migration lands.
    # ("003_email_tables",          "002_langgraph_checkpoints"),
    # ("004_documents",             "003_email_tables"),
    # ("005_browser_audit",         "004_documents"),
    # ("006_messaging_tables",      "005_browser_audit"),
]


REVISION_RE = re.compile(r'^revision(?:\s*:\s*str)?\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
DOWN_REVISION_RE = re.compile(
    r'^down_revision(?:\s*:[^=]+)?\s*=\s*(?:["\']([^"\']+)["\']|None)',
    re.MULTILINE,
)


def _parse_migration(path: Path) -> tuple[str, str | None]:
    """Return (revision, down_revision_or_None) declared in a migration file."""
    text = path.read_text()
    rev_match = REVISION_RE.search(text)
    if not rev_match:
        raise ValueError(f"{path.name}: no `revision = '...'` line found")

    down_match = DOWN_REVISION_RE.search(text)
    if not down_match:
        raise ValueError(f"{path.name}: no `down_revision = ...` line found")

    return rev_match.group(1), (down_match.group(1) if down_match.group(1) else None)


def main() -> int:
    if not VERSIONS_DIR.is_dir():
        print(f"ERROR: alembic versions directory not found: {VERSIONS_DIR}")
        return 1

    files = sorted(p for p in VERSIONS_DIR.glob("*.py") if p.name != "__init__.py")
    if not files:
        print(f"ERROR: no migration files in {VERSIONS_DIR}")
        return 1

    parsed: dict[str, tuple[str, str | None]] = {}  # filename -> (rev, down)
    revisions_seen: dict[str, str] = {}              # rev -> filename
    for f in files:
        try:
            rev, down = _parse_migration(f)
        except Exception as exc:
            print(f"ERROR: failed parsing {f.name}: {exc}")
            return 1
        if rev in revisions_seen:
            print(
                f"ERROR: duplicate revision id {rev!r} in "
                f"{revisions_seen[rev]} and {f.name}"
            )
            return 1
        parsed[f.name] = (rev, down)
        revisions_seen[rev] = f.name

    # Build the expected file-name → revision map for diff reporting.
    expected_revs = {rev for rev, _ in EXPECTED_CHAIN}
    actual_revs = set(revisions_seen)

    extras = actual_revs - expected_revs
    if extras:
        print(
            "ERROR: migration files present that EXPECTED_CHAIN doesn't know about:"
        )
        for rev in sorted(extras):
            print(f"  - {rev!r} ({revisions_seen[rev]})")
        print(
            "If a new migration legitimately lands, add it to EXPECTED_CHAIN in this script."
        )
        return 1

    missing = expected_revs - actual_revs
    if missing:
        print("ERROR: EXPECTED_CHAIN expects migrations that don't exist on disk:")
        for rev in sorted(missing):
            print(f"  - {rev!r}")
        return 1

    # Walk the chain and assert each down_revision matches.
    for rev, expected_down in EXPECTED_CHAIN:
        fname = revisions_seen[rev]
        _, actual_down = parsed[fname]
        if actual_down != expected_down:
            print(
                f"ERROR: {fname} has down_revision={actual_down!r}, "
                f"expected {expected_down!r}"
            )
            return 1

    print(f"OK: alembic history matches expected chain ({len(EXPECTED_CHAIN)} revisions).")
    for rev, down in EXPECTED_CHAIN:
        arrow = "<- root" if down is None else f"<- {down}"
        print(f"  {rev}  {arrow}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
