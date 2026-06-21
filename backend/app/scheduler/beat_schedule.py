"""Celery beat schedule — periodic task definitions.

Imported at celery_app build time; mutates celery_app.conf.beat_schedule.

Three of the jobs — gmail-renew, gmail-check, approval-expiry-sweep — are
belt-and-braces safety nets; morning-brief is user-facing maintenance.

(A nightly memory-consolidation beat was removed when the 4.B consolidation/
noise-purge engine was deferred to a real-usage signal — recoverable from git.)
"""
from celery.schedules import crontab

from app.scheduler.celery_app import celery_app


celery_app.conf.beat_schedule = {
    # 8am daily morning brief (email digest + future news section).
    "morning-brief": {
        "task": "app.scheduler.tasks.morning_brief.send_morning_brief",
        "schedule": crontab(hour=8, minute=0),
    },
    # Gmail INBOX safety-net poll every 15 minutes.
    #
    # Why this exists alongside Pub/Sub push: Pub/Sub's at-least-once
    # guarantee only covers messages the broker successfully accepted from
    # the publisher. It does NOT cover (a) Gmail's internal publisher
    # failing before publishing, or (b) the seam during watch re-registration
    # twice weekly. A 15-min poll closes both gaps. Cost: ~100 Gmail list
    # API calls/day (well under quota); LLM calls only fire when the poll
    # actually finds an unprocessed message (rare in steady state).
    #
    # If you find yourself wondering "why not just trust Pub/Sub?" — read
    # project_gmail_approval_duplicate_race.md context + the Turn 17 Q1
    # discussion. Defense-in-depth is the load-bearing rationale.
    "gmail-check": {
        "task": "app.scheduler.tasks.gmail_check.check_gmail_inbox",
        "schedule": crontab(minute="*/15"),
    },
    # Gmail watch renewal twice weekly at 3am Sun + Sat (7-day Gmail-side
    # expiry; renewing on a wall-clock cadence keeps the watch alive with
    # ~3-4 day slack, predictable for alerting). gmail_renew runs a catch-up
    # sweep after re-registering — closes the short seam where the new
    # watch's first historyId is published before the old subscription's
    # last events are fully drained.
    #
    # Cron note: `day_of_week="0,6"` selects Sun (0) AND Sat (6). The earlier
    # `*/6` form looked like "every 6 days" but cron interprets it as
    # "every 6th weekday starting from 0" → the same Sun + Sat selection by
    # accident. Twice-weekly is fine operationally (more conservative than
    # "every 6 days" against the 7-day expiry); the explicit `"0,6"` form
    # documents the actual cadence.
    "gmail-watch-renew": {
        "task": "app.scheduler.tasks.gmail_renew.renew_gmail_watch",
        "schedule": crontab(hour=3, minute=0, day_of_week="0,6"),
    },
    # Hourly approval expiry sweeper — auto-expires approvals past expires_at.
    "approval-expiry-sweep": {
        "task": "app.scheduler.tasks.approval_expiry.sweep_expired_approvals",
        "schedule": crontab(minute=0),
    },
    # Hourly inbound-email health canary — alerts (in plain language) when no
    # Gmail poll has succeeded within INBOUND_HEALTH_MAX_STALE_HOURS. Closes the
    # silent-outage gap the Jun-11 manual test surfaced (gmail_check failing on
    # an expired token for ~2 weeks with no symptom-named alert).
    "inbound-health-check": {
        "task": "app.scheduler.tasks.inbound_health.check_inbound_health",
        "schedule": crontab(minute=30),
    },
}
