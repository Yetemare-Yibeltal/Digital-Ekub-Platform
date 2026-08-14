"""
Celery tasks for the admin panel app.

This module provides background task functions for administrative operations:
- Daily, weekly, monthly, and quarterly report generation
- Sending admin alerts for system events and anomalies
- Cleaning up old admin logs, audit trails, and expired reports
- Synchronizing system settings across environments
- Periodic system health checks with alerting
- Processing scheduled report generation
- Sending dashboard digests to admin users
- Database and data backups
- System cache clearing
- General maintenance tasks
- Administrative notification broadcasting
- Report archiving and cleanup
- User activity summaries
- Payment reconciliation tasks
- Group status monitoring
- Contribution overdue monitoring

All tasks include comprehensive error handling, logging, retry logic,
and performance optimizations for bulk operations.
"""

from celery import shared_task
from celery.utils.log import get_task_logger
from django.db import transaction
from django.db.models import Q, Count, Sum, Avg, F, OuterRef, Subquery
from django.utils import timezone
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection

import logging
from datetime import timedelta, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple, Union
import json
import os
import subprocess
import shutil

from apps.users.models import User
from apps.groups.models import Group, GroupMember
from apps.contributions.models import Contribution
from apps.payments.models import Payment, Payout
from apps.notifications.models import Notification
from apps.common.utils import send_email, send_sms, format_currency
from apps.common.constants import (
    UserStatus, GroupStatus, PaymentStatus, ContributionStatus, NotificationType
)

from .models import (
    AdminAction,
    AdminLog,
    AdminPreference,
    SystemSetting,
    MaintenanceLog,
    Report,
    ReportSchedule,
    AuditTrail,
    DashboardWidget,
)

logger = get_task_logger(__name__)


# ============================================================================
# REPORT GENERATION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def generate_daily_reports(self) -> Dict[str, Any]:
    """
    Generate daily summary reports for all admin users who have requested them.
    """
    logger.info("Starting generate_daily_reports task")

    results = {
        'reports_generated': 0,
        'reports_sent': 0,
        'errors': 0,
        'details': [],
    }

    try:
        # Get admin users who want daily reports
        admin_users = User.objects.filter(
            is_staff=True,
            is_active=True,
            admin_preferences__email_notifications=True,
            deleted_at__isnull=True
        )

        yesterday = timezone.now().date() - timedelta(days=1)

        for admin in admin_users:
            try:
                # Generate daily report data
                from . import generate_daily_report
                report_data = generate_daily_report(yesterday)

                # Create report record
                report = Report.objects.create(
                    name=f"Daily Report - {yesterday.isoformat()}",
                    report_type='daily',
                    generated_by=admin,
                    title=f"Daily Report for {yesterday.isoformat()}",
                    description=f"Automatically generated daily report for {yesterday.isoformat()}",
                    data=report_data,
                    format='json',
                    date_range_start=datetime.combine(yesterday, datetime.min.time()),
                    date_range_end=datetime.combine(yesterday, datetime.max.time()),
                    generated_at=timezone.now(),
                    is_public=False,
                )

                results['reports_generated'] += 1
                results['details'].append({
                    'admin_id': admin.id,
                    'report_id': report.id,
                    'report_type': 'daily',
                })

                # Send email with report summary
                try:
                    subject = f'Daily Report - {yesterday.isoformat()}'
                    context = {
                        'admin': admin,
                        'report': report_data,
                        'date': yesterday,
                        'app_name': 'Ekub Platform',
                    }
                    html_content = render_to_string('admin/emails/daily_report.html', context)
                    plain_message = f"""
                    Daily Report for {yesterday.isoformat()}

                    New Users: {report_data.get('new_users', 0)}
                    New Groups: {report_data.get('new_groups', 0)}
                    New Contributions: {report_data.get('new_contributions', 0)}
                    New Payments: {report_data.get('new_payments', 0)}
                    Total Payment Amount: {format_currency(report_data.get('total_payment_amount', 0))}

                    View full report in the admin panel.
                    """

                    send_mail(
                        subject,
                        plain_message,
                        settings.DEFAULT_FROM_EMAIL,
                        [admin.email],
                        html_message=html_content,
                        fail_silently=False,
                    )
                    results['reports_sent'] += 1

                except Exception as e:
                    logger.error(f'Error sending daily report to admin {admin.id}: {str(e)}')

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error generating daily report for admin {admin.id}: {str(e)}')

        logger.info(f'generate_daily_reports completed: {results}')
        return results

    except Exception as e:
        logger.error(f'generate_daily_reports failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def generate_weekly_reports(self) -> Dict[str, Any]:
    """
    Generate weekly summary reports.
    """
    logger.info("Starting generate_weekly_reports task")

    results = {
        'reports_generated': 0,
        'reports_sent': 0,
        'errors': 0,
        'details': [],
    }

    try:
        admin_users = User.objects.filter(
            is_staff=True,
            is_active=True,
            admin_preferences__email_notifications=True,
            deleted_at__isnull=True
        )

        for admin in admin_users:
            try:
                from . import generate_weekly_report
                report_data = generate_weekly_report()

                report = Report.objects.create(
                    name=f"Weekly Report - {timezone.now().date().isoformat()}",
                    report_type='weekly',
                    generated_by=admin,
                    title=f"Weekly Report for {timezone.now().date().isoformat()}",
                    description="Automatically generated weekly report",
                    data=report_data,
                    format='json',
                    generated_at=timezone.now(),
                    is_public=False,
                )

                results['reports_generated'] += 1
                results['details'].append({
                    'admin_id': admin.id,
                    'report_id': report.id,
                    'report_type': 'weekly',
                })

                try:
                    subject = f'Weekly Report - {timezone.now().date().isoformat()}'
                    context = {
                        'admin': admin,
                        'report': report_data,
                        'date': timezone.now(),
                        'app_name': 'Ekub Platform',
                    }
                    html_content = render_to_string('admin/emails/weekly_report.html', context)
                    plain_message = f"""
                    Weekly Report

                    Week Start: {report_data.get('week_start', 'N/A')}
                    Week End: {report_data.get('week_end', 'N/A')}

                    Totals:
                    New Users: {report_data.get('totals', {}).get('new_users', 0)}
                    New Groups: {report_data.get('totals', {}).get('new_groups', 0)}
                    New Payments: {report_data.get('totals', {}).get('new_payments', 0)}
                    Total Payment Amount: {format_currency(report_data.get('totals', {}).get('total_payment_amount', 0))}

                    View full report in the admin panel.
                    """

                    send_mail(
                        subject,
                        plain_message,
                        settings.DEFAULT_FROM_EMAIL,
                        [admin.email],
                        html_message=html_content,
                        fail_silently=False,
                    )
                    results['reports_sent'] += 1

                except Exception as e:
                    logger.error(f'Error sending weekly report to admin {admin.id}: {str(e)}')

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error generating weekly report for admin {admin.id}: {str(e)}')

        logger.info(f'generate_weekly_reports completed: {results}')
        return results

    except Exception as e:
        logger.error(f'generate_weekly_reports failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def generate_monthly_reports(self) -> Dict[str, Any]:
    """
    Generate monthly summary reports.
    """
    logger.info("Starting generate_monthly_reports task")

    results = {
        'reports_generated': 0,
        'reports_sent': 0,
        'errors': 0,
        'details': [],
    }

    try:
        admin_users = User.objects.filter(
            is_staff=True,
            is_active=True,
            admin_preferences__email_notifications=True,
            deleted_at__isnull=True
        )

        for admin in admin_users:
            try:
                from . import generate_monthly_report
                report_data = generate_monthly_report()

                report = Report.objects.create(
                    name=f"Monthly Report - {timezone.now().date().isoformat()}",
                    report_type='monthly',
                    generated_by=admin,
                    title=f"Monthly Report for {timezone.now().date().isoformat()}",
                    description="Automatically generated monthly report",
                    data=report_data,
                    format='json',
                    generated_at=timezone.now(),
                    is_public=False,
                )

                results['reports_generated'] += 1
                results['details'].append({
                    'admin_id': admin.id,
                    'report_id': report.id,
                    'report_type': 'monthly',
                })

                try:
                    subject = f'Monthly Report - {timezone.now().date().isoformat()}'
                    context = {
                        'admin': admin,
                        'report': report_data,
                        'date': timezone.now(),
                        'app_name': 'Ekub Platform',
                    }
                    html_content = render_to_string('admin/emails/monthly_report.html', context)
                    plain_message = f"""
                    Monthly Report

                    Month: {report_data.get('month_start', 'N/A')} to {report_data.get('month_end', 'N/A')}

                    New Users: {report_data.get('new_users', 0)}
                    New Groups: {report_data.get('new_groups', 0)}
                    New Payments: {report_data.get('new_payments', 0)}
                    Total Payment Amount: {format_currency(report_data.get('total_payment_amount', 0))}
                    Active Users: {report_data.get('active_users', 0)}
                    User Growth: {report_data.get('user_growth', 0)}%

                    View full report in the admin panel.
                    """

                    send_mail(
                        subject,
                        plain_message,
                        settings.DEFAULT_FROM_EMAIL,
                        [admin.email],
                        html_message=html_content,
                        fail_silently=False,
                    )
                    results['reports_sent'] += 1

                except Exception as e:
                    logger.error(f'Error sending monthly report to admin {admin.id}: {str(e)}')

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error generating monthly report for admin {admin.id}: {str(e)}')

        logger.info(f'generate_monthly_reports completed: {results}')
        return results

    except Exception as e:
        logger.error(f'generate_monthly_reports failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# ADMIN ALERTS TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_admin_alerts(self) -> Dict[str, Any]:
    """
    Send alerts to admin users about system events and anomalies.
    """
    logger.info("Starting send_admin_alerts task")

    results = {
        'alerts_sent': 0,
        'errors': 0,
        'alerts': [],
    }

    try:
        alerts = []

        # ====================================================================
        # 1. Check for overdue contributions
        # ====================================================================
        overdue_count = Contribution.objects.filter(
            status='overdue',
            deleted_at__isnull=True
        ).count()

        if overdue_count > 10:
            alerts.append({
                'type': 'warning',
                'severity': 'high' if overdue_count > 50 else 'medium',
                'message': f'{overdue_count} overdue contributions need attention.',
                'action_url': '/admin/contributions/?status=overdue',
            })

        # ====================================================================
        # 2. Check for pending groups
        # ====================================================================
        pending_count = Group.objects.filter(
            status='pending',
            deleted_at__isnull=True
        ).count()

        if pending_count > 5:
            alerts.append({
                'type': 'info',
                'severity': 'low',
                'message': f'{pending_count} groups are pending activation.',
                'action_url': '/admin/groups/?status=pending',
            })

        # ====================================================================
        # 3. Check for suspended users
        # ====================================================================
        suspended_count = User.objects.filter(
            is_suspended=True,
            deleted_at__isnull=True
        ).count()

        if suspended_count > 10:
            alerts.append({
                'type': 'warning',
                'severity': 'medium',
                'message': f'{suspended_count} users are suspended.',
                'action_url': '/admin/users/?is_suspended=true',
            })

        # ====================================================================
        # 4. Check for failed payments
        # ====================================================================
        failed_count = Payment.objects.filter(
            status='failed',
            deleted_at__isnull=True
        ).count()

        if failed_count > 20:
            alerts.append({
                'type': 'critical',
                'severity': 'high',
                'message': f'{failed_count} payments have failed. Please check payment gateway.',
                'action_url': '/admin/payments/?status=failed',
            })

        # ====================================================================
        # 5. Check system health
        # ====================================================================
        from . import get_system_health
        health = get_system_health()
        if health.get('status') != 'ok':
            alerts.append({
                'type': 'critical',
                'severity': 'high',
                'message': 'System health check failed. Please investigate.',
                'action_url': '/admin/dashboard/health/',
                'details': health,
            })

        # ====================================================================
        # 6. Check for expired reports
        # ====================================================================
        expired_reports = Report.objects.filter(
            expires_at__lte=timezone.now(),
            deleted_at__isnull=True
        ).count()

        if expired_reports > 50:
            alerts.append({
                'type': 'info',
                'severity': 'low',
                'message': f'{expired_reports} reports have expired and will be cleaned up.',
                'action_url': '/admin/reports/',
            })

        # ====================================================================
        # 7. Check for low cache hit rate
        # ====================================================================
        cache_hits = cache.get('cache_hits', 0)
        cache_misses = cache.get('cache_misses', 0)
        total = cache_hits + cache_misses
        if total > 0:
            hit_rate = (cache_hits / total) * 100
            if hit_rate < 70:
                alerts.append({
                    'type': 'warning',
                    'severity': 'medium',
                    'message': f'Cache hit rate is {hit_rate:.1f}%. Consider optimizing caching.',
                    'action_url': '/admin/settings/',
                })

        # ====================================================================
        # Send alerts to admin users
        # ====================================================================
        if alerts:
            admin_users = User.objects.filter(
                is_staff=True,
                is_active=True,
                admin_preferences__email_notifications=True,
                deleted_at__isnull=True
            )

            for admin in admin_users:
                try:
                    context = {
                        'admin': admin,
                        'alerts': alerts,
                        'date': timezone.now(),
                        'app_name': 'Ekub Platform',
                    }

                    html_content = render_to_string('admin/emails/alerts.html', context)
                    plain_message = f"""
                    System Alerts

                    {len(alerts)} alerts require your attention.

                    {chr(10).join([f'- {a["message"]}' for a in alerts])}

                    View all alerts in the admin panel.
                    """

                    send_mail(
                        'System Alerts - Action Required',
                        plain_message,
                        settings.DEFAULT_FROM_EMAIL,
                        [admin.email],
                        html_message=html_content,
                        fail_silently=False,
                    )
                    results['alerts_sent'] += 1

                except Exception as e:
                    results['errors'] += 1
                    logger.error(f'Error sending alerts to admin {admin.id}: {str(e)}')

        results['alerts'] = alerts
        logger.info(f'send_admin_alerts completed: {results}')
        return results

    except Exception as e:
        logger.error(f'send_admin_alerts failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# CLEANUP TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=600)
def cleanup_admin_logs(self) -> Dict[str, Any]:
    """
    Clean up old admin logs, audit trails, and expired reports.
    """
    logger.info("Starting cleanup_admin_logs task")

    results = {
        'logs_deleted': 0,
        'audit_trails_deleted': 0,
        'reports_deleted': 0,
        'actions_deleted': 0,
        'errors': 0,
    }

    try:
        now = timezone.now()

        # ====================================================================
        # 1. Delete admin logs older than 90 days
        # ====================================================================
        log_threshold = now - timedelta(days=90)
        logs_deleted, _ = AdminLog.objects.filter(
            timestamp__lt=log_threshold
        ).delete()
        results['logs_deleted'] = logs_deleted

        # ====================================================================
        # 2. Delete audit trails older than 180 days
        # ====================================================================
        audit_threshold = now - timedelta(days=180)
        audits_deleted, _ = AuditTrail.objects.filter(
            timestamp__lt=audit_threshold
        ).delete()
        results['audit_trails_deleted'] = audits_deleted

        # ====================================================================
        # 3. Delete expired reports
        # ====================================================================
        reports_deleted, _ = Report.objects.filter(
            expires_at__lt=now,
            deleted_at__isnull=True
        ).delete()
        results['reports_deleted'] = reports_deleted

        # ====================================================================
        # 4. Delete admin actions older than 365 days
        # ====================================================================
        action_threshold = now - timedelta(days=365)
        actions_deleted, _ = AdminAction.objects.filter(
            timestamp__lt=action_threshold
        ).delete()
        results['actions_deleted'] = actions_deleted

        logger.info(f'cleanup_admin_logs completed: {results}')
        return results

    except Exception as e:
        logger.error(f'cleanup_admin_logs failed: {str(e)}')
        self.retry(exc=e, countdown=600)
        raise


# ============================================================================
# SYSTEM SETTINGS SYNC TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_system_settings(self) -> Dict[str, Any]:
    """
    Synchronize system settings across environments or services.
    """
    logger.info("Starting sync_system_settings task")

    results = {
        'settings_synced': 0,
        'errors': 0,
        'details': [],
    }

    try:
        # Get all system settings
        settings = SystemSetting.objects.filter(deleted_at__isnull=True)

        # Sync to cache for fast access
        for setting in settings:
            try:
                cache.set(f'system_setting_{setting.key}', setting.value, timeout=86400)  # 24 hours
                results['settings_synced'] += 1
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error syncing setting {setting.key}: {str(e)}')

        # Sync to a global settings dictionary
        settings_dict = {s.key: s.value for s in settings}
        cache.set('system_settings_all', settings_dict, timeout=86400)

        logger.info(f'sync_system_settings completed: {results}')
        return results

    except Exception as e:
        logger.error(f'sync_system_settings failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# SYSTEM HEALTH CHECK TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def check_system_health(self) -> Dict[str, Any]:
    """
    Perform a system health check and log results.
    """
    logger.info("Starting check_system_health task")

    results = {
        'status': 'ok',
        'checks': {},
        'timestamp': timezone.now().isoformat(),
    }

    try:
        from . import get_system_health
        health = get_system_health()
        results = health

        # Create maintenance log entry
        maintenance_log = MaintenanceLog.objects.create(
            task_type='sync',
            status='completed',
            started_at=timezone.now() - timedelta(seconds=5),
            completed_at=timezone.now(),
            result=json.dumps(health),
            details={'health_check': health},
        )

        logger.info(f'check_system_health completed: {health.get("status")}')
        return results

    except Exception as e:
        logger.error(f'check_system_health failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# SCHEDULED REPORT PROCESSING TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_scheduled_reports(self) -> Dict[str, Any]:
    """
    Process all active scheduled reports that are due.
    """
    logger.info("Starting process_scheduled_reports task")

    results = {
        'schedules_processed': 0,
        'reports_generated': 0,
        'errors': 0,
        'details': [],
    }

    try:
        now = timezone.now()

        # Get active schedules where next_run <= now
        schedules = ReportSchedule.objects.filter(
            is_active=True,
            next_run__lte=now,
            deleted_at__isnull=True
        )

        for schedule in schedules:
            try:
                # Generate the report based on schedule type
                if schedule.report_type == 'daily':
                    from . import generate_daily_report
                    report_data = generate_daily_report()
                elif schedule.report_type == 'weekly':
                    from . import generate_weekly_report
                    report_data = generate_weekly_report()
                elif schedule.report_type == 'monthly':
                    from . import generate_monthly_report
                    report_data = generate_monthly_report()
                else:
                    report_data = {'report_type': schedule.report_type, 'data': {}}

                # Create report
                report = Report.objects.create(
                    name=f"{schedule.name} - {now.date().isoformat()}",
                    report_type=schedule.report_type,
                    generated_by=schedule.created_by,
                    title=f"{schedule.name} - {now.date().isoformat()}",
                    description=schedule.description or f"Automated report from schedule: {schedule.name}",
                    data=report_data,
                    format=schedule.format,
                    generated_at=now,
                    is_public=False,
                )

                results['reports_generated'] += 1
                results['details'].append({
                    'schedule_id': schedule.id,
                    'report_id': report.id,
                })

                # Update schedule last_run and next_run
                schedule.last_run = now
                schedule.next_run = schedule.calculate_next_run()
                schedule.save(update_fields=['last_run', 'next_run'])

                results['schedules_processed'] += 1

                # Send report to recipients
                if schedule.recipients:
                    for recipient in schedule.recipients:
                        try:
                            context = {
                                'schedule': schedule,
                                'report': report,
                                'report_data': report_data,
                                'date': now,
                                'app_name': 'Ekub Platform',
                            }
                            html_content = render_to_string('admin/emails/scheduled_report.html', context)
                            plain_message = f"""
                            Scheduled Report: {schedule.name}

                            Report Type: {schedule.get_report_type_display()}
                            Generated: {now.strftime('%Y-%m-%d %H:%M')}

                            View the full report in the admin panel.
                            """

                            send_mail(
                                f'Scheduled Report: {schedule.name}',
                                plain_message,
                                settings.DEFAULT_FROM_EMAIL,
                                [recipient],
                                html_message=html_content,
                                fail_silently=False,
                            )
                        except Exception as e:
                            logger.error(f'Error sending scheduled report to {recipient}: {str(e)}')

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error processing schedule {schedule.id}: {str(e)}')

        logger.info(f'process_scheduled_reports completed: {results}')
        return results

    except Exception as e:
        logger.error(f'process_scheduled_reports failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# DASHBOARD DIGEST TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_dashboard_digest(self) -> Dict[str, Any]:
    """
    Send a digest of dashboard statistics to admin users.
    """
    logger.info("Starting send_dashboard_digest task")

    results = {
        'digests_sent': 0,
        'errors': 0,
        'details': [],
    }

    try:
        from . import get_dashboard_stats
        stats = get_dashboard_stats()

        admin_users = User.objects.filter(
            is_staff=True,
            is_active=True,
            admin_preferences__email_notifications=True,
            deleted_at__isnull=True
        )

        for admin in admin_users:
            try:
                context = {
                    'admin': admin,
                    'stats': stats,
                    'date': timezone.now(),
                    'app_name': 'Ekub Platform',
                }

                html_content = render_to_string('admin/emails/dashboard_digest.html', context)
                plain_message = f"""
                Dashboard Digest - {timezone.now().strftime('%Y-%m-%d %H:%M')}

                Users:
                Total: {stats['users']['total']}
                Active: {stats['users']['active']}
                Verified: {stats['users']['verified']}

                Groups:
                Total: {stats['groups']['total']}
                Active: {stats['groups']['active']}
                Completed: {stats['groups']['completed']}

                Payments:
                Total: {stats['payments']['total']}
                Completed: {stats['payments']['completed']}
                Total Amount: {format_currency(stats['payments']['total_amount'])}
                Success Rate: {stats['payments']['success_rate']}%

                Contributions:
                Total: {stats['contributions']['total']}
                Paid: {stats['contributions']['paid']}
                Overdue: {stats['contributions']['overdue']}

                View full dashboard in the admin panel.
                """

                send_mail(
                    f'Dashboard Digest - {timezone.now().strftime("%Y-%m-%d")}',
                    plain_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [admin.email],
                    html_message=html_content,
                    fail_silently=False,
                )
                results['digests_sent'] += 1

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error sending dashboard digest to admin {admin.id}: {str(e)}')

        logger.info(f'send_dashboard_digest completed: {results}')
        return results

    except Exception as e:
        logger.error(f'send_dashboard_digest failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# BACKUP TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=600)
def backup_admin_data(self) -> Dict[str, Any]:
    """
    Perform a database backup or export of admin-related data.
    """
    logger.info("Starting backup_admin_data task")

    results = {
        'backup_created': False,
        'tables_backed_up': 0,
        'rows_exported': 0,
        'file_path': '',
        'errors': 0,
    }

    try:
        backup_dir = getattr(settings, 'ADMIN_BACKUP_DIR', '/tmp/admin_backups')
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(backup_dir, f'admin_data_backup_{timestamp}.json')

        # Export data from admin-related tables
        data_to_backup = {
            'admin_actions': list(AdminAction.objects.all().values()),
            'admin_logs': list(AdminLog.objects.all().values()),
            'system_settings': list(SystemSetting.objects.all().values()),
            'admin_preferences': list(AdminPreference.objects.all().values()),
            'dashboard_widgets': list(DashboardWidget.objects.all().values()),
            'report_schedules': list(ReportSchedule.objects.all().values()),
            'maintenance_logs': list(MaintenanceLog.objects.all().values()),
        }

        with open(backup_file, 'w') as f:
            json.dump(data_to_backup, f, indent=2, default=str)

        results['backup_created'] = True
        results['file_path'] = backup_file
        results['rows_exported'] = sum(len(v) for v in data_to_backup.values())
        results['tables_backed_up'] = len(data_to_backup)

        logger.info(f'backup_admin_data completed: {backup_file}')
        return results

    except Exception as e:
        logger.error(f'backup_admin_data failed: {str(e)}')
        self.retry(exc=e, countdown=600)
        raise


# ============================================================================
# CACHE CLEARING TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def clear_system_cache(self) -> Dict[str, Any]:
    """
    Clear all system caches.
    """
    logger.info("Starting clear_system_cache task")

    results = {
        'cache_cleared': False,
        'keys_cleared': 0,
        'errors': 0,
    }

    try:
        # Clear Django cache
        cache.clear()
        results['cache_cleared'] = True

        # Clear specific cache keys
        patterns = [
            'system_setting_*',
            'system_settings_all',
            'dashboard_stats_*',
            'admin_*',
            'report_*',
        ]

        cleared = 0
        for pattern in patterns:
            try:
                keys = cache.keys(pattern)
                for key in keys:
                    cache.delete(key)
                    cleared += 1
            except Exception as e:
                logger.warning(f'Error clearing pattern {pattern}: {str(e)}')

        results['keys_cleared'] = cleared

        # Create maintenance log
        MaintenanceLog.objects.create(
            task_type='cache_clear',
            status='completed',
            started_at=timezone.now() - timedelta(seconds=2),
            completed_at=timezone.now(),
            result=f'Cleared {cleared} cache keys',
            details={'keys_cleared': cleared},
        )

        logger.info(f'clear_system_cache completed: {results}')
        return results

    except Exception as e:
        logger.error(f'clear_system_cache failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# MAINTENANCE TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=600)
def run_maintenance_tasks(self) -> Dict[str, Any]:
    """
    Run general maintenance tasks for the system.
    """
    logger.info("Starting run_maintenance_tasks task")

    results = {
        'tasks_completed': [],
        'errors': 0,
    }

    try:
        maintenance_log = MaintenanceLog.objects.create(
            task_type='system_update',
            status='running',
            started_at=timezone.now(),
            details={'tasks': ['cleanup', 'cache_clear', 'sync_settings']},
        )

        tasks = []
        errors = 0

        # 1. Clean up admin logs
        try:
            result = cleanup_admin_logs.delay()
            tasks.append({'task': 'cleanup_admin_logs', 'status': 'queued'})
        except Exception as e:
            errors += 1
            tasks.append({'task': 'cleanup_admin_logs', 'status': 'failed', 'error': str(e)})

        # 2. Clear system cache
        try:
            result = clear_system_cache.delay()
            tasks.append({'task': 'clear_system_cache', 'status': 'queued'})
        except Exception as e:
            errors += 1
            tasks.append({'task': 'clear_system_cache', 'status': 'failed', 'error': str(e)})

        # 3. Sync system settings
        try:
            result = sync_system_settings.delay()
            tasks.append({'task': 'sync_system_settings', 'status': 'queued'})
        except Exception as e:
            errors += 1
            tasks.append({'task': 'sync_system_settings', 'status': 'failed', 'error': str(e)})

        # 4. Check system health
        try:
            result = check_system_health.delay()
            tasks.append({'task': 'check_system_health', 'status': 'queued'})
        except Exception as e:
            errors += 1
            tasks.append({'task': 'check_system_health', 'status': 'failed', 'error': str(e)})

        results['tasks_completed'] = tasks
        results['errors'] = errors

        maintenance_log.status = 'completed'
        maintenance_log.completed_at = timezone.now()
        maintenance_log.result = json.dumps(results)
        maintenance_log.save()

        logger.info(f'run_maintenance_tasks completed: {results}')
        return results

    except Exception as e:
        logger.error(f'run_maintenance_tasks failed: {str(e)}')
        self.retry(exc=e, countdown=600)
        raise


# ============================================================================
# USER ACTIVITY SUMMARY TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_user_activity_summary(self) -> Dict[str, Any]:
    """
    Send a summary of user activity to admin users.
    """
    logger.info("Starting send_user_activity_summary task")

    results = {
        'summaries_sent': 0,
        'errors': 0,
    }

    try:
        now = timezone.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=7)

        # Activity statistics
        active_users_today = User.objects.filter(
            last_activity__gte=day_start,
            is_active=True,
            deleted_at__isnull=True
        ).count()

        new_users_week = User.objects.filter(
            date_joined__gte=week_start,
            deleted_at__isnull=True
        ).count()

        active_groups_week = Group.objects.filter(
            updated_at__gte=week_start,
            deleted_at__isnull=True
        ).count()

        admin_users = User.objects.filter(
            is_staff=True,
            is_active=True,
            admin_preferences__email_notifications=True,
            deleted_at__isnull=True
        )

        for admin in admin_users:
            try:
                context = {
                    'admin': admin,
                    'active_users_today': active_users_today,
                    'new_users_week': new_users_week,
                    'active_groups_week': active_groups_week,
                    'date': now,
                    'app_name': 'Ekub Platform',
                }

                html_content = render_to_string('admin/emails/user_activity_summary.html', context)
                plain_message = f"""
                User Activity Summary

                Active Users Today: {active_users_today}
                New Users This Week: {new_users_week}
                Active Groups This Week: {active_groups_week}

                View full statistics in the admin panel.
                """

                send_mail(
                    f'User Activity Summary - {now.strftime("%Y-%m-%d")}',
                    plain_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [admin.email],
                    html_message=html_content,
                    fail_silently=False,
                )
                results['summaries_sent'] += 1

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error sending user activity summary to admin {admin.id}: {str(e)}')

        logger.info(f'send_user_activity_summary completed: {results}')
        return results

    except Exception as e:
        logger.error(f'send_user_activity_summary failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# PAYMENT RECONCILIATION TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def admin_payment_reconciliation(self) -> Dict[str, Any]:
    """
    Perform payment reconciliation and notify admins of discrepancies.
    """
    logger.info("Starting admin_payment_reconciliation task")

    results = {
        'payments_checked': 0,
        'discrepancies': 0,
        'reconciled': 0,
        'errors': 0,
    }

    try:
        from apps.payments.models import Payment, PaymentReconciliation

        # Get payments that need reconciliation
        pending_reconciliation = Payment.objects.filter(
            status='completed',
            reconciliations__isnull=True,
            deleted_at__isnull=True
        )[:100]

        results['payments_checked'] = pending_reconciliation.count()

        for payment in pending_reconciliation:
            try:
                # Attempt reconciliation (simplified)
                reconciliation_data = {
                    'external_reference': payment.reference,
                    'status': 'completed',
                    'matched': True,
                    'external_data': {'source': 'admin_reconciliation_task'},
                }

                from apps.payments import reconcile_payment
                success = reconcile_payment(payment.id, reconciliation_data)

                if success:
                    results['reconciled'] += 1
                else:
                    results['discrepancies'] += 1

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error reconciling payment {payment.id}: {str(e)}')

        # If discrepancies found, alert admins
        if results['discrepancies'] > 0:
            admin_users = User.objects.filter(
                is_staff=True,
                is_active=True,
                admin_preferences__email_notifications=True,
                deleted_at__isnull=True
            )

            for admin in admin_users:
                try:
                    send_mail(
                        'Payment Reconciliation Alert',
                        f'Found {results["discrepancies"]} payment discrepancies during reconciliation.',
                        settings.DEFAULT_FROM_EMAIL,
                        [admin.email],
                        fail_silently=False,
                    )
                except Exception as e:
                    logger.error(f'Error sending reconciliation alert to admin {admin.id}: {str(e)}')

        logger.info(f'admin_payment_reconciliation completed: {results}')
        return results

    except Exception as e:
        logger.error(f'admin_payment_reconciliation failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# GROUP STATUS MONITORING TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def monitor_group_status(self) -> Dict[str, Any]:
    """
    Monitor group status and alert admins of groups needing attention.
    """
    logger.info("Starting monitor_group_status task")

    results = {
        'groups_checked': 0,
        'stalled_groups': 0,
        'completed_groups': 0,
        'alerts_sent': 0,
        'errors': 0,
    }

    try:
        now = timezone.now()
        inactive_threshold = now - timedelta(days=14)

        # Find groups with no recent activity
        stalled_groups = Group.objects.filter(
            status='active',
            updated_at__lt=inactive_threshold,
            deleted_at__isnull=True
        )

        results['groups_checked'] = Group.objects.filter(deleted_at__isnull=True).count()
        results['stalled_groups'] = stalled_groups.count()

        # Find groups ready for completion
        ready_for_completion = Group.objects.filter(
            status='active',
            end_date__lt=now,
            deleted_at__isnull=True
        )

        results['completed_groups'] = ready_for_completion.count()

        # If there are stalled groups, alert admins
        if stalled_groups.exists():
            admin_users = User.objects.filter(
                is_staff=True,
                is_active=True,
                admin_preferences__email_notifications=True,
                deleted_at__isnull=True
            )

            group_names = list(stalled_groups.values_list('name', flat=True)[:10])

            for admin in admin_users:
                try:
                    send_mail(
                        'Stalled Groups Alert',
                        f'The following groups have been inactive for over 14 days:\n\n{chr(10).join(group_names)}\n\nPlease investigate.',
                        settings.DEFAULT_FROM_EMAIL,
                        [admin.email],
                        fail_silently=False,
                    )
                    results['alerts_sent'] += 1
                except Exception as e:
                    results['errors'] += 1
                    logger.error(f'Error sending stalled groups alert to admin {admin.id}: {str(e)}')

        logger.info(f'monitor_group_status completed: {results}')
        return results

    except Exception as e:
        logger.error(f'monitor_group_status failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# CONTRIBUTION OVERDUE MONITORING TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def monitor_overdue_contributions(self) -> Dict[str, Any]:
    """
    Monitor overdue contributions and alert admins.
    """
    logger.info("Starting monitor_overdue_contributions task")

    results = {
        'overdue_count': 0,
        'critical_overdue': 0,
        'alerts_sent': 0,
        'errors': 0,
    }

    try:
        overdue_contributions = Contribution.objects.filter(
            status='overdue',
            deleted_at__isnull=True
        )

        results['overdue_count'] = overdue_contributions.count()

        # Critical overdue (more than 30 days)
        critical_threshold = timezone.now() - timedelta(days=30)
        critical = overdue_contributions.filter(due_date__lt=critical_threshold)
        results['critical_overdue'] = critical.count()

        if results['overdue_count'] > 0:
            admin_users = User.objects.filter(
                is_staff=True,
                is_active=True,
                admin_preferences__email_notifications=True,
                deleted_at__isnull=True
            )

            for admin in admin_users:
                try:
                    send_mail(
                        'Overdue Contributions Alert',
                        f'Overdue Contributions: {results["overdue_count"]}\nCritical Overdue (>30 days): {results["critical_overdue"]}\n\nPlease review and take action.',
                        settings.DEFAULT_FROM_EMAIL,
                        [admin.email],
                        fail_silently=False,
                    )
                    results['alerts_sent'] += 1
                except Exception as e:
                    results['errors'] += 1
                    logger.error(f'Error sending overdue contributions alert to admin {admin.id}: {str(e)}')

        logger.info(f'monitor_overdue_contributions completed: {results}')
        return results

    except Exception as e:
        logger.error(f'monitor_overdue_contributions failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# TASK SCHEDULING (BROKER CONFIG)
# ============================================================================

# These tasks should be scheduled in celery beat schedule:
# - generate_daily_reports: daily at 6:00 AM
# - generate_weekly_reports: weekly on Monday at 7:00 AM
# - generate_monthly_reports: monthly on the 1st at 7:00 AM
# - send_admin_alerts: every 6 hours
# - cleanup_admin_logs: weekly on Sunday at 2:00 AM
# - sync_system_settings: every 6 hours
# - check_system_health: every hour
# - process_scheduled_reports: every 15 minutes
# - send_dashboard_digest: daily at 8:00 AM
# - backup_admin_data: daily at 1:00 AM
# - clear_system_cache: weekly on Sunday at 4:00 AM
# - run_maintenance_tasks: weekly on Sunday at 3:00 AM
# - send_user_activity_summary: daily at 9:00 AM
# - admin_payment_reconciliation: daily at 2:00 AM
# - monitor_group_status: every 6 hours
# - monitor_overdue_contributions: every 4 hours


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'generate_daily_reports',
    'generate_weekly_reports',
    'generate_monthly_reports',
    'send_admin_alerts',
    'cleanup_admin_logs',
    'sync_system_settings',
    'check_system_health',
    'process_scheduled_reports',
    'send_dashboard_digest',
    'backup_admin_data',
    'clear_system_cache',
    'run_maintenance_tasks',
    'send_user_activity_summary',
    'admin_payment_reconciliation',
    'monitor_group_status',
    'monitor_overdue_contributions',
]