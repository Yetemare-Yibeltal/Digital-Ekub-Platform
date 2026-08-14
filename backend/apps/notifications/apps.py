"""
App configuration for the notifications app.

This module defines the Django AppConfig for the notifications app,
including the ready method for importing signals, registering admin,
performing system checks, validating environment settings, and
initializing default configurations.

The app also sets up periodic tasks, cache invalidation hooks, and
integrates with the overall platform's monitoring and logging systems.
"""

import logging
import sys
import os
from django.apps import AppConfig
from django.conf import settings
from django.core.checks import register, Tags, Warning, Error, Critical
from django.core.management import call_command
from django.db import connection
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class NotificationsConfig(AppConfig):
    """
    Configuration for the notifications app.

    This class handles app initialization, signal registration,
    system checks, environment validation, and startup tasks.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.notifications'
    label = 'notifications'
    verbose_name = _('Notifications')

    # Internal state for initialization tracking
    _initialized = False
    _checks_run = False
    _signals_registered = False
    _admin_registered = False
    _tasks_registered = False

    def ready(self):
        """
        Called when the app is ready.

        This method performs the following initialization tasks:
        1. Imports and registers signals
        2. Imports and registers admin classes
        3. Performs system checks
        4. Validates environment settings
        5. Initializes default configuration
        6. Sets up cache invalidation hooks
        7. Registers custom management commands
        8. Sets up periodic tasks (if Celery configured)
        9. Performs database checks
        10. Logs successful initialization
        """
        if self._initialized:
            logger.debug('Notifications app already initialized.')
            return

        logger.info('Initializing notifications app...')

        # ====================================================================
        # 1. IMPORT AND REGISTER SIGNALS
        # ====================================================================
        self._register_signals()

        # ====================================================================
        # 2. IMPORT AND REGISTER ADMIN CLASSES
        # ====================================================================
        self._register_admin()

        # ====================================================================
        # 3. PERFORM SYSTEM CHECKS
        # ====================================================================
        self._perform_system_checks()

        # ====================================================================
        # 4. VALIDATE ENVIRONMENT SETTINGS
        # ====================================================================
        self._validate_environment()

        # ====================================================================
        # 5. INITIALIZE DEFAULT CONFIGURATION
        # ====================================================================
        self._initialize_defaults()

        # ====================================================================
        # 6. SET UP CACHE INVALIDATION HOOKS
        # ====================================================================
        self._setup_cache_hooks()

        # ====================================================================
        # 7. REGISTER CUSTOM MANAGEMENT COMMANDS
        # ====================================================================
        self._register_management_commands()

        # ====================================================================
        # 8. SET UP PERIODIC TASKS (if Celery configured)
        # ====================================================================
        self._setup_periodic_tasks()

        # ====================================================================
        # 9. PERFORM DATABASE CHECKS
        # ====================================================================
        self._perform_database_checks()

        # ====================================================================
        # 10. LOG SUCCESSFUL INITIALIZATION
        # ====================================================================
        self._initialized = True
        logger.info(f'Notifications app v{self.get_version()} initialized successfully.')

    # ==========================================================================
    # REGISTRATION METHODS
    # ==========================================================================

    def _register_signals(self):
        """Import signals module to register signal handlers."""
        if self._signals_registered:
            return

        try:
            import apps.notifications.signals
            # Force registration of signal handlers
            from apps.notifications import signals as _  # noqa
            self._signals_registered = True
            logger.info('Notifications signals registered successfully.')
        except ImportError as e:
            logger.error(f'Failed to import notifications signals: {e}')
        except Exception as e:
            logger.error(f'Unexpected error registering signals: {e}')

    def _register_admin(self):
        """Import admin module to register admin classes."""
        if self._admin_registered:
            return

        try:
            import apps.notifications.admin
            # Admin classes are automatically registered via @admin.register
            self._admin_registered = True
            logger.info('Notifications admin registered successfully.')
        except ImportError as e:
            logger.error(f'Failed to import notifications admin: {e}')
        except Exception as e:
            logger.error(f'Unexpected error registering admin: {e}')

    def _register_management_commands(self):
        """Register custom management commands (if any)."""
        if self._tasks_registered:
            return

        try:
            import apps.notifications.management  # noqa
            self._tasks_registered = True
            logger.info('Notifications management commands registered.')
        except ImportError:
            logger.debug('No custom management commands found.')

    # ==========================================================================
    # SYSTEM CHECKS
    # ==========================================================================

    def _perform_system_checks(self):
        """Run Django system checks for this app."""
        from django.core.checks import run_checks

        if self._checks_run:
            return

        try:
            checks_to_run = ['apps.notifications']
            errors = run_checks(checks_to_run)
            if errors:
                for error in errors:
                    logger.error(f'System check error: {error}')
            else:
                logger.info('Notifications system checks passed.')
            self._checks_run = True
        except Exception as e:
            logger.error(f'Error running system checks: {e}')

    @classmethod
    def register_system_checks(cls):
        """
        Register custom system checks for the notifications app.
        These are executed during Django's check framework.
        """
        def check_notification_settings(app_configs, **kwargs):
            errors = []

            # Check required settings
            required_settings = [
                'NOTIFICATION_MAX_RETRY_ATTEMPTS',
                'NOTIFICATION_RETRY_DELAY_MINUTES',
                'NOTIFICATION_BATCH_SIZE',
                'NOTIFICATION_DAILY_DIGEST_HOUR',
                'NOTIFICATION_WEEKLY_DIGEST_DAY',
                'NOTIFICATION_DAILY_DIGEST_ENABLED',
                'NOTIFICATION_WEEKLY_DIGEST_ENABLED',
                'NOTIFICATION_CLEANUP_DAYS_READ',
                'NOTIFICATION_CLEANUP_DAYS_UNREAD',
                'NOTIFICATION_CLEANUP_DAYS_DELIVERIES',
            ]
            for setting in required_settings:
                if not hasattr(settings, setting):
                    errors.append(
                        Error(
                            f'Missing required setting: {setting}',
                            hint=f'Define {setting} in your settings file.',
                            obj='notifications.apps.NotificationsConfig',
                            id='notifications.E001',
                        )
                    )

            # Check that NOTIFICATION_MAX_RETRY_ATTEMPTS is positive
            if hasattr(settings, 'NOTIFICATION_MAX_RETRY_ATTEMPTS'):
                attempts = getattr(settings, 'NOTIFICATION_MAX_RETRY_ATTEMPTS')
                if attempts <= 0:
                    errors.append(
                        Error(
                            f'NOTIFICATION_MAX_RETRY_ATTEMPTS must be greater than 0, got {attempts}.',
                            hint='Set a positive integer.',
                            obj='notifications.apps.NotificationsConfig',
                            id='notifications.E002',
                        )
                    )

            # Check email configuration
            if not hasattr(settings, 'DEFAULT_FROM_EMAIL') or not getattr(settings, 'DEFAULT_FROM_EMAIL'):
                errors.append(
                    Warning(
                        'DEFAULT_FROM_EMAIL is not set. Email notifications will use a default.',
                        hint='Set DEFAULT_FROM_EMAIL in your settings.',
                        obj='notifications.apps.NotificationsConfig',
                        id='notifications.W001',
                    )
                )

            # Check SMS configuration
            if not hasattr(settings, 'AFRICASTALKING_API_KEY') or not getattr(settings, 'AFRICASTALKING_API_KEY'):
                errors.append(
                    Warning(
                        'AFRICASTALKING_API_KEY is not set. SMS notifications will not work.',
                        hint='Set AFRICASTALKING_API_KEY in your settings.',
                        obj='notifications.apps.NotificationsConfig',
                        id='notifications.W002',
                    )
                )

            # Check push notification configuration (Firebase)
            if not hasattr(settings, 'FIREBASE_CREDENTIALS') or not getattr(settings, 'FIREBASE_CREDENTIALS'):
                errors.append(
                    Warning(
                        'FIREBASE_CREDENTIALS is not set. Push notifications will not work.',
                        hint='Set FIREBASE_CREDENTIALS in your settings.',
                        obj='notifications.apps.NotificationsConfig',
                        id='notifications.W003',
                    )
                )

            return errors

        # Register the check
        register(Tags.models)(check_notification_settings)

    # ==========================================================================
    # ENVIRONMENT VALIDATION
    # ==========================================================================

    def _validate_environment(self):
        """Validate environment variables and settings."""
        logger.info('Validating notifications environment...')

        # ====================================================================
        # 1. Check required environment variables
        # ====================================================================
        required_env = [
            'DEFAULT_FROM_EMAIL',
            'AFRICASTALKING_API_KEY',
        ]
        missing = []
        for var in required_env:
            if not os.environ.get(var):
                missing.append(var)

        if missing:
            logger.warning(
                f'Missing notification environment variables: {", ".join(missing)}. '
                'Some notification channels may not work.'
            )

        # ====================================================================
        # 2. Check Redis connectivity if Celery is enabled
        # ====================================================================
        if settings.CELERY_BROKER_URL:
            try:
                from celery import current_app
                conn = current_app.connection()
                conn.ensure_connection(max_retries=3)
                conn.release()
                logger.info('Celery broker connection successful.')
            except Exception as e:
                logger.error(f'Celery broker connection failed: {e}')

        # ====================================================================
        # 3. Check database connectivity
        # ====================================================================
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                logger.info('Database connection verified.')
        except Exception as e:
            logger.error(f'Database connection failed: {e}')

        # ====================================================================
        # 4. Validate Firebase configuration for push notifications
        # ====================================================================
        try:
            import firebase_admin
            if hasattr(settings, 'FIREBASE_CREDENTIALS'):
                # Check if Firebase is initialized
                try:
                    app = firebase_admin.get_app()
                    logger.info('Firebase initialized successfully.')
                except ValueError:
                    logger.warning('Firebase not initialized. Push notifications may fail.')
        except ImportError:
            logger.warning('Firebase Admin SDK not installed. Push notifications disabled.')

        logger.info('Notifications environment validation completed.')

    # ==========================================================================
    # DEFAULT INITIALIZATION
    # ==========================================================================

    def _initialize_defaults(self):
        """Initialize default configuration values."""
        logger.info('Initializing notification defaults...')

        # Set default values for settings if not defined
        defaults = {
            'NOTIFICATION_MAX_RETRY_ATTEMPTS': 3,
            'NOTIFICATION_RETRY_DELAY_MINUTES': 5,
            'NOTIFICATION_BATCH_SIZE': 100,
            'NOTIFICATION_DAILY_DIGEST_HOUR': 7,
            'NOTIFICATION_WEEKLY_DIGEST_DAY': 1,  # Monday
            'NOTIFICATION_DAILY_DIGEST_ENABLED': True,
            'NOTIFICATION_WEEKLY_DIGEST_ENABLED': True,
            'NOTIFICATION_CLEANUP_DAYS_READ': 30,
            'NOTIFICATION_CLEANUP_DAYS_UNREAD': 90,
            'NOTIFICATION_CLEANUP_DAYS_DELIVERIES': 60,
            'NOTIFICATION_MAX_UNREAD_DISPLAY': 50,
            'NOTIFICATION_DAILY_DIGEST_MAX': 50,
            'NOTIFICATION_WEEKLY_DIGEST_MAX': 100,
            'NOTIFICATION_PUSH_ENABLED': True,
            'NOTIFICATION_EMAIL_ENABLED': True,
            'NOTIFICATION_SMS_ENABLED': False,
            'NOTIFICATION_IN_APP_ENABLED': True,
            'NOTIFICATION_DEFAULT_PRIORITY': 'medium',
        }

        for key, default_value in defaults.items():
            if not hasattr(settings, key):
                setattr(settings, key, default_value)
                logger.debug(f'Set default {key} = {default_value}')

        logger.info('Notification defaults initialized.')

    # ==========================================================================
    # CACHE INVALIDATION HOOKS
    # ==========================================================================

    def _setup_cache_hooks(self):
        """Set up cache invalidation hooks for notification-related models."""
        logger.info('Setting up cache invalidation hooks...')

        from django.core.cache import cache
        from django.db.models.signals import post_save, post_delete

        # Define a generic cache invalidation receiver
        def invalidate_notification_cache(sender, instance, **kwargs):
            """Invalidate cache for notification-related models."""
            cache_keys = []
            if hasattr(instance, 'id'):
                cache_keys.append(f'notification_{instance.id}')
                cache_keys.append(f'notification_detail_{instance.id}')
                cache_keys.append(f'notification_stats_{instance.id}')
            if hasattr(instance, 'user') and hasattr(instance.user, 'id'):
                cache_keys.append(f'notifications_{instance.user.id}')
                cache_keys.append(f'notification_count_{instance.user.id}')
                cache_keys.append(f'notification_unread_{instance.user.id}')
                cache_keys.append(f'notification_total_{instance.user.id}')
                cache_keys.append(f'preferences_{instance.user.id}')
                cache_keys.append(f'user_prefs_{instance.user.id}')
                cache_keys.append(f'digests_{instance.user.id}')
                cache_keys.append(f'schedules_{instance.user.id}')
            if hasattr(instance, 'notification') and hasattr(instance.notification, 'id'):
                cache_keys.append(f'deliveries_{instance.notification.id}')
                cache_keys.append(f'audits_{instance.notification.id}')
            if hasattr(instance, 'name'):
                cache_keys.append(f'template_{instance.name}')
                cache_keys.append(f'templates_{instance.notification_type}')
                cache_keys.append('templates_all')

            for key in cache_keys:
                cache.delete(key)

            if cache_keys:
                logger.debug(f'Invalidated {len(cache_keys)} cache keys for {sender.__name__} {instance.id}')

        # Connect signals for all notification-related models
        from .models import (
            Notification, NotificationTemplate, NotificationPreference,
            NotificationChannel, NotificationDelivery, NotificationEvent,
            NotificationSchedule, NotificationDigest, NotificationAudit
        )

        post_save.connect(invalidate_notification_cache, sender=Notification)
        post_delete.connect(invalidate_notification_cache, sender=Notification)
        post_save.connect(invalidate_notification_cache, sender=NotificationTemplate)
        post_delete.connect(invalidate_notification_cache, sender=NotificationTemplate)
        post_save.connect(invalidate_notification_cache, sender=NotificationPreference)
        post_delete.connect(invalidate_notification_cache, sender=NotificationPreference)
        post_save.connect(invalidate_notification_cache, sender=NotificationChannel)
        post_delete.connect(invalidate_notification_cache, sender=NotificationChannel)
        post_save.connect(invalidate_notification_cache, sender=NotificationDelivery)
        post_delete.connect(invalidate_notification_cache, sender=NotificationDelivery)
        post_save.connect(invalidate_notification_cache, sender=NotificationEvent)
        post_delete.connect(invalidate_notification_cache, sender=NotificationEvent)
        post_save.connect(invalidate_notification_cache, sender=NotificationSchedule)
        post_delete.connect(invalidate_notification_cache, sender=NotificationSchedule)
        post_save.connect(invalidate_notification_cache, sender=NotificationDigest)
        post_delete.connect(invalidate_notification_cache, sender=NotificationDigest)
        post_save.connect(invalidate_notification_cache, sender=NotificationAudit)
        post_delete.connect(invalidate_notification_cache, sender=NotificationAudit)

        logger.info('Cache invalidation hooks set up.')

    # ==========================================================================
    # PERIODIC TASKS SETUP
    # ==========================================================================

    def _setup_periodic_tasks(self):
        """Set up periodic tasks for Celery Beat."""
        if not self._is_celery_installed():
            logger.info('Celery not installed; periodic tasks not configured.')
            return

        try:
            from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule

            # Check if we already have tasks set up
            if PeriodicTask.objects.filter(name__startswith='notifications_').exists():
                logger.info('Periodic tasks already configured.')
                return

            # Create schedules
            interval_5min, _ = IntervalSchedule.objects.get_or_create(
                every=5,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'notifications_5min'}
            )

            interval_15min, _ = IntervalSchedule.objects.get_or_create(
                every=15,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'notifications_15min'}
            )

            interval_30min, _ = IntervalSchedule.objects.get_or_create(
                every=30,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'notifications_30min'}
            )

            crontab_daily_7am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=7,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'notifications_daily_7am'}
            )

            crontab_weekly_monday_8am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=8,
                day_of_week=1,  # Monday
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'notifications_weekly_monday_8am'}
            )

            crontab_weekly_sunday_3am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=3,
                day_of_week=0,  # Sunday
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'notifications_weekly_sunday_3am'}
            )

            # Define tasks
            tasks = [
                {
                    'name': 'notifications_process_pending',
                    'task': 'apps.notifications.tasks.process_pending_notifications',
                    'schedule': interval_15min,
                    'description': 'Process pending notifications every 15 minutes'
                },
                {
                    'name': 'notifications_scheduled',
                    'task': 'apps.notifications.tasks.process_scheduled_notifications',
                    'schedule': interval_5min,
                    'description': 'Process scheduled notifications every 5 minutes'
                },
                {
                    'name': 'notifications_retry_failed',
                    'task': 'apps.notifications.tasks.retry_failed_notifications',
                    'schedule': interval_30min,
                    'description': 'Retry failed notifications every 30 minutes'
                },
                {
                    'name': 'notifications_daily_digest',
                    'task': 'apps.notifications.tasks.send_daily_digest',
                    'schedule': crontab_daily_7am,
                    'description': 'Send daily notification digests at 7:00 AM'
                },
                {
                    'name': 'notifications_weekly_digest',
                    'task': 'apps.notifications.tasks.send_weekly_digest',
                    'schedule': crontab_weekly_monday_8am,
                    'description': 'Send weekly notification digests on Monday at 8:00 AM'
                },
                {
                    'name': 'notifications_cleanup',
                    'task': 'apps.notifications.tasks.cleanup_notifications',
                    'schedule': crontab_weekly_sunday_3am,
                    'description': 'Cleanup old notifications weekly on Sunday at 3:00 AM'
                },
            ]

            # Create periodic tasks
            for task_data in tasks:
                schedule_obj = task_data['schedule']
                PeriodicTask.objects.get_or_create(
                    name=task_data['name'],
                    defaults={
                        'task': task_data['task'],
                        'interval': schedule_obj if isinstance(schedule_obj, IntervalSchedule) else None,
                        'crontab': schedule_obj if isinstance(schedule_obj, CrontabSchedule) else None,
                        'enabled': True,
                        'description': task_data['description'],
                        'start_time': timezone.now(),
                        'one_off': False,
                    }
                )
                logger.info(f'Periodic task {task_data["name"]} registered.')

        except Exception as e:
            logger.error(f'Failed to set up periodic tasks: {e}')

    def _is_celery_installed(self) -> bool:
        """Check if Celery is installed."""
        try:
            import celery  # noqa
            return True
        except ImportError:
            return False

    # ==========================================================================
    # DATABASE CHECKS
    # ==========================================================================

    def _perform_database_checks(self):
        """Perform database checks to ensure required models exist."""
        logger.info('Performing database checks for notifications app...')

        try:
            from django.db import connection
            from django.db.migrations.executor import MigrationExecutor

            # Check if migrations are applied
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            if plan:
                logger.warning('There are pending migrations for the notifications app.')
            else:
                logger.info('All notifications migrations are applied.')

            # Check required database tables exist
            from .models import Notification
            table_name = Notification._meta.db_table
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name=%s)",
                    [table_name]
                )
                exists = cursor.fetchone()[0]
                if exists:
                    logger.info(f'Table "{table_name}" exists.')
                else:
                    logger.warning(f'Table "{table_name}" does not exist; run migrations.')

            # Check notification_preferences table
            from .models import NotificationPreference
            pref_table_name = NotificationPreference._meta.db_table
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name=%s)",
                    [pref_table_name]
                )
                exists = cursor.fetchone()[0]
                if exists:
                    logger.info(f'Table "{pref_table_name}" exists.')
                else:
                    logger.warning(f'Table "{pref_table_name}" does not exist; run migrations.')

        except Exception as e:
            logger.error(f'Database checks failed: {e}')

    # ==========================================================================
    # UTILITY METHODS
    # ==========================================================================

    def get_version(self) -> str:
        """Return the version of the notifications app."""
        from . import __version__
        return __version__

    # ==========================================================================
    # STATIC INITIALIZATION
    # ==========================================================================

    @classmethod
    def initialize_static(cls):
        """
        Perform static initialization that does not depend on the Django app
        being ready. Useful for setup during import time.
        """
        # Register system checks
        cls.register_system_checks()
        logger.debug('Notifications system checks registered.')


# ============================================================================
# STATIC INITIALIZATION
# ============================================================================

# Perform static initialization when this module is imported
NotificationsConfig.initialize_static()

# ============================================================================
# LOGGING FOR APP STARTUP
# ============================================================================

logger.info('Notifications app module loaded.')

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['NotificationsConfig']