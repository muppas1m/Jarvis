<!-- AUTO-GENERATED — do not edit by hand.
     Regenerate with `make architecture` (or scripts/gen_architecture.py).
     Source of truth is the code; edit the code, then regenerate. -->

# Celery Beat Schedule

6 periodic jobs from `app/scheduler/beat_schedule.py`.

| Beat job | Task | Schedule |
|---|---|---|
| `approval-expiry-sweep` | `app.scheduler.tasks.approval_expiry.sweep_expired_approvals` | `0 * * * *`  (m h dom mon dow) |
| `gmail-check` | `app.scheduler.tasks.gmail_check.check_gmail_inbox` | `*/15 * * * *`  (m h dom mon dow) |
| `gmail-watch-renew` | `app.scheduler.tasks.gmail_renew.renew_gmail_watch` | `0 3 * * 0,6`  (m h dom mon dow) |
| `inbound-health-check` | `app.scheduler.tasks.inbound_health.check_inbound_health` | `30 * * * *`  (m h dom mon dow) |
| `memory-consolidation` | `app.scheduler.tasks.memory_consolidation.consolidate_memory` | `0 2 * * *`  (m h dom mon dow) |
| `morning-brief` | `app.scheduler.tasks.morning_brief.send_morning_brief` | `0 8 * * *`  (m h dom mon dow) |
