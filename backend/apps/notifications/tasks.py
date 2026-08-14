"""
Celery tasks for the notifications app.

This module provides background task functions for notification operations:
- Processing pending notifications from the queue
- Sending notifications via multiple channels (email, SMS, push, in-app)
- Bulk notification sending for multiple users
- Daily and weekly notification digests
- Processing scheduled notifications
- Retrying failed notifications with exponential backoff
- Cleaning up old notifications and delivery records
- Event-driven notifications from various events
- Specialized notification tasks for different object types

All tasks include comprehensive error handling, logging, retry logic,
and performance optimizations for bulk operations.
"""

from celery import shared_task
from celery.utils.log import get_task_logger
from django.db import transaction
from django.db.models import Q, Count, Sum, F, OuterRef, Subquery
from django.utils import timezone
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple, Union
import json
import traceback

from apps.users.models import User
from apps.groups.models import Group, GroupMember
from apps.common.utils import send_email, send_sms, format_currency
from apps.common.constants import NotificationType, NotificationPriority, NotificationChannel

from .models import (
    Notification,
    NotificationTemplate,
    NotificationPreference,
    NotificationDelivery,
    NotificationEvent,
    NotificationSchedule,
    NotificationDigest,
    NotificationAudit,
)

logger = get_task_logger(__name__)


# ============================================================================
# NOTIFICATION SENDING TASK
# ============================================================================

@shared_task(bind=True, max_retries=5, default_retry_delay=60, rate_limit='30/m')
def send_notification(self, notification_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a notification via configured channels.

    Args:
        notification_data: Dictionary containing notification details:
            - id: Notification ID
            - user_id: User ID
            - email: User email
            - phone: User phone
            - message: Notification message
            - title: Notification title
            - notification_type: Type of notification
            - group_id: Optional group ID
            - object_id: Optional object ID
            - object_type: Optional object type
            - priority: Priority level
            - send_email: Whether to send email
            - send_sms: Whether to send SMS
            - send_push: Whether to send push
            - send_in_app: Whether to create in-app notification
            - template_name: Optional template name
            - template_context: Optional template context

    Returns:
        Dict with delivery results per channel
    """
    results = {
        'notification_id': notification_data.get('id'),
        'channels': {},
        'success': False,
        'errors': []
    }

    try:
        notification_id = notification_data.get('id')
        user_id = notification_data.get('user_id')
        email = notification_data.get('email')
        phone = notification_data.get('phone')
        message = notification_data.get('message')
        title = notification_data.get('title', '')
        notification_type = notification_data.get('notification_type', 'info')
        group_id = notification_data.get('group_id')
        object_id = notification_data.get('object_id')
        object_type = notification_data.get('object_type')
        priority = notification_data.get('priority', 'medium')
        send_email_flag = notification_data.get('send_email', False)
        send_sms_flag = notification_data.get('send_sms', False)
        send_push_flag = notification_data.get('send_push', False)
        send_in_app_flag = notification_data.get('send_in_app', True)
        template_name = notification_data.get('template_name')
        template_context = notification_data.get('template_context', {})

        # Get user preferences
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            results['errors'].append(f'User {user_id} not found')
            return results

        # Get notification instance if it exists
        try:
            notification = Notification.objects.get(id=notification_id)
        except Notification.DoesNotExist:
            notification = None

        # Check if user has disabled notifications
        try:
            prefs = NotificationPreference.objects.get(user=user)
        except NotificationPreference.DoesNotExist:
            prefs = None

        # ====================================================================
        # IN-APP NOTIFICATION
        # ====================================================================
        if send_in_app_flag:
            try:
                if notification is None:
                    # Create notification if it doesn't exist
                    notification = Notification.objects.create(
                        user=user,
                        notification_type=notification_type,
                        title=title,
                        message=message,
                        group_id=group_id,
                        object_id=object_id,
                        object_type=object_type,
                        priority=priority,
                        sent_at=timezone.now(),
                        delivered_at=timezone.now(),
                    )
                    notification_id = notification.id
                    results['notification_id'] = notification_id

                # Mark as delivered in-app
                delivery = NotificationDelivery.objects.create(
                    notification=notification,
                    channel='in_app',
                    status='delivered',
                    sent_at=timezone.now(),
                    delivered_at=timezone.now(),
                )
                results['channels']['in_app'] = {
                    'status': 'delivered',
                    'delivery_id': delivery.id
                }
                logger.debug(f'In-app notification {notification_id} delivered to user {user_id}')

            except Exception as e:
                results['channels']['in_app'] = {'status': 'failed', 'error': str(e)}
                results['errors'].append(f'In-app failed: {str(e)}')

        # ====================================================================
        # EMAIL NOTIFICATION
        # ====================================================================
        if send_email_flag and email and (prefs is None or prefs.email_enabled):
            try:
                # Render template if provided
                if template_name:
                    html_content = render_to_string(
                        f'emails/{template_name}.html',
                        {'user': user, **template_context}
                    )
                else:
                    html_content = None

                # Send email
                send_mail(
                    subject=title or f'Ekub Platform Notification',
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    html_message=html_content,
                    fail_silently=False,
                )

                # Record delivery
                if notification:
                    delivery = NotificationDelivery.objects.create(
                        notification=notification,
                        channel='email',
                        status='delivered',
                        sent_at=timezone.now(),
                        delivered_at=timezone.now(),
                    )
                    results['channels']['email'] = {
                        'status': 'delivered',
                        'delivery_id': delivery.id
                    }
                else:
                    results['channels']['email'] = {'status': 'sent'}

                logger.debug(f'Email notification sent to {email}')

            except Exception as e:
                results['channels']['email'] = {'status': 'failed', 'error': str(e)}
                results['errors'].append(f'Email failed: {str(e)}')

        # ====================================================================
        # SMS NOTIFICATION
        # ====================================================================
        if send_sms_flag and phone and (prefs is None or prefs.sms_enabled):
            try:
                # Truncate message for SMS (160 chars)
                sms_message = message[:160]
                send_sms(phone, sms_message)

                # Record delivery
                if notification:
                    delivery = NotificationDelivery.objects.create(
                        notification=notification,
                        channel='sms',
                        status='delivered',
                        sent_at=timezone.now(),
                        delivered_at=timezone.now(),
                    )
                    results['channels']['sms'] = {
                        'status': 'delivered',
                        'delivery_id': delivery.id
                    }
                else:
                    results['channels']['sms'] = {'status': 'sent'}

                logger.debug(f'SMS notification sent to {phone}')

            except Exception as e:
                results['channels']['sms'] = {'status': 'failed', 'error': str(e)}
                results['errors'].append(f'SMS failed: {str(e)}')

        # ====================================================================
        # PUSH NOTIFICATION
        # ====================================================================
        if send_push_flag and user.fcm_token and (prefs is None or prefs.push_enabled):
            try:
                # Send push notification via FCM
                from firebase_admin import messaging
                from firebase_admin import initialize_app, get_app
                import firebase_admin

                # Initialize Firebase if not already
                try:
                    app = get_app()
                except ValueError:
                    firebase_admin.initialize_app()

                message_obj = messaging.Message(
                    notification=messaging.Notification(
                        title=title or 'Ekub Platform',
                        body=message[:200],
                    ),
                    token=user.fcm_token,
                    data={
                        'notification_type': notification_type,
                        'notification_id': str(notification_id) if notification_id else '',
                        'group_id': str(group_id) if group_id else '',
                        'object_id': str(object_id) if object_id else '',
                        'object_type': object_type or '',
                    },
                )
                response = messaging.send(message_obj)

                # Record delivery
                if notification:
                    delivery = NotificationDelivery.objects.create(
                        notification=notification,
                        channel='push',
                        status='delivered',
                        sent_at=timezone.now(),
                        delivered_at=timezone.now(),
                        response_data={'message_id': response},
                    )
                    results['channels']['push'] = {
                        'status': 'delivered',
                        'delivery_id': delivery.id,
                        'message_id': response
                    }
                else:
                    results['channels']['push'] = {'status': 'sent'}

                logger.debug(f'Push notification sent to user {user_id}')

            except Exception as e:
                results['channels']['push'] = {'status': 'failed', 'error': str(e)}
                results['errors'].append(f'Push failed: {str(e)}')

        # ====================================================================
        # MARK NOTIFICATION AS SENT
        # ====================================================================
        if notification:
            notification.sent_at = timezone.now()
            notification.delivered_at = timezone.now()
            notification.save(update_fields=['sent_at', 'delivered_at'])

        results['success'] = len(results['errors']) == 0

        # Create audit log
        if notification:
            NotificationAudit.objects.create(
                notification=notification,
                user=user,
                action='send',
                old_status='pending',
                new_status='sent',
                details={'channels': results['channels']},
                timestamp=timezone.now(),
            )

        logger.info(f'Notification {notification_id} sent: {results["channels"]}')
        return results

    except Exception as e:
        logger.error(f'Error sending notification {notification_data.get("id")}: {str(e)}')
        results['errors'].append(f'Fatal: {str(e)}')
        self.retry(exc=e, countdown=60 * (self.request.retries + 1))
        return results


# ============================================================================
# BULK NOTIFICATION TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def send_bulk_notifications(self, user_ids: List[int], message: str,
                            notification_type: str = 'info', title: Optional[str] = None,
                            group_id: Optional[int] = None,
                            send_email: bool = True, send_sms: bool = False,
                            send_push: bool = False, send_in_app: bool = True) -> Dict[str, Any]:
    """
    Send bulk notifications to multiple users.

    Args:
        user_ids: List of user IDs
        message: Notification message
        notification_type: Type of notification
        title: Optional title
        group_id: Optional group ID
        send_email: Whether to send via email
        send_sms: Whether to send via SMS
        send_push: Whether to send via push
        send_in_app: Whether to create in-app notifications

    Returns:
        Dict with bulk send results
    """
    results = {
        'total': len(user_ids),
        'success': 0,
        'failed': 0,
        'errors': []
    }

    if not user_ids:
        return results

    # Get users in batches for performance
    batch_size = 100
    for i in range(0, len(user_ids), batch_size):
        batch = user_ids[i:i + batch_size]
        try:
            users = User.objects.filter(id__in=batch, is_active=True)
            for user in users:
                try:
                    # Create notification data
                    notification_data = {
                        'user_id': user.id,
                        'email': user.email,
                        'phone': user.phone,
                        'message': message,
                        'title': title or '',
                        'notification_type': notification_type,
                        'group_id': group_id,
                        'send_email': send_email,
                        'send_sms': send_sms,
                        'send_push': send_push,
                        'send_in_app': send_in_app,
                    }
                    # Send directly (could also queue individually)
                    send_notification.delay(notification_data)
                    results['success'] += 1
                except Exception as e:
                    results['failed'] += 1
                    results['errors'].append(f'User {user.id}: {str(e)}')
        except Exception as e:
            results['errors'].append(f'Batch {i}: {str(e)}')

    logger.info(f'Bulk notification queued: {results["success"]} success, {results["failed"]} failed')
    return results


# ============================================================================
# DIGEST TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_daily_digest(self) -> Dict[str, Any]:
    """
    Send daily notification digests to users who have opted in.
    """
    logger.info("Starting send_daily_digest task")

    results = {
        'users_processed': 0,
        'digests_sent': 0,
        'errors': 0
    }

    try:
        # Get users who have daily digest enabled
        users = User.objects.filter(
            is_active=True,
            notification_preferences__daily_digest=True,
            deleted_at__isnull=True
        )

        for user in users:
            try:
                _send_user_daily_digest(user.id)
                results['digests_sent'] += 1
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error sending daily digest to user {user.id}: {str(e)}')
            results['users_processed'] += 1

        logger.info(f'send_daily_digest completed: {results}')
        return results

    except Exception as e:
        logger.error(f'send_daily_digest failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


def _send_user_daily_digest(user_id: int) -> bool:
    """
    Send daily digest to a specific user.

    Args:
        user_id: User ID

    Returns:
        bool: True if sent successfully
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return False

    # Get notifications from the last 24 hours that are unread or recent
    threshold = timezone.now() - timedelta(days=1)
    notifications = Notification.objects.filter(
        user=user,
        created_at__gte=threshold,
        deleted_at__isnull=True
    ).order_by('-created_at')[:50]

    if not notifications.exists():
        return True  # No notifications to digest

    # Count unread
    unread_count = notifications.filter(is_read=False).count()

    # Prepare digest data
    digest_data = {
        'user': user,
        'notifications': notifications,
        'unread_count': unread_count,
        'total_count': notifications.count(),
        'date': timezone.now(),
    }

    # Create digest record
    digest = NotificationDigest.objects.create(
        user=user,
        digest_type='daily',
        notifications=list(notifications.values_list('id', flat=True)),
        summary={
            'unread_count': unread_count,
            'total_count': notifications.count(),
            'types': notifications.values('notification_type').annotate(count=Count('id')),
        },
        created_at=timezone.now(),
    )

    # Send email with digest
    subject = f'Daily Digest: {timezone.now().strftime("%Y-%m-%d")}'
    html_message = render_to_string('emails/daily_digest.html', digest_data)
    plain_message = f"""
    Daily Digest for {user.full_name}

    Notifications: {notifications.count()}
    Unread: {unread_count}

    {chr(10).join([f'- {n.title or n.message[:50]}' for n in notifications[:10]])}

    Visit the app for more details.
    """

    send_mail(
        subject,
        plain_message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html_message,
        fail_silently=False,
    )

    digest.sent_at = timezone.now()
    digest.save(update_fields=['sent_at'])

    logger.info(f'Daily digest sent to user {user_id}')
    return True


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_weekly_digest(self) -> Dict[str, Any]:
    """
    Send weekly notification digests to users who have opted in.
    """
    logger.info("Starting send_weekly_digest task")

    results = {
        'users_processed': 0,
        'digests_sent': 0,
        'errors': 0
    }

    try:
        users = User.objects.filter(
            is_active=True,
            notification_preferences__weekly_digest=True,
            deleted_at__isnull=True
        )

        for user in users:
            try:
                _send_user_weekly_digest(user.id)
                results['digests_sent'] += 1
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error sending weekly digest to user {user.id}: {str(e)}')
            results['users_processed'] += 1

        logger.info(f'send_weekly_digest completed: {results}')
        return results

    except Exception as e:
        logger.error(f'send_weekly_digest failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


def _send_user_weekly_digest(user_id: int) -> bool:
    """
    Send weekly digest to a specific user.

    Args:
        user_id: User ID

    Returns:
        bool: True if sent successfully
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return False

    threshold = timezone.now() - timedelta(days=7)
    notifications = Notification.objects.filter(
        user=user,
        created_at__gte=threshold,
        deleted_at__isnull=True
    ).order_by('-created_at')[:100]

    if not notifications.exists():
        return True

    unread_count = notifications.filter(is_read=False).count()

    digest_data = {
        'user': user,
        'notifications': notifications,
        'unread_count': unread_count,
        'total_count': notifications.count(),
        'date': timezone.now(),
        'week_start': threshold,
        'week_end': timezone.now(),
    }

    digest = NotificationDigest.objects.create(
        user=user,
        digest_type='weekly',
        notifications=list(notifications.values_list('id', flat=True)),
        summary={
            'unread_count': unread_count,
            'total_count': notifications.count(),
            'types': notifications.values('notification_type').annotate(count=Count('id')),
        },
        created_at=timezone.now(),
    )

    subject = f'Weekly Digest: {threshold.strftime("%Y-%m-%d")} to {timezone.now().strftime("%Y-%m-%d")}'
    html_message = render_to_string('emails/weekly_digest.html', digest_data)
    plain_message = f"""
    Weekly Digest for {user.full_name}

    Notifications this week: {notifications.count()}
    Unread: {unread_count}

    Visit the app for more details.
    """

    send_mail(
        subject,
        plain_message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html_message,
        fail_silently=False,
    )

    digest.sent_at = timezone.now()
    digest.save(update_fields=['sent_at'])

    logger.info(f'Weekly digest sent to user {user_id}')
    return True


# ============================================================================
# SCHEDULED NOTIFICATION TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_scheduled_notifications(self) -> Dict[str, Any]:
    """
    Process scheduled notifications that are due.
    """
    logger.info("Starting process_scheduled_notifications task")

    results = {
        'processed': 0,
        'sent': 0,
        'failed': 0,
        'errors': 0
    }

    try:
        now = timezone.now()
        # Get pending schedules where scheduled_at <= now
        schedules = NotificationSchedule.objects.filter(
            status='pending',
            scheduled_at__lte=now
        ).select_related('notification', 'notification__user')

        for schedule in schedules:
            try:
                # Execute the schedule
                success = schedule.execute()
                if success:
                    results['sent'] += 1
                else:
                    results['failed'] += 1

                results['processed'] += 1

                logger.info(f'Schedule {schedule.id} executed: {success}')

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error processing schedule {schedule.id}: {str(e)}')

        logger.info(f'process_scheduled_notifications completed: {results}')
        return results

    except Exception as e:
        logger.error(f'process_scheduled_notifications failed: {str(e)}')
        self.retry(exc=e, countdown=60)
        raise


# ============================================================================
# RETRY FAILED NOTIFICATIONS TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def retry_failed_notifications(self) -> Dict[str, Any]:
    """
    Retry failed notification deliveries with exponential backoff.
    """
    logger.info("Starting retry_failed_notifications task")

    results = {
        'retried': 0,
        'success': 0,
        'failed': 0,
        'errors': 0
    }

    try:
        # Get failed deliveries that haven't exceeded max retries
        failed_deliveries = NotificationDelivery.objects.filter(
            status='failed',
            attempt_count__lt=3,
            sent_at__lt=timezone.now() - timedelta(minutes=5)
        ).select_related('notification')

        for delivery in failed_deliveries:
            try:
                # Retry the delivery
                success = delivery.retry()
                if success:
                    results['retried'] += 1
                    # Re-send the notification
                    notification_data = {
                        'id': delivery.notification.id,
                        'user_id': delivery.notification.user.id,
                        'email': delivery.notification.user.email,
                        'phone': delivery.notification.user.phone,
                        'message': delivery.notification.message,
                        'title': delivery.notification.title,
                        'notification_type': delivery.notification.notification_type,
                        'group_id': delivery.notification.group.id if delivery.notification.group else None,
                        'object_id': delivery.notification.object_id,
                        'object_type': delivery.notification.object_type,
                        'priority': delivery.notification.priority,
                        'send_email': delivery.channel == 'email',
                        'send_sms': delivery.channel == 'sms',
                        'send_push': delivery.channel == 'push',
                        'send_in_app': delivery.channel == 'in_app',
                    }
                    send_notification.delay(notification_data)
                    results['success'] += 1
                else:
                    results['failed'] += 1
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error retrying delivery {delivery.id}: {str(e)}')

        logger.info(f'retry_failed_notifications completed: {results}')
        return results

    except Exception as e:
        logger.error(f'retry_failed_notifications failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# CLEANUP TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=600)
def cleanup_notifications(self) -> Dict[str, Any]:
    """
    Clean up old notifications and delivery records.
    - Delete notifications older than X days (read)
    - Archive unread notifications older than Y days
    - Delete delivery records older than Z days
    """
    logger.info("Starting cleanup_notifications task")

    results = {
        'notifications_deleted': 0,
        'notifications_archived': 0,
        'deliveries_deleted': 0,
        'errors': 0
    }

    try:
        now = timezone.now()

        # Delete read notifications older than 30 days
        read_threshold = now - timedelta(days=30)
        read_notifications = Notification.objects.filter(
            is_read=True,
            created_at__lt=read_threshold,
            deleted_at__isnull=True
        )
        count, _ = read_notifications.delete()
        results['notifications_deleted'] += count
        logger.info(f'Deleted {count} read notifications')

        # Archive unread notifications older than 90 days
        archive_threshold = now - timedelta(days=90)
        unread_notifications = Notification.objects.filter(
            is_read=False,
            created_at__lt=archive_threshold,
            deleted_at__isnull=True
        )
        for notification in unread_notifications:
            try:
                # Soft delete them
                notification.deleted_at = now
                notification.save(update_fields=['deleted_at'])
                results['notifications_archived'] += 1
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error archiving notification {notification.id}: {str(e)}')

        # Delete delivery records older than 60 days
        delivery_threshold = now - timedelta(days=60)
        deliveries = NotificationDelivery.objects.filter(
            created_at__lt=delivery_threshold
        )
        count, _ = deliveries.delete()
        results['deliveries_deleted'] += count
        logger.info(f'Deleted {count} delivery records')

        logger.info(f'cleanup_notifications completed: {results}')
        return results

    except Exception as e:
        logger.error(f'cleanup_notifications failed: {str(e)}')
        self.retry(exc=e, countdown=600)
        raise


# ============================================================================
# EVENT-DRIVEN NOTIFICATION TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_event_notifications(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send notifications triggered by an event.

    Args:
        event_data: Dictionary containing event data:
            - event_type: Type of event
            - user_id: User ID
            - group_id: Optional group ID
            - data: Event-specific data

    Returns:
        Dict with results
    """
    logger.info(f"Processing event notification: {event_data.get('event_type')}")

    results = {
        'event_type': event_data.get('event_type'),
        'processed': False,
        'notifications_sent': 0,
        'errors': []
    }

    try:
        event_type = event_data.get('event_type')
        user_id = event_data.get('user_id')
        group_id = event_data.get('group_id')
        data = event_data.get('data', {})

        if not user_id:
            results['errors'].append('User ID required')
            return results

        user = User.objects.get(id=user_id)

        # Determine notification based on event type
        if event_type == 'payment.completed':
            results = _handle_payment_event(user, data, results)
        elif event_type == 'payment.failed':
            results = _handle_payment_failed_event(user, data, results)
        elif event_type == 'group.joined':
            results = _handle_group_joined_event(user, data, results)
        elif event_type == 'group.member_added':
            results = _handle_group_member_added_event(user, data, results)
        elif event_type == 'contribution.paid':
            results = _handle_contribution_paid_event(user, data, results)
        elif event_type == 'contribution.overdue':
            results = _handle_contribution_overdue_event(user, data, results)
        elif event_type == 'payout.completed':
            results = _handle_payout_completed_event(user, data, results)
        elif event_type == 'user.verified':
            results = _handle_user_verified_event(user, data, results)
        else:
            results['errors'].append(f'Unknown event type: {event_type}')

        results['processed'] = True
        logger.info(f'Event {event_type} processed for user {user_id}')
        return results

    except User.DoesNotExist:
        results['errors'].append('User not found')
        return results
    except Exception as e:
        results['errors'].append(str(e))
        logger.error(f'Error processing event {event_data.get("event_type")}: {str(e)}')
        self.retry(exc=e, countdown=60)
        return results


def _handle_payment_event(user: User, data: Dict, results: Dict) -> Dict:
    """Handle payment completed event."""
    amount = data.get('amount', 0)
    group_name = data.get('group_name', '')
    results['notifications_sent'] += 1
    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': f'Your payment of {format_currency(amount)} for group "{group_name}" has been completed.',
        'title': 'Payment Completed',
        'notification_type': 'payment',
        'send_email': True,
        'send_sms': False,
        'send_push': True,
        'send_in_app': True,
        'object_id': data.get('payment_id'),
        'object_type': 'payment',
    })
    return results


def _handle_payment_failed_event(user: User, data: Dict, results: Dict) -> Dict:
    """Handle payment failed event."""
    amount = data.get('amount', 0)
    group_name = data.get('group_name', '')
    results['notifications_sent'] += 1
    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': f'Your payment of {format_currency(amount)} for group "{group_name}" has failed. Please try again.',
        'title': 'Payment Failed',
        'notification_type': 'payment',
        'send_email': True,
        'send_sms': True,
        'send_push': True,
        'send_in_app': True,
        'object_id': data.get('payment_id'),
        'object_type': 'payment',
    })
    return results


def _handle_group_joined_event(user: User, data: Dict, results: Dict) -> Dict:
    """Handle group joined event."""
    group_name = data.get('group_name', '')
    results['notifications_sent'] += 1
    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': f'You have successfully joined group "{group_name}".',
        'title': 'Group Joined',
        'notification_type': 'group',
        'send_email': True,
        'send_sms': False,
        'send_push': True,
        'send_in_app': True,
        'object_id': data.get('group_id'),
        'object_type': 'group',
    })
    return results


def _handle_group_member_added_event(user: User, data: Dict, results: Dict) -> Dict:
    """Handle group member added event."""
    group_name = data.get('group_name', '')
    added_by = data.get('added_by_email', '')
    results['notifications_sent'] += 1
    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': f'You have been added to group "{group_name}" by {added_by}.',
        'title': 'Added to Group',
        'notification_type': 'group',
        'send_email': True,
        'send_sms': False,
        'send_push': True,
        'send_in_app': True,
        'object_id': data.get('group_id'),
        'object_type': 'group',
    })
    return results


def _handle_contribution_paid_event(user: User, data: Dict, results: Dict) -> Dict:
    """Handle contribution paid event."""
    amount = data.get('amount', 0)
    group_name = data.get('group_name', '')
    round_num = data.get('round', 0)
    results['notifications_sent'] += 1
    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': f'Your contribution of {format_currency(amount)} for group "{group_name}" (Round {round_num + 1}) has been recorded.',
        'title': 'Contribution Paid',
        'notification_type': 'contribution',
        'send_email': True,
        'send_sms': False,
        'send_push': True,
        'send_in_app': True,
        'object_id': data.get('contribution_id'),
        'object_type': 'contribution',
    })
    return results


def _handle_contribution_overdue_event(user: User, data: Dict, results: Dict) -> Dict:
    """Handle contribution overdue event."""
    amount = data.get('amount', 0)
    group_name = data.get('group_name', '')
    days = data.get('days_overdue', 0)
    results['notifications_sent'] += 1
    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': f'Your contribution of {format_currency(amount)} for group "{group_name}" is {days} days overdue. Please make your payment.',
        'title': 'Contribution Overdue',
        'notification_type': 'contribution',
        'send_email': True,
        'send_sms': True,
        'send_push': True,
        'send_in_app': True,
        'object_id': data.get('contribution_id'),
        'object_type': 'contribution',
    })
    return results


def _handle_payout_completed_event(user: User, data: Dict, results: Dict) -> Dict:
    """Handle payout completed event."""
    amount = data.get('amount', 0)
    group_name = data.get('group_name', '')
    results['notifications_sent'] += 1
    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': f'Your payout of {format_currency(amount)} from group "{group_name}" has been completed.',
        'title': 'Payout Completed',
        'notification_type': 'payout',
        'send_email': True,
        'send_sms': False,
        'send_push': True,
        'send_in_app': True,
        'object_id': data.get('payout_id'),
        'object_type': 'payout',
    })
    return results


def _handle_user_verified_event(user: User, data: Dict, results: Dict) -> Dict:
    """Handle user verified event."""
    verification_type = data.get('verification_type', 'identity')
    results['notifications_sent'] += 1
    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': f'Your {verification_type} verification has been completed successfully.',
        'title': 'Verification Complete',
        'notification_type': 'verification',
        'send_email': True,
        'send_sms': False,
        'send_push': True,
        'send_in_app': True,
        'object_type': 'user',
    })
    return results


# ============================================================================
# SPECIALIZED NOTIFICATION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_payment_notification(self, user_id: int, payment_id: int, amount: Decimal,
                              group_name: str, status: str) -> Dict[str, Any]:
    """
    Send a payment-related notification.

    Args:
        user_id: User ID
        payment_id: Payment ID
        amount: Payment amount
        group_name: Group name
        status: Payment status (completed, failed, refunded)

    Returns:
        Dict with result
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return {'error': 'User not found'}

    messages = {
        'completed': f'Your payment of {format_currency(amount)} for group "{group_name}" has been completed.',
        'failed': f'Your payment of {format_currency(amount)} for group "{group_name}" has failed.',
        'refunded': f'Your payment of {format_currency(amount)} for group "{group_name}" has been refunded.',
    }
    message = messages.get(status, f'Payment {status} for group "{group_name}"')

    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': message,
        'title': f'Payment {status.capitalize()}',
        'notification_type': 'payment',
        'send_email': True,
        'send_sms': status == 'failed',
        'send_push': True,
        'send_in_app': True,
        'object_id': payment_id,
        'object_type': 'payment',
    })

    return {'status': 'queued'}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_group_notification(self, user_id: int, group_id: int, action: str,
                           group_name: str) -> Dict[str, Any]:
    """
    Send a group-related notification.

    Args:
        user_id: User ID
        group_id: Group ID
        action: Action (joined, left, admin_added, etc.)
        group_name: Group name

    Returns:
        Dict with result
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return {'error': 'User not found'}

    messages = {
        'joined': f'You have joined group "{group_name}".',
        'left': f'You have left group "{group_name}".',
        'admin_added': f'You have been made an admin of group "{group_name}".',
        'admin_removed': f'You are no longer an admin of group "{group_name}".',
    }
    message = messages.get(action, f'Group {action} for "{group_name}"')

    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': message,
        'title': f'Group {action.capitalize()}',
        'notification_type': 'group',
        'send_email': True,
        'send_sms': False,
        'send_push': True,
        'send_in_app': True,
        'object_id': group_id,
        'object_type': 'group',
    })

    return {'status': 'queued'}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_contribution_notification(self, user_id: int, contribution_id: int,
                                   amount: Decimal, group_name: str,
                                   status: str) -> Dict[str, Any]:
    """
    Send a contribution-related notification.

    Args:
        user_id: User ID
        contribution_id: Contribution ID
        amount: Contribution amount
        group_name: Group name
        status: Status (paid, overdue, pending)

    Returns:
        Dict with result
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return {'error': 'User not found'}

    messages = {
        'paid': f'Your contribution of {format_currency(amount)} for group "{group_name}" has been paid.',
        'overdue': f'Your contribution of {format_currency(amount)} for group "{group_name}" is overdue.',
        'pending': f'Your contribution of {format_currency(amount)} for group "{group_name}" is pending.',
    }
    message = messages.get(status, f'Contribution {status} for group "{group_name}"')

    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': message,
        'title': f'Contribution {status.capitalize()}',
        'notification_type': 'contribution',
        'send_email': True,
        'send_sms': status == 'overdue',
        'send_push': True,
        'send_in_app': True,
        'object_id': contribution_id,
        'object_type': 'contribution',
    })

    return {'status': 'queued'}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_payout_notification(self, user_id: int, payout_id: int, amount: Decimal,
                             group_name: str, status: str) -> Dict[str, Any]:
    """
    Send a payout-related notification.

    Args:
        user_id: User ID
        payout_id: Payout ID
        amount: Payout amount
        group_name: Group name
        status: Status (completed, pending, failed)

    Returns:
        Dict with result
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return {'error': 'User not found'}

    messages = {
        'completed': f'Your payout of {format_currency(amount)} from group "{group_name}" has been completed.',
        'pending': f'Your payout of {format_currency(amount)} from group "{group_name}" is pending.',
        'failed': f'Your payout of {format_currency(amount)} from group "{group_name}" has failed.',
    }
    message = messages.get(status, f'Payout {status} for group "{group_name}"')

    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': message,
        'title': f'Payout {status.capitalize()}',
        'notification_type': 'payout',
        'send_email': True,
        'send_sms': False,
        'send_push': True,
        'send_in_app': True,
        'object_id': payout_id,
        'object_type': 'payout',
    })

    return {'status': 'queued'}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_verification_notification(self, user_id: int, verification_type: str,
                                   status: str) -> Dict[str, Any]:
    """
    Send a verification-related notification.

    Args:
        user_id: User ID
        verification_type: Type (email, phone, identity)
        status: Status (verified, failed)

    Returns:
        Dict with result
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return {'error': 'User not found'}

    messages = {
        'verified': f'Your {verification_type} has been verified successfully.',
        'failed': f'Your {verification_type} verification has failed. Please try again.',
    }
    message = messages.get(status, f'Verification {status}')

    send_notification.delay({
        'user_id': user.id,
        'email': user.email,
        'phone': user.phone,
        'message': message,
        'title': f'Verification {status.capitalize()}',
        'notification_type': 'verification',
        'send_email': True,
        'send_sms': False,
        'send_push': True,
        'send_in_app': True,
        'object_type': 'user',
    })

    return {'status': 'queued'}


# ============================================================================
# PROCESS PENDING NOTIFICATIONS TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_pending_notifications(self) -> Dict[str, Any]:
    """
    Process any pending notifications that haven't been sent.
    """
    logger.info("Starting process_pending_notifications task")

    results = {
        'processed': 0,
        'sent': 0,
        'failed': 0,
        'errors': 0
    }

    try:
        # Find notifications that were created but not sent
        pending = Notification.objects.filter(
            sent_at__isnull=True,
            deleted_at__isnull=True
        )[:100]

        for notification in pending:
            try:
                # Prepare notification data
                notification_data = {
                    'id': notification.id,
                    'user_id': notification.user.id,
                    'email': notification.user.email,
                    'phone': notification.user.phone,
                    'message': notification.message,
                    'title': notification.title or '',
                    'notification_type': notification.notification_type,
                    'group_id': notification.group.id if notification.group else None,
                    'object_id': notification.object_id,
                    'object_type': notification.object_type,
                    'priority': notification.priority,
                    'send_email': True,
                    'send_sms': False,
                    'send_push': True,
                    'send_in_app': True,
                }
                send_notification.delay(notification_data)
                results['sent'] += 1
                results['processed'] += 1

            except Exception as e:
                results['failed'] += 1
                results['errors'] += 1
                logger.error(f'Error processing notification {notification.id}: {str(e)}')

        logger.info(f'process_pending_notifications completed: {results}')
        return results

    except Exception as e:
        logger.error(f'process_pending_notifications failed: {str(e)}')
        self.retry(exc=e, countdown=300)
        raise


# ============================================================================
# TASK SCHEDULING (BROKER CONFIG)
# ============================================================================

# These tasks should be scheduled in celery beat schedule:
# - send_daily_digest: daily at 7:00 AM
# - send_weekly_digest: weekly on Monday at 8:00 AM
# - process_scheduled_notifications: every 5 minutes
# - retry_failed_notifications: every 30 minutes
# - cleanup_notifications: weekly on Sunday at 3:00 AM
# - process_pending_notifications: every 15 minutes


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
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
    'process_pending_notifications',
]