"""
Models for the admin panel app.

This module defines all database models related to administrative functionality:
- AdminAction: Actions performed by administrators (suspend, activate, verify, etc.)
- AdminLog: General log entries for admin activities
- AdminPreference: User preferences for admin dashboard and notifications
- SystemSetting: Key-value store for system-wide settings
- MaintenanceLog: Logs of maintenance tasks and system operations
- Report: Generated reports (daily, weekly, monthly, custom)
- ReportSchedule: Scheduled report generation configurations
- AuditTrail: Comprehensive audit trail for all model changes
- DashboardWidget: Configurable dashboard widgets for admin users

All models include comprehensive fields, methods, properties, validation,
and business logic for administrative operations and system monitoring.
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
from apps.common.constants import UserStatus, GroupStatus, PaymentStatus, ContributionStatus, NotificationType
from apps.common.utils import format_currency, get_current_time

logger = logging.getLogger(__name__)


# ============================================================================
# ADMIN ACTION MODEL
# ============================================================================

class AdminAction(models.Model):
    """
    Log of administrative actions performed by admins.

    Fields:
    - user: User being acted upon (if applicable)
    - group: Group being acted upon (if applicable)
    - admin: Admin user who performed the action
    - action: Action type (suspend, activate, verify, delete, etc.)
    - details: Additional details as JSON
    - ip_address: IP address of the admin
    - user_agent: User agent of the admin's browser
    - timestamp: When the action occurred
    - created_at, updated_at: Timestamps

    Methods:
    - get_summary(): Get summary dictionary
    - get_action_display(): Get human-readable action display

    Indexes: admin, action, timestamp, user, group
    """

    ACTION_CHOICES = [
        ('suspend', 'Suspend User'),
        ('activate', 'Activate User'),
        ('verify_identity', 'Verify Identity'),
        ('delete', 'Delete User'),
        ('restore', 'Restore User'),
        ('approve_group', 'Approve Group'),
        ('complete_group', 'Complete Group'),
        ('cancel_group', 'Cancel Group'),
        ('pause_group', 'Pause Group'),
        ('resume_group', 'Resume Group'),
        ('manual_payment', 'Manual Payment'),
        ('manual_refund', 'Manual Refund'),
        ('mark_payment_failed', 'Mark Payment Failed'),
        ('broadcast_notification', 'Broadcast Notification'),
        ('generate_report', 'Generate Report'),
        ('clear_cache', 'Clear Cache'),
        ('run_maintenance', 'Run Maintenance'),
        ('system_setting_change', 'System Setting Change'),
        ('admin_login', 'Admin Login'),
        ('admin_logout', 'Admin Logout'),
        ('password_reset', 'Password Reset'),
        ('bulk_operation', 'Bulk Operation'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_actions',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User being acted upon')
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_actions',
        verbose_name=_('group'),
        db_index=True,
        help_text=_('Group being acted upon')
    )

    admin = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='admin_actions_performed',
        verbose_name=_('admin'),
        db_index=True,
        help_text=_('Admin user who performed the action')
    )

    action = models.CharField(
        _('action'),
        max_length=30,
        choices=ACTION_CHOICES,
        db_index=True,
        help_text=_('Type of action performed')
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
        help_text=_('IP address of the admin')
    )

    user_agent = models.CharField(
        _('user agent'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('User agent of the admin\'s browser')
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

    class Meta:
        db_table = 'admin_actions'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['admin', 'action']),
            models.Index(fields=['user', 'action']),
            models.Index(fields=['group', 'action']),
            models.Index(fields=['timestamp', 'action']),
        ]
        verbose_name = _('admin action')
        verbose_name_plural = _('admin actions')

    def __str__(self):
        return f"{self.admin.email} - {self.get_action_display()} at {self.timestamp}"

    def save(self, *args, **kwargs):
        if not self.timestamp:
            self.timestamp = timezone.now()
        super().save(*args, **kwargs)

    @property
    def action_display(self) -> str:
        """Get human-readable action display."""
        return dict(self.ACTION_CHOICES).get(self.action, self.action)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary dictionary for the admin action."""
        return {
            'id': self.id,
            'admin_id': self.admin.id,
            'admin_email': self.admin.email,
            'admin_name': self.admin.full_name,
            'action': self.action,
            'action_display': self.action_display,
            'user_id': self.user.id if self.user else None,
            'user_email': self.user.email if self.user else None,
            'group_id': self.group.id if self.group else None,
            'group_name': self.group.name if self.group else None,
            'details': self.details,
            'ip_address': self.ip_address,
            'timestamp': self.timestamp.isoformat(),
        }


# ============================================================================
# ADMIN LOG MODEL
# ============================================================================

class AdminLog(models.Model):
    """
    General log entries for admin activities (system-wide logging).

    Fields:
    - admin: Admin user who performed the activity
    - level: Log level (info, warning, error, critical)
    - module: Module where the log originated
    - message: Log message
    - details: Additional details as JSON
    - timestamp: When the log was created
    - ip_address: IP address of the admin
    - created_at, updated_at: Timestamps

    Indexes: admin, level, timestamp, module
    """

    LEVEL_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    admin = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='admin_logs',
        verbose_name=_('admin'),
        db_index=True,
        help_text=_('Admin user who performed the activity')
    )

    level = models.CharField(
        _('level'),
        max_length=10,
        choices=LEVEL_CHOICES,
        default='info',
        db_index=True,
        help_text=_('Log level')
    )

    module = models.CharField(
        _('module'),
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        help_text=_('Module where the log originated')
    )

    message = models.TextField(
        _('message'),
        help_text=_('Log message')
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
        help_text=_('When the log was created')
    )

    ip_address = models.GenericIPAddressField(
        _('IP address'),
        null=True,
        blank=True,
        help_text=_('IP address of the admin')
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
        db_table = 'admin_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['admin', 'level']),
            models.Index(fields=['level', 'timestamp']),
            models.Index(fields=['module', 'timestamp']),
        ]
        verbose_name = _('admin log')
        verbose_name_plural = _('admin logs')

    def __str__(self):
        return f"[{self.level.upper()}] {self.admin.email} - {self.message[:50]}"


# ============================================================================
# ADMIN PREFERENCE MODEL
# ============================================================================

class AdminPreference(models.Model):
    """
    User preferences for admin dashboard and notifications.

    Fields:
    - admin: Admin user these preferences belong to
    - dashboard_layout: JSON layout configuration for dashboard widgets
    - notification_preferences: JSON preferences for admin notifications
    - theme: UI theme preference (light, dark, auto)
    - language: Preferred language
    - timezone: Preferred timezone
    - items_per_page: Default items per page for lists
    - email_notifications: Whether to receive email notifications
    - created_at, updated_at: Timestamps

    Methods:
    - get_dashboard_layout(): Get dashboard layout
    - update_dashboard_layout(): Update dashboard layout

    Indexes: admin (unique)
    """

    admin = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='admin_preferences',
        verbose_name=_('admin'),
        db_index=True,
        help_text=_('Admin user these preferences belong to')
    )

    dashboard_layout = models.JSONField(
        _('dashboard layout'),
        default=dict,
        help_text=_('JSON layout configuration for dashboard widgets')
    )

    notification_preferences = models.JSONField(
        _('notification preferences'),
        default=dict,
        help_text=_('JSON preferences for admin notifications')
    )

    theme = models.CharField(
        _('theme'),
        max_length=10,
        choices=[
            ('light', 'Light'),
            ('dark', 'Dark'),
            ('auto', 'Auto'),
        ],
        default='light',
        help_text=_('UI theme preference')
    )

    language = models.CharField(
        _('language'),
        max_length=5,
        default='en',
        help_text=_('Preferred language')
    )

    timezone = models.CharField(
        _('timezone'),
        max_length=50,
        default='Africa/Addis_Ababa',
        help_text=_('Preferred timezone')
    )

    items_per_page = models.PositiveIntegerField(
        _('items per page'),
        default=50,
        validators=[MinValueValidator(5), MaxValueValidator(200)],
        help_text=_('Default items per page for lists')
    )

    email_notifications = models.BooleanField(
        _('email notifications'),
        default=True,
        help_text=_('Whether to receive email notifications')
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
        db_table = 'admin_preferences'
        verbose_name = _('admin preference')
        verbose_name_plural = _('admin preferences')

    def __str__(self):
        return f"Preferences for {self.admin.email}"

    def get_dashboard_layout(self) -> Dict[str, Any]:
        """Get dashboard layout configuration."""
        return self.dashboard_layout or {}

    def update_dashboard_layout(self, layout: Dict[str, Any]) -> None:
        """Update dashboard layout configuration."""
        self.dashboard_layout = layout
        self.save(update_fields=['dashboard_layout'])


# ============================================================================
# SYSTEM SETTING MODEL
# ============================================================================

class SystemSetting(models.Model):
    """
    Key-value store for system-wide settings.

    Fields:
    - key: Setting key (unique)
    - value: Setting value (JSON serializable)
    - description: Human-readable description
    - category: Category for grouping
    - is_public: Whether this setting is publicly readable
    - editable: Whether this setting is editable via admin
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - get_value(): Get the setting value
    - set_value(): Set the setting value
    - get_settings_by_category(): Get settings by category

    Indexes: key (unique), category, is_public, editable
    """

    key = models.CharField(
        _('key'),
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_('Setting key')
    )

    value = models.JSONField(
        _('value'),
        default=None,
        null=True,
        blank=True,
        help_text=_('Setting value (JSON serializable)')
    )

    description = models.TextField(
        _('description'),
        blank=True,
        null=True,
        help_text=_('Human-readable description')
    )

    category = models.CharField(
        _('category'),
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        help_text=_('Category for grouping')
    )

    is_public = models.BooleanField(
        _('is public'),
        default=False,
        db_index=True,
        help_text=_('Whether this setting is publicly readable')
    )

    editable = models.BooleanField(
        _('editable'),
        default=True,
        db_index=True,
        help_text=_('Whether this setting is editable via admin')
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
        db_table = 'system_settings'
        ordering = ['category', 'key']
        indexes = [
            models.Index(fields=['key']),
            models.Index(fields=['category', 'is_public']),
        ]
        verbose_name = _('system setting')
        verbose_name_plural = _('system settings')

    def __str__(self):
        return f"{self.key} = {self.value}"

    def get_value(self):
        """Get the setting value."""
        return self.value

    def set_value(self, value: Any) -> None:
        """Set the setting value."""
        self.value = value
        self.save(update_fields=['value'])

    @classmethod
    def get_setting(cls, key: str, default: Any = None) -> Any:
        """
        Get a setting by key with a default fallback.

        Args:
            key: Setting key
            default: Default value if setting not found

        Returns:
            Setting value or default
        """
        try:
            setting = cls.objects.get(key=key, deleted_at__isnull=True)
            return setting.value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set_setting(cls, key: str, value: Any, description: Optional[str] = None,
                   category: Optional[str] = None, is_public: bool = False) -> 'SystemSetting':
        """
        Set a system setting, creating it if it doesn't exist.

        Args:
            key: Setting key
            value: Setting value
            description: Optional description
            category: Optional category
            is_public: Whether publicly readable

        Returns:
            SystemSetting instance
        """
        setting, created = cls.objects.update_or_create(
            key=key,
            defaults={
                'value': value,
                'description': description,
                'category': category,
                'is_public': is_public,
                'editable': True,
                'deleted_at': None,
            }
        )
        return setting

    @classmethod
    def get_settings_by_category(cls, category: str) -> Dict[str, Any]:
        """
        Get all settings in a category.

        Args:
            category: Category name

        Returns:
            Dict mapping keys to values
        """
        settings = cls.objects.filter(category=category, deleted_at__isnull=True)
        return {s.key: s.value for s in settings}


# ============================================================================
# MAINTENANCE LOG MODEL
# ============================================================================

class MaintenanceLog(models.Model):
    """
    Logs of maintenance tasks and system operations.

    Fields:
    - task_type: Type of maintenance task (backup, cleanup, migration, etc.)
    - status: Status (pending, running, completed, failed)
    - started_at: When the task started
    - completed_at: When the task completed
    - duration_seconds: Duration of the task in seconds
    - result: Result summary
    - error_message: Error message if failed
    - details: Additional details as JSON
    - initiated_by: User who initiated the task (if manual)
    - created_at, updated_at: Timestamps

    Methods:
    - start(): Start the task
    - complete(): Complete the task
    - fail(): Mark as failed with error

    Indexes: task_type, status, started_at, completed_at
    """

    TASK_CHOICES = [
        ('backup', 'Backup Database'),
        ('cleanup', 'Cleanup Old Data'),
        ('migration', 'Data Migration'),
        ('sync', 'Data Synchronization'),
        ('reindex', 'Reindex Search'),
        ('cache_clear', 'Clear Cache'),
        ('report_generation', 'Report Generation'),
        ('system_update', 'System Update'),
    ]

    task_type = models.CharField(
        _('task type'),
        max_length=20,
        choices=TASK_CHOICES,
        db_index=True,
        help_text=_('Type of maintenance task')
    )

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending',
        db_index=True,
        help_text=_('Task status')
    )

    started_at = models.DateTimeField(
        _('started at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('When the task started')
    )

    completed_at = models.DateTimeField(
        _('completed at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('When the task completed')
    )

    duration_seconds = models.FloatField(
        _('duration seconds'),
        null=True,
        blank=True,
        help_text=_('Duration of the task in seconds')
    )

    result = models.TextField(
        _('result'),
        blank=True,
        null=True,
        help_text=_('Result summary')
    )

    error_message = models.TextField(
        _('error message'),
        blank=True,
        null=True,
        help_text=_('Error message if failed')
    )

    details = models.JSONField(
        _('details'),
        default=dict,
        help_text=_('Additional details')
    )

    initiated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='maintenance_logs',
        verbose_name=_('initiated by'),
        help_text=_('User who initiated the task (if manual)')
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
        db_table = 'maintenance_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task_type', 'status']),
            models.Index(fields=['status', 'started_at']),
            models.Index(fields=['completed_at']),
        ]
        verbose_name = _('maintenance log')
        verbose_name_plural = _('maintenance logs')

    def __str__(self):
        return f"{self.get_task_type_display()} - {self.status} at {self.created_at}"

    def start(self) -> None:
        """Start the maintenance task."""
        self.status = 'running'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])

    def complete(self, result: Optional[str] = None) -> None:
        """Complete the maintenance task."""
        self.status = 'completed'
        self.completed_at = timezone.now()
        if self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
        if result:
            self.result = result
        self.save(update_fields=['status', 'completed_at', 'duration_seconds', 'result'])

    def fail(self, error_message: str) -> None:
        """Mark the maintenance task as failed."""
        self.status = 'failed'
        self.completed_at = timezone.now()
        self.error_message = error_message
        if self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
        self.save(update_fields=['status', 'completed_at', 'error_message', 'duration_seconds'])

    def cancel(self) -> None:
        """Cancel the maintenance task."""
        self.status = 'cancelled'
        self.completed_at = timezone.now()
        if self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
        self.save(update_fields=['status', 'completed_at', 'duration_seconds'])


# ============================================================================
# REPORT MODEL
# ============================================================================

class Report(models.Model):
    """
    Generated reports for administrative use.

    Fields:
    - name: Report name
    - report_type: Type (daily, weekly, monthly, quarterly, custom)
    - generated_by: Admin who generated the report
    - title: Report title
    - description: Report description
    - data: JSON report data
    - format: Output format (json, csv, pdf, excel)
    - file: Optional file attachment
    - date_range_start: Start date for report data
    - date_range_end: End date for report data
    - parameters: Parameters used to generate the report
    - generated_at: When the report was generated
    - expires_at: Expiry timestamp
    - is_public: Whether publicly accessible
    - download_count: Number of downloads
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - get_summary(): Get summary dictionary
    - increment_download(): Increment download count
    - is_expired(): Check if expired

    Indexes: report_type, generated_by, generated_at, expires_at
    """

    REPORT_TYPES = [
        ('daily', 'Daily Report'),
        ('weekly', 'Weekly Report'),
        ('monthly', 'Monthly Report'),
        ('quarterly', 'Quarterly Report'),
        ('custom', 'Custom Report'),
    ]

    FORMAT_CHOICES = [
        ('json', 'JSON'),
        ('csv', 'CSV'),
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
    ]

    name = models.CharField(
        _('name'),
        max_length=255,
        db_index=True,
        help_text=_('Report name')
    )

    report_type = models.CharField(
        _('report type'),
        max_length=10,
        choices=REPORT_TYPES,
        default='custom',
        db_index=True,
        help_text=_('Type of report')
    )

    generated_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='generated_reports',
        verbose_name=_('generated by'),
        db_index=True,
        help_text=_('Admin who generated the report')
    )

    title = models.CharField(
        _('title'),
        max_length=255,
        help_text=_('Report title')
    )

    description = models.TextField(
        _('description'),
        blank=True,
        null=True,
        help_text=_('Report description')
    )

    data = models.JSONField(
        _('data'),
        default=dict,
        help_text=_('JSON report data')
    )

    format = models.CharField(
        _('format'),
        max_length=10,
        choices=FORMAT_CHOICES,
        default='json',
        help_text=_('Output format')
    )

    file = models.FileField(
        _('file'),
        upload_to='reports/%Y/%m/%d/',
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

    parameters = models.JSONField(
        _('parameters'),
        default=dict,
        help_text=_('Parameters used to generate the report')
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
        help_text=_('Expiry timestamp (reports older than X days are automatically deleted)')
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
        db_table = 'reports'
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['report_type', 'generated_at']),
            models.Index(fields=['generated_by', 'generated_at']),
            models.Index(fields=['expires_at']),
        ]
        verbose_name = _('report')
        verbose_name_plural = _('reports')

    def __str__(self):
        return f"{self.name} ({self.get_report_type_display()})"

    def save(self, *args, **kwargs):
        if not self.expires_at and self.report_type != 'custom':
            # Set expiry based on report type
            if self.report_type == 'daily':
                self.expires_at = self.generated_at + timedelta(days=30)
            elif self.report_type == 'weekly':
                self.expires_at = self.generated_at + timedelta(days=90)
            elif self.report_type == 'monthly':
                self.expires_at = self.generated_at + timedelta(days=180)
            elif self.report_type == 'quarterly':
                self.expires_at = self.generated_at + timedelta(days=365)
            else:
                self.expires_at = self.generated_at + timedelta(days=30)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        """Check if the report is expired."""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    @property
    def age_days(self) -> int:
        """Age of the report in days."""
        return (timezone.now() - self.generated_at).days

    def get_summary(self) -> Dict[str, Any]:
        """Get summary dictionary for the report."""
        return {
            'id': self.id,
            'name': self.name,
            'report_type': self.report_type,
            'report_type_display': self.get_report_type_display(),
            'generated_by': self.generated_by.id,
            'generated_by_email': self.generated_by.email,
            'generated_by_name': self.generated_by.full_name,
            'title': self.title,
            'description': self.description,
            'format': self.format,
            'date_range_start': self.date_range_start.isoformat() if self.date_range_start else None,
            'date_range_end': self.date_range_end.isoformat() if self.date_range_end else None,
            'generated_at': self.generated_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_expired': self.is_expired,
            'is_public': self.is_public,
            'download_count': self.download_count,
        }

    def increment_download(self) -> None:
        """Increment download count."""
        self.download_count += 1
        self.save(update_fields=['download_count'])


# ============================================================================
# REPORT SCHEDULE MODEL
# ============================================================================

class ReportSchedule(models.Model):
    """
    Scheduled report generation configurations.

    Fields:
    - name: Schedule name
    - report_type: Type of report to generate (daily, weekly, monthly, quarterly)
    - description: Schedule description
    - recipients: List of recipient emails
    - format: Output format
    - frequency: Frequency (daily, weekly, monthly)
    - day_of_week: Day of week for weekly schedules
    - day_of_month: Day of month for monthly schedules
    - time: Time of day to run
    - timezone: Timezone for schedule
    - is_active: Whether the schedule is active
    - last_run: Last run timestamp
    - next_run: Next run timestamp
    - parameters: Additional parameters
    - created_by: Admin who created the schedule
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - calculate_next_run(): Calculate next run time
    - run(): Execute the scheduled report generation

    Indexes: report_type, is_active, next_run
    """

    SCHEDULE_FREQUENCIES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ]

    name = models.CharField(
        _('name'),
        max_length=255,
        db_index=True,
        help_text=_('Schedule name')
    )

    report_type = models.CharField(
        _('report type'),
        max_length=10,
        choices=Report.REPORT_TYPES,
        default='daily',
        db_index=True,
        help_text=_('Type of report to generate')
    )

    description = models.TextField(
        _('description'),
        blank=True,
        null=True,
        help_text=_('Schedule description')
    )

    recipients = models.JSONField(
        _('recipients'),
        default=list,
        help_text=_('List of recipient emails')
    )

    format = models.CharField(
        _('format'),
        max_length=10,
        choices=Report.FORMAT_CHOICES,
        default='pdf',
        help_text=_('Output format')
    )

    frequency = models.CharField(
        _('frequency'),
        max_length=10,
        choices=SCHEDULE_FREQUENCIES,
        default='daily',
        db_index=True,
        help_text=_('Frequency of report generation')
    )

    day_of_week = models.PositiveSmallIntegerField(
        _('day of week'),
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(6)],
        help_text=_('Day of week (0=Sunday, 6=Saturday) for weekly schedules')
    )

    day_of_month = models.PositiveSmallIntegerField(
        _('day of month'),
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text=_('Day of month for monthly schedules')
    )

    time = models.TimeField(
        _('time'),
        default=timezone.now().time(),
        help_text=_('Time of day to run')
    )

    timezone = models.CharField(
        _('timezone'),
        max_length=50,
        default='Africa/Addis_Ababa',
        help_text=_('Timezone for schedule')
    )

    is_active = models.BooleanField(
        _('is active'),
        default=True,
        db_index=True,
        help_text=_('Whether the schedule is active')
    )

    last_run = models.DateTimeField(
        _('last run'),
        null=True,
        blank=True,
        help_text=_('Last run timestamp')
    )

    next_run = models.DateTimeField(
        _('next run'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('Next run timestamp')
    )

    parameters = models.JSONField(
        _('parameters'),
        default=dict,
        help_text=_('Additional parameters')
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='report_schedules',
        verbose_name=_('created by'),
        help_text=_('Admin who created the schedule')
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
        db_table = 'report_schedules'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'next_run']),
            models.Index(fields=['report_type', 'is_active']),
            models.Index(fields=['frequency']),
        ]
        verbose_name = _('report schedule')
        verbose_name_plural = _('report schedules')

    def __str__(self):
        return f"{self.name} ({self.get_frequency_display()})"

    def calculate_next_run(self) -> datetime:
        """
        Calculate the next run time based on the schedule configuration.

        Returns:
            datetime: Next run time
        """
        import pytz
        now = timezone.now()
        tz = pytz.timezone(self.timezone)
        local_now = now.astimezone(tz)

        # Create a datetime for today at the scheduled time
        scheduled_time = datetime.combine(
            local_now.date(),
            self.time,
            tzinfo=tz
        )

        if self.frequency == 'daily':
            # If today's time has passed, schedule for tomorrow
            if scheduled_time <= local_now:
                scheduled_time += timedelta(days=1)
            return scheduled_time.astimezone(timezone.utc)

        elif self.frequency == 'weekly':
            if self.day_of_week is None:
                raise ValueError('day_of_week is required for weekly schedule')
            # Find the next occurrence of the specified day of week
            days_ahead = (self.day_of_week - local_now.weekday()) % 7
            if days_ahead == 0 and scheduled_time <= local_now:
                days_ahead = 7
            scheduled_time += timedelta(days=days_ahead)
            return scheduled_time.astimezone(timezone.utc)

        elif self.frequency == 'monthly':
            if self.day_of_month is None:
                raise ValueError('day_of_month is required for monthly schedule')
            # Find the next occurrence of the specified day of month
            if scheduled_time.day <= local_now.day and scheduled_time <= local_now:
                # Move to next month
                if scheduled_time.month == 12:
                    scheduled_time = scheduled_time.replace(year=scheduled_time.year + 1, month=1)
                else:
                    scheduled_time = scheduled_time.replace(month=scheduled_time.month + 1)
            else:
                # Use the current month
                pass
            # Ensure the day is valid for the month
            max_day = (scheduled_time.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            scheduled_time = scheduled_time.replace(day=min(self.day_of_month, max_day.day))
            return scheduled_time.astimezone(timezone.utc)

        else:
            return now + timedelta(days=1)

    def save(self, *args, **kwargs):
        if not self.next_run:
            self.next_run = self.calculate_next_run()
        super().save(*args, **kwargs)

    def run(self) -> Optional[Report]:
        """
        Execute the scheduled report generation.

        Returns:
            Report: Generated report, or None if failed
        """
        # This would call the report generation logic
        # For now, just update last_run and next_run
        self.last_run = timezone.now()
        self.next_run = self.calculate_next_run()
        self.save(update_fields=['last_run', 'next_run'])
        return None


# ============================================================================
# AUDIT TRAIL MODEL
# ============================================================================

class AuditTrail(models.Model):
    """
    Comprehensive audit trail for all model changes.

    Fields:
    - user: User who performed the action
    - content_type: Content type of the model being audited
    - object_id: ID of the object being audited
    - content_object: Generic foreign key to the object
    - action: Action performed (create, update, delete, view)
    - changes: JSON diff of changes
    - ip_address: IP address of the user
    - user_agent: User agent of the user's browser
    - timestamp: When the action occurred
    - created_at, updated_at: Timestamps

    Methods:
    - get_object_display(): Get string representation of the object
    - get_change_summary(): Get summary of changes

    Indexes: user, content_type, object_id, action, timestamp
    """

    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('view', 'View'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('export', 'Export'),
        ('import', 'Import'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_trails',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User who performed the action')
    )

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_('content type'),
        help_text=_('Content type of the model being audited')
    )

    object_id = models.PositiveIntegerField(
        _('object ID'),
        db_index=True,
        help_text=_('ID of the object being audited')
    )

    content_object = GenericForeignKey('content_type', 'object_id')

    action = models.CharField(
        _('action'),
        max_length=10,
        choices=ACTION_CHOICES,
        db_index=True,
        help_text=_('Action performed')
    )

    changes = models.JSONField(
        _('changes'),
        default=dict,
        help_text=_('JSON diff of changes')
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

    class Meta:
        db_table = 'audit_trails'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['content_type', 'action']),
        ]
        verbose_name = _('audit trail')
        verbose_name_plural = _('audit trails')

    def __str__(self):
        action_display = self.get_action_display()
        return f"{self.action_display} on {self.content_type} #{self.object_id} by {self.user}"

    def get_object_display(self) -> str:
        """Get string representation of the object."""
        obj = self.content_object
        if obj:
            return str(obj)
        return f"{self.content_type} #{self.object_id}"

    def get_change_summary(self) -> Dict[str, Any]:
        """Get summary of changes."""
        return {
            'object_display': self.get_object_display(),
            'action': self.action,
            'action_display': self.get_action_display(),
            'user': self.user.email if self.user else 'System',
            'changes': self.changes,
            'timestamp': self.timestamp.isoformat(),
        }


# ============================================================================
# DASHBOARD WIDGET MODEL
# ============================================================================

class DashboardWidget(models.Model):
    """
    Configurable dashboard widgets for admin users.

    Fields:
    - name: Widget name
    - widget_type: Type of widget (stats, chart, table, list, custom)
    - title: Display title
    - description: Widget description
    - configuration: JSON configuration for the widget
    - admin: Admin user who owns this widget (null for system-wide)
    - is_system: Whether this is a system-defined widget
    - is_active: Whether the widget is active
    - order: Display order
    - permissions: Required permissions (comma-separated)
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - get_data(): Get widget data
    - render(): Render the widget

    Indexes: admin, widget_type, is_active, order
    """

    WIDGET_TYPES = [
        ('stats', 'Statistics'),
        ('chart', 'Chart'),
        ('table', 'Table'),
        ('list', 'List'),
        ('custom', 'Custom'),
        ('alert', 'Alert'),
        ('progress', 'Progress'),
    ]

    name = models.CharField(
        _('name'),
        max_length=100,
        db_index=True,
        help_text=_('Widget name')
    )

    widget_type = models.CharField(
        _('widget type'),
        max_length=10,
        choices=WIDGET_TYPES,
        default='stats',
        db_index=True,
        help_text=_('Type of widget')
    )

    title = models.CharField(
        _('title'),
        max_length=255,
        help_text=_('Display title')
    )

    description = models.TextField(
        _('description'),
        blank=True,
        null=True,
        help_text=_('Widget description')
    )

    configuration = models.JSONField(
        _('configuration'),
        default=dict,
        help_text=_('JSON configuration for the widget')
    )

    admin = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='dashboard_widgets',
        verbose_name=_('admin'),
        db_index=True,
        help_text=_('Admin user who owns this widget (null for system-wide)')
    )

    is_system = models.BooleanField(
        _('is system'),
        default=False,
        db_index=True,
        help_text=_('Whether this is a system-defined widget')
    )

    is_active = models.BooleanField(
        _('is active'),
        default=True,
        db_index=True,
        help_text=_('Whether the widget is active')
    )

    order = models.PositiveIntegerField(
        _('order'),
        default=0,
        help_text=_('Display order')
    )

    permissions = models.CharField(
        _('permissions'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Required permissions (comma-separated)')
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
        db_table = 'dashboard_widgets'
        ordering = ['order', 'title']
        indexes = [
            models.Index(fields=['admin', 'is_active']),
            models.Index(fields=['widget_type', 'is_active']),
            models.Index(fields=['order']),
        ]
        verbose_name = _('dashboard widget')
        verbose_name_plural = _('dashboard widgets')

    def __str__(self):
        return f"{self.title} ({self.get_widget_type_display()})"

    @property
    def is_user_widget(self) -> bool:
        """Check if this is a user-specific widget."""
        return self.admin is not None and not self.is_system

    def get_data(self) -> Dict[str, Any]:
        """
        Get widget data based on configuration.

        Returns:
            Dict with widget data
        """
        # This would be implemented in the view/API layer
        # For now, return empty data
        return {}

    def render(self) -> str:
        """
        Render the widget.

        Returns:
            str: Rendered widget HTML
        """
        # This would be implemented in the view/API layer
        return ""