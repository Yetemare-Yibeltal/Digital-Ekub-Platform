"""
Models for the audit app.

This module defines all database models related to auditing and monitoring:
- AuditLog: Central audit log for all system actions
- AuditEvent: Event-based audit records
- AuditRule: Rules for audit filtering and alerting
- AuditAlert: Alerts generated from audit rules
- AuditReport: Scheduled or on-demand audit reports
- AuditRetentionPolicy: Data retention policies
- SecurityEvent: Security-related events (login attempts, suspicious activity, etc.)
- UserActivity: User activity tracking and analytics
- SystemHealth: System health monitoring
- PerformanceMetric: Performance and latency metrics
- AnomalyDetection: Detected anomalies and outliers

All models include comprehensive fields, methods, properties, validation,
and business logic for full auditing, monitoring, and compliance.
"""

from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, F, Sum, Count, Avg, Max, Min
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from decimal import Decimal
import uuid
import json
import logging
from typing import Optional, List, Tuple, Dict, Any, Union
from datetime import timedelta, date, datetime

from apps.users.models import User
from apps.groups.models import Group
from apps.common.constants import AuditAction, NotificationType, NotificationPriority

logger = logging.getLogger(__name__)


# ============================================================================
# AUDIT LOG MODEL
# ============================================================================

class AuditLog(models.Model):
    """
    Central audit log for all system actions.

    Fields:
    - user: User who performed the action (or null for system)
    - action: Action performed (CREATE, UPDATE, DELETE, VIEW, LOGIN, LOGOUT, etc.)
    - resource: Resource type (USER, GROUP, PAYMENT, CONTRIBUTION, etc.)
    - resource_id: ID of the resource
    - details: Additional details as JSON
    - ip_address: IP address of the user
    - user_agent: User agent of the user's browser
    - severity: Severity level (info, warning, error, critical)
    - timestamp: When the action occurred
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - get_summary(): Get summary dictionary
    - get_action_display(): Get human-readable action display

    Indexes: user, action, resource, timestamp, severity
    """

    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User who performed the action (or null for system)')
    )

    action = models.CharField(
        _('action'),
        max_length=50,
        db_index=True,
        help_text=_('Action performed (e.g., CREATE, UPDATE, DELETE, VIEW)')
    )

    resource = models.CharField(
        _('resource'),
        max_length=50,
        db_index=True,
        help_text=_('Resource type (e.g., USER, GROUP, PAYMENT)')
    )

    resource_id = models.PositiveIntegerField(
        _('resource ID'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('ID of the resource')
    )

    details = models.JSONField(
        _('details'),
        default=dict,
        help_text=_('Additional details about the action')
    )

    ip_address = models.GenericIPAddressField(
        _('IP address'),
        null=True,
        blank=True,
        help_text=_('IP address of the user')
    )

    user_agent = models.CharField(
        _('user agent'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('User agent of the user\'s browser')
    )

    severity = models.CharField(
        _('severity'),
        max_length=10,
        choices=SEVERITY_CHOICES,
        default='info',
        db_index=True,
        help_text=_('Severity level')
    )

    timestamp = models.DateTimeField(
        _('timestamp'),
        default=timezone.now,
        db_index=True,
        help_text=_('When the action occurred')
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
        db_table = 'audit_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'action']),
            models.Index(fields=['resource', 'resource_id']),
            models.Index(fields=['timestamp', 'severity']),
            models.Index(fields=['action', 'timestamp']),
        ]
        verbose_name = _('audit log')
        verbose_name_plural = _('audit logs')

    def __str__(self):
        return f"{self.action} on {self.resource} by {self.user.email if self.user else 'System'} at {self.timestamp}"

    def save(self, *args, **kwargs):
        if not self.timestamp:
            self.timestamp = timezone.now()
        super().save(*args, **kwargs)

    @property
    def action_display(self) -> str:
        """Get human-readable action display."""
        return dict(AuditAction.CHOICES).get(self.action, self.action)

    @property
    def severity_display(self) -> str:
        """Get human-readable severity display."""
        return dict(self.SEVERITY_CHOICES).get(self.severity, self.severity)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary dictionary for the audit log."""
        return {
            'id': self.id,
            'user_id': self.user.id if self.user else None,
            'user_email': self.user.email if self.user else 'System',
            'action': self.action,
            'action_display': self.action_display,
            'resource': self.resource,
            'resource_id': self.resource_id,
            'details': self.details,
            'ip_address': self.ip_address,
            'severity': self.severity,
            'timestamp': self.timestamp.isoformat(),
        }


# ============================================================================
# AUDIT EVENT MODEL
# ============================================================================

class AuditEvent(models.Model):
    """
    Event-based audit records for real-time monitoring.

    Fields:
    - event_type: Type of event (e.g., 'user.login', 'payment.processed')
    - user: User associated with the event
    - group: Group associated with the event
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

    EVENT_TYPES = [
        ('user.login', 'User Login'),
        ('user.logout', 'User Logout'),
        ('user.register', 'User Registration'),
        ('user.profile_update', 'Profile Update'),
        ('user.password_change', 'Password Change'),
        ('group.create', 'Group Created'),
        ('group.update', 'Group Updated'),
        ('group.delete', 'Group Deleted'),
        ('group.join', 'User Joined Group'),
        ('group.leave', 'User Left Group'),
        ('payment.initiated', 'Payment Initiated'),
        ('payment.completed', 'Payment Completed'),
        ('payment.failed', 'Payment Failed'),
        ('payment.refunded', 'Payment Refunded'),
        ('contribution.paid', 'Contribution Paid'),
        ('contribution.overdue', 'Contribution Overdue'),
        ('payout.completed', 'Payout Completed'),
        ('payout.failed', 'Payout Failed'),
        ('system.startup', 'System Startup'),
        ('system.shutdown', 'System Shutdown'),
        ('system.maintenance', 'System Maintenance'),
        ('security.alert', 'Security Alert'),
        ('admin.action', 'Admin Action'),
    ]

    event_type = models.CharField(
        _('event type'),
        max_length=50,
        choices=EVENT_TYPES,
        db_index=True,
        help_text=_('Type of event')
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='audit_events',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User associated with the event')
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_events',
        verbose_name=_('group'),
        help_text=_('Group associated with the event')
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
        db_table = 'audit_events'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type', 'processed']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['processed', 'created_at']),
        ]
        verbose_name = _('audit event')
        verbose_name_plural = _('audit events')

    def __str__(self):
        return f"Event #{self.id} - {self.event_type} - {'processed' if self.processed else 'pending'}"

    def process(self) -> bool:
        """Process the event and generate notifications."""
        if self.processed:
            return True

        try:
            # This would call a task or trigger notification generation
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
# AUDIT RULE MODEL
# ============================================================================

class AuditRule(models.Model):
    """
    Rules for audit filtering and alerting.

    Fields:
    - name: Rule name
    - description: Rule description
    - condition: JSON condition for matching (e.g., {"action": "CREATE", "resource": "USER"})
    - action: Action to take when condition is met (log, alert, notify)
    - severity: Severity level
    - is_active: Whether the rule is active
    - trigger_count: Number of times triggered
    - last_triggered: Last trigger timestamp
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - evaluate(): Evaluate the rule against an audit log
    - trigger(): Trigger the rule action

    Indexes: is_active, severity, last_triggered
    """

    ACTION_CHOICES = [
        ('log', 'Log Only'),
        ('alert', 'Generate Alert'),
        ('notify', 'Send Notification'),
        ('block', 'Block Action'),
    ]

    name = models.CharField(
        _('name'),
        max_length=255,
        db_index=True,
        help_text=_('Rule name')
    )

    description = models.TextField(
        _('description'),
        blank=True,
        null=True,
        help_text=_('Rule description')
    )

    condition = models.JSONField(
        _('condition'),
        default=dict,
        help_text=_('JSON condition for matching (e.g., {"action": "CREATE", "resource": "USER"})')
    )

    action = models.CharField(
        _('action'),
        max_length=10,
        choices=ACTION_CHOICES,
        default='log',
        help_text=_('Action to take when condition is met')
    )

    severity = models.CharField(
        _('severity'),
        max_length=10,
        choices=AuditLog.SEVERITY_CHOICES,
        default='warning',
        help_text=_('Severity level')
    )

    is_active = models.BooleanField(
        _('is active'),
        default=True,
        db_index=True,
        help_text=_('Whether the rule is active')
    )

    trigger_count = models.PositiveIntegerField(
        _('trigger count'),
        default=0,
        help_text=_('Number of times triggered')
    )

    last_triggered = models.DateTimeField(
        _('last triggered'),
        null=True,
        blank=True,
        help_text=_('Last trigger timestamp')
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
        db_table = 'audit_rules'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'severity']),
            models.Index(fields=['last_triggered']),
        ]
        verbose_name = _('audit rule')
        verbose_name_plural = _('audit rules')

    def __str__(self):
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"

    def evaluate(self, audit_log: AuditLog) -> bool:
        """
        Evaluate the rule against an audit log entry.

        Args:
            audit_log: AuditLog instance to evaluate

        Returns:
            bool: True if the rule matches
        """
        condition = self.condition
        for key, value in condition.items():
            if hasattr(audit_log, key):
                if getattr(audit_log, key) != value:
                    return False
            else:
                # Check in details
                if audit_log.details.get(key) != value:
                    return False
        return True

    def trigger(self, audit_log: AuditLog) -> None:
        """
        Trigger the rule action.

        Args:
            audit_log: The audit log that triggered the rule
        """
        self.trigger_count += 1
        self.last_triggered = timezone.now()
        self.save(update_fields=['trigger_count', 'last_triggered'])

        if self.action == 'alert':
            # Create an alert
            AuditAlert.objects.create(
                rule=self,
                audit_log=audit_log,
                severity=self.severity,
                message=f"Rule '{self.name}' triggered by {audit_log.action} on {audit_log.resource}",
                timestamp=timezone.now(),
            )
        elif self.action == 'notify':
            # Send notification
            from apps.notifications.tasks import send_notification
            if audit_log.user:
                # Notify the user
                send_notification.delay({
                    'user_id': audit_log.user.id,
                    'email': audit_log.user.email,
                    'message': f"Rule '{self.name}' triggered by your action.",
                    'notification_type': 'security',
                })
        # 'log' action does nothing additional; audit_log already created


# ============================================================================
# AUDIT ALERT MODEL
# ============================================================================

class AuditAlert(models.Model):
    """
    Alerts generated from audit rules.

    Fields:
    - rule: The rule that generated the alert
    - audit_log: The audit log that triggered the alert
    - severity: Severity level
    - message: Alert message
    - status: Status (new, acknowledged, resolved, dismissed)
    - acknowledged_by: User who acknowledged the alert
    - acknowledged_at: When the alert was acknowledged
    - resolved_at: When the alert was resolved
    - timestamp: When the alert was created
    - created_at, updated_at: Timestamps

    Methods:
    - acknowledge(): Acknowledge the alert
    - resolve(): Resolve the alert
    - dismiss(): Dismiss the alert

    Indexes: rule, status, severity, timestamp
    """

    STATUS_CHOICES = [
        ('new', 'New'),
        ('acknowledged', 'Acknowledged'),
        ('resolved', 'Resolved'),
        ('dismissed', 'Dismissed'),
    ]

    rule = models.ForeignKey(
        AuditRule,
        on_delete=models.CASCADE,
        related_name='alerts',
        verbose_name=_('rule'),
        db_index=True,
        help_text=_('The rule that generated the alert')
    )

    audit_log = models.ForeignKey(
        AuditLog,
        on_delete=models.CASCADE,
        related_name='alerts',
        verbose_name=_('audit log'),
        help_text=_('The audit log that triggered the alert')
    )

    severity = models.CharField(
        _('severity'),
        max_length=10,
        choices=AuditLog.SEVERITY_CHOICES,
        default='warning',
        db_index=True,
        help_text=_('Severity level')
    )

    message = models.TextField(
        _('message'),
        help_text=_('Alert message')
    )

    status = models.CharField(
        _('status'),
        max_length=15,
        choices=STATUS_CHOICES,
        default='new',
        db_index=True,
        help_text=_('Alert status')
    )

    acknowledged_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_alerts_acknowledged',
        verbose_name=_('acknowledged by'),
        help_text=_('User who acknowledged the alert')
    )

    acknowledged_at = models.DateTimeField(
        _('acknowledged at'),
        null=True,
        blank=True,
        help_text=_('When the alert was acknowledged')
    )

    resolved_at = models.DateTimeField(
        _('resolved at'),
        null=True,
        blank=True,
        help_text=_('When the alert was resolved')
    )

    timestamp = models.DateTimeField(
        _('timestamp'),
        default=timezone.now,
        db_index=True,
        help_text=_('When the alert was created')
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
        db_table = 'audit_alerts'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['rule', 'status']),
            models.Index(fields=['status', 'severity']),
            models.Index(fields=['timestamp', 'status']),
        ]
        verbose_name = _('audit alert')
        verbose_name_plural = _('audit alerts')

    def __str__(self):
        return f"Alert #{self.id} - {self.status} - {self.severity}"

    def acknowledge(self, user: User) -> None:
        """Acknowledge the alert."""
        if self.status == 'new':
            self.status = 'acknowledged'
            self.acknowledged_by = user
            self.acknowledged_at = timezone.now()
            self.save()
            logger.info(f'Alert {self.id} acknowledged by {user.email}')

    def resolve(self) -> None:
        """Resolve the alert."""
        if self.status in ['new', 'acknowledged']:
            self.status = 'resolved'
            self.resolved_at = timezone.now()
            self.save()
            logger.info(f'Alert {self.id} resolved')

    def dismiss(self) -> None:
        """Dismiss the alert."""
        if self.status == 'new':
            self.status = 'dismissed'
            self.save()
            logger.info(f'Alert {self.id} dismissed')


# ============================================================================
# AUDIT REPORT MODEL
# ============================================================================

class AuditReport(models.Model):
    """
    Scheduled or on-demand audit reports.

    Fields:
    - name: Report name
    - description: Report description
    - report_type: Type (compliance, security, activity, custom)
    - parameters: JSON parameters
    - generated_by: User who generated the report
    - format: Output format (json, csv, pdf)
    - data: JSON report data
    - file: Optional file attachment
    - date_range_start: Start date
    - date_range_end: End date
    - generated_at: When the report was generated
    - expires_at: Expiry timestamp
    - is_public: Whether publicly accessible
    - download_count: Number of downloads
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - get_summary(): Get summary dictionary
    - increment_download(): Increment download count

    Indexes: report_type, generated_by, generated_at, expires_at
    """

    REPORT_TYPES = [
        ('compliance', 'Compliance Report'),
        ('security', 'Security Report'),
        ('activity', 'Activity Report'),
        ('custom', 'Custom Report'),
    ]

    FORMAT_CHOICES = [
        ('json', 'JSON'),
        ('csv', 'CSV'),
        ('pdf', 'PDF'),
    ]

    name = models.CharField(
        _('name'),
        max_length=255,
        db_index=True,
        help_text=_('Report name')
    )

    description = models.TextField(
        _('description'),
        blank=True,
        null=True,
        help_text=_('Report description')
    )

    report_type = models.CharField(
        _('report type'),
        max_length=10,
        choices=REPORT_TYPES,
        default='custom',
        db_index=True,
        help_text=_('Type of report')
    )

    parameters = models.JSONField(
        _('parameters'),
        default=dict,
        help_text=_('JSON parameters')
    )

    generated_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='audit_reports',
        verbose_name=_('generated by'),
        db_index=True,
        help_text=_('User who generated the report')
    )

    format = models.CharField(
        _('format'),
        max_length=10,
        choices=FORMAT_CHOICES,
        default='json',
        help_text=_('Output format')
    )

    data = models.JSONField(
        _('data'),
        default=dict,
        help_text=_('JSON report data')
    )

    file = models.FileField(
        _('file'),
        upload_to='audit_reports/%Y/%m/%d/',
        null=True,
        blank=True,
        help_text=_('Optional file attachment')
    )

    date_range_start = models.DateTimeField(
        _('date range start'),
        null=True,
        blank=True,
        help_text=_('Start date for report data')
    )

    date_range_end = models.DateTimeField(
        _('date range end'),
        null=True,
        blank=True,
        help_text=_('End date for report data')
    )

    generated_at = models.DateTimeField(
        _('generated at'),
        default=timezone.now,
        db_index=True,
        help_text=_('When the report was generated')
    )

    expires_at = models.DateTimeField(
        _('expires at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('Expiry timestamp')
    )

    is_public = models.BooleanField(
        _('is public'),
        default=False,
        db_index=True,
        help_text=_('Whether publicly accessible')
    )

    download_count = models.PositiveIntegerField(
        _('download count'),
        default=0,
        help_text=_('Number of downloads')
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
        db_table = 'audit_reports'
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['report_type', 'generated_at']),
            models.Index(fields=['generated_by', 'generated_at']),
            models.Index(fields=['expires_at']),
        ]
        verbose_name = _('audit report')
        verbose_name_plural = _('audit reports')

    def __str__(self):
        return f"{self.name} ({self.get_report_type_display()})"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = self.generated_at + timedelta(days=90)
        super().save(*args, **kwargs)

    def get_summary(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'report_type': self.report_type,
            'generated_by': self.generated_by.id,
            'generated_by_email': self.generated_by.email,
            'format': self.format,
            'generated_at': self.generated_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_public': self.is_public,
            'download_count': self.download_count,
        }

    def increment_download(self) -> None:
        self.download_count += 1
        self.save(update_fields=['download_count'])


# ============================================================================
# AUDIT RETENTION POLICY MODEL
# ============================================================================

class AuditRetentionPolicy(models.Model):
    """
    Data retention policies for audit data.

    Fields:
    - resource_type: Type of resource (AUDIT_LOG, SECURITY_EVENT, USER_ACTIVITY)
    - retention_days: Number of days to retain data
    - description: Policy description
    - is_active: Whether the policy is active
    - created_at, updated_at: Timestamps

    Methods:
    - enforce(): Enforce the retention policy

    Indexes: resource_type (unique), is_active
    """

    RESOURCE_TYPES = [
        ('AUDIT_LOG', 'Audit Log'),
        ('SECURITY_EVENT', 'Security Event'),
        ('USER_ACTIVITY', 'User Activity'),
        ('SYSTEM_HEALTH', 'System Health'),
        ('PERFORMANCE_METRIC', 'Performance Metric'),
        ('ANOMALY_DETECTION', 'Anomaly Detection'),
    ]

    resource_type = models.CharField(
        _('resource type'),
        max_length=20,
        choices=RESOURCE_TYPES,
        unique=True,
        db_index=True,
        help_text=_('Type of resource')
    )

    retention_days = models.PositiveIntegerField(
        _('retention days'),
        default=365,
        validators=[MinValueValidator(1)],
        help_text=_('Number of days to retain data')
    )

    description = models.TextField(
        _('description'),
        blank=True,
        null=True,
        help_text=_('Policy description')
    )

    is_active = models.BooleanField(
        _('is active'),
        default=True,
        db_index=True,
        help_text=_('Whether the policy is active')
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
        db_table = 'audit_retention_policies'
        ordering = ['resource_type']
        indexes = [
            models.Index(fields=['resource_type', 'is_active']),
        ]
        verbose_name = _('audit retention policy')
        verbose_name_plural = _('audit retention policies')

    def __str__(self):
        return f"{self.get_resource_type_display()} - {self.retention_days} days"

    def enforce(self) -> int:
        """
        Enforce the retention policy by deleting old records.

        Returns:
            int: Number of records deleted
        """
        cutoff_date = timezone.now() - timedelta(days=self.retention_days)

        if self.resource_type == 'AUDIT_LOG':
            count, _ = AuditLog.objects.filter(timestamp__lt=cutoff_date).delete()
            return count
        elif self.resource_type == 'SECURITY_EVENT':
            count, _ = SecurityEvent.objects.filter(timestamp__lt=cutoff_date).delete()
            return count
        elif self.resource_type == 'USER_ACTIVITY':
            count, _ = UserActivity.objects.filter(timestamp__lt=cutoff_date).delete()
            return count
        elif self.resource_type == 'SYSTEM_HEALTH':
            count, _ = SystemHealth.objects.filter(timestamp__lt=cutoff_date).delete()
            return count
        elif self.resource_type == 'PERFORMANCE_METRIC':
            count, _ = PerformanceMetric.objects.filter(timestamp__lt=cutoff_date).delete()
            return count
        elif self.resource_type == 'ANOMALY_DETECTION':
            count, _ = AnomalyDetection.objects.filter(timestamp__lt=cutoff_date).delete()
            return count

        return 0


# ============================================================================
# SECURITY EVENT MODEL
# ============================================================================

class SecurityEvent(models.Model):
    """
    Security-related events (login attempts, suspicious activity, etc.).

    Fields:
    - user: User associated with the event
    - event_type: Type of security event
    - description: Description of the event
    - severity: Severity level
    - details: Additional details
    - ip_address: IP address
    - user_agent: User agent
    - timestamp: When the event occurred
    - created_at, updated_at: Timestamps

    Methods:
    - get_summary(): Get summary dictionary

    Indexes: event_type, severity, timestamp, user
    """

    SECURITY_EVENT_TYPES = [
        ('LOGIN_SUCCESS', 'Login Success'),
        ('LOGIN_FAILED', 'Login Failed'),
        ('LOGOUT', 'Logout'),
        ('PASSWORD_CHANGE', 'Password Change'),
        ('PASSWORD_RESET', 'Password Reset'),
        ('ACCOUNT_LOCKED', 'Account Locked'),
        ('ACCOUNT_UNLOCKED', 'Account Unlocked'),
        ('ACCOUNT_SUSPENDED', 'Account Suspended'),
        ('ACCOUNT_REACTIVATED', 'Account Reactivated'),
        ('SUSPICIOUS_ACTIVITY', 'Suspicious Activity'),
        ('UNAUTHORIZED_ACCESS', 'Unauthorized Access'),
        ('IP_BLOCKED', 'IP Blocked'),
        ('IP_UNBLOCKED', 'IP Unblocked'),
        ('RATE_LIMIT_EXCEEDED', 'Rate Limit Exceeded'),
        ('API_KEY_CREATED', 'API Key Created'),
        ('API_KEY_REVOKED', 'API Key Revoked'),
        ('TWO_FACTOR_ENABLED', '2FA Enabled'),
        ('TWO_FACTOR_DISABLED', '2FA Disabled'),
        ('DEVICE_REGISTERED', 'Device Registered'),
        ('DEVICE_REMOVED', 'Device Removed'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='security_events',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User associated with the event')
    )

    event_type = models.CharField(
        _('event type'),
        max_length=30,
        choices=SECURITY_EVENT_TYPES,
        db_index=True,
        help_text=_('Type of security event')
    )

    description = models.TextField(
        _('description'),
        help_text=_('Description of the event')
    )

    severity = models.CharField(
        _('severity'),
        max_length=10,
        choices=AuditLog.SEVERITY_CHOICES,
        default='warning',
        db_index=True,
        help_text=_('Severity level')
    )

    details = models.JSONField(
        _('details'),
        default=dict,
        help_text=_('Additional details')
    )

    ip_address = models.GenericIPAddressField(
        _('IP address'),
        null=True,
        blank=True,
        help_text=_('IP address')
    )

    user_agent = models.CharField(
        _('user agent'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('User agent')
    )

    timestamp = models.DateTimeField(
        _('timestamp'),
        default=timezone.now,
        db_index=True,
        help_text=_('When the event occurred')
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
        db_table = 'security_events'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'event_type']),
            models.Index(fields=['severity', 'timestamp']),
            models.Index(fields=['event_type', 'timestamp']),
        ]
        verbose_name = _('security event')
        verbose_name_plural = _('security events')

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.user.email} at {self.timestamp}"

    def get_summary(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'user_id': self.user.id,
            'user_email': self.user.email,
            'event_type': self.event_type,
            'event_type_display': self.get_event_type_display(),
            'description': self.description,
            'severity': self.severity,
            'details': self.details,
            'ip_address': self.ip_address,
            'timestamp': self.timestamp.isoformat(),
        }


# ============================================================================
# USER ACTIVITY MODEL
# ============================================================================

class UserActivity(models.Model):
    """
    User activity tracking for analytics.

    Fields:
    - user: User performing the activity
    - action: Action performed
    - resource: Resource type
    - resource_id: ID of the resource
    - details: Additional details
    - session_id: Session ID
    - ip_address: IP address
    - user_agent: User agent
    - timestamp: When the activity occurred
    - created_at, updated_at: Timestamps

    Indexes: user, action, timestamp, resource
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='user_activities',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User performing the activity')
    )

    action = models.CharField(
        _('action'),
        max_length=50,
        db_index=True,
        help_text=_('Action performed')
    )

    resource = models.CharField(
        _('resource'),
        max_length=50,
        db_index=True,
        help_text=_('Resource type')
    )

    resource_id = models.PositiveIntegerField(
        _('resource ID'),
        null=True,
        blank=True,
        help_text=_('ID of the resource')
    )

    details = models.JSONField(
        _('details'),
        default=dict,
        help_text=_('Additional details')
    )

    session_id = models.CharField(
        _('session ID'),
        max_length=100,
        blank=True,
        null=True,
        help_text=_('Session ID')
    )

    ip_address = models.GenericIPAddressField(
        _('IP address'),
        null=True,
        blank=True,
        help_text=_('IP address')
    )

    user_agent = models.CharField(
        _('user agent'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('User agent')
    )

    timestamp = models.DateTimeField(
        _('timestamp'),
        default=timezone.now,
        db_index=True,
        help_text=_('When the activity occurred')
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
        db_table = 'user_activities'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'action']),
            models.Index(fields=['resource', 'timestamp']),
            models.Index(fields=['timestamp', 'user']),
        ]
        verbose_name = _('user activity')
        verbose_name_plural = _('user activities')

    def __str__(self):
        return f"{self.user.email} - {self.action} on {self.resource} at {self.timestamp}"


# ============================================================================
# SYSTEM HEALTH MODEL
# ============================================================================

class SystemHealth(models.Model):
    """
    System health monitoring.

    Fields:
    - component: Component name (database, cache, celery, etc.)
    - status: Status (ok, warning, error, degraded)
    - message: Status message
    - details: Additional details
    - checked_at: When the check was performed
    - created_at, updated_at: Timestamps

    Indexes: component, status, checked_at
    """

    STATUS_CHOICES = [
        ('ok', 'OK'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('degraded', 'Degraded'),
    ]

    component = models.CharField(
        _('component'),
        max_length=50,
        db_index=True,
        help_text=_('Component name')
    )

    status = models.CharField(
        _('status'),
        max_length=10,
        choices=STATUS_CHOICES,
        default='ok',
        db_index=True,
        help_text=_('Status')
    )

    message = models.TextField(
        _('message'),
        blank=True,
        null=True,
        help_text=_('Status message')
    )

    details = models.JSONField(
        _('details'),
        default=dict,
        help_text=_('Additional details')
    )

    checked_at = models.DateTimeField(
        _('checked at'),
        default=timezone.now,
        db_index=True,
        help_text=_('When the check was performed')
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
        db_table = 'system_health'
        ordering = ['-checked_at']
        indexes = [
            models.Index(fields=['component', 'status']),
            models.Index(fields=['checked_at', 'component']),
        ]
        verbose_name = _('system health')
        verbose_name_plural = _('system health checks')

    def __str__(self):
        return f"{self.component} - {self.status} at {self.checked_at}"


# ============================================================================
# PERFORMANCE METRIC MODEL
# ============================================================================

class PerformanceMetric(models.Model):
    """
    Performance and latency metrics.

    Fields:
    - metric_name: Name of the metric (api_latency, db_query_time, etc.)
    - value: Metric value
    - unit: Unit (ms, bytes, count, etc.)
    - labels: Labels for filtering
    - timestamp: When the metric was recorded
    - created_at, updated_at: Timestamps

    Methods:
    - get_aggregate(): Get aggregated statistics

    Indexes: metric_name, timestamp, labels
    """

    metric_name = models.CharField(
        _('metric name'),
        max_length=100,
        db_index=True,
        help_text=_('Name of the metric')
    )

    value = models.DecimalField(
        _('value'),
        max_digits=20,
        decimal_places=4,
        help_text=_('Metric value')
    )

    unit = models.CharField(
        _('unit'),
        max_length=20,
        default='ms',
        help_text=_('Unit (ms, bytes, count, etc.)')
    )

    labels = models.JSONField(
        _('labels'),
        default=dict,
        help_text=_('Labels for filtering')
    )

    timestamp = models.DateTimeField(
        _('timestamp'),
        default=timezone.now,
        db_index=True,
        help_text=_('When the metric was recorded')
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
        db_table = 'performance_metrics'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['metric_name', 'timestamp']),
            models.Index(fields=['labels']),
        ]
        verbose_name = _('performance metric')
        verbose_name_plural = _('performance metrics')

    def __str__(self):
        return f"{self.metric_name} = {self.value} {self.unit} at {self.timestamp}"

    @classmethod
    def get_aggregate(cls, metric_name: str, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """
        Get aggregate statistics for a metric.

        Args:
            metric_name: Name of the metric
            start_date: Start date
            end_date: End date

        Returns:
            Dict with min, max, avg, sum, count
        """
        queryset = cls.objects.filter(
            metric_name=metric_name,
            timestamp__gte=start_date,
            timestamp__lte=end_date
        )
        stats = queryset.aggregate(
            min=Min('value'),
            max=Max('value'),
            avg=Avg('value'),
            sum=Sum('value'),
            count=Count('id')
        )
        return {
            'min': stats['min'],
            'max': stats['max'],
            'avg': stats['avg'],
            'sum': stats['sum'],
            'count': stats['count'],
        }


# ============================================================================
# ANOMALY DETECTION MODEL
# ============================================================================

class AnomalyDetection(models.Model):
    """
    Detected anomalies and outliers.

    Fields:
    - anomaly_type: Type of anomaly (spike, drop, pattern, etc.)
    - metric_name: Name of the metric
    - value: Anomalous value
    - baseline: Baseline value
    - z_score: Z-score indicating deviation
    - severity: Severity level
    - description: Description of the anomaly
    - detected_at: When the anomaly was detected
    - resolved_at: When the anomaly was resolved
    - status: Status (open, investigating, resolved, false_positive)
    - details: Additional details
    - created_at, updated_at: Timestamps

    Methods:
    - resolve(): Resolve the anomaly
    - mark_false_positive(): Mark as false positive

    Indexes: anomaly_type, status, detected_at, metric_name
    """

    ANOMALY_TYPES = [
        ('spike', 'Sudden Spike'),
        ('drop', 'Sudden Drop'),
        ('pattern', 'Unusual Pattern'),
        ('outlier', 'Outlier'),
        ('trend', 'Trend Change'),
        ('seasonal', 'Seasonal Anomaly'),
    ]

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('investigating', 'Investigating'),
        ('resolved', 'Resolved'),
        ('false_positive', 'False Positive'),
    ]

    anomaly_type = models.CharField(
        _('anomaly type'),
        max_length=10,
        choices=ANOMALY_TYPES,
        db_index=True,
        help_text=_('Type of anomaly')
    )

    metric_name = models.CharField(
        _('metric name'),
        max_length=100,
        db_index=True,
        help_text=_('Name of the metric')
    )

    value = models.DecimalField(
        _('value'),
        max_digits=20,
        decimal_places=4,
        help_text=_('Anomalous value')
    )

    baseline = models.DecimalField(
        _('baseline'),
        max_digits=20,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=_('Baseline value')
    )

    z_score = models.DecimalField(
        _('z-score'),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_('Z-score indicating deviation')
    )

    severity = models.CharField(
        _('severity'),
        max_length=10,
        choices=AuditLog.SEVERITY_CHOICES,
        default='warning',
        db_index=True,
        help_text=_('Severity level')
    )

    description = models.TextField(
        _('description'),
        help_text=_('Description of the anomaly')
    )

    detected_at = models.DateTimeField(
        _('detected at'),
        default=timezone.now,
        db_index=True,
        help_text=_('When the anomaly was detected')
    )

    resolved_at = models.DateTimeField(
        _('resolved at'),
        null=True,
        blank=True,
        help_text=_('When the anomaly was resolved')
    )

    status = models.CharField(
        _('status'),
        max_length=15,
        choices=STATUS_CHOICES,
        default='open',
        db_index=True,
        help_text=_('Anomaly status')
    )

    details = models.JSONField(
        _('details'),
        default=dict,
        help_text=_('Additional details')
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
        db_table = 'anomaly_detections'
        ordering = ['-detected_at']
        indexes = [
            models.Index(fields=['anomaly_type', 'status']),
            models.Index(fields=['metric_name', 'detected_at']),
            models.Index(fields=['status', 'detected_at']),
        ]
        verbose_name = _('anomaly detection')
        verbose_name_plural = _('anomaly detections')

    def __str__(self):
        return f"{self.get_anomaly_type_display()} on {self.metric_name} at {self.detected_at}"

    def resolve(self) -> None:
        """Resolve the anomaly."""
        if self.status in ['open', 'investigating']:
            self.status = 'resolved'
            self.resolved_at = timezone.now()
            self.save()
            logger.info(f'Anomaly {self.id} resolved')

    def mark_false_positive(self) -> None:
        """Mark the anomaly as a false positive."""
        if self.status in ['open', 'investigating']:
            self.status = 'false_positive'
            self.resolved_at = timezone.now()
            self.save()
            logger.info(f'Anomaly {self.id} marked as false positive')