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

    app_root = Path(app.__file__).parent
    scripts_root = app_root.parent / "scripts"
    n = sum(1 for _ in app_root.rglob("*.py") if "__pycache__" not in str(_))

    parts = [
        "# Module Map\n",
        "The running system (`app/`) plus operational entry points (`scripts/`). One-line role "
        "from each module's docstring. (`tests/` and `alembic/` are excluded as support tooling.)\n",
        f"## `app/` — the system ({n} modules)\n",
        "```\n" + "\n".join(_tree(app_root)) + "\n```\n",
    ]
    if scripts_root.exists():
        parts += [
            "## `scripts/` — operational entry points\n",
            "```\n" + "\n".join(_tree(scripts_root)) + "\n```\n",
        ]
    return "\n".join(parts)


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

    # FastAPI 0.137 resolves `include_router` lazily, so static `app.routes` no
    # longer exposes the resolved Route objects (with `.dependant`). The OpenAPI
    # schema is the version-stable enumeration of paths + methods + tags. Auth is
    # a router-level dependency (not an OpenAPI security scheme), so we derive it
    # structurally: the only public routers are health + webhooks (each verifies
    # its own provider signature; see `app/api/router.py`) — every other route is
    # under the `get_current_user`-gated protected sub-router.
    public_tags = {"health", "webhooks"}

    paths = app.openapi().get("paths", {})
    rows = []
    for path, ops in paths.items():
        if path in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"):
            continue
        for method, op in ops.items():
            verb = method.upper()
            if verb in ("HEAD", "OPTIONS"):
                continue
            tags = tuple(op.get("tags") or [])
            auth = "public" if (public_tags & set(tags)) else "🔒 auth"
            rows.append((path, verb, auth, ", ".join(tags)))

    rows.sort()
    table = ["| Method | Path | Auth | Tags |", "|---|---|---|---|"]
    table += [f"| `{v}` | `{p}` | {a} | {t} |" for (p, v, a, t) in rows]
    return (
        "# API Routes\n\n"
        f"{len(rows)} routes from the live FastAPI app (`app/main.py` → `app/api/router.py`), "
        "enumerated via the OpenAPI schema. Auth is derived structurally — public routers are "
        "health + webhooks; every other route is under the `get_current_user`-gated protected "
        "sub-router.\n\n"
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
# 06 — LLM gateway routing (slots, TASK_ROUTING, force_model, caps).
# ===========================================================================
def gen_llm_gateway() -> str:
    from app.config import settings  # noqa: PLC0415
    from app.llm.models import TASK_ROUTING, get_models  # noqa: PLC0415

    models = get_models()
    slot_rows = [f"| `{slot}` | `{mc.model_id}` | {mc.provider} |" for slot, mc in models.items()]
    routing_rows = [f"| `{tt}` | `{slot}` |" for tt, slot in sorted(TASK_ROUTING.items())]
    hard = settings.DAILY_LLM_SPEND_CAP_USD
    soft_pct = int(settings.DAILY_LLM_SOFT_CAP_PCT * 100)
    return (
        "# LLM Gateway Routing\n\n"
        "Every chat completion routes through `app/llm/gateway.py:LLMGateway.complete()`. Slots are "
        "built in `app/llm/models.py:get_models()`; `task_type` picks a slot via `TASK_ROUTING`; "
        "`force_model=\"<slot>\"` overrides routing for one call.\n\n"
        "## Model slots (also the valid `force_model` targets)\n\n"
        "| Slot | Model ID | Provider |\n|---|---|---|\n" + "\n".join(slot_rows) + "\n\n"
        "## `task_type` → slot (`TASK_ROUTING`)\n\n"
        "| task_type | Slot |\n|---|---|\n" + "\n".join(routing_rows) + "\n\n"
        "Any unmapped `task_type` falls back to `primary`.\n\n"
        "## Routing precedence (in `complete()`)\n\n"
        f"1. **Hard cap** — if today's LLM spend ≥ `DAILY_LLM_SPEND_CAP_USD` (${hard:.2f}), the gateway "
        "raises `CostCapExceededError` and the agent halts until UTC midnight.\n"
        f"2. **Soft cap** — at ≥ {soft_pct}% of the hard cap (`DAILY_LLM_SOFT_CAP_PCT`), every call is "
        "degraded to the `fast` slot (unless `force_model` is set).\n"
        "3. **force_model** — routes to that named slot (e.g. document contextualization uses "
        "`force_model=\"contextualizer\"` to stay OFF the agent's Groq).\n"
        "4. Otherwise **`TASK_ROUTING[task_type]`**, else `primary`.\n\n"
        "On a provider failure the gateway falls over to the `fallback` slot once (no recursion past it).\n"
    )


# ===========================================================================
# 07 — external services & dependencies (compose infra + config providers).
# Secret-safe: setting NAMES + non-secret descriptors only; never values of
# tokens/keys/passwords/credential URLs.
# ===========================================================================
def gen_external_services(compose_file: str | None) -> str:
    import yaml  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415
    from app.llm.models import get_models  # noqa: PLC0415

    parts = [
        "# External Services & Dependencies\n",
        "Every external / infrastructure dependency the system talks to. Interconnection FLOWS are "
        "the Phase-2 DFD; this is the mechanical inventory.\n",
        "## Infrastructure (docker-compose services)\n",
    ]
    if compose_file and Path(compose_file).exists():
        data = yaml.safe_load(Path(compose_file).read_text(encoding="utf-8")) or {}
        services = data.get("services", {}) or {}
        rows = []
        for name, cfg in sorted(services.items()):
            cfg = cfg or {}
            img = cfg.get("image")
            if not img and cfg.get("build"):
                b = cfg["build"]
                img = f"build: {b if isinstance(b, str) else b.get('context', '.')}"
            rows.append(f"| `{name}` | {img or '?'} |")
        parts.append("| Service | Image / build |\n|---|---|\n" + "\n".join(rows) + "\n")
    else:
        parts.append("> _Compose file not provided (`--compose-file`); infra services not introspected._\n")

    providers = sorted({mc.provider for mc in get_models().values()})
    parts.append("\n## LLM providers (reached via the gateway slots — see `06_llm_gateway.md`)\n")
    parts.append("| Provider |\n|---|\n" + "\n".join(f"| {p} |" for p in providers) + "\n")

    rows = [
        ("Ollama (local model server)", "embeddings + reranker",
         f"`OLLAMA_BASE_URL` · embed `{settings.EMBEDDING_MODEL}` · rerank `{settings.RERANK_MODEL}`"),
        ("Postgres + pgvector", "datastore + vector store",
         "`DATABASE_URL` — LangGraph checkpoints, app tables, mem0 + tool + document vectors"),
        ("Redis", "cache / counters / Celery broker", "`REDIS_URL` — cost cap, rate limits, Celery"),
        ("Telegram Bot API", "chat channel (long-poll / webhook)", "`TELEGRAM_BOT_TOKEN`"),
        ("Google / Gmail", "email + calendar + Pub/Sub push",
         "`GOOGLE_*` OAuth · `GMAIL_PUBSUB_TOPIC` / `GMAIL_PUBSUB_SUBSCRIPTION`"),
        ("Langfuse", "LLM observability / tracing", "`LANGFUSE_HOST`"),
    ]
    parts.append("\n## APIs, datastores & observability (curated roles — from config, secrets omitted)\n")
    parts.append(
        "| Dependency | Role | Configured via |\n|---|---|---|\n"
        + "\n".join(f"| {n} | {r} | {d} |" for (n, r, d) in rows) + "\n"
    )

    # Auto-scan: every endpoint-shaped setting NAME, so a NEW external dependency
    # self-surfaces here (and the drift-gate then catches the omission) without
    # the curated table above having to be hand-updated. Names only — many of
    # these are credential-bearing URLs; values are never emitted.
    suffixes = ("_URL", "_HOST", "_BASE_URL", "_TOPIC")
    endpoints = sorted(f for f in type(settings).model_fields if f.endswith(suffixes))
    parts.append("\n## Detected config endpoints (auto-scanned — self-surfaces new deps)\n")
    parts.append(
        "Setting names ending in `_URL` / `_HOST` / `_BASE_URL` / `_TOPIC`. A new endpoint-shaped "
        "setting appears here automatically; give it a curated role in the table above.\n\n"
        + "\n".join(f"- `{f}`" for f in endpoints) + "\n"
    )
    return "\n".join(parts)


# ===========================================================================
# Orchestration
# ===========================================================================
async def generate_all(out: Path, compose_file: str | None) -> None:
    from functools import partial  # noqa: PLC0415

    artifacts = [
        ("00_module_map.md", gen_module_map),
        ("01_database_erd.md", gen_db_erd),
        ("02_api_routes.md", gen_api_routes),
        ("03_tools.md", gen_tools),
        ("04_celery_schedule.md", gen_celery_schedule),
        ("05_agent_graph.md", gen_agent_graph),
        ("06_llm_gateway.md", gen_llm_gateway),
        ("07_external_services.md", partial(gen_external_services, compose_file)),
    ]
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for fname, fn in artifacts:
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
    parser.add_argument("--compose-file", default=None,
                        help="Path to docker-compose.yml (copy it into the container first — it "
                             "lives outside the /app mount). Omitted → infra-services section degrades.")
    args = parser.parse_args()
    asyncio.run(generate_all(Path(args.out), args.compose_file))


if __name__ == "__main__":
    main()
