"""
App configuration for the payments app.

This module defines the Django AppConfig for the payments app,
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


class PaymentsConfig(AppConfig):
    """
    Configuration for the payments app.

    This class handles app initialization, signal registration,
    system checks, environment validation, and startup tasks.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.payments'
    label = 'payments'
    verbose_name = _('Payments')

    # Internal state for initialization tracking
    _initialized = False
    _checks_run = False
    _signals_registered = False
    _admin_registered = False

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
            logger.debug('Payments app already initialized.')
            return

        logger.info('Initializing payments app...')

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
        logger.info(f'Payments app v{self.get_version()} initialized successfully.')

    # ==========================================================================
    # REGISTRATION METHODS
    # ==========================================================================

    def _register_signals(self):
        """Import signals module to register signal handlers."""
        if self._signals_registered:
            return

        try:
            import apps.payments.signals
            # Force registration of signal handlers
            from apps.payments import signals as _  # noqa
            self._signals_registered = True
            logger.info('Payments signals registered successfully.')
        except ImportError as e:
            logger.error(f'Failed to import payments signals: {e}')
        except Exception as e:
            logger.error(f'Unexpected error registering signals: {e}')

    def _register_admin(self):
        """Import admin module to register admin classes."""
        if self._admin_registered:
            return

        try:
            import apps.payments.admin
            # Admin classes are automatically registered via @admin.register
            self._admin_registered = True
            logger.info('Payments admin registered successfully.')
        except ImportError as e:
            logger.error(f'Failed to import payments admin: {e}')
        except Exception as e:
            logger.error(f'Unexpected error registering admin: {e}')

    def _register_management_commands(self):
        """Register custom management commands (if any)."""
        try:
            import apps.payments.management  # noqa
            logger.info('Payments management commands registered.')
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
            checks_to_run = ['apps.payments']
            errors = run_checks(checks_to_run)
            if errors:
                for error in errors:
                    logger.error(f'System check error: {error}')
            else:
                logger.info('Payments system checks passed.')
            self._checks_run = True
        except Exception as e:
            logger.error(f'Error running system checks: {e}')

    @classmethod
    def register_system_checks(cls):
        """
        Register custom system checks for the payments app.
        These are executed during Django's check framework.
        """
        def check_payment_settings(app_configs, **kwargs):
            errors = []

            # Check required settings
            required_settings = [
                'PAYMENT_MAX_AMOUNT',
                'PAYMENT_MIN_AMOUNT',
                'PAYMENT_EXPIRY_HOURS',
                'PAYMENT_MAX_RETRY_COUNT',
                'PAYMENT_WEBHOOK_TIMEOUT',
                'PAYMENT_RECONCILIATION_DAYS',
            ]
            for setting in required_settings:
                if not hasattr(settings, setting):
                    errors.append(
                        Error(
                            f'Missing required setting: {setting}',
                            hint=f'Define {setting} in your settings file.',
                            obj='payments.apps.PaymentsConfig',
                            id='payments.E001',
                        )
                    )

            # Check that PAYMENT_EXPIRY_HOURS is positive
            if hasattr(settings, 'PAYMENT_EXPIRY_HOURS'):
                expiry = getattr(settings, 'PAYMENT_EXPIRY_HOURS')
                if expiry <= 0:
                    errors.append(
                        Error(
                            f'PAYMENT_EXPIRY_HOURS must be greater than 0, got {expiry}.',
                            hint='Set a positive integer.',
                            obj='payments.apps.PaymentsConfig',
                            id='payments.E002',
                        )
                    )

            # Check payment gateway configuration
            if not hasattr(settings, 'CHAPA_SECRET_KEY') or not getattr(settings, 'CHAPA_SECRET_KEY'):
                errors.append(
                    Warning(
                        'CHAPA_SECRET_KEY is not set. Chapa payments will not work.',
                        hint='Set CHAPA_SECRET_KEY in your settings or environment.',
                        obj='payments.apps.PaymentsConfig',
                        id='payments.W001',
                    )
                )
            if not hasattr(settings, 'TELEBIRR_API_KEY') or not getattr(settings, 'TELEBIRR_API_KEY'):
                errors.append(
                    Warning(
                        'TELEBIRR_API_KEY is not set. Telebirr payments will not work.',
                        hint='Set TELEBIRR_API_KEY in your settings or environment.',
                        obj='payments.apps.PaymentsConfig',
                        id='payments.W002',
                    )
                )

            return errors

        # Register the check
        register(Tags.models)(check_payment_settings)

    # ==========================================================================
    # ENVIRONMENT VALIDATION
    # ==========================================================================

    def _validate_environment(self):
        """Validate environment variables and settings."""
        logger.info('Validating payments environment...')

        # ====================================================================
        # 1. Check required environment variables
        # ====================================================================
        required_env = [
            'CHAPA_SECRET_KEY',
            'CHAPA_PUBLIC_KEY',
            'TELEBIRR_API_KEY',
            'PAYMENT_WEBHOOK_SECRET',
        ]
        missing = []
        for var in required_env:
            if not os.environ.get(var):
                missing.append(var)

        if missing:
            logger.warning(
                f'Missing payment gateway environment variables: {", ".join(missing)}. '
                'Payment processing will be limited.'
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
        # 4. Validate webhook secret
        # ====================================================================
        webhook_secret = getattr(settings, 'PAYMENT_WEBHOOK_SECRET', '')
        if not webhook_secret:
            logger.warning('PAYMENT_WEBHOOK_SECRET is not set. Webhook signatures will not be verified.')

        logger.info('Payments environment validation completed.')

    # ==========================================================================
    # DEFAULT INITIALIZATION
    # ==========================================================================

    def _initialize_defaults(self):
        """Initialize default configuration values."""
        logger.info('Initializing payment defaults...')

        # Set default values for settings if not defined
        defaults = {
            'PAYMENT_MAX_AMOUNT': 10000000.00,          # 10 million
            'PAYMENT_MIN_AMOUNT': 1.00,
            'PAYMENT_EXPIRY_HOURS': 24,
            'PAYMENT_MAX_RETRY_COUNT': 3,
            'PAYMENT_WEBHOOK_TIMEOUT': 30,
            'PAYMENT_RECONCILIATION_DAYS': 30,
            'PAYMENT_BATCH_SIZE': 100,
            'PAYMENT_AUTO_COMPLETE_AFTER_WEBHOOK': True,
            'PAYMENT_REQUIRE_VERIFICATION': True,
            'PAYMENT_REMINDER_INTERVAL_HOURS': 6,
            'PAYMENT_MAX_REMINDERS': 3,
        }

        for key, default_value in defaults.items():
            if not hasattr(settings, key):
                setattr(settings, key, default_value)
                logger.debug(f'Set default {key} = {default_value}')

        logger.info('Payment defaults initialized.')

    # ==========================================================================
    # CACHE INVALIDATION HOOKS
    # ==========================================================================

    def _setup_cache_hooks(self):
        """Set up cache invalidation hooks for payment-related models."""
        logger.info('Setting up cache invalidation hooks...')

        from django.core.cache import cache
        from django.db.models.signals import post_save, post_delete

        # Define a generic cache invalidation receiver
        def invalidate_payment_cache(sender, instance, **kwargs):
            """Invalidate cache for payment-related models."""
            cache_keys = []
            if hasattr(instance, 'id'):
                cache_keys.append(f'payment_{instance.id}')
                cache_keys.append(f'payment_detail_{instance.id}')
                cache_keys.append(f'payment_stats_{instance.id}')
            if hasattr(instance, 'reference'):
                cache_keys.append(f'payment_{instance.reference}')
            if hasattr(instance, 'payment') and hasattr(instance.payment, 'id'):
                cache_keys.append(f'payment_{instance.payment.id}')
                cache_keys.append(f'payment_transactions_{instance.payment.id}')
                cache_keys.append(f'payment_gateway_logs_{instance.payment.id}')
                cache_keys.append(f'payment_reconciliations_{instance.payment.id}')
                cache_keys.append(f'payment_disputes_{instance.payment.id}')
            if hasattr(instance, 'user') and hasattr(instance.user, 'id'):
                cache_keys.append(f'user_payments_{instance.user.id}')
                cache_keys.append(f'user_payouts_{instance.user.id}')
            if hasattr(instance, 'group') and hasattr(instance.group, 'id'):
                cache_keys.append(f'group_payments_{instance.group.id}')
                cache_keys.append(f'group_payouts_{instance.group.id}')
                cache_keys.append(f'group_{instance.group.id}')
                cache_keys.append(f'group_stats_{instance.group.id}')

            for key in cache_keys:
                cache.delete(key)

            logger.debug(f'Invalidated {len(cache_keys)} cache keys for {sender.__name__} {instance.id}')

        # Connect signals for all payment-related models
        from .models import (
            Payment, Payout, PaymentTransaction, PaymentGatewayLog,
            PaymentWebhookLog, PaymentReconciliation, PaymentDispute,
            Settlement, PaymentMethod, PaymentAudit
        )

        post_save.connect(invalidate_payment_cache, sender=Payment)
        post_delete.connect(invalidate_payment_cache, sender=Payment)
        post_save.connect(invalidate_payment_cache, sender=Payout)
        post_delete.connect(invalidate_payment_cache, sender=Payout)
        post_save.connect(invalidate_payment_cache, sender=PaymentTransaction)
        post_delete.connect(invalidate_payment_cache, sender=PaymentTransaction)
        post_save.connect(invalidate_payment_cache, sender=PaymentGatewayLog)
        post_delete.connect(invalidate_payment_cache, sender=PaymentGatewayLog)
        post_save.connect(invalidate_payment_cache, sender=PaymentWebhookLog)
        post_delete.connect(invalidate_payment_cache, sender=PaymentWebhookLog)
        post_save.connect(invalidate_payment_cache, sender=PaymentReconciliation)
        post_delete.connect(invalidate_payment_cache, sender=PaymentReconciliation)
        post_save.connect(invalidate_payment_cache, sender=PaymentDispute)
        post_delete.connect(invalidate_payment_cache, sender=PaymentDispute)
        post_save.connect(invalidate_payment_cache, sender=Settlement)
        post_delete.connect(invalidate_payment_cache, sender=Settlement)
        post_save.connect(invalidate_payment_cache, sender=PaymentMethod)
        post_delete.connect(invalidate_payment_cache, sender=PaymentMethod)

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
            if PeriodicTask.objects.filter(name__startswith='payments_').exists():
                logger.info('Periodic tasks already configured.')
                return

            # Create schedules
            interval_15min, _ = IntervalSchedule.objects.get_or_create(
                every=15,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'payments_15min'}
            )

            interval_30min, _ = IntervalSchedule.objects.get_or_create(
                every=30,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'payments_30min'}
            )

            crontab_daily, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=1,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'payments_daily'}
            )

            crontab_weekly, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=3,
                day_of_week=0,  # Sunday
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'payments_weekly'}
            )

            # Define tasks
            tasks = [
                {
                    'name': 'payments_process_pending',
                    'task': 'apps.payments.tasks.process_pending_payments',
                    'schedule': interval_15min,
                    'description': 'Process pending payments every 15 minutes'
                },
                {
                    'name': 'payments_process_payouts',
                    'task': 'apps.payments.tasks.process_payouts',
                    'schedule': interval_30min,
                    'description': 'Process payouts every 30 minutes'
                },
                {
                    'name': 'payments_reconcile',
                    'task': 'apps.payments.tasks.reconcile_payments',
                    'schedule': crontab_daily,
                    'description': 'Reconcile payments daily at 1:00 AM'
                },
                {
                    'name': 'payments_send_digest',
                    'task': 'apps.payments.tasks.send_payment_digest',
                    'schedule': crontab_daily,
                    'description': 'Send daily payment digest at 1:00 AM'
                },
                {
                    'name': 'payments_update_stats',
                    'task': 'apps.payments.tasks.update_payment_stats',
                    'schedule': interval_30min,
                    'description': 'Update payment statistics every 30 minutes'
                },
                {
                    'name': 'payments_cleanup',
                    'task': 'apps.payments.tasks.cleanup_payment_logs',
                    'schedule': crontab_weekly,
                    'description': 'Cleanup payment logs weekly'
                },
                {
                    'name': 'payments_retry_failed',
                    'task': 'apps.payments.tasks.retry_failed_payments',
                    'schedule': interval_30min,
                    'description': 'Retry failed payments every 30 minutes'
                },
                {
                    'name': 'payments_auto_refund_expired',
                    'task': 'apps.payments.tasks.auto_refund_expired',
                    'schedule': crontab_daily,
                    'description': 'Auto-refund expired payments daily at 2:00 AM'
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
        logger.info('Performing database checks for payments app...')

        try:
            from django.db import connection
            from django.db.migrations.executor import MigrationExecutor

            # Check if migrations are applied
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            if plan:
                logger.warning('There are pending migrations for the payments app.')
            else:
                logger.info('All payments migrations are applied.')

            # Check required database tables exist
            from .models import Payment
            table_name = Payment._meta.db_table
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

        except Exception as e:
            logger.error(f'Database checks failed: {e}')

    # ==========================================================================
    # UTILITY METHODS
    # ==========================================================================

    def get_version(self) -> str:
        """Return the version of the payments app."""
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
        logger.debug('Payments system checks registered.')


# ============================================================================
# STATIC INITIALIZATION
# ============================================================================

# Perform static initialization when this module is imported
PaymentsConfig.initialize_static()

# ============================================================================
# LOGGING FOR APP STARTUP
# ============================================================================

logger.info('Payments app module loaded.')

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['PaymentsConfig']