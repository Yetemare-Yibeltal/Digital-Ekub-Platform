"""
Services for the notifications app.

This module provides the service layer for all notification operations:
- Notification sending via multiple channels (email, SMS, push, in-app)
- Template rendering and personalization
- User preference management and opt-out handling
- Digest generation and sending (daily, weekly)
- Notification delivery tracking
- Webhook handling for external notification events
- Bulk notification services
- Channel configuration and fallback

All services include comprehensive error handling, logging,
and integration with the notification models and tasks.
"""

import logging
import json
import re
from typing import Optional, List, Dict, Any, Union, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.db import transaction
from django.core.cache import cache
from django.contrib.auth import get_user_model
import requests
from urllib.parse import urljoin

from apps.users.models import User
from apps.groups.models import Group, GroupMember
from apps.common.utils import format_currency, send_email, send_sms
from apps.common.constants import NotificationType, NotificationChannel, NotificationPriority

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

logger = logging.getLogger(__name__)


# ============================================================================
# CORE NOTIFICATION SERVICE
# ============================================================================

class NotificationService:
    """
    Core service for notification operations.

    This class provides the main interface for sending notifications
    via multiple channels with preference checking, template rendering,
    and delivery tracking.
    """

    def __init__(self):
        self._preference_cache = {}
        self._template_cache = {}

    # --------------------------------------------------------------------------
    # MAIN SEND METHOD
    # --------------------------------------------------------------------------

    def send_notification(
        self,
        user: User,
        message: str,
        notification_type: str = NotificationType.INFO,
        title: Optional[str] = None,
        group: Optional[Group] = None,
        object_id: Optional[int] = None,
        object_type: Optional[str] = None,
        priority: str = NotificationPriority.MEDIUM,
        channels: Optional[List[str]] = None,
        template_name: Optional[str] = None,
        template_context: Optional[Dict[str, Any]] = None,
        send_email: Optional[bool] = None,
        send_sms: Optional[bool] = None,
        send_push: Optional[bool] = None,
        send_in_app: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Send a notification to a user via multiple channels.

        Args:
            user: User to send notification to
            message: Notification message
            notification_type: Type of notification
            title: Optional title
            group: Optional group context
            object_id: Optional object ID
            object_type: Optional object type
            priority: Priority level
            channels: List of channels to use (overrides individual flags)
            template_name: Optional template name
            template_context: Optional template context
            send_email: Whether to send via email (overrides preference)
            send_sms: Whether to send via SMS (overrides preference)
            send_push: Whether to send via push (overrides preference)
            send_in_app: Whether to create in-app notification

        Returns:
            Dict with notification details and delivery results
        """
        # Get user preferences
        prefs = self._get_preferences(user)

        # Determine which channels to use
        channels_to_use = self._determine_channels(
            user=user,
            prefs=prefs,
            notification_type=notification_type,
            channels=channels,
            send_email=send_email,
            send_sms=send_sms,
            send_push=send_push,
            send_in_app=send_in_app,
        )

        if not channels_to_use:
            return {
                'success': False,
                'error': 'No channels available',
                'user_id': user.id,
            }

        # Render template if provided
        rendered_content = self._render_content(
            message=message,
            title=title,
            template_name=template_name,
            template_context=template_context or {},
            user=user,
            group=group,
        )

        # Create notification record
        notification = self._create_notification_record(
            user=user,
            message=rendered_content['message'],
            notification_type=notification_type,
            title=rendered_content['title'],
            group=group,
            object_id=object_id,
            object_type=object_type,
            priority=priority,
        )

        # Send via each channel
        results = {}
        for channel in channels_to_use:
            result = self._send_via_channel(
                channel=channel,
                notification=notification,
                user=user,
                message=rendered_content['message'],
                title=rendered_content['title'],
                prefs=prefs,
                template_context=template_context or {},
            )
            results[channel] = result

        # Update notification with delivery status
        self._update_notification_status(notification, results)

        return {
            'notification_id': notification.id,
            'channels': results,
            'success': any(r.get('success', False) for r in results.values()),
            'user_id': user.id,
        }

    # --------------------------------------------------------------------------
    # CHANNEL DETERMINATION
    # --------------------------------------------------------------------------

    def _determine_channels(
        self,
        user: User,
        prefs: NotificationPreference,
        notification_type: str,
        channels: Optional[List[str]] = None,
        send_email: Optional[bool] = None,
        send_sms: Optional[bool] = None,
        send_push: Optional[bool] = None,
        send_in_app: Optional[bool] = None,
    ) -> List[str]:
        """Determine which channels to use for a notification."""
        available_channels = []

        # Check quiet hours
        if self._is_in_quiet_hours(user, prefs):
            # During quiet hours, only send urgent notifications via in-app
            if notification_type == NotificationType.URGENT:
                available_channels.append('in_app')
            return available_channels

        # Explicit channel list takes precedence
        if channels:
            for channel in channels:
                if self._is_channel_available(user, prefs, channel, notification_type):
                    available_channels.append(channel)
            return available_channels

        # Individual flags
        if send_in_app or (send_in_app is None and self._is_channel_available(user, prefs, 'in_app', notification_type)):
            available_channels.append('in_app')

        if send_email or (send_email is None and self._is_channel_available(user, prefs, 'email', notification_type)):
            available_channels.append('email')

        if send_sms or (send_sms is None and self._is_channel_available(user, prefs, 'sms', notification_type)):
            available_channels.append('sms')

        if send_push or (send_push is None and self._is_channel_available(user, prefs, 'push', notification_type)):
            available_channels.append('push')

        # Always fallback to in-app if no channels available
        if not available_channels:
            available_channels.append('in_app')

        return available_channels

    def _is_channel_available(
        self,
        user: User,
        prefs: NotificationPreference,
        channel: str,
        notification_type: str
    ) -> bool:
        """Check if a channel is available for a user."""
        if not user.is_active:
            return False

        # Check preference
        if not prefs.is_channel_enabled(channel):
            return False

        # Check category preference
        if not prefs.is_category_enabled(notification_type):
            return False

        # Check channel-specific requirements
        if channel == 'email' and not user.email:
            return False
        if channel == 'sms' and not user.phone:
            return False
        if channel == 'push' and not user.fcm_token:
            return False

        return True

    def _is_in_quiet_hours(self, user: User, prefs: NotificationPreference) -> bool:
        """Check if current time is within quiet hours."""
        return prefs.is_in_quiet_hours()

    # --------------------------------------------------------------------------
    # CONTENT RENDERING
    # --------------------------------------------------------------------------

    def _render_content(
        self,
        message: str,
        title: Optional[str],
        template_name: Optional[str],
        template_context: Dict[str, Any],
        user: User,
        group: Optional[Group],
    ) -> Dict[str, str]:
        """Render notification content with optional template."""
        context = {
            'user': user,
            'group': group,
            'app_name': 'Ekub Platform',
            'support_email': getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@ekub-platform.com'),
            **template_context,
        }

        rendered_message = message
        rendered_title = title or ''

        if template_name:
            try:
                # Try to use the template
                template = self._get_template(template_name)
                if template:
                    rendered = template.render(context)
                    rendered_message = rendered.get('body', message)
                    rendered_title = rendered.get('subject', title or rendered_message[:100])
                else:
                    # Fallback to inline template rendering
                    from django.template import Template, Context
                    body_template = Template(message)
                    rendered_message = body_template.render(Context(context))
                    if title:
                        title_template = Template(title)
                        rendered_title = title_template.render(Context(context))
            except Exception as e:
                logger.error(f'Error rendering template {template_name}: {str(e)}')
                # Fallback to raw message

        return {
            'message': rendered_message,
            'title': rendered_title,
        }

    def _get_template(self, name: str) -> Optional[NotificationTemplate]:
        """Get a notification template by name (cached)."""
        if name in self._template_cache:
            return self._template_cache[name]

        try:
            template = NotificationTemplate.objects.get(name=name, is_active=True)
            self._template_cache[name] = template
            return template
        except NotificationTemplate.DoesNotExist:
            return None

    # --------------------------------------------------------------------------
    # NOTIFICATION RECORD CREATION
    # --------------------------------------------------------------------------

    def _create_notification_record(
        self,
        user: User,
        message: str,
        notification_type: str,
        title: Optional[str],
        group: Optional[Group],
        object_id: Optional[int],
        object_type: Optional[str],
        priority: str,
    ) -> Notification:
        """Create a notification record in the database."""
        notification = Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=title or '',
            message=message,
            group=group,
            object_id=object_id,
            object_type=object_type,
            priority=priority,
            sent_at=timezone.now(),
        )
        return notification

    def _update_notification_status(self, notification: Notification, results: Dict[str, Any]) -> None:
        """Update notification status based on delivery results."""
        all_success = all(r.get('success', False) for r in results.values())
        if all_success:
            notification.delivered_at = timezone.now()
            notification.save(update_fields=['delivered_at'])
        else:
            # Some channels failed; record attempts
            pass

    # --------------------------------------------------------------------------
    # CHANNEL-SPECIFIC DELIVERY
    # --------------------------------------------------------------------------

    def _send_via_channel(
        self,
        channel: str,
        notification: Notification,
        user: User,
        message: str,
        title: str,
        prefs: NotificationPreference,
        template_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send a notification via a specific channel."""
        if channel == 'in_app':
            return self._send_in_app(notification, user, message, title)
        elif channel == 'email':
            return self._send_email(notification, user, message, title, template_context)
        elif channel == 'sms':
            return self._send_sms(notification, user, message)
        elif channel == 'push':
            return self._send_push(notification, user, message, title)
        else:
            return {'success': False, 'error': f'Unknown channel: {channel}'}

    def _send_in_app(
        self,
        notification: Notification,
        user: User,
        message: str,
        title: str,
    ) -> Dict[str, Any]:
        """Send an in-app notification."""
        # The notification already exists, just mark it as delivered
        delivery = NotificationDelivery.objects.create(
            notification=notification,
            user=user,
            channel='in_app',
            status='delivered',
            sent_at=timezone.now(),
            delivered_at=timezone.now(),
        )
        return {
            'success': True,
            'delivery_id': delivery.id,
            'channel': 'in_app',
        }

    def _send_email(
        self,
        notification: Notification,
        user: User,
        message: str,
        title: str,
        template_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send an email notification."""
        if not user.email:
            return {'success': False, 'error': 'No email address'}

        try:
            # Render HTML email if template available
            html_content = None
            try:
                html_content = render_to_string(
                    'emails/notification.html',
                    {
                        'user': user,
                        'message': message,
                        'title': title,
                        'notification_type': notification.notification_type,
                        'app_name': 'Ekub Platform',
                        **template_context,
                    }
                )
            except Exception:
                pass

            send_email(
                to_email=user.email,
                subject=title or 'Ekub Platform Notification',
                message=message,
                html_content=html_content,
            )

            # Record delivery
            delivery = NotificationDelivery.objects.create(
                notification=notification,
                user=user,
                channel='email',
                status='delivered',
                sent_at=timezone.now(),
                delivered_at=timezone.now(),
            )

            return {
                'success': True,
                'delivery_id': delivery.id,
                'channel': 'email',
            }
        except Exception as e:
            logger.error(f'Failed to send email to {user.email}: {str(e)}')
            delivery = NotificationDelivery.objects.create(
                notification=notification,
                user=user,
                channel='email',
                status='failed',
                error_message=str(e),
                sent_at=timezone.now(),
            )
            return {
                'success': False,
                'error': str(e),
                'delivery_id': delivery.id,
                'channel': 'email',
            }

    def _send_sms(
        self,
        notification: Notification,
        user: User,
        message: str,
    ) -> Dict[str, Any]:
        """Send an SMS notification."""
        if not user.phone:
            return {'success': False, 'error': 'No phone number'}

        try:
            # Truncate message for SMS (160 chars)
            sms_message = message[:160]
            send_sms(user.phone, sms_message)

            delivery = NotificationDelivery.objects.create(
                notification=notification,
                user=user,
                channel='sms',
                status='delivered',
                sent_at=timezone.now(),
                delivered_at=timezone.now(),
            )

            return {
                'success': True,
                'delivery_id': delivery.id,
                'channel': 'sms',
            }
        except Exception as e:
            logger.error(f'Failed to send SMS to {user.phone}: {str(e)}')
            delivery = NotificationDelivery.objects.create(
                notification=notification,
                user=user,
                channel='sms',
                status='failed',
                error_message=str(e),
                sent_at=timezone.now(),
            )
            return {
                'success': False,
                'error': str(e),
                'delivery_id': delivery.id,
                'channel': 'sms',
            }

    def _send_push(
        self,
        notification: Notification,
        user: User,
        message: str,
        title: str,
    ) -> Dict[str, Any]:
        """Send a push notification via Firebase Cloud Messaging."""
        if not user.fcm_token:
            return {'success': False, 'error': 'No FCM token'}

        try:
            # Attempt to send via Firebase
            from firebase_admin import messaging
            import firebase_admin

            # Ensure Firebase is initialized
            try:
                app = firebase_admin.get_app()
            except ValueError:
                firebase_admin.initialize_app()

            # Build message
            fcm_message = messaging.Message(
                notification=messaging.Notification(
                    title=title or 'Ekub Platform',
                    body=message[:200],
                ),
                token=user.fcm_token,
                data={
                    'notification_type': notification.notification_type,
                    'notification_id': str(notification.id),
                    'group_id': str(notification.group.id) if notification.group else '',
                },
            )

            response = messaging.send(fcm_message)

            delivery = NotificationDelivery.objects.create(
                notification=notification,
                user=user,
                channel='push',
                status='delivered',
                sent_at=timezone.now(),
                delivered_at=timezone.now(),
                response_data={'message_id': response},
            )

            return {
                'success': True,
                'delivery_id': delivery.id,
                'message_id': response,
                'channel': 'push',
            }
        except Exception as e:
            logger.error(f'Failed to send push to user {user.id}: {str(e)}')
            delivery = NotificationDelivery.objects.create(
                notification=notification,
                user=user,
                channel='push',
                status='failed',
                error_message=str(e),
                sent_at=timezone.now(),
            )
            return {
                'success': False,
                'error': str(e),
                'delivery_id': delivery.id,
                'channel': 'push',
            }

    # --------------------------------------------------------------------------
    # PREFERENCE HELPERS
    # --------------------------------------------------------------------------

    def _get_preferences(self, user: User) -> NotificationPreference:
        """Get user preferences (cached)."""
        cache_key = f'prefs_{user.id}'
        if cache_key in self._preference_cache:
            return self._preference_cache[cache_key]

        prefs, _ = NotificationPreference.objects.get_or_create(user=user)
        self._preference_cache[cache_key] = prefs
        return prefs


# ============================================================================
# BULK NOTIFICATION SERVICE
# ============================================================================

class BulkNotificationService:
    """
    Service for sending bulk notifications to multiple users.
    """

    def __init__(self):
        self.notification_service = NotificationService()

    def send_bulk_notifications(
        self,
        user_ids: List[int],
        message: str,
        notification_type: str = NotificationType.INFO,
        title: Optional[str] = None,
        group_id: Optional[int] = None,
        send_email: bool = True,
        send_sms: bool = False,
        send_push: bool = False,
        send_in_app: bool = True,
    ) -> Dict[str, Any]:
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
        if not user_ids:
            return {'success': False, 'error': 'No users specified'}

        # Get group if provided
        group = None
        if group_id:
            try:
                group = Group.objects.get(id=group_id, deleted_at__isnull=True)
            except Group.DoesNotExist:
                pass

        results = {
            'total': len(user_ids),
            'sent': 0,
            'failed': 0,
            'errors': [],
        }

        # Process users in batches
        batch_size = getattr(settings, 'NOTIFICATION_BATCH_SIZE', 100)
        for i in range(0, len(user_ids), batch_size):
            batch = user_ids[i:i + batch_size]
            users = User.objects.filter(id__in=batch, is_active=True)

            for user in users:
                try:
                    result = self.notification_service.send_notification(
                        user=user,
                        message=message,
                        notification_type=notification_type,
                        title=title,
                        group=group,
                        send_email=send_email,
                        send_sms=send_sms,
                        send_push=send_push,
                        send_in_app=send_in_app,
                    )
                    if result.get('success'):
                        results['sent'] += 1
                    else:
                        results['failed'] += 1
                        results['errors'].append({
                            'user_id': user.id,
                            'error': result.get('error', 'Unknown error'),
                        })
                except Exception as e:
                    results['failed'] += 1
                    results['errors'].append({
                        'user_id': user.id,
                        'error': str(e),
                    })

        return results


# ============================================================================
# NOTIFICATION PREFERENCE SERVICE
# ============================================================================

class NotificationPreferenceService:
    """
    Service for managing user notification preferences.
    """

    def get_preferences(self, user: User) -> Dict[str, Any]:
        """Get user notification preferences."""
        try:
            prefs = NotificationPreference.objects.get(user=user)
            return {
                'email_enabled': prefs.email_enabled,
                'sms_enabled': prefs.sms_enabled,
                'push_enabled': prefs.push_enabled,
                'in_app_enabled': prefs.in_app_enabled,
                'daily_digest': prefs.daily_digest,
                'weekly_digest': prefs.weekly_digest,
                'categories': prefs.categories,
                'quiet_hours_start': prefs.quiet_hours_start,
                'quiet_hours_end': prefs.quiet_hours_end,
                'timezone': prefs.timezone,
            }
        except NotificationPreference.DoesNotExist:
            return {
                'email_enabled': True,
                'sms_enabled': False,
                'push_enabled': True,
                'in_app_enabled': True,
                'daily_digest': False,
                'weekly_digest': False,
                'categories': {},
                'quiet_hours_start': None,
                'quiet_hours_end': None,
                'timezone': 'Africa/Addis_Ababa',
            }

    def update_preferences(self, user: User, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """Update user notification preferences."""
        with transaction.atomic():
            prefs, created = NotificationPreference.objects.get_or_create(user=user)

            # Update fields
            for key, value in preferences.items():
                if hasattr(prefs, key):
                    setattr(prefs, key, value)

            prefs.save()

            # Clear cache
            cache.delete(f'prefs_{user.id}')

        return self.get_preferences(user)


# ============================================================================
# DIGEST SERVICE
# ============================================================================

class DigestService:
    """
    Service for generating and sending notification digests.
    """

    def generate_daily_digest(self, user: User) -> Optional[NotificationDigest]:
        """Generate a daily digest for a user."""
        threshold = timezone.now() - timedelta(days=1)
        notifications = Notification.objects.filter(
            user=user,
            created_at__gte=threshold,
            deleted_at__isnull=True
        ).order_by('-created_at')

        if not notifications.exists():
            return None

        digest = NotificationDigest.objects.create(
            user=user,
            digest_type='daily',
            notifications=list(notifications.values_list('id', flat=True)),
            summary={
                'total': notifications.count(),
                'unread': notifications.filter(is_read=False).count(),
                'types': {},
            },
        )

        return digest

    def generate_weekly_digest(self, user: User) -> Optional[NotificationDigest]:
        """Generate a weekly digest for a user."""
        threshold = timezone.now() - timedelta(days=7)
        notifications = Notification.objects.filter(
            user=user,
            created_at__gte=threshold,
            deleted_at__isnull=True
        ).order_by('-created_at')

        if not notifications.exists():
            return None

        digest = NotificationDigest.objects.create(
            user=user,
            digest_type='weekly',
            notifications=list(notifications.values_list('id', flat=True)),
            summary={
                'total': notifications.count(),
                'unread': notifications.filter(is_read=False).count(),
                'types': {},
            },
        )

        return digest

    def send_digest(self, digest: NotificationDigest) -> bool:
        """Send a digest to the user."""
        if digest.sent_at:
            return False

        try:
            user = digest.user
            notifications = Notification.objects.filter(
                id__in=digest.notifications,
                deleted_at__isnull=True
            )

            context = {
                'user': user,
                'notifications': notifications,
                'digest_type': digest.digest_type,
                'date': timezone.now(),
            }

            # Send email
            subject = f'{digest.digest_type.capitalize()} Digest: {timezone.now().strftime("%Y-%m-%d")}'
            html_message = render_to_string('emails/digest.html', context)
            plain_message = f"""
            {digest.digest_type.capitalize()} Digest for {user.full_name}

            You have {notifications.count()} notifications.

            View them in the app.
            """

            send_email(
                to_email=user.email,
                subject=subject,
                message=plain_message,
                html_content=html_message,
            )

            digest.sent_at = timezone.now()
            digest.save(update_fields=['sent_at'])
            return True

        except Exception as e:
            logger.error(f'Failed to send digest {digest.id}: {str(e)}')
            return False


# ============================================================================
# NOTIFICATION WEBHOOK SERVICE
# ============================================================================

class NotificationWebhookService:
    """
    Service for handling webhook notifications to external services.
    """

    def send_webhook(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 5,
    ) -> Dict[str, Any]:
        """
        Send a webhook notification to an external URL.

        Args:
            url: Webhook URL
            payload: Payload to send
            headers: Additional headers
            timeout: Request timeout in seconds

        Returns:
            Dict with response details
        """
        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers or {},
                timeout=timeout,
            )
            return {
                'success': 200 <= response.status_code < 300,
                'status_code': response.status_code,
                'response': response.text[:500] if response.text else '',
            }
        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Timeout'}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'Connection error'}
        except Exception as e:
            return {'success': False, 'error': str(e)}


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'NotificationService',
    'BulkNotificationService',
    'NotificationPreferenceService',
    'DigestService',
    'NotificationWebhookService',
]