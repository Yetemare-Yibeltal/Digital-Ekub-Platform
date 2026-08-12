import os
from celery import Celery
from celery.schedules import crontab
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('ekub')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')

app.conf.beat_schedule = {
    'send-daily-reminders': {
        'task': 'apps.notifications.tasks.send_daily_reminders',
        'schedule': crontab(hour=8, minute=0),
    },
    'process-expired-groups': {
        'task': 'apps.groups.tasks.process_expired_groups',
        'schedule': crontab(hour=0, minute=0),
    },
    'cleanup-expired-tokens': {
        'task': 'apps.users.tasks.cleanup_expired_tokens',
        'schedule': crontab(hour=2, minute=0),
    },
    'process-overdue-contributions': {
        'task': 'apps.contributions.tasks.process_overdue_contributions',
        'schedule': crontab(hour=6, minute=0),
    },
    'auto-select-winner': {
        'task': 'apps.groups.tasks.auto_select_winner',
        'schedule': crontab(hour=18, minute=0),
    },
}