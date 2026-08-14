"""
Signals for the notifications app.

This module provides signal handlers for all notification-related models:
- Notification: handle creation, read status changes, and cleanup
- NotificationTemplate: handle template changes
- NotificationPreference: handle preference updates and cache invalidation
- NotificationChannel: handle channel changes
- NotificationDelivery: handle delivery status updates
- NotificationEvent: handle event processing triggers
- NotificationSchedule: handle schedule execution triggers
- NotificationDigest: handle digest creation and sending
- NotificationAudit: handle audit trail creation

All signal handlers include comprehensive logging, error handling,
cache invalidation, and integration with user/group statistics.
"""

import logging
import json
from django.db.models.signals import post_save, pre_save, pre_delete, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum, Count, F
from decimal import Decimal

from apps.users.models import User
from apps.groups.models import Group
from apps.common.utils import log_audit_event, get_current_time
from apps.common.constants import NotificationType, NotificationChannel, NotificationPriority

from .models import (
    Notification,
    NotificationTemplate,
    NotificationPreference,
    NotificationChannel,
    NotificationDelivery,
    NotificationEvent,
    NotificationSchedule,
    NotificationDigest,
    NotificationAudit,
)
from .tasks import send_notification, process_scheduled_notifications

logger = logging.getLogger(__name__)


# ============================================================================
# NOTIFICATION SIGNALS
# ============================================================================

@receiver(pre_save, sender=Notification)
def notification_pre_save_handler(sender, instance, **kwargs):
    """
    Handle pre-save events for Notification model:
    - Set sent_at and delivered_at if not set
    - Set expires_at for urgent notifications
    - Validate status changes (read/unread)
    """
    # Set sent_at if not set
    if not instance.sent_at:
        instance.sent_at = timezone.now()
    if not instance.delivered_at and instance.sent_at:
        instance.delivered_at = instance.sent_at

    # Set expiry for urgent notifications
    if not instance.expires_at and instance.priority == NotificationPriority.URGENT:
        instance.expires_at = timezone.now() + timezone.timedelta(days=7)

    # Validate read status change
    if instance.pk:
        try:
            old = Notification.objects.get(pk=instance.pk)
            if old.is_read != instance.is_read:
                if instance.is_read and not instance.read_at:
                    instance.read_at = timezone.now()
                elif not instance.is_read:
                    instance.read_at = None
                logger.info(f'Notification {instance.id} read status changed to {instance.is_read}')
        except Notification.DoesNotExist:
            pass


@receiver(post_save, sender=Notification)
def notification_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for Notification model:
    - Invalidate cache
    - Update user notification statistics
    - Create audit entry for new notifications
    - Trigger delivery if needed
    - Send real-time notification via WebSocket (if enabled)
    """
    # Invalidate cache
    cache.delete(f'notifications_{instance.user.id}')
    cache.delete(f'notification_count_{instance.user.id}')
    cache.delete(f'notification_unread_{instance.user.id}')
    cache.delete(f'notification_{instance.id}')

    if created:
        logger.info(f'Notification {instance.id} created for user {instance.user.id}')
        log_audit_event(
            user_id=instance.created_by.id if instance.created_by else None,
            action='notification_created',
            resource='notification',
            resource_id=instance.id,
            details={
                'user_id': instance.user.id,
                'notification_type': instance.notification_type,
                'priority': instance.priority,
            }
        )

        # Queue delivery task (if not already sent via the create flow)
        # The create flow may have already sent it, but we can safely trigger again (idempotent)
        # We'll check if the notification was already sent by seeing if sent_at is set
        if not instance.sent_at:
            notification_data = {
                'id': instance.id,
                'user_id': instance.user.id,
                'email': instance.user.email,
                'phone': instance.user.phone,
                'message': instance.message,
                'title': instance.title or '',
                'notification_type': instance.notification_type,
                'group_id': instance.group.id if instance.group else None,
                'object_id': instance.object_id,
                'object_type': instance.object_type,
                'priority': instance.priority,
                'send_email': True,  # Default to sending email; controlled by preferences
                'send_sms': False,
                'send_push': True,
                'send_in_app': True,
            }
            send_notification.delay(notification_data)

        # Update user's unread count cache
        unread_count = Notification.objects.filter(
            user=instance.user,
            is_read=False,
            deleted_at__isnull=True
        ).count()
        cache.set(f'notification_unread_{instance.user.id}', unread_count, timeout=3600)

    else:
        # Check if read status changed
        try:
            old = Notification.objects.get(pk=instance.pk)
            if old.is_read != instance.is_read:
                log_audit_event(
                    user_id=instance.created_by.id if instance.created_by else None,
                    action='notification_read_status_changed',
                    resource='notification',
                    resource_id=instance.id,
                    details={
                        'old_read': old.is_read,
                        'new_read': instance.is_read,
                        'read_at': instance.read_at.isoformat() if instance.read_at else None,
                    }
                )
                # Invalidate unread cache
                cache.delete(f'notification_unread_{instance.user.id}')
        except Notification.DoesNotExist:
            pass


@receiver(pre_delete, sender=Notification)
def notification_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for Notification model:
    - Prevent permanent deletion of unread notifications (soft delete only)
    - Log audit event
    """
    if not instance.deleted_at:
        # Soft delete instead of hard delete
        instance.deleted_at = timezone.now()
        instance.save(update_fields=['deleted_at'])
        logger.warning(f'Hard delete attempted on notification {instance.id}, converted to soft delete')
        raise Exception('Use soft delete by setting deleted_at instead of delete()')


@receiver(post_delete, sender=Notification)
def notification_post_delete_handler(sender, instance, **kwargs):
    """
    Handle post-delete events for Notification model:
    - Clean up cache
    - Log audit event
    """
    cache.delete(f'notifications_{instance.user.id}')
    cache.delete(f'notification_count_{instance.user.id}')
    cache.delete(f'notification_unread_{instance.user.id}')
    cache.delete(f'notification_{instance.id}')
    logger.info(f'Notification {instance.id} permanently deleted')


# ============================================================================
# NOTIFICATION TEMPLATE SIGNALS
# ============================================================================

@receiver(pre_save, sender=NotificationTemplate)
def notification_template_pre_save_handler(sender, instance, **kwargs):
    """
    Handle pre-save events for NotificationTemplate model:
    - Validate template name uniqueness (case-insensitive)
    """
    if instance.pk:
        try:
            old = NotificationTemplate.objects.get(pk=instance.pk)
            if old.name.lower() != instance.name.lower():
                # Check for duplicate name
                if NotificationTemplate.objects.filter(name__iexact=instance.name).exclude(pk=instance.pk).exists():
                    raise ValueError(f'Template with name "{instance.name}" already exists')
        except NotificationTemplate.DoesNotExist:
            pass


@receiver(post_save, sender=NotificationTemplate)
def notification_template_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for NotificationTemplate model:
    - Invalidate template cache
    - Log audit event
    """
    cache.delete(f'template_{instance.name}')
    cache.delete(f'templates_{instance.notification_type}')
    cache.delete('templates_all')

    if created:
        logger.info(f'Notification template {instance.id} created: {instance.name}')
        log_audit_event(
            user_id=None,
            action='template_created',
            resource='notification_template',
            resource_id=instance.id,
            details={'name': instance.name, 'type': instance.notification_type}
        )
    else:
        logger.info(f'Notification template {instance.id} updated: {instance.name}')


@receiver(pre_delete, sender=NotificationTemplate)
def notification_template_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for NotificationTemplate model:
    - Prevent deletion of active templates that are in use (optional)
    - Log audit event
    """
    # Check if template is used by any scheduled notifications
    if instance.is_active:
        logger.warning(f'Active template {instance.name} is being deleted')
    log_audit_event(
        user_id=None,
        action='template_deleted',
        resource='notification_template',
        resource_id=instance.id,
        details={'name': instance.name}
    )


# ============================================================================
# NOTIFICATION PREFERENCE SIGNALS
# ============================================================================

@receiver(post_save, sender=NotificationPreference)
def notification_preference_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for NotificationPreference model:
    - Invalidate preference cache
    - Log audit event
    """
    cache.delete(f'preferences_{instance.user.id}')
    cache.delete(f'user_prefs_{instance.user.id}')

    if created:
        logger.info(f'Notification preferences created for user {instance.user.id}')
    else:
        logger.info(f'Notification preferences updated for user {instance.user.id}')


@receiver(pre_delete, sender=NotificationPreference)
def notification_preference_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for NotificationPreference model:
    - Log audit event
    """
    cache.delete(f'preferences_{instance.user.id}')
    cache.delete(f'user_prefs_{instance.user.id}')
    logger.info(f'Notification preferences deleted for user {instance.user.id}')


# ============================================================================
# NOTIFICATION CHANNEL SIGNALS
# ============================================================================

@receiver(post_save, sender=NotificationChannel)
def notification_channel_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for NotificationChannel model:
    - Invalidate channel cache
    - Log audit event
    """
    cache.delete(f'channel_{instance.name}')
    cache.delete('channels_all')

    if created:
        logger.info(f'Notification channel {instance.id} created: {instance.name}')
    else:
        logger.info(f'Notification channel {instance.id} updated: {instance.name}')


@receiver(pre_delete, sender=NotificationChannel)
def notification_channel_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for NotificationChannel model:
    - Log audit event
    """
    cache.delete(f'channel_{instance.name}')
    cache.delete('channels_all')
    logger.info(f'Notification channel {instance.id} deleted: {instance.name}')


# ============================================================================
# NOTIFICATION DELIVERY SIGNALS
# ============================================================================

@receiver(post_save, sender=NotificationDelivery)
def notification_delivery_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for NotificationDelivery model:
    - Invalidate delivery cache
    - Update notification delivery status
    - Log audit event
    """
    cache.delete(f'deliveries_{instance.notification.id}')
    cache.delete(f'delivery_{instance.id}')

    if created:
        logger.debug(f'Notification delivery {instance.id} created for notification {instance.notification.id}')

    # If delivery status changed, update notification
    try:
        old = NotificationDelivery.objects.get(pk=instance.pk)
        if old.status != instance.status:
            logger.info(f'Delivery {instance.id} status changed from {old.status} to {instance.status}')
            # If delivery succeeded, update notification's delivered_at
            if instance.status == 'delivered' and instance.notification.delivered_at is None:
                instance.notification.delivered_at = timezone.now()
                instance.notification.save(update_fields=['delivered_at'])
            # If delivery failed, maybe trigger retry (handled by tasks)
    except NotificationDelivery.DoesNotExist:
        pass


# ============================================================================
# NOTIFICATION EVENT SIGNALS
# ============================================================================

@receiver(post_save, sender=NotificationEvent)
def notification_event_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for NotificationEvent model:
    - Invalidate event cache
    - Trigger event processing if not already processed
    - Log audit event
    """
    cache.delete(f'events_{instance.user.id}')
    cache.delete(f'event_{instance.id}')

    if created:
        logger.info(f'Notification event {instance.id} created: {instance.event_type}')
        log_audit_event(
            user_id=instance.user.id,
            action='event_created',
            resource='notification_event',
            resource_id=instance.id,
            details={'event_type': instance.event_type, 'data': instance.data}
        )

        # Trigger processing if not automatically processed
        if not instance.processed:
            from .tasks import send_event_notifications
            event_data = {
                'event_type': instance.event_type,
                'user_id': instance.user.id,
                'group_id': instance.group.id if instance.group else None,
                'data': instance.data,
            }
            send_event_notifications.delay(event_data)

    else:
        # Check if processed status changed
        try:
            old = NotificationEvent.objects.get(pk=instance.pk)
            if old.processed != instance.processed:
                logger.info(f'Event {instance.id} processed status changed to {instance.processed}')
                if instance.processed and not instance.processed_at:
                    instance.processed_at = timezone.now()
                    instance.save(update_fields=['processed_at'])
        except NotificationEvent.DoesNotExist:
            pass


@receiver(pre_delete, sender=NotificationEvent)
def notification_event_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for NotificationEvent model:
    - Log audit event
    """
    cache.delete(f'events_{instance.user.id}')
    cache.delete(f'event_{instance.id}')
    logger.info(f'Notification event {instance.id} deleted')


# ============================================================================
# NOTIFICATION SCHEDULE SIGNALS
# ============================================================================

@receiver(post_save, sender=NotificationSchedule)
def notification_schedule_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for NotificationSchedule model:
    - Invalidate schedule cache
    - Log audit event
    - Trigger immediate processing if scheduled for now
    """
    cache.delete(f'schedules_{instance.notification.user.id}')
    cache.delete(f'schedule_{instance.id}')

    if created:
        logger.info(f'Notification schedule {instance.id} created for notification {instance.notification.id}')
        log_audit_event(
            user_id=instance.notification.user.id,
            action='schedule_created',
            resource='notification_schedule',
            resource_id=instance.id,
            details={
                'notification_id': instance.notification.id,
                'scheduled_at': instance.scheduled_at.isoformat(),
            }
        )

        # If scheduled for now or past, trigger processing
        if instance.scheduled_at <= timezone.now():
            process_scheduled_notifications.delay()

    else:
        # Check if status changed
        try:
            old = NotificationSchedule.objects.get(pk=instance.pk)
            if old.status != instance.status:
                logger.info(f'Schedule {instance.id} status changed from {old.status} to {instance.status}')
        except NotificationSchedule.DoesNotExist:
            pass


@receiver(pre_delete, sender=NotificationSchedule)
def notification_schedule_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for NotificationSchedule model:
    - Log audit event
    """
    cache.delete(f'schedules_{instance.notification.user.id}')
    cache.delete(f'schedule_{instance.id}')
    logger.info(f'Notification schedule {instance.id} deleted')


# ============================================================================
# NOTIFICATION DIGEST SIGNALS
# ============================================================================

@receiver(post_save, sender=NotificationDigest)
def notification_digest_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for NotificationDigest model:
    - Invalidate digest cache
    - Log audit event
    - Trigger digest sending if not sent yet
    """
    cache.delete(f'digests_{instance.user.id}')
    cache.delete(f'digest_{instance.id}')
    cache.delete(f'digest_{instance.user.id}_{instance.digest_type}')

    if created:
        logger.info(f'Notification digest {instance.id} created for user {instance.user.id}')
        log_audit_event(
            user_id=instance.user.id,
            action='digest_created',
            resource='notification_digest',
            resource_id=instance.id,
            details={
                'digest_type': instance.digest_type,
                'notification_count': len(instance.notifications),
            }
        )

        # Auto-send if not yet sent and priority
        if not instance.sent_at:
            # For daily digests, send immediately if user has daily digest enabled
            try:
                prefs = NotificationPreference.objects.get(user=instance.user)
                if instance.digest_type == 'daily' and prefs.daily_digest:
                    from .tasks import send_daily_digest
                    send_daily_digest.delay()
            except NotificationPreference.DoesNotExist:
                pass

    else:
        # Check if sent status changed
        try:
            old = NotificationDigest.objects.get(pk=instance.pk)
            if old.sent_at != instance.sent_at:
                logger.info(f'Digest {instance.id} sent at {instance.sent_at}')
        except NotificationDigest.DoesNotExist:
            pass


# ============================================================================
# NOTIFICATION AUDIT SIGNALS
# ============================================================================

@receiver(post_save, sender=NotificationAudit)
def notification_audit_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for NotificationAudit model:
    - Invalidate audit cache
    - Log debug message
    """
    if created:
        cache.delete(f'audits_{instance.notification.id}')
        logger.debug(f'Notification audit {instance.id} created for notification {instance.notification.id}')


# ============================================================================
# CROSS-MODEL SIGNALS FOR USER STATISTICS
# ============================================================================

@receiver(post_save, sender=Notification)
def notification_user_statistics_handler(sender, instance, created, **kwargs):
    """
    Update user statistics when notification is created or read.
    """
    user = instance.user
    with transaction.atomic():
        # Update total notification count
        total = Notification.objects.filter(
            user=user,
            deleted_at__isnull=True
        ).count()

        # Update unread count
        unread = Notification.objects.filter(
            user=user,
            is_read=False,
            deleted_at__isnull=True
        ).count()

        # These fields may not exist on User model, but we can add them if needed
        # For now, we just cache them
        cache.set(f'notification_total_{user.id}', total, timeout=3600)
        cache.set(f'notification_unread_{user.id}', unread, timeout=3600)

        logger.debug(f'Updated notification stats for user {user.id}: total={total}, unread={unread}')


# ============================================================================
# CACHE INVALIDATION UTILITY
# ============================================================================

def invalidate_notification_cache_all(user_id: int):
    """
    Invalidate all cache keys related to a user's notifications.
    """
    keys = [
        f'notifications_{user_id}',
        f'notification_count_{user_id}',
        f'notification_unread_{user_id}',
        f'notification_total_{user_id}',
        f'preferences_{user_id}',
        f'user_prefs_{user_id}',
        f'digests_{user_id}',
        f'schedules_{user_id}',
    ]
    for key in keys:
        cache.delete(key)
    logger.debug(f'Cache invalidated for notifications of user {user_id}')


# ============================================================================
# LOGGING UTILITY
# ============================================================================

def log_notification_action(notification, action, user=None, details=None):
    """
    Utility to log a notification action with consistent format.
    """
    log_data = {
        'notification_id': notification.id,
        'user_id': notification.user.id,
        'action': action,
        'user_id_actor': user.id if user else None,
        'timestamp': timezone.now().isoformat(),
        'details': details or {}
    }
    logger.info(f'NOTIFICATION_ACTION: {json.dumps(log_data)}')


# ============================================================================
# SIGNAL DISPATCHER (for manual triggering)
# ============================================================================

def dispatch_notification_signals(notification_id, signal_name, *args, **kwargs):
    """
    Manually dispatch notification signals for testing or admin actions.
    """
    try:
        notification = Notification.objects.get(id=notification_id)
    except Notification.DoesNotExist:
        return None

    if signal_name == 'post_save':
        notification_post_save_handler(Notification, notification, created=False, **kwargs)
    elif signal_name == 'pre_save':
        notification_pre_save_handler(Notification, notification, **kwargs)
    elif signal_name == 'pre_delete':
        notification_pre_delete_handler(Notification, notification, **kwargs)
    elif signal_name == 'post_delete':
        notification_post_delete_handler(Notification, notification, **kwargs)
    return True


def dispatch_template_signals(template_id, signal_name, *args, **kwargs):
    """
    Manually dispatch template signals for testing or admin actions.
    """
    try:
        template = NotificationTemplate.objects.get(id=template_id)
    except NotificationTemplate.DoesNotExist:
        return None

    if signal_name == 'post_save':
        notification_template_post_save_handler(NotificationTemplate, template, created=False, **kwargs)
    elif signal_name == 'pre_save':
        notification_template_pre_save_handler(NotificationTemplate, template, **kwargs)
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
            # Re-raise to prevent silent failures
            raise
    return wrapper