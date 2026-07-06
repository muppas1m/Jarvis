# Phase 1 — Pivot Report: the Non‑Blocking Approval Migration

**Audit mission:** determine whether the seed decisions of the "blocking → non‑blocking
approval" migration were architecturally sound. **This phase locates the pivot and records
the sound *before* state.** No soundness judgement is made here — that is Phase 2/3, gated by
the master.

**Author:** research/audit agent (read‑only). **Date:** 2026‑07‑05.
**Repo:** `Jarvis_bot`, branch `main` @ `6f356c0` at start.

---

## 0. Method & reading‑rule compliance

**Read (allowed):** `jarvis-implementation-plan.md` context; git history *metadata* (log,
messages, `--stat`, pickaxe, targeted diffs); and **pre‑migration code only**, via an isolated
detached worktree pinned at the baseline commit.

**NOT read (per the strict rule, to protect the audit from anchoring):** `handoff/`,
`docs/testing/`, `commits.md`, `architecture_needs_revision.md`, and **any post‑migration
code**. The seed/after diffs were inspected as *history metadata* (to prove the pivot), never
as the current implementation.

**Isolation technique:** `git worktree add --detach <scratch>/baseline_40758a9 40758a9`. All
baseline citations below were read from that snapshot, which physically contains *only*
pre‑migration code — the migration's files do not exist there. The fan‑out readers were
constrained to that directory with an explicit "no git commands" rule so they could not reach
post‑migration code.

**Locating technique:** pickaxe `git log --reverse -S "interrupt(" -- backend/` (catches the
line that removes the call), a commit‑message scan (`interrupt`/`approval`/`queue`/`block`/
`non-block`), and then **confirming the candidate's diff with my own eyes** — it must *actually*
remove/bypass the `interrupt()` blocking path, not merely mention it.

---

## 1. Verdict (up front)

| Role | Commit | One line |
|---|---|---|
| **SEED (the pivot)** | **`88ad34d`** | *approvals(Phase3): cutover to non‑blocking queue + unified claim‑gated dispatch; retire interrupt() from the live path* — 2026‑06‑24 22:17 |
| **BASELINE (sound "before")** | **`40758a9`** | *email: agent‑direct email_send tool returns honest maybe‑delivered wording…* — 2026‑06‑24 19:00 (last pristine pre‑migration commit) |
| Precursor (runner‑up seed) | `f283f77` | *approvals(Phase3 Step1): …execute‑on‑approve dispatcher + claim expiry gate (**not yet wired**)* — the migration's Step‑1 scaffolding; leaves `interrupt()` live |

**Branch created:** `research/pre-migration-baseline` → `40758a9` (verified; `main` untouched,
no checkout performed).

The migration is a tight four‑commit run, all authored on **2026‑06‑24**:

```
40758a9  19:00  ── BASELINE (pristine blocking; interrupt() live) ────────────┐
f283f77  20:30  Phase3 Step1  add non-blocking scaffolding, "not yet wired"    │ still
                              (approval_dispatch.py, execute_tool_guarded)     │ blocking
88ad34d  22:17  Phase3 CUTOVER  retire interrupt() from the live path  ◄── SEED (pivot)
b0b5760  22:23  Phase3         deploy-time drain for pre-cutover paused checkpoints
95d92df  22:44  Phase3         retire dead resume era (route_approval_decision/
                              CHANNEL_ORIGIN_HANDLERS/resolve/resume_turn)
```

---

## 2. Seed evidence — `88ad34d` actually removes the blocking path

**Full identity**

```
commit  88ad34d
parent  f283f77
date    2026-06-24 22:17:07 -0400
subject approvals(Phase3): cutover to non-blocking queue + unified claim-gated
        dispatch; retire interrupt() from the live path
```

**Change surface (`--stat`)** — note the two smoking guns (a deleted resume test, a new queue
test) and the gutting of `runner.py`/`nodes.py`:

```
 backend/app/agent/approval_dispatch.py         |  62 ++
 backend/app/agent/nodes.py                     | 147 ++------          ← interrupt() removed
 backend/app/agent/runner.py                    | 234 +----------       ← resume era removed
 backend/app/api/approvals.py                   |  75 +-
 backend/app/messaging/channels/telegram.py     |  24 +-
 backend/app/scheduler/tasks/approval_expiry.py |  28 +-
 backend/tests/test_queue_exactly_once.py       | 225 ++++++++++++      ← NEW (queue)
 backend/tests/test_resume_dedup.py             | 369 ------------------ ← DELETED (resume)
 …                                              (13 files, +619 / −840)
```

**Own‑eyes diff confirmation** (`git show 88ad34d -- …/nodes.py …/runner.py`, `−` removed /
`+` added):

- Removes the import of the primitive:
  `−from langgraph.types import interrupt`
- Removes the **live pause call** in `tool_executor`:
  `−        decision = interrupt(` (with its whole `# APPROVE → pause via interrupt` block).
- Replaces it with the non‑blocking queue rationale in‑diff:
  `+ (Phase 3 retired \`interrupt()\`: APPROVE-tier tools no longer pause the turn;` …
  `+   … QUEUE, never interrupt(). … Retiring interrupt() kills its whole fragility class`
  `+   (orphaned tool_calls, resume-fail, async-rebind-on-resume). NO side effect fires` …
- Rips out the resume machinery in `runner.py`:
  `−        env = await resume_turn(thread_id, {"approved": True, "user_msg": …})` (and the
  reject/edit variants), and converts every resume site into a *legacy backstop*:
  `+   # Legacy paused-at-interrupt checkpoint … NEVER resume the graph. The old`
  `+   # Command(resume) path is [retired]`.
- Test‑level proof: **deletes** `test_resume_dedup.py` (−369, the interrupt/resume dedup
  suite) and **adds** `test_queue_exactly_once.py` (+225, the new queue's exactly‑once suite).

This is unambiguous: `88ad34d` is where the `interrupt()` blocking path is torn out of the
graph and replaced by a queue. ✅ It satisfies the confirmation criterion.

---

## 3. Candidate ranking (ambiguity resolved with evidence)

The one genuine ambiguity: the migration's *first authored commit* (`f283f77`) is **not** the
commit that *removes* `interrupt()` (`88ad34d`). The task's confirm gate — "*the seed's diff
must actually remove or bypass the `interrupt()` blocking path*" — is the tiebreaker, and it
selects `88ad34d`.

| Rank | Commit | Removes/bypasses `interrupt()` in the graph? | Evidence | Verdict |
|---|---|---|---|---|
| **1** | **`88ad34d`** | **Yes — removes the import + the `decision = interrupt(…)` call + the whole resume era; deletes the resume test, adds the queue test.** | §2 own‑eyes diff | **SEED** ✅ |
| 2 | `f283f77` | **No.** Adds dormant scaffolding (`approval_dispatch.py`, `execute_tool_guarded`, execute‑on‑approve dispatcher, claim‑expiry gate) but its diff never touches the live `interrupt(` call. Its own module docstring says: *"The cutover that retires `interrupt()` … builds + tests this in isolation"* — i.e. the author states the cutover is a **separate later** commit. Subject literally says **"(not yet wired)"**. | pickaxe hits are only `row.interrupt_id` field refs, not the call | Precursor / seed‑by‑intent, fails the gate |
| — | `b0b5760`, `95d92df` | After the cutover — a drain for pre‑cutover paused checkpoints, then deletion of the now‑dead resume dispatch (`route_approval_decision`, `CHANNEL_ORIGIN_HANDLERS`, `resolve`, `resume_turn`). | message scan + pickaxe | Post‑pivot cleanup, not the pivot |
| — | `c72cf66`, `5937e14`, `e6fde02`, `b8ae908` (4.A / "decisive‑cards", A2) | No. Nicer inline/NL/voice approval **UX**, but still resolved **through the interrupt/resume path** (they predate Phase 3 by a week; `ff36f2a` even files non‑blocking decisions as a *future* note). | message scan; dates 06‑17→06‑20 | Approval UX *inside* the blocking model; not the pivot |

**Why `f283f77` is not the seed despite being the migration's first commit:** it is
scaffolding that is deliberately inert — blocking mode is still fully operative after it
(`interrupt()` is still the live path). Calling it "the seed" would violate the explicit
confirm criterion. It is best described as the migration's **Step‑1 co‑seed by intent**, and I
flag it so the master can decide whether "the seed" should mean *first‑authored* (`f283f77`) or
*first‑effective* (`88ad34d`). My recommendation, per the criterion, is `88ad34d`.

---

## 4. Baseline commit & branch — `40758a9`

**Chosen baseline:** `40758a9` (the seed's **grand**parent), *not* the seed's literal parent
`f283f77`.

**Why deviate from "normally the seed's parent":** `f283f77` is itself the migration's Step‑1
commit — it already carries dormant non‑blocking scaffolding. That makes it a *contaminated*
"before" snapshot and a poor fit for a branch literally named `pre-migration-baseline`.
`40758a9` is the **last commit with zero migration scaffolding** and a fully coherent,
self‑consistent `interrupt()` blocking design — the truest record of "what was sound before."
Blocking mode is intact at both commits (`interrupt()` is live through `f283f77`), so `40758a9`
also satisfies the definition "the last commit where blocking mode was intact."

> If the master prefers the literal seed‑parent, re‑point in one command:
> `git branch -f research/pre-migration-baseline f283f77`. The architecture below is
> unchanged either way (the interrupt/resume path is byte‑identical between them; `f283f77`
> only *adds* unused files).

**Branch created & verified:**
```
refs/heads/research/pre-migration-baseline → 40758a9  ✅
current branch: main (unchanged — no checkout performed, working tree read‑only)
```

---

## 5. Baseline architecture sketch — how blocking approval worked (@ `40758a9`)

*(All citations are `file:line` at commit `40758a9`.)*

### 5.1 Graph topology & persistence
A single linear `StateGraph` compiled with an **`AsyncPostgresSaver`** checkpointer
(`graph.py:25,56‑85,147`). The checkpointer writes state to Postgres **after every node**, so a
turn paused mid‑graph survives process restarts (`graph.py:8‑10`).

```
START → memory_load → agent ──[should_continue]──┬─ tool_calls? → tool_executor ┐
                        ▲                         └─ none        → persist → compact → END
                        │                                                   │
                        └──────────[should_continue_tools]──────────────────┘
                            tool_executor loops to itself while the latest
                            AIMessage still has un-answered tool_calls;
                            otherwise returns to agent.
              ⏸  THE PAUSE lives *inside* tool_executor, on an APPROVE-tier call.
```

`build_graph()` wiring: `graph.py:117‑147`; routers `should_continue`
(`nodes.py:754‑759`) and `should_continue_tools` (`nodes.py:561‑581`). State schema
(`state.py:22‑53`): `messages` uses the `add_messages` reducer and is checkpointer‑managed;
`thread_id`/`platform`/`turn_started_at` etc. are per‑turn metadata. Thread identity is
**server‑authoritative** — `canonical_thread_id` returns `f"web:{channel_user_id}"` anchored to
the authenticated user, not a client‑minted id (`runner.py:116‑121`), carried into LangGraph as
`config={"configurable":{"thread_id":…}}` (`runner.py:102`). Recovery hatch `reset_thread`
deletes a poisoned thread's checkpoints (`graph.py:88‑97`).

**The pause is dynamic, not a static gate.** `compile()` is called with *only* the checkpointer
— there is **no `interrupt_before`/`interrupt_after`** on the graph (`graph.py:147`). The pause
is decided at runtime *inside* `tool_executor_node` by calling `interrupt()`, so which turns
pause depends on the safety classification of the specific tool call, not on a compiled edge.
The paused computation itself lives in four LangGraph Postgres tables — `checkpoints`,
`checkpoint_writes`, `checkpoint_blobs`, `checkpoint_migrations` (provisioned by Alembic
migration 002); `init_checkpointer()` runs from FastAPI lifespan startup (`main.py:139`), and the
Celery path re‑inits per task.

**Crucial invariant — one tool call per `tool_executor` invocation** (`nodes.py:282‑291`):
because `interrupt()` does **not** commit the node's partial return, processing multiple calls
in a loop and pausing halfway would, on resume, **re‑execute earlier calls** (e.g.
`email_send` twice). Doing exactly one call per invocation makes each invocation atomically
idempotent — state is committed *between* invocations, and the conditional edge loops back
until every call in the latest `AIMessage` has a `ToolMessage`.

### 5.2 What triggers an approval — the safety tiers
`SafetyClassifier.classify()` maps each tool call to one of four levels
(`safety.py:31‑92`): **SAFE** (execute silently), **NOTIFY** (execute then inform),
**APPROVE** (*pause via `interrupt()`, resume only on yes* — `safety.py:7`), **BLOCKED**
(never). Side‑effecting tools are APPROVE: `email_send`, `email_reply`, `calendar_create/
update/delete`, `whatsapp_send`, `booking_reserve`, … (`safety.py:60‑69`). **Unknown tools
default to APPROVE** — fail‑safe (`safety.py:85`). Args‑aware escalation only ever bumps *up*
(e.g. `telegram_send` to a non‑master chat → APPROVE; `safety.py:106‑122`).

### 5.3 Where `interrupt()` sits — the pause
Inside `tool_executor_node`, the APPROVE branch (`nodes.py:390‑433`):
1. **Idempotency guard** — `_find_pending_approval(thread_id, interrupt_id=tool_call_id)`
   (`nodes.py:397,786‑806`). Because the node re‑runs from the top on every resume, this skips
   a duplicate row + duplicate ping if one already exists (the "Jun‑11 double‑prompt" fix).
2. First pass only: `_create_pending_approval(…)` (`nodes.py:405,831‑852`) + a Telegram ping
   via `send_approval_request_to_master(…)` (`nodes.py:411`), optionally enriched with a
   calendar‑conflict warning (`nodes.py:401‑404,771‑783`).
3. **`decision = interrupt({type:"approval_required", approval_id, tool_name, tool_args,
   description})`** (`nodes.py:425‑433`) — snapshots state and exits the graph. On resume this
   same call *returns the resume value*.
4. Resume value routes the node: `revise` → discard card + `[REVISE]` marker so the agent
   re‑drafts (`nodes.py:439‑459`); `approved:false` → `[REJECTED]` ToolMessage
   (`nodes.py:461‑475`); `approved:true` → fall through to execute (`nodes.py:479‑558`). Any
   free‑text the master sent rides along as `user_msg` and is appended as a `HumanMessage`
   **after** the resolving `ToolMessage` (`nodes.py:435‑437`) to avoid orphaning the call.

### 5.4 Approval lifecycle — end‑to‑end trace
```
1. agent emits an AIMessage with a tool_call for an APPROVE-tier tool.        nodes.py:159,754
2. tool_executor classifies it APPROVE.                                       nodes.py:373,390
3. First pass: INSERT pending_approvals row (status="pending",               nodes.py:405,831
   interrupt_id = tool_call_id) + ping master on Telegram.                    nodes.py:411
4. interrupt(payload) → graph pauses; checkpointer persists the paused state. nodes.py:425; graph.py:8
5. _build_envelope reads task.interrupts → returns status="interrupted"       runner.py:1310-1324
   with the interrupt payload; run_turn returns it.                           runner.py:250-267
6. Surfaces to the master:
     • HUD/chat stream yields {type:"approval_required", content:payload}.    runner.py:536-537
     • Telegram already has the two-button Approve/Reject card.               telegram.py:152-160
     • Voice speaks the approval ask.                                         runner.py:1101-1106,605
7. Master decides →
     • button (HUD/Telegram): resolve_approval() claims the row, then         approvals.py:49-99,266-308
       resume_turn(thread_id, {"approved": …}).                              telegram.py:334-370
     • free text in-thread: run_turn detects the pause and calls              runner.py:210-215
       _resolve_pending → resolve_decision (LLM intent) → resume_turn.        runner.py:325-367
8. resume_turn: graph.ainvoke(Command(resume=decision)) re-enters the paused  runner.py:270-301
   tool_executor; interrupt() returns `decision`; the node executes /         nodes.py:434-475
   rejects / re-drafts.
9. On approve: execute tool → sanitize → archive → audit → (NOTIFY ping).     nodes.py:479-558
   Orphan guard ensures a ToolMessage always returns.                        nodes.py:522-557
10. Graph runs on to persist→compact→END; _build_envelope returns            graph.py:143-145
    status="complete". Row is "approved" (claimed in step 7).                 approvals.py:82-99
```
If a message arrives while paused and the resolver judges it *unrelated*, nothing resumes —
`_pending_interrupt_envelope` returns a gentle nudge and the card stays live
(`runner.py:210‑214,1262‑1280`).

### 5.5 State & persistence of an approval
`PendingApproval` (`db/models.py:118‑136`), table `pending_approvals`:
`thread_id` (idx), **`interrupt_id`** (the LangGraph resume token = the `tool_call_id`, the
link back to the paused checkpoint — `db/models.py:126`), `action_type`, `description`,
`payload` JSONB (`{tool_name, tool_args}`), `status` ∈
`pending|approved|rejected|discarded|expired` (idx, `db/models.py:130`), `expires_at` (idx),
`resolved_at`, `resolved_via` ∈ `telegram|web|whatsapp|system`. Composite index
`ix_pending_approvals_status_expires` powers the expiry sweep (`db/models.py:317‑319`).
`expires_at` is set to `now + APPROVAL_EXPIRY_HOURS` = **72h** (`nodes.py:844‑847`,
`config.py:379`). The paused **graph state itself** lives in the LangGraph checkpoint tables
(Alembic migration 002), separate from this row — the row is the human‑facing card, the
checkpoint is the resumable computation, and `interrupt_id` ties them together.

> **Baseline caveat (independently verified):** the "one pending row per `interrupt_id`"
> invariant is enforced *only in application code* (`_find_pending_approval`'s SELECT). There is
> **no DB guarantee** behind it — `status` is a bare `String(20)` (no enum/CHECK), and
> `(thread_id, interrupt_id)` has **no unique constraint** with `interrupt_id` itself **unindexed**
> (only `thread_id` is indexed) (`db/models.py:125‑130`). A concurrent double‑insert is not
> DB‑blocked. Noted as a pre‑existing property of the *baseline*, relevant to Phase 2.

### 5.6 HUD / dashboard consumption
`api/approvals.py`: `GET /pending` lists live cards (`:232`); `GET /inbound/next` serves the
oldest channel‑origin (inbound‑email) card one‑at‑a‑time (`:182‑214`); **`POST
/{approval_id}/decide`** is the button handler — it `resolve_approval()`s the row (an **atomic
claim**: conditional `pending→approved/rejected` UPDATE; "not_claimed" if already taken —
`:49‑99`) then calls **`resume_turn(thread_id, decision)`** (`:266‑308`). The returned envelope
can itself be `status="interrupted"` again if the resumed chain hits **another** approval
(chained HITL — `:22‑23`). `get_thread_decisions()` (`:104‑120`) feeds the in‑thread NL
resolver.

### 5.7 Telegram consumption
`send_approval_request_to_master` posts a two‑button inline keyboard whose `callback_data`
ferries `{"a":"approve"|"reject","id":approval_id}` (`telegram.py:152‑160`). The
`CallbackQueryHandler` parses it, edits the card to `✅ Approved` / `❌ Rejected`, calls
`resolve_approval(…, resolved_via="telegram")`, then resumes the graph via the channel resume
dispatcher (`telegram.py:334‑370`; docstring `:11‑13` names `route_approval_decision`).

> **Baseline caveats (independently verified):** (1) the button `CallbackQueryHandler` is wired
> on the **dev long‑polling** app only — in **webhook** mode `tg.normalize` returns `None` for
> `callback_query` updates and the endpoint silently `{"ok":true,"ignored":true}`s
> (`webhooks/telegram.py:72‑78`), so over the webhook the master can resolve only by
> natural‑language text or the web dashboard, not the buttons. (2) A natural‑language
> approve/reject arriving over Telegram is audit‑logged `resolved_via="web"` because
> `_resolve_approval_row` hardcodes it (`runner.py:319‑322`) — a channel‑attribution imprecision.

### 5.8 Voice consumption (brief)
`voice_turn` detects the pause the same way and *speaks* the approval ask
(`runner.py:938,1101‑1106`, `_approval_speech` `:605‑635`); hands‑free resolution routes through
the same `_resolve_pending`/`resume_turn` path (`runner.py:657‑686`).

### 5.9 Expiry sweep
Hourly `@critical_task` `sweep_expired_approvals` (`scheduler/tasks/approval_expiry.py`):
selects `pending` rows past `expires_at`, marks them `expired`/`resolved_via="system"`, then
**resumes each paused graph with a rejection** (`route_approval_decision(thread_id, platform,
{"approved": False, "reason": "…"})`, `:29‑58`) so no turn is left stuck mid‑graph. Fail‑loud
(alerts the master after 3 failed runs, `:4‑9`). It must `reset_async_state_for_task()` first
(`:30`) — the checkpointer is a per‑process singleton bound to the FastAPI startup loop, so a
Celery `asyncio.run()` would otherwise hit "Future attached to a different loop."

> **Baseline nit (independently verified):** the rejection reason string reads *"approval expired
> (no response within 24h)"* (`:55`) but the real window is **72h** (`APPROVAL_EXPIRY_HOURS`) — a
> stale user‑facing string in the baseline. Separately, an in‑code docstring at
> `approvals.py:237‑240` already says pending cards are swept by *"a Phase 3 Celery job"* — a
> small archaeological tell that the queue/Phase‑3 direction was anticipated **before** the
> cutover.

### 5.10 What the blocking design *guaranteed* (descriptive — not a soundness verdict)
- **No side effect without an explicit "yes":** the side‑effecting tool call runs only after
  `interrupt()` returns `approved:true` — the send physically cannot fire before approval
  (`nodes.py:425‑476`).
- **Exactly‑once execution:** one‑call‑per‑invocation + commit‑between‑invocations means a
  resume cannot re‑run an already‑executed call (`nodes.py:282‑291`).
- **Durable across restarts:** the paused turn is a Postgres checkpoint; the process can die
  and resume later (`graph.py:8‑10`).
- **Single source of truth for "is it paused":** a *genuine* `task.interrupts`, not a bare
  `state.next` — barge‑in residue is disambiguated (`runner.py:1131‑1160`).
- **One unified envelope** across text/stream/voice/resume (`runner.py:1283‑1336`).

**Costs the code itself acknowledges (descriptive):** the turn is *blocked* until the card
resolves (the very thing the migration set out to change); the node re‑runs top‑to‑bottom on
every resume, so the whole APPROVE branch (row‑create + master‑ping) would re‑fire without the
idempotency guard — *"27 rows for ~14 requests"* before it was added (`nodes.py:389‑396,789‑795`);
one‑call‑per‑invocation means *N* tool calls = *N* checkpoint commits + *N* self‑loop hops
(`nodes.py:282‑291`); *"one interrupt pauses at a time"* (`runner.py:311`) — strictly one
outstanding decision per thread, with **no graph‑level concurrency gate** if two turns hit the
same `thread_id`; every fresh turn must repair barge‑in "cancellation residue"
(`runner.py:1163‑1244`); and the async‑loop rebind hazard means any non‑lifespan entry point
(Celery) must rebind the checkpointer first. The resume path's fragility class is named in‑diff
at the cutover itself ("orphaned tool_calls, resume‑fail, async‑rebind‑on‑resume").

### 5.11 Independent verification of this sketch
This baseline map was cross‑checked by an 8‑agent fan‑out (7 subsystem readers + 1 synthesis/
completeness critic), each constrained to the **isolated baseline worktree** (no git, no access
to post‑migration code) — 0 errors, ~528K tokens. The critic independently reproduced the
end‑to‑end lifecycle trace and topology above and **confirmed every load‑bearing claim** (the
`interrupt()` pause site, one‑call‑per‑invocation exactly‑once, the atomic `resolve_approval`
claim, `task.interrupts` pause detection, the four‑tier safety model). It surfaced **no
contradiction** with §5.1–5.10; it did catch a *stale in‑code docstring* (`approvals.py:237‑240`,
"no sweeper / a Phase 3 job will sweep") that contradicts the *live* hourly sweeper this report
documents in §5.9 — i.e. the sweeper exists at baseline. The small pre‑existing baseline
imperfections it verified (app‑level‑only idempotency, 24h/72h string, Telegram‑webhook button
gap, description divergence, `resolved_via` attribution) are captured inline in §5.5/5.7/5.9 and
belong on the **Phase‑2 watchlist** — so the audit can tell *pre‑existing* issues apart from any
the migration introduced.

---

## 6. Handoff to Phase 2 (no soundness conclusions yet)
With the pivot fixed and the baseline branched, Phase 2 can diff `40758a9` (or `f283f77`) →
`88ad34d`+`b0b5760`+`95d92df` and interrogate the **seed decisions**: replacing the durable
`interrupt()` pause with a queued claim‑gated dispatch; where "no‑execute‑without‑yes" and
"exactly‑once" now live once the graph no longer holds the paused computation; and whether the
guarantees enumerated in §5.10 are preserved, relocated, or lost. **Deferred to Phase 2 per the
gate.**

---

## 7. 📍 Status
- **Pivot located & confirmed with own eyes.** Seed = **`88ad34d`** (retires `interrupt()` from
  the live path — import + call removed, resume era deleted, resume‑test→queue‑test swap).
- **Baseline = `40758a9`** (pristine pre‑migration); branch **`research/pre-migration-baseline`
  created & verified**; `main` untouched.
- **Ambiguity flagged:** `f283f77` is the migration's first‑authored (but inert) commit;
  recommend `88ad34d` as the seed per the confirm criterion. Master may re‑point the baseline to
  `f283f77` if "seed‑parent" is preferred (design is identical).
- **Reading rule honored:** no `handoff/`, `docs/testing/`, `commits.md`,
  `architecture_needs_revision.md`, or post‑migration source read as implementation.
- **STOP — awaiting the master's confirmation of the pivot before Phase 2.**
