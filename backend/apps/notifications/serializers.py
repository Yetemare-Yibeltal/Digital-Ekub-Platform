"""
Serializers for the notifications app.

This module provides comprehensive serializers for all notification models:
- Notification serializers (list, detail, create, update)
- NotificationTemplate serializers (list, create, update)
- NotificationPreference serializers (list, update)
- NotificationChannel serializers (list, create, update)
- NotificationDelivery serializers (list, detail)
- NotificationEvent serializers (list, create)
- NotificationSchedule serializers (list, create, update)
- NotificationDigest serializers (list, detail)
- NotificationAudit serializers (list, detail)
- Bulk operation serializers
- Statistics serializers

All serializers include full validation, computed fields, nested relationships,
and proper error handling for all notification operations.
"""

from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from decimal import Decimal
from typing import Dict, Any, Optional, List

from apps.users.models import User
from apps.users.serializers import UserBaseSerializer
from apps.groups.models import Group
from apps.groups.serializers import GroupListSerializer
from apps.common.constants import NotificationType, NotificationChannel, NotificationPriority
from apps.common.utils import format_currency

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

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# NOTIFICATION SERIALIZERS
# ============================================================================

class NotificationBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer with common fields for Notification model.
    """
    notification_type_display = serializers.CharField(source='get_notification_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)
    age_days = serializers.IntegerField(read_only=True)
    priority_level = serializers.IntegerField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'user', 'user_name', 'user_email', 'group', 'group_name',
            'notification_type', 'notification_type_display',
            'title', 'message', 'object_id', 'object_type',
            'priority', 'priority_display', 'priority_level',
            'is_read', 'read_at', 'sent_at', 'delivered_at',
            'expires_at', 'is_expired', 'age_days',
            'metadata', 'created_by', 'created_at', 'updated_at', 'deleted_at',
        ]
        read_only_fields = [
            'id', 'notification_type_display', 'priority_display',
            'user_name', 'user_email', 'group_name',
            'created_at', 'updated_at', 'deleted_at',
            'sent_at', 'delivered_at', 'is_expired', 'age_days',
            'priority_level', 'created_by',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_group_name(self, obj) -> str:
        return obj.group.name if obj.group else ''


class NotificationListSerializer(NotificationBaseSerializer):
    """
    Lightweight serializer for listing notifications.
    """
    class Meta(NotificationBaseSerializer.Meta):
        fields = [
            'id', 'user_name', 'user_email', 'group_name',
            'notification_type', 'notification_type_display',
            'title', 'message', 'priority', 'priority_display',
            'is_read', 'sent_at', 'created_at',
            'is_expired', 'priority_level',
        ]


class NotificationDetailSerializer(NotificationBaseSerializer):
    """
    Detailed serializer with nested relationships.
    """
    deliveries = serializers.SerializerMethodField()
    user_detail = serializers.SerializerMethodField()
    group_detail = serializers.SerializerMethodField()

    class Meta(NotificationBaseSerializer.Meta):
        fields = NotificationBaseSerializer.Meta.fields + [
            'deliveries', 'user_detail', 'group_detail',
        ]

    def get_deliveries(self, obj):
        deliveries = obj.deliveries.all().order_by('-created_at')
        return NotificationDeliverySerializer(deliveries, many=True).data

    def get_user_detail(self, obj):
        return UserBaseSerializer(obj.user).data

    def get_group_detail(self, obj):
        if obj.group:
            return GroupListSerializer(obj.group).data
        return None


class NotificationCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a new notification.
    """
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=True,
        help_text=_('User receiving the notification')
    )
    notification_type = serializers.ChoiceField(
        choices=NotificationType.CHOICES,
        default=NotificationType.INFO,
        required=False,
        help_text=_('Type of notification')
    )
    priority = serializers.ChoiceField(
        choices=NotificationPriority.CHOICES,
        default=NotificationPriority.MEDIUM,
        required=False,
        help_text=_('Priority level')
    )
    group = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.filter(deleted_at__isnull=True),
        required=False,
        help_text=_('Optional group context')
    )
    send_email = serializers.BooleanField(
        required=False,
        default=False,
        help_text=_('Whether to send via email')
    )
    send_sms = serializers.BooleanField(
        required=False,
        default=False,
        help_text=_('Whether to send via SMS')
    )
    send_push = serializers.BooleanField(
        required=False,
        default=False,
        help_text=_('Whether to send via push')
    )
    send_in_app = serializers.BooleanField(
        required=False,
        default=True,
        help_text=_('Whether to create in-app notification')
    )

    class Meta:
        model = Notification
        fields = [
            'user', 'group', 'notification_type', 'title', 'message',
            'object_id', 'object_type', 'priority', 'metadata',
            'send_email', 'send_sms', 'send_push', 'send_in_app',
        ]
        extra_kwargs = {
            'title': {'required': False, 'allow_blank': True},
            'message': {'required': True},
            'object_id': {'required': False},
            'object_type': {'required': False},
            'metadata': {'required': False},
        }

    def validate(self, attrs):
        # If object_id is provided, object_type must also be provided
        if attrs.get('object_id') and not attrs.get('object_type'):
            raise serializers.ValidationError(
                {'object_type': _('object_type is required when object_id is provided.')}
            )

        # If group is provided, ensure user is a member
        if attrs.get('group'):
            group = attrs.get('group')
            user = attrs.get('user')
            from apps.groups.models import GroupMember
            if not GroupMember.objects.filter(group=group, user=user, is_active=True).exists():
                raise serializers.ValidationError(
                    {'group': _('User is not a member of the specified group.')}
                )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        send_email = validated_data.pop('send_email', False)
        send_sms = validated_data.pop('send_sms', False)
        send_push = validated_data.pop('send_push', False)
        send_in_app = validated_data.pop('send_in_app', True)

        # Create notification
        notification = Notification.objects.create(
            sent_at=timezone.now(),
            delivered_at=timezone.now(),
            **validated_data
        )

        # Queue delivery if needed
        if send_in_app or send_email or send_sms or send_push:
            from .tasks import send_notification
            notification_data = {
                'id': notification.id,
                'user_id': notification.user.id,
                'email': notification.user.email,
                'phone': notification.user.phone,
                'message': notification.message,
                'title': notification.title,
                'notification_type': notification.notification_type,
                'group_id': notification.group.id if notification.group else None,
                'object_id': notification.object_id,
                'object_type': notification.object_type,
                'priority': notification.priority,
                'send_email': send_email,
                'send_sms': send_sms,
                'send_push': send_push,
                'send_in_app': send_in_app,
            }
            send_notification.delay(notification_data)

        logger.info(f'Notification {notification.id} created by {self.context.get("request").user}')
        return notification


class NotificationUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a notification (mark as read, etc.).
    """
    is_read = serializers.BooleanField(required=False, help_text=_('Mark as read'))

    class Meta:
        model = Notification
        fields = ['is_read']

    def update(self, instance, validated_data):
        if 'is_read' in validated_data:
            if validated_data['is_read'] and not instance.is_read:
                instance.mark_as_read()
            elif not validated_data['is_read'] and instance.is_read:
                instance.mark_as_unread()
        return instance


# ============================================================================
# NOTIFICATION TEMPLATE SERIALIZERS
# ============================================================================

class NotificationTemplateSerializer(serializers.ModelSerializer):
    """
    Serializer for NotificationTemplate model.
    """
    notification_type_display = serializers.CharField(source='get_notification_type_display', read_only=True)

    class Meta:
        model = NotificationTemplate
        fields = [
            'id', 'name', 'description', 'notification_type', 'notification_type_display',
            'subject', 'body_template', 'html_template', 'channels', 'is_active',
            'created_at', 'updated_at', 'deleted_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'deleted_at']


class NotificationTemplateCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a notification template.
    """
    name = serializers.CharField(required=True, max_length=100)
    body_template = serializers.CharField(required=True)

    class Meta:
        model = NotificationTemplate
        fields = [
            'name', 'description', 'notification_type', 'subject',
            'body_template', 'html_template', 'channels', 'is_active',
        ]
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True},
            'subject': {'required': False, 'allow_blank': True},
            'html_template': {'required': False, 'allow_blank': True},
            'channels': {'required': False, 'default': 'email,in_app'},
            'is_active': {'required': False, 'default': True},
        }

    def validate_name(self, value):
        if NotificationTemplate.objects.filter(name=value).exists():
            raise serializers.ValidationError(_('A template with this name already exists.'))
        return value

    def validate_body_template(self, value):
        if not value or len(value.strip()) < 10:
            raise serializers.ValidationError(_('Body template must be at least 10 characters.'))
        return value


class NotificationTemplateUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a notification template.
    """
    class Meta:
        model = NotificationTemplate
        fields = [
            'description', 'notification_type', 'subject',
            'body_template', 'html_template', 'channels', 'is_active',
        ]


# ============================================================================
# NOTIFICATION PREFERENCE SERIALIZER
# ============================================================================

class NotificationPreferenceSerializer(serializers.ModelSerializer):
    """
    Serializer for NotificationPreference model.
    """
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()

    class Meta:
        model = NotificationPreference
        fields = [
            'id', 'user', 'user_name', 'user_email',
            'email_enabled', 'sms_enabled', 'push_enabled', 'in_app_enabled',
            'daily_digest', 'weekly_digest', 'categories',
            'quiet_hours_start', 'quiet_hours_end', 'timezone',
            'created_at', 'updated_at', 'deleted_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'deleted_at']

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''


class NotificationPreferenceUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating notification preferences.
    """
    class Meta:
        model = NotificationPreference
        fields = [
            'email_enabled', 'sms_enabled', 'push_enabled', 'in_app_enabled',
            'daily_digest', 'weekly_digest', 'categories',
            'quiet_hours_start', 'quiet_hours_end', 'timezone',
        ]

    def validate_categories(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(_('Categories must be a JSON object.'))
        # Ensure all keys are valid notification types
        valid_types = [choice[0] for choice in NotificationType.CHOICES]
        for key in value.keys():
            if key not in valid_types:
                raise serializers.ValidationError(
                    _('Invalid category key: {key}. Valid types: {valid}').format(
                        key=key, valid=', '.join(valid_types)
                    )
                )
        return value


# ============================================================================
# NOTIFICATION CHANNEL SERIALIZERS
# ============================================================================

class NotificationChannelSerializer(serializers.ModelSerializer):
    """
    Serializer for NotificationChannel model.
    """
    name_display = serializers.CharField(source='get_name_display', read_only=True)

    class Meta:
        model = NotificationChannel
        fields = [
            'id', 'name', 'name_display', 'is_active',
            'provider', 'configuration', 'priority',
            'created_at', 'updated_at', 'deleted_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'deleted_at']


# ============================================================================
# NOTIFICATION DELIVERY SERIALIZER
# ============================================================================

class NotificationDeliverySerializer(serializers.ModelSerializer):
    """
    Serializer for NotificationDelivery model.
    """
    channel_display = serializers.CharField(source='get_channel_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = NotificationDelivery
        fields = [
            'id', 'notification', 'channel', 'channel_display',
            'status', 'status_display', 'attempt_count',
            'sent_at', 'delivered_at', 'error_message', 'response_data',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'channel_display', 'status_display',
            'created_at', 'updated_at', 'attempt_count',
        ]


# ============================================================================
# NOTIFICATION EVENT SERIALIZER
# ============================================================================

class NotificationEventSerializer(serializers.ModelSerializer):
    """
    Serializer for NotificationEvent model.
    """
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()

    class Meta:
        model = NotificationEvent
        fields = [
            'id', 'event_type', 'user', 'user_name', 'user_email',
            'group', 'group_name', 'data', 'processed',
            'processed_at', 'error_message',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'processed', 'processed_at', 'created_at', 'updated_at']

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_group_name(self, obj) -> str:
        return obj.group.name if obj.group else ''


class NotificationEventCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a notification event.
    """
    class Meta:
        model = NotificationEvent
        fields = ['event_type', 'user', 'group', 'data']
        extra_kwargs = {
            'event_type': {'required': True},
            'user': {'required': True},
            'group': {'required': False},
            'data': {'required': False},
        }

    def validate_event_type(self, value):
        if not value or len(value) < 3:
            raise serializers.ValidationError(_('Event type must be at least 3 characters.'))
        return value


# ============================================================================
# NOTIFICATION SCHEDULE SERIALIZER
# ============================================================================

class NotificationScheduleSerializer(serializers.ModelSerializer):
    """
    Serializer for NotificationSchedule model.
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    notification_title = serializers.SerializerMethodField()

    class Meta:
        model = NotificationSchedule
        fields = [
            'id', 'notification', 'notification_title',
            'scheduled_at', 'executed_at', 'status', 'status_display',
            'retry_count', 'error_message',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'notification_title', 'status_display', 'created_at', 'updated_at', 'retry_count']

    def get_notification_title(self, obj) -> str:
        return obj.notification.title or obj.notification.message[:50]


class NotificationScheduleCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for scheduling a notification.
    """
    notification = serializers.PrimaryKeyRelatedField(
        queryset=Notification.objects.filter(deleted_at__isnull=True),
        required=True,
        help_text=_('Notification to schedule')
    )
    scheduled_at = serializers.DateTimeField(required=True, help_text=_('When to deliver'))

    class Meta:
        model = NotificationSchedule
        fields = ['notification', 'scheduled_at']

    def validate_scheduled_at(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError(_('Scheduled time must be in the future.'))
        return value


# ============================================================================
# NOTIFICATION DIGEST SERIALIZER
# ============================================================================

class NotificationDigestSerializer(serializers.ModelSerializer):
    """
    Serializer for NotificationDigest model.
    """
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    digest_type_display = serializers.CharField(source='get_digest_type_display', read_only=True)
    notification_count = serializers.SerializerMethodField()

    class Meta:
        model = NotificationDigest
        fields = [
            'id', 'user', 'user_name', 'user_email',
            'digest_type', 'digest_type_display',
            'notifications', 'notification_count',
            'summary', 'sent_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_notification_count(self, obj) -> int:
        return len(obj.notifications) if obj.notifications else 0


# ============================================================================
# NOTIFICATION AUDIT SERIALIZER
# ============================================================================

class NotificationAuditSerializer(serializers.ModelSerializer):
    """
    Serializer for NotificationAudit model.
    """
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()

    class Meta:
        model = NotificationAudit
        fields = [
            'id', 'notification', 'user', 'user_name', 'user_email',
            'action', 'old_status', 'new_status', 'details',
            'timestamp', 'ip_address',
        ]
        read_only_fields = ['id', 'timestamp', 'ip_address']

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else 'System'

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''


# ============================================================================
# BULK NOTIFICATION SERIALIZER
# ============================================================================

class BulkNotificationSerializer(serializers.Serializer):
    """
    Serializer for sending bulk notifications.
    """
    user_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        help_text=_('List of user IDs to notify')
    )
    message = serializers.CharField(required=True, help_text=_('Notification message'))
    notification_type = serializers.ChoiceField(
        choices=NotificationType.CHOICES,
        default=NotificationType.INFO,
        required=False,
        help_text=_('Type of notification')
    )
    title = serializers.CharField(required=False, allow_blank=True, help_text=_('Notification title'))
    group_id = serializers.IntegerField(required=False, help_text=_('Optional group ID'))
    send_email = serializers.BooleanField(default=True, required=False)
    send_sms = serializers.BooleanField(default=False, required=False)
    send_push = serializers.BooleanField(default=False, required=False)
    send_in_app = serializers.BooleanField(default=True, required=False)

    def validate_user_ids(self, value):
        if not value:
            raise serializers.ValidationError(_('At least one user ID is required.'))
        existing_users = User.objects.filter(id__in=value, is_active=True).count()
        if existing_users != len(value):
            raise serializers.ValidationError(_('Some user IDs are invalid or inactive.'))
        return value

    def validate_group_id(self, value):
        if value:
            try:
                Group.objects.get(id=value, deleted_at__isnull=True)
            except Group.DoesNotExist:
                raise serializers.ValidationError(_('Group not found.'))
        return value


# ============================================================================
# NOTIFICATION STATISTICS SERIALIZER
# ============================================================================

class NotificationStatsSerializer(serializers.Serializer):
    """
    Serializer for notification statistics.
    """
    total = serializers.IntegerField()
    unread = serializers.IntegerField()
    read = serializers.IntegerField()
    read_rate = serializers.FloatField()
    by_type = serializers.DictField(child=serializers.IntegerField())
    by_channel = serializers.ListField(child=serializers.DictField())


# ============================================================================
# MARK ALL READ SERIALIZER
# ============================================================================

class MarkAllReadSerializer(serializers.Serializer):
    """
    Serializer for marking all notifications as read.
    """
    user_id = serializers.IntegerField(required=False, help_text=_('User ID (default: current user)'))

    def validate_user_id(self, value):
        if value:
            try:
                User.objects.get(id=value, is_active=True)
            except User.DoesNotExist:
                raise serializers.ValidationError(_('User not found.'))
        return value


# ============================================================================
# CLEAR NOTIFICATIONS SERIALIZER
# ============================================================================

class ClearNotificationsSerializer(serializers.Serializer):
    """
    Serializer for clearing notifications.
    """
    user_id = serializers.IntegerField(required=False, help_text=_('User ID (default: current user)'))
    before_date = serializers.DateTimeField(required=False, help_text=_('Delete notifications before this date'))


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'NotificationBaseSerializer',
    'NotificationListSerializer',
    'NotificationDetailSerializer',
    'NotificationCreateSerializer',
    'NotificationUpdateSerializer',
    'NotificationTemplateSerializer',
    'NotificationTemplateCreateSerializer',
    'NotificationTemplateUpdateSerializer',
    'NotificationPreferenceSerializer',
    'NotificationPreferenceUpdateSerializer',
    'NotificationChannelSerializer',
    'NotificationDeliverySerializer',
    'NotificationEventSerializer',
    'NotificationEventCreateSerializer',
    'NotificationScheduleSerializer',
    'NotificationScheduleCreateSerializer',
    'NotificationDigestSerializer',
    'NotificationAuditSerializer',
    'BulkNotificationSerializer',
    'NotificationStatsSerializer',
    'MarkAllReadSerializer',
    'ClearNotificationsSerializer',
]