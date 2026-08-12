"""
Celery configuration for the Digital Ekub Platform.

This module creates the Celery application instance and configures it
to use the Django settings for broker and result backend.

It automatically discovers tasks from all installed Django apps,
allowing for distributed task processing.

For more information, see:
https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html
"""

import os
from celery import Celery
from django.conf import settings

# Set default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Create the Celery application instance
app = Celery('ekub')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related config keys
#   should have a `CELERY_` prefix in Django settings.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)


# Optional: Debug task to test Celery is working
@app.task(bind=True)
def debug_task(self):
    """A simple debug task that prints the request details."""
    print(f'Request: {self.request!r}')


# ============================================================================
# SAMPLE BEAT SCHEDULE (uncomment when adding periodic tasks)
# ============================================================================
# from celery.schedules import crontab
# app.conf.beat_schedule = {
#     'send-daily-contribution-reminders': {
#         'task': 'apps.notifications.tasks.send_daily_reminders',
#         'schedule': crontab(hour=8, minute=0),  # 8:00 AM daily
#     },
#     'process-expired-groups': {
#         'task': 'apps.groups.tasks.process_expired_groups',
#         'schedule': crontab(hour=0, minute=0),  # Midnight daily
#     },
#     'cleanup-expired-tokens': {
#         'task': 'apps.users.tasks.cleanup_expired_tokens',
#         'schedule': crontab(hour=2, minute=0),  # 2:00 AM daily
#     },
# }