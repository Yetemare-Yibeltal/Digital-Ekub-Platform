"""
Admin configuration for the admin panel app.

This module provides comprehensive Django admin interfaces for all admin panel models:
- AdminAction: Log of administrative actions
- AdminLog: General log entries for admin activities
- AdminPreference: Admin user preferences
- SystemSetting: System-wide settings
- MaintenanceLog: Logs of maintenance tasks
- Report: Generated reports
- ReportSchedule: Scheduled report configurations
- AuditTrail: Comprehensive audit trail
- DashboardWidget: Configurable dashboard widgets

All admin classes include custom list displays, filters, search fields,
inline relationships, and custom actions for efficient management.
"""

from django.contrib import admin
from django.contrib.admin import ModelAdmin, TabularInline, StackedInline
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.urls import reverse
from django.utils.html import format_html
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.db import transaction
import csv
import json
from io import StringIO

from apps.users.models import User
from apps.groups.models import Group
from apps.common.constants import UserStatus, GroupStatus, PaymentStatus, ContributionStatus
from apps.common.utils import format_currency, log_audit_event

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


# ============================================================================
# INLINE CLASSES
# ============================================================================

class ReportScheduleInline(TabularInline):
    """Inline for report schedules (for a user or system)."""
    model = ReportSchedule
    extra = 0
    fields = ('name', 'frequency', 'is_active', 'next_run')
    readonly_fields = ('next_run',)
    can_delete = True
    verbose_name = _('Report Schedule')
    verbose_name_plural = _('Report Schedules')


class AdminActionInline(TabularInline):
    """Inline for admin actions (for a user)."""
    model = AdminAction
    extra = 0
    fields = ('action', 'timestamp', 'ip_address')
    readonly_fields = ('action', 'timestamp', 'ip_address')
    can_delete = False
    max_num = 10
    verbose_name = _('Admin Action')
    verbose_name_plural = _('Admin Actions')


# ============================================================================
# ADMIN ACTION ADMIN
# ============================================================================

@admin.register(AdminAction)
class AdminActionAdmin(ModelAdmin):
    """
    Admin configuration for AdminAction model.
    """
    list_display = (
        'id',
        'admin_display',
        'action_display',
        'target_display',
        'target_type_display',
        'timestamp_display',
        'ip_address_display',
    )

    list_filter = (
        'action',
        ('admin', admin.RelatedOnlyFieldListFilter),
        ('user', admin.RelatedOnlyFieldListFilter),
        ('group', admin.RelatedOnlyFieldListFilter),
        'timestamp',
    )

    search_fields = (
        'admin__email',
        'admin__first_name',
        'admin__last_name',
        'user__email',
        'group__name',
        'details',
        'ip_address',
    )

    ordering = ('-timestamp',)

    readonly_fields = (
        'id',
        'admin',
        'user',
        'group',
        'action',
        'details',
        'ip_address',
        'user_agent',
        'timestamp',
        'created_at',
        'updated_at',
        'get_formatted_details',
    )

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'id',
                'admin',
                'action',
            )
        }),
        (_('Target'), {
            'fields': (
                'user',
                'group',
            )
        }),
        (_('Details'), {
            'fields': (
                'details',
                'get_formatted_details',
            ),
            'classes': ('collapse',),
        }),
        (_('Metadata'), {
            'fields': (
                'ip_address',
                'user_agent',
                'timestamp',
            )
        }),
        (_('System'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'export_as_csv',
        'export_as_json',
        'delete_selected',
    ]

    list_per_page = 50

    # --------------------------------------------------------------------------
    # CUSTOM DISPLAY METHODS
    # --------------------------------------------------------------------------

    def admin_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.admin.id])
        return format_html('<a href="{}">{}</a>', url, obj.admin.email)
    admin_display.short_description = _('Admin')
    admin_display.admin_order_field = 'admin__email'

    def action_display(self, obj):
        return obj.get_action_display()
    action_display.short_description = _('Action')
    action_display.admin_order_field = 'action'

    def target_display(self, obj):
        if obj.user:
            url = reverse('admin:users_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.email)
        elif obj.group:
            url = reverse('admin:groups_group_change', args=[obj.group.id])
            return format_html('<a href="{}">{}</a>', url, obj.group.name)
        return '-'
    target_display.short_description = _('Target')

    def target_type_display(self, obj):
        if obj.user:
            return 'User'
        elif obj.group:
            return 'Group'
        return 'System'
    target_type_display.short_description = _('Target Type')

    def timestamp_display(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')
    timestamp_display.admin_order_field = 'timestamp'

    def ip_address_display(self, obj):
        return obj.ip_address or '-'
    ip_address_display.short_description = _('IP')

    def get_formatted_details(self, obj):
        if obj.details:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.details, indent=2))
        return '-'
    get_formatted_details.short_description = _('Formatted Details')

    # --------------------------------------------------------------------------
    # CUSTOM ACTIONS
    # --------------------------------------------------------------------------

    def export_as_csv(self, request, queryset):
        meta = self.model._meta
        field_names = ['id', 'admin__email', 'action', 'user__email', 'group__name', 'details', 'ip_address', 'timestamp']
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename={meta.verbose_name_plural}.csv'
        writer = csv.writer(response)
        writer.writerow(field_names)
        for obj in queryset:
            row = [
                obj.id,
                obj.admin.email,
                obj.get_action_display(),
                obj.user.email if obj.user else '',
                obj.group.name if obj.group else '',
                json.dumps(obj.details),
                obj.ip_address or '',
                obj.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            ]
            writer.writerow(row)
        self.message_user(request, f'Exported {queryset.count()} admin action(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def export_as_json(self, request, queryset):
        data = []
        for obj in queryset:
            data.append({
                'id': obj.id,
                'admin': obj.admin.email,
                'action': obj.get_action_display(),
                'user': obj.user.email if obj.user else None,
                'group': obj.group.name if obj.group else None,
                'details': obj.details,
                'ip_address': obj.ip_address,
                'timestamp': obj.timestamp.isoformat(),
            })
        response = HttpResponse(
            json.dumps(data, indent=2),
            content_type='application/json'
        )
        response['Content-Disposition'] = 'attachment; filename=admin_actions.json'
        self.message_user(request, f'Exported {queryset.count()} admin action(s).')
        return response
    export_as_json.short_description = _('Export selected as JSON')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} admin action(s).')
    delete_selected.short_description = _('Delete selected')

    # --------------------------------------------------------------------------
    # OVERRIDEN METHODS
    # --------------------------------------------------------------------------

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('admin', 'user', 'group')

    def has_add_permission(self, request):
        # Admin actions are automatically created; manual creation not allowed
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# ADMIN LOG ADMIN
# ============================================================================

@admin.register(AdminLog)
class AdminLogAdmin(ModelAdmin):
    """
    Admin configuration for AdminLog model.
    """
    list_display = (
        'id',
        'admin_display',
        'level_badge',
        'module_display',
        'message_short',
        'timestamp_display',
    )

    list_filter = (
        'level',
        'module',
        ('admin', admin.RelatedOnlyFieldListFilter),
        'timestamp',
    )

    search_fields = (
        'admin__email',
        'message',
        'module',
        'details',
    )

    ordering = ('-timestamp',)

    readonly_fields = (
        'id',
        'admin',
        'level',
        'module',
        'message',
        'details',
        'ip_address',
        'timestamp',
        'created_at',
        'updated_at',
        'get_formatted_details',
    )

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'id',
                'admin',
                'level',
                'module',
            )
        }),
        (_('Message'), {
            'fields': (
                'message',
                'details',
                'get_formatted_details',
            )
        }),
        (_('Metadata'), {
            'fields': (
                'ip_address',
                'timestamp',
            )
        }),
        (_('System'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'export_as_csv',
        'delete_selected',
    ]

    def admin_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.admin.id])
        return format_html('<a href="{}">{}</a>', url, obj.admin.email)
    admin_display.short_description = _('Admin')
    admin_display.admin_order_field = 'admin__email'

    def level_badge(self, obj):
        colors = {
            'info': 'blue',
            'warning': 'orange',
            'error': 'red',
            'critical': 'darkred',
        }
        color = colors.get(obj.level, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_level_display()
        )
    level_badge.short_description = _('Level')
    level_badge.admin_order_field = 'level'

    def module_display(self, obj):
        return obj.module or '-'
    module_display.short_description = _('Module')
    module_display.admin_order_field = 'module'

    def message_short(self, obj):
        return obj.message[:50] + ('...' if len(obj.message) > 50 else '')
    message_short.short_description = _('Message')
    message_short.admin_order_field = 'message'

    def timestamp_display(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')
    timestamp_display.admin_order_field = 'timestamp'

    def get_formatted_details(self, obj):
        if obj.details:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.details, indent=2))
        return '-'
    get_formatted_details.short_description = _('Formatted Details')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=admin_logs.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Admin', 'Level', 'Module', 'Message', 'Timestamp'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.admin.email,
                obj.get_level_display(),
                obj.module or '',
                obj.message,
                obj.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        self.message_user(request, f'Exported {queryset.count()} admin log(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} admin log(s).')
    delete_selected.short_description = _('Delete selected')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('admin')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# ADMIN PREFERENCE ADMIN
# ============================================================================

@admin.register(AdminPreference)
class AdminPreferenceAdmin(ModelAdmin):
    """
    Admin configuration for AdminPreference model.
    """
    list_display = (
        'id',
        'admin_display',
        'theme_display',
        'language',
        'timezone',
        'items_per_page',
        'email_notifications_display',
        'updated_at_display',
    )

    list_filter = (
        'theme',
        'language',
        'timezone',
        'email_notifications',
        ('admin', admin.RelatedOnlyFieldListFilter),
        'updated_at',
    )

    search_fields = (
        'admin__email',
        'admin__first_name',
        'admin__last_name',
    )

    ordering = ('-updated_at',)

    readonly_fields = (
        'id',
        'admin',
        'created_at',
        'updated_at',
        'deleted_at',
        'get_dashboard_layout_display',
        'get_notification_prefs_display',
    )

    fieldsets = (
        (_('User'), {
            'fields': ('admin',)
        }),
        (_('Preferences'), {
            'fields': (
                'theme',
                'language',
                'timezone',
                'items_per_page',
                'email_notifications',
            )
        }),
        (_('Dashboard'), {
            'fields': (
                'dashboard_layout',
                'get_dashboard_layout_display',
            ),
            'classes': ('collapse',),
        }),
        (_('Notifications'), {
            'fields': (
                'notification_preferences',
                'get_notification_prefs_display',
            ),
            'classes': ('collapse',),
        }),
        (_('System'), {
            'fields': (
                'created_at',
                'updated_at',
                'deleted_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'enable_email_notifications',
        'disable_email_notifications',
        'set_light_theme',
        'set_dark_theme',
        'set_auto_theme',
    ]

    def admin_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.admin.id])
        return format_html('<a href="{}">{}</a>', url, obj.admin.email)
    admin_display.short_description = _('Admin')
    admin_display.admin_order_field = 'admin__email'

    def theme_display(self, obj):
        return obj.get_theme_display()
    theme_display.short_description = _('Theme')
    theme_display.admin_order_field = 'theme'

    def email_notifications_display(self, obj):
        return '✓' if obj.email_notifications else '✗'
    email_notifications_display.short_description = _('Email Notif.')
    email_notifications_display.admin_order_field = 'email_notifications'

    def updated_at_display(self, obj):
        return obj.updated_at.strftime('%Y-%m-%d %H:%M')
    updated_at_display.short_description = _('Updated')
    updated_at_display.admin_order_field = 'updated_at'

    def get_dashboard_layout_display(self, obj):
        if obj.dashboard_layout:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.dashboard_layout, indent=2))
        return '-'
    get_dashboard_layout_display.short_description = _('Dashboard Layout')

    def get_notification_prefs_display(self, obj):
        if obj.notification_preferences:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.notification_preferences, indent=2))
        return '-'
    get_notification_prefs_display.short_description = _('Notification Prefs')

    def enable_email_notifications(self, request, queryset):
        count = queryset.update(email_notifications=True)
        self.message_user(request, f'Enabled email notifications for {count} admin(s).')
    enable_email_notifications.short_description = _('Enable email notifications')

    def disable_email_notifications(self, request, queryset):
        count = queryset.update(email_notifications=False)
        self.message_user(request, f'Disabled email notifications for {count} admin(s).')
    disable_email_notifications.short_description = _('Disable email notifications')

    def set_light_theme(self, request, queryset):
        count = queryset.update(theme='light')
        self.message_user(request, f'Set theme to light for {count} admin(s).')
    set_light_theme.short_description = _('Set theme to Light')

    def set_dark_theme(self, request, queryset):
        count = queryset.update(theme='dark')
        self.message_user(request, f'Set theme to dark for {count} admin(s).')
    set_dark_theme.short_description = _('Set theme to Dark')

    def set_auto_theme(self, request, queryset):
        count = queryset.update(theme='auto')
        self.message_user(request, f'Set theme to auto for {count} admin(s).')
    set_auto_theme.short_description = _('Set theme to Auto')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('admin')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ============================================================================
# SYSTEM SETTING ADMIN
# ============================================================================

@admin.register(SystemSetting)
class SystemSettingAdmin(ModelAdmin):
    """
    Admin configuration for SystemSetting model.
    """
    list_display = (
        'id',
        'key_display',
        'value_display',
        'category',
        'is_public_badge',
        'editable_badge',
        'updated_at_display',
    )

    list_filter = (
        'category',
        'is_public',
        'editable',
        ('deleted_at', admin.EmptyFieldListFilter),
        'updated_at',
    )

    search_fields = (
        'key',
        'value',
        'description',
        'category',
    )

    ordering = ('category', 'key')

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'deleted_at',
    )

    fieldsets = (
        (_('Setting'), {
            'fields': (
                'key',
                'value',
                'description',
                'category',
            )
        }),
        (_('Permissions'), {
            'fields': (
                'is_public',
                'editable',
            )
        }),
        (_('System'), {
            'fields': (
                'created_at',
                'updated_at',
                'deleted_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'make_public',
        'make_private',
        'make_editable',
        'make_readonly',
        'export_as_csv',
        'restore_deleted',
    ]

    def key_display(self, obj):
        return format_html(
            '<code style="background: #f8f9fa; padding: 2px 6px; border-radius: 4px;">{}</code>',
            obj.key
        )
    key_display.short_description = _('Key')
    key_display.admin_order_field = 'key'

    def value_display(self, obj):
        value = obj.value
        if isinstance(value, (dict, list)):
            return json.dumps(value, indent=2)[:100]
        if isinstance(value, bool):
            return '✓' if value else '✗'
        return str(value)[:100]
    value_display.short_description = _('Value')
    value_display.admin_order_field = 'value'

    def is_public_badge(self, obj):
        return '✓' if obj.is_public else '✗'
    is_public_badge.short_description = _('Public')
    is_public_badge.admin_order_field = 'is_public'

    def editable_badge(self, obj):
        return '✓' if obj.editable else '✗'
    editable_badge.short_description = _('Editable')
    editable_badge.admin_order_field = 'editable'

    def updated_at_display(self, obj):
        return obj.updated_at.strftime('%Y-%m-%d %H:%M')
    updated_at_display.short_description = _('Updated')
    updated_at_display.admin_order_field = 'updated_at'

    def make_public(self, request, queryset):
        count = queryset.update(is_public=True)
        self.message_user(request, f'Marked {count} setting(s) as public.')
    make_public.short_description = _('Make public')

    def make_private(self, request, queryset):
        count = queryset.update(is_public=False)
        self.message_user(request, f'Marked {count} setting(s) as private.')
    make_private.short_description = _('Make private')

    def make_editable(self, request, queryset):
        count = queryset.update(editable=True)
        self.message_user(request, f'Marked {count} setting(s) as editable.')
    make_editable.short_description = _('Make editable')

    def make_readonly(self, request, queryset):
        count = queryset.update(editable=False)
        self.message_user(request, f'Marked {count} setting(s) as read-only.')
    make_readonly.short_description = _('Make read-only')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=system_settings.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Key', 'Value', 'Category', 'Public', 'Editable'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.key,
                json.dumps(obj.value),
                obj.category or '',
                'Yes' if obj.is_public else 'No',
                'Yes' if obj.editable else 'No',
            ])
        self.message_user(request, f'Exported {queryset.count()} setting(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def restore_deleted(self, request, queryset):
        count = queryset.filter(deleted_at__isnull=False).update(deleted_at=None)
        self.message_user(request, f'Restored {count} deleted setting(s).')
    restore_deleted.short_description = _('Restore deleted')

    def get_queryset(self, request):
        return super().get_queryset(request)


# ============================================================================
# MAINTENANCE LOG ADMIN
# ============================================================================

@admin.register(MaintenanceLog)
class MaintenanceLogAdmin(ModelAdmin):
    """
    Admin configuration for MaintenanceLog model.
    """
    list_display = (
        'id',
        'task_type_display',
        'status_badge',
        'duration_display',
        'started_at_display',
        'completed_at_display',
        'initiated_by_display',
    )

    list_filter = (
        'task_type',
        'status',
        ('initiated_by', admin.RelatedOnlyFieldListFilter),
        'started_at',
        'completed_at',
    )

    search_fields = (
        'task_type',
        'result',
        'error_message',
        'details',
        'initiated_by__email',
    )

    ordering = ('-started_at',)

    readonly_fields = (
        'id',
        'task_type',
        'status',
        'started_at',
        'completed_at',
        'duration_seconds',
        'result',
        'error_message',
        'details',
        'initiated_by',
        'created_at',
        'updated_at',
        'get_formatted_details',
    )

    fieldsets = (
        (_('Task'), {
            'fields': (
                'task_type',
                'status',
            )
        }),
        (_('Timing'), {
            'fields': (
                'started_at',
                'completed_at',
                'duration_seconds',
            )
        }),
        (_('Result'), {
            'fields': (
                'result',
                'error_message',
                'details',
                'get_formatted_details',
            )
        }),
        (_('Metadata'), {
            'fields': (
                'initiated_by',
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'export_as_csv',
    ]

    def task_type_display(self, obj):
        return obj.get_task_type_display()
    task_type_display.short_description = _('Task')
    task_type_display.admin_order_field = 'task_type'

    def status_badge(self, obj):
        colors = {
            'pending': 'orange',
            'running': 'blue',
            'completed': 'green',
            'failed': 'red',
            'cancelled': 'gray',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def duration_display(self, obj):
        if obj.duration_seconds:
            if obj.duration_seconds < 60:
                return f"{obj.duration_seconds:.1f}s"
            elif obj.duration_seconds < 3600:
                return f"{obj.duration_seconds/60:.1f}m"
            else:
                return f"{obj.duration_seconds/3600:.1f}h"
        return '-'
    duration_display.short_description = _('Duration')

    def started_at_display(self, obj):
        return obj.started_at.strftime('%Y-%m-%d %H:%M:%S') if obj.started_at else '-'
    started_at_display.short_description = _('Started')
    started_at_display.admin_order_field = 'started_at'

    def completed_at_display(self, obj):
        return obj.completed_at.strftime('%Y-%m-%d %H:%M:%S') if obj.completed_at else '-'
    completed_at_display.short_description = _('Completed')
    completed_at_display.admin_order_field = 'completed_at'

    def initiated_by_display(self, obj):
        if obj.initiated_by:
            url = reverse('admin:users_user_change', args=[obj.initiated_by.id])
            return format_html('<a href="{}">{}</a>', url, obj.initiated_by.email)
        return 'System'
    initiated_by_display.short_description = _('Initiated By')
    initiated_by_display.admin_order_field = 'initiated_by__email'

    def get_formatted_details(self, obj):
        if obj.details:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.details, indent=2))
        return '-'
    get_formatted_details.short_description = _('Details')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=maintenance_logs.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Task', 'Status', 'Started', 'Completed', 'Duration', 'Initiated By'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.get_task_type_display(),
                obj.get_status_display(),
                obj.started_at.strftime('%Y-%m-%d %H:%M:%S') if obj.started_at else '',
                obj.completed_at.strftime('%Y-%m-%d %H:%M:%S') if obj.completed_at else '',
                obj.duration_seconds or '',
                obj.initiated_by.email if obj.initiated_by else 'System',
            ])
        self.message_user(request, f'Exported {queryset.count()} maintenance log(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('initiated_by')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ============================================================================
# REPORT ADMIN
# ============================================================================

@admin.register(Report)
class ReportAdmin(ModelAdmin):
    """
    Admin configuration for Report model.
    """
    list_display = (
        'id',
        'name_display',
        'report_type_badge',
        'generated_by_display',
        'format_display',
        'is_expired_badge',
        'download_count_display',
        'generated_at_display',
    )

    list_filter = (
        'report_type',
        'format',
        'is_public',
        ('generated_by', admin.RelatedOnlyFieldListFilter),
        'generated_at',
        'expires_at',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    search_fields = (
        'name',
        'title',
        'description',
        'generated_by__email',
    )

    ordering = ('-generated_at',)

    readonly_fields = (
        'id',
        'generated_by',
        'generated_at',
        'expires_at',
        'download_count',
        'created_at',
        'updated_at',
        'deleted_at',
        'is_expired',
        'age_days',
        'get_data_preview',
    )

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'name',
                'title',
                'description',
                'report_type',
                'format',
            )
        }),
        (_('Content'), {
            'fields': (
                'data',
                'get_data_preview',
            ),
            'classes': ('collapse',),
        }),
        (_('Date Range'), {
            'fields': (
                'date_range_start',
                'date_range_end',
            ),
            'classes': ('collapse',),
        }),
        (_('Metadata'), {
            'fields': (
                'generated_by',
                'generated_at',
                'expires_at',
                'is_expired',
                'age_days',
                'is_public',
                'download_count',
                'parameters',
                'file',
            )
        }),
        (_('System'), {
            'fields': (
                'created_at',
                'updated_at',
                'deleted_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'mark_as_public',
        'mark_as_private',
        'export_as_csv',
        'delete_expired',
        'download_selected',
    ]

    def name_display(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:admin_panel_report_change', args=[obj.id]),
            obj.name
        )
    name_display.short_description = _('Name')
    name_display.admin_order_field = 'name'

    def report_type_badge(self, obj):
        colors = {
            'daily': 'blue',
            'weekly': 'purple',
            'monthly': 'green',
            'quarterly': 'orange',
            'custom': 'gray',
        }
        color = colors.get(obj.report_type, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_report_type_display()
        )
    report_type_badge.short_description = _('Type')
    report_type_badge.admin_order_field = 'report_type'

    def generated_by_display(self, obj):
        if obj.generated_by:
            url = reverse('admin:users_user_change', args=[obj.generated_by.id])
            return format_html('<a href="{}">{}</a>', url, obj.generated_by.email)
        return 'System'
    generated_by_display.short_description = _('Generated By')
    generated_by_display.admin_order_field = 'generated_by__email'

    def format_display(self, obj):
        return obj.get_format_display()
    format_display.short_description = _('Format')
    format_display.admin_order_field = 'format'

    def is_expired_badge(self, obj):
        if obj.is_expired:
            return format_html('<span style="color: red; font-weight: bold;">Expired</span>')
        return format_html('<span style="color: green; font-weight: bold;">Active</span>')
    is_expired_badge.short_description = _('Status')
    is_expired_badge.admin_order_field = 'expires_at'

    def download_count_display(self, obj):
        return obj.download_count
    download_count_display.short_description = _('Downloads')
    download_count_display.admin_order_field = 'download_count'

    def generated_at_display(self, obj):
        return obj.generated_at.strftime('%Y-%m-%d %H:%M')
    generated_at_display.short_description = _('Generated')
    generated_at_display.admin_order_field = 'generated_at'

    def get_data_preview(self, obj):
        if obj.data:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;max-height:300px;overflow:auto;">{}</pre>', json.dumps(obj.data, indent=2)[:2000])
        return '-'
    get_data_preview.short_description = _('Data Preview')

    def mark_as_public(self, request, queryset):
        count = queryset.update(is_public=True)
        self.message_user(request, f'Marked {count} report(s) as public.')
    mark_as_public.short_description = _('Make public')

    def mark_as_private(self, request, queryset):
        count = queryset.update(is_public=False)
        self.message_user(request, f'Marked {count} report(s) as private.')
    mark_as_private.short_description = _('Make private')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=reports.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Name', 'Type', 'Generated By', 'Format', 'Expired', 'Downloads', 'Generated At'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.name,
                obj.get_report_type_display(),
                obj.generated_by.email if obj.generated_by else 'System',
                obj.get_format_display(),
                'Yes' if obj.is_expired else 'No',
                obj.download_count,
                obj.generated_at.strftime('%Y-%m-%d %H:%M'),
            ])
        self.message_user(request, f'Exported {queryset.count()} report(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def delete_expired(self, request, queryset):
        count = queryset.filter(is_expired=True).delete()[0]
        self.message_user(request, f'Deleted {count} expired report(s).')
    delete_expired.short_description = _('Delete expired selected')

    def download_selected(self, request, queryset):
        # Simulate download action
        count = queryset.count()
        self.message_user(request, f'Downloading {count} report(s)... (implement actual download logic)')
    download_selected.short_description = _('Download selected')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('generated_by')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# REPORT SCHEDULE ADMIN
# ============================================================================

@admin.register(ReportSchedule)
class ReportScheduleAdmin(ModelAdmin):
    """
    Admin configuration for ReportSchedule model.
    """
    list_display = (
        'id',
        'name_display',
        'frequency_display',
        'report_type_display',
        'is_active_badge',
        'next_run_display',
        'last_run_display',
        'created_by_display',
        'created_at_display',
    )

    list_filter = (
        'frequency',
        'report_type',
        'is_active',
        ('created_by', admin.RelatedOnlyFieldListFilter),
        'next_run',
        'last_run',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    search_fields = (
        'name',
        'description',
        'recipients',
        'created_by__email',
    )

    ordering = ('next_run',)

    readonly_fields = (
        'id',
        'created_by',
        'last_run',
        'next_run',
        'created_at',
        'updated_at',
        'deleted_at',
        'calculate_next_run_display',
    )

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'name',
                'description',
                'report_type',
                'frequency',
            )
        }),
        (_('Schedule'), {
            'fields': (
                'day_of_week',
                'day_of_month',
                'time',
                'timezone',
            )
        }),
        (_('Execution'), {
            'fields': (
                'is_active',
                'last_run',
                'next_run',
                'calculate_next_run_display',
            )
        }),
        (_('Recipients & Format'), {
            'fields': (
                'recipients',
                'format',
            )
        }),
        (_('Parameters'), {
            'fields': (
                'parameters',
            ),
            'classes': ('collapse',),
        }),
        (_('Metadata'), {
            'fields': (
                'created_by',
                'created_at',
                'updated_at',
                'deleted_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'activate_schedules',
        'deactivate_schedules',
        'run_now',
        'export_as_csv',
    ]

    def name_display(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:admin_panel_reportschedule_change', args=[obj.id]),
            obj.name
        )
    name_display.short_description = _('Name')
    name_display.admin_order_field = 'name'

    def frequency_display(self, obj):
        return obj.get_frequency_display()
    frequency_display.short_description = _('Frequency')
    frequency_display.admin_order_field = 'frequency'

    def report_type_display(self, obj):
        return obj.get_report_type_display()
    report_type_display.short_description = _('Report Type')
    report_type_display.admin_order_field = 'report_type'

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color: green; font-weight: bold;">✓ Active</span>')
        return format_html('<span style="color: red; font-weight: bold;">✗ Inactive</span>')
    is_active_badge.short_description = _('Active')
    is_active_badge.admin_order_field = 'is_active'

    def next_run_display(self, obj):
        return obj.next_run.strftime('%Y-%m-%d %H:%M') if obj.next_run else '-'
    next_run_display.short_description = _('Next Run')
    next_run_display.admin_order_field = 'next_run'

    def last_run_display(self, obj):
        return obj.last_run.strftime('%Y-%m-%d %H:%M') if obj.last_run else '-'
    last_run_display.short_description = _('Last Run')
    last_run_display.admin_order_field = 'last_run'

    def created_by_display(self, obj):
        if obj.created_by:
            url = reverse('admin:users_user_change', args=[obj.created_by.id])
            return format_html('<a href="{}">{}</a>', url, obj.created_by.email)
        return 'System'
    created_by_display.short_description = _('Created By')
    created_by_display.admin_order_field = 'created_by__email'

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def calculate_next_run_display(self, obj):
        try:
            next_run = obj.calculate_next_run()
            return next_run.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            return f'Error: {str(e)}'
    calculate_next_run_display.short_description = _('Calculated Next Run')

    def activate_schedules(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'Activated {count} schedule(s).')
    activate_schedules.short_description = _('Activate selected schedules')

    def deactivate_schedules(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'Deactivated {count} schedule(s).')
    deactivate_schedules.short_description = _('Deactivate selected schedules')

    def run_now(self, request, queryset):
        count = 0
        for schedule in queryset:
            if schedule.is_active:
                schedule.run()
                count += 1
        self.message_user(request, f'Triggered {count} schedule(s) to run now.')
    run_now.short_description = _('Run now')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=report_schedules.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Name', 'Frequency', 'Report Type', 'Active', 'Next Run', 'Created By'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.name,
                obj.get_frequency_display(),
                obj.get_report_type_display(),
                'Yes' if obj.is_active else 'No',
                obj.next_run.strftime('%Y-%m-%d %H:%M') if obj.next_run else '',
                obj.created_by.email if obj.created_by else 'System',
            ])
        self.message_user(request, f'Exported {queryset.count()} schedule(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('created_by')

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# AUDIT TRAIL ADMIN
# ============================================================================

@admin.register(AuditTrail)
class AuditTrailAdmin(ModelAdmin):
    """
    Admin configuration for AuditTrail model (read-only).
    """
    list_display = (
        'id',
        'object_display',
        'action_badge',
        'user_display',
        'content_type_display',
        'timestamp_display',
    )

    list_filter = (
        'action',
        ('content_type', admin.RelatedOnlyFieldListFilter),
        ('user', admin.RelatedOnlyFieldListFilter),
        'timestamp',
    )

    search_fields = (
        'object_id',
        'user__email',
        'changes',
        'content_type__model',
    )

    ordering = ('-timestamp',)

    readonly_fields = (
        'id',
        'content_type',
        'object_id',
        'action',
        'user',
        'changes',
        'ip_address',
        'user_agent',
        'timestamp',
        'created_at',
        'updated_at',
        'get_object_display',
        'get_changes_display',
    )

    fieldsets = (
        (_('Audit Entry'), {
            'fields': (
                'id',
                'content_type',
                'object_id',
                'get_object_display',
                'action',
            )
        }),
        (_('User'), {
            'fields': (
                'user',
                'ip_address',
                'user_agent',
            )
        }),
        (_('Changes'), {
            'fields': (
                'changes',
                'get_changes_display',
            ),
            'classes': ('collapse',),
        }),
        (_('Timing'), {
            'fields': (
                'timestamp',
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'export_as_csv',
        'delete_selected',
    ]

    def object_display(self, obj):
        return obj.get_object_display()
    object_display.short_description = _('Object')
    object_display.admin_order_field = 'object_id'

    def action_badge(self, obj):
        colors = {
            'create': 'green',
            'update': 'blue',
            'delete': 'red',
            'view': 'gray',
            'login': 'purple',
            'logout': 'purple',
            'export': 'orange',
            'import': 'orange',
        }
        color = colors.get(obj.action, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_action_display()
        )
    action_badge.short_description = _('Action')
    action_badge.admin_order_field = 'action'

    def user_display(self, obj):
        if obj.user:
            url = reverse('admin:users_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.email)
        return 'System'
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def content_type_display(self, obj):
        return obj.content_type.name if obj.content_type else '-'
    content_type_display.short_description = _('Content Type')
    content_type_display.admin_order_field = 'content_type__model'

    def timestamp_display(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')
    timestamp_display.admin_order_field = 'timestamp'

    def get_object_display(self, obj):
        return obj.get_object_display()
    get_object_display.short_description = _('Object Display')

    def get_changes_display(self, obj):
        if obj.changes:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;max-height:300px;overflow:auto;">{}</pre>', json.dumps(obj.changes, indent=2))
        return '-'
    get_changes_display.short_description = _('Changes')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=audit_trails.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Action', 'User', 'Content Type', 'Object ID', 'Timestamp'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.get_action_display(),
                obj.user.email if obj.user else 'System',
                obj.content_type.name if obj.content_type else '',
                obj.object_id,
                obj.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        self.message_user(request, f'Exported {queryset.count()} audit trail(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} audit trail(s).')
    delete_selected.short_description = _('Delete selected')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'content_type')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# DASHBOARD WIDGET ADMIN
# ============================================================================

@admin.register(DashboardWidget)
class DashboardWidgetAdmin(ModelAdmin):
    """
    Admin configuration for DashboardWidget model.
    """
    list_display = (
        'id',
        'title_display',
        'widget_type_badge',
        'admin_display',
        'is_system_badge',
        'is_active_badge',
        'order_display',
        'updated_at_display',
    )

    list_filter = (
        'widget_type',
        'is_system',
        'is_active',
        ('admin', admin.RelatedOnlyFieldListFilter),
        'updated_at',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    search_fields = (
        'name',
        'title',
        'description',
        'admin__email',
        'permissions',
    )

    ordering = ('order', 'title')

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'deleted_at',
        'is_user_widget',
        'get_configuration_display',
    )

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'name',
                'title',
                'description',
                'widget_type',
            )
        }),
        (_('Configuration'), {
            'fields': (
                'configuration',
                'get_configuration_display',
            ),
            'classes': ('collapse',),
        }),
        (_('Ownership'), {
            'fields': (
                'admin',
                'is_system',
                'is_user_widget',
            )
        }),
        (_('Status & Order'), {
            'fields': (
                'is_active',
                'order',
                'permissions',
            )
        }),
        (_('System'), {
            'fields': (
                'created_at',
                'updated_at',
                'deleted_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'activate_widgets',
        'deactivate_widgets',
        'make_system',
        'make_user',
        'export_as_csv',
    ]

    def title_display(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:admin_panel_dashboardwidget_change', args=[obj.id]),
            obj.title
        )
    title_display.short_description = _('Title')
    title_display.admin_order_field = 'title'

    def widget_type_badge(self, obj):
        colors = {
            'stats': 'blue',
            'chart': 'purple',
            'table': 'green',
            'list': 'orange',
            'custom': 'gray',
            'alert': 'red',
            'progress': 'teal',
        }
        color = colors.get(obj.widget_type, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_widget_type_display()
        )
    widget_type_badge.short_description = _('Type')
    widget_type_badge.admin_order_field = 'widget_type'

    def admin_display(self, obj):
        if obj.admin:
            url = reverse('admin:users_user_change', args=[obj.admin.id])
            return format_html('<a href="{}">{}</a>', url, obj.admin.email)
        return 'System'
    admin_display.short_description = _('Admin')
    admin_display.admin_order_field = 'admin__email'

    def is_system_badge(self, obj):
        return '✓' if obj.is_system else '✗'
    is_system_badge.short_description = _('System')
    is_system_badge.admin_order_field = 'is_system'

    def is_active_badge(self, obj):
        return '✓' if obj.is_active else '✗'
    is_active_badge.short_description = _('Active')
    is_active_badge.admin_order_field = 'is_active'

    def order_display(self, obj):
        return obj.order
    order_display.short_description = _('Order')
    order_display.admin_order_field = 'order'

    def updated_at_display(self, obj):
        return obj.updated_at.strftime('%Y-%m-%d %H:%M')
    updated_at_display.short_description = _('Updated')
    updated_at_display.admin_order_field = 'updated_at'

    def get_configuration_display(self, obj):
        if obj.configuration:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.configuration, indent=2))
        return '-'
    get_configuration_display.short_description = _('Configuration')

    def activate_widgets(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'Activated {count} widget(s).')
    activate_widgets.short_description = _('Activate selected widgets')

    def deactivate_widgets(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'Deactivated {count} widget(s).')
    deactivate_widgets.short_description = _('Deactivate selected widgets')

    def make_system(self, request, queryset):
        count = queryset.update(is_system=True, admin=None)
        self.message_user(request, f'Made {count} widget(s) system-wide.')
    make_system.short_description = _('Make system-wide')

    def make_user(self, request, queryset):
        # This would need a user to assign; for bulk, not meaningful, so we skip.
        self.message_user(request, 'Please edit each widget individually to assign a user.', level='WARNING')
    make_user.short_description = _('Assign to a user (manual)')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=dashboard_widgets.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Name', 'Title', 'Type', 'System', 'Active', 'Order', 'Admin'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.name,
                obj.title,
                obj.get_widget_type_display(),
                'Yes' if obj.is_system else 'No',
                'Yes' if obj.is_active else 'No',
                obj.order,
                obj.admin.email if obj.admin else 'System',
            ])
        self.message_user(request, f'Exported {queryset.count()} widget(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('admin')

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser