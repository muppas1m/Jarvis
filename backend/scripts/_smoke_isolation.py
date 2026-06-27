"""Import FIRST (before any `app.*` import) in every DB-touching smoke script.

The side effect at import time binds this process to the isolated `<db>_test`
database — exactly like pytest does — so a smoke run can never write to the
master's live data. It MUST be the first import: the env var has to be set before
`app.config` builds the settings singleton (that's where the URL swap happens).

    import _smoke_isolation  # noqa: F401  — bind to the test DB before app imports

Then the smoke runs unchanged; its scoped seed/cleanup now happens in the throwaway
test DB. `ensure_test_database(drop_first=False)` is idempotent — a one-time create,
fast on every subsequent run.
"""
import os

os.environ.setdefault("JARVIS_TEST_MODE", "1")

from app.db.test_provisioning import assert_isolated, ensure_test_database  # noqa: E402

assert_isolated()
ensure_test_database(drop_first=False)
