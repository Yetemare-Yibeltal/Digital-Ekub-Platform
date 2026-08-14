"""
Models for the notifications app.

This module defines all database models related to notification management:
- Notification: Main notification entity linked to user and optional objects
- NotificationTemplate: Reusable notification templates with placeholders
- NotificationPreference: User preferences for notification channels and categories
- NotificationChannel: Configuration for notification delivery channels
- NotificationDelivery: Delivery tracking for each notification channel
- NotificationEvent: Event-driven notification triggers
- NotificationSchedule: Scheduled notifications for future delivery
- NotificationDigest: Aggregated notification digests
- NotificationAudit: Audit trail for notification actions

All models include comprehensive fields, methods, properties, validation,
and business logic for full notification lifecycle management.
"""

from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, F, Sum, Count, Avg, Max, Min
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.template import Template, Context
from django.template.loader import render_to_string
from django.core.mail import send_mail, EmailMultiAlternatives
from django.conf import settings
from django.contrib.postgres.fields import JSONField
from decimal import Decimal
import uuid
import json
import logging
from typing import Optional, List, Tuple, Dict, Any, Union
from datetime import timedelta, date, datetime

from apps.users.models import User
from apps.groups.models import Group
from apps.common.constants import NotificationType, NotificationChannel, NotificationPriority
from apps.common.utils import format_currency, get_current_time, send_email, send_sms

logger = logging.getLogger(__name__)


# ============================================================================
# NOTIFICATION MODEL
# ============================================================================

class Notification(models.Model):
    """
    Main Notification model representing a notification sent to a user.

    Fields:
    - user: The user receiving the notification
    - group: Optional group context
    - notification_type: Type of notification (info, success, warning, error, etc.)
    - title: Notification title
    - message: Notification message content
    - object_id: ID of the related object (if any)
    - object_type: Type of the related object (e.g., 'payment', 'contribution')
    - priority: Priority level (low, medium, high, urgent)
    - is_read: Whether the notification has been read
    - read_at: When the notification was read
    - sent_at: When the notification was sent
    - delivered_at: When the notification was delivered
    - expires_at: Optional expiry timestamp
    - metadata: Additional metadata as JSON
    - created_by: User who created the notification (system or admin)
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - mark_as_read(): Mark notification as read
    - mark_as_unread(): Mark notification as unread
    - is_expired(): Check if notification is expired
    - get_summary(): Get summary dictionary
    - send(): Send the notification via appropriate channels

    Indexes: user, notification_type, is_read, sent_at, created_at
    """

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User receiving the notification')
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name=_('group'),
        help_text=_('Optional group context')
    )

    # ========================================================================
    # CONTENT FIELDS
    # ========================================================================

    notification_type = models.CharField(
        _('notification type'),
        max_length=20,
        choices=NotificationType.CHOICES,
        default=NotificationType.INFO,
        db_index=True,
        help_text=_('Type of notification')
    )

    title = models.CharField(
        _('title'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Notification title')
    )

    message = models.TextField(
        _('message'),
        help_text=_('Notification message content')
    )

    # ========================================================================
    # OBJECT REFERENCE (Generic Foreign Key replacement)
    # ========================================================================

    object_id = models.PositiveIntegerField(
        _('object ID'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('ID of the related object')
    )

    object_type = models.CharField(
        _('object type'),
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        help_text=_('Type of the related object (e.g., payment, contribution)')
    )

    # ========================================================================
    # PRIORITY
    # ========================================================================

    priority = models.CharField(
        _('priority'),
        max_length=10,
        choices=NotificationPriority.CHOICES,
        default=NotificationPriority.MEDIUM,
        db_index=True,
        help_text=_('Priority level')
    )

    # ========================================================================
    # STATUS FIELDS
    # ========================================================================

    is_read = models.BooleanField(
        _('is read'),
        default=False,
        db_index=True,
        help_text=_('Whether the notification has been read')
    )

    read_at = models.DateTimeField(
        _('read at'),
        null=True,
        blank=True,
        help_text=_('When the notification was read')
    )

    sent_at = models.DateTimeField(
        _('sent at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('When the notification was sent')
    )

    delivered_at = models.DateTimeField(
        _('delivered at'),
        null=True,
        blank=True,
        help_text=_('When the notification was delivered')
    )

    expires_at = models.DateTimeField(
        _('expires at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('Optional expiry timestamp')
    )

    # ========================================================================
    # METADATA
    # ========================================================================

    metadata = models.JSONField(
        _('metadata'),
        default=dict,
        help_text=_('Additional metadata')
    )

    # ========================================================================
    # METADATA
    # ========================================================================

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications_created',
        verbose_name=_('created by'),
        help_text=_('User who created this notification')
    )

    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )

    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True,
        db_index=True
    )

    deleted_at = models.DateTimeField(
        _('deleted at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('Soft delete timestamp')
    )

    # ========================================================================
    # META
    # ========================================================================

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['notification_type', 'created_at']),
            models.Index(fields=['priority', 'created_at']),
            models.Index(fields=['object_id', 'object_type']),
            models.Index(fields=['sent_at', 'delivered_at']),
        ]
        verbose_name = _('notification')
        verbose_name_plural = _('notifications')

    def __str__(self):
        return f"Notification #{self.id} - {self.user.email} - {self.notification_type}"

    def save(self, *args, **kwargs):
        """Override save to set sent_at and delivered_at."""
        if not self.sent_at:
            self.sent_at = timezone.now()
        if not self.delivered_at and self.sent_at:
            self.delivered_at = self.sent_at

        # Set expiry if not set and priority is urgent
        if not self.expires_at and self.priority == NotificationPriority.URGENT:
            self.expires_at = timezone.now() + timedelta(days=7)

        super().save(*args, **kwargs)

        # Invalidate cache
        from django.core.cache import cache
        cache.delete(f'notifications_{self.user.id}')
        cache.delete(f'notification_count_{self.user.id}')
        cache.delete(f'notification_unread_{self.user.id}')

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_expired(self) -> bool:
        """Check if the notification is expired."""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    @property
    def is_read_status(self) -> bool:
        """Check if the notification has been read."""
        return self.is_read

    @property
    def age_days(self) -> int:
        """Age of the notification in days."""
        return (timezone.now() - self.created_at).days

    @property
    def priority_level(self) -> int:
        """Numeric priority level for sorting."""
        levels = {
            NotificationPriority.LOW: 0,
            NotificationPriority.MEDIUM: 1,
            NotificationPriority.HIGH: 2,
            NotificationPriority.URGENT: 3,
        }
        return levels.get(self.priority, 1)

    # ========================================================================
    # BUSINESS METHODS
    # ========================================================================

    def mark_as_read(self) -> bool:
        """Mark the notification as read."""
        if self.is_read:
            return True
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=['is_read', 'read_at'])
        return True

    def mark_as_unread(self) -> bool:
        """Mark the notification as unread."""
        if not self.is_read:
            return True
        self.is_read = False
        self.read_at = None
        self.save(update_fields=['is_read', 'read_at'])
        return True

    def delete_permanently(self) -> None:
        """Permanently delete the notification."""
        self.delete()

    # ========================================================================
    # SUMMARY METHODS
    # ========================================================================

    def get_summary(self) -> Dict[str, Any]:
        """Get summary dictionary for the notification."""
        return {
            'id': self.id,
            'user_id': self.user.id,
            'user_email': self.user.email,
            'group_id': self.group.id if self.group else None,
            'group_name': self.group.name if self.group else None,
            'notification_type': self.notification_type,
            'title': self.title,
            'message': self.message,
            'object_id': self.object_id,
            'object_type': self.object_type,
            'priority': self.priority,
            'is_read': self.is_read,
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def get_detail(self) -> Dict[str, Any]:
        """Get detailed summary with related object data."""
        summary = self.get_summary()
        # Add user details
        summary['user_detail'] = {
            'id': self.user.id,
            'email': self.user.email,
            'full_name': self.user.full_name,
            'profile_picture': self.user.profile_picture.url if self.user.profile_picture else None,
        }
        # Add group details if exists
        if self.group:
            summary['group_detail'] = {
                'id': self.group.id,
                'name': self.group.name,
            }
        return summary


# ============================================================================
# NOTIFICATION TEMPLATE MODEL
# ============================================================================

class NotificationTemplate(models.Model):
    """
    Reusable notification template with placeholders.

    Fields:
    - name: Template name (unique)
    - description: Optional description
    - notification_type: Type of notification this template is for
    - subject: Email subject template (optional)
    - body_template: Message body template with placeholders
    - html_template: Optional HTML email template
    - channels: Channels this template supports (comma-separated)
    - is_active: Whether the template is active
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - render(): Render the template with given context
    - render_subject(): Render the subject
    - render_body(): Render the body
    - render_html(): Render the HTML template

    Indexes: name, notification_type, is_active
    """

    name = models.CharField(
        _('name'),
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_('Unique template name')
    )

    description = models.TextField(
        _('description'),
        blank=True,
        null=True,
        help_text=_('Optional description')
    )

    notification_type = models.CharField(
        _('notification type'),
        max_length=20,
        choices=NotificationType.CHOICES,
        default=NotificationType.INFO,
        db_index=True,
        help_text=_('Type of notification this template is for')
    )

    subject = models.CharField(
        _('subject'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Email subject template with placeholders')
    )

    body_template = models.TextField(
        _('body template'),
        help_text=_('Message body with placeholders (e.g., {{ user.full_name }})')
    )

    html_template = models.TextField(
        _('HTML template'),
        blank=True,
        null=True,
        help_text=_('Optional HTML email template')
    )

    channels = models.CharField(
        _('channels'),
        max_length=100,
        default='email,in_app',
        help_text=_('Comma-separated list of supported channels')
    )

    is_active = models.BooleanField(
        _('is active'),
        default=True,
        db_index=True,
        help_text=_('Whether the template is active')
    )

    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )

    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True,
        db_index=True
    )

    deleted_at = models.DateTimeField(
        _('deleted at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('Soft delete timestamp')
    )

    class Meta:
        db_table = 'notification_templates'
        ordering = ['name']
        indexes = [
            models.Index(fields=['name', 'is_active']),
            models.Index(fields=['notification_type', 'is_active']),
        ]
        verbose_name = _('notification template')
        verbose_name_plural = _('notification templates')

    def __str__(self):
        return self.name

    def render(self, context: Dict[str, Any]) -> Dict[str, str]:
        """
        Render the template with the given context.

        Args:
            context: Dictionary of template variables

        Returns:
            dict: Rendered subject, body, and HTML
        """
        result = {}
        try:
            if self.subject:
                subject_template = Template(self.subject)
                result['subject'] = subject_template.render(Context(context))
            else:
                result['subject'] = ''

            body_template_obj = Template(self.body_template)
            result['body'] = body_template_obj.render(Context(context))

            if self.html_template:
                html_template_obj = Template(self.html_template)
                result['html'] = html_template_obj.render(Context(context))

        except Exception as e:
            logger.error(f'Error rendering template {self.name}: {str(e)}')
            result['body'] = str(e)
            result['html'] = ''

        return result

    def render_subject(self, context: Dict[str, Any]) -> str:
        """Render only the subject."""
        if not self.subject:
            return ''
        try:
            template = Template(self.subject)
            return template.render(Context(context))
        except Exception as e:
            logger.error(f'Error rendering subject for {self.name}: {str(e)}')
            return ''

    def render_body(self, context: Dict[str, Any]) -> str:
        """Render only the body."""
        try:
            template = Template(self.body_template)
            return template.render(Context(context))
        except Exception as e:
            logger.error(f'Error rendering body for {self.name}: {str(e)}')
            return str(e)

    def render_html(self, context: Dict[str, Any]) -> str:
        """Render the HTML template."""
        if not self.html_template:
            return ''
        try:
            template = Template(self.html_template)
            return template.render(Context(context))
        except Exception as e:
            logger.error(f'Error rendering HTML for {self.name}: {str(e)}')
            return ''


# ============================================================================
# NOTIFICATION PREFERENCE MODEL
# ============================================================================

class NotificationPreference(models.Model):
    """
    User preferences for notification channels and categories.

    Fields:
    - user: User these preferences belong to
    - email_enabled: Whether email notifications are enabled
    - sms_enabled: Whether SMS notifications are enabled
    - push_enabled: Whether push notifications are enabled
    - in_app_enabled: Whether in-app notifications are enabled
    - daily_digest: Whether daily digest is enabled
    - weekly_digest: Whether weekly digest is enabled
    - categories: Per-category preferences (JSON)
    - quiet_hours_start: Start of quiet hours
    - quiet_hours_end: End of quiet hours
    - timezone: User's timezone
    - updated_at, created_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - is_channel_enabled(): Check if a channel is enabled
    - is_category_enabled(): Check if a category is enabled
    - is_in_quiet_hours(): Check if current time is in quiet hours

    Indexes: user (unique)
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='notification_preferences',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User these preferences belong to')
    )

    email_enabled = models.BooleanField(
        _('email enabled'),
        default=True,
        help_text=_('Whether email notifications are enabled')
    )

    sms_enabled = models.BooleanField(
        _('SMS enabled'),
        default=False,
        help_text=_('Whether SMS notifications are enabled')
    )

    push_enabled = models.BooleanField(
        _('push enabled'),
        default=True,
        help_text=_('Whether push notifications are enabled')
    )

    in_app_enabled = models.BooleanField(
        _('in-app enabled'),
        default=True,
        help_text=_('Whether in-app notifications are enabled')
    )

    daily_digest = models.BooleanField(
        _('daily digest'),
        default=False,
        help_text=_('Whether daily digest is enabled')
    )

    weekly_digest = models.BooleanField(
        _('weekly digest'),
        default=False,
        help_text=_('Whether weekly digest is enabled')
    )

    categories = models.JSONField(
        _('categories'),
        default=dict,
        help_text=_('Per-category preferences (e.g., {"payment": true, "group": false})')
    )

    quiet_hours_start = models.TimeField(
        _('quiet hours start'),
        null=True,
        blank=True,
        help_text=_('Start of quiet hours (e.g., 22:00:00)')
    )

    quiet_hours_end = models.TimeField(
        _('quiet hours end'),
        null=True,
        blank=True,
        help_text=_('End of quiet hours (e.g., 07:00:00)')
    )

    timezone = models.CharField(
        _('timezone'),
        max_length=50,
        default='Africa/Addis_Ababa',
        help_text=_('User timezone')
    )

    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )

    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True,
        db_index=True
    )

    deleted_at = models.DateTimeField(
        _('deleted at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('Soft delete timestamp')
    )

    class Meta:
        db_table = 'notification_preferences'
        verbose_name = _('notification preference')
        verbose_name_plural = _('notification preferences')

    def __str__(self):
        return f"Preferences for {self.user.email}"

    def is_channel_enabled(self, channel: str) -> bool:
        """Check if a specific channel is enabled."""
        channel_map = {
            'email': 'email_enabled',
            'sms': 'sms_enabled',
            'push': 'push_enabled',
            'in_app': 'in_app_enabled',
        }
        field = channel_map.get(channel)
        if not field:
            return False
        return getattr(self, field, False)

    def is_category_enabled(self, category: str) -> bool:
        """Check if a specific category is enabled."""
        # If category not in categories dict, default to True
        return self.categories.get(category, True)

    def is_in_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        if not self.quiet_hours_start or not self.quiet_hours_end:
            return False

        import pytz
        now = timezone.now()
        user_tz = pytz.timezone(self.timezone)
        local_now = now.astimezone(user_tz)
        current_time = local_now.time()

        start = self.quiet_hours_start
        end = self.quiet_hours_end

        if start < end:
            return start <= current_time <= end
        else:  # Overnight quiet hours
            return current_time >= start or current_time <= end


# ============================================================================
# NOTIFICATION CHANNEL MODEL
# ============================================================================

class NotificationChannel(models.Model):
    """
    Configuration for notification delivery channels.

    Fields:
    - name: Channel name (email, sms, push, in_app, webhook)
    - is_active: Whether the channel is active
    - provider: Provider name (e.g., 'sendgrid', 'twilio', 'firebase')
    - configuration: JSON configuration for the channel
    - priority: Priority order (lower number = higher priority)
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - send(): Send notification via this channel
    - test(): Test the channel configuration

    Indexes: name (unique), is_active, priority
    """

    name = models.CharField(
        _('name'),
        max_length=20,
        choices=NotificationChannel.CHOICES,
        unique=True,
        db_index=True,
        help_text=_('Channel name')
    )

    is_active = models.BooleanField(
        _('is active'),
        default=True,
        db_index=True,
        help_text=_('Whether the channel is active')
    )

    provider = models.CharField(
        _('provider'),
        max_length=50,
        blank=True,
        null=True,
        help_text=_('Provider name')
    )

    configuration = models.JSONField(
        _('configuration'),
        default=dict,
        help_text=_('JSON configuration for the channel')
    )

    priority = models.PositiveIntegerField(
        _('priority'),
        default=100,
        help_text=_('Priority order (lower number = higher priority)')
    )

    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )

    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True,
        db_index=True
    )

    deleted_at = models.DateTimeField(
        _('deleted at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('Soft delete timestamp')
    )

    class Meta:
        db_table = 'notification_channels'
        ordering = ['priority', 'name']
        indexes = [
            models.Index(fields=['name', 'is_active']),
            models.Index(fields=['priority']),
        ]
        verbose_name = _('notification channel')
        verbose_name_plural = _('notification channels')

    def __str__(self):
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"


# ============================================================================
# NOTIFICATION DELIVERY MODEL
# ============================================================================

class NotificationDelivery(models.Model):
    """
    Delivery tracking for each notification channel.

    Fields:
    - notification: The notification being delivered
    - channel: Channel used (email, sms, push, in_app, webhook)
    - status: Delivery status (pending, sent, delivered, failed, bounced)
    - attempt_count: Number of delivery attempts
    - sent_at: When the delivery was attempted
    - delivered_at: When the delivery succeeded
    - error_message: Error message if failed
    - response_data: Response data from the delivery provider
    - created_at, updated_at: Timestamps

    Methods:
    - mark_sent(): Mark as sent
    - mark_delivered(): Mark as delivered
    - mark_failed(): Mark as failed with error
    - retry(): Increment attempt count and retry

    Indexes: notification, channel, status, sent_at
    """

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name='deliveries',
        verbose_name=_('notification'),
        db_index=True,
        help_text=_('The notification being delivered')
    )

    channel = models.CharField(
        _('channel'),
        max_length=20,
        choices=NotificationChannel.CHOICES,
        db_index=True,
        help_text=_('Channel used')
    )

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('sent', 'Sent'),
            ('delivered', 'Delivered'),
            ('failed', 'Failed'),
            ('bounced', 'Bounced'),
            ('blocked', 'Blocked'),
        ],
        default='pending',
        db_index=True,
        help_text=_('Delivery status')
    )

    attempt_count = models.PositiveIntegerField(
        _('attempt count'),
        default=0,
        help_text=_('Number of delivery attempts')
    )

    sent_at = models.DateTimeField(
        _('sent at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('When the delivery was attempted')
    )

    delivered_at = models.DateTimeField(
        _('delivered at'),
        null=True,
        blank=True,
        help_text=_('When the delivery succeeded')
    )

    error_message = models.TextField(
        _('error message'),
        blank=True,
        null=True,
        help_text=_('Error message if failed')
    )

    response_data = models.JSONField(
        _('response data'),
        default=dict,
        help_text=_('Response data from the delivery provider')
    )

    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )

    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True,
        db_index=True
    )

    class Meta:
        db_table = 'notification_deliveries'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['notification', 'channel']),
            models.Index(fields=['status', 'sent_at']),
            models.Index(fields=['channel', 'status']),
        ]
        verbose_name = _('notification delivery')
        verbose_name_plural = _('notification deliveries')

    def __str__(self):
        return f"Delivery #{self.id} - {self.channel} - {self.status}"

    def mark_sent(self) -> None:
        """Mark the delivery as sent."""
        self.status = 'sent'
        self.sent_at = timezone.now()
        self.attempt_count += 1
        self.save(update_fields=['status', 'sent_at', 'attempt_count'])

    def mark_delivered(self) -> None:
        """Mark the delivery as delivered."""
        self.status = 'delivered'
        self.delivered_at = timezone.now()
        self.save(update_fields=['status', 'delivered_at'])

    def mark_failed(self, error_message: str) -> None:
        """Mark the delivery as failed with error message."""
        self.status = 'failed'
        self.error_message = error_message
        self.attempt_count += 1
        self.save(update_fields=['status', 'error_message', 'attempt_count'])

    def retry(self) -> bool:
        """Retry the delivery if attempt count is less than 3."""
        if self.attempt_count >= 3:
            return False
        self.status = 'pending'
        self.save(update_fields=['status'])
        return True


# ============================================================================
# NOTIFICATION EVENT MODEL
# ============================================================================

class NotificationEvent(models.Model):
    """
    Event-driven notification trigger.

    Fields:
    - event_type: Type of event (e.g., 'payment.completed', 'group.joined')
    - user: User associated with the event
    - group: Optional group context
    - data: Event data as JSON
    - processed: Whether the event has been processed
    - processed_at: When the event was processed
    - error_message: Error message if processing failed
    - created_at, updated_at: Timestamps

    Methods:
    - process(): Process the event and generate notifications
    - retry(): Retry processing if failed

    Indexes: event_type, processed, created_at, user
    """

    event_type = models.CharField(
        _('event type'),
        max_length=50,
        db_index=True,
        help_text=_('Type of event')
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notification_events',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User associated with the event')
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notification_events',
        verbose_name=_('group'),
        help_text=_('Optional group context')
    )

    data = models.JSONField(
        _('data'),
        default=dict,
        help_text=_('Event data')
    )

    processed = models.BooleanField(
        _('processed'),
        default=False,
        db_index=True,
        help_text=_('Whether the event has been processed')
    )

    processed_at = models.DateTimeField(
        _('processed at'),
        null=True,
        blank=True,
        help_text=_('When the event was processed')
    )

    error_message = models.TextField(
        _('error message'),
        blank=True,
        null=True,
        help_text=_('Error message if processing failed')
    )

    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )

    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True,
        db_index=True
    )

    class Meta:
        db_table = 'notification_events'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type', 'processed']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['processed', 'created_at']),
        ]
        verbose_name = _('notification event')
        verbose_name_plural = _('notification events')

    def __str__(self):
        return f"Event #{self.id} - {self.event_type} - {'processed' if self.processed else 'pending'}"

    def process(self) -> bool:
        """Process the event and generate notifications."""
        if self.processed:
            return True

        try:
            # This would call a task or trigger notification generation
            # For now, just mark as processed
            self.processed = True
            self.processed_at = timezone.now()
            self.save(update_fields=['processed', 'processed_at'])
            logger.info(f'Event {self.id} processed successfully')
            return True
        except Exception as e:
            self.error_message = str(e)
            self.save(update_fields=['error_message'])
            logger.error(f'Error processing event {self.id}: {str(e)}')
            return False

    def retry(self) -> bool:
        """Retry processing if failed."""
        if self.processed:
            return False
        self.error_message = None
        self.save(update_fields=['error_message'])
        return self.process()


# ============================================================================
# NOTIFICATION SCHEDULE MODEL
# ============================================================================

class NotificationSchedule(models.Model):
    """
    Scheduled notifications for future delivery.

    Fields:
    - notification: The notification to deliver
    - scheduled_at: When to deliver
    - executed_at: When it was executed
    - status: Status (pending, sent, failed)
    - retry_count: Number of retry attempts
    - error_message: Error message if failed
    - created_at, updated_at: Timestamps

    Methods:
    - execute(): Execute the scheduled notification
    - reschedule(): Reschedule for a later time
    - cancel(): Cancel the schedule

    Indexes: scheduled_at, status, notification
    """

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name='schedules',
        verbose_name=_('notification'),
        db_index=True,
        help_text=_('The notification to deliver')
    )

    scheduled_at = models.DateTimeField(
        _('scheduled at'),
        db_index=True,
        help_text=_('When to deliver')
    )

    executed_at = models.DateTimeField(
        _('executed at'),
        null=True,
        blank=True,
        help_text=_('When it was executed')
    )

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('sent', 'Sent'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending',
        db_index=True,
        help_text=_('Schedule status')
    )

    retry_count = models.PositiveIntegerField(
        _('retry count'),
        default=0,
        help_text=_('Number of retry attempts')
    )

    error_message = models.TextField(
        _('error message'),
        blank=True,
        null=True,
        help_text=_('Error message if failed')
    )

    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )

    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True,
        db_index=True
    )

    class Meta:
        db_table = 'notification_schedules'
        ordering = ['scheduled_at']
        indexes = [
            models.Index(fields=['scheduled_at', 'status']),
            models.Index(fields=['notification', 'status']),
            models.Index(fields=['status', 'scheduled_at']),
        ]
        verbose_name = _('notification schedule')
        verbose_name_plural = _('notification schedules')

    def __str__(self):
        return f"Schedule #{self.id} - {self.scheduled_at} - {self.status}"

    def execute(self) -> bool:
        """Execute the scheduled notification."""
        if self.status != 'pending':
            return False

        try:
            # Send the notification via the normal sending process
            # This would call the notification sending logic
            self.status = 'sent'
            self.executed_at = timezone.now()
            self.save(update_fields=['status', 'executed_at'])
            logger.info(f'Scheduled notification {self.id} executed')
            return True
        except Exception as e:
            self.status = 'failed'
            self.error_message = str(e)
            self.retry_count += 1
            self.save(update_fields=['status', 'error_message', 'retry_count'])
            logger.error(f'Error executing scheduled notification {self.id}: {str(e)}')
            return False

    def reschedule(self, new_time: Optional[timezone.datetime] = None) -> bool:
        """Reschedule for a later time."""
        if self.status not in ['pending', 'failed']:
            return False

        if new_time is None:
            new_time = timezone.now() + timedelta(hours=1)

        self.scheduled_at = new_time
        self.status = 'pending'
        self.save(update_fields=['scheduled_at', 'status'])
        logger.info(f'Scheduled notification {self.id} rescheduled to {new_time}')
        return True

    def cancel(self) -> bool:
        """Cancel the schedule."""
        if self.status == 'cancelled':
            return True

        self.status = 'cancelled'
        self.save(update_fields=['status'])
        logger.info(f'Scheduled notification {self.id} cancelled')
        return True


# ============================================================================
# NOTIFICATION DIGEST MODEL
# ============================================================================

class NotificationDigest(models.Model):
    """
    Aggregated notification digest for users.

    Fields:
    - user: User receiving the digest
    - digest_type: Type (daily, weekly)
    - notifications: JSON list of notification IDs
    - summary: JSON summary of the digest
    - sent_at: When the digest was sent
    - created_at, updated_at: Timestamps

    Methods:
    - add_notification(): Add a notification to the digest
    - remove_notification(): Remove a notification from the digest
    - send(): Send the digest
    - get_summary(): Get summary dictionary

    Indexes: user, digest_type, sent_at, created_at
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notification_digests',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User receiving the digest')
    )

    digest_type = models.CharField(
        _('digest type'),
        max_length=10,
        choices=[
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
        ],
        default='daily',
        db_index=True,
        help_text=_('Type of digest')
    )

    notifications = models.JSONField(
        _('notifications'),
        default=list,
        help_text=_('List of notification IDs')
    )

    summary = models.JSONField(
        _('summary'),
        default=dict,
        help_text=_('JSON summary of the digest')
    )

    sent_at = models.DateTimeField(
        _('sent at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('When the digest was sent')
    )

    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )

    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True,
        db_index=True
    )

    class Meta:
        db_table = 'notification_digests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'digest_type']),
            models.Index(fields=['sent_at', 'created_at']),
            models.Index(fields=['user', 'sent_at']),
        ]
        verbose_name = _('notification digest')
        verbose_name_plural = _('notification digests')

    def __str__(self):
        return f"Digest #{self.id} - {self.user.email} - {self.digest_type}"

    def add_notification(self, notification_id: int) -> None:
        """Add a notification to the digest."""
        if notification_id not in self.notifications:
            self.notifications.append(notification_id)
            self.save(update_fields=['notifications'])

    def remove_notification(self, notification_id: int) -> None:
        """Remove a notification from the digest."""
        if notification_id in self.notifications:
            self.notifications.remove(notification_id)
            self.save(update_fields=['notifications'])

    def send(self) -> bool:
        """Send the digest to the user."""
        if self.sent_at:
            return False

        # This would call the email/SMS sending logic
        # For now, just mark as sent
        self.sent_at = timezone.now()
        self.save(update_fields=['sent_at'])
        logger.info(f'Digest {self.id} sent to user {self.user.id}')
        return True


# ============================================================================
# NOTIFICATION AUDIT MODEL
# ============================================================================

class NotificationAudit(models.Model):
    """
    Audit trail for notification actions.

    Fields:
    - notification: The notification being audited
    - user: User who performed the action
    - action: Action performed (create, send, read, delete, etc.)
    - old_status: Previous status
    - new_status: New status
    - details: Additional details as JSON
    - timestamp: When the action occurred
    - ip_address: IP address of the requester

    Indexes: notification, user, action, timestamp
    """

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name='audits',
        verbose_name=_('notification'),
        db_index=True,
        help_text=_('The notification being audited')
    )

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notification_audits',
        verbose_name=_('user'),
        help_text=_('User who performed the action')
    )

    action = models.CharField(
        _('action'),
        max_length=50,
        db_index=True,
        help_text=_('Action performed')
    )

    old_status = models.CharField(
        _('old status'),
        max_length=20,
        blank=True,
        null=True,
        help_text=_('Previous status')
    )

    new_status = models.CharField(
        _('new status'),
        max_length=20,
        blank=True,
        null=True,
        help_text=_('New status')
    )

    details = models.JSONField(
        _('details'),
        default=dict,
        help_text=_('Additional details')
    )

    timestamp = models.DateTimeField(
        _('timestamp'),
        default=timezone.now,
        db_index=True,
        help_text=_('When the action occurred')
    )

    ip_address = models.GenericIPAddressField(
        _('IP address'),
        null=True,
        blank=True,
        help_text=_('IP address of the requester')
    )

    class Meta:
        db_table = 'notification_audits'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['notification', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]
        verbose_name = _('notification audit')
        verbose_name_plural = _('notification audits')

    def __str__(self):
        return f"Audit #{self.id} - {self.action} on notification #{self.notification.id}"