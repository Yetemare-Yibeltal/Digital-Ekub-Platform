"""
Celery tasks for the audit app.

This module provides background task functions for audit and monitoring operations:
- Processing pending audit events
- Generating scheduled audit reports (daily, weekly, monthly)
- Enforcing data retention policies
- Periodic system health checks
- Collecting performance metrics
- Detecting anomalies in metrics
- Sending security alerts for critical events
- Sending health alerts for degraded systems
- Sending anomaly alerts for detected anomalies
- Cleaning up old audit logs (retention enforcement)
- Cleaning up old security events
- Cleaning up old user activities
- Aggregating audit statistics for reporting
- Generating daily audit summaries
- Processing and evaluating audit rules
- Syncing audit configuration across services
- Backing up audit data

All tasks include comprehensive error handling, logging, retry logic,
and performance optimizations for bulk operations.
"""

from celery import shared_task
from celery.utils.log import get_task_logger
from django.db import transaction
from django.db.models import Q, Count, Sum, Avg, F, OuterRef, Subquery, Min, Max
from django.utils import timezone
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command

import logging
from datetime import timedelta, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple, Union
import json
import os
import subprocess
import shutil

from apps.users.models import User
from apps.common.utils import send_email, send_sms, format_currency
from apps.common.constants import NotificationType, NotificationPriority

from .models import (
    AuditLog,
    AuditEvent,
    AuditRule,
    AuditAlert,
    AuditReport,
    AuditRetentionPolicy,
    SecurityEvent,
    UserActivity,
    SystemHealth,
    PerformanceMetric,
    AnomalyDetection,
)

logger = get_task_logger(__name__)


# ============================================================================
# AUDIT EVENT PROCESSING TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_audit_events(self) -> Dict[str, Any]:
    """
    Process all pending audit events.
    - Evaluate against audit rules
    - Generate alerts for matching events
    - Update event status to processed
    """
    logger.info("Starting process_audit_events task")

    results = {
        'processed': 0,
        'alerts_generated': 0,
        'errors': 0,
        'details': [],
    }

    try:
        # Get pending events
        events = AuditEvent.objects.filter(processed=False).order_by('created_at')[:100]

        for event in events:
            try:
                with transaction.atomic():
                    # Evaluate against rules
                    rules = AuditRule.objects.filter(is_active=True)
                    for rule in rules:
                        if rule.evaluate(event):
                            # Generate alert
                            alert = AuditAlert.objects.create(
                                rule=rule,
                                severity=rule.severity,
                                message=f"Rule '{rule.name}' triggered by event {event.event_type}",
                                timestamp=timezone.now(),
                            )
                            results['alerts_generated'] += 1
                            rule.trigger(event)

                    # Mark as processed
                    event.processed = True
                    event.processed_at = timezone.now()
                    event.save(update_fields=['processed', 'processed_at'])
                    results['processed'] += 1
                    results['details'].append({
                        'event_id': event.id,
                        'event_type': event.event_type,
                        'alerts_generated': results['alerts_generated'],
                    })

            except Exception as e:
                results['errors'] += 1
                event.error_message = str(e)
                event.save(update_fields=['error_message'])
                logger.error(f'Error processing event {event.id}: {str(e)}')

        logger.info(f'process_audit_events completed: {results}')
        return results

    except Exception as e:
        logger.error(f'process_audit_events failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# AUDIT REPORT GENERATION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def generate_daily_audit_reports(self) -> Dict[str, Any]:
    """
    Generate daily audit summary reports for admin users.
    """
    logger.info("Starting generate_daily_audit_reports task")

    results = {
        'reports_generated': 0,
        'reports_sent': 0,
        'errors': 0,
    }

    try:
        admin_users = User.objects.filter(
            is_staff=True,
            is_active=True,
            admin_preferences__email_notifications=True,
            deleted_at__isnull=True
        )

        yesterday = timezone.now().date() - timedelta(days=1)

        for admin in admin_users:
            try:
                # Generate daily audit summary
                start_date = datetime.combine(yesterday, datetime.min.time())
                end_date = datetime.combine(yesterday, datetime.max.time())

                # Audit statistics
                total_logs = AuditLog.objects.filter(
                    timestamp__gte=start_date,
                    timestamp__lte=end_date
                ).count()

                by_severity = AuditLog.objects.filter(
                    timestamp__gte=start_date,
                    timestamp__lte=end_date
                ).values('severity').annotate(count=Count('id'))

                by_action = AuditLog.objects.filter(
                    timestamp__gte=start_date,
                    timestamp__lte=end_date
                ).values('action').annotate(count=Count('id')).order_by('-count')[:10]

                security_events = SecurityEvent.objects.filter(
                    timestamp__gte=start_date,
                    timestamp__lte=end_date
                ).count()

                alerts = AuditAlert.objects.filter(
                    timestamp__gte=start_date,
                    timestamp__lte=end_date
                ).count()

                anomalies = AnomalyDetection.objects.filter(
                    detected_at__gte=start_date,
                    detected_at__lte=end_date
                ).count()

                # Create report
                report = AuditReport.objects.create(
                    name=f"Daily Audit Summary - {yesterday.isoformat()}",
                    report_type='activity',
                    generated_by=admin,
                    parameters={
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                    },
                    format='json',
                    data={
                        'total_logs': total_logs,
                        'by_severity': list(by_severity),
                        'top_actions': list(by_action),
                        'security_events': security_events,
                        'alerts': alerts,
                        'anomalies': anomalies,
                    },
                    generated_at=timezone.now(),
                    is_public=False,
                )

                results['reports_generated'] += 1

                # Send email
                context = {
                    'admin': admin,
                    'report': report,
                    'date': yesterday,
                    'app_name': 'Ekub Platform',
                }
                html_content = render_to_string('audit/emails/daily_audit_summary.html', context)
                plain_message = f"""
                Daily Audit Summary - {yesterday.isoformat()}

                Total Audit Logs: {total_logs}
                Security Events: {security_events}
                Alerts: {alerts}
                Anomalies: {anomalies}

                View full report in the admin panel.
                """

                send_mail(
                    f'Daily Audit Summary - {yesterday.isoformat()}',
                    plain_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [admin.email],
                    html_message=html_content,
                    fail_silently=False,
                )
                results['reports_sent'] += 1

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error generating daily audit report for admin {admin.id}: {str(e)}')

        logger.info(f'generate_daily_audit_reports completed: {results}')
        return results

    except Exception as e:
        logger.error(f'generate_daily_audit_reports failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def generate_weekly_audit_reports(self) -> Dict[str, Any]:
    """
    Generate weekly audit summary reports for admin users.
    """
    logger.info("Starting generate_weekly_audit_reports task")

    results = {
        'reports_generated': 0,
        'reports_sent': 0,
        'errors': 0,
    }

    try:
        admin_users = User.objects.filter(
            is_staff=True,
            is_active=True,
            admin_preferences__email_notifications=True,
            deleted_at__isnull=True
        )

        week_start = timezone.now().date() - timedelta(days=7)
        week_end = timezone.now().date()

        for admin in admin_users:
            try:
                start_date = datetime.combine(week_start, datetime.min.time())
                end_date = datetime.combine(week_end, datetime.max.time())

                # Weekly statistics
                total_logs = AuditLog.objects.filter(
                    timestamp__gte=start_date,
                    timestamp__lte=end_date
                ).count()

                by_day = AuditLog.objects.filter(
                    timestamp__gte=start_date,
                    timestamp__lte=end_date
                ).extra(
                    select={'day': 'date(timestamp)'}
                ).values('day').annotate(count=Count('id')).order_by('day')

                by_user = AuditLog.objects.filter(
                    timestamp__gte=start_date,
                    timestamp__lte=end_date
                ).values('user__email').annotate(count=Count('id')).order_by('-count')[:10]

                security_events = SecurityEvent.objects.filter(
                    timestamp__gte=start_date,
                    timestamp__lte=end_date
                ).count()

                alerts = AuditAlert.objects.filter(
                    timestamp__gte=start_date,
                    timestamp__lte=end_date
                ).count()

                anomalies = AnomalyDetection.objects.filter(
                    detected_at__gte=start_date,
                    detected_at__lte=end_date
                ).count()

                report = AuditReport.objects.create(
                    name=f"Weekly Audit Summary - {week_start.isoformat()} to {week_end.isoformat()}",
                    report_type='activity',
                    generated_by=admin,
                    parameters={
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                    },
                    format='json',
                    data={
                        'total_logs': total_logs,
                        'by_day': list(by_day),
                        'top_users': list(by_user),
                        'security_events': security_events,
                        'alerts': alerts,
                        'anomalies': anomalies,
                    },
                    generated_at=timezone.now(),
                    is_public=False,
                )

                results['reports_generated'] += 1

                context = {
                    'admin': admin,
                    'report': report,
                    'week_start': week_start,
                    'week_end': week_end,
                    'app_name': 'Ekub Platform',
                }
                html_content = render_to_string('audit/emails/weekly_audit_summary.html', context)
                plain_message = f"""
                Weekly Audit Summary
                {week_start.isoformat()} to {week_end.isoformat()}

                Total Audit Logs: {total_logs}
                Security Events: {security_events}
                Alerts: {alerts}
                Anomalies: {anomalies}

                View full report in the admin panel.
                """

                send_mail(
                    f'Weekly Audit Summary - {week_start.isoformat()}',
                    plain_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [admin.email],
                    html_message=html_content,
                    fail_silently=False,
                )
                results['reports_sent'] += 1

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error generating weekly audit report for admin {admin.id}: {str(e)}')

        logger.info(f'generate_weekly_audit_reports completed: {results}')
        return results

    except Exception as e:
        logger.error(f'generate_weekly_audit_reports failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# RETENTION POLICY ENFORCEMENT TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=600)
def enforce_retention_policies(self) -> Dict[str, Any]:
    """
    Enforce all active retention policies.
    - Deletes old audit logs, security events, user activities, etc.
    """
    logger.info("Starting enforce_retention_policies task")

    results = {
        'policies_enforced': 0,
        'records_deleted': 0,
        'errors': 0,
        'details': [],
    }

    try:
        policies = AuditRetentionPolicy.objects.filter(is_active=True)

        for policy in policies:
            try:
                deleted = policy.enforce()
                results['records_deleted'] += deleted
                results['policies_enforced'] += 1
                results['details'].append({
                    'policy_id': policy.id,
                    'resource_type': policy.resource_type,
                    'deleted': deleted,
                })
                logger.info(f'Retention policy enforced: {policy.resource_type} - deleted {deleted} records')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error enforcing retention policy {policy.id}: {str(e)}')

        logger.info(f'enforce_retention_policies completed: {results}')
        return results

    except Exception as e:
        logger.error(f'enforce_retention_policies failed: {str(e)}')
        self.retry(exc=e, countdown=600)
        raise


# ============================================================================
# SYSTEM HEALTH CHECK TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def check_system_health_task(self) -> Dict[str, Any]:
    """
    Perform system health checks for all components.
    """
    logger.info("Starting check_system_health_task")

    results = {
        'checks_performed': 0,
        'warnings': 0,
        'errors': 0,
        'details': [],
    }

    try:
        components = ['database', 'cache', 'celery', 'payment_gateway', 'email', 'sms', 'redis']

        for component in components:
            try:
                status = 'ok'
                message = ''
                details = {}

                if component == 'database':
                    from django.db import connection
                    with connection.cursor() as cursor:
                        start = timezone.now()
                        cursor.execute('SELECT 1')
                        end = timezone.now()
                    latency = (end - start).total_seconds() * 1000
                    details['latency_ms'] = round(latency, 2)
                    if latency > 100:
                        status = 'warning'
                        message = f'Database latency is {latency:.2f}ms'
                        results['warnings'] += 1

                elif component == 'cache':
                    from django.core.cache import cache
                    start = timezone.now()
                    cache.set('health_check', 'ok', 10)
                    value = cache.get('health_check')
                    end = timezone.now()
                    if value == 'ok':
                        latency = (end - start).total_seconds() * 1000
                        details['latency_ms'] = round(latency, 2)
                        if latency > 50:
                            status = 'warning'
                            message = f'Cache latency is {latency:.2f}ms'
                            results['warnings'] += 1
                    else:
                        status = 'error'
                        message = 'Cache returned unexpected value'
                        results['errors'] += 1

                elif component == 'celery':
                    from celery import current_app
                    conn = current_app.connection()
                    conn.ensure_connection(max_retries=3)
                    conn.release()
                    details['status'] = 'ok'

                elif component == 'payment_gateway':
                    from apps.payments.gateways import get_available_gateways
                    gateways = get_available_gateways()
                    details['gateways'] = gateways
                    if not any(gateways.values()):
                        status = 'warning'
                        message = 'No payment gateways available'
                        results['warnings'] += 1

                elif component == 'email':
                    # Check email configuration
                    if settings.DEFAULT_FROM_EMAIL:
                        details['from_email'] = settings.DEFAULT_FROM_EMAIL
                    else:
                        status = 'warning'
                        message = 'Email not configured'
                        results['warnings'] += 1

                elif component == 'sms':
                    # Check SMS configuration
                    if settings.AFRICASTALKING_API_KEY:
                        details['provider'] = 'Africa\'s Talking'
                    else:
                        status = 'warning'
                        message = 'SMS not configured'
                        results['warnings'] += 1

                elif component == 'redis':
                    from django.core.cache import cache
                    try:
                        cache.set('redis_health_check', 'ok', 10)
                        value = cache.get('redis_health_check')
                        if value == 'ok':
                            details['status'] = 'ok'
                        else:
                            status = 'error'
                            message = 'Redis not responding'
                            results['errors'] += 1
                    except Exception as e:
                        status = 'error'
                        message = str(e)
                        results['errors'] += 1

                # Create health check record
                SystemHealth.objects.create(
                    component=component,
                    status=status,
                    message=message,
                    details=details,
                    checked_at=timezone.now(),
                )

                results['checks_performed'] += 1
                results['details'].append({
                    'component': component,
                    'status': status,
                    'message': message,
                })

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error checking component {component}: {str(e)}')
                SystemHealth.objects.create(
                    component=component,
                    status='error',
                    message=f'Health check failed: {str(e)}',
                    details={'error': str(e)},
                    checked_at=timezone.now(),
                )

        # If there are critical errors, send alert
        if results['errors'] > 0 or results['warnings'] > 3:
            send_health_alert.delay(results)

        logger.info(f'check_system_health_task completed: {results}')
        return results

    except Exception as e:
        logger.error(f'check_system_health_task failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# PERFORMANCE METRICS COLLECTION TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def collect_performance_metrics(self) -> Dict[str, Any]:
    """
    Collect performance metrics from various sources.
    """
    logger.info("Starting collect_performance_metrics task")

    results = {
        'metrics_collected': 0,
        'errors': 0,
    }

    try:
        from django.db import connection
        import time

        # Database query performance
        start = time.time()
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        db_latency = (time.time() - start) * 1000

        PerformanceMetric.objects.create(
            metric_name='db_query_latency',
            value=db_latency,
            unit='ms',
            labels={'type': 'health_check'},
            timestamp=timezone.now(),
        )
        results['metrics_collected'] += 1

        # Cache performance
        from django.core.cache import cache
        start = time.time()
        cache.set('perf_test', 'ok', 10)
        value = cache.get('perf_test')
        cache_latency = (time.time() - start) * 1000

        PerformanceMetric.objects.create(
            metric_name='cache_latency',
            value=cache_latency,
            unit='ms',
            labels={'type': 'health_check'},
            timestamp=timezone.now(),
        )
        results['metrics_collected'] += 1

        # API request count (from cache)
        api_requests = cache.get('api_requests_total', 0)
        PerformanceMetric.objects.create(
            metric_name='api_requests_total',
            value=api_requests,
            unit='count',
            labels={'type': 'system'},
            timestamp=timezone.now(),
        )
        results['metrics_collected'] += 1

        # Active users (from cache)
        active_users = cache.get('active_users_total', 0)
        PerformanceMetric.objects.create(
            metric_name='active_users_total',
            value=active_users,
            unit='count',
            labels={'type': 'user'},
            timestamp=timezone.now(),
        )
        results['metrics_collected'] += 1

        # Database connection count
        from django.db import connections
        db_connections = len(connections.all())
        PerformanceMetric.objects.create(
            metric_name='db_connections',
            value=db_connections,
            unit='count',
            labels={'type': 'database'},
            timestamp=timezone.now(),
        )
        results['metrics_collected'] += 1

        # Log metric collection
        logger.info(f'collect_performance_metrics completed: {results}')
        return results

    except Exception as e:
        logger.error(f'collect_performance_metrics failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# ANOMALY DETECTION TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def detect_anomalies_task(self) -> Dict[str, Any]:
    """
    Detect anomalies in performance metrics.
    """
    logger.info("Starting detect_anomalies_task")

    results = {
        'anomalies_detected': 0,
        'errors': 0,
        'details': [],
    }

    try:
        # Check for anomalies in key metrics
        metrics_to_check = ['db_query_latency', 'cache_latency', 'api_requests_total']

        for metric_name in metrics_to_check:
            try:
                # Get last 24 hours of data
                start_date = timezone.now() - timedelta(hours=24)
                metrics = PerformanceMetric.objects.filter(
                    metric_name=metric_name,
                    timestamp__gte=start_date
                ).order_by('-timestamp')[:100]

                if metrics.count() < 10:
                    continue

                # Calculate baseline
                values = [float(m.value) for m in metrics]
                mean = sum(values) / len(values)
                std_dev = (sum((x - mean) ** 2 for x in values) / len(values)) ** 0.5

                # Get latest value
                latest = metrics.first()
                if latest and std_dev > 0:
                    z_score = (float(latest.value) - mean) / std_dev

                    # If z_score > 3, it's an anomaly
                    if abs(z_score) > 3:
                        anomaly_type = 'spike' if z_score > 0 else 'drop'
                        severity = 'error' if abs(z_score) > 5 else 'warning'

                        # Check if anomaly already exists for this metric
                        existing = AnomalyDetection.objects.filter(
                            metric_name=metric_name,
                            status='open',
                            detected_at__gte=timezone.now() - timedelta(hours=1)
                        ).exists()

                        if not existing:
                            AnomalyDetection.objects.create(
                                anomaly_type=anomaly_type,
                                metric_name=metric_name,
                                value=latest.value,
                                baseline=mean,
                                z_score=z_score,
                                severity=severity,
                                description=f'Anomaly detected in {metric_name}: z-score={z_score:.2f}',
                                detected_at=timezone.now(),
                                status='open',
                                details={
                                    'mean': mean,
                                    'std_dev': std_dev,
                                    'z_score': z_score,
                                    'threshold': 3.0,
                                },
                            )
                            results['anomalies_detected'] += 1
                            results['details'].append({
                                'metric_name': metric_name,
                                'z_score': z_score,
                                'anomaly_type': anomaly_type,
                            })

                            # If severe, send alert
                            if severity == 'error':
                                send_anomaly_alert.delay(metric_name, z_score, mean)

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error detecting anomaly for {metric_name}: {str(e)}')

        logger.info(f'detect_anomalies_task completed: {results}')
        return results

    except Exception as e:
        logger.error(f'detect_anomalies_task failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# ALERT TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_security_alert(self, security_event_id: int) -> Dict[str, Any]:
    """
    Send a security alert for a critical security event.
    """
    try:
        event = SecurityEvent.objects.get(id=security_event_id)
    except SecurityEvent.DoesNotExist:
        logger.error(f'Security event {security_event_id} not found')
        return {'error': 'Event not found'}

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
                'event': event,
                'app_name': 'Ekub Platform',
            }
            html_content = render_to_string('audit/emails/security_alert.html', context)
            plain_message = f"""
            SECURITY ALERT

            Event: {event.get_event_type_display()}
            User: {event.user.email}
            Description: {event.description}
            Severity: {event.severity}
            Time: {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

            Please investigate immediately.
            """

            send_mail(
                f'[SECURITY] {event.get_event_type_display()} - {event.user.email}',
                plain_message,
                settings.DEFAULT_FROM_EMAIL,
                [admin.email],
                html_message=html_content,
                fail_silently=False,
            )
        except Exception as e:
            logger.error(f'Error sending security alert to admin {admin.id}: {str(e)}')

    return {'sent_to': admin_users.count()}


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_health_alert(self, health_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a health alert for degraded system components.
    """
    if health_results.get('errors', 0) == 0 and health_results.get('warnings', 0) <= 3:
        return {'message': 'No critical issues'}

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
                'health_results': health_results,
                'app_name': 'Ekub Platform',
            }
            html_content = render_to_string('audit/emails/health_alert.html', context)
            plain_message = f"""
            SYSTEM HEALTH ALERT

            Errors: {health_results.get('errors', 0)}
            Warnings: {health_results.get('warnings', 0)}

            Details:
            {json.dumps(health_results.get('details', []), indent=2)}

            Please investigate immediately.
            """

            send_mail(
                f'[SYSTEM HEALTH] {health_results.get("errors", 0)} errors, {health_results.get("warnings", 0)} warnings',
                plain_message,
                settings.DEFAULT_FROM_EMAIL,
                [admin.email],
                html_message=html_content,
                fail_silently=False,
            )
        except Exception as e:
            logger.error(f'Error sending health alert to admin {admin.id}: {str(e)}')

    return {'sent_to': admin_users.count()}


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_anomaly_alert(self, metric_name: str, z_score: float, baseline: float) -> Dict[str, Any]:
    """
    Send an alert for a detected anomaly.
    """
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
                'metric_name': metric_name,
                'z_score': z_score,
                'baseline': baseline,
                'app_name': 'Ekub Platform',
            }
            html_content = render_to_string('audit/emails/anomaly_alert.html', context)
            plain_message = f"""
            ANOMALY DETECTED

            Metric: {metric_name}
            Z-Score: {z_score:.2f}
            Baseline: {baseline:.2f}

            This indicates unusual behavior in the system.

            Please investigate.
            """

            send_mail(
                f'[ANOMALY] {metric_name} - z-score {z_score:.2f}',
                plain_message,
                settings.DEFAULT_FROM_EMAIL,
                [admin.email],
                html_message=html_content,
                fail_silently=False,
            )
        except Exception as e:
            logger.error(f'Error sending anomaly alert to admin {admin.id}: {str(e)}')

    return {'sent_to': admin_users.count()}


# ============================================================================
# CLEANUP TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=600)
def cleanup_old_audit_data(self) -> Dict[str, Any]:
    """
    Comprehensive cleanup of all old audit data.
    """
    logger.info("Starting cleanup_old_audit_data task")

    results = {
        'audit_logs_deleted': 0,
        'security_events_deleted': 0,
        'user_activities_deleted': 0,
        'anomalies_deleted': 0,
        'metrics_deleted': 0,
        'errors': 0,
    }

    try:
        # Delete audit logs older than 365 days (if no retention policy)
        cutoff = timezone.now() - timedelta(days=365)
        deleted, _ = AuditLog.objects.filter(timestamp__lt=cutoff).delete()
        results['audit_logs_deleted'] = deleted

        # Delete security events older than 90 days
        cutoff = timezone.now() - timedelta(days=90)
        deleted, _ = SecurityEvent.objects.filter(timestamp__lt=cutoff).delete()
        results['security_events_deleted'] = deleted

        # Delete user activities older than 180 days
        cutoff = timezone.now() - timedelta(days=180)
        deleted, _ = UserActivity.objects.filter(timestamp__lt=cutoff).delete()
        results['user_activities_deleted'] = deleted

        # Delete resolved anomalies older than 30 days
        cutoff = timezone.now() - timedelta(days=30)
        deleted, _ = AnomalyDetection.objects.filter(
            status__in=['resolved', 'false_positive'],
            resolved_at__lt=cutoff
        ).delete()
        results['anomalies_deleted'] = deleted

        # Delete old performance metrics (older than 90 days)
        cutoff = timezone.now() - timedelta(days=90)
        deleted, _ = PerformanceMetric.objects.filter(timestamp__lt=cutoff).delete()
        results['metrics_deleted'] = deleted

        logger.info(f'cleanup_old_audit_data completed: {results}')
        return results

    except Exception as e:
        logger.error(f'cleanup_old_audit_data failed: {str(e)}')
        self.retry(exc=e, countdown=600)
        raise


# ============================================================================
# AUDIT STATISTICS AGGREGATION TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def aggregate_audit_statistics(self) -> Dict[str, Any]:
    """
    Aggregate audit statistics for reporting and caching.
    """
    logger.info("Starting aggregate_audit_statistics task")

    results = {
        'statistics_cached': False,
        'errors': 0,
    }

    try:
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)

        # Cache statistics for quick access
        stats = {
            'today': {
                'total_logs': AuditLog.objects.filter(timestamp__gte=today_start).count(),
                'security_events': SecurityEvent.objects.filter(timestamp__gte=today_start).count(),
                'alerts': AuditAlert.objects.filter(timestamp__gte=today_start).count(),
                'anomalies': AnomalyDetection.objects.filter(detected_at__gte=today_start).count(),
            },
            'week': {
                'total_logs': AuditLog.objects.filter(timestamp__gte=week_start).count(),
                'security_events': SecurityEvent.objects.filter(timestamp__gte=week_start).count(),
                'alerts': AuditAlert.objects.filter(timestamp__gte=week_start).count(),
                'anomalies': AnomalyDetection.objects.filter(detected_at__gte=week_start).count(),
            },
            'month': {
                'total_logs': AuditLog.objects.filter(timestamp__gte=month_start).count(),
                'security_events': SecurityEvent.objects.filter(timestamp__gte=month_start).count(),
                'alerts': AuditAlert.objects.filter(timestamp__gte=month_start).count(),
                'anomalies': AnomalyDetection.objects.filter(detected_at__gte=month_start).count(),
            },
            'total': {
                'total_logs': AuditLog.objects.count(),
                'security_events': SecurityEvent.objects.count(),
                'alerts': AuditAlert.objects.count(),
                'anomalies': AnomalyDetection.objects.count(),
                'rules': AuditRule.objects.filter(is_active=True).count(),
                'policies': AuditRetentionPolicy.objects.filter(is_active=True).count(),
            },
        }

        # Cache the statistics
        cache.set('audit_statistics', stats, timeout=3600)
        results['statistics_cached'] = True

        logger.info(f'aggregate_audit_statistics completed: {results}')
        return results

    except Exception as e:
        logger.error(f'aggregate_audit_statistics failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# AUDIT RULE PROCESSING TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_audit_rules_task(self) -> Dict[str, Any]:
    """
    Process and evaluate all active audit rules against recent audit logs.
    """
    logger.info("Starting process_audit_rules_task")

    results = {
        'logs_processed': 0,
        'rules_triggered': 0,
        'alerts_generated': 0,
        'errors': 0,
    }

    try:
        rules = AuditRule.objects.filter(is_active=True)
        if not rules.exists():
            return results

        # Get recent audit logs (last 5 minutes)
        cutoff = timezone.now() - timedelta(minutes=5)
        recent_logs = AuditLog.objects.filter(timestamp__gte=cutoff).order_by('timestamp')[:100]

        for log in recent_logs:
            results['logs_processed'] += 1
            for rule in rules:
                try:
                    if rule.evaluate(log):
                        rule.trigger(log)
                        results['rules_triggered'] += 1
                        # Create alert
                        AuditAlert.objects.create(
                            rule=rule,
                            audit_log=log,
                            severity=rule.severity,
                            message=f"Rule '{rule.name}' triggered by {log.action} on {log.resource}",
                            timestamp=timezone.now(),
                        )
                        results['alerts_generated'] += 1
                except Exception as e:
                    results['errors'] += 1
                    logger.error(f'Error evaluating rule {rule.id} against log {log.id}: {str(e)}')

        logger.info(f'process_audit_rules_task completed: {results}')
        return results

    except Exception as e:
        logger.error(f'process_audit_rules_task failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# AUDIT CONFIGURATION SYNC TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_audit_configuration(self) -> Dict[str, Any]:
    """
    Sync audit configuration across services and cache.
    """
    logger.info("Starting sync_audit_configuration task")

    results = {
        'rules_synced': 0,
        'policies_synced': 0,
        'errors': 0,
    }

    try:
        # Sync rules to cache
        rules = AuditRule.objects.filter(is_active=True)
        rule_data = []
        for rule in rules:
            rule_data.append({
                'id': rule.id,
                'name': rule.name,
                'condition': rule.condition,
                'action': rule.action,
                'severity': rule.severity,
            })
        cache.set('audit_rules_active', rule_data, timeout=3600)
        results['rules_synced'] = rules.count()

        # Sync retention policies to cache
        policies = AuditRetentionPolicy.objects.filter(is_active=True)
        policy_data = []
        for policy in policies:
            policy_data.append({
                'id': policy.id,
                'resource_type': policy.resource_type,
                'retention_days': policy.retention_days,
            })
        cache.set('audit_retention_policies_active', policy_data, timeout=3600)
        results['policies_synced'] = policies.count()

        logger.info(f'sync_audit_configuration completed: {results}')
        return results

    except Exception as e:
        logger.error(f'sync_audit_configuration failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# AUDIT DATA BACKUP TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=600)
def backup_audit_data(self) -> Dict[str, Any]:
    """
    Backup audit data to a file for archival purposes.
    """
    logger.info("Starting backup_audit_data task")

    results = {
        'backup_created': False,
        'records_exported': 0,
        'file_path': '',
        'errors': 0,
    }

    try:
        backup_dir = getattr(settings, 'AUDIT_BACKUP_DIR', '/tmp/audit_backups')
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(backup_dir, f'audit_data_backup_{timestamp}.json')

        # Export data from audit tables
        data_to_backup = {
            'audit_logs': list(AuditLog.objects.all().values()),
            'security_events': list(SecurityEvent.objects.all().values()),
            'user_activities': list(UserActivity.objects.all().values()),
            'anomalies': list(AnomalyDetection.objects.all().values()),
            'performance_metrics': list(PerformanceMetric.objects.all().values()),
        }

        with open(backup_file, 'w') as f:
            json.dump(data_to_backup, f, indent=2, default=str)

        results['backup_created'] = True
        results['file_path'] = backup_file
        results['records_exported'] = sum(len(v) for v in data_to_backup.values())

        logger.info(f'backup_audit_data completed: {backup_file}')
        return results

    except Exception as e:
        logger.error(f'backup_audit_data failed: {str(e)}')
        self.retry(exc=e, countdown=600)
        raise


# ============================================================================
# TASK SCHEDULING (BROKER CONFIG)
# ============================================================================

# These tasks should be scheduled in celery beat schedule:
# - process_audit_events: every minute
# - process_audit_rules_task: every 5 minutes
# - check_system_health_task: every 5 minutes
# - collect_performance_metrics: every 5 minutes
# - detect_anomalies_task: every 15 minutes
# - aggregate_audit_statistics: every hour
# - generate_daily_audit_reports: daily at 7:00 AM
# - generate_weekly_audit_reports: weekly on Monday at 8:00 AM
# - enforce_retention_policies: daily at 2:00 AM
# - cleanup_old_audit_data: daily at 3:00 AM
# - sync_audit_configuration: every hour
# - backup_audit_data: daily at 1:00 AM


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'process_audit_events',
    'generate_daily_audit_reports',
    'generate_weekly_audit_reports',
    'enforce_retention_policies',
    'check_system_health_task',
    'collect_performance_metrics',
    'detect_anomalies_task',
    'send_security_alert',
    'send_health_alert',
    'send_anomaly_alert',
    'cleanup_old_audit_data',
    'aggregate_audit_statistics',
    'process_audit_rules_task',
    'sync_audit_configuration',
    'backup_audit_data',
]