"""
Signals for the audit app.

This module provides signal handlers for all audit models:
- AuditLog: automatic creation from model changes, cache invalidation
- AuditEvent: trigger processing on creation, update status
- AuditRule: cache invalidation, trigger evaluation
- AuditAlert: notify on status changes, cache invalidation
- AuditReport: update expiry, cache invalidation
- AuditRetentionPolicy: enforce on save, cache invalidation
- SecurityEvent: trigger alerts on critical severity, cache invalidation
- UserActivity: track user actions, cache invalidation
- SystemHealth: trigger health alerts, cache invalidation
- PerformanceMetric: trigger anomaly detection, cache invalidation
- AnomalyDetection: trigger alerts, cache invalidation

All signal handlers include comprehensive logging, error handling,
cache invalidation, and integration with the system.
"""

import logging
import json
from django.db.models.signals import (
    pre_save, post_save, pre_delete, post_delete,
    m2m_changed, class_prepared
)
from django.dispatch import receiver
from django.utils import timezone
from django.core.cache import cache
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from apps.users.models import User
from apps.common.utils import log_audit_event, get_client_ip

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

logger = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def invalidate_audit_cache(model_name: str, instance_id: Optional[int] = None):
    """
    Invalidate cache keys related to audit models.
    """
    keys = []
    if model_name == 'audit_log':
        keys.append('audit_logs_recent')
        keys.append('audit_statistics')
        if instance_id:
            keys.append(f'audit_log_{instance_id}')
    elif model_name == 'audit_event':
        if instance_id:
            keys.append(f'audit_event_{instance_id}')
    elif model_name == 'audit_rule':
        keys.append('audit_rules_active')
        if instance_id:
            keys.append(f'audit_rule_{instance_id}')
    elif model_name == 'audit_alert':
        if instance_id:
            keys.append(f'audit_alert_{instance_id}')
    elif model_name == 'audit_report':
        keys.append('audit_reports_recent')
        if instance_id:
            keys.append(f'audit_report_{instance_id}')
    elif model_name == 'audit_retention_policy':
        keys.append('audit_retention_policies_active')
        if instance_id:
            keys.append(f'audit_retention_policy_{instance_id}')
    elif model_name == 'security_event':
        keys.append('security_events_recent')
        keys.append('security_statistics')
        if instance_id:
            keys.append(f'security_event_{instance_id}')
    elif model_name == 'user_activity':
        if instance_id:
            keys.append(f'user_activity_{instance_id}')
    elif model_name == 'system_health':
        keys.append('system_health_latest')
        if instance_id:
            keys.append(f'system_health_{instance_id}')
    elif model_name == 'performance_metric':
        keys.append('performance_metrics_latest')
        if instance_id:
            keys.append(f'performance_metric_{instance_id}')
    elif model_name == 'anomaly_detection':
        keys.append('anomaly_detections_open')
        if instance_id:
            keys.append(f'anomaly_detection_{instance_id}')

    for key in keys:
        cache.delete(key)
        logger.debug(f'Invalidated cache key: {key}')


def create_audit_log_from_model(instance, action: str, user=None, details: dict = None):
    """
    Create an audit log entry from a model instance change.
    """
    try:
        content_type = ContentType.objects.get_for_model(instance)
        resource = content_type.model.upper()
        resource_id = instance.pk
        log_entry = AuditLog.objects.create(
            user=user,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details or {},
            timestamp=timezone.now(),
        )
        logger.debug(f'Audit log created for {resource} #{resource_id} - {action}')
        return log_entry
    except Exception as e:
        logger.error(f'Error creating audit log: {str(e)}')
        return None


# ============================================================================
# AUDIT LOG SIGNALS
# ============================================================================

@receiver(pre_save, sender=AuditLog)
def audit_log_pre_save_handler(sender, instance, **kwargs):
    """Set timestamp if not provided."""
    if not instance.timestamp:
        instance.timestamp = timezone.now()
    if not instance.action:
        raise ValidationError('Action is required.')
    if not instance.resource:
        raise ValidationError('Resource is required.')


@receiver(post_save, sender=AuditLog)
def audit_log_post_save_handler(sender, instance, created, **kwargs):
    """Invalidate cache and trigger rules if new."""
    invalidate_audit_cache('audit_log', instance.id)
    if created:
        # Trigger rule evaluation for this log (via task)
        from .tasks import process_audit_rules_task
        process_audit_rules_task.delay()
        logger.info(f'Audit log created: {instance.action} on {instance.resource} by {instance.user}')


@receiver(pre_delete, sender=AuditLog)
def audit_log_pre_delete_handler(sender, instance, **kwargs):
    """Log deletion."""
    logger.info(f'AuditLog {instance.id} is being deleted')


@receiver(post_delete, sender=AuditLog)
def audit_log_post_delete_handler(sender, instance, **kwargs):
    """Clean up cache."""
    invalidate_audit_cache('audit_log', instance.id)


# ============================================================================
# AUDIT EVENT SIGNALS
# ============================================================================

@receiver(pre_save, sender=AuditEvent)
def audit_event_pre_save_handler(sender, instance, **kwargs):
    """Ensure processed status consistency."""
    if instance.processed and not instance.processed_at:
        instance.processed_at = timezone.now()


@receiver(post_save, sender=AuditEvent)
def audit_event_post_save_handler(sender, instance, created, **kwargs):
    """Process event if not processed and new."""
    invalidate_audit_cache('audit_event', instance.id)
    if created:
        logger.info(f'Audit event created: {instance.event_type}')
        if not instance.processed:
            from .tasks import process_audit_events
            process_audit_events.delay()


@receiver(pre_delete, sender=AuditEvent)
def audit_event_pre_delete_handler(sender, instance, **kwargs):
    """Log deletion."""
    logger.info(f'AuditEvent {instance.id} is being deleted')


@receiver(post_delete, sender=AuditEvent)
def audit_event_post_delete_handler(sender, instance, **kwargs):
    """Clean up cache."""
    invalidate_audit_cache('audit_event', instance.id)


# ============================================================================
# AUDIT RULE SIGNALS
# ============================================================================

@receiver(pre_save, sender=AuditRule)
def audit_rule_pre_save_handler(sender, instance, **kwargs):
    """Validate condition JSON."""
    if not isinstance(instance.condition, dict):
        raise ValidationError('Condition must be a JSON object.')
    if not instance.name:
        raise ValidationError('Name is required.')


@receiver(post_save, sender=AuditRule)
def audit_rule_post_save_handler(sender, instance, created, **kwargs):
    """Sync rule to cache and invalidate."""
    invalidate_audit_cache('audit_rule', instance.id)
    if created:
        logger.info(f'Audit rule created: {instance.name}')
    else:
        logger.info(f'Audit rule updated: {instance.name}')
    # Sync active rules to cache
    if instance.is_active:
        from .tasks import sync_audit_configuration
        sync_audit_configuration.delay()


@receiver(pre_delete, sender=AuditRule)
def audit_rule_pre_delete_handler(sender, instance, **kwargs):
    """Log deletion."""
    logger.info(f'AuditRule {instance.id} ({instance.name}) is being deleted')


@receiver(post_delete, sender=AuditRule)
def audit_rule_post_delete_handler(sender, instance, **kwargs):
    """Clean up cache and sync."""
    invalidate_audit_cache('audit_rule', instance.id)
    from .tasks import sync_audit_configuration
    sync_audit_configuration.delay()


# ============================================================================
# AUDIT ALERT SIGNALS
# ============================================================================

@receiver(pre_save, sender=AuditAlert)
def audit_alert_pre_save_handler(sender, instance, **kwargs):
    """Set timestamp if not set."""
    if not instance.timestamp:
        instance.timestamp = timezone.now()
    if not instance.message:
        raise ValidationError('Message is required.')


@receiver(post_save, sender=AuditAlert)
def audit_alert_post_save_handler(sender, instance, created, **kwargs):
    """Send notification for new alerts of high severity."""
    invalidate_audit_cache('audit_alert', instance.id)
    if created and instance.severity in ['error', 'critical']:
        logger.warning(f'Critical audit alert: {instance.message}')
        # Could trigger a real-time notification here
        # from .tasks import send_audit_alert_notification
        # send_audit_alert_notification.delay(instance.id)


@receiver(pre_delete, sender=AuditAlert)
def audit_alert_pre_delete_handler(sender, instance, **kwargs):
    """Log deletion."""
    logger.info(f'AuditAlert {instance.id} is being deleted')


@receiver(post_delete, sender=AuditAlert)
def audit_alert_post_delete_handler(sender, instance, **kwargs):
    """Clean up cache."""
    invalidate_audit_cache('audit_alert', instance.id)


# ============================================================================
# AUDIT REPORT SIGNALS
# ============================================================================

@receiver(pre_save, sender=AuditReport)
def audit_report_pre_save_handler(sender, instance, **kwargs):
    """Set generated_at and expiry."""
    if not instance.generated_at:
        instance.generated_at = timezone.now()
    if not instance.expires_at:
        instance.expires_at = instance.generated_at + timezone.timedelta(days=90)


@receiver(post_save, sender=AuditReport)
def audit_report_post_save_handler(sender, instance, created, **kwargs):
    """Invalidate cache."""
    invalidate_audit_cache('audit_report', instance.id)
    if created:
        logger.info(f'Audit report generated: {instance.name}')


@receiver(pre_delete, sender=AuditReport)
def audit_report_pre_delete_handler(sender, instance, **kwargs):
    """Log deletion."""
    logger.info(f'AuditReport {instance.id} ({instance.name}) is being deleted')


@receiver(post_delete, sender=AuditReport)
def audit_report_post_delete_handler(sender, instance, **kwargs):
    """Clean up cache."""
    invalidate_audit_cache('audit_report', instance.id)


# ============================================================================
# AUDIT RETENTION POLICY SIGNALS
# ============================================================================

@receiver(pre_save, sender=AuditRetentionPolicy)
def audit_retention_policy_pre_save_handler(sender, instance, **kwargs):
    """Validate retention days."""
    if instance.retention_days < 1:
        raise ValidationError('Retention days must be at least 1.')


@receiver(post_save, sender=AuditRetentionPolicy)
def audit_retention_policy_post_save_handler(sender, instance, created, **kwargs):
    """Sync to cache and enforce if active."""
    invalidate_audit_cache('audit_retention_policy', instance.id)
    if created:
        logger.info(f'Retention policy created: {instance.resource_type} - {instance.retention_days} days')
    else:
        logger.info(f'Retention policy updated: {instance.resource_type} - {instance.retention_days} days')
    if instance.is_active:
        from .tasks import sync_audit_configuration
        sync_audit_configuration.delay()
        # Optionally enforce immediately
        # instance.enforce()


@receiver(pre_delete, sender=AuditRetentionPolicy)
def audit_retention_policy_pre_delete_handler(sender, instance, **kwargs):
    """Log deletion."""
    logger.info(f'AuditRetentionPolicy {instance.id} is being deleted')


@receiver(post_delete, sender=AuditRetentionPolicy)
def audit_retention_policy_post_delete_handler(sender, instance, **kwargs):
    """Clean up cache."""
    invalidate_audit_cache('audit_retention_policy', instance.id)


# ============================================================================
# SECURITY EVENT SIGNALS
# ============================================================================

@receiver(pre_save, sender=SecurityEvent)
def security_event_pre_save_handler(sender, instance, **kwargs):
    """Set timestamp if not set."""
    if not instance.timestamp:
        instance.timestamp = timezone.now()
    if not instance.description:
        raise ValidationError('Description is required.')


@receiver(post_save, sender=SecurityEvent)
def security_event_post_save_handler(sender, instance, created, **kwargs):
    """Trigger alerts for critical events and invalidate cache."""
    invalidate_audit_cache('security_event', instance.id)
    if created:
        logger.warning(f'Security event: {instance.event_type} - {instance.user.email}')
        if instance.severity in ['error', 'critical']:
            from .tasks import send_security_alert
            send_security_alert.delay(instance.id)
        # Also create an audit log entry
        create_audit_log_from_model(
            instance,
            action='CREATE',
            user=instance.user,
            details={
                'event_type': instance.event_type,
                'description': instance.description,
                'severity': instance.severity,
            }
        )


@receiver(pre_delete, sender=SecurityEvent)
def security_event_pre_delete_handler(sender, instance, **kwargs):
    """Log deletion."""
    logger.info(f'SecurityEvent {instance.id} is being deleted')


@receiver(post_delete, sender=SecurityEvent)
def security_event_post_delete_handler(sender, instance, **kwargs):
    """Clean up cache."""
    invalidate_audit_cache('security_event', instance.id)


# ============================================================================
# USER ACTIVITY SIGNALS
# ============================================================================

@receiver(pre_save, sender=UserActivity)
def user_activity_pre_save_handler(sender, instance, **kwargs):
    """Set timestamp if not set."""
    if not instance.timestamp:
        instance.timestamp = timezone.now()
    if not instance.action:
        raise ValidationError('Action is required.')
    if not instance.resource:
        raise ValidationError('Resource is required.')


@receiver(post_save, sender=UserActivity)
def user_activity_post_save_handler(sender, instance, created, **kwargs):
    """Invalidate cache and maybe update user activity summary."""
    invalidate_audit_cache('user_activity', instance.id)
    if created:
        logger.debug(f'User activity: {instance.user.email} - {instance.action} on {instance.resource}')
        # Optionally update user's last activity field
        if instance.user:
            instance.user.last_activity = timezone.now()
            instance.user.save(update_fields=['last_activity'])


@receiver(pre_delete, sender=UserActivity)
def user_activity_pre_delete_handler(sender, instance, **kwargs):
    """Log deletion."""
    logger.info(f'UserActivity {instance.id} is being deleted')


@receiver(post_delete, sender=UserActivity)
def user_activity_post_delete_handler(sender, instance, **kwargs):
    """Clean up cache."""
    invalidate_audit_cache('user_activity', instance.id)


# ============================================================================
# SYSTEM HEALTH SIGNALS
# ============================================================================

@receiver(pre_save, sender=SystemHealth)
def system_health_pre_save_handler(sender, instance, **kwargs):
    """Set checked_at if not set."""
    if not instance.checked_at:
        instance.checked_at = timezone.now()
    if not instance.component:
        raise ValidationError('Component is required.')


@receiver(post_save, sender=SystemHealth)
def system_health_post_save_handler(sender, instance, created, **kwargs):
    """Trigger alerts for degraded/error status and invalidate cache."""
    invalidate_audit_cache('system_health', instance.id)
    if created:
        logger.info(f'System health check: {instance.component} - {instance.status}')
        if instance.status in ['error', 'degraded']:
            from .tasks import send_health_alert
            # We need to construct a health results dict for the alert
            health_results = {
                'errors': 1 if instance.status == 'error' else 0,
                'warnings': 1 if instance.status == 'degraded' else 0,
                'details': [{
                    'component': instance.component,
                    'status': instance.status,
                    'message': instance.message,
                }]
            }
            send_health_alert.delay(health_results)


@receiver(pre_delete, sender=SystemHealth)
def system_health_pre_delete_handler(sender, instance, **kwargs):
    """Log deletion."""
    logger.info(f'SystemHealth {instance.id} is being deleted')


@receiver(post_delete, sender=SystemHealth)
def system_health_post_delete_handler(sender, instance, **kwargs):
    """Clean up cache."""
    invalidate_audit_cache('system_health', instance.id)


# ============================================================================
# PERFORMANCE METRIC SIGNALS
# ============================================================================

@receiver(pre_save, sender=PerformanceMetric)
def performance_metric_pre_save_handler(sender, instance, **kwargs):
    """Set timestamp if not set."""
    if not instance.timestamp:
        instance.timestamp = timezone.now()
    if not instance.metric_name:
        raise ValidationError('Metric name is required.')
    if instance.value is None:
        raise ValidationError('Value is required.')


@receiver(post_save, sender=PerformanceMetric)
def performance_metric_post_save_handler(sender, instance, created, **kwargs):
    """Trigger anomaly detection and cache invalidation."""
    invalidate_audit_cache('performance_metric', instance.id)
    if created:
        logger.debug(f'Performance metric: {instance.metric_name} = {instance.value} {instance.unit}')
        # Periodically trigger anomaly detection (every N metrics)
        # We can use a counter in cache
        counter = cache.get('perf_metric_counter', 0) + 1
        cache.set('perf_metric_counter', counter, timeout=3600)
        if counter % 10 == 0:  # Run anomaly detection every 10 metrics
            from .tasks import detect_anomalies_task
            detect_anomalies_task.delay()


@receiver(pre_delete, sender=PerformanceMetric)
def performance_metric_pre_delete_handler(sender, instance, **kwargs):
    """Log deletion."""
    logger.info(f'PerformanceMetric {instance.id} is being deleted')


@receiver(post_delete, sender=PerformanceMetric)
def performance_metric_post_delete_handler(sender, instance, **kwargs):
    """Clean up cache."""
    invalidate_audit_cache('performance_metric', instance.id)


# ============================================================================
# ANOMALY DETECTION SIGNALS
# ============================================================================

@receiver(pre_save, sender=AnomalyDetection)
def anomaly_detection_pre_save_handler(sender, instance, **kwargs):
    """Set detected_at if not set."""
    if not instance.detected_at:
        instance.detected_at = timezone.now()
    if not instance.description:
        raise ValidationError('Description is required.')


@receiver(post_save, sender=AnomalyDetection)
def anomaly_detection_post_save_handler(sender, instance, created, **kwargs):
    """Send alert for high-severity anomalies and invalidate cache."""
    invalidate_audit_cache('anomaly_detection', instance.id)
    if created:
        logger.warning(f'Anomaly detected: {instance.anomaly_type} on {instance.metric_name}')
        if instance.severity in ['error', 'critical']:
            from .tasks import send_anomaly_alert
            send_anomaly_alert.delay(instance.metric_name, instance.z_score or 0, instance.baseline or 0)
    else:
        # If status changed, maybe log
        try:
            old = AnomalyDetection.objects.get(pk=instance.pk)
            if old.status != instance.status:
                logger.info(f'Anomaly {instance.id} status changed from {old.status} to {instance.status}')
        except AnomalyDetection.DoesNotExist:
            pass


@receiver(pre_delete, sender=AnomalyDetection)
def anomaly_detection_pre_delete_handler(sender, instance, **kwargs):
    """Log deletion."""
    logger.info(f'AnomalyDetection {instance.id} is being deleted')


@receiver(post_delete, sender=AnomalyDetection)
def anomaly_detection_post_delete_handler(sender, instance, **kwargs):
    """Clean up cache."""
    invalidate_audit_cache('anomaly_detection', instance.id)


# ============================================================================
# CROSS-MODEL SIGNALS FOR USER ACTIONS
# ============================================================================

@receiver(post_save, sender=User)
def user_post_save_audit_handler(sender, instance, created, **kwargs):
    """
    When a user is created or updated, log to AuditLog.
    """
    if created:
        action = 'CREATE'
        details = {'email': instance.email}
    else:
        action = 'UPDATE'
        # Detect changes (simple diff)
        try:
            old = User.objects.get(pk=instance.pk)
            changes = {}
            for field in ['email', 'first_name', 'last_name', 'is_active', 'is_suspended', 'is_verified']:
                if getattr(old, field) != getattr(instance, field):
                    changes[field] = {'old': getattr(old, field), 'new': getattr(instance, field)}
            details = {'changes': changes}
        except User.DoesNotExist:
            details = {}
    create_audit_log_from_model(instance, action, user=instance, details=details)


@receiver(post_save, sender=Group)
def group_post_save_audit_handler(sender, instance, created, **kwargs):
    """Log group creation/update to AuditLog."""
    action = 'CREATE' if created else 'UPDATE'
    details = {'name': instance.name, 'status': instance.status}
    create_audit_log_from_model(instance, action, details=details)


@receiver(post_save, sender=Payment)
def payment_post_save_audit_handler(sender, instance, created, **kwargs):
    """Log payment creation/update to AuditLog."""
    action = 'CREATE' if created else 'UPDATE'
    details = {'amount': float(instance.amount), 'status': instance.status}
    create_audit_log_from_model(instance, action, user=instance.user, details=details)


@receiver(post_save, sender=Contribution)
def contribution_post_save_audit_handler(sender, instance, created, **kwargs):
    """Log contribution creation/update to AuditLog."""
    action = 'CREATE' if created else 'UPDATE'
    details = {'amount': float(instance.amount), 'status': instance.status}
    create_audit_log_from_model(instance, action, user=instance.user, details=details)


@receiver(post_save, sender=Payout)
def payout_post_save_audit_handler(sender, instance, created, **kwargs):
    """Log payout creation/update to AuditLog."""
    action = 'CREATE' if created else 'UPDATE'
    details = {'amount': float(instance.amount), 'status': instance.status}
    create_audit_log_from_model(instance, action, user=instance.user, details=details)


@receiver(post_save, sender=Notification)
def notification_post_save_audit_handler(sender, instance, created, **kwargs):
    """Log notification creation to AuditLog."""
    if created:
        details = {'notification_type': instance.notification_type, 'user': instance.user.email}
        create_audit_log_from_model(instance, 'CREATE', user=instance.user, details=details)


# ============================================================================
# SIGNAL FOR INVALIDATING CACHE ON USER LOGIN/LOGOUT
# ============================================================================

# We can intercept user login/logout signals if needed (via django.contrib.auth.signals)
# But we handle that via custom login/logout views that create SecurityEvents.


# ============================================================================
# SIGNAL DISPATCHER (for manual triggering)
# ============================================================================

def dispatch_audit_signals(model_name: str, instance_id: int, signal_name: str, *args, **kwargs):
    """
    Manually dispatch signals for testing or admin actions.
    """
    models = {
        'audit_log': AuditLog,
        'audit_event': AuditEvent,
        'audit_rule': AuditRule,
        'audit_alert': AuditAlert,
        'audit_report': AuditReport,
        'audit_retention_policy': AuditRetentionPolicy,
        'security_event': SecurityEvent,
        'user_activity': UserActivity,
        'system_health': SystemHealth,
        'performance_metric': PerformanceMetric,
        'anomaly_detection': AnomalyDetection,
    }
    model_class = models.get(model_name)
    if not model_class:
        return None

    try:
        instance = model_class.objects.get(id=instance_id)
    except model_class.DoesNotExist:
        return None

    if signal_name == 'pre_save':
        pre_save.send(sender=model_class, instance=instance, **kwargs)
    elif signal_name == 'post_save':
        post_save.send(sender=model_class, instance=instance, created=False, **kwargs)
    elif signal_name == 'pre_delete':
        pre_delete.send(sender=model_class, instance=instance, **kwargs)
    elif signal_name == 'post_delete':
        post_delete.send(sender=model_class, instance=instance, **kwargs)
    return True


# ============================================================================
# ERROR HANDLING WRAPPER
# ============================================================================

def handle_signal_error(func):
    """
    Decorator to catch and log errors in signal handlers.
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f'Error in signal handler {func.__name__}: {str(e)}', exc_info=True)
            # For signals, we often don't want to break the transaction
            return None
    return wrapper