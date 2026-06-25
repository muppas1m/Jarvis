<!-- AUTO-GENERATED — do not edit by hand.
     Regenerate with `make architecture` (or scripts/gen_architecture.py).
     Source of truth is the code; edit the code, then regenerate. -->

# Tools & Safety Tiers

12 registered tools. Safety tier from `app/agent/safety.py:TOOL_SAFETY_MAP` (SAFE = silent · NOTIFY = run+inform · APPROVE = pause for the master · BLOCKED = never). Backing module is the handler's `__module__`.

| Tool | Safety tier | Always-loaded | Backing module | Summary |
|---|---|---|---|---|
| `calendar_create` | APPROVE |  | `app.agent.tools.calendar_tool` | Create a new event on the master's Google Calendar |
| `calendar_delete` | APPROVE |  | `app.agent.tools.calendar_tool` | Delete / cancel an existing calendar event by event_id |
| `calendar_read` | SAFE |  | `app.agent.tools.calendar_tool` | Read upcoming events from the master's Google Calendar — what's scheduled, meetings, what'… |
| `calendar_update` | APPROVE |  | `app.agent.tools.calendar_tool` | Update / reschedule an existing calendar event — change its title, time, description, or l… |
| `document_search` | SAFE |  | `app.agent.tools.document_search` | Search the master's ingested documents (PDFs, Word/Excel files, notes, markdown) for passa… |
| `email_history_search` | SAFE |  | `app.agent.tools.email_history` | Search the master's email history — what messages came in, who sent them, were they replie… |
| `email_send` | APPROVE |  | `app.agent.tools.email_send` | Send an email via the master's account |
| `memory_search` | SAFE | yes | `app.agent.tools.builtin_memory` | Search the master's persistent conversation memory — facts they've told you, preferences, … |
| `task_add` | SAFE |  | `app.agent.tools.actionable_tool` | Record a task / to-do the master needs to act on, into their task list |
| `task_complete` | SAFE |  | `app.agent.tools.actionable_tool` | Mark a task DONE when the master says they've finished it — matches an open task by its wo… |
| `task_drop` | SAFE |  | `app.agent.tools.actionable_tool` | DROP / cancel a task the master no longer needs to do — abandoned, NOT done |
| `task_list` | SAFE |  | `app.agent.tools.actionable_tool` | List the master's tasks — their TO-DO list, the source of truth for what they need to act … |
