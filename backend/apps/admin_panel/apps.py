"""
App configuration for the admin panel app.

This module defines the Django AppConfig for the admin panel app,
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
from django.db.models.signals import post_migrate
from decimal import Decimal
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class AdminPanelConfig(AppConfig):
    """
    Configuration for the admin panel app.

    This class handles app initialization, signal registration,
    system checks, environment validation, and startup tasks.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.admin_panel'
    label = 'admin_panel'
    verbose_name = _('Admin Panel')

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
            logger.debug('Admin panel app already initialized.')
            return

        logger.info('Initializing admin panel app...')

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
        logger.info(f'Admin Panel app v{self.get_version()} initialized successfully.')

    # ==========================================================================
    # REGISTRATION METHODS
    # ==========================================================================

    def _register_signals(self):
        """Import signals module to register signal handlers."""
        if self._signals_registered:
            return

        try:
            import apps.admin_panel.signals
            # Force registration of signal handlers
            from apps.admin_panel import signals as _  # noqa
            self._signals_registered = True
            logger.info('Admin panel signals registered successfully.')
        except ImportError as e:
            logger.error(f'Failed to import admin panel signals: {e}')
        except Exception as e:
            logger.error(f'Unexpected error registering signals: {e}')

    def _register_admin(self):
        """Import admin module to register admin classes."""
        if self._admin_registered:
            return

        try:
            import apps.admin_panel.admin
            # Admin classes are automatically registered via @admin.register
            self._admin_registered = True
            logger.info('Admin panel admin registered successfully.')
        except ImportError as e:
            logger.error(f'Failed to import admin panel admin: {e}')
        except Exception as e:
            logger.error(f'Unexpected error registering admin: {e}')

    def _register_management_commands(self):
        """Register custom management commands (if any)."""
        if self._tasks_registered:
            return

        try:
            import apps.admin_panel.management  # noqa
            self._tasks_registered = True
            logger.info('Admin panel management commands registered.')
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
            checks_to_run = ['apps.admin_panel']
            errors = run_checks(checks_to_run)
            if errors:
                for error in errors:
                    logger.error(f'System check error: {error}')
            else:
                logger.info('Admin panel system checks passed.')
            self._checks_run = True
        except Exception as e:
            logger.error(f'Error running system checks: {e}')

    @classmethod
    def register_system_checks(cls):
        """
        Register custom system checks for the admin panel app.
        These are executed during Django's check framework.
        """
        def check_admin_settings(app_configs, **kwargs):
            errors = []

            # Check required settings
            required_settings = [
                'ADMIN_BACKUP_DIR',
                'ADMIN_REPORT_RETENTION_DAYS',
                'ADMIN_AUDIT_RETENTION_DAYS',
                'ADMIN_LOG_RETENTION_DAYS',
                'ADMIN_ACTION_RETENTION_DAYS',
                'ADMIN_REPORT_AUTO_GENERATE',
                'ADMIN_ALERT_EMAIL_RECIPIENTS',
            ]
            for setting in required_settings:
                if not hasattr(settings, setting):
                    errors.append(
                        Error(
                            f'Missing required setting: {setting}',
                            hint=f'Define {setting} in your settings file.',
                            obj='admin_panel.apps.AdminPanelConfig',
                            id='admin_panel.E001',
                        )
                    )

            # Check backup directory
            backup_dir = getattr(settings, 'ADMIN_BACKUP_DIR', '')
            if backup_dir and not os.path.exists(backup_dir):
                try:
                    os.makedirs(backup_dir, exist_ok=True)
                except Exception as e:
                    errors.append(
                        Warning(
                            f'Cannot create backup directory: {backup_dir}',
                            hint=f'Ensure the directory exists and is writable. Error: {str(e)}',
                            obj='admin_panel.apps.AdminPanelConfig',
                            id='admin_panel.W001',
                        )
                    )

            # Check retention days
            retention_days = getattr(settings, 'ADMIN_REPORT_RETENTION_DAYS', 30)
            if retention_days < 7:
                errors.append(
                    Warning(
                        f'ADMIN_REPORT_RETENTION_DAYS is low ({retention_days}). Consider increasing for compliance.',
                        hint='Set to at least 30 days for regulatory compliance.',
                        obj='admin_panel.apps.AdminPanelConfig',
                        id='admin_panel.W002',
                    )
                )

            return errors

        # Register the check
        register(Tags.models)(check_admin_settings)

    # ==========================================================================
    # ENVIRONMENT VALIDATION
    # ==========================================================================

    def _validate_environment(self):
        """Validate environment variables and settings."""
        logger.info('Validating admin panel environment...')

        # ====================================================================
        # 1. Check required environment variables
        # ====================================================================
        required_env = [
            'ADMIN_EMAIL',
        ]
        missing = []
        for var in required_env:
            if not os.environ.get(var):
                missing.append(var)

        if missing:
            logger.warning(
                f'Missing admin environment variables: {", ".join(missing)}. '
                'Some admin features may not work.'
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
        # 4. Check backup directory
        # ====================================================================
        backup_dir = getattr(settings, 'ADMIN_BACKUP_DIR', '/tmp/admin_backups')
        if not os.path.exists(backup_dir):
            try:
                os.makedirs(backup_dir, exist_ok=True)
                logger.info(f'Created backup directory: {backup_dir}')
            except Exception as e:
                logger.error(f'Failed to create backup directory {backup_dir}: {str(e)}')

        # ====================================================================
        # 5. Check email configuration
        # ====================================================================
        if not settings.DEFAULT_FROM_EMAIL:
            logger.warning('DEFAULT_FROM_EMAIL is not set. Admin emails may not be sent.')

        logger.info('Admin panel environment validation completed.')

    # ==========================================================================
    # DEFAULT INITIALIZATION
    # ==========================================================================

    def _initialize_defaults(self):
        """Initialize default configuration values."""
        logger.info('Initializing admin panel defaults...')

        # Set default values for settings if not defined
        defaults = {
            'ADMIN_BACKUP_DIR': '/tmp/admin_backups',
            'ADMIN_REPORT_RETENTION_DAYS': 30,
            'ADMIN_AUDIT_RETENTION_DAYS': 180,
            'ADMIN_LOG_RETENTION_DAYS': 90,
            'ADMIN_ACTION_RETENTION_DAYS': 365,
            'ADMIN_REPORT_AUTO_GENERATE': True,
            'ADMIN_ALERT_EMAIL_RECIPIENTS': [],
            'ADMIN_DASHBOARD_WIDGETS_ENABLED': True,
            'ADMIN_SYSTEM_HEALTH_ENABLED': True,
            'ADMIN_MAINTENANCE_MODE_ENABLED': False,
            'ADMIN_CACHE_PREFIX': 'admin_',
            'ADMIN_SESSION_TIMEOUT': 3600,
            'ADMIN_MAX_REPORT_SIZE': 10485760,  # 10 MB
            'ADMIN_EXPORT_LIMIT': 10000,
            'ADMIN_BULK_ACTION_LIMIT': 100,
        }

        for key, default_value in defaults.items():
            if not hasattr(settings, key):
                setattr(settings, key, default_value)
                logger.debug(f'Set default {key} = {default_value}')

        logger.info('Admin panel defaults initialized.')

    # ==========================================================================
    # CACHE INVALIDATION HOOKS
    # ==========================================================================

    def _setup_cache_hooks(self):
        """Set up cache invalidation hooks for admin-related models."""
        logger.info('Setting up cache invalidation hooks...')

        from django.core.cache import cache
        from django.db.models.signals import post_save, post_delete

        # Define a generic cache invalidation receiver
        def invalidate_admin_cache(sender, instance, **kwargs):
            """Invalidate cache for admin panel models."""
            cache_keys = []
            model_name = sender._meta.model_name

            if model_name == 'systemsetting':
                cache_keys.append('system_settings_all')
                if hasattr(instance, 'key'):
                    cache_keys.append(f'system_setting_{instance.key}')
            elif model_name == 'adminaction':
                cache_keys.append('admin_actions_recent')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'admin_action_{instance.id}')
            elif model_name == 'adminlog':
                cache_keys.append('admin_logs_recent')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'admin_log_{instance.id}')
            elif model_name == 'adminpreference':
                if hasattr(instance, 'admin_id'):
                    cache_keys.append(f'admin_prefs_{instance.admin_id}')
                cache_keys.append('admin_prefs_all')
            elif model_name == 'report':
                cache_keys.append('reports_recent')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'report_{instance.id}')
            elif model_name == 'reportschedule':
                cache_keys.append('report_schedules_active')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'report_schedule_{instance.id}')
            elif model_name == 'dashboardwidget':
                cache_keys.append('dashboard_widgets_all')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'dashboard_widget_{instance.id}')
            elif model_name == 'audittrail':
                if hasattr(instance, 'id'):
                    cache_keys.append(f'audit_trail_{instance.id}')
            elif model_name == 'maintenancelog':
                cache_keys.append('maintenance_logs_recent')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'maintenance_log_{instance.id}')

            # Also invalidate any user/group cache if applicable
            if hasattr(instance, 'user') and instance.user:
                cache_keys.append(f'user_{instance.user.id}')
            if hasattr(instance, 'admin') and instance.admin:
                cache_keys.append(f'user_{instance.admin.id}')
            if hasattr(instance, 'group') and instance.group:
                cache_keys.append(f'group_{instance.group.id}')

            for key in cache_keys:
                cache.delete(key)

            if cache_keys:
                logger.debug(f'Invalidated {len(cache_keys)} cache keys for {model_name} {instance.id}')

        # Connect signals for all admin panel models
        from .models import (
            AdminAction, AdminLog, AdminPreference, SystemSetting,
            MaintenanceLog, Report, ReportSchedule, AuditTrail, DashboardWidget
        )

        post_save.connect(invalidate_admin_cache, sender=AdminAction)
        post_delete.connect(invalidate_admin_cache, sender=AdminAction)
        post_save.connect(invalidate_admin_cache, sender=AdminLog)
        post_delete.connect(invalidate_admin_cache, sender=AdminLog)
        post_save.connect(invalidate_admin_cache, sender=AdminPreference)
        post_delete.connect(invalidate_admin_cache, sender=AdminPreference)
        post_save.connect(invalidate_admin_cache, sender=SystemSetting)
        post_delete.connect(invalidate_admin_cache, sender=SystemSetting)
        post_save.connect(invalidate_admin_cache, sender=MaintenanceLog)
        post_delete.connect(invalidate_admin_cache, sender=MaintenanceLog)
        post_save.connect(invalidate_admin_cache, sender=Report)
        post_delete.connect(invalidate_admin_cache, sender=Report)
        post_save.connect(invalidate_admin_cache, sender=ReportSchedule)
        post_delete.connect(invalidate_admin_cache, sender=ReportSchedule)
        post_save.connect(invalidate_admin_cache, sender=AuditTrail)
        post_delete.connect(invalidate_admin_cache, sender=AuditTrail)
        post_save.connect(invalidate_admin_cache, sender=DashboardWidget)
        post_delete.connect(invalidate_admin_cache, sender=DashboardWidget)

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
            if PeriodicTask.objects.filter(name__startswith='admin_').exists():
                logger.info('Periodic tasks already configured.')
                return

            # Create schedules
            interval_15min, _ = IntervalSchedule.objects.get_or_create(
                every=15,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'admin_15min'}
            )

            interval_1hour, _ = IntervalSchedule.objects.get_or_create(
                every=60,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'admin_1hour'}
            )

            interval_6hour, _ = IntervalSchedule.objects.get_or_create(
                every=360,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'admin_6hour'}
            )

            crontab_daily_6am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=6,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'admin_daily_6am'}
            )

            crontab_daily_7am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=7,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'admin_daily_7am'}
            )

            crontab_daily_8am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=8,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'admin_daily_8am'}
            )

            crontab_daily_9am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=9,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'admin_daily_9am'}
            )

            crontab_daily_1am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=1,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'admin_daily_1am'}
            )

            crontab_daily_2am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=2,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'admin_daily_2am'}
            )

            crontab_weekly_monday_7am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=7,
                day_of_week=1,  # Monday
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'admin_weekly_monday_7am'}
            )

            crontab_monthly_1st_7am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=7,
                day_of_week='*',
                day_of_month=1,
                month_of_year='*',
                defaults={'name': 'admin_monthly_1st_7am'}
            )

            crontab_weekly_sunday_2am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=2,
                day_of_week=0,  # Sunday
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'admin_weekly_sunday_2am'}
            )

            crontab_weekly_sunday_3am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=3,
                day_of_week=0,  # Sunday
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'admin_weekly_sunday_3am'}
            )

            crontab_weekly_sunday_4am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=4,
                day_of_week=0,  # Sunday
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'admin_weekly_sunday_4am'}
            )

            # Define tasks
            tasks = [
                {
                    'name': 'admin_generate_daily_reports',
                    'task': 'apps.admin_panel.tasks.generate_daily_reports',
                    'schedule': crontab_daily_6am,
                    'description': 'Generate daily reports at 6:00 AM'
                },
                {
                    'name': 'admin_generate_weekly_reports',
                    'task': 'apps.admin_panel.tasks.generate_weekly_reports',
                    'schedule': crontab_weekly_monday_7am,
                    'description': 'Generate weekly reports on Monday at 7:00 AM'
                },
                {
                    'name': 'admin_generate_monthly_reports',
                    'task': 'apps.admin_panel.tasks.generate_monthly_reports',
                    'schedule': crontab_monthly_1st_7am,
                    'description': 'Generate monthly reports on the 1st at 7:00 AM'
                },
                {
                    'name': 'admin_send_alerts',
                    'task': 'apps.admin_panel.tasks.send_admin_alerts',
                    'schedule': interval_6hour,
                    'description': 'Send admin alerts every 6 hours'
                },
                {
                    'name': 'admin_cleanup_logs',
                    'task': 'apps.admin_panel.tasks.cleanup_admin_logs',
                    'schedule': crontab_weekly_sunday_2am,
                    'description': 'Clean up admin logs on Sunday at 2:00 AM'
                },
                {
                    'name': 'admin_sync_settings',
                    'task': 'apps.admin_panel.tasks.sync_system_settings',
                    'schedule': interval_6hour,
                    'description': 'Sync system settings every 6 hours'
                },
                {
                    'name': 'admin_check_health',
                    'task': 'apps.admin_panel.tasks.check_system_health',
                    'schedule': interval_1hour,
                    'description': 'Check system health every hour'
                },
                {
                    'name': 'admin_process_scheduled_reports',
                    'task': 'apps.admin_panel.tasks.process_scheduled_reports',
                    'schedule': interval_15min,
                    'description': 'Process scheduled reports every 15 minutes'
                },
                {
                    'name': 'admin_dashboard_digest',
                    'task': 'apps.admin_panel.tasks.send_dashboard_digest',
                    'schedule': crontab_daily_8am,
                    'description': 'Send dashboard digest at 8:00 AM'
                },
                {
                    'name': 'admin_backup_data',
                    'task': 'apps.admin_panel.tasks.backup_admin_data',
                    'schedule': crontab_daily_1am,
                    'description': 'Backup admin data at 1:00 AM'
                },
                {
                    'name': 'admin_clear_cache',
                    'task': 'apps.admin_panel.tasks.clear_system_cache',
                    'schedule': crontab_weekly_sunday_4am,
                    'description': 'Clear system cache on Sunday at 4:00 AM'
                },
                {
                    'name': 'admin_run_maintenance',
                    'task': 'apps.admin_panel.tasks.run_maintenance_tasks',
                    'schedule': crontab_weekly_sunday_3am,
                    'description': 'Run maintenance tasks on Sunday at 3:00 AM'
                },
                {
                    'name': 'admin_user_activity_summary',
                    'task': 'apps.admin_panel.tasks.send_user_activity_summary',
                    'schedule': crontab_daily_9am,
                    'description': 'Send user activity summary at 9:00 AM'
                },
                {
                    'name': 'admin_payment_reconciliation',
                    'task': 'apps.admin_panel.tasks.admin_payment_reconciliation',
                    'schedule': crontab_daily_2am,
                    'description': 'Perform payment reconciliation at 2:00 AM'
                },
                {
                    'name': 'admin_monitor_groups',
                    'task': 'apps.admin_panel.tasks.monitor_group_status',
                    'schedule': interval_6hour,
                    'description': 'Monitor group status every 6 hours'
                },
                {
                    'name': 'admin_monitor_overdue_contributions',
                    'task': 'apps.admin_panel.tasks.monitor_overdue_contributions',
                    'schedule': interval_6hour,
                    'description': 'Monitor overdue contributions every 6 hours'
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
        logger.info('Performing database checks for admin panel app...')

        try:
            from django.db import connection
            from django.db.migrations.executor import MigrationExecutor

            # Check if migrations are applied
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            if plan:
                logger.warning('There are pending migrations for the admin panel app.')
            else:
                logger.info('All admin panel migrations are applied.')

            # Check required database tables exist
            from .models import SystemSetting
            table_name = SystemSetting._meta.db_table
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

            # Check admin_actions table
            from .models import AdminAction
            action_table = AdminAction._meta.db_table
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name=%s)",
                    [action_table]
                )
                exists = cursor.fetchone()[0]
                if exists:
                    logger.info(f'Table "{action_table}" exists.')
                else:
                    logger.warning(f'Table "{action_table}" does not exist; run migrations.')

        except Exception as e:
            logger.error(f'Database checks failed: {e}')

    # ==========================================================================
    # POST_MIGRATE SIGNAL TO CREATE DEFAULT SETTINGS
    # ==========================================================================

    @classmethod
    def create_default_settings(cls, sender, **kwargs):
        """
        Create default system settings and admin preferences after migrations.
        """
        try:
            from .models import SystemSetting

            # Create default system settings
            defaults = [
                ('site_name', 'Digital Ekub Platform', 'Site name', 'general', True),
                ('support_email', 'support@ekub-platform.com', 'Support email address', 'general', True),
                ('maintenance_mode_enabled', False, 'Enable maintenance mode', 'system', False),
                ('report_auto_generate_enabled', True, 'Enable auto-generation of reports', 'reports', False),
                ('max_users_per_group', 100, 'Maximum users per group', 'groups', False),
                ('default_contribution_amount', 100.00, 'Default contribution amount', 'contributions', False),
                ('platform_fee_percentage', 2.5, 'Platform fee percentage', 'payments', False),
            ]

            for key, value, description, category, is_public in defaults:
                SystemSetting.objects.get_or_create(
                    key=key,
                    defaults={
                        'value': value,
                        'description': description,
                        'category': category,
                        'is_public': is_public,
                        'editable': True,
                    }
                )

            logger.info('Default system settings created.')

        except Exception as e:
            logger.error(f'Error creating default system settings: {str(e)}')

    # ==========================================================================
    # UTILITY METHODS
    # ==========================================================================

    def get_version(self) -> str:
        """Return the version of the admin panel app."""
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
        logger.debug('Admin panel system checks registered.')

        # Connect post_migrate signal to create default settings
        post_migrate.connect(cls.create_default_settings, sender=cls)


# ============================================================================
# STATIC INITIALIZATION
# ============================================================================

# Perform static initialization when this module is imported
AdminPanelConfig.initialize_static()

# ============================================================================
# LOGGING FOR APP STARTUP
# ============================================================================

logger.info('Admin panel app module loaded.')

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['AdminPanelConfig']