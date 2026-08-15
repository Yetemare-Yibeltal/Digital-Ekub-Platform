"""
App configuration for the audit app.

This module defines the Django AppConfig for the audit app,
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


class AuditConfig(AppConfig):
    """
    Configuration for the audit app.

    This class handles app initialization, signal registration,
    system checks, environment validation, and startup tasks.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.audit'
    label = 'audit'
    verbose_name = _('Audit')

    # Internal state for initialization tracking
    _initialized = False
    _checks_run = False
    _signals_registered = False
    _admin_registered = False
    _tasks_registered = False
    _middleware_registered = False

    def ready(self):
        """
        Called when the app is ready.

        This method performs the following initialization tasks:
        1. Imports and registers signals
        2. Imports and registers admin classes
        3. Imports and registers middleware
        4. Performs system checks
        5. Validates environment settings
        6. Initializes default configuration
        7. Sets up cache invalidation hooks
        8. Registers custom management commands
        9. Sets up periodic tasks (if Celery configured)
        10. Performs database checks
        11. Logs successful initialization
        """
        if self._initialized:
            logger.debug('Audit app already initialized.')
            return

        logger.info('Initializing audit app...')

        # ====================================================================
        # 1. IMPORT AND REGISTER SIGNALS
        # ====================================================================
        self._register_signals()

        # ====================================================================
        # 2. IMPORT AND REGISTER ADMIN CLASSES
        # ====================================================================
        self._register_admin()

        # ====================================================================
        # 3. IMPORT AND REGISTER MIDDLEWARE
        # ====================================================================
        self._register_middleware()

        # ====================================================================
        # 4. PERFORM SYSTEM CHECKS
        # ====================================================================
        self._perform_system_checks()

        # ====================================================================
        # 5. VALIDATE ENVIRONMENT SETTINGS
        # ====================================================================
        self._validate_environment()

        # ====================================================================
        # 6. INITIALIZE DEFAULT CONFIGURATION
        # ====================================================================
        self._initialize_defaults()

        # ====================================================================
        # 7. SET UP CACHE INVALIDATION HOOKS
        # ====================================================================
        self._setup_cache_hooks()

        # ====================================================================
        # 8. REGISTER CUSTOM MANAGEMENT COMMANDS
        # ====================================================================
        self._register_management_commands()

        # ====================================================================
        # 9. SET UP PERIODIC TASKS (if Celery configured)
        # ====================================================================
        self._setup_periodic_tasks()

        # ====================================================================
        # 10. PERFORM DATABASE CHECKS
        # ====================================================================
        self._perform_database_checks()

        # ====================================================================
        # 11. LOG SUCCESSFUL INITIALIZATION
        # ====================================================================
        self._initialized = True
        logger.info(f'Audit app v{self.get_version()} initialized successfully.')

    # ==========================================================================
    # REGISTRATION METHODS
    # ==========================================================================

    def _register_signals(self):
        """Import signals module to register signal handlers."""
        if self._signals_registered:
            return

        try:
            import apps.audit.signals
            # Force registration of signal handlers
            from apps.audit import signals as _  # noqa
            self._signals_registered = True
            logger.info('Audit signals registered successfully.')
        except ImportError as e:
            logger.error(f'Failed to import audit signals: {e}')
        except Exception as e:
            logger.error(f'Unexpected error registering signals: {e}')

    def _register_admin(self):
        """Import admin module to register admin classes."""
        if self._admin_registered:
            return

        try:
            import apps.audit.admin
            # Admin classes are automatically registered via @admin.register
            self._admin_registered = True
            logger.info('Audit admin registered successfully.')
        except ImportError as e:
            logger.error(f'Failed to import audit admin: {e}')
        except Exception as e:
            logger.error(f'Unexpected error registering admin: {e}')

    def _register_middleware(self):
        """Register middleware classes."""
        if self._middleware_registered:
            return

        try:
            from .middleware import (
                RequestIDMiddleware,
                RequestLoggingMiddleware,
                ResponseLoggingMiddleware,
                PerformanceMiddleware,
                UserActivityMiddleware,
                SecurityMiddleware,
                AuditContextMiddleware,
                RequestTimeoutMiddleware,
                BodyLoggingMiddleware,
                ErrorLoggingMiddleware,
                UserSessionAuditMiddleware,
            )
            self._middleware_registered = True
            logger.info('Audit middleware registered successfully.')
        except ImportError as e:
            logger.error(f'Failed to import audit middleware: {e}')
        except Exception as e:
            logger.error(f'Unexpected error registering middleware: {e}')

    def _register_management_commands(self):
        """Register custom management commands (if any)."""
        if self._tasks_registered:
            return

        try:
            import apps.audit.management  # noqa
            self._tasks_registered = True
            logger.info('Audit management commands registered.')
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
            checks_to_run = ['apps.audit']
            errors = run_checks(checks_to_run)
            if errors:
                for error in errors:
                    logger.error(f'System check error: {error}')
            else:
                logger.info('Audit system checks passed.')
            self._checks_run = True
        except Exception as e:
            logger.error(f'Error running system checks: {e}')

    @classmethod
    def register_system_checks(cls):
        """
        Register custom system checks for the audit app.
        These are executed during Django's check framework.
        """
        def check_audit_settings(app_configs, **kwargs):
            errors = []

            # Check required settings
            required_settings = [
                'AUDIT_EXCLUDED_PATHS',
                'AUDIT_MAX_REQUEST_BODY_LOG',
                'AUDIT_MAX_RESPONSE_BODY_LOG',
                'AUDIT_PERFORMANCE_THRESHOLDS',
                'AUDIT_SECURITY_PATTERNS',
                'AUDIT_REQUEST_TIMEOUT',
                'AUDIT_BACKUP_DIR',
            ]
            for setting in required_settings:
                if not hasattr(settings, setting):
                    errors.append(
                        Error(
                            f'Missing required setting: {setting}',
                            hint=f'Define {setting} in your settings file.',
                            obj='audit.apps.AuditConfig',
                            id='audit.E001',
                        )
                    )

            # Check backup directory
            backup_dir = getattr(settings, 'AUDIT_BACKUP_DIR', '')
            if backup_dir and not os.path.exists(backup_dir):
                try:
                    os.makedirs(backup_dir, exist_ok=True)
                except Exception as e:
                    errors.append(
                        Warning(
                            f'Cannot create backup directory: {backup_dir}',
                            hint=f'Ensure the directory exists and is writable. Error: {str(e)}',
                            obj='audit.apps.AuditConfig',
                            id='audit.W001',
                        )
                    )

            # Check performance thresholds
            thresholds = getattr(settings, 'AUDIT_PERFORMANCE_THRESHOLDS', {})
            if thresholds.get('warning', 0) <= 0 or thresholds.get('critical', 0) <= 0:
                errors.append(
                    Warning(
                        'AUDIT_PERFORMANCE_THRESHOLDS should have positive values.',
                        hint='Set warning and critical thresholds in milliseconds.',
                        obj='audit.apps.AuditConfig',
                        id='audit.W002',
                    )
                )

            # Check request timeout
            timeout = getattr(settings, 'AUDIT_REQUEST_TIMEOUT', 0)
            if timeout <= 0:
                errors.append(
                    Warning(
                        'AUDIT_REQUEST_TIMEOUT should be a positive value in seconds.',
                        hint='Set a reasonable timeout value (e.g., 30).',
                        obj='audit.apps.AuditConfig',
                        id='audit.W003',
                    )
                )

            return errors

        # Register the check
        register(Tags.models)(check_audit_settings)

    # ==========================================================================
    # ENVIRONMENT VALIDATION
    # ==========================================================================

    def _validate_environment(self):
        """Validate environment variables and settings."""
        logger.info('Validating audit environment...')

        # ====================================================================
        # 1. Check required environment variables
        # ====================================================================
        required_env = [
            'SECRET_KEY',
        ]
        missing = []
        for var in required_env:
            if not os.environ.get(var):
                missing.append(var)

        if missing:
            logger.warning(
                f'Missing audit environment variables: {", ".join(missing)}. '
                'Some audit features may not work.'
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
        backup_dir = getattr(settings, 'AUDIT_BACKUP_DIR', '/tmp/audit_backups')
        if not os.path.exists(backup_dir):
            try:
                os.makedirs(backup_dir, exist_ok=True)
                logger.info(f'Created backup directory: {backup_dir}')
            except Exception as e:
                logger.error(f'Failed to create backup directory {backup_dir}: {str(e)}')

        # ====================================================================
        # 5. Check email configuration for alerts
        # ====================================================================
        if not settings.DEFAULT_FROM_EMAIL:
            logger.warning('DEFAULT_FROM_EMAIL is not set. Audit alerts may not be sent.')

        # ====================================================================
        # 6. Validate security patterns
        # ====================================================================
        security_patterns = getattr(settings, 'AUDIT_SECURITY_PATTERNS', {})
        if not security_patterns:
            logger.warning('AUDIT_SECURITY_PATTERNS is empty. Security event detection may not work.')

        logger.info('Audit environment validation completed.')

    # ==========================================================================
    # DEFAULT INITIALIZATION
    # ==========================================================================

    def _initialize_defaults(self):
        """Initialize default configuration values."""
        logger.info('Initializing audit defaults...')

        # Set default values for settings if not defined
        defaults = {
            'AUDIT_EXCLUDED_PATHS': [
                '/admin/',
                '/static/',
                '/media/',
                '/api/v1/auth/token/',
                '/api/v1/auth/refresh/',
                '/health/',
                '/ping/',
                '/ready/',
                '/favicon.ico',
                '/robots.txt',
            ],
            'AUDIT_MAX_REQUEST_BODY_LOG': 1024,
            'AUDIT_MAX_RESPONSE_BODY_LOG': 1024,
            'AUDIT_PERFORMANCE_THRESHOLDS': {
                'warning': 1000,
                'critical': 5000,
            },
            'AUDIT_SECURITY_PATTERNS': {
                'login_attempt': {'path': r'/api/v1/auth/login/', 'method': 'POST', 'description': 'Login Attempt'},
                'failed_login': {'path': r'/api/v1/auth/login/', 'method': 'POST', 'status_code': 401, 'description': 'Failed Login Attempt'},
                'password_change': {'path': r'/api/v1/auth/change-password/', 'method': 'POST', 'description': 'Password Change'},
                'registration': {'path': r'/api/v1/auth/register/', 'method': 'POST', 'description': 'User Registration'},
            },
            'AUDIT_REQUEST_TIMEOUT': 30,
            'AUDIT_BACKUP_DIR': '/tmp/audit_backups',
            'AUDIT_RETENTION_DAYS': 365,
            'AUDIT_EVENT_BATCH_SIZE': 100,
            'AUDIT_REPORT_AUTO_GENERATE': True,
            'AUDIT_ALERT_EMAIL_RECIPIENTS': [],
            'AUDIT_SAMPLE_RATE': 0.1,
            'AUDIT_SUSPICIOUS_USER_AGENTS': [
                'curl', 'wget', 'python-requests', 'java', 'perl', 'ruby',
                'go-http-client', 'nikto', 'sqlmap', 'nmap', 'nessus',
                'openvas', 'burp', 'zap', 'w3af', 'acunetix',
            ],
            'AUDIT_SQL_INJECTION_PATTERNS': [
                r'(\%27)|(\')|(\-\-)|(\%23)|(#)',
                r'((\%3D)|(=))[^\n]*((\%27)|(\')|(\-\-)|(\%3B)|(;))',
            ],
            'AUDIT_XSS_PATTERNS': [
                r'<script.*?>.*?</script>',
                r'javascript:',
                r'onerror=',
                r'onload=',
            ],
        }

        for key, default_value in defaults.items():
            if not hasattr(settings, key):
                setattr(settings, key, default_value)
                logger.debug(f'Set default {key} = {default_value}')

        logger.info('Audit defaults initialized.')

    # ==========================================================================
    # CACHE INVALIDATION HOOKS
    # ==========================================================================

    def _setup_cache_hooks(self):
        """Set up cache invalidation hooks for audit-related models."""
        logger.info('Setting up cache invalidation hooks...')

        from django.core.cache import cache
        from django.db.models.signals import post_save, post_delete

        # Define a generic cache invalidation receiver
        def invalidate_audit_cache(sender, instance, **kwargs):
            """Invalidate cache for audit models."""
            cache_keys = []
            model_name = sender._meta.model_name

            if model_name == 'auditlog':
                cache_keys.append('audit_logs_recent')
                cache_keys.append('audit_statistics')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'audit_log_{instance.id}')
            elif model_name == 'auditevent':
                if hasattr(instance, 'id'):
                    cache_keys.append(f'audit_event_{instance.id}')
            elif model_name == 'auditrule':
                cache_keys.append('audit_rules_active')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'audit_rule_{instance.id}')
            elif model_name == 'auditalert':
                if hasattr(instance, 'id'):
                    cache_keys.append(f'audit_alert_{instance.id}')
            elif model_name == 'auditreport':
                cache_keys.append('audit_reports_recent')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'audit_report_{instance.id}')
            elif model_name == 'auditretentionpolicy':
                cache_keys.append('audit_retention_policies_active')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'audit_retention_policy_{instance.id}')
            elif model_name == 'securityevent':
                cache_keys.append('security_events_recent')
                cache_keys.append('security_statistics')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'security_event_{instance.id}')
            elif model_name == 'useractivity':
                if hasattr(instance, 'id'):
                    cache_keys.append(f'user_activity_{instance.id}')
            elif model_name == 'systemhealth':
                cache_keys.append('system_health_latest')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'system_health_{instance.id}')
            elif model_name == 'performancemetric':
                cache_keys.append('performance_metrics_latest')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'performance_metric_{instance.id}')
            elif model_name == 'anomalydetection':
                cache_keys.append('anomaly_detections_open')
                if hasattr(instance, 'id'):
                    cache_keys.append(f'anomaly_detection_{instance.id}')

            for key in cache_keys:
                cache.delete(key)

            if cache_keys:
                logger.debug(f'Invalidated {len(cache_keys)} cache keys for {model_name} {instance.id}')

        # Connect signals for all audit models
        from .models import (
            AuditLog, AuditEvent, AuditRule, AuditAlert, AuditReport,
            AuditRetentionPolicy, SecurityEvent, UserActivity, SystemHealth,
            PerformanceMetric, AnomalyDetection
        )

        post_save.connect(invalidate_audit_cache, sender=AuditLog)
        post_delete.connect(invalidate_audit_cache, sender=AuditLog)
        post_save.connect(invalidate_audit_cache, sender=AuditEvent)
        post_delete.connect(invalidate_audit_cache, sender=AuditEvent)
        post_save.connect(invalidate_audit_cache, sender=AuditRule)
        post_delete.connect(invalidate_audit_cache, sender=AuditRule)
        post_save.connect(invalidate_audit_cache, sender=AuditAlert)
        post_delete.connect(invalidate_audit_cache, sender=AuditAlert)
        post_save.connect(invalidate_audit_cache, sender=AuditReport)
        post_delete.connect(invalidate_audit_cache, sender=AuditReport)
        post_save.connect(invalidate_audit_cache, sender=AuditRetentionPolicy)
        post_delete.connect(invalidate_audit_cache, sender=AuditRetentionPolicy)
        post_save.connect(invalidate_audit_cache, sender=SecurityEvent)
        post_delete.connect(invalidate_audit_cache, sender=SecurityEvent)
        post_save.connect(invalidate_audit_cache, sender=UserActivity)
        post_delete.connect(invalidate_audit_cache, sender=UserActivity)
        post_save.connect(invalidate_audit_cache, sender=SystemHealth)
        post_delete.connect(invalidate_audit_cache, sender=SystemHealth)
        post_save.connect(invalidate_audit_cache, sender=PerformanceMetric)
        post_delete.connect(invalidate_audit_cache, sender=PerformanceMetric)
        post_save.connect(invalidate_audit_cache, sender=AnomalyDetection)
        post_delete.connect(invalidate_audit_cache, sender=AnomalyDetection)

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
            if PeriodicTask.objects.filter(name__startswith='audit_').exists():
                logger.info('Periodic tasks already configured.')
                return

            # Create schedules
            interval_1min, _ = IntervalSchedule.objects.get_or_create(
                every=1,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'audit_1min'}
            )

            interval_5min, _ = IntervalSchedule.objects.get_or_create(
                every=5,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'audit_5min'}
            )

            interval_15min, _ = IntervalSchedule.objects.get_or_create(
                every=15,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'audit_15min'}
            )

            interval_1hour, _ = IntervalSchedule.objects.get_or_create(
                every=60,
                period=IntervalSchedule.MINUTES,
                defaults={'name': 'audit_1hour'}
            )

            crontab_daily_7am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=7,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'audit_daily_7am'}
            )

            crontab_daily_8am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=8,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'audit_daily_8am'}
            )

            crontab_daily_1am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=1,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'audit_daily_1am'}
            )

            crontab_daily_2am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=2,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'audit_daily_2am'}
            )

            crontab_daily_3am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=3,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'audit_daily_3am'}
            )

            crontab_daily_4am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=4,
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'audit_daily_4am'}
            )

            crontab_weekly_monday_7am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=7,
                day_of_week=1,  # Monday
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'audit_weekly_monday_7am'}
            )

            crontab_weekly_sunday_3am, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour=3,
                day_of_week=0,  # Sunday
                day_of_month='*',
                month_of_year='*',
                defaults={'name': 'audit_weekly_sunday_3am'}
            )

            # Define tasks
            tasks = [
                {
                    'name': 'audit_process_events',
                    'task': 'apps.audit.tasks.process_audit_events',
                    'schedule': interval_1min,
                    'description': 'Process pending audit events every minute'
                },
                {
                    'name': 'audit_process_rules',
                    'task': 'apps.audit.tasks.process_audit_rules_task',
                    'schedule': interval_5min,
                    'description': 'Process audit rules every 5 minutes'
                },
                {
                    'name': 'audit_check_health',
                    'task': 'apps.audit.tasks.check_system_health_task',
                    'schedule': interval_5min,
                    'description': 'Check system health every 5 minutes'
                },
                {
                    'name': 'audit_collect_metrics',
                    'task': 'apps.audit.tasks.collect_performance_metrics',
                    'schedule': interval_5min,
                    'description': 'Collect performance metrics every 5 minutes'
                },
                {
                    'name': 'audit_detect_anomalies',
                    'task': 'apps.audit.tasks.detect_anomalies_task',
                    'schedule': interval_15min,
                    'description': 'Detect anomalies every 15 minutes'
                },
                {
                    'name': 'audit_aggregate_stats',
                    'task': 'apps.audit.tasks.aggregate_audit_statistics',
                    'schedule': interval_1hour,
                    'description': 'Aggregate audit statistics every hour'
                },
                {
                    'name': 'audit_sync_config',
                    'task': 'apps.audit.tasks.sync_audit_configuration',
                    'schedule': interval_1hour,
                    'description': 'Sync audit configuration every hour'
                },
                {
                    'name': 'audit_daily_reports',
                    'task': 'apps.audit.tasks.generate_daily_audit_reports',
                    'schedule': crontab_daily_7am,
                    'description': 'Generate daily audit reports at 7:00 AM'
                },
                {
                    'name': 'audit_weekly_reports',
                    'task': 'apps.audit.tasks.generate_weekly_audit_reports',
                    'schedule': crontab_weekly_monday_7am,
                    'description': 'Generate weekly audit reports on Monday at 7:00 AM'
                },
                {
                    'name': 'audit_enforce_retention',
                    'task': 'apps.audit.tasks.enforce_retention_policies',
                    'schedule': crontab_daily_2am,
                    'description': 'Enforce retention policies daily at 2:00 AM'
                },
                {
                    'name': 'audit_cleanup_old_data',
                    'task': 'apps.audit.tasks.cleanup_old_audit_data',
                    'schedule': crontab_daily_3am,
                    'description': 'Cleanup old audit data daily at 3:00 AM'
                },
                {
                    'name': 'audit_backup_data',
                    'task': 'apps.audit.tasks.backup_audit_data',
                    'schedule': crontab_daily_1am,
                    'description': 'Backup audit data daily at 1:00 AM'
                },
                {
                    'name': 'audit_health_alert',
                    'task': 'apps.audit.tasks.send_health_alert',
                    'schedule': interval_15min,
                    'description': 'Send health alerts every 15 minutes'
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
        logger.info('Performing database checks for audit app...')

        try:
            from django.db import connection
            from django.db.migrations.executor import MigrationExecutor

            # Check if migrations are applied
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            if plan:
                logger.warning('There are pending migrations for the audit app.')
            else:
                logger.info('All audit migrations are applied.')

            # Check required database tables exist
            from .models import AuditLog
            table_name = AuditLog._meta.db_table
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

            # Check audit_events table
            from .models import AuditEvent
            event_table = AuditEvent._meta.db_table
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name=%s)",
                    [event_table]
                )
                exists = cursor.fetchone()[0]
                if exists:
                    logger.info(f'Table "{event_table}" exists.')
                else:
                    logger.warning(f'Table "{event_table}" does not exist; run migrations.')

            # Check security_events table
            from .models import SecurityEvent
            security_table = SecurityEvent._meta.db_table
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name=%s)",
                    [security_table]
                )
                exists = cursor.fetchone()[0]
                if exists:
                    logger.info(f'Table "{security_table}" exists.')
                else:
                    logger.warning(f'Table "{security_table}" does not exist; run migrations.')

            # Check performance_metrics table
            from .models import PerformanceMetric
            metric_table = PerformanceMetric._meta.db_table
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name=%s)",
                    [metric_table]
                )
                exists = cursor.fetchone()[0]
                if exists:
                    logger.info(f'Table "{metric_table}" exists.')
                else:
                    logger.warning(f'Table "{metric_table}" does not exist; run migrations.')

        except Exception as e:
            logger.error(f'Database checks failed: {e}')

    # ==========================================================================
    # POST_MIGRATE SIGNAL TO CREATE DEFAULT RULES AND POLICIES
    # ==========================================================================

    @classmethod
    def create_default_audit_data(cls, sender, **kwargs):
        """
        Create default audit rules, retention policies, and system settings after migrations.
        """
        try:
            from .models import AuditRule, AuditRetentionPolicy, SystemHealth

            # Create default retention policies
            policies = [
                ('AUDIT_LOG', 365, 'Retain audit logs for 1 year'),
                ('SECURITY_EVENT', 180, 'Retain security events for 6 months'),
                ('USER_ACTIVITY', 90, 'Retain user activities for 3 months'),
                ('SYSTEM_HEALTH', 30, 'Retain system health records for 30 days'),
                ('PERFORMANCE_METRIC', 90, 'Retain performance metrics for 90 days'),
                ('ANOMALY_DETECTION', 180, 'Retain anomaly detections for 6 months'),
            ]

            for resource_type, days, description in policies:
                AuditRetentionPolicy.objects.get_or_create(
                    resource_type=resource_type,
                    defaults={
                        'retention_days': days,
                        'description': description,
                        'is_active': True,
                    }
                )

            logger.info('Default retention policies created.')

            # Create default audit rules
            rules = [
                {
                    'name': 'Critical Security Events',
                    'description': 'Alert on critical security events',
                    'condition': {'severity': 'critical', 'action': 'LOGIN_FAILED'},
                    'action': 'alert',
                    'severity': 'critical',
                },
                {
                    'name': 'Unauthorized Access Attempts',
                    'description': 'Alert on unauthorized access attempts',
                    'condition': {'severity': 'warning', 'action': 'UNAUTHORIZED_ACCESS'},
                    'action': 'alert',
                    'severity': 'warning',
                },
                {
                    'name': 'Failed Logins',
                    'description': 'Monitor failed login attempts',
                    'condition': {'severity': 'warning', 'action': 'LOGIN_FAILED'},
                    'action': 'log',
                    'severity': 'warning',
                },
                {
                    'name': 'SQL Injection Attempts',
                    'description': 'Alert on SQL injection attempts',
                    'condition': {'severity': 'critical', 'action': 'SQL_INJECTION_ATTEMPT'},
                    'action': 'alert',
                    'severity': 'critical',
                },
                {
                    'name': 'Admin Actions',
                    'description': 'Monitor all admin actions',
                    'condition': {'resource': 'ADMIN', 'action': 'CREATE'},
                    'action': 'log',
                    'severity': 'info',
                },
            ]

            for rule_data in rules:
                AuditRule.objects.get_or_create(
                    name=rule_data['name'],
                    defaults={
                        'description': rule_data['description'],
                        'condition': rule_data['condition'],
                        'action': rule_data['action'],
                        'severity': rule_data['severity'],
                        'is_active': True,
                    }
                )

            logger.info('Default audit rules created.')

            # Create initial system health record
            SystemHealth.objects.get_or_create(
                component='system',
                defaults={
                    'status': 'ok',
                    'message': 'System initialized successfully',
                    'details': {'initialized_at': timezone.now().isoformat()},
                    'checked_at': timezone.now(),
                }
            )

            logger.info('Initial system health record created.')

        except Exception as e:
            logger.error(f'Error creating default audit data: {str(e)}')

    # ==========================================================================
    # UTILITY METHODS
    # ==========================================================================

    def get_version(self) -> str:
        """Return the version of the audit app."""
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
        logger.debug('Audit system checks registered.')

        # Connect post_migrate signal to create default data
        post_migrate.connect(cls.create_default_audit_data, sender=cls)


# ============================================================================
# STATIC INITIALIZATION
# ============================================================================

# Perform static initialization when this module is imported
AuditConfig.initialize_static()

# ============================================================================
# LOGGING FOR APP STARTUP
# ============================================================================

logger.info('Audit app module loaded.')

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['AuditConfig']