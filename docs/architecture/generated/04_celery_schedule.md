<!-- AUTO-GENERATED — do not edit by hand.
     Regenerate with `make architecture` (or scripts/gen_architecture.py).
     Source of truth is the code; edit the code, then regenerate. -->

# Celery Beat Schedule

5 periodic jobs from `app/scheduler/beat_schedule.py`.

| Beat job | Task | Schedule |
|---|---|---|
| `approval-expiry-sweep` | `app.scheduler.tasks.approval_expiry.sweep_expired_approvals` | `0 * * * *`  (m h dom mon dow) |
| `email-check` | `app.scheduler.tasks.email_check.check_inbox` | `*/15 * * * *`  (m h dom mon dow) |
| `email-watch-renew` | `app.scheduler.tasks.email_renew.renew_watch` | `0 3 * * 0,6`  (m h dom mon dow) |
| `inbound-health-check` | `app.scheduler.tasks.inbound_health.check_inbound_health` | `30 * * * *`  (m h dom mon dow) |
| `morning-brief` | `app.scheduler.tasks.morning_brief.send_morning_brief` | `0 8 * * *`  (m h dom mon dow) |
