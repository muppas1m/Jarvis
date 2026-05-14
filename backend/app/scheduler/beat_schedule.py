"""Celery beat schedule — periodic task definitions.

Imported at celery_app build time; mutates celery_app.conf.beat_schedule.

Five jobs in Phase 2 (Turn 17). Three of them — gmail-renew, gmail-check,
approval-expiry-sweep — are belt-and-braces safety nets. The other two —
morning-brief, memory-consolidation — are user-facing maintenance.

Phase 3 adds news-briefing and memory-conflict-check; that's Turn 25 and
Turn 26.5 work respectively.
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
    # every 6 days. A 15-min poll closes both gaps. Cost: ~100 Gmail list
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
    # Gmail watch renewal every 6 days (7-day expiry, renew early).
    # gmail_renew runs a catch-up sweep after re-registering — closes the
    # short seam where the new watch's first historyId is published before
    # the old subscription's last events are fully drained.
    "gmail-watch-renew": {
        "task": "app.scheduler.tasks.gmail_renew.renew_gmail_watch",
        "schedule": crontab(hour=3, minute=0, day_of_week="*/6"),
    },
    # Nightly memory consolidation at 2am.
    # Phase 2 ships a log-only stub; real implementation lands in Turn 26.5
    # (project plan close-out section) alongside memory_conflict_check.
    "memory-consolidation": {
        "task": "app.scheduler.tasks.memory_consolidation.consolidate_memory",
        "schedule": crontab(hour=2, minute=0),
    },
    # Hourly approval expiry sweeper — auto-expires approvals past expires_at.
    "approval-expiry-sweep": {
        "task": "app.scheduler.tasks.approval_expiry.sweep_expired_approvals",
        "schedule": crontab(minute=0),
    },
}
