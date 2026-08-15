"""
Serializers for the audit app.

This module provides comprehensive serializers for all audit models:
- AuditLog serializers (list, detail, create)
- AuditEvent serializers (list, detail, create, process)
- AuditRule serializers (list, detail, create, update)
- AuditAlert serializers (list, detail, create, acknowledge, resolve)
- AuditReport serializers (list, detail, create)
- AuditRetentionPolicy serializers (list, detail, create, update)
- SecurityEvent serializers (list, detail, create)
- UserActivity serializers (list, detail)
- SystemHealth serializers (list, detail, create)
- PerformanceMetric serializers (list, detail, create)
- AnomalyDetection serializers (list, detail, create, resolve)

All serializers include full validation, computed fields, nested relationships,
and proper error handling for all audit operations.
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

from apps.users.models import User
from apps.users.serializers import UserBaseSerializer
from apps.groups.models import Group
from apps.groups.serializers import GroupListSerializer
from apps.common.constants import AuditAction
from apps.common.utils import format_currency, get_current_time

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

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# AUDIT LOG SERIALIZERS
# ============================================================================

class AuditLogBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer with common fields for AuditLog model.
    """
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    user_email = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    severity_color = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            'id', 'user', 'user_email', 'user_name',
            'action', 'action_display', 'resource', 'resource_id',
            'details', 'ip_address', 'user_agent',
            'severity', 'severity_display', 'severity_color',
            'timestamp', 'created_at', 'updated_at', 'deleted_at',
        ]
        read_only_fields = [
            'id', 'action_display', 'severity_display',
            'user_email', 'user_name', 'severity_color',
            'timestamp', 'created_at', 'updated_at', 'deleted_at',
        ]

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else 'System'

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else 'System'

    def get_severity_color(self, obj) -> str:
        colors = {
            'info': 'blue',
            'warning': 'orange',
            'error': 'red',
            'critical': 'darkred',
        }
        return colors.get(obj.severity, 'gray')


class AuditLogListSerializer(AuditLogBaseSerializer):
    """
    Lightweight serializer for listing audit logs.
    """
    class Meta(AuditLogBaseSerializer.Meta):
        fields = [
            'id', 'user_email', 'user_name', 'action', 'action_display',
            'resource', 'severity', 'severity_display', 'severity_color',
            'timestamp',
        ]


class AuditLogDetailSerializer(AuditLogBaseSerializer):
    """
    Detailed serializer with nested relationships.
    """
    user_detail = serializers.SerializerMethodField()
    resource_type_display = serializers.SerializerMethodField()

    class Meta(AuditLogBaseSerializer.Meta):
        fields = AuditLogBaseSerializer.Meta.fields + [
            'user_detail', 'resource_type_display',
        ]

    def get_user_detail(self, obj):
        if obj.user:
            return UserBaseSerializer(obj.user).data
        return None

    def get_resource_type_display(self, obj):
        # Map resource type to human-readable name
        resource_map = {
            'USER': 'User',
            'GROUP': 'Group',
            'PAYMENT': 'Payment',
            'CONTRIBUTION': 'Contribution',
            'PAYOUT': 'Payout',
            'NOTIFICATION': 'Notification',
            'SYSTEM': 'System',
            'ADMIN': 'Admin',
        }
        return resource_map.get(obj.resource, obj.resource)


class AuditLogCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating an audit log entry.
    """
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        help_text=_('User who performed the action (optional)')
    )
    action = serializers.CharField(required=True, max_length=50)
    resource = serializers.CharField(required=True, max_length=50)

    class Meta:
        model = AuditLog
        fields = [
            'user', 'action', 'resource', 'resource_id',
            'details', 'ip_address', 'user_agent', 'severity',
        ]
        extra_kwargs = {
            'resource_id': {'required': False},
            'details': {'required': False},
            'ip_address': {'required': False},
            'user_agent': {'required': False},
            'severity': {'required': False, 'default': 'info'},
        }

    def validate_action(self, value):
        valid_actions = [choice[0] for choice in AuditAction.CHOICES]
        if value not in valid_actions:
            raise serializers.ValidationError(_('Invalid action type.'))
        return value

    def validate_severity(self, value):
        valid_severities = [choice[0] for choice in AuditLog.SEVERITY_CHOICES]
        if value not in valid_severities:
            raise serializers.ValidationError(_('Invalid severity level.'))
        return value

    def create(self, validated_data):
        validated_data['timestamp'] = timezone.now()
        return super().create(validated_data)


# ============================================================================
# AUDIT EVENT SERIALIZERS
# ============================================================================

class AuditEventBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer for AuditEvent model.
    """
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    user_email = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = [
            'id', 'event_type', 'event_type_display',
            'user', 'user_email', 'user_name',
            'group', 'group_name',
            'data', 'processed', 'processed_at',
            'error_message', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'event_type_display', 'user_email', 'user_name',
            'group_name', 'processed', 'processed_at',
            'created_at', 'updated_at',
        ]

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_group_name(self, obj) -> str:
        return obj.group.name if obj.group else ''


class AuditEventListSerializer(AuditEventBaseSerializer):
    """
    Lightweight serializer for listing events.
    """
    class Meta(AuditEventBaseSerializer.Meta):
        fields = [
            'id', 'event_type', 'event_type_display',
            'user_email', 'group_name',
            'processed', 'created_at',
        ]


class AuditEventDetailSerializer(AuditEventBaseSerializer):
    """
    Detailed serializer with nested relationships.
    """
    user_detail = serializers.SerializerMethodField()
    group_detail = serializers.SerializerMethodField()

    class Meta(AuditEventBaseSerializer.Meta):
        fields = AuditEventBaseSerializer.Meta.fields + [
            'user_detail', 'group_detail',
        ]

    def get_user_detail(self, obj):
        return UserBaseSerializer(obj.user).data if obj.user else None

    def get_group_detail(self, obj):
        return GroupListSerializer(obj.group).data if obj.group else None


class AuditEventCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating an audit event.
    """
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=True,
        help_text=_('User associated with the event')
    )
    event_type = serializers.ChoiceField(
        choices=AuditEvent.EVENT_TYPES,
        required=True,
        help_text=_('Type of event')
    )
    group = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.filter(deleted_at__isnull=True),
        required=False,
        help_text=_('Group associated with the event')
    )

    class Meta:
        model = AuditEvent
        fields = ['event_type', 'user', 'group', 'data']
        extra_kwargs = {
            'data': {'required': False},
        }


# ============================================================================
# AUDIT RULE SERIALIZERS
# ============================================================================

class AuditRuleBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer for AuditRule model.
    """
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    is_active_display = serializers.SerializerMethodField()

    class Meta:
        model = AuditRule
        fields = [
            'id', 'name', 'description', 'condition',
            'action', 'action_display', 'severity', 'severity_display',
            'is_active', 'is_active_display',
            'trigger_count', 'last_triggered',
            'created_at', 'updated_at', 'deleted_at',
        ]
        read_only_fields = [
            'id', 'action_display', 'severity_display',
            'is_active_display', 'trigger_count', 'last_triggered',
            'created_at', 'updated_at', 'deleted_at',
        ]

    def get_is_active_display(self, obj):
        return '✓ Active' if obj.is_active else '✗ Inactive'


class AuditRuleListSerializer(AuditRuleBaseSerializer):
    """
    Lightweight serializer for listing rules.
    """
    class Meta(AuditRuleBaseSerializer.Meta):
        fields = [
            'id', 'name', 'action', 'severity',
            'is_active_display', 'trigger_count', 'last_triggered',
        ]


class AuditRuleDetailSerializer(AuditRuleBaseSerializer):
    """
    Detailed serializer for rules.
    """
    alerts = serializers.SerializerMethodField()

    class Meta(AuditRuleBaseSerializer.Meta):
        fields = AuditRuleBaseSerializer.Meta.fields + ['alerts']

    def get_alerts(self, obj):
        alerts = obj.alerts.all().order_by('-timestamp')[:10]
        return AuditAlertListSerializer(alerts, many=True).data


class AuditRuleCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating an audit rule.
    """
    name = serializers.CharField(required=True, max_length=255)
    condition = serializers.JSONField(required=True)
    action = serializers.ChoiceField(
        choices=AuditRule.ACTION_CHOICES,
        default='log',
        required=False,
        help_text=_('Action to take')
    )
    severity = serializers.ChoiceField(
        choices=AuditLog.SEVERITY_CHOICES,
        default='warning',
        required=False,
        help_text=_('Severity level')
    )

    class Meta:
        model = AuditRule
        fields = [
            'name', 'description', 'condition',
            'action', 'severity', 'is_active',
        ]
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True},
            'is_active': {'required': False, 'default': True},
        }

    def validate_condition(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(_('Condition must be a JSON object.'))
        if not value:
            raise serializers.ValidationError(_('Condition cannot be empty.'))
        # Validate condition fields
        valid_keys = ['action', 'resource', 'severity', 'user_id', 'resource_id']
        for key in value.keys():
            if key not in valid_keys:
                raise serializers.ValidationError(_(f'Invalid condition key: {key}'))
        return value


class AuditRuleUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating an audit rule.
    """
    class Meta:
        model = AuditRule
        fields = [
            'name', 'description', 'condition',
            'action', 'severity', 'is_active',
        ]


# ============================================================================
# AUDIT ALERT SERIALIZERS
# ============================================================================

class AuditAlertBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer for AuditAlert model.
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    rule_name = serializers.SerializerMethodField()
    acknowledged_by_email = serializers.SerializerMethodField()

    class Meta:
        model = AuditAlert
        fields = [
            'id', 'rule', 'rule_name', 'audit_log',
            'severity', 'severity_display', 'message',
            'status', 'status_display',
            'acknowledged_by', 'acknowledged_by_email',
            'acknowledged_at', 'resolved_at',
            'timestamp', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'rule_name', 'severity_display',
            'status_display', 'acknowledged_by_email',
            'timestamp', 'created_at', 'updated_at',
        ]

    def get_rule_name(self, obj):
        return obj.rule.name if obj.rule else ''

    def get_acknowledged_by_email(self, obj):
        return obj.acknowledged_by.email if obj.acknowledged_by else ''


class AuditAlertListSerializer(AuditAlertBaseSerializer):
    """
    Lightweight serializer for listing alerts.
    """
    class Meta(AuditAlertBaseSerializer.Meta):
        fields = [
            'id', 'rule_name', 'severity_display', 'message',
            'status_display', 'timestamp',
        ]


class AuditAlertDetailSerializer(AuditAlertBaseSerializer):
    """
    Detailed serializer for alerts.
    """
    rule_detail = serializers.SerializerMethodField()
    audit_log_detail = serializers.SerializerMethodField()

    class Meta(AuditAlertBaseSerializer.Meta):
        fields = AuditAlertBaseSerializer.Meta.fields + [
            'rule_detail', 'audit_log_detail',
        ]

    def get_rule_detail(self, obj):
        return AuditRuleListSerializer(obj.rule).data if obj.rule else None

    def get_audit_log_detail(self, obj):
        return AuditLogListSerializer(obj.audit_log).data if obj.audit_log else None


class AuditAlertAcknowledgeSerializer(serializers.Serializer):
    """
    Serializer for acknowledging an alert.
    """
    user_id = serializers.IntegerField(required=True, help_text=_('User acknowledging the alert'))

    def validate_user_id(self, value):
        try:
            user = User.objects.get(id=value, is_active=True)
            return user
        except User.DoesNotExist:
            raise serializers.ValidationError(_('User not found.'))


# ============================================================================
# AUDIT REPORT SERIALIZERS
# ============================================================================

class AuditReportBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer for AuditReport model.
    """
    report_type_display = serializers.CharField(source='get_report_type_display', read_only=True)
    format_display = serializers.CharField(source='get_format_display', read_only=True)
    generated_by_email = serializers.SerializerMethodField()
    generated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditReport
        fields = [
            'id', 'name', 'description', 'report_type', 'report_type_display',
            'parameters', 'generated_by', 'generated_by_email', 'generated_by_name',
            'format', 'format_display', 'data', 'file',
            'date_range_start', 'date_range_end',
            'generated_at', 'expires_at', 'is_public', 'download_count',
            'created_at', 'updated_at', 'deleted_at',
        ]
        read_only_fields = [
            'id', 'report_type_display', 'format_display',
            'generated_by_email', 'generated_by_name',
            'generated_at', 'download_count',
            'created_at', 'updated_at', 'deleted_at',
        ]

    def get_generated_by_email(self, obj) -> str:
        return obj.generated_by.email if obj.generated_by else ''

    def get_generated_by_name(self, obj) -> str:
        return obj.generated_by.full_name if obj.generated_by else ''


class AuditReportListSerializer(AuditReportBaseSerializer):
    """
    Lightweight serializer for listing audit reports.
    """
    class Meta(AuditReportBaseSerializer.Meta):
        fields = [
            'id', 'name', 'report_type_display', 'format_display',
            'generated_by_email', 'generated_at', 'download_count',
        ]


class AuditReportCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for generating an audit report.
    """
    generated_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        help_text=_('User generating the report')
    )

    class Meta:
        model = AuditReport
        fields = [
            'name', 'description', 'report_type', 'parameters',
            'generated_by', 'format', 'date_range_start', 'date_range_end',
            'is_public',
        ]
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True},
            'parameters': {'required': False},
            'format': {'required': False, 'default': 'json'},
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


# ============================================================================
# AUDIT RETENTION POLICY SERIALIZER
# ============================================================================

class AuditRetentionPolicySerializer(serializers.ModelSerializer):
    """
    Serializer for AuditRetentionPolicy model.
    """
    resource_type_display = serializers.CharField(source='get_resource_type_display', read_only=True)

    class Meta:
        model = AuditRetentionPolicy
        fields = [
            'id', 'resource_type', 'resource_type_display',
            'retention_days', 'description', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class AuditRetentionPolicyCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a retention policy.
    """
    class Meta:
        model = AuditRetentionPolicy
        fields = ['resource_type', 'retention_days', 'description', 'is_active']
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True},
            'is_active': {'required': False, 'default': True},
        }

    def validate_resource_type(self, value):
        if AuditRetentionPolicy.objects.filter(resource_type=value).exists():
            raise serializers.ValidationError(_('A policy for this resource type already exists.'))
        return value


# ============================================================================
# SECURITY EVENT SERIALIZERS
# ============================================================================

class SecurityEventBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer for SecurityEvent model.
    """
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    user_email = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = SecurityEvent
        fields = [
            'id', 'user', 'user_email', 'user_name',
            'event_type', 'event_type_display',
            'description', 'severity', 'severity_display',
            'details', 'ip_address', 'user_agent',
            'timestamp', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'event_type_display', 'severity_display',
            'user_email', 'user_name', 'timestamp',
            'created_at', 'updated_at',
        ]

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''


class SecurityEventListSerializer(SecurityEventBaseSerializer):
    """
    Lightweight serializer for listing security events.
    """
    class Meta(SecurityEventBaseSerializer.Meta):
        fields = [
            'id', 'user_email', 'event_type_display',
            'description', 'severity_display', 'timestamp',
        ]


class SecurityEventCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a security event.
    """
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=True,
        help_text=_('User associated with the event')
    )
    event_type = serializers.ChoiceField(
        choices=SecurityEvent.SECURITY_EVENT_TYPES,
        required=True,
        help_text=_('Type of security event')
    )

    class Meta:
        model = SecurityEvent
        fields = [
            'user', 'event_type', 'description',
            'severity', 'details', 'ip_address', 'user_agent',
        ]
        extra_kwargs = {
            'severity': {'required': False, 'default': 'warning'},
            'details': {'required': False},
            'ip_address': {'required': False},
            'user_agent': {'required': False},
        }


# ============================================================================
# USER ACTIVITY SERIALIZER
# ============================================================================

class UserActivitySerializer(serializers.ModelSerializer):
    """
    Serializer for UserActivity model.
    """
    user_email = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    resource_type_display = serializers.SerializerMethodField()

    class Meta:
        model = UserActivity
        fields = [
            'id', 'user', 'user_email', 'user_name',
            'action', 'resource', 'resource_id', 'resource_type_display',
            'details', 'session_id', 'ip_address', 'user_agent',
            'timestamp', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user_email', 'user_name', 'resource_type_display',
            'timestamp', 'created_at', 'updated_at',
        ]

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_resource_type_display(self, obj):
        resource_map = {
            'USER': 'User',
            'GROUP': 'Group',
            'PAYMENT': 'Payment',
            'CONTRIBUTION': 'Contribution',
            'PAYOUT': 'Payout',
            'NOTIFICATION': 'Notification',
        }
        return resource_map.get(obj.resource, obj.resource)


class UserActivityCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a user activity record.
    """
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=True,
        help_text=_('User performing the activity')
    )
    action = serializers.CharField(required=True, max_length=50)

    class Meta:
        model = UserActivity
        fields = [
            'user', 'action', 'resource', 'resource_id',
            'details', 'session_id', 'ip_address', 'user_agent',
        ]
        extra_kwargs = {
            'resource_id': {'required': False},
            'details': {'required': False},
            'session_id': {'required': False},
            'ip_address': {'required': False},
            'user_agent': {'required': False},
        }


# ============================================================================
# SYSTEM HEALTH SERIALIZER
# ============================================================================

class SystemHealthSerializer(serializers.ModelSerializer):
    """
    Serializer for SystemHealth model.
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = SystemHealth
        fields = [
            'id', 'component', 'status', 'status_display',
            'message', 'details', 'checked_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'status_display', 'checked_at',
            'created_at', 'updated_at',
        ]


class SystemHealthCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a system health check record.
    """
    component = serializers.CharField(required=True, max_length=50)
    status = serializers.ChoiceField(
        choices=SystemHealth.STATUS_CHOICES,
        default='ok',
        required=False,
        help_text=_('Status')
    )

    class Meta:
        model = SystemHealth
        fields = ['component', 'status', 'message', 'details']


# ============================================================================
# PERFORMANCE METRIC SERIALIZER
# ============================================================================

class PerformanceMetricSerializer(serializers.ModelSerializer):
    """
    Serializer for PerformanceMetric model.
    """
    value_display = serializers.SerializerMethodField()

    class Meta:
        model = PerformanceMetric
        fields = [
            'id', 'metric_name', 'value', 'value_display',
            'unit', 'labels', 'timestamp',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'timestamp', 'created_at', 'updated_at']

    def get_value_display(self, obj):
        if obj.unit == 'ms':
            if obj.value < 1:
                return f"{obj.value * 1000:.2f} µs"
            return f"{obj.value:.2f} ms"
        return f"{obj.value} {obj.unit}"


class PerformanceMetricCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a performance metric.
    """
    metric_name = serializers.CharField(required=True, max_length=100)
    value = serializers.DecimalField(required=True, max_digits=20, decimal_places=4)

    class Meta:
        model = PerformanceMetric
        fields = ['metric_name', 'value', 'unit', 'labels']
        extra_kwargs = {
            'unit': {'required': False, 'default': 'ms'},
            'labels': {'required': False},
        }


# ============================================================================
# ANOMALY DETECTION SERIALIZER
# ============================================================================

class AnomalyDetectionBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer for AnomalyDetection model.
    """
    anomaly_type_display = serializers.CharField(source='get_anomaly_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)

    class Meta:
        model = AnomalyDetection
        fields = [
            'id', 'anomaly_type', 'anomaly_type_display',
            'metric_name', 'value', 'baseline', 'z_score',
            'severity', 'severity_display',
            'description', 'status', 'status_display',
            'detected_at', 'resolved_at', 'details',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'anomaly_type_display', 'status_display',
            'severity_display', 'detected_at',
            'created_at', 'updated_at',
        ]


class AnomalyDetectionListSerializer(AnomalyDetectionBaseSerializer):
    """
    Lightweight serializer for listing anomalies.
    """
    class Meta(AnomalyDetectionBaseSerializer.Meta):
        fields = [
            'id', 'anomaly_type_display', 'metric_name',
            'value', 'severity_display', 'status_display',
            'detected_at',
        ]


class AnomalyDetectionCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating an anomaly detection record.
    """
    anomaly_type = serializers.ChoiceField(
        choices=AnomalyDetection.ANOMALY_TYPES,
        required=True,
        help_text=_('Type of anomaly')
    )
    metric_name = serializers.CharField(required=True, max_length=100)
    value = serializers.DecimalField(required=True, max_digits=20, decimal_places=4)

    class Meta:
        model = AnomalyDetection
        fields = [
            'anomaly_type', 'metric_name', 'value', 'baseline',
            'z_score', 'severity', 'description', 'details',
        ]
        extra_kwargs = {
            'baseline': {'required': False},
            'z_score': {'required': False},
            'severity': {'required': False, 'default': 'warning'},
            'description': {'required': True},
            'details': {'required': False},
        }


class AnomalyDetectionUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating an anomaly detection (status).
    """
    class Meta:
        model = AnomalyDetection
        fields = ['status']
        extra_kwargs = {
            'status': {'required': True},
        }


# ============================================================================
# STATISTICS SERIALIZERS
# ============================================================================

class AuditStatisticsSerializer(serializers.Serializer):
    """
    Serializer for audit statistics.
    """
    total_logs = serializers.IntegerField()
    by_action = serializers.DictField(child=serializers.IntegerField())
    by_resource = serializers.DictField(child=serializers.IntegerField())
    by_severity = serializers.DictField(child=serializers.IntegerField())
    by_user = serializers.DictField(child=serializers.IntegerField())
    time_range = serializers.DictField()


class SecurityStatisticsSerializer(serializers.Serializer):
    """
    Serializer for security event statistics.
    """
    total_events = serializers.IntegerField()
    by_event_type = serializers.DictField(child=serializers.IntegerField())
    by_severity = serializers.DictField(child=serializers.IntegerField())
    suspicious_events = serializers.IntegerField()
    time_range = serializers.DictField()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'AuditLogBaseSerializer',
    'AuditLogListSerializer',
    'AuditLogDetailSerializer',
    'AuditLogCreateSerializer',
    'AuditEventBaseSerializer',
    'AuditEventListSerializer',
    'AuditEventDetailSerializer',
    'AuditEventCreateSerializer',
    'AuditRuleBaseSerializer',
    'AuditRuleListSerializer',
    'AuditRuleDetailSerializer',
    'AuditRuleCreateSerializer',
    'AuditRuleUpdateSerializer',
    'AuditAlertBaseSerializer',
    'AuditAlertListSerializer',
    'AuditAlertDetailSerializer',
    'AuditAlertAcknowledgeSerializer',
    'AuditReportBaseSerializer',
    'AuditReportListSerializer',
    'AuditReportCreateSerializer',
    'AuditRetentionPolicySerializer',
    'AuditRetentionPolicyCreateSerializer',
    'SecurityEventBaseSerializer',
    'SecurityEventListSerializer',
    'SecurityEventCreateSerializer',
    'UserActivitySerializer',
    'UserActivityCreateSerializer',
    'SystemHealthSerializer',
    'SystemHealthCreateSerializer',
    'PerformanceMetricSerializer',
    'PerformanceMetricCreateSerializer',
    'AnomalyDetectionBaseSerializer',
    'AnomalyDetectionListSerializer',
    'AnomalyDetectionCreateSerializer',
    'AnomalyDetectionUpdateSerializer',
    'AuditStatisticsSerializer',
    'SecurityStatisticsSerializer',
]