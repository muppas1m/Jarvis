"""Architecture-doc generator — introspects the LIVE code and emits Markdown +
Mermaid into docs/architecture/generated/.

Principle: GENERATE the mechanical (what code already encodes), so it can never
drift. The hand-authored intent (DFD, narrative, decisions) lives elsewhere and
is gated separately. Every file this writes is stamped AUTO-GENERATED.

Run (the host conda env lacks the deps; this MUST run in the container where the
app + services are importable):

    docker compose exec -T backend python scripts/gen_architecture.py --out /tmp/arch
    docker cp jarvis-backend:/tmp/arch/. docs/architecture/generated/

…or just `make architecture` from the repo root, which wraps both steps.

Each artifact is independent: a failure in one writes an error stub and the rest
still generate, so a partial environment never produces an empty doc set.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import inspect
from pathlib import Path

STAMP = (
    "<!-- AUTO-GENERATED — do not edit by hand.\n"
    "     Regenerate with `make architecture` (or scripts/gen_architecture.py).\n"
    "     Source of truth is the code; edit the code, then regenerate. -->\n\n"
)


# ===========================================================================
# 00 — module map (tree + one-line role). Pure file/AST read — no app import,
# so this always works even if a heavy module fails to import.
# ===========================================================================
def _module_role(py_file: Path) -> str:
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree)
    except Exception:  # noqa: BLE001
        return "(unparseable)"
    if not doc:
        return "—"
    first = next((ln.strip() for ln in doc.splitlines() if ln.strip()), "—")
    return (first[:110] + "…") if len(first) > 111 else first


def _tree(root: Path) -> list[str]:
    lines: list[str] = []

    def walk(directory: Path, prefix: str) -> None:
        children = [
            c for c in directory.iterdir()
            if c.name != "__pycache__" and not c.name.startswith(".")
            and (c.is_dir() or c.suffix == ".py")
        ]
        children.sort(key=lambda c: (c.is_file(), c.name.lower()))
        for i, child in enumerate(children):
            last = i == len(children) - 1
            branch = "└── " if last else "├── "
            if child.is_dir():
                lines.append(f"{prefix}{branch}{child.name}/")
                walk(child, prefix + ("    " if last else "│   "))
            else:
                lines.append(f"{prefix}{branch}{child.name} — {_module_role(child)}")

    lines.append(f"{root.name}/")
    walk(root, "")
    return lines


def gen_module_map() -> str:
    import app  # noqa: PLC0415

    root = Path(app.__file__).parent
    body = "\n".join(_tree(root))
    n = sum(1 for _ in root.rglob("*.py") if "__pycache__" not in str(_))
    return (
        "# Module Map\n\n"
        f"The `app/` package — {n} modules, one-line role from each module's docstring.\n\n"
        "```\n" + body + "\n```\n"
    )


# ===========================================================================
# 01 — DB ERD from the SQLAlchemy models. No DB connection (metadata only).
# ===========================================================================
def gen_db_erd() -> str:
    from app.db.models import Base  # noqa: PLC0415

    tables = Base.metadata.tables
    lines = ["erDiagram"]
    rels: list[str] = []

    for tname in sorted(tables):
        table = tables[tname]
        lines.append(f"    {tname} {{")
        for col in table.columns:
            ctype = type(col.type).__name__
            keys = []
            if col.primary_key:
                keys.append("PK")
            if col.foreign_keys:
                keys.append("FK")
            key_str = (" " + ",".join(keys)) if keys else ""
            lines.append(f"        {ctype} {col.name}{key_str}")
        lines.append("    }")
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            rels.append(f'    {parent} ||--o{{ {tname} : "{fk.parent.name}"')

    lines.extend(sorted(set(rels)))
    rel_note = (
        "Relations are FK constraints."
        if rels else
        "**No DB-level foreign keys** — this is intentional: tables are associated at the "
        "application layer by `thread_id` (a string), and LangGraph's checkpoint tables own the "
        "canonical per-thread conversation state. So the entities below stand alone in the schema."
    )
    return (
        "# Database ERD\n\n"
        f"{len(tables)} tables, introspected from `app/db/models.py` (`Base.metadata`). "
        f"{rel_note}\n\n"
        "```mermaid\n" + "\n".join(lines) + "\n```\n"
    )


# ===========================================================================
# 02 — API route map + auth, from the live FastAPI app.
# ===========================================================================
def gen_api_routes() -> str:
    from app.main import app  # noqa: PLC0415
    from app.security.auth import get_current_user  # noqa: PLC0415

    def requires_auth(route) -> bool:
        def walk(dep) -> bool:
            if getattr(dep, "call", None) is get_current_user:
                return True
            return any(walk(d) for d in getattr(dep, "dependencies", []))
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            return False
        return any(walk(d) for d in dependant.dependencies)

    rows = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods or path in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"):
            continue
        verbs = ",".join(sorted(m for m in methods if m != "HEAD"))
        auth = "🔒 auth" if requires_auth(route) else "public"
        tags = ", ".join(getattr(route, "tags", []) or [])
        rows.append((path, verbs, auth, tags))

    rows.sort()
    table = ["| Method | Path | Auth | Tags |", "|---|---|---|---|"]
    table += [f"| `{v}` | `{p}` | {a} | {t} |" for (p, v, a, t) in rows]
    return (
        "# API Routes\n\n"
        f"{len(rows)} routes from the live FastAPI app (`app/main.py` → `app/api/router.py`). "
        "Auth = a `get_current_user` dependency on the route (the protected sub-router).\n\n"
        + "\n".join(table) + "\n"
    )


# ===========================================================================
# 03 — tool registry + safety tiers.
# ===========================================================================
def gen_tools() -> str:
    from app.agent.safety import TOOL_SAFETY_MAP  # noqa: PLC0415
    from app.agent.tools import register_all_tools, tool_registry  # noqa: PLC0415

    register_all_tools()

    rows = []
    for name in sorted(tool_registry._entries):
        entry = tool_registry._entries[name]
        tier = TOOL_SAFETY_MAP.get(name)
        tier_s = tier.value.upper() if tier is not None else "APPROVE (default)"
        handler = getattr(entry.tool, "func", None) or getattr(entry.tool, "coroutine", None)
        module = getattr(handler, "__module__", "?")
        always = "yes" if entry.always_loaded else ""
        one_line = entry.description.split(".")[0].strip()
        one_line = (one_line[:90] + "…") if len(one_line) > 91 else one_line
        rows.append((name, tier_s, always, module, one_line))

    table = ["| Tool | Safety tier | Always-loaded | Backing module | Summary |",
             "|---|---|---|---|---|"]
    table += [f"| `{n}` | {t} | {a} | `{m}` | {s} |" for (n, t, a, m, s) in rows]
    return (
        "# Tools & Safety Tiers\n\n"
        f"{len(rows)} registered tools. Safety tier from `app/agent/safety.py:TOOL_SAFETY_MAP` "
        "(SAFE = silent · NOTIFY = run+inform · APPROVE = pause for the master · BLOCKED = never). "
        "Backing module is the handler's `__module__`.\n\n"
        + "\n".join(table) + "\n"
    )


# ===========================================================================
# 04 — Celery beat schedule.
# ===========================================================================
def gen_celery_schedule() -> str:
    from app.scheduler.beat_schedule import celery_app  # noqa: PLC0415

    def cron_str(sched) -> str:
        parts = [getattr(sched, f"_orig_{f}", None) for f in
                 ("minute", "hour", "day_of_month", "month_of_year", "day_of_week")]
        if all(p is not None for p in parts):
            return "`" + " ".join(str(p) for p in parts) + "`  (m h dom mon dow)"
        return f"`{sched}`"

    rows = []
    for name, cfg in sorted(celery_app.conf.beat_schedule.items()):
        rows.append((name, cfg["task"], cron_str(cfg["schedule"])))

    table = ["| Beat job | Task | Schedule |", "|---|---|---|"]
    table += [f"| `{n}` | `{t}` | {s} |" for (n, t, s) in rows]
    return (
        "# Celery Beat Schedule\n\n"
        f"{len(rows)} periodic jobs from `app/scheduler/beat_schedule.py`.\n\n"
        + "\n".join(table) + "\n"
    )


# ===========================================================================
# 05 — LangGraph agent graph via draw_mermaid. Needs the checkpointer (DB).
# ===========================================================================
async def gen_agent_graph() -> str:
    from app.agent.graph import build_graph, init_checkpointer  # noqa: PLC0415

    await init_checkpointer()
    mermaid = build_graph().get_graph().draw_mermaid()
    return (
        "# Agent Graph (LangGraph)\n\n"
        "Rendered from the compiled `StateGraph` (`app/agent/graph.py:build_graph`) via "
        "`get_graph().draw_mermaid()`. The APPROVE-tier interrupt lives inside "
        "`tool_executor` (it pauses the graph; resume re-enters the same node).\n\n"
        "```mermaid\n" + mermaid.strip() + "\n```\n"
    )


# ===========================================================================
# Orchestration
# ===========================================================================
ARTIFACTS = [
    ("00_module_map.md", gen_module_map),
    ("01_database_erd.md", gen_db_erd),
    ("02_api_routes.md", gen_api_routes),
    ("03_tools.md", gen_tools),
    ("04_celery_schedule.md", gen_celery_schedule),
    ("05_agent_graph.md", gen_agent_graph),
]


async def generate_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for fname, fn in ARTIFACTS:
        try:
            content = await fn() if inspect.iscoroutinefunction(fn) else fn()
        except Exception as exc:  # noqa: BLE001 — one failure must not kill the set
            content = (
                f"# {fname}\n\n> **Generation FAILED** — `{type(exc).__name__}: {exc}`\n\n"
                "Fix the environment (is the stack up?) and re-run `make architecture`.\n"
            )
            print(f"  ✗ {fname}: {type(exc).__name__}: {exc}")
        else:
            print(f"  ✓ {fname}")
        (out / fname).write_text(STAMP + content, encoding="utf-8")
        written.append(fname)

    index = (
        STAMP
        + "# Generated Architecture Docs\n\n"
        "Mechanical, introspected from the live code — **do not hand-edit**; run "
        "`make architecture`. The hand-authored intent (overview, DFD, decisions) is in the "
        "parent `docs/architecture/` directory.\n\n"
        + "\n".join(f"- [{f.split('_', 1)[1][:-3].replace('_', ' ').title()}]({f})" for f in written)
        + "\n"
    )
    (out / "index.md").write_text(index, encoding="utf-8")
    print(f"\nWrote {len(written) + 1} files to {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/architecture/generated",
                        help="Output directory (in-container path).")
    args = parser.parse_args()
    asyncio.run(generate_all(Path(args.out)))


if __name__ == "__main__":
    main()
