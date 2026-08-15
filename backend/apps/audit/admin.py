"""
Admin configuration for the audit app.

This module provides comprehensive Django admin interfaces for all audit models:
- AuditLog: Central audit log with full CRUD and filtering
- AuditEvent: Event-based audit records with processing controls
- AuditRule: Rules for audit filtering and alerting with inline alerts
- AuditAlert: Alerts generated from audit rules with status management
- AuditReport: Scheduled or on-demand audit reports with download
- AuditRetentionPolicy: Data retention policies with enforcement
- SecurityEvent: Security-related events with severity tracking
- UserActivity: User activity tracking with analytics
- SystemHealth: System health monitoring with component status
- PerformanceMetric: Performance metrics with aggregation
- AnomalyDetection: Detected anomalies with resolution actions

All admin classes include custom list displays, filters, search fields,
inline relationships, custom actions, and detailed fieldsets for efficient management.
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
from django.db.models import Count, Sum, Q, Avg
import csv
import json
from io import StringIO

from apps.users.models import User
from apps.common.utils import format_currency, log_audit_event

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


# ============================================================================
# INLINE CLASSES
# ============================================================================

class AuditAlertInline(TabularInline):
    """Inline for audit alerts (for a rule)."""
    model = AuditAlert
    extra = 0
    fields = ('severity', 'status', 'message', 'timestamp')
    readonly_fields = ('severity', 'status', 'message', 'timestamp')
    can_delete = False
    max_num = 10
    verbose_name = _('Alert')
    verbose_name_plural = _('Alerts')
    ordering = ('-timestamp',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('rule', 'acknowledged_by')


class AuditEventInline(TabularInline):
    """Inline for audit events."""
    model = AuditEvent
    extra = 0
    fields = ('event_type', 'user', 'processed', 'created_at')
    readonly_fields = ('event_type', 'user', 'processed', 'created_at')
    can_delete = False
    max_num = 10
    verbose_name = _('Event')
    verbose_name_plural = _('Events')
    ordering = ('-created_at',)


class AuditLogInline(TabularInline):
    """Inline for audit logs (for a user)."""
    model = AuditLog
    extra = 0
    fields = ('action', 'resource', 'severity', 'timestamp')
    readonly_fields = ('action', 'resource', 'severity', 'timestamp')
    can_delete = False
    max_num = 10
    verbose_name = _('Audit Log')
    verbose_name_plural = _('Audit Logs')
    ordering = ('-timestamp',)


class SecurityEventInline(TabularInline):
    """Inline for security events (for a user)."""
    model = SecurityEvent
    extra = 0
    fields = ('event_type', 'severity', 'description', 'timestamp')
    readonly_fields = ('event_type', 'severity', 'description', 'timestamp')
    can_delete = False
    max_num = 10
    verbose_name = _('Security Event')
    verbose_name_plural = _('Security Events')
    ordering = ('-timestamp',)


# ============================================================================
# AUDIT LOG ADMIN
# ============================================================================

@admin.register(AuditLog)
class AuditLogAdmin(ModelAdmin):
    """
    Admin configuration for AuditLog model with comprehensive features.
    """
    list_display = (
        'id',
        'user_display',
        'action_badge',
        'resource_display',
        'resource_id_display',
        'severity_badge',
        'timestamp_display',
        'ip_address_short',
        'actions_display',
    )

    list_filter = (
        'action',
        'resource',
        'severity',
        ('user', admin.RelatedOnlyFieldListFilter),
        'timestamp',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    search_fields = (
        'id',
        'user__email',
        'user__first_name',
        'user__last_name',
        'action',
        'resource',
        'resource_id',
        'details',
        'ip_address',
        'user_agent',
    )

    ordering = ('-timestamp',)

    readonly_fields = (
        'id',
        'user',
        'action',
        'resource',
        'resource_id',
        'details',
        'ip_address',
        'user_agent',
        'severity',
        'timestamp',
        'created_at',
        'updated_at',
        'deleted_at',
        'get_formatted_details',
        'get_audit_summary',
    )

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'id',
                'user',
                'action',
                'resource',
                'resource_id',
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
                'severity',
                'timestamp',
            )
        }),
        (_('Statistics'), {
            'fields': (
                'get_audit_summary',
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

    inlines = []

    actions = [
        'export_as_csv',
        'export_as_json',
        'delete_selected',
        'mark_as_critical',
        'mark_as_warning',
        'mark_as_info',
        'mark_as_deleted',
        'restore_deleted',
        'bulk_export',
    ]

    list_per_page = 50
    list_max_show_all = 200
    save_as = True

    # --------------------------------------------------------------------------
    # CUSTOM DISPLAY METHODS
    # --------------------------------------------------------------------------

    def user_display(self, obj):
        if obj.user:
            url = reverse('admin:users_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.email)
        return '<span style="color: gray;">System</span>'
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'
    user_display.allow_tags = True

    def action_badge(self, obj):
        colors = {
            'CREATE': '#28a745',
            'UPDATE': '#007bff',
            'DELETE': '#dc3545',
            'VIEW': '#6c757d',
            'LOGIN': '#6f42c1',
            'LOGOUT': '#6f42c1',
            'EXPORT': '#fd7e14',
            'IMPORT': '#fd7e14',
            'REGISTER': '#20c997',
            'VERIFY': '#20c997',
            'APPROVE': '#17a2b8',
            'REJECT': '#dc3545',
            'CANCEL': '#dc3545',
            'SUSPEND': '#dc3545',
            'UNSUSPEND': '#28a745',
            'LOCK': '#dc3545',
            'UNLOCK': '#28a745',
            'PAYMENT': '#007bff',
            'REFUND': '#fd7e14',
        }
        color = colors.get(obj.action, '#6c757d')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            obj.action_display
        )
    action_badge.short_description = _('Action')
    action_badge.admin_order_field = 'action'

    def resource_display(self, obj):
        return format_html('<code>{}</code>', obj.resource)
    resource_display.short_description = _('Resource')
    resource_display.admin_order_field = 'resource'

    def resource_id_display(self, obj):
        if obj.resource_id:
            return format_html('<code>{}</code>', obj.resource_id)
        return '-'
    resource_id_display.short_description = _('Resource ID')
    resource_id_display.admin_order_field = 'resource_id'

    def severity_badge(self, obj):
        colors = {
            'info': '#17a2b8',
            'warning': '#ffc107',
            'error': '#dc3545',
            'critical': '#8b0000',
        }
        color = colors.get(obj.severity, '#6c757d')
        text_color = 'black' if obj.severity == 'warning' else 'white'
        return format_html(
            '<span style="background: {}; color: {}; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            text_color,
            obj.get_severity_display()
        )
    severity_badge.short_description = _('Severity')
    severity_badge.admin_order_field = 'severity'

    def timestamp_display(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')
    timestamp_display.admin_order_field = 'timestamp'

    def ip_address_short(self, obj):
        if obj.ip_address:
            return obj.ip_address
        return '-'
    ip_address_short.short_description = _('IP')

    def actions_display(self, obj):
        actions = []
        if obj.severity != 'critical':
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #8b0000; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Mark Critical</button>',
                    f'/admin/audit/auditlog/{obj.id}/mark_critical/'
                )
            )
        if obj.severity != 'warning':
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #ffc107; color: black; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Mark Warning</button>',
                    f'/admin/audit/auditlog/{obj.id}/mark_warning/'
                )
            )
        if obj.severity != 'info':
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #17a2b8; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Mark Info</button>',
                    f'/admin/audit/auditlog/{obj.id}/mark_info/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Quick Actions')
    actions_display.allow_tags = True

    def get_formatted_details(self, obj):
        if obj.details:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;max-height:300px;overflow:auto;">{}</pre>', json.dumps(obj.details, indent=2))
        return '-'
    get_formatted_details.short_description = _('Formatted Details')

    def get_audit_summary(self, obj):
        # Count similar logs
        similar_count = AuditLog.objects.filter(
            action=obj.action,
            resource=obj.resource,
            user=obj.user,
            severity=obj.severity
        ).count()
        return format_html(
            '<table style="border-collapse: collapse;">'
            '<tr><td>Similar logs (same action, resource, user):</td><td style="font-weight: bold; padding-left: 10px;">{}</td></tr>'
            '<tr><td>User\'s total logs:</td><td style="font-weight: bold; padding-left: 10px;">{}</td></tr>'
            '</table>',
            similar_count,
            AuditLog.objects.filter(user=obj.user).count() if obj.user else 0
        )
    get_audit_summary.short_description = _('Summary')

    # --------------------------------------------------------------------------
    # CUSTOM ACTIONS
    # --------------------------------------------------------------------------

    def export_as_csv(self, request, queryset):
        meta = self.model._meta
        field_names = ['id', 'user__email', 'action', 'resource', 'resource_id', 'severity', 'ip_address', 'timestamp']
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename={meta.verbose_name_plural}.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'User', 'Action', 'Resource', 'Resource ID', 'Severity', 'IP', 'Timestamp'])
        for obj in queryset:
            row = [
                obj.id,
                obj.user.email if obj.user else 'System',
                obj.action_display,
                obj.resource,
                obj.resource_id,
                obj.get_severity_display(),
                obj.ip_address or '',
                obj.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            ]
            writer.writerow(row)
        self.message_user(request, f'Exported {queryset.count()} audit log(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def export_as_json(self, request, queryset):
        data = []
        for obj in queryset:
            data.append({
                'id': obj.id,
                'user': obj.user.email if obj.user else 'System',
                'action': obj.action_display,
                'resource': obj.resource,
                'resource_id': obj.resource_id,
                'severity': obj.severity,
                'details': obj.details,
                'ip_address': obj.ip_address,
                'timestamp': obj.timestamp.isoformat(),
            })
        response = HttpResponse(json.dumps(data, indent=2), content_type='application/json')
        response['Content-Disposition'] = 'attachment; filename=audit_logs.json'
        self.message_user(request, f'Exported {queryset.count()} audit log(s).')
        return response
    export_as_json.short_description = _('Export selected as JSON')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} audit log(s).')
    delete_selected.short_description = _('Delete selected')

    def mark_as_critical(self, request, queryset):
        count = queryset.update(severity='critical')
        self.message_user(request, f'Marked {count} audit log(s) as critical.')
    mark_as_critical.short_description = _('Mark selected as critical')

    def mark_as_warning(self, request, queryset):
        count = queryset.update(severity='warning')
        self.message_user(request, f'Marked {count} audit log(s) as warning.')
    mark_as_warning.short_description = _('Mark selected as warning')

    def mark_as_info(self, request, queryset):
        count = queryset.update(severity='info')
        self.message_user(request, f'Marked {count} audit log(s) as info.')
    mark_as_info.short_description = _('Mark selected as info')

    def mark_as_deleted(self, request, queryset):
        count = 0
        for obj in queryset:
            if not obj.deleted_at:
                obj.deleted_at = timezone.now()
                obj.save(update_fields=['deleted_at'])
                count += 1
        self.message_user(request, f'Soft deleted {count} audit log(s).')
    mark_as_deleted.short_description = _('Soft delete selected')

    def restore_deleted(self, request, queryset):
        count = queryset.filter(deleted_at__isnull=False).update(deleted_at=None)
        self.message_user(request, f'Restored {count} soft-deleted audit log(s).')
    restore_deleted.short_description = _('Restore selected')

    def bulk_export(self, request, queryset):
        # Simple placeholder for bulk export
        self.message_user(request, f'Bulk export of {queryset.count()} logs initiated.')
    bulk_export.short_description = _('Bulk export selected')

    # --------------------------------------------------------------------------
    # CUSTOM ADMIN VIEWS
    # --------------------------------------------------------------------------

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:log_id>/mark_critical/', self.admin_site.admin_view(self.mark_critical_view), name='mark_critical'),
            path('<int:log_id>/mark_warning/', self.admin_site.admin_view(self.mark_warning_view), name='mark_warning'),
            path('<int:log_id>/mark_info/', self.admin_site.admin_view(self.mark_info_view), name='mark_info'),
        ]
        return custom_urls + urls

    def mark_critical_view(self, request, log_id):
        log = get_object_or_404(AuditLog, id=log_id)
        log.severity = 'critical'
        log.save(update_fields=['severity'])
        self.message_user(request, f'Log #{log.id} marked as critical.')
        return HttpResponseRedirect(reverse('admin:audit_auditlog_changelist'))

    def mark_warning_view(self, request, log_id):
        log = get_object_or_404(AuditLog, id=log_id)
        log.severity = 'warning'
        log.save(update_fields=['severity'])
        self.message_user(request, f'Log #{log.id} marked as warning.')
        return HttpResponseRedirect(reverse('admin:audit_auditlog_changelist'))

    def mark_info_view(self, request, log_id):
        log = get_object_or_404(AuditLog, id=log_id)
        log.severity = 'info'
        log.save(update_fields=['severity'])
        self.message_user(request, f'Log #{log.id} marked as info.')
        return HttpResponseRedirect(reverse('admin:audit_auditlog_changelist'))

    # --------------------------------------------------------------------------
    # OVERRIDEN METHODS
    # --------------------------------------------------------------------------

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# AUDIT EVENT ADMIN
# ============================================================================

@admin.register(AuditEvent)
class AuditEventAdmin(ModelAdmin):
    """
    Admin configuration for AuditEvent model with processing controls.
    """
    list_display = (
        'id',
        'event_type_badge',
        'user_display',
        'group_display',
        'processed_badge',
        'error_badge',
        'created_at_display',
        'actions_display',
    )

    list_filter = (
        'event_type',
        'processed',
        ('user', admin.RelatedOnlyFieldListFilter),
        ('group', admin.RelatedOnlyFieldListFilter),
        'created_at',
    )

    search_fields = (
        'id',
        'event_type',
        'user__email',
        'group__name',
        'data',
        'error_message',
    )

    ordering = ('-created_at',)

    readonly_fields = (
        'id',
        'event_type',
        'user',
        'group',
        'data',
        'processed',
        'processed_at',
        'error_message',
        'created_at',
        'updated_at',
        'get_data_display',
        'get_event_summary',
    )

    fieldsets = (
        (_('Event'), {
            'fields': (
                'id',
                'event_type',
                'user',
                'group',
            )
        }),
        (_('Data'), {
            'fields': (
                'data',
                'get_data_display',
            ),
            'classes': ('collapse',),
        }),
        (_('Processing'), {
            'fields': (
                'processed',
                'processed_at',
                'error_message',
            )
        }),
        (_('Summary'), {
            'fields': (
                'get_event_summary',
            ),
            'classes': ('collapse',),
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
        'process_events',
        'retry_events',
        'delete_selected',
        'export_as_csv',
        'mark_processed',
    ]

    def event_type_badge(self, obj):
        return format_html(
            '<code style="background: #e9ecef; padding: 2px 6px; border-radius: 4px; font-size: 12px;">{}</code>',
            obj.event_type
        )
    event_type_badge.short_description = _('Event Type')
    event_type_badge.admin_order_field = 'event_type'

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def group_display(self, obj):
        if obj.group:
            url = reverse('admin:groups_group_change', args=[obj.group.id])
            return format_html('<a href="{}">{}</a>', url, obj.group.name)
        return '-'
    group_display.short_description = _('Group')
    group_display.admin_order_field = 'group__name'

    def processed_badge(self, obj):
        if obj.processed:
            return format_html('<span style="color: #28a745; font-weight: bold;">✓ Processed</span>')
        return format_html('<span style="color: #ffc107; font-weight: bold;">⏳ Pending</span>')
    processed_badge.short_description = _('Processed')
    processed_badge.admin_order_field = 'processed'

    def error_badge(self, obj):
        if obj.error_message:
            return format_html('<span style="color: #dc3545; font-weight: bold;">✗ Error</span>')
        return '-'
    error_badge.short_description = _('Error')

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def actions_display(self, obj):
        actions = []
        if not obj.processed:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #28a745; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Process</button>',
                    f'/admin/audit/auditevent/{obj.id}/process/'
                )
            )
        if obj.error_message:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #17a2b8; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Retry</button>',
                    f'/admin/audit/auditevent/{obj.id}/retry/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')

    def get_data_display(self, obj):
        if obj.data:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;max-height:300px;overflow:auto;">{}</pre>', json.dumps(obj.data, indent=2))
        return '-'
    get_data_display.short_description = _('Data')

    def get_event_summary(self, obj):
        # Count similar events
        similar = AuditEvent.objects.filter(event_type=obj.event_type).count()
        return format_html(
            '<table><tr><td>Similar events (same type):</td><td style="font-weight: bold; padding-left:10px;">{}</td></tr></table>',
            similar
        )
    get_event_summary.short_description = _('Summary')

    def process_events(self, request, queryset):
        count = 0
        for obj in queryset.filter(processed=False):
            obj.process()
            count += 1
        self.message_user(request, f'Processed {count} event(s).')
    process_events.short_description = _('Process selected events')

    def retry_events(self, request, queryset):
        count = 0
        for obj in queryset.filter(processed=False, error_message__isnull=False):
            obj.retry()
            count += 1
        self.message_user(request, f'Retried {count} event(s).')
    retry_events.short_description = _('Retry selected events')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} event(s).')
    delete_selected.short_description = _('Delete selected')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=audit_events.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Event Type', 'User', 'Group', 'Processed', 'Created'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.event_type,
                obj.user.email,
                obj.group.name if obj.group else '',
                'Yes' if obj.processed else 'No',
                obj.created_at.strftime('%Y-%m-%d %H:%M'),
            ])
        self.message_user(request, f'Exported {queryset.count()} event(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def mark_processed(self, request, queryset):
        count = queryset.filter(processed=False).update(processed=True, processed_at=timezone.now())
        self.message_user(request, f'Marked {count} event(s) as processed.')
    mark_processed.short_description = _('Mark selected as processed')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'group')

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:event_id>/process/', self.admin_site.admin_view(self.process_view), name='process'),
            path('<int:event_id>/retry/', self.admin_site.admin_view(self.retry_view), name='retry'),
        ]
        return custom_urls + urls

    def process_view(self, request, event_id):
        event = get_object_or_404(AuditEvent, id=event_id)
        event.process()
        self.message_user(request, f'Event #{event.id} processed.')
        return HttpResponseRedirect(reverse('admin:audit_auditevent_changelist'))

    def retry_view(self, request, event_id):
        event = get_object_or_404(AuditEvent, id=event_id)
        event.retry()
        self.message_user(request, f'Event #{event.id} retried.')
        return HttpResponseRedirect(reverse('admin:audit_auditevent_changelist'))

    def has_add_permission(self, request):
        return False


# ============================================================================
# AUDIT RULE ADMIN
# ============================================================================

@admin.register(AuditRule)
class AuditRuleAdmin(ModelAdmin):
    """
    Admin configuration for AuditRule model with inline alerts.
    """
    list_display = (
        'id',
        'name_display',
        'action_badge',
        'severity_badge',
        'is_active_badge',
        'trigger_count_display',
        'last_triggered_display',
        'created_at_display',
        'actions_display',
    )

    list_filter = (
        'action',
        'severity',
        'is_active',
        'created_at',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    search_fields = (
        'name',
        'description',
        'condition',
    )

    ordering = ('-created_at',)

    readonly_fields = (
        'id',
        'trigger_count',
        'last_triggered',
        'created_at',
        'updated_at',
        'deleted_at',
        'get_condition_display',
        'get_rule_summary',
    )

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'id',
                'name',
                'description',
                'action',
                'severity',
                'is_active',
            )
        }),
        (_('Condition'), {
            'fields': (
                'condition',
                'get_condition_display',
            ),
            'classes': ('collapse',),
        }),
        (_('Statistics'), {
            'fields': (
                'trigger_count',
                'last_triggered',
                'get_rule_summary',
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

    inlines = [AuditAlertInline]

    actions = [
        'activate_rules',
        'deactivate_rules',
        'export_as_csv',
        'delete_selected',
        'duplicate_rules',
        'reset_trigger_count',
    ]

    def name_display(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:audit_auditrule_change', args=[obj.id]),
            obj.name
        )
    name_display.short_description = _('Name')
    name_display.admin_order_field = 'name'

    def action_badge(self, obj):
        return obj.get_action_display()
    action_badge.short_description = _('Action')
    action_badge.admin_order_field = 'action'

    def severity_badge(self, obj):
        colors = {
            'info': '#17a2b8',
            'warning': '#ffc107',
            'error': '#dc3545',
            'critical': '#8b0000',
        }
        color = colors.get(obj.severity, '#6c757d')
        text_color = 'black' if obj.severity == 'warning' else 'white'
        return format_html(
            '<span style="background: {}; color: {}; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            text_color,
            obj.get_severity_display()
        )
    severity_badge.short_description = _('Severity')
    severity_badge.admin_order_field = 'severity'

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color: #28a745; font-weight: bold;">✓ Active</span>')
        return format_html('<span style="color: #dc3545; font-weight: bold;">✗ Inactive</span>')
    is_active_badge.short_description = _('Active')
    is_active_badge.admin_order_field = 'is_active'

    def trigger_count_display(self, obj):
        return obj.trigger_count
    trigger_count_display.short_description = _('Triggers')
    trigger_count_display.admin_order_field = 'trigger_count'

    def last_triggered_display(self, obj):
        if obj.last_triggered:
            return obj.last_triggered.strftime('%Y-%m-%d %H:%M')
        return '-'
    last_triggered_display.short_description = _('Last Triggered')
    last_triggered_display.admin_order_field = 'last_triggered'

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def actions_display(self, obj):
        actions = []
        if obj.is_active:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #dc3545; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Deactivate</button>',
                    f'/admin/audit/auditrule/{obj.id}/toggle_active/'
                )
            )
        else:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #28a745; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Activate</button>',
                    f'/admin/audit/auditrule/{obj.id}/toggle_active/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')

    def get_condition_display(self, obj):
        if obj.condition:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.condition, indent=2))
        return '-'
    get_condition_display.short_description = _('Condition')

    def get_rule_summary(self, obj):
        alerts = obj.alerts.count()
        return format_html(
            '<table><tr><td>Alerts generated:</td><td style="font-weight: bold; padding-left:10px;">{}</td></tr></table>',
            alerts
        )
    get_rule_summary.short_description = _('Summary')

    def activate_rules(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'Activated {count} rule(s).')
    activate_rules.short_description = _('Activate selected rules')

    def deactivate_rules(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'Deactivated {count} rule(s).')
    deactivate_rules.short_description = _('Deactivate selected rules')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=audit_rules.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Name', 'Action', 'Severity', 'Active', 'Triggers', 'Last Triggered'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.name,
                obj.get_action_display(),
                obj.get_severity_display(),
                'Yes' if obj.is_active else 'No',
                obj.trigger_count,
                obj.last_triggered.strftime('%Y-%m-%d %H:%M') if obj.last_triggered else '',
            ])
        self.message_user(request, f'Exported {queryset.count()} rule(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        for obj in queryset:
            obj.deleted_at = timezone.now()
            obj.save()
        self.message_user(request, f'Soft deleted {count} rule(s).')
    delete_selected.short_description = _('Soft delete selected')

    def duplicate_rules(self, request, queryset):
        count = 0
        for obj in queryset:
            new_obj = obj
            new_obj.pk = None
            new_obj.name = f"{obj.name}_copy_{count+1}"
            new_obj.trigger_count = 0
            new_obj.last_triggered = None
            new_obj.created_at = timezone.now()
            new_obj.updated_at = timezone.now()
            new_obj.save()
            count += 1
        self.message_user(request, f'Duplicated {count} rule(s).')
    duplicate_rules.short_description = _('Duplicate selected rules')

    def reset_trigger_count(self, request, queryset):
        count = queryset.update(trigger_count=0, last_triggered=None)
        self.message_user(request, f'Reset trigger count for {count} rule(s).')
    reset_trigger_count.short_description = _('Reset trigger count')

    def get_queryset(self, request):
        return super().get_queryset(request)

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:rule_id>/toggle_active/', self.admin_site.admin_view(self.toggle_active_view), name='toggle_active'),
        ]
        return custom_urls + urls

    def toggle_active_view(self, request, rule_id):
        rule = get_object_or_404(AuditRule, id=rule_id)
        rule.is_active = not rule.is_active
        rule.save(update_fields=['is_active'])
        self.message_user(request, f'Rule "{rule.name}" {"activated" if rule.is_active else "deactivated"}.')
        return HttpResponseRedirect(reverse('admin:audit_auditrule_changelist'))

    def has_add_permission(self, request):
        return request.user.is_superuser


# ============================================================================
# AUDIT ALERT ADMIN
# ============================================================================

@admin.register(AuditAlert)
class AuditAlertAdmin(ModelAdmin):
    """
    Admin configuration for AuditAlert model with status management.
    """
    list_display = (
        'id',
        'rule_display',
        'severity_badge',
        'message_short',
        'status_badge',
        'timestamp_display',
        'acknowledged_by_display',
        'actions_display',
    )

    list_filter = (
        'severity',
        'status',
        ('rule', admin.RelatedOnlyFieldListFilter),
        'timestamp',
    )

    search_fields = (
        'message',
        'rule__name',
        'audit_log__user__email',
        'audit_log__action',
        'acknowledged_by__email',
    )

    ordering = ('-timestamp',)

    readonly_fields = (
        'id',
        'rule',
        'audit_log',
        'severity',
        'message',
        'status',
        'acknowledged_by',
        'acknowledged_at',
        'resolved_at',
        'timestamp',
        'created_at',
        'updated_at',
        'get_alert_summary',
        'get_audit_log_link',
    )

    fieldsets = (
        (_('Alert'), {
            'fields': (
                'id',
                'rule',
                'audit_log',
                'severity',
                'message',
            )
        }),
        (_('Status'), {
            'fields': (
                'status',
                'acknowledged_by',
                'acknowledged_at',
                'resolved_at',
            )
        }),
        (_('Links'), {
            'fields': (
                'get_audit_log_link',
            ),
            'classes': ('collapse',),
        }),
        (_('Summary'), {
            'fields': (
                'get_alert_summary',
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
        'acknowledge_alerts',
        'resolve_alerts',
        'dismiss_alerts',
        'delete_selected',
        'export_as_csv',
        'escalate_alerts',
    ]

    def rule_display(self, obj):
        url = reverse('admin:audit_auditrule_change', args=[obj.rule.id])
        return format_html('<a href="{}">{}</a>', url, obj.rule.name)
    rule_display.short_description = _('Rule')
    rule_display.admin_order_field = 'rule__name'

    def severity_badge(self, obj):
        colors = {
            'info': '#17a2b8',
            'warning': '#ffc107',
            'error': '#dc3545',
            'critical': '#8b0000',
        }
        color = colors.get(obj.severity, '#6c757d')
        text_color = 'black' if obj.severity == 'warning' else 'white'
        return format_html(
            '<span style="background: {}; color: {}; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            text_color,
            obj.get_severity_display()
        )
    severity_badge.short_description = _('Severity')
    severity_badge.admin_order_field = 'severity'

    def message_short(self, obj):
        return obj.message[:50] + ('...' if len(obj.message) > 50 else '')
    message_short.short_description = _('Message')
    message_short.admin_order_field = 'message'

    def status_badge(self, obj):
        colors = {
            'new': '#ffc107',
            'acknowledged': '#17a2b8',
            'resolved': '#28a745',
            'dismissed': '#6c757d',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def timestamp_display(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')
    timestamp_display.admin_order_field = 'timestamp'

    def acknowledged_by_display(self, obj):
        if obj.acknowledged_by:
            url = reverse('admin:users_user_change', args=[obj.acknowledged_by.id])
            return format_html('<a href="{}">{}</a>', url, obj.acknowledged_by.email)
        return '-'
    acknowledged_by_display.short_description = _('Acknowledged By')
    acknowledged_by_display.admin_order_field = 'acknowledged_by__email'

    def actions_display(self, obj):
        actions = []
        if obj.status == 'new':
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #17a2b8; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Acknowledge</button>',
                    f'/admin/audit/auditalert/{obj.id}/acknowledge/'
                )
            )
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #6c757d; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Dismiss</button>',
                    f'/admin/audit/auditalert/{obj.id}/dismiss/'
                )
            )
        if obj.status in ['new', 'acknowledged']:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #28a745; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Resolve</button>',
                    f'/admin/audit/auditalert/{obj.id}/resolve/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')

    def get_alert_summary(self, obj):
        return format_html(
            '<table><tr><td>Alert age:</td><td style="font-weight: bold; padding-left:10px;">{} days</td></tr></table>',
            (timezone.now() - obj.timestamp).days
        )
    get_alert_summary.short_description = _('Summary')

    def get_audit_log_link(self, obj):
        if obj.audit_log:
            url = reverse('admin:audit_auditlog_change', args=[obj.audit_log.id])
            return format_html('<a href="{}">View Audit Log #{}</a>', url, obj.audit_log.id)
        return '-'
    get_audit_log_link.short_description = _('Audit Log Link')

    def acknowledge_alerts(self, request, queryset):
        count = 0
        user = request.user
        for obj in queryset.filter(status='new'):
            obj.acknowledge(user)
            count += 1
        self.message_user(request, f'Acknowledged {count} alert(s).')
    acknowledge_alerts.short_description = _('Acknowledge selected alerts')

    def resolve_alerts(self, request, queryset):
        count = 0
        for obj in queryset.filter(status__in=['new', 'acknowledged']):
            obj.resolve()
            count += 1
        self.message_user(request, f'Resolved {count} alert(s).')
    resolve_alerts.short_description = _('Resolve selected alerts')

    def dismiss_alerts(self, request, queryset):
        count = 0
        for obj in queryset.filter(status='new'):
            obj.dismiss()
            count += 1
        self.message_user(request, f'Dismissed {count} alert(s).')
    dismiss_alerts.short_description = _('Dismiss selected alerts')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} alert(s).')
    delete_selected.short_description = _('Delete selected')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=audit_alerts.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Rule', 'Severity', 'Status', 'Message', 'Timestamp', 'Acknowledged By'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.rule.name,
                obj.get_severity_display(),
                obj.get_status_display(),
                obj.message,
                obj.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                obj.acknowledged_by.email if obj.acknowledged_by else '',
            ])
        self.message_user(request, f'Exported {queryset.count()} alert(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def escalate_alerts(self, request, queryset):
        count = queryset.filter(status='new').update(severity='critical')
        self.message_user(request, f'Escalated {count} alert(s) to critical.')
    escalate_alerts.short_description = _('Escalate selected alerts')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('rule', 'audit_log', 'acknowledged_by')

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:alert_id>/acknowledge/', self.admin_site.admin_view(self.acknowledge_view), name='acknowledge'),
            path('<int:alert_id>/resolve/', self.admin_site.admin_view(self.resolve_view), name='resolve'),
            path('<int:alert_id>/dismiss/', self.admin_site.admin_view(self.dismiss_view), name='dismiss'),
        ]
        return custom_urls + urls

    def acknowledge_view(self, request, alert_id):
        alert = get_object_or_404(AuditAlert, id=alert_id)
        alert.acknowledge(request.user)
        self.message_user(request, f'Alert #{alert.id} acknowledged.')
        return HttpResponseRedirect(reverse('admin:audit_auditalert_changelist'))

    def resolve_view(self, request, alert_id):
        alert = get_object_or_404(AuditAlert, id=alert_id)
        alert.resolve()
        self.message_user(request, f'Alert #{alert.id} resolved.')
        return HttpResponseRedirect(reverse('admin:audit_auditalert_changelist'))

    def dismiss_view(self, request, alert_id):
        alert = get_object_or_404(AuditAlert, id=alert_id)
        alert.dismiss()
        self.message_user(request, f'Alert #{alert.id} dismissed.')
        return HttpResponseRedirect(reverse('admin:audit_auditalert_changelist'))

    def has_add_permission(self, request):
        return False


# ============================================================================
# AUDIT REPORT ADMIN
# ============================================================================

@admin.register(AuditReport)
class AuditReportAdmin(ModelAdmin):
    """
    Admin configuration for AuditReport model.
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
        'actions_display',
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
        'description',
        'generated_by__email',
        'parameters',
        'data',
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
        'get_data_preview',
        'get_report_summary',
        'get_parameters_display',
    )

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'id',
                'name',
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
        (_('Parameters'), {
            'fields': (
                'parameters',
                'get_parameters_display',
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
                'is_public',
                'download_count',
                'file',
            )
        }),
        (_('Summary'), {
            'fields': (
                'get_report_summary',
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
        'mark_as_public',
        'mark_as_private',
        'export_as_csv',
        'delete_expired',
        'download_selected',
        'extend_expiry',
    ]

    def name_display(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:audit_auditreport_change', args=[obj.id]),
            obj.name
        )
    name_display.short_description = _('Name')
    name_display.admin_order_field = 'name'

    def report_type_badge(self, obj):
        colors = {
            'compliance': '#17a2b8',
            'security': '#6f42c1',
            'activity': '#28a745',
            'custom': '#6c757d',
        }
        color = colors.get(obj.report_type, '#6c757d')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
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
            return format_html('<span style="color: #dc3545; font-weight: bold;">Expired</span>')
        return format_html('<span style="color: #28a745; font-weight: bold;">Active</span>')
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

    def actions_display(self, obj):
        actions = []
        if not obj.is_expired:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #28a745; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Download</button>',
                    f'/admin/audit/auditreport/{obj.id}/download/'
                )
            )
        if obj.is_expired:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #17a2b8; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Extend</button>',
                    f'/admin/audit/auditreport/{obj.id}/extend_expiry/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')

    def get_data_preview(self, obj):
        if obj.data:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;max-height:300px;overflow:auto;">{}</pre>', json.dumps(obj.data, indent=2)[:2000])
        return '-'
    get_data_preview.short_description = _('Data Preview')

    def get_report_summary(self, obj):
        age = (timezone.now() - obj.generated_at).days
        return format_html(
            '<table><tr><td>Age:</td><td style="font-weight: bold; padding-left:10px;">{} days</td></tr>'
            '<tr><td>Data size:</td><td style="font-weight: bold; padding-left:10px;">{} records</td></tr></table>',
            age,
            len(obj.data) if obj.data else 0
        )
    get_report_summary.short_description = _('Summary')

    def get_parameters_display(self, obj):
        if obj.parameters:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.parameters, indent=2))
        return '-'
    get_parameters_display.short_description = _('Parameters')

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
        response['Content-Disposition'] = 'attachment; filename=audit_reports.csv'
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
        count = queryset.count()
        self.message_user(request, f'Downloading {count} report(s)...')
    download_selected.short_description = _('Download selected')

    def extend_expiry(self, request, queryset):
        count = 0
        for obj in queryset:
            if obj.is_expired:
                obj.expires_at = timezone.now() + timezone.timedelta(days=30)
                obj.save(update_fields=['expires_at'])
                count += 1
        self.message_user(request, f'Extended expiry for {count} report(s) by 30 days.')
    extend_expiry.short_description = _('Extend expiry (30 days)')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('generated_by')

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:report_id>/download/', self.admin_site.admin_view(self.download_view), name='download'),
            path('<int:report_id>/extend_expiry/', self.admin_site.admin_view(self.extend_expiry_view), name='extend_expiry'),
        ]
        return custom_urls + urls

    def download_view(self, request, report_id):
        report = get_object_or_404(AuditReport, id=report_id)
        if report.is_expired:
            self.message_user(request, 'Report is expired.', messages.ERROR)
        else:
            report.download_count += 1
            report.save(update_fields=['download_count'])
            self.message_user(request, f'Report #{report.id} download initiated.')
        return HttpResponseRedirect(reverse('admin:audit_auditreport_changelist'))

    def extend_expiry_view(self, request, report_id):
        report = get_object_or_404(AuditReport, id=report_id)
        report.expires_at = timezone.now() + timezone.timedelta(days=30)
        report.save(update_fields=['expires_at'])
        self.message_user(request, f'Report #{report.id} expiry extended by 30 days.')
        return HttpResponseRedirect(reverse('admin:audit_auditreport_changelist'))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# AUDIT RETENTION POLICY ADMIN
# ============================================================================

@admin.register(AuditRetentionPolicy)
class AuditRetentionPolicyAdmin(ModelAdmin):
    """
    Admin configuration for AuditRetentionPolicy model.
    """
    list_display = (
        'id',
        'resource_type_badge',
        'retention_days_display',
        'is_active_badge',
        'updated_at_display',
        'actions_display',
    )

    list_filter = (
        'resource_type',
        'is_active',
        'updated_at',
    )

    search_fields = (
        'resource_type',
        'description',
    )

    ordering = ('resource_type',)

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'resource_type_display',
        'get_policy_summary',
    )

    fieldsets = (
        (_('Policy'), {
            'fields': (
                'id',
                'resource_type',
                'resource_type_display',
                'retention_days',
                'description',
                'is_active',
            )
        }),
        (_('Summary'), {
            'fields': (
                'get_policy_summary',
            ),
            'classes': ('collapse',),
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
        'activate_policies',
        'deactivate_policies',
        'enforce_policies',
        'export_as_csv',
        'bulk_update_retention',
    ]

    def resource_type_badge(self, obj):
        return obj.get_resource_type_display()
    resource_type_badge.short_description = _('Resource Type')
    resource_type_badge.admin_order_field = 'resource_type'

    def resource_type_display(self, obj):
        return obj.get_resource_type_display()
    resource_type_display.short_description = _('Resource Type')

    def retention_days_display(self, obj):
        return f"{obj.retention_days} days"
    retention_days_display.short_description = _('Retention')
    retention_days_display.admin_order_field = 'retention_days'

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color: #28a745; font-weight: bold;">✓ Active</span>')
        return format_html('<span style="color: #dc3545; font-weight: bold;">✗ Inactive</span>')
    is_active_badge.short_description = _('Active')
    is_active_badge.admin_order_field = 'is_active'

    def updated_at_display(self, obj):
        return obj.updated_at.strftime('%Y-%m-%d %H:%M')
    updated_at_display.short_description = _('Updated')
    updated_at_display.admin_order_field = 'updated_at'

    def actions_display(self, obj):
        if obj.is_active:
            return format_html(
                '<button onclick="location.href=\'{}\'" style="background: #28a745; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; font-size: 10px;">Enforce Now</button>',
                f'/admin/audit/auditretentionpolicy/{obj.id}/enforce/'
            )
        return '-'
    actions_display.short_description = _('Actions')

    def get_policy_summary(self, obj):
        # Estimate records to be deleted based on retention
        return format_html(
            '<table><tr><td>Estimated affected records:</td><td style="font-weight: bold; padding-left:10px;">Calculated on enforce</td></tr></table>'
        )
    get_policy_summary.short_description = _('Summary')

    def activate_policies(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'Activated {count} policy(s).')
    activate_policies.short_description = _('Activate selected policies')

    def deactivate_policies(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'Deactivated {count} policy(s).')
    deactivate_policies.short_description = _('Deactivate selected policies')

    def enforce_policies(self, request, queryset):
        total_deleted = 0
        for policy in queryset.filter(is_active=True):
            deleted = policy.enforce()
            total_deleted += deleted
        self.message_user(request, f'Enforced {queryset.count()} policy(s), deleted {total_deleted} records.')
    enforce_policies.short_description = _('Enforce selected policies')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=retention_policies.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Resource Type', 'Retention Days', 'Active', 'Description'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.get_resource_type_display(),
                obj.retention_days,
                'Yes' if obj.is_active else 'No',
                obj.description or '',
            ])
        self.message_user(request, f'Exported {queryset.count()} policy(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def bulk_update_retention(self, request, queryset):
        # Simple placeholder for bulk update
        self.message_user(request, 'Bulk update retention days: use change list edit directly.')
    bulk_update_retention.short_description = _('Bulk update retention (manual)')

    def get_queryset(self, request):
        return super().get_queryset(request)

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:policy_id>/enforce/', self.admin_site.admin_view(self.enforce_view), name='enforce'),
        ]
        return custom_urls + urls

    def enforce_view(self, request, policy_id):
        policy = get_object_or_404(AuditRetentionPolicy, id=policy_id)
        if not policy.is_active:
            self.message_user(request, 'Policy is not active.', messages.ERROR)
        else:
            deleted = policy.enforce()
            self.message_user(request, f'Policy enforced. Deleted {deleted} records.')
        return HttpResponseRedirect(reverse('admin:audit_auditretentionpolicy_changelist'))

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# SECURITY EVENT ADMIN
# ============================================================================

@admin.register(SecurityEvent)
class SecurityEventAdmin(ModelAdmin):
    """
    Admin configuration for SecurityEvent model.
    """
    list_display = (
        'id',
        'event_type_badge',
        'user_display',
        'severity_badge',
        'description_short',
        'timestamp_display',
        'ip_address_short',
        'actions_display',
    )

    list_filter = (
        'event_type',
        'severity',
        ('user', admin.RelatedOnlyFieldListFilter),
        'timestamp',
    )

    search_fields = (
        'id',
        'user__email',
        'description',
        'details',
        'ip_address',
    )

    ordering = ('-timestamp',)

    readonly_fields = (
        'id',
        'user',
        'event_type',
        'description',
        'severity',
        'details',
        'ip_address',
        'user_agent',
        'timestamp',
        'created_at',
        'updated_at',
        'get_details_display',
        'get_security_summary',
        'get_user_link',
    )

    fieldsets = (
        (_('Event'), {
            'fields': (
                'id',
                'event_type',
                'user',
                'description',
                'severity',
            )
        }),
        (_('Details'), {
            'fields': (
                'details',
                'get_details_display',
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
        (_('Links'), {
            'fields': (
                'get_user_link',
            ),
            'classes': ('collapse',),
        }),
        (_('Summary'), {
            'fields': (
                'get_security_summary',
            ),
            'classes': ('collapse',),
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
        'mark_as_critical',
        'mark_as_warning',
        'export_as_csv',
        'delete_selected',
        'block_ip',
    ]

    def event_type_badge(self, obj):
        return obj.get_event_type_display()
    event_type_badge.short_description = _('Event Type')
    event_type_badge.admin_order_field = 'event_type'

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def severity_badge(self, obj):
        colors = {
            'info': '#17a2b8',
            'warning': '#ffc107',
            'error': '#dc3545',
            'critical': '#8b0000',
        }
        color = colors.get(obj.severity, '#6c757d')
        text_color = 'black' if obj.severity == 'warning' else 'white'
        return format_html(
            '<span style="background: {}; color: {}; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            text_color,
            obj.get_severity_display()
        )
    severity_badge.short_description = _('Severity')
    severity_badge.admin_order_field = 'severity'

    def description_short(self, obj):
        return obj.description[:50] + ('...' if len(obj.description) > 50 else '')
    description_short.short_description = _('Description')
    description_short.admin_order_field = 'description'

    def timestamp_display(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')
    timestamp_display.admin_order_field = 'timestamp'

    def ip_address_short(self, obj):
        return obj.ip_address or '-'
    ip_address_short.short_description = _('IP')

    def actions_display(self, obj):
        actions = []
        if obj.severity != 'critical':
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #8b0000; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Mark Critical</button>',
                    f'/admin/audit/securityevent/{obj.id}/mark_critical/'
                )
            )
        if obj.ip_address:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #dc3545; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Block IP</button>',
                    f'/admin/audit/securityevent/{obj.id}/block_ip/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')

    def get_details_display(self, obj):
        if obj.details:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.details, indent=2))
        return '-'
    get_details_display.short_description = _('Details')

    def get_security_summary(self, obj):
        # Count similar events
        similar = SecurityEvent.objects.filter(event_type=obj.event_type).count()
        return format_html(
            '<table><tr><td>Similar events (same type):</td><td style="font-weight: bold; padding-left:10px;">{}</td></tr></table>',
            similar
        )
    get_security_summary.short_description = _('Summary')

    def get_user_link(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">View User Profile</a>', url)
    get_user_link.short_description = _('User Link')

    def mark_as_critical(self, request, queryset):
        count = queryset.update(severity='critical')
        self.message_user(request, f'Marked {count} security event(s) as critical.')
    mark_as_critical.short_description = _('Mark selected as critical')

    def mark_as_warning(self, request, queryset):
        count = queryset.update(severity='warning')
        self.message_user(request, f'Marked {count} security event(s) as warning.')
    mark_as_warning.short_description = _('Mark selected as warning')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=security_events.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Event Type', 'User', 'Severity', 'Description', 'Timestamp', 'IP'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.get_event_type_display(),
                obj.user.email,
                obj.get_severity_display(),
                obj.description,
                obj.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                obj.ip_address or '',
            ])
        self.message_user(request, f'Exported {queryset.count()} security event(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} security event(s).')
    delete_selected.short_description = _('Delete selected')

    def block_ip(self, request, queryset):
        count = 0
        for obj in queryset:
            if obj.ip_address:
                # Placeholder for IP blocking logic
                count += 1
        self.message_user(request, f'Blocked IP for {count} event(s).')
    block_ip.short_description = _('Block IP (placeholder)')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:event_id>/mark_critical/', self.admin_site.admin_view(self.mark_critical_view), name='mark_critical'),
            path('<int:event_id>/block_ip/', self.admin_site.admin_view(self.block_ip_view), name='block_ip'),
        ]
        return custom_urls + urls

    def mark_critical_view(self, request, event_id):
        event = get_object_or_404(SecurityEvent, id=event_id)
        event.severity = 'critical'
        event.save(update_fields=['severity'])
        self.message_user(request, f'Security event #{event.id} marked as critical.')
        return HttpResponseRedirect(reverse('admin:audit_securityevent_changelist'))

    def block_ip_view(self, request, event_id):
        event = get_object_or_404(SecurityEvent, id=event_id)
        # Placeholder for IP blocking
        self.message_user(request, f'IP {event.ip_address} blocked (placeholder).')
        return HttpResponseRedirect(reverse('admin:audit_securityevent_changelist'))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# USER ACTIVITY ADMIN
# ============================================================================

@admin.register(UserActivity)
class UserActivityAdmin(ModelAdmin):
    """
    Admin configuration for UserActivity model.
    """
    list_display = (
        'id',
        'user_display',
        'action_display',
        'resource_display',
        'resource_id_display',
        'timestamp_display',
        'ip_address_short',
    )

    list_filter = (
        'action',
        'resource',
        ('user', admin.RelatedOnlyFieldListFilter),
        'timestamp',
    )

    search_fields = (
        'user__email',
        'action',
        'resource',
        'resource_id',
        'details',
        'session_id',
        'ip_address',
    )

    ordering = ('-timestamp',)

    readonly_fields = (
        'id',
        'user',
        'action',
        'resource',
        'resource_id',
        'details',
        'session_id',
        'ip_address',
        'user_agent',
        'timestamp',
        'created_at',
        'updated_at',
        'get_details_display',
    )

    fieldsets = (
        (_('Activity'), {
            'fields': (
                'id',
                'user',
                'action',
                'resource',
                'resource_id',
            )
        }),
        (_('Details'), {
            'fields': (
                'details',
                'get_details_display',
            ),
            'classes': ('collapse',),
        }),
        (_('Session'), {
            'fields': (
                'session_id',
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
        'delete_selected',
        'analyze_user_activity',
    ]

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def action_display(self, obj):
        return obj.action
    action_display.short_description = _('Action')
    action_display.admin_order_field = 'action'

    def resource_display(self, obj):
        return obj.resource
    resource_display.short_description = _('Resource')
    resource_display.admin_order_field = 'resource'

    def resource_id_display(self, obj):
        return obj.resource_id if obj.resource_id else '-'
    resource_id_display.short_description = _('Resource ID')
    resource_id_display.admin_order_field = 'resource_id'

    def timestamp_display(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')
    timestamp_display.admin_order_field = 'timestamp'

    def ip_address_short(self, obj):
        return obj.ip_address or '-'
    ip_address_short.short_description = _('IP')

    def get_details_display(self, obj):
        if obj.details:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.details, indent=2))
        return '-'
    get_details_display.short_description = _('Details')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=user_activities.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'User', 'Action', 'Resource', 'Resource ID', 'Timestamp', 'IP'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.user.email,
                obj.action,
                obj.resource,
                obj.resource_id,
                obj.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                obj.ip_address or '',
            ])
        self.message_user(request, f'Exported {queryset.count()} activity record(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} activity record(s).')
    delete_selected.short_description = _('Delete selected')

    def analyze_user_activity(self, request, queryset):
        # Placeholder for analytics
        self.message_user(request, f'Analyzing {queryset.count()} activity records.')
    analyze_user_activity.short_description = _('Analyze selected')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# SYSTEM HEALTH ADMIN
# ============================================================================

@admin.register(SystemHealth)
class SystemHealthAdmin(ModelAdmin):
    """
    Admin configuration for SystemHealth model.
    """
    list_display = (
        'id',
        'component_display',
        'status_badge',
        'message_short',
        'checked_at_display',
        'actions_display',
    )

    list_filter = (
        'component',
        'status',
        'checked_at',
    )

    search_fields = (
        'component',
        'message',
        'details',
    )

    ordering = ('-checked_at',)

    readonly_fields = (
        'id',
        'component',
        'status',
        'message',
        'details',
        'checked_at',
        'created_at',
        'updated_at',
        'get_details_display',
        'get_health_summary',
    )

    fieldsets = (
        (_('Health Check'), {
            'fields': (
                'id',
                'component',
                'status',
                'message',
            )
        }),
        (_('Details'), {
            'fields': (
                'details',
                'get_details_display',
            ),
            'classes': ('collapse',),
        }),
        (_('Summary'), {
            'fields': (
                'get_health_summary',
            ),
            'classes': ('collapse',),
        }),
        (_('Timing'), {
            'fields': (
                'checked_at',
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'export_as_csv',
        'delete_selected',
        'clear_old_health',
        'run_check_now',
    ]

    def component_display(self, obj):
        return obj.component
    component_display.short_description = _('Component')
    component_display.admin_order_field = 'component'

    def status_badge(self, obj):
        colors = {
            'ok': '#28a745',
            'warning': '#ffc107',
            'error': '#dc3545',
            'degraded': '#fd7e14',
        }
        color = colors.get(obj.status, '#6c757d')
        text_color = 'black' if obj.status == 'warning' else 'white'
        return format_html(
            '<span style="background: {}; color: {}; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            text_color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def message_short(self, obj):
        return obj.message[:50] + ('...' if len(obj.message) > 50 else '')
    message_short.short_description = _('Message')
    message_short.admin_order_field = 'message'

    def checked_at_display(self, obj):
        return obj.checked_at.strftime('%Y-%m-%d %H:%M:%S')
    checked_at_display.short_description = _('Checked At')
    checked_at_display.admin_order_field = 'checked_at'

    def actions_display(self, obj):
        if obj.status in ['error', 'degraded']:
            return format_html(
                '<button onclick="location.href=\'{}\'" style="background: #17a2b8; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; font-size: 10px;">Re-check</button>',
                f'/admin/audit/systemhealth/{obj.id}/recheck/'
            )
        return '-'
    actions_display.short_description = _('Actions')

    def get_details_display(self, obj):
        if obj.details:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.details, indent=2))
        return '-'
    get_details_display.short_description = _('Details')

    def get_health_summary(self, obj):
        # Count total checks
        total = SystemHealth.objects.filter(component=obj.component).count()
        return format_html(
            '<table><tr><td>Total checks for component:</td><td style="font-weight: bold; padding-left:10px;">{}</td></tr></table>',
            total
        )
    get_health_summary.short_description = _('Summary')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=system_health.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Component', 'Status', 'Message', 'Checked At'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.component,
                obj.get_status_display(),
                obj.message or '',
                obj.checked_at.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        self.message_user(request, f'Exported {queryset.count()} health record(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} health record(s).')
    delete_selected.short_description = _('Delete selected')

    def clear_old_health(self, request, queryset):
        # Clear health records older than 30 days
        threshold = timezone.now() - timezone.timedelta(days=30)
        count = queryset.filter(checked_at__lt=threshold).delete()[0]
        self.message_user(request, f'Deleted {count} old health record(s).')
    clear_old_health.short_description = _('Clear old (30 days)')

    def run_check_now(self, request, queryset):
        # Placeholder to trigger recheck
        self.message_user(request, f'Recheck triggered for {queryset.count()} components.')
    run_check_now.short_description = _('Re-check selected')

    def get_queryset(self, request):
        return super().get_queryset(request)

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:health_id>/recheck/', self.admin_site.admin_view(self.recheck_view), name='recheck'),
        ]
        return custom_urls + urls

    def recheck_view(self, request, health_id):
        health = get_object_or_404(SystemHealth, id=health_id)
        # Trigger recheck (placeholder)
        self.message_user(request, f'Recheck triggered for {health.component}.')
        return HttpResponseRedirect(reverse('admin:audit_systemhealth_changelist'))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# PERFORMANCE METRIC ADMIN
# ============================================================================

@admin.register(PerformanceMetric)
class PerformanceMetricAdmin(ModelAdmin):
    """
    Admin configuration for PerformanceMetric model.
    """
    list_display = (
        'id',
        'metric_name_display',
        'value_display',
        'unit_display',
        'timestamp_display',
        'actions_display',
    )

    list_filter = (
        'metric_name',
        'unit',
        'timestamp',
    )

    search_fields = (
        'metric_name',
        'labels',
    )

    ordering = ('-timestamp',)

    readonly_fields = (
        'id',
        'metric_name',
        'value',
        'unit',
        'labels',
        'timestamp',
        'created_at',
        'updated_at',
        'get_labels_display',
        'get_metric_summary',
    )

    fieldsets = (
        (_('Metric'), {
            'fields': (
                'id',
                'metric_name',
                'value',
                'unit',
            )
        }),
        (_('Labels'), {
            'fields': (
                'labels',
                'get_labels_display',
            ),
            'classes': ('collapse',),
        }),
        (_('Summary'), {
            'fields': (
                'get_metric_summary',
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
        'aggregate_selected',
        'clear_old_metrics',
    ]

    def metric_name_display(self, obj):
        return obj.metric_name
    metric_name_display.short_description = _('Metric')
    metric_name_display.admin_order_field = 'metric_name'

    def value_display(self, obj):
        return obj.value
    value_display.short_description = _('Value')
    value_display.admin_order_field = 'value'

    def unit_display(self, obj):
        return obj.unit
    unit_display.short_description = _('Unit')
    unit_display.admin_order_field = 'unit'

    def timestamp_display(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')
    timestamp_display.admin_order_field = 'timestamp'

    def actions_display(self, obj):
        # Quick action to view anomaly for this metric
        anomalies = AnomalyDetection.objects.filter(metric_name=obj.metric_name, status='open').count()
        if anomalies > 0:
            return format_html(
                '<span style="color: #dc3545;">{} open anomalies</span>',
                anomalies
            )
        return '-'
    actions_display.short_description = _('Open Anomalies')

    def get_labels_display(self, obj):
        if obj.labels:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.labels, indent=2))
        return '-'
    get_labels_display.short_description = _('Labels')

    def get_metric_summary(self, obj):
        # Get aggregate for same metric
        from .models import PerformanceMetric
        stats = PerformanceMetric.get_aggregate(obj.metric_name, timezone.now() - timezone.timedelta(days=1), timezone.now())
        return format_html(
            '<table><tr><td>Avg (24h):</td><td style="padding-left:10px;">{}</td></tr>'
            '<tr><td>Max (24h):</td><td style="padding-left:10px;">{}</td></tr>'
            '<tr><td>Min (24h):</td><td style="padding-left:10px;">{}</td></tr>'
            '<tr><td>Count (24h):</td><td style="padding-left:10px;">{}</td></tr></table>',
            stats.get('avg', 'N/A'),
            stats.get('max', 'N/A'),
            stats.get('min', 'N/A'),
            stats.get('count', 'N/A')
        )
    get_metric_summary.short_description = _('24h Summary')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=performance_metrics.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Metric Name', 'Value', 'Unit', 'Timestamp', 'Labels'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.metric_name,
                float(obj.value),
                obj.unit,
                obj.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                json.dumps(obj.labels),
            ])
        self.message_user(request, f'Exported {queryset.count()} metric(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} metric(s).')
    delete_selected.short_description = _('Delete selected')

    def aggregate_selected(self, request, queryset):
        # Aggregate selected metrics
        if queryset.exists():
            avg = queryset.aggregate(avg=Avg('value'))['avg']
            self.message_user(request, f'Aggregated average value: {avg}')
    aggregate_selected.short_description = _('Aggregate selected')

    def clear_old_metrics(self, request, queryset):
        threshold = timezone.now() - timezone.timedelta(days=30)
        count = queryset.filter(timestamp__lt=threshold).delete()[0]
        self.message_user(request, f'Deleted {count} old metric(s).')
    clear_old_metrics.short_description = _('Clear old (30 days)')

    def get_queryset(self, request):
        return super().get_queryset(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================================
# ANOMALY DETECTION ADMIN
# ============================================================================

@admin.register(AnomalyDetection)
class AnomalyDetectionAdmin(ModelAdmin):
    """
    Admin configuration for AnomalyDetection model.
    """
    list_display = (
        'id',
        'anomaly_type_badge',
        'metric_name_display',
        'value_display',
        'severity_badge',
        'status_badge',
        'detected_at_display',
        'actions_display',
    )

    list_filter = (
        'anomaly_type',
        'severity',
        'status',
        'metric_name',
        'detected_at',
    )

    search_fields = (
        'metric_name',
        'description',
        'details',
    )

    ordering = ('-detected_at',)

    readonly_fields = (
        'id',
        'anomaly_type',
        'metric_name',
        'value',
        'baseline',
        'z_score',
        'severity',
        'description',
        'status',
        'detected_at',
        'resolved_at',
        'details',
        'created_at',
        'updated_at',
        'get_details_display',
        'get_anomaly_summary',
    )

    fieldsets = (
        (_('Anomaly'), {
            'fields': (
                'id',
                'anomaly_type',
                'metric_name',
                'value',
                'baseline',
                'z_score',
            )
        }),
        (_('Description'), {
            'fields': (
                'severity',
                'description',
                'status',
            )
        }),
        (_('Details'), {
            'fields': (
                'details',
                'get_details_display',
            ),
            'classes': ('collapse',),
        }),
        (_('Summary'), {
            'fields': (
                'get_anomaly_summary',
            ),
            'classes': ('collapse',),
        }),
        (_('Timing'), {
            'fields': (
                'detected_at',
                'resolved_at',
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'resolve_anomalies',
        'mark_false_positives',
        'export_as_csv',
        'delete_selected',
        'escalate_anomalies',
    ]

    def anomaly_type_badge(self, obj):
        return obj.get_anomaly_type_display()
    anomaly_type_badge.short_description = _('Type')
    anomaly_type_badge.admin_order_field = 'anomaly_type'

    def metric_name_display(self, obj):
        return obj.metric_name
    metric_name_display.short_description = _('Metric')
    metric_name_display.admin_order_field = 'metric_name'

    def value_display(self, obj):
        return obj.value
    value_display.short_description = _('Value')
    value_display.admin_order_field = 'value'

    def severity_badge(self, obj):
        colors = {
            'info': '#17a2b8',
            'warning': '#ffc107',
            'error': '#dc3545',
            'critical': '#8b0000',
        }
        color = colors.get(obj.severity, '#6c757d')
        text_color = 'black' if obj.severity == 'warning' else 'white'
        return format_html(
            '<span style="background: {}; color: {}; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            text_color,
            obj.get_severity_display()
        )
    severity_badge.short_description = _('Severity')
    severity_badge.admin_order_field = 'severity'

    def status_badge(self, obj):
        colors = {
            'open': '#ffc107',
            'investigating': '#17a2b8',
            'resolved': '#28a745',
            'false_positive': '#6c757d',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def detected_at_display(self, obj):
        return obj.detected_at.strftime('%Y-%m-%d %H:%M:%S')
    detected_at_display.short_description = _('Detected')
    detected_at_display.admin_order_field = 'detected_at'

    def actions_display(self, obj):
        actions = []
        if obj.status in ['open', 'investigating']:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #28a745; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">Resolve</button>',
                    f'/admin/audit/anomalydetection/{obj.id}/resolve/'
                )
            )
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #6c757d; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 10px;">False Positive</button>',
                    f'/admin/audit/anomalydetection/{obj.id}/false_positive/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')

    def get_details_display(self, obj):
        if obj.details:
            return format_html('<pre style="background:#f8f9fa;padding:10px;border-radius:4px;">{}</pre>', json.dumps(obj.details, indent=2))
        return '-'
    get_details_display.short_description = _('Details')

    def get_anomaly_summary(self, obj):
        # Count similar anomalies
        similar = AnomalyDetection.objects.filter(metric_name=obj.metric_name).count()
        return format_html(
            '<table><tr><td>Anomalies for same metric:</td><td style="font-weight: bold; padding-left:10px;">{}</td></tr></table>',
            similar
        )
    get_anomaly_summary.short_description = _('Summary')

    def resolve_anomalies(self, request, queryset):
        count = 0
        for obj in queryset.filter(status__in=['open', 'investigating']):
            obj.resolve()
            count += 1
        self.message_user(request, f'Resolved {count} anomaly(ies).')
    resolve_anomalies.short_description = _('Resolve selected anomalies')

    def mark_false_positives(self, request, queryset):
        count = 0
        for obj in queryset.filter(status__in=['open', 'investigating']):
            obj.mark_false_positive()
            count += 1
        self.message_user(request, f'Marked {count} anomaly(ies) as false positive.')
    mark_false_positives.short_description = _('Mark selected as false positive')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=anomalies.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Type', 'Metric', 'Value', 'Severity', 'Status', 'Detected At'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.get_anomaly_type_display(),
                obj.metric_name,
                float(obj.value),
                obj.get_severity_display(),
                obj.get_status_display(),
                obj.detected_at.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        self.message_user(request, f'Exported {queryset.count()} anomaly(ies).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} anomaly(ies).')
    delete_selected.short_description = _('Delete selected')

    def escalate_anomalies(self, request, queryset):
        count = queryset.filter(status__in=['open', 'investigating']).update(severity='critical')
        self.message_user(request, f'Escalated {count} anomaly(ies) to critical.')
    escalate_anomalies.short_description = _('Escalate selected')

    def get_queryset(self, request):
        return super().get_queryset(request)

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:anomaly_id>/resolve/', self.admin_site.admin_view(self.resolve_view), name='resolve'),
            path('<int:anomaly_id>/false_positive/', self.admin_site.admin_view(self.false_positive_view), name='false_positive'),
        ]
        return custom_urls + urls

    def resolve_view(self, request, anomaly_id):
        anomaly = get_object_or_404(AnomalyDetection, id=anomaly_id)
        anomaly.resolve()
        self.message_user(request, f'Anomaly #{anomaly.id} resolved.')
        return HttpResponseRedirect(reverse('admin:audit_anomalydetection_changelist'))

    def false_positive_view(self, request, anomaly_id):
        anomaly = get_object_or_404(AnomalyDetection, id=anomaly_id)
        anomaly.mark_false_positive()
        self.message_user(request, f'Anomaly #{anomaly.id} marked as false positive.')
        return HttpResponseRedirect(reverse('admin:audit_anomalydetection_changelist'))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser