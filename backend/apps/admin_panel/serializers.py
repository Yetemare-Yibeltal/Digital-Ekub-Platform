"""
Serializers for the admin panel app.

This module provides comprehensive serializers for all admin panel models:
- AdminAction serializers (list, detail, create)
- AdminLog serializers (list, detail, create)
- AdminPreference serializers (list, update)
- SystemSetting serializers (list, create, update)
- MaintenanceLog serializers (list, detail, create)
- Report serializers (list, detail, create, update)
- ReportSchedule serializers (list, detail, create, update)
- AuditTrail serializers (list, detail)
- DashboardWidget serializers (list, create, update)
- Dashboard stats serializer
- System health serializer
- Bulk action serializers

All serializers include full validation, computed fields, nested relationships,
and proper error handling for all administrative operations.
"""

from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal
from typing import Dict, Any, Optional, List
import json
import csv
import io

from apps.users.models import User
from apps.users.serializers import UserBaseSerializer
from apps.groups.models import Group
from apps.groups.serializers import GroupListSerializer
from apps.common.constants import (
    UserStatus, GroupStatus, PaymentStatus, ContributionStatus, NotificationType
)
from apps.common.utils import format_currency, get_current_time

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

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# ADMIN ACTION SERIALIZERS
# ============================================================================

class AdminActionBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer with common fields for AdminAction model.
    """
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    admin_email = serializers.SerializerMethodField()
    admin_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()

    class Meta:
        model = AdminAction
        fields = [
            'id', 'user', 'user_email', 'user_name', 'group', 'group_name',
            'admin', 'admin_email', 'admin_name', 'action', 'action_display',
            'details', 'ip_address', 'user_agent', 'timestamp',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'action_display', 'admin_email', 'admin_name',
            'user_email', 'user_name', 'group_name',
            'timestamp', 'created_at', 'updated_at',
        ]

    def get_admin_email(self, obj) -> str:
        return obj.admin.email if obj.admin else ''

    def get_admin_name(self, obj) -> str:
        return obj.admin.full_name if obj.admin else ''

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_group_name(self, obj) -> str:
        return obj.group.name if obj.group else ''


class AdminActionListSerializer(AdminActionBaseSerializer):
    """
    Lightweight serializer for listing admin actions.
    """
    class Meta(AdminActionBaseSerializer.Meta):
        fields = [
            'id', 'admin_email', 'admin_name', 'action', 'action_display',
            'user_email', 'user_name', 'group_name', 'timestamp',
        ]


class AdminActionDetailSerializer(AdminActionBaseSerializer):
    """
    Detailed serializer with nested relationships.
    """
    admin_detail = serializers.SerializerMethodField()
    user_detail = serializers.SerializerMethodField()
    group_detail = serializers.SerializerMethodField()

    class Meta(AdminActionBaseSerializer.Meta):
        fields = AdminActionBaseSerializer.Meta.fields + [
            'admin_detail', 'user_detail', 'group_detail',
        ]

    def get_admin_detail(self, obj):
        return UserBaseSerializer(obj.admin).data if obj.admin else None

    def get_user_detail(self, obj):
        return UserBaseSerializer(obj.user).data if obj.user else None

    def get_group_detail(self, obj):
        return GroupListSerializer(obj.group).data if obj.group else None


class AdminActionCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating an admin action log entry.
    """
    admin = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=True,
        help_text=_('Admin user who performed the action')
    )
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        help_text=_('User being acted upon')
    )
    group = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.filter(deleted_at__isnull=True),
        required=False,
        help_text=_('Group being acted upon')
    )
    action = serializers.ChoiceField(
        choices=AdminAction.ACTION_CHOICES,
        required=True,
        help_text=_('Type of action performed')
    )

    class Meta:
        model = AdminAction
        fields = [
            'admin', 'user', 'group', 'action', 'details',
            'ip_address', 'user_agent',
        ]
        extra_kwargs = {
            'details': {'required': False},
            'ip_address': {'required': False},
            'user_agent': {'required': False},
        }

    def validate(self, attrs):
        # If user is provided, ensure user is not the admin (cannot act on self)
        if attrs.get('user') and attrs.get('admin'):
            if attrs['user'] == attrs['admin'] and not attrs['admin'].is_superuser:
                raise serializers.ValidationError(
                    {'user': _('Admin cannot perform actions on themselves.')}
                )
        return attrs

    def create(self, validated_data):
        validated_data['timestamp'] = timezone.now()
        return super().create(validated_data)


# ============================================================================
# ADMIN LOG SERIALIZERS
# ============================================================================

class AdminLogBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer for AdminLog model.
    """
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    admin_email = serializers.SerializerMethodField()
    admin_name = serializers.SerializerMethodField()

    class Meta:
        model = AdminLog
        fields = [
            'id', 'admin', 'admin_email', 'admin_name', 'level', 'level_display',
            'module', 'message', 'details', 'timestamp', 'ip_address',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'level_display', 'admin_email', 'admin_name',
            'timestamp', 'created_at', 'updated_at',
        ]

    def get_admin_email(self, obj) -> str:
        return obj.admin.email if obj.admin else ''

    def get_admin_name(self, obj) -> str:
        return obj.admin.full_name if obj.admin else ''


class AdminLogListSerializer(AdminLogBaseSerializer):
    """
    Lightweight serializer for listing admin logs.
    """
    class Meta(AdminLogBaseSerializer.Meta):
        fields = [
            'id', 'admin_email', 'level', 'level_display',
            'module', 'message', 'timestamp',
        ]


class AdminLogCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating an admin log entry.
    """
    admin = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=True,
        help_text=_('Admin user who performed the activity')
    )
    level = serializers.ChoiceField(
        choices=AdminLog.LEVEL_CHOICES,
        default='info',
        required=False,
        help_text=_('Log level')
    )
    message = serializers.CharField(required=True, help_text=_('Log message'))

    class Meta:
        model = AdminLog
        fields = ['admin', 'level', 'module', 'message', 'details', 'ip_address']
        extra_kwargs = {
            'module': {'required': False},
            'details': {'required': False},
            'ip_address': {'required': False},
        }

    def create(self, validated_data):
        validated_data['timestamp'] = timezone.now()
        return super().create(validated_data)


# ============================================================================
# ADMIN PREFERENCE SERIALIZER
# ============================================================================

class AdminPreferenceSerializer(serializers.ModelSerializer):
    """
    Serializer for AdminPreference model.
    """
    admin_email = serializers.SerializerMethodField()
    admin_name = serializers.SerializerMethodField()

    class Meta:
        model = AdminPreference
        fields = [
            'id', 'admin', 'admin_email', 'admin_name',
            'dashboard_layout', 'notification_preferences',
            'theme', 'language', 'timezone', 'items_per_page',
            'email_notifications', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_admin_email(self, obj) -> str:
        return obj.admin.email if obj.admin else ''

    def get_admin_name(self, obj) -> str:
        return obj.admin.full_name if obj.admin else ''


class AdminPreferenceUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating admin preferences.
    """
    class Meta:
        model = AdminPreference
        fields = [
            'dashboard_layout', 'notification_preferences',
            'theme', 'language', 'timezone', 'items_per_page',
            'email_notifications',
        ]

    def validate_items_per_page(self, value):
        if value < 5 or value > 200:
            raise serializers.ValidationError(_('Items per page must be between 5 and 200.'))
        return value


# ============================================================================
# SYSTEM SETTING SERIALIZERS
# ============================================================================

class SystemSettingSerializer(serializers.ModelSerializer):
    """
    Serializer for SystemSetting model.
    """
    class Meta:
        model = SystemSetting
        fields = [
            'id', 'key', 'value', 'description', 'category',
            'is_public', 'editable', 'created_at', 'updated_at', 'deleted_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'deleted_at']


class SystemSettingCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a system setting.
    """
    key = serializers.CharField(required=True, max_length=100)
    value = serializers.JSONField(required=True)

    class Meta:
        model = SystemSetting
        fields = ['key', 'value', 'description', 'category', 'is_public', 'editable']
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True},
            'category': {'required': False, 'allow_blank': True},
            'is_public': {'required': False, 'default': False},
            'editable': {'required': False, 'default': True},
        }

    def validate_key(self, value):
        if SystemSetting.objects.filter(key=value, deleted_at__isnull=True).exists():
            raise serializers.ValidationError(_('A setting with this key already exists.'))
        return value


class SystemSettingUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a system setting.
    """
    class Meta:
        model = SystemSetting
        fields = ['value', 'description', 'category', 'is_public', 'editable']


class SystemSettingBulkUpdateSerializer(serializers.Serializer):
    """
    Serializer for bulk updating system settings.
    """
    settings = serializers.DictField(
        child=serializers.JSONField(),
        required=True,
        help_text=_('Dictionary of key-value pairs to update')
    )

    def validate_settings(self, value):
        if not value:
            raise serializers.ValidationError(_('At least one setting is required.'))
        return value


# ============================================================================
# MAINTENANCE LOG SERIALIZERS
# ============================================================================

class MaintenanceLogBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer for MaintenanceLog model.
    """
    task_type_display = serializers.CharField(source='get_task_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    initiated_by_email = serializers.SerializerMethodField()
    initiated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceLog
        fields = [
            'id', 'task_type', 'task_type_display', 'status', 'status_display',
            'started_at', 'completed_at', 'duration_seconds', 'result',
            'error_message', 'details', 'initiated_by', 'initiated_by_email',
            'initiated_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'task_type_display', 'status_display',
            'started_at', 'completed_at', 'duration_seconds',
            'created_at', 'updated_at',
        ]

    def get_initiated_by_email(self, obj) -> str:
        return obj.initiated_by.email if obj.initiated_by else 'System'

    def get_initiated_by_name(self, obj) -> str:
        return obj.initiated_by.full_name if obj.initiated_by else 'System'


class MaintenanceLogListSerializer(MaintenanceLogBaseSerializer):
    """
    Lightweight serializer for listing maintenance logs.
    """
    class Meta(MaintenanceLogBaseSerializer.Meta):
        fields = [
            'id', 'task_type', 'task_type_display', 'status', 'status_display',
            'started_at', 'completed_at', 'duration_seconds',
            'initiated_by_email', 'created_at',
        ]


class MaintenanceLogCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a maintenance log entry.
    """
    task_type = serializers.ChoiceField(
        choices=MaintenanceLog.TASK_CHOICES,
        required=True,
        help_text=_('Type of maintenance task')
    )
    initiated_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        help_text=_('User who initiated the task')
    )

    class Meta:
        model = MaintenanceLog
        fields = ['task_type', 'details', 'initiated_by']
        extra_kwargs = {
            'details': {'required': False},
        }


# ============================================================================
# REPORT SERIALIZERS
# ============================================================================

class ReportBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer for Report model.
    """
    report_type_display = serializers.CharField(source='get_report_type_display', read_only=True)
    format_display = serializers.CharField(source='get_format_display', read_only=True)
    generated_by_email = serializers.SerializerMethodField()
    generated_by_name = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)
    age_days = serializers.IntegerField(read_only=True)

    class Meta:
        model = Report
        fields = [
            'id', 'name', 'report_type', 'report_type_display',
            'generated_by', 'generated_by_email', 'generated_by_name',
            'title', 'description', 'data', 'format', 'format_display',
            'file', 'date_range_start', 'date_range_end',
            'parameters', 'generated_at', 'expires_at',
            'is_expired', 'age_days', 'is_public', 'download_count',
            'created_at', 'updated_at', 'deleted_at',
        ]
        read_only_fields = [
            'id', 'report_type_display', 'format_display',
            'generated_by_email', 'generated_by_name',
            'generated_at', 'download_count',
            'is_expired', 'age_days', 'created_at', 'updated_at', 'deleted_at',
        ]

    def get_generated_by_email(self, obj) -> str:
        return obj.generated_by.email if obj.generated_by else ''

    def get_generated_by_name(self, obj) -> str:
        return obj.generated_by.full_name if obj.generated_by else ''


class ReportListSerializer(ReportBaseSerializer):
    """
    Lightweight serializer for listing reports.
    """
    class Meta(ReportBaseSerializer.Meta):
        fields = [
            'id', 'name', 'report_type', 'report_type_display',
            'generated_by_email', 'title', 'format', 'generated_at',
            'is_expired', 'is_public', 'download_count',
        ]


class ReportDetailSerializer(ReportBaseSerializer):
    """
    Detailed serializer with nested relationships.
    """
    generated_by_detail = serializers.SerializerMethodField()

    class Meta(ReportBaseSerializer.Meta):
        fields = ReportBaseSerializer.Meta.fields + ['generated_by_detail']

    def get_generated_by_detail(self, obj):
        return UserBaseSerializer(obj.generated_by).data if obj.generated_by else None


class ReportCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for generating a report.
    """
    name = serializers.CharField(required=True, max_length=255)
    report_type = serializers.ChoiceField(
        choices=Report.REPORT_TYPES,
        default='custom',
        required=False,
        help_text=_('Type of report')
    )
    generated_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        help_text=_('Admin who generated the report')
    )
    format = serializers.ChoiceField(
        choices=Report.FORMAT_CHOICES,
        default='json',
        required=False,
        help_text=_('Output format')
    )
    date_range_start = serializers.DateTimeField(required=False)
    date_range_end = serializers.DateTimeField(required=False)

    class Meta:
        model = Report
        fields = [
            'name', 'report_type', 'generated_by', 'title', 'description',
            'format', 'date_range_start', 'date_range_end', 'parameters',
            'is_public',
        ]
        extra_kwargs = {
            'title': {'required': False},
            'description': {'required': False, 'allow_blank': True},
            'parameters': {'required': False},
            'is_public': {'required': False, 'default': False},
        }

    def validate(self, attrs):
        if attrs.get('date_range_start') and attrs.get('date_range_end'):
            if attrs['date_range_start'] > attrs['date_range_end']:
                raise serializers.ValidationError(
                    {'date_range_start': _('Start date must be before end date.')}
                )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        if not validated_data.get('generated_by') and self.context.get('request'):
            validated_data['generated_by'] = self.context['request'].user
        validated_data['generated_at'] = timezone.now()
        return super().create(validated_data)


class ReportUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a report.
    """
    class Meta:
        model = Report
        fields = ['name', 'title', 'description', 'is_public']


# ============================================================================
# REPORT SCHEDULE SERIALIZERS
# ============================================================================

class ReportScheduleBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer for ReportSchedule model.
    """
    frequency_display = serializers.CharField(source='get_frequency_display', read_only=True)
    created_by_email = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    next_run_display = serializers.SerializerMethodField()
    last_run_display = serializers.SerializerMethodField()

    class Meta:
        model = ReportSchedule
        fields = [
            'id', 'name', 'report_type', 'description', 'recipients',
            'format', 'frequency', 'frequency_display',
            'day_of_week', 'day_of_month', 'time', 'timezone',
            'is_active', 'last_run', 'last_run_display',
            'next_run', 'next_run_display', 'parameters',
            'created_by', 'created_by_email', 'created_by_name',
            'created_at', 'updated_at', 'deleted_at',
        ]
        read_only_fields = [
            'id', 'frequency_display', 'created_by_email', 'created_by_name',
            'last_run', 'next_run', 'created_at', 'updated_at', 'deleted_at',
        ]

    def get_created_by_email(self, obj) -> str:
        return obj.created_by.email if obj.created_by else ''

    def get_created_by_name(self, obj) -> str:
        return obj.created_by.full_name if obj.created_by else ''

    def get_last_run_display(self, obj) -> str:
        if obj.last_run:
            return obj.last_run.strftime('%Y-%m-%d %H:%M')
        return '-'

    def get_next_run_display(self, obj) -> str:
        if obj.next_run:
            return obj.next_run.strftime('%Y-%m-%d %H:%M')
        return '-'


class ReportScheduleListSerializer(ReportScheduleBaseSerializer):
    """
    Lightweight serializer for listing report schedules.
    """
    class Meta(ReportScheduleBaseSerializer.Meta):
        fields = [
            'id', 'name', 'report_type', 'frequency', 'frequency_display',
            'is_active', 'last_run_display', 'next_run_display',
            'created_by_email', 'created_at',
        ]


class ReportScheduleCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a report schedule.
    """
    name = serializers.CharField(required=True, max_length=255)
    frequency = serializers.ChoiceField(
        choices=ReportSchedule.SCHEDULE_FREQUENCIES,
        default='daily',
        required=False,
        help_text=_('Frequency of report generation')
    )
    recipients = serializers.ListField(
        child=serializers.EmailField(),
        required=True,
        help_text=_('List of recipient emails')
    )
    created_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        help_text=_('Admin who created the schedule')
    )

    class Meta:
        model = ReportSchedule
        fields = [
            'name', 'report_type', 'description', 'recipients',
            'format', 'frequency', 'day_of_week', 'day_of_month',
            'time', 'timezone', 'is_active', 'parameters', 'created_by',
        ]
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True},
            'day_of_week': {'required': False},
            'day_of_month': {'required': False},
            'time': {'required': False},
            'timezone': {'required': False},
            'is_active': {'required': False, 'default': True},
            'parameters': {'required': False},
        }

    def validate(self, attrs):
        frequency = attrs.get('frequency', 'daily')

        if frequency == 'weekly' and attrs.get('day_of_week') is None:
            raise serializers.ValidationError(
                {'day_of_week': _('Day of week is required for weekly schedules.')}
            )

        if frequency == 'monthly' and attrs.get('day_of_month') is None:
            raise serializers.ValidationError(
                {'day_of_month': _('Day of month is required for monthly schedules.')}
            )

        return attrs

    def create(self, validated_data):
        if not validated_data.get('created_by') and self.context.get('request'):
            validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


class ReportScheduleUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a report schedule.
    """
    class Meta:
        model = ReportSchedule
        fields = [
            'name', 'description', 'recipients', 'format',
            'frequency', 'day_of_week', 'day_of_month',
            'time', 'timezone', 'is_active', 'parameters',
        ]

    def validate(self, attrs):
        frequency = attrs.get('frequency')

        if frequency == 'weekly' and attrs.get('day_of_week') is None:
            raise serializers.ValidationError(
                {'day_of_week': _('Day of week is required for weekly schedules.')}
            )

        if frequency == 'monthly' and attrs.get('day_of_month') is None:
            raise serializers.ValidationError(
                {'day_of_month': _('Day of month is required for monthly schedules.')}
            )

        return attrs


# ============================================================================
# AUDIT TRAIL SERIALIZER
# ============================================================================

class AuditTrailSerializer(serializers.ModelSerializer):
    """
    Serializer for AuditTrail model.
    """
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    user_email = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    object_display = serializers.SerializerMethodField()
    content_type_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditTrail
        fields = [
            'id', 'user', 'user_email', 'user_name',
            'content_type', 'content_type_name', 'object_id',
            'object_display', 'action', 'action_display',
            'changes', 'ip_address', 'user_agent',
            'timestamp', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'action_display', 'user_email', 'user_name',
            'object_display', 'content_type_name',
            'timestamp', 'created_at', 'updated_at',
        ]

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else 'System'

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else 'System'

    def get_object_display(self, obj) -> str:
        return obj.get_object_display()

    def get_content_type_name(self, obj) -> str:
        return obj.content_type.name if obj.content_type else ''


# ============================================================================
# DASHBOARD WIDGET SERIALIZER
# ============================================================================

class DashboardWidgetSerializer(serializers.ModelSerializer):
    """
    Serializer for DashboardWidget model.
    """
    widget_type_display = serializers.CharField(source='get_widget_type_display', read_only=True)
    admin_email = serializers.SerializerMethodField()
    admin_name = serializers.SerializerMethodField()
    is_user_widget = serializers.BooleanField(read_only=True)

    class Meta:
        model = DashboardWidget
        fields = [
            'id', 'name', 'widget_type', 'widget_type_display',
            'title', 'description', 'configuration',
            'admin', 'admin_email', 'admin_name',
            'is_system', 'is_user_widget', 'is_active',
            'order', 'permissions',
            'created_at', 'updated_at', 'deleted_at',
        ]
        read_only_fields = [
            'id', 'widget_type_display', 'admin_email', 'admin_name',
            'is_user_widget', 'created_at', 'updated_at', 'deleted_at',
        ]

    def get_admin_email(self, obj) -> str:
        return obj.admin.email if obj.admin else ''

    def get_admin_name(self, obj) -> str:
        return obj.admin.full_name if obj.admin else ''


class DashboardWidgetCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a dashboard widget.
    """
    admin = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        help_text=_('Admin user who owns this widget (null for system-wide)')
    )

    class Meta:
        model = DashboardWidget
        fields = [
            'name', 'widget_type', 'title', 'description',
            'configuration', 'admin', 'is_system', 'is_active',
            'order', 'permissions',
        ]
        extra_kwargs = {
            'is_system': {'required': False, 'default': False},
            'is_active': {'required': False, 'default': True},
            'order': {'required': False, 'default': 0},
            'permissions': {'required': False, 'allow_blank': True},
        }


class DashboardWidgetUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a dashboard widget.
    """
    class Meta:
        model = DashboardWidget
        fields = [
            'name', 'title', 'description', 'configuration',
            'is_active', 'order', 'permissions',
        ]


# ============================================================================
# DASHBOARD STATS SERIALIZER
# ============================================================================

class DashboardStatsSerializer(serializers.Serializer):
    """
    Serializer for dashboard statistics.
    """
    users = serializers.DictField()
    groups = serializers.DictField()
    contributions = serializers.DictField()
    payments = serializers.DictField()
    notifications = serializers.DictField()
    system = serializers.DictField()
    trends = serializers.DictField()
    alerts = serializers.ListField()


# ============================================================================
# SYSTEM HEALTH SERIALIZER
# ============================================================================

class SystemHealthSerializer(serializers.Serializer):
    """
    Serializer for system health check.
    """
    status = serializers.CharField()
    checks = serializers.DictField()
    timestamp = serializers.CharField()


# ============================================================================
# ADMIN BULK ACTION SERIALIZER
# ============================================================================

class AdminBulkActionSerializer(serializers.Serializer):
    """
    Serializer for bulk admin actions.
    """
    action = serializers.CharField(required=True, help_text=_('Action to perform'))
    ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        help_text=_('List of IDs to perform action on')
    )
    resource_type = serializers.CharField(
        required=True,
        help_text=_('Type of resource (user, group, payment, contribution)')
    )
    details = serializers.JSONField(
        required=False,
        help_text=_('Additional details for the action')
    )

    def validate_action(self, value):
        valid_actions = [
            'suspend', 'activate', 'delete', 'verify',
            'approve', 'complete', 'cancel', 'pause', 'resume',
            'mark_paid', 'refund', 'fail',
        ]
        if value not in valid_actions:
            raise serializers.ValidationError(
                _(f'Invalid action. Must be one of: {", ".join(valid_actions)}')
            )
        return value

    def validate_resource_type(self, value):
        valid_resources = ['user', 'group', 'payment', 'contribution']
        if value not in valid_resources:
            raise serializers.ValidationError(
                _(f'Invalid resource type. Must be one of: {", ".join(valid_resources)}')
            )
        return value

    def validate(self, attrs):
        if not attrs.get('ids'):
            raise serializers.ValidationError(
                {'ids': _('At least one ID is required.')}
            )
        return attrs


# ============================================================================
# REPORT DATA SERIALIZER
# ============================================================================

class ReportDataSerializer(serializers.Serializer):
    """
    Serializer for report data generation.
    """
    report_type = serializers.ChoiceField(
        choices=Report.REPORT_TYPES,
        required=True,
        help_text=_('Type of report to generate')
    )
    date_range_start = serializers.DateTimeField(required=False)
    date_range_end = serializers.DateTimeField(required=False)
    parameters = serializers.JSONField(required=False)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'AdminActionBaseSerializer',
    'AdminActionListSerializer',
    'AdminActionDetailSerializer',
    'AdminActionCreateSerializer',
    'AdminLogBaseSerializer',
    'AdminLogListSerializer',
    'AdminLogCreateSerializer',
    'AdminPreferenceSerializer',
    'AdminPreferenceUpdateSerializer',
    'SystemSettingSerializer',
    'SystemSettingCreateSerializer',
    'SystemSettingUpdateSerializer',
    'SystemSettingBulkUpdateSerializer',
    'MaintenanceLogBaseSerializer',
    'MaintenanceLogListSerializer',
    'MaintenanceLogCreateSerializer',
    'ReportBaseSerializer',
    'ReportListSerializer',
    'ReportDetailSerializer',
    'ReportCreateSerializer',
    'ReportUpdateSerializer',
    'ReportScheduleBaseSerializer',
    'ReportScheduleListSerializer',
    'ReportScheduleCreateSerializer',
    'ReportScheduleUpdateSerializer',
    'AuditTrailSerializer',
    'DashboardWidgetSerializer',
    'DashboardWidgetCreateSerializer',
    'DashboardWidgetUpdateSerializer',
    'DashboardStatsSerializer',
    'SystemHealthSerializer',
    'AdminBulkActionSerializer',
    'ReportDataSerializer',
]