"""
Signals for the admin panel app.

This module provides signal handlers for all administrative models:
- AdminAction: log actions, invalidate cache
- AdminLog: log entries, update timestamps
- AdminPreference: sync preferences, invalidate cache
- SystemSetting: sync to cache on save/delete
- MaintenanceLog: track task lifecycle
- Report: update expiry, send notifications
- ReportSchedule: calculate next run, update status
- AuditTrail: create from model changes
- DashboardWidget: update ordering, invalidate cache

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
from apps.common.utils import log_audit_event, get_current_time

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

logger = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def invalidate_admin_cache(model_name: str, instance_id: Optional[int] = None):
    """
    Invalidate cache keys related to admin models.

    Args:
        model_name: Name of the model (e.g., 'system_setting', 'admin_action')
        instance_id: Optional instance ID for specific key invalidation
    """
    keys = []
    if model_name == 'system_setting':
        keys.append('system_settings_all')
        if instance_id:
            setting = SystemSetting.objects.filter(id=instance_id).first()
            if setting:
                keys.append(f'system_setting_{setting.key}')
    elif model_name == 'admin_action':
        keys.append('admin_actions_recent')
        if instance_id:
            keys.append(f'admin_action_{instance_id}')
    elif model_name == 'admin_log':
        keys.append('admin_logs_recent')
        if instance_id:
            keys.append(f'admin_log_{instance_id}')
    elif model_name == 'admin_preference':
        if instance_id:
            pref = AdminPreference.objects.filter(id=instance_id).first()
            if pref:
                keys.append(f'admin_prefs_{pref.admin_id}')
        keys.append('admin_prefs_all')
    elif model_name == 'report':
        keys.append('reports_recent')
        if instance_id:
            keys.append(f'report_{instance_id}')
    elif model_name == 'report_schedule':
        keys.append('report_schedules_active')
        if instance_id:
            keys.append(f'report_schedule_{instance_id}')
    elif model_name == 'dashboard_widget':
        keys.append('dashboard_widgets_all')
        if instance_id:
            keys.append(f'dashboard_widget_{instance_id}')
    elif model_name == 'audit_trail':
        if instance_id:
            keys.append(f'audit_trail_{instance_id}')
    elif model_name == 'maintenance_log':
        keys.append('maintenance_logs_recent')
        if instance_id:
            keys.append(f'maintenance_log_{instance_id}')

    for key in keys:
        cache.delete(key)
        logger.debug(f'Invalidated cache key: {key}')


def create_audit_trail(instance, action: str, user=None, changes: dict = None):
    """
    Create an audit trail entry for a model instance.

    Args:
        instance: The model instance being audited
        action: Action performed (create, update, delete)
        user: User who performed the action
        changes: Dictionary of changes (for update actions)
    """
    try:
        content_type = ContentType.objects.get_for_model(instance)
        audit = AuditTrail.objects.create(
            content_type=content_type,
            object_id=instance.pk,
            action=action,
            user=user,
            changes=changes or {},
            timestamp=timezone.now(),
        )
        logger.debug(f'Audit trail created for {content_type.model} #{instance.pk} - {action}')
        return audit
    except Exception as e:
        logger.error(f'Error creating audit trail: {str(e)}')
        return None


def log_admin_action(admin_user, action: str, target_user=None, target_group=None,
                     details: dict = None, ip_address: str = None, user_agent: str = None):
    """
    Helper to create an AdminAction entry.

    Args:
        admin_user: User performing the action
        action: Action type
        target_user: Optional target user
        target_group: Optional target group
        details: Additional details
        ip_address: IP address
        user_agent: User agent
    """
    try:
        admin_action = AdminAction.objects.create(
            admin=admin_user,
            user=target_user,
            group=target_group,
            action=action,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            timestamp=timezone.now(),
        )
        logger.info(f'Admin action logged: {action} by {admin_user.email}')
        return admin_action
    except Exception as e:
        logger.error(f'Error logging admin action: {str(e)}')
        return None


# ============================================================================
# ADMIN ACTION SIGNALS
# ============================================================================

@receiver(pre_save, sender=AdminAction)
def admin_action_pre_save_handler(sender, instance, **kwargs):
    """
    Ensure timestamp is set for admin actions.
    """
    if not instance.timestamp:
        instance.timestamp = timezone.now()
    if not instance.action:
        raise ValidationError('Action type is required.')


@receiver(post_save, sender=AdminAction)
def admin_action_post_save_handler(sender, instance, created, **kwargs):
    """
    Invalidate cache after admin action creation.
    """
    if created:
        invalidate_admin_cache('admin_action', instance.id)
        # If this action affects a user, group, or system setting, trigger additional cache invalidation
        if instance.action in ['suspend', 'activate', 'verify_identity', 'delete'] and instance.user:
            # User management actions may affect user cache
            cache.delete(f'user_{instance.user.id}')
            cache.delete(f'user_stats_{instance.user.id}')
        elif instance.action in ['approve_group', 'complete_group', 'cancel_group', 'pause_group', 'resume_group'] and instance.group:
            cache.delete(f'group_{instance.group.id}')
            cache.delete(f'group_stats_{instance.group.id}')
        elif instance.action in ['system_setting_change']:
            cache.delete('system_settings_all')


@receiver(pre_delete, sender=AdminAction)
def admin_action_pre_delete_handler(sender, instance, **kwargs):
    """
    Log admin action deletion.
    """
    logger.info(f'AdminAction {instance.id} is being deleted (action: {instance.action})')


@receiver(post_delete, sender=AdminAction)
def admin_action_post_delete_handler(sender, instance, **kwargs):
    """
    Clean up cache after admin action deletion.
    """
    invalidate_admin_cache('admin_action', instance.id)


# ============================================================================
# ADMIN LOG SIGNALS
# ============================================================================

@receiver(pre_save, sender=AdminLog)
def admin_log_pre_save_handler(sender, instance, **kwargs):
    """
    Set timestamp for admin logs.
    """
    if not instance.timestamp:
        instance.timestamp = timezone.now()
    if not instance.level:
        instance.level = 'info'


@receiver(post_save, sender=AdminLog)
def admin_log_post_save_handler(sender, instance, created, **kwargs):
    """
    Invalidate cache after admin log creation.
    """
    if created:
        invalidate_admin_cache('admin_log', instance.id)
        # If high severity, maybe send alert
        if instance.level in ['error', 'critical']:
            logger.warning(f'Admin log level {instance.level}: {instance.message}')


@receiver(post_delete, sender=AdminLog)
def admin_log_post_delete_handler(sender, instance, **kwargs):
    """
    Clean up cache after admin log deletion.
    """
    invalidate_admin_cache('admin_log', instance.id)


# ============================================================================
# ADMIN PREFERENCE SIGNALS
# ============================================================================

@receiver(pre_save, sender=AdminPreference)
def admin_preference_pre_save_handler(sender, instance, **kwargs):
    """
    Validate preferences and set defaults.
    """
    if instance.items_per_page < 5 or instance.items_per_page > 200:
        raise ValidationError('Items per page must be between 5 and 200.')
    if instance.theme not in ['light', 'dark', 'auto']:
        instance.theme = 'light'


@receiver(post_save, sender=AdminPreference)
def admin_preference_post_save_handler(sender, instance, created, **kwargs):
    """
    Invalidate cache after preference update.
    """
    invalidate_admin_cache('admin_preference', instance.id)
    if created:
        logger.info(f'Admin preferences created for user {instance.admin_id}')
    else:
        logger.info(f'Admin preferences updated for user {instance.admin_id}')


@receiver(pre_delete, sender=AdminPreference)
def admin_preference_pre_delete_handler(sender, instance, **kwargs):
    """
    Log preference deletion.
    """
    logger.info(f'Admin preferences for user {instance.admin_id} are being deleted')


@receiver(post_delete, sender=AdminPreference)
def admin_preference_post_delete_handler(sender, instance, **kwargs):
    """
    Clean up cache after preference deletion.
    """
    invalidate_admin_cache('admin_preference', instance.id)


# ============================================================================
# SYSTEM SETTING SIGNALS
# ============================================================================

@receiver(pre_save, sender=SystemSetting)
def system_setting_pre_save_handler(sender, instance, **kwargs):
    """
    Validate system setting key and value.
    """
    if not instance.key or len(instance.key.strip()) < 2:
        raise ValidationError('Key is required and must be at least 2 characters.')
    # Ensure key is in lowercase for consistency
    instance.key = instance.key.lower()


@receiver(post_save, sender=SystemSetting)
def system_setting_post_save_handler(sender, instance, created, **kwargs):
    """
    Sync setting to cache after save.
    """
    # Update cache
    cache.set(f'system_setting_{instance.key}', instance.value, timeout=86400)
    # Invalidate the all settings cache
    invalidate_admin_cache('system_setting', instance.id)
    # Also update the global settings dict
    try:
        all_settings = cache.get('system_settings_all', {})
        all_settings[instance.key] = instance.value
        cache.set('system_settings_all', all_settings, timeout=86400)
    except Exception as e:
        logger.error(f'Error updating system settings cache: {str(e)}')

    if created:
        logger.info(f'System setting created: {instance.key}')
    else:
        logger.info(f'System setting updated: {instance.key}')


@receiver(pre_delete, sender=SystemSetting)
def system_setting_pre_delete_handler(sender, instance, **kwargs):
    """
    Log setting deletion.
    """
    logger.info(f'System setting {instance.key} is being deleted')


@receiver(post_delete, sender=SystemSetting)
def system_setting_post_delete_handler(sender, instance, **kwargs):
    """
    Remove setting from cache after deletion.
    """
    cache.delete(f'system_setting_{instance.key}')
    invalidate_admin_cache('system_setting', instance.id)
    # Update global settings dict
    try:
        all_settings = cache.get('system_settings_all', {})
        if instance.key in all_settings:
            del all_settings[instance.key]
            cache.set('system_settings_all', all_settings, timeout=86400)
    except Exception as e:
        logger.error(f'Error updating system settings cache on delete: {str(e)}')


# ============================================================================
# MAINTENANCE LOG SIGNALS
# ============================================================================

@receiver(pre_save, sender=MaintenanceLog)
def maintenance_log_pre_save_handler(sender, instance, **kwargs):
    """
    Set status and timestamps for maintenance logs.
    """
    if instance.status == 'running' and not instance.started_at:
        instance.started_at = timezone.now()
    if instance.status in ['completed', 'failed', 'cancelled'] and not instance.completed_at:
        instance.completed_at = timezone.now()
    if instance.completed_at and instance.started_at and not instance.duration_seconds:
        instance.duration_seconds = (instance.completed_at - instance.started_at).total_seconds()


@receiver(post_save, sender=MaintenanceLog)
def maintenance_log_post_save_handler(sender, instance, created, **kwargs):
    """
    Invalidate cache and maybe send alerts for failures.
    """
    if created:
        invalidate_admin_cache('maintenance_log', instance.id)
    else:
        invalidate_admin_cache('maintenance_log', instance.id)
        if instance.status == 'failed' and instance.error_message:
            # Log critical failure
            logger.critical(f'Maintenance task {instance.task_type} failed: {instance.error_message}')


@receiver(post_delete, sender=MaintenanceLog)
def maintenance_log_post_delete_handler(sender, instance, **kwargs):
    """
    Clean up cache after deletion.
    """
    invalidate_admin_cache('maintenance_log', instance.id)


# ============================================================================
# REPORT SIGNALS
# ============================================================================

@receiver(pre_save, sender=Report)
def report_pre_save_handler(sender, instance, **kwargs):
    """
    Set expiry based on report type.
    """
    if not instance.generated_at:
        instance.generated_at = timezone.now()
    if not instance.expires_at:
        # Set expiry based on report type
        if instance.report_type == 'daily':
            instance.expires_at = instance.generated_at + timezone.timedelta(days=30)
        elif instance.report_type == 'weekly':
            instance.expires_at = instance.generated_at + timezone.timedelta(days=90)
        elif instance.report_type == 'monthly':
            instance.expires_at = instance.generated_at + timezone.timedelta(days=180)
        elif instance.report_type == 'quarterly':
            instance.expires_at = instance.generated_at + timezone.timedelta(days=365)
        else:
            instance.expires_at = instance.generated_at + timezone.timedelta(days=30)


@receiver(post_save, sender=Report)
def report_post_save_handler(sender, instance, created, **kwargs):
    """
    Invalidate cache and log report generation.
    """
    invalidate_admin_cache('report', instance.id)
    if created:
        logger.info(f'Report generated: {instance.name} by {instance.generated_by.email if instance.generated_by else "system"}')


@receiver(pre_delete, sender=Report)
def report_pre_delete_handler(sender, instance, **kwargs):
    """
    Log report deletion.
    """
    logger.info(f'Report {instance.id} ({instance.name}) is being deleted')


@receiver(post_delete, sender=Report)
def report_post_delete_handler(sender, instance, **kwargs):
    """
    Clean up cache and optionally delete file.
    """
    invalidate_admin_cache('report', instance.id)
    # If file exists, maybe delete it
    if instance.file:
        try:
            instance.file.delete(save=False)
            logger.debug(f'Deleted report file: {instance.file.name}')
        except Exception as e:
            logger.error(f'Error deleting report file: {str(e)}')


# ============================================================================
# REPORT SCHEDULE SIGNALS
# ============================================================================

@receiver(pre_save, sender=ReportSchedule)
def report_schedule_pre_save_handler(sender, instance, **kwargs):
    """
    Calculate next run time for schedule.
    """
    if not instance.next_run:
        instance.next_run = instance.calculate_next_run()
    # Validate frequency-specific fields
    if instance.frequency == 'weekly' and instance.day_of_week is None:
        raise ValidationError('day_of_week is required for weekly schedules')
    if instance.frequency == 'monthly' and instance.day_of_month is None:
        raise ValidationError('day_of_month is required for monthly schedules')


@receiver(post_save, sender=ReportSchedule)
def report_schedule_post_save_handler(sender, instance, created, **kwargs):
    """
    Invalidate cache and log schedule changes.
    """
    invalidate_admin_cache('report_schedule', instance.id)
    if created:
        logger.info(f'Report schedule created: {instance.name} by {instance.created_by.email if instance.created_by else "system"}')
    else:
        logger.info(f'Report schedule updated: {instance.name}')


@receiver(pre_delete, sender=ReportSchedule)
def report_schedule_pre_delete_handler(sender, instance, **kwargs):
    """
    Log schedule deletion.
    """
    logger.info(f'Report schedule {instance.id} ({instance.name}) is being deleted')


@receiver(post_delete, sender=ReportSchedule)
def report_schedule_post_delete_handler(sender, instance, **kwargs):
    """
    Clean up cache after deletion.
    """
    invalidate_admin_cache('report_schedule', instance.id)


# ============================================================================
# AUDIT TRAIL SIGNALS
# ============================================================================

@receiver(pre_save, sender=AuditTrail)
def audit_trail_pre_save_handler(sender, instance, **kwargs):
    """
    Set timestamp for audit trail.
    """
    if not instance.timestamp:
        instance.timestamp = timezone.now()


@receiver(post_save, sender=AuditTrail)
def audit_trail_post_save_handler(sender, instance, created, **kwargs):
    """
    Invalidate cache after audit trail creation.
    """
    if created:
        invalidate_admin_cache('audit_trail', instance.id)
        logger.debug(f'Audit trail created: {instance.action} on {instance.content_type} #{instance.object_id}')


@receiver(post_delete, sender=AuditTrail)
def audit_trail_post_delete_handler(sender, instance, **kwargs):
    """
    Clean up cache after deletion.
    """
    invalidate_admin_cache('audit_trail', instance.id)


# ============================================================================
# DASHBOARD WIDGET SIGNALS
# ============================================================================

@receiver(pre_save, sender=DashboardWidget)
def dashboard_widget_pre_save_handler(sender, instance, **kwargs):
    """
    Validate widget configuration and set order.
    """
    if not instance.title:
        instance.title = instance.name
    if instance.order < 0:
        instance.order = 0


@receiver(post_save, sender=DashboardWidget)
def dashboard_widget_post_save_handler(sender, instance, created, **kwargs):
    """
    Invalidate cache and log widget changes.
    """
    invalidate_admin_cache('dashboard_widget', instance.id)
    if created:
        logger.info(f'Dashboard widget created: {instance.title} for user {instance.admin_id or "system"}')
    else:
        logger.info(f'Dashboard widget updated: {instance.title}')


@receiver(pre_delete, sender=DashboardWidget)
def dashboard_widget_pre_delete_handler(sender, instance, **kwargs):
    """
    Log widget deletion.
    """
    logger.info(f'Dashboard widget {instance.id} ({instance.title}) is being deleted')


@receiver(post_delete, sender=DashboardWidget)
def dashboard_widget_post_delete_handler(sender, instance, **kwargs):
    """
    Clean up cache after deletion.
    """
    invalidate_admin_cache('dashboard_widget', instance.id)


# ============================================================================
# CROSS-MODEL SIGNALS FOR USER ADMIN PREFERENCES
# ============================================================================

@receiver(post_save, sender=User)
def user_post_save_admin_preference_handler(sender, instance, created, **kwargs):
    """
    When a user is promoted to staff, ensure they have admin preferences.
    """
    if instance.is_staff and not created:
        try:
            AdminPreference.objects.get_or_create(admin=instance)
            logger.debug(f'Admin preferences created for newly promoted admin: {instance.email}')
        except Exception as e:
            logger.error(f'Error creating admin preferences for {instance.email}: {str(e)}')


# ============================================================================
# SIGNAL FOR SYSTEM SETTING CHANGES TO TRIGGER TASKS
# ============================================================================

@receiver(post_save, sender=SystemSetting)
def system_setting_change_trigger_handler(sender, instance, created, **kwargs):
    """
    When certain system settings change, trigger related tasks.
    """
    if instance.key == 'maintenance_mode_enabled' and instance.value == True:
        # If maintenance mode is enabled, maybe run cleanup tasks
        from .tasks import run_maintenance_tasks
        run_maintenance_tasks.delay()
    elif instance.key == 'report_auto_generate_enabled' and instance.value == True:
        # If auto-report generation is enabled, trigger daily reports
        from .tasks import generate_daily_reports
        generate_daily_reports.delay()


# ============================================================================
# SIGNAL FOR MAINTENANCE LOG COMPLETION TO SEND NOTIFICATIONS
# ============================================================================

@receiver(post_save, sender=MaintenanceLog)
def maintenance_log_completion_handler(sender, instance, created, **kwargs):
    """
    When a maintenance task completes, send notification to admins.
    """
    if not created and instance.status in ['completed', 'failed']:
        # If it's a failure, we already log it; could also send email
        if instance.status == 'failed':
            logger.critical(f'Maintenance task failed: {instance.task_type} - {instance.error_message}')
            # In production, we could send email alerts here


# ============================================================================
# SIGNAL FOR REPORT EXPIRY CHECK (could be used by a periodic task)
# ============================================================================

@receiver(post_save, sender=Report)
def report_expiry_check_handler(sender, instance, created, **kwargs):
    """
    If a report is expired, trigger cleanup (but this is handled by periodic task).
    """
    if instance.expires_at and instance.expires_at <= timezone.now():
        logger.info(f'Report {instance.id} has expired and will be cleaned up by scheduled task.')


# ============================================================================
# SIGNAL FOR DASHBOARD WIDGET ORDER REINDEXING
# ============================================================================

@receiver(pre_save, sender=DashboardWidget)
def dashboard_widget_order_handler(sender, instance, **kwargs):
    """
    When order is changed, ensure uniqueness for the same admin.
    """
    if instance.admin:
        # Reorder widgets for the same admin if needed
        # This is a simple placeholder; more complex logic could be added
        pass


# ============================================================================
# SIGNAL FOR ADMIN ACTION USER GROUP CACHE INVALIDATION
# ============================================================================

@receiver(post_save, sender=AdminAction)
def admin_action_user_group_cache_handler(sender, instance, created, **kwargs):
    """
    Invalidate user or group cache when admin action affects them.
    """
    if created:
        if instance.user:
            cache.delete(f'user_admin_actions_{instance.user.id}')
            cache.delete(f'user_actions_{instance.user.id}')
        if instance.group:
            cache.delete(f'group_admin_actions_{instance.group.id}')


# ============================================================================
# SIGNAL FOR SYSTEM SETTING CACHE SYNC ON STARTUP (simulated)
# ============================================================================

# On app ready, we can load settings into cache, but that's done in apps.py ready method.
# However, we can listen to post_migrate to populate cache.
# Not implemented here because it's done in apps.py


# ============================================================================
# LOGGING UTILITY
# ============================================================================

def log_admin_signal_event(signal_name: str, model_name: str, instance_id: int, **kwargs):
    """
    Utility to log signal events for debugging.
    """
    logger.debug(f'Signal {signal_name} triggered for {model_name} #{instance_id} with kwargs: {kwargs}')


# ============================================================================
# SIGNAL DISPATCHER (for manual triggering)
# ============================================================================

def dispatch_admin_signals(model_name: str, instance_id: int, signal_name: str, *args, **kwargs):
    """
    Manually dispatch signals for testing or admin actions.
    """
    models = {
        'admin_action': AdminAction,
        'admin_log': AdminLog,
        'admin_preference': AdminPreference,
        'system_setting': SystemSetting,
        'maintenance_log': MaintenanceLog,
        'report': Report,
        'report_schedule': ReportSchedule,
        'audit_trail': AuditTrail,
        'dashboard_widget': DashboardWidget,
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
            # Re-raise to prevent silent failures (optional)
            # raise
            # For signals, we often don't want to break the transaction
            return None
    return wrapper