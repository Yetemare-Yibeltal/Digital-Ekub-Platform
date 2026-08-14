"""
Notifications app for the Digital Ekub Platform.

This app handles all notification-related operations including:
- Sending notifications via multiple channels (email, SMS, push, in-app, webhook)
- Notification templates and personalization
- Notification preferences and opt-out management
- Delivery tracking and retry logic
- Batch and bulk notifications
- Real-time notifications via WebSocket
- Notification scheduling and digests
- Notification analytics and reporting
- User notification preferences management

All notification operations are centralized in this app and include
comprehensive delivery tracking, error handling, and logging.
"""

__version__ = '1.0.0'
__app_name__ = 'notifications'
__author__ = 'Digital Ekub Team'
__description__ = 'Notification management for the Digital Ekub Platform'

# Set default app configuration for Django
default_app_config = 'apps.notifications.apps.NotificationsConfig'

# ============================================================================
# IMPORT ALL PUBLIC COMPONENTS
# ============================================================================

# Models
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

# Serializers
from .serializers import (
    NotificationSerializer,
    NotificationDetailSerializer,
    NotificationCreateSerializer,
    NotificationUpdateSerializer,
    NotificationListSerializer,
    NotificationTemplateSerializer,
    NotificationTemplateCreateSerializer,
    NotificationTemplateUpdateSerializer,
    NotificationPreferenceSerializer,
    NotificationPreferenceUpdateSerializer,
    NotificationChannelSerializer,
    NotificationDeliverySerializer,
    NotificationEventSerializer,
    NotificationScheduleSerializer,
    NotificationDigestSerializer,
    NotificationAuditSerializer,
    BulkNotificationSerializer,
    NotificationStatsSerializer,
)

# Views
from .views import (
    NotificationViewSet,
    NotificationTemplateViewSet,
    NotificationPreferenceViewSet,
    NotificationChannelViewSet,
    NotificationDeliveryViewSet,
    NotificationEventViewSet,
    NotificationScheduleViewSet,
    NotificationDigestViewSet,
    NotificationAuditViewSet,
    NotificationStatsView,
    NotificationSendView,
    BulkNotificationSendView,
    NotificationWebhookView,
    NotificationPreferencesView,
    NotificationMarkAllReadView,
    NotificationClearAllView,
)

# Permissions
from .permissions import (
    IsNotificationOwner,
    IsNotificationOwnerOrAdmin,
    CanViewNotification,
    CanCreateNotification,
    CanUpdateNotification,
    CanDeleteNotification,
    CanSendNotification,
    CanManageTemplates,
    CanManagePreferences,
    CanViewStats,
    IsAdminNotification,
)

# Tasks
from .tasks import (
    process_pending_notifications,
    send_notification,
    send_bulk_notifications,
    send_daily_digest,
    send_weekly_digest,
    process_scheduled_notifications,
    retry_failed_notifications,
    cleanup_notifications,
    send_event_notifications,
    send_payment_notification,
    send_group_notification,
    send_contribution_notification,
    send_payout_notification,
    send_verification_notification,
)

# Signals
from .signals import (
    notification_post_save_handler,
    notification_pre_save_handler,
    notification_pre_delete_handler,
    notification_template_post_save_handler,
    notification_preference_post_save_handler,
    notification_delivery_post_save_handler,
)

# ============================================================================
# NOTIFICATION CONSTANTS (RE-EXPORT)
# ============================================================================

from apps.common.constants import NotificationType, NotificationChannel, NotificationPriority

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

import logging
import json
import hashlib
from typing import Optional, Dict, Any, List, Union
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
from django.conf import settings
from django.template import Template, Context
from django.template.loader import render_to_string
from django.core.mail import send_mail, EmailMultiAlternatives
from django.core.exceptions import ValidationError

from apps.users.models import User
from apps.groups.models import Group

logger = logging.getLogger(__name__)


# ============================================================================
# NOTIFICATION SENDING HELPERS
# ============================================================================

def send_notification_to_user(
    user: User,
    message: str,
    notification_type: str = 'info',
    title: Optional[str] = None,
    group: Optional[Group] = None,
    object_id: Optional[int] = None,
    object_type: Optional[str] = None,
    send_email: bool = True,
    send_sms: bool = False,
    send_push: bool = False,
    send_in_app: bool = True,
    priority: str = 'medium',
    template_name: Optional[str] = None,
    template_context: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Send a notification to a user via multiple channels.

    Args:
        user: User to send notification to
        message: Notification message
        notification_type: Type of notification
        title: Optional notification title
        group: Optional group context
        object_id: Optional object ID
        object_type: Optional object type
        send_email: Whether to send via email
        send_sms: Whether to send via SMS
        send_push: Whether to send via push notification
        send_in_app: Whether to create in-app notification
        priority: Priority level (low, medium, high, urgent)
        template_name: Optional email template name
        template_context: Optional template context

    Returns:
        Dict with notification details and delivery status
    """
    from .models import Notification, NotificationDelivery
    from .tasks import send_notification as send_notification_task

    if not user:
        raise ValueError('User is required')

    # Create notification record
    notification = Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title or '',
        message=message,
        group=group,
        object_id=object_id,
        object_type=object_type,
        priority=priority,
        is_read=False,
        sent_at=timezone.now(),
        delivered_at=timezone.now(),
    )

    # Build notification data
    notification_data = {
        'id': notification.id,
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': message,
        'title': title,
        'notification_type': notification_type,
        'group_id': group.id if group else None,
        'object_id': object_id,
        'object_type': object_type,
        'priority': priority,
        'template_name': template_name,
        'template_context': template_context or {},
        'send_email': send_email,
        'send_sms': send_sms,
        'send_push': send_push,
        'send_in_app': send_in_app,
    }

    # Send via task for async processing
    send_notification_task.delay(notification_data)

    result = {
        'notification_id': notification.id,
        'channels_requested': [],
        'channels_sent': [],
        'status': 'queued',
    }

    if send_in_app:
        result['channels_requested'].append('in_app')

    if send_email and user.email:
        result['channels_requested'].append('email')

    if send_sms and user.phone:
        result['channels_requested'].append('sms')

    if send_push and user.fcm_token:
        result['channels_requested'].append('push')

    return result


def send_bulk_notifications(
    users: List[User],
    message: str,
    notification_type: str = 'info',
    title: Optional[str] = None,
    group: Optional[Group] = None,
    send_email: bool = True,
    send_sms: bool = False,
    send_push: bool = False,
    send_in_app: bool = True,
) -> Dict[str, Any]:
    """
    Send bulk notifications to multiple users.

    Args:
        users: List of users to notify
        message: Notification message
        notification_type: Type of notification
        title: Optional title
        group: Optional group context
        send_email: Whether to send via email
        send_sms: Whether to send via SMS
        send_push: Whether to send via push
        send_in_app: Whether to create in-app notifications

    Returns:
        Dict with bulk notification results
    """
    from .tasks import send_bulk_notifications

    if not users:
        return {'error': 'No users specified'}

    user_ids = [user.id for user in users]

    result = send_bulk_notifications.delay(
        user_ids=user_ids,
        message=message,
        notification_type=notification_type,
        title=title,
        group_id=group.id if group else None,
        send_email=send_email,
        send_sms=send_sms,
        send_push=send_push,
        send_in_app=send_in_app,
    )

    return {
        'task_id': result.id,
        'user_count': len(user_ids),
        'status': 'queued',
    }


def send_notification_to_group(
    group: Group,
    message: str,
    notification_type: str = 'info',
    title: Optional[str] = None,
    exclude_user: Optional[User] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Send a notification to all members of a group.

    Args:
        group: Group to send notification to
        message: Notification message
        notification_type: Type of notification
        title: Optional title
        exclude_user: Optional user to exclude
        **kwargs: Additional arguments passed to send_bulk_notifications

    Returns:
        Dict with bulk notification results
    """
    from apps.groups.models import GroupMember

    members = GroupMember.objects.filter(group=group, is_active=True)
    if exclude_user:
        members = members.exclude(user=exclude_user)

    users = [member.user for member in members.select_related('user')]

    if not users:
        return {'error': 'No users found in group'}

    return send_bulk_notifications(
        users=users,
        message=message,
        notification_type=notification_type,
        title=title,
        group=group,
        **kwargs,
    )


# ============================================================================
# NOTIFICATION TEMPLATE HELPERS
# ============================================================================

def render_notification_template(template_name: str, context: Dict[str, Any]) -> str:
    """
    Render a notification template with the given context.

    Args:
        template_name: Name of the template
        context: Template context

    Returns:
        str: Rendered template
    """
    try:
        return render_to_string(f'notifications/{template_name}.html', context)
    except Exception as e:
        logger.error(f'Error rendering notification template {template_name}: {str(e)}')
        return str(e)


def render_email_template(template_name: str, context: Dict[str, Any]) -> str:
    """
    Render an email template with the given context.

    Args:
        template_name: Name of the template
        context: Template context

    Returns:
        str: Rendered email HTML
    """
    try:
        return render_to_string(f'emails/{template_name}.html', context)
    except Exception as e:
        logger.error(f'Error rendering email template {template_name}: {str(e)}')
        return str(e)


# ============================================================================
# NOTIFICATION PREFERENCES HELPERS
# ============================================================================

def get_user_notification_preferences(user: User) -> Dict[str, Any]:
    """
    Get notification preferences for a user.

    Args:
        user: User to get preferences for

    Returns:
        dict: User notification preferences
    """
    from .models import NotificationPreference

    try:
        prefs = NotificationPreference.objects.get(user=user)
        return {
            'email': prefs.email_enabled,
            'sms': prefs.sms_enabled,
            'push': prefs.push_enabled,
            'in_app': prefs.in_app_enabled,
            'daily_digest': prefs.daily_digest,
            'weekly_digest': prefs.weekly_digest,
            'categories': prefs.categories,
            'quiet_hours_start': prefs.quiet_hours_start,
            'quiet_hours_end': prefs.quiet_hours_end,
        }
    except NotificationPreference.DoesNotExist:
        return {
            'email': True,
            'sms': False,
            'push': True,
            'in_app': True,
            'daily_digest': False,
            'weekly_digest': False,
            'categories': {},
        }


def update_user_notification_preferences(user: User, preferences: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update notification preferences for a user.

    Args:
        user: User to update preferences for
        preferences: New preferences

    Returns:
        dict: Updated preferences
    """
    from .models import NotificationPreference

    with transaction.atomic():
        prefs, created = NotificationPreference.objects.get_or_create(user=user)

        for key, value in preferences.items():
            if hasattr(prefs, key):
                setattr(prefs, key, value)

        prefs.save()
        logger.info(f'Notification preferences updated for user {user.id}')

    return get_user_notification_preferences(user)


# ============================================================================
# NOTIFICATION DELIVERY HELPERS
# ============================================================================

def log_notification_delivery(
    notification_id: int,
    channel: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """
    Log notification delivery status.

    Args:
        notification_id: ID of the notification
        channel: Channel used (email, sms, push, in_app)
        status: Delivery status
        error_message: Optional error message
    """
    from .models import NotificationDelivery

    NotificationDelivery.objects.create(
        notification_id=notification_id,
        channel=channel,
        status=status,
        error_message=error_message,
        delivered_at=timezone.now(),
    )


def get_notification_stats(user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Get notification statistics.

    Args:
        user_id: Optional user filter

    Returns:
        dict: Notification statistics
    """
    from .models import Notification
    from django.db.models import Count, Sum, Q

    queryset = Notification.objects.all()
    if user_id:
        queryset = queryset.filter(user_id=user_id)

    total = queryset.count()
    unread = queryset.filter(is_read=False).count()
    read = queryset.filter(is_read=True).count()

    # Group by type
    type_stats = queryset.values('notification_type').annotate(
        count=Count('id')
    )

    # Group by channel
    from .models import NotificationDelivery
    channel_stats = NotificationDelivery.objects.filter(
        notification__in=queryset
    ).values('channel').annotate(
        count=Count('id'),
        successful=Count('id', filter=Q(status='success')),
        failed=Count('id', filter=Q(status='failed')),
    )

    return {
        'total': total,
        'unread': unread,
        'read': read,
        'read_rate': round((read / total * 100) if total > 0 else 0, 2),
        'by_type': {
            item['notification_type']: item['count']
            for item in type_stats
        },
        'by_channel': [
            {
                'channel': item['channel'],
                'total': item['count'],
                'successful': item['successful'],
                'failed': item['failed'],
                'success_rate': round((item['successful'] / item['count'] * 100) if item['count'] > 0 else 0, 2),
            }
            for item in channel_stats
        ],
    }


def mark_notification_read(notification_id: int) -> bool:
    """
    Mark a notification as read.

    Args:
        notification_id: ID of the notification

    Returns:
        bool: True if marked as read
    """
    from .models import Notification

    try:
        notification = Notification.objects.get(id=notification_id)
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=['is_read', 'read_at'])
        return True
    except Notification.DoesNotExist:
        return False


def mark_all_notifications_read(user_id: int) -> int:
    """
    Mark all notifications for a user as read.

    Args:
        user_id: ID of the user

    Returns:
        int: Number of notifications marked as read
    """
    from .models import Notification

    count = Notification.objects.filter(
        user_id=user_id,
        is_read=False
    ).update(
        is_read=True,
        read_at=timezone.now()
    )
    return count


def clear_notifications(user_id: int, before_date: Optional[timezone.datetime] = None) -> int:
    """
    Clear notifications for a user.

    Args:
        user_id: ID of the user
        before_date: Optional date to delete notifications before

    Returns:
        int: Number of notifications cleared
    """
    from .models import Notification

    queryset = Notification.objects.filter(user_id=user_id)
    if before_date:
        queryset = queryset.filter(created_at__lt=before_date)

    count, _ = queryset.delete()
    return count


# ============================================================================
# NOTIFICATION EVENT HELPERS
# ============================================================================

def create_notification_event(
    event_type: str,
    user: User,
    data: Dict[str, Any],
    group: Optional[Group] = None,
) -> Dict[str, Any]:
    """
    Create a notification event for triggering notifications.

    Args:
        event_type: Type of event
        user: User associated with the event
        data: Event data
        group: Optional group context

    Returns:
        dict: Created event data
    """
    from .models import NotificationEvent

    event = NotificationEvent.objects.create(
        event_type=event_type,
        user=user,
        group=group,
        data=data,
        processed=False,
    )

    return {
        'event_id': event.id,
        'event_type': event_type,
        'user_id': user.id,
        'data': data,
        'status': 'created',
    }


# ============================================================================
# CACHE INVALIDATION UTILITY
# ============================================================================

def invalidate_notification_cache(user_id: int):
    """
    Invalidate all cache keys related to a user's notifications.
    """
    keys = [
        f'notifications_{user_id}',
        f'notification_count_{user_id}',
        f'notification_unread_{user_id}',
        f'notification_prefs_{user_id}',
    ]
    for key in keys:
        cache.delete(key)
    logger.debug(f'Cache invalidated for notifications of user {user_id}')


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Package metadata
    '__version__',
    '__app_name__',
    '__author__',
    '__description__',

    # Models
    'Notification',
    'NotificationTemplate',
    'NotificationPreference',
    'NotificationChannel',
    'NotificationDelivery',
    'NotificationEvent',
    'NotificationSchedule',
    'NotificationDigest',
    'NotificationAudit',

    # Serializers
    'NotificationSerializer',
    'NotificationDetailSerializer',
    'NotificationCreateSerializer',
    'NotificationUpdateSerializer',
    'NotificationListSerializer',
    'NotificationTemplateSerializer',
    'NotificationTemplateCreateSerializer',
    'NotificationTemplateUpdateSerializer',
    'NotificationPreferenceSerializer',
    'NotificationPreferenceUpdateSerializer',
    'NotificationChannelSerializer',
    'NotificationDeliverySerializer',
    'NotificationEventSerializer',
    'NotificationScheduleSerializer',
    'NotificationDigestSerializer',
    'NotificationAuditSerializer',
    'BulkNotificationSerializer',
    'NotificationStatsSerializer',

    # Views
    'NotificationViewSet',
    'NotificationTemplateViewSet',
    'NotificationPreferenceViewSet',
    'NotificationChannelViewSet',
    'NotificationDeliveryViewSet',
    'NotificationEventViewSet',
    'NotificationScheduleViewSet',
    'NotificationDigestViewSet',
    'NotificationAuditViewSet',
    'NotificationStatsView',
    'NotificationSendView',
    'BulkNotificationSendView',
    'NotificationWebhookView',
    'NotificationPreferencesView',
    'NotificationMarkAllReadView',
    'NotificationClearAllView',

    # Permissions
    'IsNotificationOwner',
    'IsNotificationOwnerOrAdmin',
    'CanViewNotification',
    'CanCreateNotification',
    'CanUpdateNotification',
    'CanDeleteNotification',
    'CanSendNotification',
    'CanManageTemplates',
    'CanManagePreferences',
    'CanViewStats',
    'IsAdminNotification',

    # Tasks
    'process_pending_notifications',
    'send_notification',
    'send_bulk_notifications',
    'send_daily_digest',
    'send_weekly_digest',
    'process_scheduled_notifications',
    'retry_failed_notifications',
    'cleanup_notifications',
    'send_event_notifications',
    'send_payment_notification',
    'send_group_notification',
    'send_contribution_notification',
    'send_payout_notification',
    'send_verification_notification',

    # Signals
    'notification_post_save_handler',
    'notification_pre_save_handler',
    'notification_pre_delete_handler',
    'notification_template_post_save_handler',
    'notification_preference_post_save_handler',
    'notification_delivery_post_save_handler',

    # Constants
    'NotificationType',
    'NotificationChannel',
    'NotificationPriority',

    # Helper functions
    'send_notification_to_user',
    'send_bulk_notifications',
    'send_notification_to_group',
    'render_notification_template',
    'render_email_template',
    'get_user_notification_preferences',
    'update_user_notification_preferences',
    'log_notification_delivery',
    'get_notification_stats',
    'mark_notification_read',
    'mark_all_notifications_read',
    'clear_notifications',
    'create_notification_event',
    'invalidate_notification_cache',
]

# ============================================================================
# LOGGING
# ============================================================================

logger.info(f'Notifications app v{__version__} initialized')