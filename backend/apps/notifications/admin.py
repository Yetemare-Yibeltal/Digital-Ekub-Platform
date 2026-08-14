"""
Admin configuration for the notifications app.

This module provides comprehensive Django admin interfaces for all notification models:
- Notification: Main notification entity with full CRUD operations
- NotificationTemplate: Reusable notification templates
- NotificationPreference: User notification preferences
- NotificationChannel: Notification delivery channel configuration
- NotificationDelivery: Delivery tracking records
- NotificationEvent: Event-driven notification triggers
- NotificationSchedule: Scheduled notification management
- NotificationDigest: Notification digest records
- NotificationAudit: Audit trail for notification actions

All admin classes include custom list displays, filters, search fields,
inline relationships, and custom actions for efficient notification management.
"""

from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.urls import reverse
from django.utils.html import format_html
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.db import transaction
from decimal import Decimal
import csv
import json
from io import StringIO

from apps.users.models import User
from apps.groups.models import Group
from apps.common.constants import NotificationType, NotificationChannel, NotificationPriority
from apps.common.utils import format_currency, log_audit_event

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


# ============================================================================
# NOTIFICATION ADMIN
# ============================================================================

@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    """
    Admin configuration for Notification model with comprehensive features.
    """
    list_display = (
        'id',
        'user_display',
        'group_display',
        'notification_type_badge',
        'title_display',
        'priority_badge',
        'status_badge',
        'sent_at_display',
        'created_at_display',
        'actions_display',
    )

    list_filter = (
        'notification_type',
        'priority',
        'is_read',
        ('user', admin.RelatedOnlyFieldListFilter),
        ('group', admin.RelatedOnlyFieldListFilter),
        'created_at',
        'sent_at',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    search_fields = (
        'id',
        'title',
        'message',
        'user__email',
        'user__first_name',
        'user__last_name',
        'group__name',
        'object_type',
        'object_id',
    )

    ordering = ('-created_at',)

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'deleted_at',
        'sent_at',
        'delivered_at',
        'created_by',
        'get_deliveries_link',
        'get_audit_trail_link',
    )

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'id',
                'user',
                'group',
                'notification_type',
                'title',
                'message',
            )
        }),

        (_('Priority & Status'), {
            'fields': (
                'priority',
                'is_read',
                'read_at',
                'expires_at',
            )
        }),

        (_('Object Reference'), {
            'fields': (
                'object_id',
                'object_type',
            ),
            'classes': ('collapse',),
        }),

        (_('Metadata'), {
            'fields': (
                'metadata',
                'created_by',
                'sent_at',
                'delivered_at',
                'deleted_at',
            ),
            'classes': ('collapse',),
        }),

        (_('Admin Links'), {
            'fields': (
                'get_deliveries_link',
                'get_audit_trail_link',
            ),
            'classes': ('collapse',),
        }),

        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    inlines = []

    actions = [
        'mark_as_read',
        'mark_as_unread',
        'delete_selected',
        'export_as_csv',
        'resend_notifications',
    ]

    list_per_page = 50

    # --------------------------------------------------------------------------
    # CUSTOM DISPLAY METHODS
    # --------------------------------------------------------------------------

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

    def notification_type_badge(self, obj):
        colors = {
            NotificationType.INFO: 'blue',
            NotificationType.SUCCESS: 'green',
            NotificationType.WARNING: 'orange',
            NotificationType.ERROR: 'red',
            NotificationType.REMINDER: 'purple',
            NotificationType.ALERT: 'darkred',
            NotificationType.PROMOTION: 'pink',
            NotificationType.SYSTEM: 'gray',
            NotificationType.TRANSACTION: 'teal',
            NotificationType.GROUP: 'indigo',
            NotificationType.CONTRIBUTION: 'cyan',
            NotificationType.PAYMENT: 'green',
            NotificationType.PAYOUT: 'blue',
            NotificationType.VERIFICATION: 'purple',
            NotificationType.SECURITY: 'darkred',
        }
        color = colors.get(obj.notification_type, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_notification_type_display()
        )
    notification_type_badge.short_description = _('Type')
    notification_type_badge.admin_order_field = 'notification_type'

    def title_display(self, obj):
        title = obj.title or obj.message[:50]
        if len(title) > 50:
            title = title[:50] + '...'
        return title
    title_display.short_description = _('Title')
    title_display.admin_order_field = 'title'

    def priority_badge(self, obj):
        colors = {
            NotificationPriority.LOW: 'gray',
            NotificationPriority.MEDIUM: 'blue',
            NotificationPriority.HIGH: 'orange',
            NotificationPriority.URGENT: 'red',
        }
        color = colors.get(obj.priority, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_priority_display()
        )
    priority_badge.short_description = _('Priority')
    priority_badge.admin_order_field = 'priority'

    def status_badge(self, obj):
        if obj.is_deleted:
            return format_html(
                '<span style="color: gray; font-weight: bold;">Deleted</span>'
            )
        if obj.is_read:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Read</span>'
            )
        if obj.is_expired:
            return format_html(
                '<span style="color: orange; font-weight: bold;">⚠ Expired</span>'
            )
        return format_html(
            '<span style="color: blue; font-weight: bold;">● Unread</span>'
        )
    status_badge.short_description = _('Status')

    def sent_at_display(self, obj):
        if obj.sent_at:
            return obj.sent_at.strftime('%Y-%m-%d %H:%M')
        return '-'
    sent_at_display.short_description = _('Sent')
    sent_at_display.admin_order_field = 'sent_at'

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def actions_display(self, obj):
        actions = []
        if not obj.is_read and not obj.is_deleted:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #28a745; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 1px; font-size: 11px;">Mark Read</button>',
                    f'/admin/notifications/notification/{obj.id}/mark_read/'
                )
            )
        if obj.is_read and not obj.is_deleted:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #ffc107; color: black; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 1px; font-size: 11px;">Mark Unread</button>',
                    f'/admin/notifications/notification/{obj.id}/mark_unread/'
                )
            )
        if not obj.is_deleted:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #dc3545; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 1px; font-size: 11px;">Delete</button>',
                    f'/admin/notifications/notification/{obj.id}/soft_delete/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')
    actions_display.allow_tags = True

    def get_deliveries_link(self, obj):
        url = reverse('admin:notifications_notificationdelivery_changelist') + f'?notification__id__exact={obj.id}'
        count = obj.deliveries.count()
        return format_html('<a href="{}">View Deliveries ({})</a>', url, count)
    get_deliveries_link.short_description = _('Deliveries')

    def get_audit_trail_link(self, obj):
        url = reverse('admin:notifications_notificationaudit_changelist') + f'?notification__id__exact={obj.id}'
        count = obj.audits.count()
        return format_html('<a href="{}">View Audit Trail ({})</a>', url, count)
    get_audit_trail_link.short_description = _('Audit Trail')

    # --------------------------------------------------------------------------
    # CUSTOM ACTIONS
    # --------------------------------------------------------------------------

    def mark_as_read(self, request, queryset):
        count = 0
        for obj in queryset.filter(is_read=False):
            obj.mark_as_read()
            count += 1
        self.message_user(request, f'Marked {count} notification(s) as read.')
    mark_as_read.short_description = _('Mark selected as read')

    def mark_as_unread(self, request, queryset):
        count = 0
        for obj in queryset.filter(is_read=True):
            obj.mark_as_unread()
            count += 1
        self.message_user(request, f'Marked {count} notification(s) as unread.')
    mark_as_unread.short_description = _('Mark selected as unread')

    def delete_selected(self, request, queryset):
        count = 0
        for obj in queryset:
            if not obj.is_deleted:
                obj.deleted_at = timezone.now()
                obj.save(update_fields=['deleted_at'])
                count += 1
        self.message_user(request, f'Soft deleted {count} notification(s).')
    delete_selected.short_description = _('Soft delete selected')

    def export_as_csv(self, request, queryset):
        meta = self.model._meta
        field_names = ['id', 'user__email', 'group__name', 'notification_type', 'title', 'is_read', 'created_at']
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename={meta.verbose_name_plural}.csv'
        writer = csv.writer(response)
        writer.writerow(field_names)
        for obj in queryset:
            row = [
                obj.id,
                obj.user.email,
                obj.group.name if obj.group else '',
                obj.get_notification_type_display(),
                obj.title or obj.message[:50],
                'Yes' if obj.is_read else 'No',
                obj.created_at.strftime('%Y-%m-%d %H:%M'),
            ]
            writer.writerow(row)
        self.message_user(request, f'Exported {queryset.count()} notification(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def resend_notifications(self, request, queryset):
        count = 0
        from .tasks import send_notification
        for obj in queryset.filter(sent_at__isnull=False):
            notification_data = {
                'id': obj.id,
                'user_id': obj.user.id,
                'email': obj.user.email,
                'phone': obj.user.phone,
                'message': obj.message,
                'title': obj.title or '',
                'notification_type': obj.notification_type,
                'group_id': obj.group.id if obj.group else None,
                'object_id': obj.object_id,
                'object_type': obj.object_type,
                'priority': obj.priority,
                'send_email': True,
                'send_sms': False,
                'send_push': True,
                'send_in_app': True,
            }
            send_notification.delay(notification_data)
            count += 1
        self.message_user(request, f'Queued {count} notification(s) for resend.')
    resend_notifications.short_description = _('Resend selected notifications')

    # --------------------------------------------------------------------------
    # CUSTOM ADMIN VIEWS
    # --------------------------------------------------------------------------

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:notification_id>/mark_read/', self.admin_site.admin_view(self.mark_read_view), name='mark_read'),
            path('<int:notification_id>/mark_unread/', self.admin_site.admin_view(self.mark_unread_view), name='mark_unread'),
            path('<int:notification_id>/soft_delete/', self.admin_site.admin_view(self.soft_delete_view), name='soft_delete'),
        ]
        return custom_urls + urls

    def mark_read_view(self, request, notification_id):
        notification = get_object_or_404(Notification, id=notification_id)
        notification.mark_as_read()
        self.message_user(request, f'Notification #{notification.id} marked as read.')
        return HttpResponseRedirect(reverse('admin:notifications_notification_changelist'))

    def mark_unread_view(self, request, notification_id):
        notification = get_object_or_404(Notification, id=notification_id)
        notification.mark_as_unread()
        self.message_user(request, f'Notification #{notification.id} marked as unread.')
        return HttpResponseRedirect(reverse('admin:notifications_notification_changelist'))

    def soft_delete_view(self, request, notification_id):
        notification = get_object_or_404(Notification, id=notification_id)
        notification.deleted_at = timezone.now()
        notification.save(update_fields=['deleted_at'])
        self.message_user(request, f'Notification #{notification.id} soft deleted.')
        return HttpResponseRedirect(reverse('admin:notifications_notification_changelist'))

    # --------------------------------------------------------------------------
    # OVERRIDEN METHODS
    # --------------------------------------------------------------------------

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'group', 'created_by')

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.save()
        log_audit_event(
            user_id=request.user.id,
            action='notification_' + ('created' if not change else 'updated') + '_via_admin',
            resource='notification',
            resource_id=obj.id,
        )


# ============================================================================
# NOTIFICATION TEMPLATE ADMIN
# ============================================================================

@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(ModelAdmin):
    """
    Admin configuration for NotificationTemplate model.
    """
    list_display = (
        'id',
        'name_display',
        'notification_type_badge',
        'channels_display',
        'is_active_badge',
        'created_at_display',
        'actions_display',
    )

    list_filter = (
        'notification_type',
        'is_active',
        'created_at',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    search_fields = (
        'name',
        'description',
        'subject',
        'body_template',
    )

    ordering = ('name',)

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'deleted_at',
        'preview',
    )

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'id',
                'name',
                'description',
                'notification_type',
                'is_active',
            )
        }),
        (_('Template Content'), {
            'fields': (
                'subject',
                'body_template',
                'html_template',
            )
        }),
        (_('Settings'), {
            'fields': (
                'channels',
                'preview',
            ),
            'classes': ('collapse',),
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'activate_templates',
        'deactivate_templates',
        'export_as_csv',
        'duplicate_templates',
    ]

    def name_display(self, obj):
        return format_html(
            '<code style="background: #f8f9fa; padding: 2px 6px; border-radius: 4px;">{}</code>',
            obj.name
        )
    name_display.short_description = _('Name')
    name_display.admin_order_field = 'name'

    def notification_type_badge(self, obj):
        colors = {
            NotificationType.INFO: 'blue',
            NotificationType.SUCCESS: 'green',
            NotificationType.WARNING: 'orange',
            NotificationType.ERROR: 'red',
            NotificationType.REMINDER: 'purple',
            NotificationType.ALERT: 'darkred',
            NotificationType.PROMOTION: 'pink',
            NotificationType.SYSTEM: 'gray',
            NotificationType.TRANSACTION: 'teal',
            NotificationType.GROUP: 'indigo',
            NotificationType.CONTRIBUTION: 'cyan',
            NotificationType.PAYMENT: 'green',
            NotificationType.PAYOUT: 'blue',
            NotificationType.VERIFICATION: 'purple',
            NotificationType.SECURITY: 'darkred',
        }
        color = colors.get(obj.notification_type, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_notification_type_display()
        )
    notification_type_badge.short_description = _('Type')
    notification_type_badge.admin_order_field = 'notification_type'

    def channels_display(self, obj):
        channels = obj.channels.split(',') if obj.channels else []
        colors = {'email': 'blue', 'sms': 'orange', 'push': 'green', 'in_app': 'purple', 'webhook': 'red'}
        html = []
        for channel in channels:
            color = colors.get(channel.strip(), 'gray')
            html.append(
                format_html(
                    '<span style="background: {}; color: white; padding: 2px 6px; border-radius: 12px; font-size: 10px; margin: 1px;">{}</span>',
                    color,
                    channel.strip()
                )
            )
        return format_html('&nbsp;'.join(html))
    channels_display.short_description = _('Channels')

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Active</span>'
            )
        return format_html(
            '<span style="color: red; font-weight: bold;">✗ Inactive</span>'
        )
    is_active_badge.short_description = _('Active')
    is_active_badge.admin_order_field = 'is_active'

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def actions_display(self, obj):
        actions = []
        if obj.is_active:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #dc3545; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Deactivate</button>',
                    f'/admin/notifications/notificationtemplate/{obj.id}/toggle_active/'
                )
            )
        else:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #28a745; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Activate</button>',
                    f'/admin/notifications/notificationtemplate/{obj.id}/toggle_active/'
                )
            )
        actions.append(
            format_html(
                '<button onclick="location.href=\'{}\'" style="background: #17a2b8; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Duplicate</button>',
                f'/admin/notifications/notificationtemplate/{obj.id}/duplicate/'
            )
        )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')

    def preview(self, obj):
        """Preview the template with sample data."""
        context = {
            'user': {'full_name': 'John Doe', 'email': 'john@example.com'},
            'group': {'name': 'Sample Group'},
            'amount': '1,000.00 ETB',
            'date': timezone.now().strftime('%Y-%m-%d'),
            'app_name': 'Ekub Platform',
        }
        try:
            body = obj.render_body(context)
            return format_html(
                '<div style="background: #f8f9fa; padding: 15px; border-radius: 4px; border: 1px solid #dee2e6; max-height: 300px; overflow: auto; white-space: pre-wrap;">{}</div>',
                body
            )
        except Exception as e:
            return format_html('<span style="color: red;">Error rendering: {}</span>', str(e))
    preview.short_description = _('Preview')

    def activate_templates(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'Activated {count} template(s).')
    activate_templates.short_description = _('Activate selected templates')

    def deactivate_templates(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'Deactivated {count} template(s).')
    deactivate_templates.short_description = _('Deactivate selected templates')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=templates.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Name', 'Type', 'Active', 'Channels', 'Created'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.name,
                obj.get_notification_type_display(),
                'Yes' if obj.is_active else 'No',
                obj.channels,
                obj.created_at.strftime('%Y-%m-%d %H:%M'),
            ])
        self.message_user(request, f'Exported {queryset.count()} template(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def duplicate_templates(self, request, queryset):
        count = 0
        for obj in queryset:
            new_obj = obj
            new_obj.pk = None
            new_obj.name = f"{obj.name}_copy_{count+1}"
            new_obj.created_at = timezone.now()
            new_obj.updated_at = timezone.now()
            new_obj.save()
            count += 1
        self.message_user(request, f'Duplicated {count} template(s).')
    duplicate_templates.short_description = _('Duplicate selected templates')

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:template_id>/toggle_active/', self.admin_site.admin_view(self.toggle_active_view), name='toggle_active'),
            path('<int:template_id>/duplicate/', self.admin_site.admin_view(self.duplicate_view), name='duplicate'),
        ]
        return custom_urls + urls

    def toggle_active_view(self, request, template_id):
        template = get_object_or_404(NotificationTemplate, id=template_id)
        template.is_active = not template.is_active
        template.save()
        self.message_user(request, f'Template "{template.name}" {"activated" if template.is_active else "deactivated"}.')
        return HttpResponseRedirect(reverse('admin:notifications_notificationtemplate_changelist'))

    def duplicate_view(self, request, template_id):
        template = get_object_or_404(NotificationTemplate, id=template_id)
        new_template = template
        new_template.pk = None
        new_template.name = f"{template.name}_copy"
        new_template.created_at = timezone.now()
        new_template.updated_at = timezone.now()
        new_template.save()
        self.message_user(request, f'Template "{template.name}" duplicated as "{new_template.name}".')
        return HttpResponseRedirect(reverse('admin:notifications_notificationtemplate_changelist'))


# ============================================================================
# NOTIFICATION PREFERENCE ADMIN
# ============================================================================

@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(ModelAdmin):
    """
    Admin configuration for NotificationPreference model.
    """
    list_display = (
        'id',
        'user_display',
        'email_enabled_display',
        'sms_enabled_display',
        'push_enabled_display',
        'in_app_enabled_display',
        'daily_digest_display',
        'updated_at_display',
    )

    list_filter = (
        'email_enabled',
        'sms_enabled',
        'push_enabled',
        'in_app_enabled',
        'daily_digest',
        'weekly_digest',
        ('user', admin.RelatedOnlyFieldListFilter),
        'updated_at',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    search_fields = (
        'user__email',
        'user__first_name',
        'user__last_name',
        'categories',
    )

    ordering = ('-updated_at',)

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'deleted_at',
    )

    fieldsets = (
        (_('User'), {
            'fields': ('user',)
        }),
        (_('Channel Preferences'), {
            'fields': (
                'email_enabled',
                'sms_enabled',
                'push_enabled',
                'in_app_enabled',
            )
        }),
        (_('Digest Preferences'), {
            'fields': (
                'daily_digest',
                'weekly_digest',
            )
        }),
        (_('Advanced'), {
            'fields': (
                'categories',
                'quiet_hours_start',
                'quiet_hours_end',
                'timezone',
            ),
            'classes': ('collapse',),
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'enable_email',
        'disable_email',
        'enable_sms',
        'disable_sms',
        'enable_push',
        'disable_push',
        'enable_daily_digest',
        'disable_daily_digest',
    ]

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def email_enabled_display(self, obj):
        return '✓' if obj.email_enabled else '✗'
    email_enabled_display.short_description = _('Email')

    def sms_enabled_display(self, obj):
        return '✓' if obj.sms_enabled else '✗'
    sms_enabled_display.short_description = _('SMS')

    def push_enabled_display(self, obj):
        return '✓' if obj.push_enabled else '✗'
    push_enabled_display.short_description = _('Push')

    def in_app_enabled_display(self, obj):
        return '✓' if obj.in_app_enabled else '✗'
    in_app_enabled_display.short_description = _('In-App')

    def daily_digest_display(self, obj):
        return '✓' if obj.daily_digest else '✗'
    daily_digest_display.short_description = _('Daily Digest')

    def updated_at_display(self, obj):
        return obj.updated_at.strftime('%Y-%m-%d %H:%M')
    updated_at_display.short_description = _('Updated')
    updated_at_display.admin_order_field = 'updated_at'

    def enable_email(self, request, queryset):
        count = queryset.update(email_enabled=True)
        self.message_user(request, f'Enabled email for {count} user(s).')
    enable_email.short_description = _('Enable email')

    def disable_email(self, request, queryset):
        count = queryset.update(email_enabled=False)
        self.message_user(request, f'Disabled email for {count} user(s).')
    disable_email.short_description = _('Disable email')

    def enable_sms(self, request, queryset):
        count = queryset.update(sms_enabled=True)
        self.message_user(request, f'Enabled SMS for {count} user(s).')
    enable_sms.short_description = _('Enable SMS')

    def disable_sms(self, request, queryset):
        count = queryset.update(sms_enabled=False)
        self.message_user(request, f'Disabled SMS for {count} user(s).')
    disable_sms.short_description = _('Disable SMS')

    def enable_push(self, request, queryset):
        count = queryset.update(push_enabled=True)
        self.message_user(request, f'Enabled push for {count} user(s).')
    enable_push.short_description = _('Enable push')

    def disable_push(self, request, queryset):
        count = queryset.update(push_enabled=False)
        self.message_user(request, f'Disabled push for {count} user(s).')
    disable_push.short_description = _('Disable push')

    def enable_daily_digest(self, request, queryset):
        count = queryset.update(daily_digest=True)
        self.message_user(request, f'Enabled daily digest for {count} user(s).')
    enable_daily_digest.short_description = _('Enable daily digest')

    def disable_daily_digest(self, request, queryset):
        count = queryset.update(daily_digest=False)
        self.message_user(request, f'Disabled daily digest for {count} user(s).')
    disable_daily_digest.short_description = _('Disable daily digest')


# ============================================================================
# NOTIFICATION CHANNEL ADMIN
# ============================================================================

@admin.register(NotificationChannel)
class NotificationChannelAdmin(ModelAdmin):
    """
    Admin configuration for NotificationChannel model.
    """
    list_display = (
        'id',
        'name_display',
        'is_active_badge',
        'provider',
        'priority',
        'created_at_display',
    )

    list_filter = (
        'is_active',
        'name',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    search_fields = (
        'name',
        'provider',
        'configuration',
    )

    ordering = ('priority', 'name')

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'deleted_at',
    )

    fieldsets = (
        (_('Channel'), {
            'fields': (
                'name',
                'is_active',
                'provider',
            )
        }),
        (_('Configuration'), {
            'fields': (
                'configuration',
                'priority',
            ),
            'classes': ('collapse',),
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'activate_channels',
        'deactivate_channels',
    ]

    def name_display(self, obj):
        return obj.get_name_display()
    name_display.short_description = _('Name')
    name_display.admin_order_field = 'name'

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color: green; font-weight: bold;">✓ Active</span>')
        return format_html('<span style="color: red; font-weight: bold;">✗ Inactive</span>')
    is_active_badge.short_description = _('Active')
    is_active_badge.admin_order_field = 'is_active'

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def activate_channels(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'Activated {count} channel(s).')
    activate_channels.short_description = _('Activate selected channels')

    def deactivate_channels(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'Deactivated {count} channel(s).')
    deactivate_channels.short_description = _('Deactivate selected channels')


# ============================================================================
# NOTIFICATION DELIVERY ADMIN
# ============================================================================

@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(ModelAdmin):
    """
    Admin configuration for NotificationDelivery model (read-only).
    """
    list_display = (
        'id',
        'notification_display',
        'user_display',
        'channel_badge',
        'status_badge',
        'attempt_count_display',
        'sent_at_display',
        'created_at_display',
    )

    list_filter = (
        'channel',
        'status',
        ('notification', admin.RelatedOnlyFieldListFilter),
        'sent_at',
        'created_at',
    )

    search_fields = (
        'notification__id',
        'user__email',
        'channel',
        'error_message',
        'response_data',
    )

    ordering = ('-created_at',)

    readonly_fields = (
        'id',
        'notification',
        'user',
        'channel',
        'status',
        'attempt_count',
        'sent_at',
        'delivered_at',
        'error_message',
        'response_data',
        'created_at',
        'updated_at',
    )

    fieldsets = (
        (_('Delivery'), {
            'fields': (
                'notification',
                'user',
                'channel',
                'status',
                'attempt_count',
            )
        }),
        (_('Timing'), {
            'fields': (
                'sent_at',
                'delivered_at',
            )
        }),
        (_('Details'), {
            'fields': (
                'error_message',
                'response_data',
            ),
            'classes': ('collapse',),
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'retry_deliveries',
    ]

    def notification_display(self, obj):
        url = reverse('admin:notifications_notification_change', args=[obj.notification.id])
        return format_html('<a href="{}">#{}</a>', url, obj.notification.id)
    notification_display.short_description = _('Notification')
    notification_display.admin_order_field = 'notification__id'

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def channel_badge(self, obj):
        colors = {
            'email': 'blue',
            'sms': 'orange',
            'push': 'green',
            'in_app': 'purple',
            'webhook': 'red',
        }
        color = colors.get(obj.channel, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_channel_display()
        )
    channel_badge.short_description = _('Channel')
    channel_badge.admin_order_field = 'channel'

    def status_badge(self, obj):
        colors = {
            'pending': 'orange',
            'sent': 'blue',
            'delivered': 'green',
            'failed': 'red',
            'bounced': 'darkred',
            'blocked': 'gray',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def attempt_count_display(self, obj):
        if obj.attempt_count == 0:
            return '0'
        color = 'green' if obj.attempt_count < 3 else 'orange'
        return format_html('<span style="color: {};">{}</span>', color, obj.attempt_count)
    attempt_count_display.short_description = _('Attempts')
    attempt_count_display.admin_order_field = 'attempt_count'

    def sent_at_display(self, obj):
        if obj.sent_at:
            return obj.sent_at.strftime('%Y-%m-%d %H:%M')
        return '-'
    sent_at_display.short_description = _('Sent')
    sent_at_display.admin_order_field = 'sent_at'

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def retry_deliveries(self, request, queryset):
        count = 0
        for obj in queryset.filter(status='failed', attempt_count__lt=3):
            if obj.retry():
                count += 1
        self.message_user(request, f'Retried {count} delivery(s).')
    retry_deliveries.short_description = _('Retry selected deliveries')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ============================================================================
# NOTIFICATION EVENT ADMIN
# ============================================================================

@admin.register(NotificationEvent)
class NotificationEventAdmin(ModelAdmin):
    """
    Admin configuration for NotificationEvent model.
    """
    list_display = (
        'id',
        'event_type_display',
        'user_display',
        'group_display',
        'processed_badge',
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
        'event_type',
        'user__email',
        'group__name',
        'data',
        'error_message',
    )

    ordering = ('-created_at',)

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'processed_at',
        'error_message',
    )

    fieldsets = (
        (_('Event'), {
            'fields': (
                'event_type',
                'user',
                'group',
                'data',
            )
        }),
        (_('Processing'), {
            'fields': (
                'processed',
                'processed_at',
                'error_message',
            )
        }),
        (_('Timestamps'), {
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
    ]

    def event_type_display(self, obj):
        return format_html(
            '<code style="background: #f8f9fa; padding: 2px 6px; border-radius: 4px;">{}</code>',
            obj.event_type
        )
    event_type_display.short_description = _('Event Type')
    event_type_display.admin_order_field = 'event_type'

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
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Processed</span>'
            )
        return format_html(
                '<span style="color: orange; font-weight: bold;">⏳ Pending</span>'
            )
    processed_badge.short_description = _('Processed')
    processed_badge.admin_order_field = 'processed'

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
                    f'/admin/notifications/notificationevent/{obj.id}/process/'
                )
            )
        if obj.error_message:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #17a2b8; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Retry</button>',
                    f'/admin/notifications/notificationevent/{obj.id}/retry/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')

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

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:event_id>/process/', self.admin_site.admin_view(self.process_view), name='process'),
            path('<int:event_id>/retry/', self.admin_site.admin_view(self.retry_view), name='retry'),
        ]
        return custom_urls + urls

    def process_view(self, request, event_id):
        event = get_object_or_404(NotificationEvent, id=event_id)
        event.process()
        self.message_user(request, f'Event #{event.id} processed.')
        return HttpResponseRedirect(reverse('admin:notifications_notificationevent_changelist'))

    def retry_view(self, request, event_id):
        event = get_object_or_404(NotificationEvent, id=event_id)
        event.retry()
        self.message_user(request, f'Event #{event.id} retried.')
        return HttpResponseRedirect(reverse('admin:notifications_notificationevent_changelist'))


# ============================================================================
# NOTIFICATION SCHEDULE ADMIN
# ============================================================================

@admin.register(NotificationSchedule)
class NotificationScheduleAdmin(ModelAdmin):
    """
    Admin configuration for NotificationSchedule model.
    """
    list_display = (
        'id',
        'notification_display',
        'user_display',
        'scheduled_at_display',
        'status_badge',
        'retry_count_display',
        'created_at_display',
        'actions_display',
    )

    list_filter = (
        'status',
        ('notification', admin.RelatedOnlyFieldListFilter),
        'scheduled_at',
        'created_at',
    )

    search_fields = (
        'notification__id',
        'notification__user__email',
        'error_message',
    )

    ordering = ('scheduled_at',)

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'executed_at',
        'retry_count',
        'error_message',
    )

    fieldsets = (
        (_('Schedule'), {
            'fields': (
                'notification',
                'scheduled_at',
                'status',
            )
        }),
        (_('Execution'), {
            'fields': (
                'executed_at',
                'retry_count',
                'error_message',
            ),
            'classes': ('collapse',),
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'execute_schedules',
        'cancel_schedules',
    ]

    def notification_display(self, obj):
        url = reverse('admin:notifications_notification_change', args=[obj.notification.id])
        title = obj.notification.title or obj.notification.message[:30]
        return format_html('<a href="{}">#{}</a>', url, obj.notification.id)
    notification_display.short_description = _('Notification')
    notification_display.admin_order_field = 'notification__id'

    def user_display(self, obj):
        user = obj.notification.user
        url = reverse('admin:users_user_change', args=[user.id])
        return format_html('<a href="{}">{}</a>', url, user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'notification__user__email'

    def scheduled_at_display(self, obj):
        return obj.scheduled_at.strftime('%Y-%m-%d %H:%M')
    scheduled_at_display.short_description = _('Scheduled')
    scheduled_at_display.admin_order_field = 'scheduled_at'

    def status_badge(self, obj):
        colors = {'pending': 'orange', 'sent': 'green', 'failed': 'red', 'cancelled': 'gray'}
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def retry_count_display(self, obj):
        if obj.retry_count == 0:
            return '0'
        color = 'green' if obj.retry_count < 3 else 'orange'
        return format_html('<span style="color: {};">{}</span>', color, obj.retry_count)
    retry_count_display.short_description = _('Retries')
    retry_count_display.admin_order_field = 'retry_count'

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def actions_display(self, obj):
        actions = []
        if obj.status == 'pending':
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #28a745; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Execute</button>',
                    f'/admin/notifications/notificationschedule/{obj.id}/execute/'
                )
            )
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #dc3545; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Cancel</button>',
                    f'/admin/notifications/notificationschedule/{obj.id}/cancel/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')

    def execute_schedules(self, request, queryset):
        count = 0
        for obj in queryset.filter(status='pending'):
            obj.execute()
            count += 1
        self.message_user(request, f'Executed {count} schedule(s).')
    execute_schedules.short_description = _('Execute selected schedules')

    def cancel_schedules(self, request, queryset):
        count = 0
        for obj in queryset.filter(status='pending'):
            obj.cancel()
            count += 1
        self.message_user(request, f'Cancelled {count} schedule(s).')
    cancel_schedules.short_description = _('Cancel selected schedules')

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:schedule_id>/execute/', self.admin_site.admin_view(self.execute_view), name='execute'),
            path('<int:schedule_id>/cancel/', self.admin_site.admin_view(self.cancel_view), name='cancel'),
        ]
        return custom_urls + urls

    def execute_view(self, request, schedule_id):
        schedule = get_object_or_404(NotificationSchedule, id=schedule_id)
        schedule.execute()
        self.message_user(request, f'Schedule #{schedule.id} executed.')
        return HttpResponseRedirect(reverse('admin:notifications_notificationschedule_changelist'))

    def cancel_view(self, request, schedule_id):
        schedule = get_object_or_404(NotificationSchedule, id=schedule_id)
        schedule.cancel()
        self.message_user(request, f'Schedule #{schedule.id} cancelled.')
        return HttpResponseRedirect(reverse('admin:notifications_notificationschedule_changelist'))


# ============================================================================
# NOTIFICATION DIGEST ADMIN
# ============================================================================

@admin.register(NotificationDigest)
class NotificationDigestAdmin(ModelAdmin):
    """
    Admin configuration for NotificationDigest model (read-only).
    """
    list_display = (
        'id',
        'user_display',
        'digest_type_badge',
        'notification_count_display',
        'sent_badge',
        'created_at_display',
    )

    list_filter = (
        'digest_type',
        ('user', admin.RelatedOnlyFieldListFilter),
        'sent_at',
        'created_at',
    )

    search_fields = (
        'user__email',
        'user__first_name',
        'user__last_name',
    )

    ordering = ('-created_at',)

    readonly_fields = (
        'id',
        'user',
        'digest_type',
        'notifications',
        'summary',
        'sent_at',
        'created_at',
        'updated_at',
    )

    fieldsets = (
        (_('Digest'), {
            'fields': (
                'user',
                'digest_type',
                'notifications',
                'summary',
            )
        }),
        (_('Status'), {
            'fields': (
                'sent_at',
            )
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def digest_type_badge(self, obj):
        colors = {'daily': 'blue', 'weekly': 'purple'}
        color = colors.get(obj.digest_type, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_digest_type_display()
        )
    digest_type_badge.short_description = _('Type')
    digest_type_badge.admin_order_field = 'digest_type'

    def notification_count_display(self, obj):
        return len(obj.notifications) if obj.notifications else 0
    notification_count_display.short_description = _('Notifications')
    notification_count_display.admin_order_field = 'notifications'

    def sent_badge(self, obj):
        if obj.sent_at:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Sent</span>'
            )
        return format_html(
                '<span style="color: orange; font-weight: bold;">⏳ Pending</span>'
            )
    sent_badge.short_description = _('Sent')
    sent_badge.admin_order_field = 'sent_at'

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ============================================================================
# NOTIFICATION AUDIT ADMIN
# ============================================================================

@admin.register(NotificationAudit)
class NotificationAuditAdmin(ModelAdmin):
    """
    Admin configuration for NotificationAudit model (read-only).
    """
    list_display = (
        'id',
        'notification_display',
        'user_display',
        'action_display',
        'old_status_display',
        'new_status_display',
        'timestamp_display',
    )

    list_filter = (
        'action',
        ('notification', admin.RelatedOnlyFieldListFilter),
        ('user', admin.RelatedOnlyFieldListFilter),
        'timestamp',
    )

    search_fields = (
        'action',
        'notification__id',
        'user__email',
        'details',
    )

    ordering = ('-timestamp',)

    readonly_fields = (
        'id',
        'notification',
        'user',
        'action',
        'old_status',
        'new_status',
        'details',
        'timestamp',
        'ip_address',
    )

    fieldsets = (
        (_('Audit Entry'), {
            'fields': (
                'notification',
                'user',
                'action',
                'timestamp',
            )
        }),
        (_('Status Change'), {
            'fields': (
                'old_status',
                'new_status',
            )
        }),
        (_('Details'), {
            'fields': (
                'details',
                'ip_address',
            ),
            'classes': ('collapse',),
        }),
    )

    def notification_display(self, obj):
        url = reverse('admin:notifications_notification_change', args=[obj.notification.id])
        return format_html('<a href="{}">#{}</a>', url, obj.notification.id)
    notification_display.short_description = _('Notification')
    notification_display.admin_order_field = 'notification__id'

    def user_display(self, obj):
        if obj.user:
            url = reverse('admin:users_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.email)
        return 'System'
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def action_display(self, obj):
        return format_html(
            '<code style="background: #f8f9fa; padding: 2px 6px; border-radius: 4px;">{}</code>',
            obj.action
        )
    action_display.short_description = _('Action')
    action_display.admin_order_field = 'action'

    def old_status_display(self, obj):
        return obj.old_status or '-'
    old_status_display.short_description = _('Old Status')

    def new_status_display(self, obj):
        return obj.new_status or '-'
    new_status_display.short_description = _('New Status')

    def timestamp_display(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')
    timestamp_display.admin_order_field = 'timestamp'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False