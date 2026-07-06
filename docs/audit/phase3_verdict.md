# Phase 3 — Verdict: the actual migration, graded against the frozen ideal

**Mission:** unblind, read the real migration, and grade it against the frozen Phase‑2 ideal
(`phase2_ideal_design.md` — unchangeable; deviations are graded, not absorbed). The master suspects
drift; my job is the evidence, including the possibility he's wrong.

**Author:** research/audit agent. **Date:** 2026‑07‑05. **Scope:** seed `f283f77`/`88ad34d` →
HEAD `6f356c0`.

**Reading order followed (as instructed):** (1) seed diffs `f283f77`+`88ad34d` (own eyes) — seed
grade formed *before* reading any outcome; (2) the migration walk — the `approvals(Phase3)` run, the
queue‑coupling era, the A1 loop rework, the A2 "approval‑as‑message"/seal, the B1 consent work — via
`commits.md`, `handoff/agent_drift_catalog.md`, `handoff/jarvis_redesign_roadmap.md`,
`handoff/migration_nonblocking_approvals.md`, `docs/testing/manual_verification_plan.md`; (3) HEAD
code last. A 7‑reader era‑walk fan‑out cross‑checked the first‑hand reading.

---

## 1. Verdict in one line

> **The seed was PARTIALLY SOUND; the drift is REAL and the master is right to suspect it — but it
> is a *later* fold, not a fatal seed decision, and the author has already been self‑correcting
> toward (independently, the same design as) the frozen ideal. HEAD CONVERGES on the spine and
> consent, and still DIVERGES on exactly‑once hardening and migration discipline.**

**Classification: `drifted-later` — origin at a seed *surfacing* decision, destructive in the
queue‑coupling era, ~70% self‑corrected by HEAD.** Not `seed-sound` (a seed decision seeded the
drift); not `drifted-at-seed` in the fatal sense (the seed's core *mechanism* was sound and matches
the ideal).

```
 SEED (Jun 24)          QUEUE-COUPLING ERA          A1 LOOP REWORK        UN-COUPLING (Jun 29-Jul 4)
 88ad34d [QUEUED]  ──►  7e686b6 present-in-moment ─► 7c6c2d9/10e7431  ──► c73f20e in-graph resolve
 answer-in-turn         presented_approval_id        (fighting the        cd1a732 "the seal"
 (SOUND, = ideal)       + out-of-graph resolve       queue-marker         5f9b374 "consent vs
 + QUEUE surfacing      + queued_finish canned        fragility)           conversation, not queue"
   (the drift seed)     closing (THE FOLD)                                08449b5 retire coupling
                                                                          (INCOMPLETE at HEAD)
        └──────────────── the author's §3 "unifying root class" ─────────────────┘
                    "out-of-graph response paths that bypass the brain/checkpoint"
                    = the exact INVERSE of the ideal's axis A + axis E
```

---

## 2. The seed — PARTIALLY SOUND (evidence from `f283f77` + `88ad34d`, own eyes)

### What the seed got RIGHT (convergent with the ideal)
- **Retire `interrupt()` by ANSWERING the tool‑call in‑turn.** The APPROVE branch writes the row,
  pings the master, and **returns a `[QUEUED]` `ToolMessage` so the turn completes cleanly** —
  *"NO side effect fires in this turn"* (`88ad34d`, `nodes.py` APPROVE branch; the diff removes
  `from langgraph.types import interrupt` and the `decision = interrupt(…)` call). This is
  **identical to the ideal's spine mechanism** ("propose‑then‑answer‑in‑turn → clean checkpoint →
  non‑blocking is structural"), and the commit names the same win: *"kills its whole fragility class
  (orphaned tool_calls, resume‑fail, async‑rebind‑on‑resume)."* ✅ Sound.
- **One unified claim‑gated dispatch.** `resolve_and_dispatch` — *"THE single claim‑then‑dispatch
  gate every transport calls … structurally impossible to dispatch an unclaimed approval"*
  (`approval_dispatch.py:43`). This is the ideal's "one dispatcher, one atomic claim." ✅ Sound.
- **Generalize the already‑non‑blocking inbound pattern to all approvals** — `dispatch_approval`
  routes email rows to the untouched inbound handler and tool rows to `execute_tool_guarded`
  (`f283f77` `approval_dispatch.py`). This is the ideal's central thesis. ✅ Sound.

### What the seed got WRONG or deferred (the seeds of the drift)
1. **The card is surfaced OUT‑OF‑GRAPH as a QUEUE artifact, not as a brain message.** The seed's
   model is *"queue a row → surface it by polling `GET /approvals/queue` → resolve via Approve/Reject
   buttons"* (`88ad34d` retires `interrupt()` in favour of a queue; `acfdfaf` adds the unified queue
   read). The prompt still says *"a card with Approve / Reject"* (`88ad34d` `prompts.py`). This is
   the **inverse of ideal axis A** (the card must be a brain‑authored `AIMessage`, R2/R10/R11). **This
   surfacing decision is the drift's origin.**
2. **Exactly‑once is SINGLE‑LAYER (at‑most‑once), not the ideal's fused claim+lease+idempotency.** The
   dispatcher's own words: *"IDEMPOTENCY is the CALLER's job … the atomic claim gates this … never
   re‑claims"* (`f283f77` `approval_dispatch.py:26‑30`). No lease, no idempotency key, no
   `dispatch_status`, no in‑doubt reconciliation. A crash between claim and provider‑send leaves
   `status=approved` with the action never run and no reaper — a **silent lost send** (my red‑team
   RT‑X4). The author later admits it: *"at‑most‑once execution"* (`migration_nonblocking_approvals.md`
   §3). This *inherits* the baseline's under‑hardening rather than introducing new drift — but it is
   below ideal axis C, and **it was never closed** (§4).
3. **Word/voice consent REGRESSED at the seed.** `88ad34d` deleted `run_turn`'s natural‑language
   resolver (`_resolve_pending`) and left a *legacy nudge*; resolution became button‑only, with
   word/voice consent to be rebuilt later. (Below ideal axis E, temporarily.)

**Seed grade: partially sound.** The retire‑interrupt *mechanism* is sound and convergent; the
*out‑of‑graph queue surfacing* choice + deferred consent/hardening are what the master calls the
"queue‑coupling era," and they seeded what followed.

---

## 3. The fold — where the architecture bent away from sound

### The bend: out‑of‑graph resolution coupling
The seed's "surface/resolve out‑of‑graph" choice was **deepened, in the queue‑coupling era, into a
resolution model that couples consent to a stale *queue position* rather than the conversation.** The
precise mechanism (independently pinned by the era‑walk): the client derived
**`presented_approval_id = items.find(first pending) = the OLDEST pending card`** (`useJarvis.ts:331`),
re‑derived on *every* message, and shipped it as the resolve **target**; the backend **trusted it
verbatim** (*"a valid generic verb approves whatever card it is handed"*, `agent_drift_catalog.md:527`).
Three surfaces embody the coupling:
- `7e686b6` (3B) "present‑in‑moment" — the just‑queued card is an **ephemeral `approval_required`
  event of tool_args, deliberately *not* checkpointed** (no card↔message link).
- The **`presented_approval_id` pointer** + the `_presented_disposition` shortcuts in `runner.py`
  (`stream_turn`/`voice_turn`) that `yield done; return` **before the graph runs**.
- The **`queued_finish` canned closing** (`7c6c2d9`/`10e7431`) that replaces the agent's synthesis
  with a template.

`c73f20e` moved resolution *into* the graph (`card_resolution_node`) — a real CONVERGE on the spine
(persisted, checkpointed, strong‑judged; it killed the D2/D3/NV1 data‑loss class) — **but it read the
target from `state['presented_approval_id']`, so it *entrenched* the pointer‑as‑target divergence that
directly produced D15.** `cd1a732` "the seal" was a **mitigation, not a cure** — a 151‑line deterministic
token‑matcher (`_names_mismatched_target`/`_card_distinguishing_text`) that still keyed off the
client pointer and *over‑refused* (D25's false `named_mismatch` deadlock). The **true unfold deleted the
seal wholesale**: `5f9b374`+`08449b5` replace the pointer with a **code‑owned conversation referent**
walked from the most‑recent `jarvis`‑linked approval *message* + a `jarvis.solicited` dispatch anchor —
*"exactly the ideal A/E model."*

**The author diagnosed this himself — and his diagnosis is the exact inverse of the ideal.**
`agent_drift_catalog.md` §3 "The unifying root class":
> *"The migration introduced **out‑of‑graph response paths** that bypass the agent's brain and/or the
> checkpoint … D1 — `queued_finish_node` replaces the agent's synthesis with a canned closing
> (bypasses the BRAIN). D2/D3 — the presented‑card disposition shortcuts return before the graph runs
> (bypass the BRAIN AND the checkpoint)."*

The ideal's axis A (card = brain message from the graph) and axis E (consent resolved *in‑graph, over
the conversation*) are precisely the two things the fold violated.

### The critical consequences (the D‑codes = my red‑team, hit for real)
| Author's bug | What happened | Frozen‑ideal axis violated | My red‑team predicted it |
|---|---|---|---|
| **D15/D16 (Critical)** | *"'Send it' resolved + SENT the WRONG card"* — a stale `presented_approval_id`; *"the node trusts the passed id without checking it matches the conversational referent … the claim gate held (at‑most‑once) but on the WRONG card."* An email the master believed rejected went out. | E — ordinals/referent must bind to the narration epoch; ASK on mismatch/>1; never guess | **RT‑CS2** (ordinal drift → wrong card) |
| **D24 (Critical, "yes‑trap")** | A deterministic read‑back solicited consent *for the exact action the master was rejecting*; one "yes" would SEND it. | E — edit/reject terminates consent; strict unified bar | **RT‑CS1/RT‑CS5** (edit/soft‑affirm) |
| **D26** | Paraphrased repeat → supersede‑mint → *"invites consent on UNSEEN content … the Ideal PDF's blind‑approval risk."* | E — never solicit/send unseen; seen a dispatch‑gate | **RT‑P1** (seen‑gate must be universal) |
| **D19 / D1 / D2** | Proactive/approval/answer text shown but **not persisted** → vanishes on refresh; canned closings. | A — the card/answer must be a persisted brain message | (my message‑first spine) |
| **D18** | Raw `<tool_output trust="untrusted">` wrapper rendered to the master and stored as `outcome_detail`. | D/injection — single‑source clean body; untrusted‑as‑data | **RT‑critic #4** (injection) |
| **D22 (High)** | A malformed `llama` tool_call orphans the checkpoint → 400 bricks the thread. | (model‑layer; both the migration *and* the ideal under‑address a malformed‑tool‑call orphan) | — (a gap in my ideal too) |

**Where the fold sits, precisely:** the *origin* is a **seed surfacing decision** (`88ad34d`/`acfdfaf`
— surface/resolve out‑of‑graph). It became **destructive in the queue‑coupling era** (`7e686b6` →
the `presented_approval_id`/`_presented_disposition` machinery → the `queued_finish` canned closing),
which produced the critical wrong‑card/vanishing/yes‑trap bugs. There is **no single "twist‑everything"
commit**; the twist is the *pattern* — treating the approval as a queue position resolved out‑of‑graph
instead of a conversation message resolved in‑graph.

### The correction (the un‑coupling — toward the ideal)
The author recognized the root class and spent Jun 29–Jul 4 un‑coupling it — *toward the frozen ideal*:
- `c73f20e` — **presented‑card resolution runs through an in‑graph `card_resolution_node`** (persisted,
  claim‑gated, strong‑judged). → ideal E (consent in‑graph).
- `cd1a732` — **"the seal"**: resolve only the authoritative live card the master referred to; **refuse
  on >1 / mismatch**. → ideal E (ASK on ambiguity, never guess).
- `28edc4b` — **compaction keeps messages whose approval is still pending.** → ideal A/E (pin the card
  message).
- `5f9b374` — **"consent resolves against the conversation, not the queue."** → ideal E, verbatim.
- `08449b5` — **"retire the presented‑card coupling."** → ideal A (un‑couple from the queue artifact).
- `81c4016`/`23785e7`/`f8ec0f5` — **edits supersede their exact target, re‑emit through the mint path,
  never leave a stale invite.** → ideal E (edit terminates consent, re‑mint).
- `nodes.py:1231` — the approval card is now minted as **`AIMessage(…, additional_kwargs={"jarvis":
  {approval_ids…}})`** — a **brain message in the stream** carrying the row linkage. → ideal A.

---

## 4. Convergence — HEAD vs. the ideal, axis by axis

| Ideal axis | HEAD position (file:line) | Grade |
|---|---|---|
| **A — card is a brain message; propose‑then‑answer‑in‑turn; non‑blocking structural** | `interrupt()` fully retired; `[QUEUED]` answers the tool‑call in‑turn → clean checkpoint, non‑blocking structural (converged). The card is a persisted `AIMessage` + `additional_kwargs.jarvis` linkage, compaction‑pinned (`nodes.py:1231`,`28edc4b`,`nodes.py:1810`). **But its content is a code‑composed *narration* ("I've queued it for your approval, Sir — shall I go ahead?") that *links* to the row; the send body lives in `row.payload` and is surfaced separately.** | **CONVERGED on the mechanism; PARTIAL on content** — the message is a link+narration, not the brain‑authored card body the ideal specifies (the body is row‑sourced, which is fine for single‑source, but the "message IS the card" identity is only half‑realized). |
| **B — one hardened row; provenance link; live ordinals; read via one service** | Row is the *"operative record … source of truth"* (`models.py:140`); the MESSAGE links to the row via `additional_kwargs.jarvis` (inverse of the ideal's `card_message_id`, same effect); `approvals_service.list_pending_cards` is the one shared read (`b18aa9a`). **But no `seq`, no `card_message_id` column, no `mode`.** Referent uses a conversation‑message anchor instead of a `seq` ordinal. | **PARTIAL** |
| **C — fused claim+lease; provider timeout < TTL; fenced writes; provider‑native idempotency; in‑doubt reconcile; reaper** | `resolve_and_dispatch` = **claim → dispatch → record_outcome, SINGLE‑LAYER** (`approval_dispatch.py:43`). No lease, no `idempotency_key`, no `dispatch_status`, no reaper. `EmailSendUncertain → "unconfirmed"` is surfaced honestly but **not reconciled**; a re‑approve can double‑send; a crash‑in‑doubt loses the send. Author admits *"at‑most‑once."* | **DIVERGED / UNCLOSED** — the one axis the migration never addressed. |
| **D — one read + one dispatcher; single‑source body; one resolution path** | Every channel funnels through the one `resolve_and_dispatch` claim gate (`telegram.py:248`, `approvals.py:259`, `card_resolution_node`); the body is dispatched **verbatim from `row.payload`** (single‑source ✓). HUD **retains Approve/Reject buttons** (`ApprovalCard.tsx:131`); two grounding paths (in‑graph vs out‑of‑conversation) not fully unified like the ideal's ResolutionEvent. | **CONVERGED** (with a button/word divergence from R10 — see §8). |
| **E — strong‑model consent; deterministic pre‑gate; strict unified bar; multi‑card selector anchored + ASK; seen a dispatch invariant; edit terminates consent** | `card_resolution_node` in‑graph, **strong model** (`runner.py:391`); the seal refuses on >1/mismatch and *asks* (`nodes.py:1444`); consent over the **conversation** (`_resolve_conversation_target`, `5f9b374`); **unified strict bar** (`5c0e385`/`3aa29fb`); edit supersedes exact target (`81c4016`); **dispatch safety rests on the structural `jarvis.solicited` anchor** — an unanchored "yes" confirms but *never dispatches* (`nodes.py:1237`) — with the solicitation‑regex demoted to interim "persona‑lint" (`nodes.py:298`, side‑doors D27/D28 still open). | **CONVERGED on the single‑turn mechanisms** — and *more battle‑tested than the ideal* on edge cases. **Two real gaps:** (1) "seen" is a *solicitation‑time* guard (never invite on unseen), not a hard *dispatch‑time* seen‑flag (the Telegram button path *"skips the LLM"*); (2) **consent is STATELESS single‑shot** — it refuses on ambiguity but there is **no conversational‑disambiguation state**, so a clarifying follow‑up ("i meant the approval for timmy") misroutes (D24). The ideal's *stateful* "ASK, then resolve the follow‑up against the ASK" is the author's **"B1," which is a frozen design on the roadmap, NOT yet implemented.** |
| **F — strangler; per‑action_type flag; immutable mode; drain‑before‑retire; validated** | **Big‑bang cutover** (`88ad34d` retired `interrupt()` for all APPROVE tools at once; drain `b0b5760` ran *after*); **no per‑action_type flag, no immutable `mode`.** *"The whole migration was exercised only on the fallback model (`gpt-4o-mini`)"* — never re‑verified on the `llama` primary (`migration_nonblocking_approvals.md` §6). | **DIVERGED** — riskier discipline; a real verification debt. |

**Net:** HEAD converges strongly on A, D, E; partially on B; diverges/unclosed on C and F. The
un‑coupling is **incomplete** — `presented_approval_id` residue still threads through `runner.py` /
`nodes.py` / `state.py` (full retirement is deferred to a future "A4"), and stale in‑code comments
remain (`approvals.py:15` still says "resume graph"; `graph.py` docstring omits the new nodes).

---

## 5. The striking finding: the author independently re‑derived the ideal

This is the strongest evidence that the ideal is the *right* target and that the drift is real. Working
from the **same requirement PDF** (the drift catalog cites *"the Ideal PDF's blind‑approval risk"* at
D26) and hitting the failures in production, the author's redesign vocabulary converged on the frozen
ideal's exact positions — arrived at from the opposite direction:
- Ideal axis A ("the card IS a brain message") ⇔ author: *"A2 = approval message"*, *"approval IS the
  message"* (NV3), *"synthesize in‑graph AND persist"* (§3).
- Ideal axis E ("consent in‑graph over the conversation; ASK on ambiguity") ⇔ author: *"consent
  resolves against the conversation, not the queue"* (`5f9b374`), the seal's *"refuse on >1/mismatch"*.
- Ideal §3 root‑class ⇔ author §3 root‑class — the *same* diagnosis (out‑of‑graph paths bypassing
  brain/checkpoint), stated independently.

The author even validated the ideal's axis B by *rejecting* the opposite. The redesign roadmap's first
draft proposed *"retire the queue; store the payload in the checkpoint blob with a lightweight
idempotency ledger"* — then **recanted under senior‑engineer review**: *"That was an over‑correction and
is wrong — a payload persisted in a checkpoint blob that code parses + dispatches from IS a DB record"*
→ the hybrid *"kill the coupling, keep the record"* (`jarvis_redesign_roadmap.md:34‑40`). That is
exactly the ideal's axis B: **un‑couple the surfacing, keep the one hardened row as the operative
record.**

Two audits, blind to each other, landed on one architecture. That is not a coincidence; it is the
design the requirements imply.

> **Independent cross‑check.** A 7‑reader era‑walk (queue‑coupling · loop‑rework · consent/outcomes ·
> un‑coupling · author‑drift‑record · HEAD · failure‑record), run blind to this write‑up, converged on
> the same conclusions: the fold is the presented‑card/queue‑position coupling
> (`presented_approval_id`=oldest, trusted verbatim), `c73f20e` converged‑but‑entrenched, `cd1a732` was
> a mitigation the true unfold (`5f9b374`/`08449b5`) deleted, exactly‑once stays at‑most‑once, and the
> current consent (A2) is stateless with the stateful layer (B1) still on the roadmap.

---

## 6. Verdict + path

- **Seed:** **partially sound.** The retire‑interrupt mechanism (`[QUEUED]` answer‑in‑turn, unified
  claim‑gated dispatch, generalize inbound) was sound and convergent. The **out‑of‑graph queue
  surfacing** decision seeded the drift; exactly‑once was under‑hardened; word‑consent regressed.
- **The fold:** **drifted‑later.** Origin at the seed *surfacing* decision (`88ad34d`/`acfdfaf`),
  **destructive in the queue‑coupling era** (`7e686b6` → the `presented_approval_id`/
  `_presented_disposition` out‑of‑graph resolution + the `queued_finish` canned closing), producing
  the Critical wrong‑card (D15/D16), yes‑trap (D24), unseen‑solicit (D26), and vanishing‑turn (D19)
  bugs. The author named the root class (§3) and has been un‑coupling toward the ideal since
  `c73f20e`.
- **Convergence:** HEAD **converges** on the spine (A), consent (E), dispatch/read (D); **partial** on
  state/provenance (B); **diverges/unclosed** on exactly‑once (C) and migration discipline/verification
  (F). The un‑coupling is **~70% done** (residual `presented_approval_id`; deferred "A4").
- **Is the master right to suspect drift?** **Yes — the drift was real and, at its worst, Critical**
  (an email actually sent on the wrong card). **But** it was a later fold, not a fatal seed decision,
  the seed's core mechanism was sound, and the author is already self‑correcting toward the same design
  this audit derived blind. The suspicion is correct; the *shape* is "drifted‑later, largely
  self‑corrected," not "rotten from the seed."

---

## 7. Salvageable vs. not (against the frozen ideal)

**Salvageable — keep (already IS the ideal, arrived at independently):**
- The `[QUEUED]` answer‑in‑turn clean‑checkpoint mechanism (non‑blocking is structural). *(ideal A)*
- The card‑as‑brain‑message with the `additional_kwargs.jarvis` linkage + compaction‑pin. *(ideal A)*
- The in‑graph `card_resolution_node`: strong‑model, consent‑over‑conversation, the seal (ASK on
  >1/mismatch), the solicitation contract, edit‑supersedes‑exact‑target. *(ideal E — battle‑tested)*
- The single `resolve_and_dispatch` claim gate + `approvals_service` shared read + single‑source body
  from `row.payload` + the executed/failed/**unconfirmed** outcome lifecycle. *(ideal B/D)*
- The code‑enforced completeness guard (`119f16d` validate‑recipient‑before‑queuing). *(ideal E)*

**Not salvageable as‑is — needs the ideal's hardening:**
- **Exactly‑once (axis C).** The at‑most‑once claim needs the fused claim+lease, `T_req < lease TTL`,
  fenced terminal writes, provider‑native idempotency (Calendar supplied‑id / email `rfc822msgid`
  read‑back), an **`in_doubt` state with a master‑facing exit**, and a reaper. Today a crash‑in‑doubt
  loses a send and a re‑approve can double‑send — **open at HEAD.**
- **The `seen` gate.** It is a *solicitation‑time* guard, not a hard *dispatch‑time* invariant; the
  ideal makes never‑send‑unseen a dispatch‑time refusal on every path (incl. the button/Telegram
  path, which currently *"skips the LLM"*).
- **The residual out‑of‑graph coupling.** `presented_approval_id` / `_presented_disposition` residue
  should complete its retirement (the author's deferred "A4"); the HUD button path should enforce the
  same dispatch‑time guards as the word path.
- **Provenance/state (axis B).** No `seq` (referent leans on a conversation‑message anchor — works,
  but the ideal's monotonic `seq` is more robust under out‑of‑order resolution); no `mode` (moot now,
  but the big‑bang cutover carried the risk the ideal's per‑row `mode` was designed to remove).
- **Verification debt (axis F).** The migration was **never validated on the `llama` primary** — the
  open‑weights malformed‑tool‑call orphan (D22) is a live hazard that *neither* the migration *nor*
  the ideal fully addresses (an honest gap in my Phase‑2 design too).

---

## 8. Two honest caveats on my own grading

1. **The button/word fork (my flagged open question) went the other way.** HEAD keeps HUD Approve/Reject
   buttons *and* word consent; my ideal recommended word‑only per R10. The requirement's "button or
   word" is *satisfied*; R10's "no HUD buttons" is not. This is a **defensible product choice, not a
   drift** — I grade it neutral, and note my ideal's word‑only stance was a recommendation, not a
   requirement.
2. **My ideal shares one gap with the migration.** Both under‑address the **malformed‑tool‑call orphan
   from an open‑weights primary** (D22). My "answer‑in‑turn → clean checkpoint" assumes a *well‑formed*
   tool_call; a `llama` `tool_use_failed` orphans the checkpoint regardless of the approval design.
   The migration's `9a7869e` (mint‑time repair + load‑time strip) is a real fix my ideal did not
   specify. Credit where due.

---

## 9. 📍 Status
- **Verdict:** **partially‑sound seed → drifted‑later (queue‑coupling / out‑of‑graph resolution) →
  ~70% self‑corrected toward the frozen ideal.** The master's drift suspicion is **correct** (real,
  at‑worst‑Critical drift), with the precise shape and the exact fold commits documented above.
- **Convergence:** A/D/E converged, B partial, **C (exactly‑once) and F (migration discipline +
  primary‑model validation) still open** — the two things worth hardening next, per the ideal.
- **Independent‑design validation:** the author, blind to this audit and working from the same
  requirement PDF, re‑derived the ideal's spine and consent model — strong evidence the target is
  right.
- **Read‑order honored:** seed graded before its outcome was read; HEAD read last.
- **STOP — no fixes, no tickets, no code**, per instruction.
