# Phase 4 — The Convergence Map

**Purpose:** measure, element by element, how much of the frozen Phase‑2 ideal (and each Ideal‑PDF
requirement) exists in the current implementation — so the master knows exactly where the build
stands, what remains, whether the remainder is *planned* or *unplanned*, and in what order to close it.

**Author:** research/audit agent. **Date:** 2026‑07‑05. **Read‑only; no fixes, tickets, or code.**
**Yardstick:** `phase2_ideal_design.md` (frozen, unamendable) + `Research_docs/Jarvis_Ideal_Feature_Set.pdf`.
**HEAD audited (pinned):** `6f356c0` — *"hold inbound auto‑drafting off until inbound cards can link to
the conversation"* (2026‑07‑04).
**Plan of record:** `handoff/jarvis_redesign_roadmap.md` + the frozen `handoff/b1_research_split_decision_log.md`
(B1 = Phase‑B, design‑frozen 2026‑07‑05, **awaiting the master's word — not built**).

---

## 0. Method, counting rule, and the two re‑verified claims

**Status vocabulary (one per element, evidence‑cited):** `CONVERGED` (exists at HEAD, proven) ·
`PARTIAL` (which half exists / which is missing) · `MISSING‑PLANNED` (absent at HEAD, covered by
in‑flight design) · `MISSING‑UNPLANNED` (absent, in no plan) · `DIVERGED` (HEAD does the contrary).

**Counting rule for the percentages:** each element scores **CONVERGED = 1.0, PARTIAL = 0.5, all
others = 0.0**; **convergence % = Σ score ÷ element count**, equal‑weighted (no element is weighted
above another — a fine‑grained hardening item counts the same as a spine item, so read the axis
breakdown, not just the headline). Separately I report **planned‑coverage** of the remainder (how much
of the non‑CONVERGED is already designed), because a MISSING‑PLANNED gap is a very different status
from a MISSING‑UNPLANNED one.

**Evidence base:** first‑hand reads of HEAD + a 6‑reader per‑axis evidence fan‑out (file:line);
2 of the 6 readers died on a transient "connection closed" API error and were re‑run. All file:line
below is at `6f356c0`.

### The two Phase‑3 claims, re‑verified fresh at HEAD
1. **"Can any sweep re‑open a claimed row, or is crash‑in‑doubt purely at‑most‑once?"** → **Purely
   at‑most‑once; no recovery.** The *only* sweep is `approval_expiry.sweep_expired_approvals`, which
   selects `status=='pending' AND expires_at<now` and flips them to `'expired'` — it **never touches an
   `approved`‑but‑undispatched row** (`approval_expiry.py:34‑46`). `resolve_and_dispatch` is
   single‑layer: the atomic claim writes `status='approved'` (`approvals.py:95`), dispatch then
   overwrites the *same* column to `executed|failed|unconfirmed` (`approval_dispatch.py:145‑162`).
   There is **no `dispatch_status`/lease column and no reaper**, so a crash between claim and provider
   send strands the row at `'approved'` permanently, with the action never executed and nothing to
   recover it. **Confirmed at‑most‑once, silent lost‑send on crash.**
2. **"The exact location of the `presented_approval_id` residual."** → **My Phase‑3 claim was
   imprecise; correcting it here.** At HEAD `presented_approval_id` (the client pointer) is **fully
   retired** — it survives only as *retirement comments* (`state.py:73`, `useJarvis.ts:327`). What
   remains is the differently‑named in‑graph judge `_judge_presented` (`runner.py:761`, called by
   `card_resolution_node` at `nodes.py:1548`), which resolves against the **conversation referent**
   (the converged path, *not* residue), plus the client‑only `presented_nav` skip event. The
   un‑coupling is **more complete** than Phase‑3 stated.

---

## 1. Headline

> **Overall convergence ≈ 56–59% (equal‑weighted; 56% incl. the migration‑process axis, 59% on architecture+PDF).** The **spine (A) and consent mechanisms (E‑core) are
> converged**; **state/exactly‑once (B/C) is the atomic‑claim floor without the hardening**; **channel
> and capability breadth (D/PDF) is largely designed‑not‑built.** Of the ~42% remainder, **~60% is
> MISSING‑PLANNED** (B1 stateful consent, B3 card‑from‑row, C1–C4 capability, Phase‑D, NV4 model
> validation) and **~40% is MISSING‑UNPLANNED** — dominated by one cluster: **exactly‑once hardening
> (axis C), which roadmap §7 deliberately declares "solved" and my re‑verification shows is not.**

Per‑axis convergence (counting rule above):

| Axis | Convergence | One‑line |
|---|---:|---|
| **A** Graph topology / spine | **~69%** | interrupt() gone, card‑is‑a‑message, non‑blocking structural — but `message_repair` kept, no reaper/FIFO |
| **B** State model | **~39%** | hardened‑enough row + shared read + message↔row link; no `seq`/`idempotency_key`/`dispatch_status`/`mode`/constraints |
| **C** Exactly‑once | **~36%** | atomic claim + provider timeout + never‑blind‑retry present; **no lease, no provider idempotency, no reaper** |
| **D** Channels | **~60%** | one read + one dispatcher + single‑source body + alerts→HUD; HUD buttons live, no ResolutionEvent, webhook callback broken |
| **E** Consent | **~50%** | strong‑model judge, seal (ASK‑on‑ambiguity), strict bar, edit‑supersedes — but **stateless** (B1 adds state), no multi‑card/kind‑scope/epoch‑bind |
| **F** Migration (process) | *n/a* | migration **complete** (big‑bang, not strangler); discipline diverged; **primary‑model validation pending (NV4)** |
| **PDF** requirements | **~76%** | autonomy/email‑core/briefing/alerts converged; no‑buttons, real‑handles, complex‑summary, events‑as‑messages planned |

*(Axis F measures migration **process**, not architecture; it's complete but diverged from the
strangler ideal, so its % would mislead — reported qualitatively.)*

---

## 2. The status table (every element, evidence‑cited)

### Axis A — graph topology / spine
| # | Element | Status | Evidence (HEAD `6f356c0`) / plan |
|---|---|---|---|
| A1 | `interrupt()` deleted / no pause | **CONVERGED** | `nodes.py:827` (APPROVE queues, no interrupt); `graph.py` no `interrupt_before` |
| A2 | in‑graph consent gate before agent | **CONVERGED** | `card_resolution_node` at `graph.py:147`, `nodes.py:1501` |
| A3 | tool‑call answered in‑turn (`[QUEUED]`) → clean checkpoint | **CONVERGED** | `nodes.py:959`; `should_continue_tools`→`queued_finish` |
| A4 | card is a brain `AIMessage` linked to the row | **CONVERGED** | `nodes.py:1231` (`AIMessage`+`additional_kwargs.jarvis`) |
| A5 | non‑blocking structural (turn ends complete) | **CONVERGED** | `graph.py:180` (`queued_finish→persist→compact→END`) |
| A6 | inline dispatch + **leased reaper** backstop | **PARTIAL** | inline dispatch `nodes.py:1479`; **reaper absent** (see C6) → MISSING‑UNPLANNED half |
| A7 | per‑thread FIFO + master‑priority lane | **MISSING‑UNPLANNED** | no turn serialization/priority anywhere |
| A8 | `message_repair`/paused‑refusal/one‑per‑thread **retired** | **DIVERGED** | *not* retired: `repair_orphaned_tool_calls` still called (`nodes.py:485`, kept for the llama orphan); legacy paused‑nudge kept (`runner.py:268/384/973`). Legitimate (model‑layer), but contrary to the ideal's claim |

### Axis B — state model
| # | Element | Status | Evidence / plan |
|---|---|---|---|
| B1 | one hardened row (payload+status+expiry, atomic‑claimable) | **CONVERGED** | `models.py:153‑161`; claim `approvals.py:85‑99` |
| B2 | message↔row provenance link | **CONVERGED** | inverse link `additional_kwargs.jarvis.approval_ids` `nodes.py:1231‑1240` (no `card_message_id` column, but the axis accepts either direction) |
| B3 | monotonic `seq` for live ordinals | **MISSING‑PLANNED** | absent; ordering is `created_at.asc()` `approvals_service.py:128` → **B1** (live‑ordinal disambiguation) |
| B4 | `idempotency_key` column | **MISSING‑UNPLANNED** | absent; only turn‑scoped in‑memory dedup `state.py:57‑63` → §7 "solved" |
| B5 | `mode` column (immutable per‑row) | **MISSING‑UNPLANNED** | absent; moot (migration already done) |
| B6 | `dispatch_status` + lease columns | **MISSING‑UNPLANNED** | absent (grep→0) → §7 "solved" |
| B7 | read only via `approvals_service`; no pending list in AgentState | **CONVERGED** | `approvals_service.py:117‑130`; AgentState holds only turn‑scoped markers |
| B8 | constraints (status enum/CHECK, unique idempotency, partial‑unique one‑active) | **PARTIAL** | indexes present (`001_initial_schema.py:163‑167`); **status is free `String(20)`, no CHECK/unique** (`models.py:154`; `012` notes "no enum change") → partly **B1** |
| B9 | `approvals_service` filters unlinked rows | **MISSING‑PLANNED** | `list_pending_cards` filters only `pending`+unexpired, no linkage predicate → **C1** |

### Axis C — exactly‑once *(roadmap §7 declares this "solved by the atomic claim"; the hardening is deliberately out‑of‑scope → the ABSENT/PARTIAL halves are MISSING‑UNPLANNED)*
| # | Element | Status | Evidence / plan |
|---|---|---|---|
| C0 | atomic claim = one decision winner | **CONVERGED** | `approvals.py:85‑97` (`UPDATE…WHERE status='pending' AND expires_at>now RETURNING`); one gate `resolve_and_dispatch` |
| C1 | fuse claim + dispatch‑lease in one write | **PARTIAL** (claim only) | no lease token/owner/TTL fused; status→`approved` at claim, no dispatch phase → **UNPLANNED** |
| C2 | provider‑call timeout `< lease TTL` | **PARTIAL** | timeout present (`gmail.py:64‑79`, `calendar_tool.py:88‑103`); **no lease to bound against** → UNPLANNED |
| C3 | fenced terminal writes (`lease_owner`+`attempt`) | **PARTIAL** | outcome write present but keyed on `id` only (`approval_dispatch.py:157`), no fence columns → UNPLANNED |
| C4 | provider‑native idempotency (Calendar supplied‑id; email `rfc822msgid` read‑back) | **MISSING‑UNPLANNED** | `calendar_create` sends no client `id`/`iCalUID` (`calendar_tool.py:169‑191` → retried insert duplicates); Gmail sends no stable self‑Message‑ID (`gmail.py:96‑138`) |
| C5 | `EmailSendUncertain`→`in_doubt` + never blind‑retry + master exit | **PARTIAL** | never‑blind‑retry **fully present** (`_RETRYABLE_SEND_STATUS={429,503}`, `gmail.py:49,173‑183`) + honest "unconfirmed" notice (`email_send.py:113‑118`); **no reconcile, no master‑facing resend‑with‑new‑key exit** |
| C6 | reaper sweeps `approved`‑but‑unleased | **MISSING‑UNPLANNED** | no `dispatch_status`, no reaper; the only sweep is pending→expired (`approval_expiry.py:34‑46`) → **crash‑in‑doubt lost send** (re‑verified) |
| C7 | row‑first + re‑link, never blind‑discard | **PARTIAL** | row‑first present (durable row = source of truth, dispatch loads by id `approval_dispatch.py:274`); no re‑link reconciler |

### Axis D — channels
| # | Element | Status | Evidence / plan |
|---|---|---|---|
| D1 | one `approvals_service` (read) + one dispatcher (resolve) | **CONVERGED** | `approvals_service.py:117`; `resolve_and_dispatch` called by web (`approvals.py:259`), Telegram (`telegram.py:248`), in‑graph (`nodes.py:1479`) |
| D2 | send body single‑sourced from `row.payload` | **CONVERGED** | `approval_dispatch.py:308‑310`; `inbound.py:210‑211` (draft in payload) |
| D3 | HUD word‑only, **no buttons** (R10) | **DIVERGED** | live Approve/Reject buttons `ApprovalCard.tsx:128‑155` → planned **B3** (tagged the A2→B3 transition) |
| D4 | Telegram optional buttons | **CONVERGED** | `telegram.py:176‑191` inline keyboard → `resolve_and_dispatch` |
| D5 | one narration path (ResolutionEvent) | **PARTIAL** | shared `_record_outcome` core (`approval_dispatch.py:104`); **no ResolutionEvent object** (grep→0), each channel renders its own → **B2** + the unscheduled channel‑unification |
| D6 | Telegram webhook `callback_query` + `update_id` dedup | **MISSING‑UNPLANNED** | webhook silently ignores `callback_query` (`webhooks/telegram.py:72‑78`); buttons don't resolve in prod/webhook mode; no `update_id` dedup |
| D7 | dispatcher enforces seen‑gate; no button on unseen | **MISSING‑PLANNED** | no seen‑gate anywhere; claim checks only pending+expiry (`approvals.py:88‑94`) → will dispatch an unseen card (D26 class) → **B1** (word path) / hard gate UNPLANNED |
| D8 | inbound channel‑origin links via conversation `thread_id` | **MISSING‑PLANNED** | inbound `thread_id='email:<provider>:<id>'` (`inbound.py:185`), **not** the conversation thread → **C1** (inbound auto‑draft OFF until then, `6f356c0`) |
| D9 | system alerts → both HUD + Telegram | **CONVERGED** | `failure_alerter.py:89‑94` (SystemAlert row + Telegram); HUD `activity.py:186‑197` (Note2 ✓) |
| D10 | resolved‑card render (badges, no live buttons on non‑pending) | **CONVERGED** | `ApprovalCard.tsx:66,98‑108,128` (buttons behind `!resolved`; ✅/❌/⚠️ badges) |

### Axis E — consent *(re‑run‑confirmed + first‑hand; file:line at HEAD)*
| # | Element | Status | Evidence / plan |
|---|---|---|---|
| E1 | strong `DECISION_MODEL`, never fast tier | **CONVERGED** | judged on strong model (`runner.py:391`; `config` DECISION_MODEL; locked by `test_decision_judge_live`) |
| E2 | cheap deterministic pre‑gate | **PARTIAL** | referent‑existence skip (`card_resolution_judge_skipped no_referent`); **no message‑shape pre‑gate** → lingering‑card strong‑model tax → UNPLANNED |
| E3 | strict unified consent (fillers + non‑committal re‑ask) | **CONVERGED** | `5c0e385`/`3aa29fb`; `jarvis.solicited` dispatch anchor (`nodes.py:1237`); bare‑affirmative dispatches only on a singleton |
| E4 | multi‑card selector, kind‑scoped | **MISSING‑PLANNED** | single most‑recent referent today; kind‑scoped selection is **B1.1** (issue‑5) |
| E5 | ordinals bound to narration epoch + ASK on drift | **MISSING‑PLANNED** | judge window hardcoded `[-6:]` (`nodes.py:1541`), not epoch‑bound, no drift check → **B1.2** |
| E6 | ASK on >1/mismatch, never guess | **CONVERGED** | the seal refuses on >1/mismatch and *asks* (`nodes.py:1444`, `_confirm_worthy_mismatch`) |
| E7 | confidence gate (ambiguous → never approve) | **CONVERGED** | conservative judge: `ambiguous→unclear→re‑ask, NEVER approve` (`runner.py:766`) |
| E8 | seen/heard a **dispatch‑time** hard invariant | **PARTIAL** | solicitation contract (never *invite* on unseen, A2 s1a) present; **hard dispatch‑time refusal absent** (see D7) → UNPLANNED |
| E9 | edit terminates consent (re‑mint, never send unseen) | **CONVERGED** | `81c4016` supersede‑by‑target + same‑tool pin; `f8ec0f5` edit‑no‑mint floor strips solicitation |
| E10 | approve_all pins ids+versions + unseen soft‑confirm + eligibility filter | **MISSING‑PLANNED** | single‑card only; "approve both"/"reject both" loops → **B1** multi‑target + Phase‑D batch |
| E11 | code‑enforced completeness + no‑reply guard at propose AND dispatch | **PARTIAL** | inbound recipient validation before queuing (`email_send.py`, `119f16d`); outbound placeholder → **C2**, no‑reply → **C1** |
| E12 | untrusted‑body‑as‑data injection defense | **CONVERGED** | `sanitizer.py:53` wraps tool output `<tool_output trust="untrusted">` DATA; inbound gated by C1 |
| E13 | compound‑turn split (resolve + forward residual) | **MISSING‑PLANNED** | a resolved‑consent turn ends at persist, residual request dropped (`nodes.py:1479‑1496,1601‑1604`) → **B1** |
| E14 | request‑to‑assistant hard negatives + deixis | **PARTIAL** | prompt‑level negatives + deixis (`decision_resolver.py:74‑79`); stateful deixis vs a candidate set → **B1** |
| E15 | `heard` flips on TTS‑complete (barge‑in→false) | **MISSING‑UNPLANNED** | voice reads full draft; no barge‑in‑during‑read `heard` handling |
| E16 | **stateful** conversational disambiguation | **MISSING‑PLANNED** | stateless single‑shot today (issue1‑5 dead‑end) → **B1.0** (the headline B1 deliverable) |

### Axis F — migration (process; complete but diverged)
| # | Element | Status | Evidence / plan |
|---|---|---|---|
| F1 | strangler, per‑action_type flag gating minting | **DIVERGED (moot)** | big‑bang cutover `88ad34d`, no flag; migration complete |
| F2 | immutable per‑row `mode` | **MISSING‑UNPLANNED (moot)** | no `mode`; migration already done |
| F3 | drain‑before‑retire | **DIVERGED (done)** | drain `b0b5760` ran *after* the cutover; complete |
| F4 | guard‑retirement bound to interrupt() retirement | **DIVERGED** | `message_repair` kept (llama orphan), paused‑nudge kept (legacy) — see A8 |
| F5 | primary‑model validation | **MISSING‑PLANNED** | entire migration validated only on `gpt‑4o‑mini`; `llama` re‑validation = **NV4** (master‑triggered) |
| F6 | behavior‑class test discipline | **CONVERGED** | reproduce‑first + behavior‑class + ledger (roadmap §6, standing rules) |

### Ideal‑PDF requirements
| # | Requirement | Status | Evidence / plan |
|---|---|---|---|
| R1/R3/R4 | smart/helpful · remembers master · contextual | **CONVERGED** | memory/profile/context subsystems (pre‑existing, preserved) |
| R2 | UI text from the brain, spoken | **CONVERGED** | card & replies are `AIMessage`s (`nodes.py:1231`); tool output wrapped/never shown raw |
| R5 | complete replies, no placeholder/junk | **PARTIAL** | inbound recipient validation done; outbound `[Your Name]` (D13) → **C2** |
| R6 | real handles only (no no‑reply/bot) | **MISSING‑PLANNED** | D20 recurs; inbound auto‑draft OFF until **C1** (`6f356c0`) |
| R7 | complex → self‑summary, inline | **MISSING‑PLANNED** | complex→heads‑up card today (`ba24a68`); self‑pushed inline summary → **Phase‑D1** |
| R8 | then draft on ask | **CONVERGED** | master‑initiated draft path |
| R9 | summaries inline + persisted, not queued | **PARTIAL** | approval messages inline+persisted (A2); complex‑email inline summary → **D1/D2** |
| R10 | draft → card, **no buttons**, consent by intention | **PARTIAL** | card‑as‑message + word consent present; **HUD buttons live** → **B3** |
| R11 | multiple cards stack most‑recent‑bottom, from graph | **CONVERGED** | graph‑emitted card messages; frontend stacks |
| R12 | consent mapping + 100% confirm + ask‑ambiguous | **PARTIAL** | single‑card done (seal); multi‑card mapping → **B1** |
| R13 | master‑initiated cards | **CONVERGED** | `email_send`/`calendar_create` on request |
| R14 | non‑restrictive conversation | **CONVERGED** | non‑blocking structural (A5) |
| R15 | preserve `email_history_search` etc. | **CONVERGED** | kept + outcome‑aware (`16eec00`) |
| R16 | calendar add/modify/delete w/ consent | **CONVERGED** | `calendar_*` APPROVE cards |
| R17 | remind upcoming events | **MISSING‑PLANNED** | → **Phase‑D3** |
| R18 | add/update read in voice | **PARTIAL** | voice reads approval prose; events‑as‑messages polish → **C3** |
| R19 | delete reads name + confirms | **CONVERGED** | `enrich_delete_args` reads the event name at mint (`calendar_tool.py:412‑441`) + confirm |
| R20 | overlap‑check | **CONVERGED** | `calendar_conflict_warning` (pre‑existing) |
| R21 | briefing uncaught/fresh + events | **CONVERGED** | briefing shipped (Phase 5); richer → D3 |
| R22 | past‑day briefing on request | **CONVERGED** | briefing scope today/yesterday/past (`83741bc`) |
| Note2 | system‑alerts → HUD log | **CONVERGED** | `failure_alerter.py:89‑94` → HUD + Telegram |

---

## 3. Convergence percentages (counting rule in §0)

| Axis | Score / N | % | Notes |
|---|---|---:|---|
| A — spine | 5.5 / 8 | **69%** | A1‑A5 converged; A6 half (reaper→C), A7 unplanned, A8 diverged |
| B — state | 3.5 / 9 | **39%** | row + link + shared read; the hardening columns absent |
| C — exactly‑once | 2.5 / 7 | **36%** | claim + timeout + never‑retry + row‑first present; lease/idempotency/reaper absent |
| D — channels | 6 / 10 | **60%** | one read+dispatcher+single‑source+alerts; buttons/webhook/ResolutionEvent gaps |
| E — consent | 8 / 16 | **50%** | strong judge + seal + strict bar + edit; stateless, no multi‑card/kind‑scope/epoch‑bind |
| **Ideal A–E subtotal** | **25.5 / 50** | **51%** | (F excluded — process, not architecture) |
| PDF requirements | 17.5 / 23 | **76%** | core email/calendar/briefing/alerts converged; UX‑surface + capability breadth planned |
| **Overall (A–E + PDF)** | **43 / 73** | **~59%** | |
| **Overall (incl. F process)** | **44.5 / 79** | **~56%** | F drags it because the migration *process* diverged (but is complete) |

**Planned‑coverage of the remainder (the number that matters most):** of the **~35 non‑CONVERGED
elements**, **~21 are MISSING‑PLANNED** (B1: B3/E4/E5/E10/E16/D7/R12/B8 · B3: D3/R10 · C1: R6/D8/B9/E11 ·
C2: R5 · C3: R18/R19 · D1‑phase: R7 · D3‑phase: R17 · NV4: F5 · B2: D5) and **~14 are
MISSING‑UNPLANNED** (A7, A8‑by‑choice, B4, B5‑moot, B6, C1/C2/C3‑lease, C4, C5‑reconcile, C6, C7‑relink,
D6, E2, E8‑hard, E15). **≈60% of the remainder is already designed.** The unplanned ~40% is dominated
by **one cluster — exactly‑once hardening (C1/C3/C4/C5/C6/C7 + B4/B6)** — plus the **Telegram‑webhook
callback** gap; the rest (A7, E2, E8‑hard, E15, B5) are narrow.

---

## 4. The remainder specification

Every non‑CONVERGED item as a named gap. **Size:** S ≤ ~1 focused change · M ≈ a task · L ≈ a phase.

### G1 — Exactly‑once hardening *(the one high‑risk UNPLANNED gap)*
- **What:** close the at‑most‑once gaps the atomic claim leaves — (a) a **reaper + `dispatch_status`/lease**
  so a crash between claim and send is recovered, not a silent lost action (C1/C3/C6, A6); (b)
  **provider‑native idempotency** — a client `id`=f(approval_id) on `calendar_create` (409⇒success) and
  a stable self‑`Message‑ID` + `rfc822msgid:` read‑back on email — so a retry/re‑approve can't
  double‑send (C4); (c) an **`in_doubt` reconcile + a master‑facing "check Sent / resend‑with‑new‑key"
  exit** (C5/C7).
- **Serves:** ideal axis C (C1‑C7), A6; PDF "no junk sent twice."
- **Evidence of absence:** `approval_expiry.py:34‑46` (only pending→expired); `approval_dispatch.py:157`
  (unfenced write, no lease); `calendar_tool.py:169‑191` / `gmail.py:96‑138` (no idempotency key);
  no `dispatch_status` column (grep→0).
- **Dependencies/ordering:** independent of B1 (it's the **dispatch substrate**, not consent) → slots
  in parallel; needs a small additive migration (`dispatch_status`/`lease_owner`/`attempt`/`idempotency_key`).
  **Best done before NV4** (a flakier open‑weights primary + mid‑turn fallback = more crash‑in‑doubt).
- **Size:** **M–L.** **Risk if never done:** a crashed/timed‑out send is **silently lost** (master
  believes it queued; it never goes), and a re‑approve after an "unconfirmed" **double‑sends** an
  email / **duplicates** a calendar event. *The plan (roadmap §7) explicitly considers this solved —
  this is the single place the plan and the ideal disagree, and the master should decide whether to
  re‑open it.*

### G2 — Stateful conversational consent (B1) *(the largest PLANNED gap)*
- **What:** consent becomes stateful — asks/confirms carry their anchor + candidate set as jarvis‑tagged
  messages; the follow‑up resolves the question that asked it; multi‑card **kind‑scoped** selection;
  multi‑target outcomes; judge window sized from the anchor. **Serves:** E4/E5/E10/E13/E16, R12, D7‑word.
- **Evidence of absence:** stateless single‑shot judge; `issue1‑5` transcripts dead‑end; judge window
  hardcoded `[-6:]` (`nodes.py:1540`); `card_outcome` a single dict.
- **Planned at:** **B1 (frozen 2026‑07‑05, awaiting the master's word)** + B3 as a hard co‑requisite of
  its multi‑target path. **Size:** **L. Do NOT re‑plan — this map slots around it.**
- **Risk if never done:** consent works only on the golden path; every deviation (compound reject,
  "the Timmy one", kind‑named card) dead‑ends — the master's own milestone failure mode.

### G3 — Card‑from‑row + retire HUD buttons (B3)
- **What:** render the HUD card from `row.payload`, retire the button‑card + poll → word/voice consent
  on the HUD. **Serves:** R10, D3, D5(partly), D10. **Evidence:** live buttons `ApprovalCard.tsx:128‑155`.
- **Planned at:** **B3** (co‑requisite of B1's multi‑target). **Size:** **M.** **Risk:** the R10
  "no‑buttons, consent‑by‑intention" ideal never lands; the double‑surface transition persists.

### G4 — Inbound‑as‑conversation‑message + real handles (C1)
- **What:** inbound drafts inject into the `web:master` conversation as linked Jarvis messages;
  real handles only (no no‑reply/bot). **Serves:** R6, R9‑inbound, D8, B9, E11‑no‑reply.
- **Evidence:** inbound `thread_id='email:…'` not conversation‑linked (`inbound.py:185`); auto‑draft
  **OFF** (`INBOUND_AUTO_DRAFT`, `6f356c0`). **Planned at:** **C1. Size:** **M.** **Risk:** inbound
  auto‑drafting stays disabled; D20 (replies to no‑reply) recurs when re‑enabled.

### G5 — Outbound placeholder guard (C2)
- **What:** code‑guard no‑placeholder/junk before an outbound send is eligible (D13 `[Your Name]`).
  **Serves:** R5, E11‑outbound. **Planned at:** **C2. Size:** **S.** **Risk:** a `[Your Name]` draft
  can ship as‑is.

### G6 — Events as approval messages (C3)
- **What:** calendar add/update as approval messages read aloud; delete reads the event name + confirms;
  overlap narrated. **Serves:** R18, R19, R16‑R20. **Planned at:** **C3. Size:** **M.** **Risk:** calendar
  approvals stay less conversational than email; delete‑by‑name UX absent.

### G7 — Proactive capability (Phase D)
- **What:** complex‑email self‑summary (R7/D1), batch‑draft summarization + approve‑all soft‑confirm
  (E10/D2), event reminders + richer briefing (R17/D3). **Planned at:** **Phase D. Size:** **L.**
  **Risk:** the "progressive ideal" (proactive smartness) never lands; batch‑approve UX absent.

### G8 — Primary‑model validation (NV4)
- **What:** migrate PRIMARY→`gpt‑oss‑120b`, FAST→`gpt‑oss‑20b` + full ledger re‑validation on the new
  family. **Serves:** F5. **Evidence:** whole migration validated only on `gpt‑4o‑mini`
  (`migration_nonblocking_approvals.md` §6); `llama` orphan (D22) live. **Planned at:** **NV4
  (master‑triggered; Groq decommission 2026‑08‑16 is the only hard date). Size:** **M–L.** **Risk:**
  after 08‑16 every `llama` call fails → silent fallback‑only; nothing re‑verified on a real primary.

### G9 — Narrow UNPLANNED items (fold into the nearest phase or a hardening pass)
| id | What | Serves | Size | Risk if never done |
|---|---|---|---|---|
| **D6** | Telegram webhook `callback_query` handling + `update_id` dedup | D6 | S | Telegram buttons don't resolve in prod/webhook mode; retried callbacks could double‑inject |
| **E8/D7** | hard dispatch‑time seen‑gate on the button path | E8 | S | a Telegram button on an unseen batch card sends content the master never saw (D26 class) |
| **E2** | cheap message‑shape pre‑gate | E2 | S | a lingering card taxes the strong model on every unrelated turn (cost/latency) |
| **E15** | `heard` flips on TTS‑complete (barge‑in→false) | E15 | S | a barged‑in voice read can send content past the point the master heard |
| **A7** | per‑thread FIFO + priority lane | A7 | S | two concurrent turns on one thread could lose‑update (low for single‑master) |
| **B8** | status enum/CHECK + unique constraints | B8 | S | a bad status string is insertable; DB doesn't enforce the one‑active invariant (app‑level only) |
| **D5** | a single ResolutionEvent narration object (channel unification) | D5 | **L** | the "three near‑parallel turn paths" bug generator persists (the roadmap's own truth #2) |

*(B5 `mode` and F1–F4 are moot — the migration is complete; they'd only matter for a future re‑migration.)*

---

## 5. The ordered completion path (respecting B1's in‑flight state)

**Constraint honored:** B1 is design‑frozen and awaiting the master's word — **not re‑planned here; the
sequence slots around it.** Ordering is by dependency + risk, not calendar.

1. **B1 (+ B3 co‑requisite) — the in‑flight next step.** Stateful consent + card‑from‑row. Closes G2,
   G3, and most of D7‑word/R10/R12. *Owned; do not disturb — it's the golden‑path‑off fix the master's
   milestone needs.*
2. **G1 — Exactly‑once hardening — recommend slotting NOW, in parallel with B1** (different subsystem:
   dispatch substrate vs consent, so no file collision). It is the **only high‑risk UNPLANNED gap** and
   the roadmap deliberately excludes it, so it needs an explicit master decision. **Do it before G8
   (NV4)** — a flakier primary multiplies crash‑in‑doubt. *(If the master accepts §7's "solved" stance,
   record it as an accepted residual instead — but the lost‑send + double‑send scenarios above are real.)*
3. **C1 → C2 → C3 → C4 (Phase C capability).** Inbound‑as‑message/real‑handles (re‑enables inbound
   drafting), outbound placeholder guard, events‑as‑messages, preserve caps. Closes G4/G5/G6 and
   R5/R6/R7‑inbound/R18/R19. C1 depends on B1's linkage primitives (thread‑linked cards).
4. **G9 narrow hardening — fold into the phase that touches the same surface:** D6 + E8/D7‑button with
   the Telegram/frontend work (B3/C1); E2 + E15 with the voice/consent work (B1); B8 with any approval
   migration (G1 or C1). Cheap, independent, S‑sized.
5. **G8 — NV4 model migration + full ledger re‑validation.** Master‑triggered; after A2/B1 per the plan;
   sequence **after** G1 so the exactly‑once floor is in place before the flakier primary.
6. **G7 — Phase D proactive smartness.** Complex‑summary, batch‑approve, reminders, richer briefing —
   the progressive ideal, last.
7. **D5 channel unification (large, unscheduled).** The "one core + thin adapters" refactor the roadmap
   names as its top structural risk (two monoliths, three turn paths). Not urgent for correctness, but
   the highest‑leverage debt reducer — slot as a dedicated effort when the capability phases stabilize.

---

## 6. 📍 Status
- **Convergence measured:** overall ≈ **56% (59% excluding migration‑process axis F)**; per‑axis + PDF
  tabled with file:line at `6f356c0`; counting rule stated.
- **Remainder classified:** **~60% MISSING‑PLANNED** (B1/B3/C/D/NV4) · **~40% MISSING‑UNPLANNED**,
  dominated by **exactly‑once hardening (G1)** + the Telegram‑webhook callback (D6).
- **Two Phase‑3 claims re‑verified:** (1) crash‑in‑doubt is **purely at‑most‑once, no recovery**
  (confirmed); (2) `presented_approval_id` is **fully retired** — my Phase‑3 "residual" was imprecise,
  corrected here.
- **The one decision for the master:** whether to re‑open **exactly‑once hardening (G1)**, which the
  roadmap §7 deliberately scopes out as "solved" but which my re‑verification shows leaves a silent
  lost‑send on crash and a double‑send on re‑approve. Everything else is either converged or already
  designed (B1/B3/C/D/NV4).
- **STOP — the master reviews before anything is acted on.** No fixes, no tickets, no code.
