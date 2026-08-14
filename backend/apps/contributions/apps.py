"""
App configuration for the contributions app.

This module defines the Django AppConfig for the contributions app,
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

logger = logging.getLogger(__name__)


class ContributionsConfig(AppConfig):
    """
    Configuration for the contributions app.

    This class handles app initialization, signal registration,
    system checks, environment validation, and startup tasks.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.contributions'
    label = 'contributions'
    verbose_name = _('Contributions')

    # Internal state for initialization tracking
    _initialized = False
    _checks_run = False
    _signals_registered = False

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
        8. Logs successful initialization
        """
        if self._initialized:
            logger.debug('Contributions app already initialized.')
            return

        logger.info('Initializing contributions app...')

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
        # 9. PERFORM DATABASE CHECKS (if needed)
        # ====================================================================
        self._perform_database_checks()

        # ====================================================================
        # 10. LOG SUCCESSFUL INITIALIZATION
        # ====================================================================
        self._initialized = True
        logger.info(f'Contributions app v{self.get_version()} initialized successfully.')

    # ==========================================================================
    # REGISTRATION METHODS
    # ==========================================================================

    def _register_signals(self):
        """Import signals module to register signal handlers."""
        if self._signals_registered:
            return

        try:
            import apps.contributions.signals
            # Force registration of signal handlers
            from apps.contributions import signals as _  # noqa
            self._signals_registered = True
            logger.info('Contributions signals registered successfully.')
        except ImportError as e:
            logger.error(f'Failed to import contributions signals: {e}')
            # Do not raise to allow app to continue
        except Exception as e:
            logger.error(f'Unexpected error registering signals: {e}')

    def _register_admin(self):
        """Import admin module to register admin classes."""
        try:
            import apps.contributions.admin
            # Admin classes are automatically registered via @admin.register
            logger.info('Contributions admin registered successfully.')
        except ImportError as e:
            logger.error(f'Failed to import contributions admin: {e}')

    def _register_management_commands(self):
        """Register custom management commands (if any)."""
        # This is a placeholder; actual commands would be in management/commands/
        # We can add a check to ensure management directory exists.
        try:
            import apps.contributions.management  # noqa
            logger.info('Contributions management commands registered.')
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
            # Run only checks for our app
            checks_to_run = ['apps.contributions']
            errors = run_checks(checks_to_run)
            if errors:
                for error in errors:
                    logger.error(f'System check error: {error}')
            else:
                logger.info('Contributions system checks passed.')
            self._checks_run = True
        except Exception as e:
            logger.error(f'Error running system checks: {e}')

    @classmethod
    def register_system_checks(cls):
        """
        Register custom system checks for the contributions app.
        These are executed during Django's check framework.
        """
        def check_contribution_settings(app_configs, **kwargs):
            errors = []

            # Check required settings
            required_settings = [
                'CONTRIBUTION_MAX_AMOUNT',
                'CONTRIBUTION_MIN_AMOUNT',
                'CONTRIBUTION_DEFAULT_PENALTY_RATE',
                'CONTRIBUTION_OVERDUE_GRACE_DAYS',
                'CONTRIBUTION_AUTO_WAIVE_DAYS',
                'CONTRIBUTION_MAX_PENALTY_PERCENT',
            ]
            for setting in required_settings:
                if not hasattr(settings, setting):
                    errors.append(
                        Error(
                            f'Missing required setting: {setting}',
                            hint=f'Define {setting} in your settings file.',
                            obj='contributions.apps.ContributionsConfig',
                            id='contributions.E001',
                        )
                    )

            # Check that CONTRIBUTION_MAX_PENALTY_PERCENT is between 0 and 100
            if hasattr(settings, 'CONTRIBUTION_MAX_PENALTY_PERCENT'):
                penalty = getattr(settings, 'CONTRIBUTION_MAX_PENALTY_PERCENT')
                if not (0 <= penalty <= 100):
                    errors.append(
                        Error(
                            f'CONTRIBUTION_MAX_PENALTY_PERCENT must be between 0 and 100, got {penalty}.',
                            hint='Set a value between 0 and 100 inclusive.',
                            obj='contributions.apps.ContributionsConfig',
                            id='contributions.E002',
                        )
                    )

            return errors

        # Register the check
        register(Tags.models)(check_contribution_settings)

    # ==========================================================================
    # ENVIRONMENT VALIDATION
    # ==========================================================================

    def _validate_environment(self):
        """Validate environment variables and settings."""
        logger.info('Validating contributions environment...')

        # ====================================================================
        # 1. Check required environment variables
        # ====================================================================
        required_env = [
            'CHAPA_SECRET_KEY',
            'CHAPA_PUBLIC_KEY',
            'TELEBIRR_API_KEY',
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
        # 4. Validate payment gateway credentials
        # ====================================================================
        self._validate_payment_gateways()

        logger.info('Contributions environment validation completed.')

    def _validate_payment_gateways(self):
        """Validate payment gateway configurations."""
        # Chapa
        chapa_secret = getattr(settings, 'CHAPA_SECRET_KEY', '')
        if not chapa_secret:
            logger.warning('Chapa secret key is not set. Chapa payments will fail.')

        # Telebirr
        telebirr_key = getattr(settings, 'TELEBIRR_API_KEY', '')
        if not telebirr_key:
            logger.warning('Telebirr API key is not set. Telebirr payments will fail.')

        # Check that at least one gateway is configured
        if not chapa_secret and not telebirr_key:
            logger.warning(
                'No payment gateway is configured. '
                'Set CHAPA_SECRET_KEY or TELEBIRR_API_KEY to enable payments.'
            )

    # ==========================================================================
    # DEFAULT INITIALIZATION
    # ==========================================================================

    def _initialize_defaults(self):
        """Initialize default configuration values."""
        logger.info('Initializing contribution defaults...')

        # Set default values for settings if not defined
        defaults = {
            'CONTRIBUTION_MAX_AMOUNT': 1000000.00,
            'CONTRIBUTION_MIN_AMOUNT': 10.00,
            'CONTRIBUTION_DEFAULT_PENALTY_RATE': 0.02,   # 2%
            'CONTRIBUTION_OVERDUE_GRACE_DAYS': 7,
            'CONTRIBUTION_AUTO_WAIVE_DAYS': 90,
            'CONTRIBUTION_MAX_PENALTY_PERCENT': 50,      # 50% of amount
            'CONTRIBUTION_REMINDER_INTERVAL_DAYS': 2,
            'CONTRIBUTION_MAX_REMINDERS': 3,
            'CONTRIBUTION_PENDING_SYNC_INTERVAL': 3600,  # 1 hour
            'CONTRIBUTION_OVERDUE_CHECK_INTERVAL': 21600,  # 6 hours
            'CONTRIBUTION_REPORT_GENERATION_HOUR': 0,    # midnight
        }

        for key, default_value in defaults.items():
            if not hasattr(settings, key):
                setattr(settings, key, default_value)
                logger.debug(f'Set default {key} = {default_value}')

        logger.info('Contribution defaults initialized.')

    # ==========================================================================
    # CACHE INVALIDATION HOOKS
    # ==========================================================================

    def _setup_cache_hooks(self):
        """Set up cache invalidation hooks for contribution-related models."""
        logger.info('Setting up cache invalidation hooks...')

        # Import cache and signal receivers
        from django.core.cache import cache
        from django.db.models.signals import post_save, post_delete

        # Define a generic cache invalidation receiver
        def invalidate_contribution_cache(sender, instance, **kwargs):
            """Invalidate cache for contribution-related models."""
            cache_keys = []
            if hasattr(instance, 'id'):
                cache_keys.append(f'contribution_{instance.id}')
            if hasattr(instance, 'contribution') and hasattr(instance.contribution, 'id'):
                cache_keys.append(f'contribution_{instance.contribution.id}')
                cache_keys.append(f'contribution_payments_{instance.contribution.id}')
            if hasattr(instance, 'user') and hasattr(instance.user, 'id'):
                cache_keys.append(f'user_contributions_{instance.user.id}')
                cache_keys.append(f'user_pending_{instance.user.id}')
                cache_keys.append(f'user_overdue_{instance.user.id}')
            if hasattr(instance, 'group') and hasattr(instance.group, 'id'):
                cache_keys.append(f'group_contributions_{instance.group.id}')
                cache_keys.append(f'group_{instance.group.id}')
                cache_keys.append(f'group_stats_{instance.group.id}')

            for key in cache_keys:
                cache.delete(key)

            logger.debug(f'Invalidated cache keys: {cache_keys}')

        # Connect signals for Contribution and related models
        from .models import Contribution, ContributionPayment, ContributionReminder
        post_save.connect(invalidate_contribution_cache, sender=Contribution)
        post_delete.connect(invalidate_contribution_cache, sender=Contribution)
        post_save.connect(invalidate_contribution_cache, sender=ContributionPayment)
        post_delete.connect(invalidate_contribution_cache, sender=ContributionPayment)
        post_save.connect(invalidate_contribution_cache, sender=ContributionReminder)
        post_delete.connect(invalidate_contribution_cache, sender=ContributionReminder)

        logger.info('Cache invalidation hooks set up.')

    # ==========================================================================
    # PERIODIC TASKS SETUP
    # ==========================================================================

    def _setup_periodic_tasks(self):
        """Set up periodic tasks for Celery Beat if celery is installed."""
        if not self._is_celery_installed():
            logger.info('Celery not installed; periodic tasks not configured.')
            return

        try:
            from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule

            # Check if we already have tasks set up
            if PeriodicTask.objects.filter(name__startswith='contributions_').exists():
                logger.info('Periodic tasks already configured.')
                return

            # Create schedules
            interval, _ = IntervalSchedule.objects.get_or_create(
                every=3600,
                period=IntervalSchedule.SECONDS,
                defaults={'name': 'contributions_hourly'}
            )

            crontab, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=0,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'contributions_daily'}
            )

            # Define tasks
            tasks = [
                {
                    'name': 'contributions_process_pending',
                    'task': 'apps.contributions.tasks.process_pending_contributions',
                    'schedule': interval,
                    'description': 'Process pending contributions hourly'
                },
                {
                    'name': 'contributions_check_overdue',
                    'task': 'apps.contributions.tasks.check_overdue_contributions',
                    'schedule': interval,
                    'description': 'Check overdue contributions every 6 hours'
                },
                {
                    'name': 'contributions_send_digest',
                    'task': 'apps.contributions.tasks.send_contribution_digest',
                    'schedule': crontab,
                    'description': 'Send daily contribution digest'
                },
                {
                    'name': 'contributions_auto_waive',
                    'task': 'apps.contributions.tasks.auto_waive_overdue_contributions',
                    'schedule': crontab,
                    'description': 'Auto-waive overdue contributions daily'
                },
                {
                    'name': 'contributions_update_stats',
                    'task': 'apps.contributions.tasks.update_contribution_stats',
                    'schedule': interval,
                    'description': 'Update contribution statistics every 6 hours'
                },
                {
                    'name': 'contributions_cleanup',
                    'task': 'apps.contributions.tasks.cleanup_completed_contributions',
                    'schedule': crontab,
                    'description': 'Cleanup completed contributions weekly'
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
            import celery
            return True
        except ImportError:
            return False

    # ==========================================================================
    # DATABASE CHECKS
    # ==========================================================================

    def _perform_database_checks(self):
        """Perform database checks to ensure required models exist."""
        logger.info('Performing database checks for contributions app...')

        try:
            from django.db import connection
            from django.db.migrations.executor import MigrationExecutor

            # Check if migrations are applied
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            if plan:
                logger.warning('There are pending migrations for the contributions app.')
            else:
                logger.info('All contributions migrations are applied.')

            # Check required database tables exist
            from .models import Contribution
            table_name = Contribution._meta.db_table
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
        """Return the version of the contributions app."""
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
        logger.debug('Contributions system checks registered.')


# ============================================================================
# STATIC INITIALIZATION
# ============================================================================

# Perform static initialization when this module is imported
ContributionsConfig.initialize_static()

# ============================================================================
# LOGGING FOR APP STARTUP
# ============================================================================

# This log will appear when the app is loaded
logger.info('Contributions app module loaded.')

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['ContributionsConfig']