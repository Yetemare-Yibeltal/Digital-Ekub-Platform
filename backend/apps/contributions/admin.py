"""
Admin configuration for the contributions app.

This module provides comprehensive Django admin interfaces for all contribution models:
- Contribution: Main contribution entity with full CRUD operations
- ContributionPayment: Payment records with status management
- ContributionReminder: Reminder tracking
- ContributionAudit: Audit log viewing

All admin classes include custom list displays, filters, search fields,
inline relationships, and custom actions for efficient contribution management.
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
from apps.common.constants import ContributionStatus, ContributionType, PaymentStatus, PaymentMethod
from apps.common.utils import format_currency, log_audit_event

from .models import (
    Contribution,
    ContributionPayment,
    ContributionReminder,
    ContributionAudit,
)


# ============================================================================
# CONTRIBUTION ADMIN
# ============================================================================

@admin.register(Contribution)
class ContributionAdmin(ModelAdmin):
    """
    Admin configuration for Contribution model with comprehensive features.
    """
    # List display
    list_display = (
        'id',
        'user_display',
        'group_display',
        'amount_display',
        'round_display',
        'status_badge',
        'due_date_display',
        'paid_date_display',
        'days_overdue_display',
        'created_at_display',
        'actions_display',
    )

    # List filters
    list_filter = (
        'status',
        'contribution_type',
        ('group', admin.RelatedOnlyFieldListFilter),
        ('user', admin.RelatedOnlyFieldListFilter),
        'due_date',
        'paid_date',
        'created_at',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    # Search fields
    search_fields = (
        'id',
        'user__email',
        'user__first_name',
        'user__last_name',
        'group__name',
        'reference',
        'notes',
    )

    # Ordering
    ordering = ('-due_date',)

    # Readonly fields
    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'deleted_at',
        'created_by',
        'payment',
        'days_overdue',
        'penalty_applied',
        'reminder_count',
        'platform_fee',
        'net_amount',
        'get_audit_trail_link',
        'get_payment_link',
        'get_reminders_link',
        'get_status_history_display',
    )

    # Fieldsets
    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'id',
                'user',
                'group',
                'round',
                'amount',
                'contribution_type',
                'status',
            )
        }),

        (_('Dates'), {
            'fields': (
                'due_date',
                'paid_date',
                'created_at',
                'updated_at',
            )
        }),

        (_('Financial Details'), {
            'fields': (
                'penalty_amount',
                'waived_amount',
                'platform_fee',
                'net_amount',
                'reference',
                'notes',
            )
        }),

        (_('Statistics'), {
            'fields': (
                'days_overdue',
                'penalty_applied',
                'reminder_count',
                'get_status_history_display',
            ),
            'classes': ('collapse',),
        }),

        (_('Admin Links'), {
            'fields': (
                'get_payment_link',
                'get_reminders_link',
                'get_audit_trail_link',
            ),
            'classes': ('collapse',),
        }),

        (_('Metadata'), {
            'fields': (
                'created_by',
                'deleted_at',
            ),
            'classes': ('collapse',),
        }),
    )

    # Actions
    actions = [
        'mark_as_paid',
        'mark_as_overdue',
        'cancel_contributions',
        'refund_contributions',
        'waive_contributions',
        'export_as_csv',
        'export_as_json',
        'soft_delete_selected',
        'restore_selected',
    ]

    # List per page
    list_per_page = 50

    # List max show all
    list_max_show_all = 200

    # Save as
    save_as = True

    # --------------------------------------------------------------------------
    # CUSTOM DISPLAY METHODS
    # --------------------------------------------------------------------------

    def user_display(self, obj):
        """Display user with link to user admin."""
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def group_display(self, obj):
        """Display group with link to group admin."""
        url = reverse('admin:groups_group_change', args=[obj.group.id])
        return format_html('<a href="{}">{}</a>', url, obj.group.name)
    group_display.short_description = _('Group')
    group_display.admin_order_field = 'group__name'

    def amount_display(self, obj):
        """Display formatted amount."""
        return format_currency(obj.amount)
    amount_display.short_description = _('Amount')
    amount_display.admin_order_field = 'amount'

    def round_display(self, obj):
        """Display round number (1-indexed)."""
        return obj.round + 1
    round_display.short_description = _('Round')
    round_display.admin_order_field = 'round'

    def status_badge(self, obj):
        """Display status with colored badge."""
        colors = {
            ContributionStatus.PENDING: 'orange',
            ContributionStatus.PAID: 'green',
            ContributionStatus.OVERDUE: 'red',
            ContributionStatus.CANCELLED: 'gray',
            ContributionStatus.REFUNDED: 'blue',
            ContributionStatus.PARTIALLY_PAID: 'purple',
            ContributionStatus.WAIVED: 'teal',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 12px; font-size: 12px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def due_date_display(self, obj):
        """Display formatted due date."""
        if obj.due_date:
            return obj.due_date.strftime('%Y-%m-%d %H:%M')
        return '-'
    due_date_display.short_description = _('Due Date')
    due_date_display.admin_order_field = 'due_date'

    def paid_date_display(self, obj):
        """Display formatted paid date."""
        if obj.paid_date:
            return obj.paid_date.strftime('%Y-%m-%d %H:%M')
        return '-'
    paid_date_display.short_description = _('Paid Date')
    paid_date_display.admin_order_field = 'paid_date'

    def days_overdue_display(self, obj):
        """Display days overdue with color."""
        if obj.status == ContributionStatus.OVERDUE:
            days = obj.days_overdue_calculated
            color = 'red' if days > 30 else 'orange' if days > 7 else 'yellow'
            return format_html(
                '<span style="color: {}; font-weight: bold;">{} days</span>',
                color,
                days
            )
        return '-'
    days_overdue_display.short_description = _('Days Overdue')
    days_overdue_display.admin_order_field = 'days_overdue'

    def created_at_display(self, obj):
        """Display formatted created at."""
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def actions_display(self, obj):
        """Display action buttons for quick operations."""
        actions = []

        if obj.status in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #28a745; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 2px;">Mark Paid</button>',
                    f'/admin/contributions/contribution/{obj.id}/mark_paid/'
                )
            )

        if obj.status == ContributionStatus.PENDING:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #ffc107; color: black; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 2px;">Mark Overdue</button>',
                    f'/admin/contributions/contribution/{obj.id}/mark_overdue/'
                )
            )

        if obj.status not in [ContributionStatus.CANCELLED, ContributionStatus.REFUNDED]:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #dc3545; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 2px;">Cancel</button>',
                    f'/admin/contributions/contribution/{obj.id}/cancel/'
                )
            )

        if obj.status == ContributionStatus.PAID:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #17a2b8; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 2px;">Refund</button>',
                    f'/admin/contributions/contribution/{obj.id}/refund/'
                )
            )

        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')
    actions_display.allow_tags = True

    def get_audit_trail_link(self, obj):
        """Link to audit trail for this contribution."""
        url = reverse('admin:contributions_contributionaudit_changelist') + f'?contribution__id__exact={obj.id}'
        count = obj.audits.count()
        return format_html('<a href="{}">View Audit Trail ({})</a>', url, count)
    get_audit_trail_link.short_description = _('Audit Trail')

    def get_payment_link(self, obj):
        """Link to payment for this contribution."""
        if obj.payment:
            url = reverse('admin:contributions_contributionpayment_change', args=[obj.payment.id])
            return format_html('<a href="{}">View Payment (#{})</a>', url, obj.payment.id)
        return _('No payment recorded')
    get_payment_link.short_description = _('Payment')

    def get_reminders_link(self, obj):
        """Link to reminders for this contribution."""
        url = reverse('admin:contributions_contributionreminder_changelist') + f'?contribution__id__exact={obj.id}'
        count = obj.reminders.count()
        return format_html('<a href="{}">View Reminders ({})</a>', url, count)
    get_reminders_link.short_description = _('Reminders')

    def get_status_history_display(self, obj):
        """Display status history as a formatted list."""
        history = obj.status_history
        if not history:
            return _('No status changes recorded.')

        html = '<table style="border-collapse: collapse; width: 100%;">'
        html += '<tr><th style="text-align: left; padding: 2px 8px;">Old</th>'
        html += '<th style="text-align: left; padding: 2px 8px;">New</th>'
        html += '<th style="text-align: left; padding: 2px 8px;">Date</th></tr>'
        for entry in history[-10:]:  # Show last 10
            html += f'<tr><td style="padding: 2px 8px;">{entry["old_status"]}</td>'
            html += f'<td style="padding: 2px 8px;">{entry["new_status"]}</td>'
            html += f'<td style="padding: 2px 8px;">{entry["timestamp"].strftime("%Y-%m-%d %H:%M")}</td></tr>'
        html += '</table>'
        return format_html(html)
    get_status_history_display.short_description = _('Status History')

    # --------------------------------------------------------------------------
    # CUSTOM ACTIONS
    # --------------------------------------------------------------------------

    def mark_as_paid(self, request, queryset):
        """Mark selected contributions as paid."""
        count = 0
        errors = []
        for contribution in queryset.filter(status__in=[ContributionStatus.PENDING, ContributionStatus.OVERDUE]):
            try:
                contribution.mark_as_paid(payment_method='cash')
                count += 1
            except Exception as e:
                errors.append(f'#{contribution.id}: {str(e)}')
        msg = f'Marked {count} contribution(s) as paid.'
        if errors:
            msg += f' Errors: {", ".join(errors)}'
        self.message_user(request, msg)
    mark_as_paid.short_description = _('Mark selected as paid')

    def mark_as_overdue(self, request, queryset):
        """Mark selected contributions as overdue."""
        count = 0
        errors = []
        for contribution in queryset.filter(status=ContributionStatus.PENDING):
            try:
                contribution.mark_as_overdue()
                count += 1
            except Exception as e:
                errors.append(f'#{contribution.id}: {str(e)}')
        msg = f'Marked {count} contribution(s) as overdue.'
        if errors:
            msg += f' Errors: {", ".join(errors)}'
        self.message_user(request, msg)
    mark_as_overdue.short_description = _('Mark selected as overdue')

    def cancel_contributions(self, request, queryset):
        """Cancel selected contributions."""
        reason = request.POST.get('reason', 'Cancelled via admin')
        count = 0
        errors = []
        for contribution in queryset.filter(
            status__in=[ContributionStatus.PENDING, ContributionStatus.OVERDUE]
        ):
            try:
                contribution.cancel(reason)
                count += 1
            except Exception as e:
                errors.append(f'#{contribution.id}: {str(e)}')
        msg = f'Cancelled {count} contribution(s).'
        if errors:
            msg += f' Errors: {", ".join(errors)}'
        self.message_user(request, msg)
    cancel_contributions.short_description = _('Cancel selected contributions')

    def refund_contributions(self, request, queryset):
        """Refund selected contributions."""
        reason = request.POST.get('reason', 'Refunded via admin')
        count = 0
        errors = []
        for contribution in queryset.filter(status=ContributionStatus.PAID):
            try:
                contribution.refund(reason)
                count += 1
            except Exception as e:
                errors.append(f'#{contribution.id}: {str(e)}')
        msg = f'Refunded {count} contribution(s).'
        if errors:
            msg += f' Errors: {", ".join(errors)}'
        self.message_user(request, msg)
    refund_contributions.short_description = _('Refund selected contributions')

    def waive_contributions(self, request, queryset):
        """Waive selected contributions."""
        amount = Decimal(request.POST.get('amount', '0'))
        if amount <= 0:
            self.message_user(request, 'Please provide a valid amount to waive.', messages.ERROR)
            return
        reason = request.POST.get('reason', 'Waived via admin')
        count = 0
        errors = []
        for contribution in queryset.filter(status__in=[ContributionStatus.PENDING, ContributionStatus.OVERDUE]):
            try:
                contribution.waive(min(amount, contribution.amount), reason)
                count += 1
            except Exception as e:
                errors.append(f'#{contribution.id}: {str(e)}')
        msg = f'Waived {count} contribution(s).'
        if errors:
            msg += f' Errors: {", ".join(errors)}'
        self.message_user(request, msg)
    waive_contributions.short_description = _('Waive selected contributions')

    def export_as_csv(self, request, queryset):
        """Export selected contributions as CSV."""
        meta = self.model._meta
        field_names = [
            'id', 'user__email', 'group__name', 'amount', 'round',
            'status', 'due_date', 'paid_date', 'penalty_amount',
            'waived_amount', 'reference', 'created_at'
        ]
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename={meta.verbose_name_plural}.csv'
        writer = csv.writer(response)
        writer.writerow(field_names)
        for obj in queryset:
            row = [
                obj.id,
                obj.user.email,
                obj.group.name,
                float(obj.amount),
                obj.round,
                obj.get_status_display(),
                obj.due_date.strftime('%Y-%m-%d') if obj.due_date else '',
                obj.paid_date.strftime('%Y-%m-%d') if obj.paid_date else '',
                float(obj.penalty_amount),
                float(obj.waived_amount),
                obj.reference or '',
                obj.created_at.strftime('%Y-%m-%d %H:%M'),
            ]
            writer.writerow(row)
        self.message_user(request, f'Exported {queryset.count()} contribution(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def export_as_json(self, request, queryset):
        """Export selected contributions as JSON."""
        from django.core.serializers.json import DjangoJSONEncoder
        data = list(queryset.values(
            'id', 'user__email', 'group__name', 'amount', 'round',
            'status', 'due_date', 'paid_date', 'penalty_amount',
            'waived_amount', 'reference', 'created_at'
        ))
        response = HttpResponse(
            json.dumps(data, cls=DjangoJSONEncoder, indent=2),
            content_type='application/json'
        )
        response['Content-Disposition'] = 'attachment; filename=contributions.json'
        self.message_user(request, f'Exported {queryset.count()} contribution(s).')
        return response
    export_as_json.short_description = _('Export selected as JSON')

    def soft_delete_selected(self, request, queryset):
        """Soft delete selected contributions."""
        count = 0
        for obj in queryset:
            if not obj.is_deleted:
                obj.soft_delete(reason='Deleted via admin')
                count += 1
        self.message_user(request, f'Soft deleted {count} contribution(s).')
    soft_delete_selected.short_description = _('Soft delete selected')

    def restore_selected(self, request, queryset):
        """Restore selected soft-deleted contributions."""
        count = 0
        for obj in queryset.filter(deleted_at__isnull=False):
            obj.restore()
            count += 1
        self.message_user(request, f'Restored {count} contribution(s).')
    restore_selected.short_description = _('Restore selected')

    # --------------------------------------------------------------------------
    # CUSTOM ADMIN VIEWS
    # --------------------------------------------------------------------------

    def get_urls(self):
        """Add custom admin URLs for contribution actions."""
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:contribution_id>/mark_paid/',
                self.admin_site.admin_view(self.mark_paid_view),
                name='mark_paid'
            ),
            path(
                '<int:contribution_id>/mark_overdue/',
                self.admin_site.admin_view(self.mark_overdue_view),
                name='mark_overdue'
            ),
            path(
                '<int:contribution_id>/cancel/',
                self.admin_site.admin_view(self.cancel_view),
                name='cancel'
            ),
            path(
                '<int:contribution_id>/refund/',
                self.admin_site.admin_view(self.refund_view),
                name='refund'
            ),
        ]
        return custom_urls + urls

    def mark_paid_view(self, request, contribution_id):
        """Custom admin view to mark a contribution as paid."""
        contribution = get_object_or_404(Contribution, id=contribution_id)
        try:
            contribution.mark_as_paid(payment_method='cash')
            self.message_user(request, f'Contribution #{contribution.id} marked as paid.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:contributions_contribution_changelist'))

    def mark_overdue_view(self, request, contribution_id):
        """Custom admin view to mark a contribution as overdue."""
        contribution = get_object_or_404(Contribution, id=contribution_id)
        try:
            contribution.mark_as_overdue()
            self.message_user(request, f'Contribution #{contribution.id} marked as overdue.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:contributions_contribution_changelist'))

    def cancel_view(self, request, contribution_id):
        """Custom admin view to cancel a contribution."""
        contribution = get_object_or_404(Contribution, id=contribution_id)
        try:
            contribution.cancel(reason='Cancelled via admin')
            self.message_user(request, f'Contribution #{contribution.id} cancelled.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:contributions_contribution_changelist'))

    def refund_view(self, request, contribution_id):
        """Custom admin view to refund a contribution."""
        contribution = get_object_or_404(Contribution, id=contribution_id)
        try:
            contribution.refund(reason='Refunded via admin')
            self.message_user(request, f'Contribution #{contribution.id} refunded.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:contributions_contribution_changelist'))

    # --------------------------------------------------------------------------
    # OVERRIDEN METHODS
    # --------------------------------------------------------------------------

    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related('user', 'group', 'created_by', 'payment')

    def save_model(self, request, obj, form, change):
        """Save model with audit logging."""
        if not change:
            obj.created_by = request.user
            obj.save()
            log_audit_event(
                user_id=request.user.id,
                action='contribution_created_via_admin',
                resource='contribution',
                resource_id=obj.id,
                details={'group_id': obj.group.id, 'user_id': obj.user.id}
            )
        else:
            obj.save()
            log_audit_event(
                user_id=request.user.id,
                action='contribution_updated_via_admin',
                resource='contribution',
                resource_id=obj.id,
                details={'updated_fields': list(form.changed_data)}
            )

    def delete_model(self, request, obj):
        """Soft delete instead of hard delete."""
        obj.soft_delete(reason=f'Deleted by admin {request.user.email}')
        self.message_user(request, f'Contribution #{obj.id} has been soft deleted.')

    def delete_queryset(self, request, queryset):
        """Soft delete multiple contributions."""
        count = 0
        for obj in queryset:
            obj.soft_delete(reason=f'Bulk deleted by admin {request.user.email}')
            count += 1
        self.message_user(request, f'{count} contribution(s) have been soft deleted.')


# ============================================================================
# CONTRIBUTION PAYMENT ADMIN
# ============================================================================

@admin.register(ContributionPayment)
class ContributionPaymentAdmin(ModelAdmin):
    """Admin configuration for ContributionPayment model."""

    list_display = (
        'id',
        'contribution_display',
        'user_display',
        'amount_display',
        'payment_method_display',
        'status_badge',
        'paid_at_display',
        'reference_display',
    )

    list_filter = (
        'status',
        'payment_method',
        ('user', admin.RelatedOnlyFieldListFilter),
        ('group', admin.RelatedOnlyFieldListFilter),
        'paid_at',
        'created_at',
    )

    search_fields = (
        'id',
        'user__email',
        'user__first_name',
        'user__last_name',
        'group__name',
        'reference',
        'contribution__id',
    )

    ordering = ('-paid_at',)

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'paid_at',
        'user',
        'group',
        'contribution',
    )

    fieldsets = (
        (_('Payment Details'), {
            'fields': (
                'contribution',
                'user',
                'group',
                'amount',
                'payment_method',
                'status',
            )
        }),
        (_('Reference'), {
            'fields': (
                'reference',
                'paid_at',
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
        'mark_completed',
        'mark_failed',
        'refund_payments',
        'export_as_csv',
    ]

    def contribution_display(self, obj):
        """Display contribution with link."""
        url = reverse('admin:contributions_contribution_change', args=[obj.contribution.id])
        return format_html('<a href="{}">#{}</a>', url, obj.contribution.id)
    contribution_display.short_description = _('Contribution')
    contribution_display.admin_order_field = 'contribution__id'

    def user_display(self, obj):
        """Display user with link."""
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def amount_display(self, obj):
        """Display formatted amount."""
        return format_currency(obj.amount)
    amount_display.short_description = _('Amount')
    amount_display.admin_order_field = 'amount'

    def payment_method_display(self, obj):
        """Display payment method with badge."""
        colors = {
            PaymentMethod.TELEBIRR: 'blue',
            PaymentMethod.CHAPA: 'green',
            PaymentMethod.BANK_TRANSFER: 'purple',
            PaymentMethod.CASH: 'orange',
            PaymentMethod.MOBILE_MONEY: 'teal',
            PaymentMethod.CARD: 'red',
        }
        color = colors.get(obj.payment_method, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 12px; font-size: 12px;">{}</span>',
            color,
            obj.get_payment_method_display()
        )
    payment_method_display.short_description = _('Method')
    payment_method_display.admin_order_field = 'payment_method'

    def status_badge(self, obj):
        """Display status with colored badge."""
        colors = {
            PaymentStatus.PENDING: 'orange',
            PaymentStatus.PROCESSING: 'blue',
            PaymentStatus.COMPLETED: 'green',
            PaymentStatus.FAILED: 'red',
            PaymentStatus.CANCELLED: 'gray',
            PaymentStatus.REFUNDED: 'purple',
            PaymentStatus.REVERSED: 'darkred',
            PaymentStatus.EXPIRED: 'gray',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 12px; font-size: 12px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def paid_at_display(self, obj):
        """Display formatted paid at."""
        if obj.paid_at:
            return obj.paid_at.strftime('%Y-%m-%d %H:%M')
        return '-'
    paid_at_display.short_description = _('Paid At')
    paid_at_display.admin_order_field = 'paid_at'

    def reference_display(self, obj):
        """Display reference with truncation."""
        if obj.reference:
            return obj.reference[:30]
        return '-'
    reference_display.short_description = _('Reference')
    reference_display.admin_order_field = 'reference'

    def mark_completed(self, request, queryset):
        """Mark selected payments as completed."""
        count = 0
        for payment in queryset.filter(status=PaymentStatus.PENDING):
            payment.complete()
            count += 1
        self.message_user(request, f'Marked {count} payment(s) as completed.')
    mark_completed.short_description = _('Mark selected as completed')

    def mark_failed(self, request, queryset):
        """Mark selected payments as failed."""
        count = 0
        for payment in queryset.filter(status=PaymentStatus.PENDING):
            payment.fail()
            count += 1
        self.message_user(request, f'Marked {count} payment(s) as failed.')
    mark_failed.short_description = _('Mark selected as failed')

    def refund_payments(self, request, queryset):
        """Refund selected payments."""
        count = 0
        for payment in queryset.filter(status=PaymentStatus.COMPLETED):
            payment.refund_payment()
            count += 1
        self.message_user(request, f'Refunded {count} payment(s).')
    refund_payments.short_description = _('Refund selected payments')

    def export_as_csv(self, request, queryset):
        """Export selected payments as CSV."""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=payments.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Contribution', 'User', 'Amount', 'Method', 'Status', 'Reference', 'Paid At'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.contribution.id,
                obj.user.email,
                float(obj.amount),
                obj.get_payment_method_display(),
                obj.get_status_display(),
                obj.reference or '',
                obj.paid_at.strftime('%Y-%m-%d %H:%M') if obj.paid_at else '',
            ])
        self.message_user(request, f'Exported {queryset.count()} payment(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related('user', 'group', 'contribution')


# ============================================================================
# CONTRIBUTION REMINDER ADMIN
# ============================================================================

@admin.register(ContributionReminder)
class ContributionReminderAdmin(ModelAdmin):
    """Admin configuration for ContributionReminder model."""

    list_display = (
        'id',
        'contribution_display',
        'user_display',
        'reminder_type_display',
        'sent_at_display',
        'sent_successfully_display',
    )

    list_filter = (
        'reminder_type',
        'sent_successfully',
        ('user', admin.RelatedOnlyFieldListFilter),
        'sent_at',
    )

    search_fields = (
        'user__email',
        'user__first_name',
        'user__last_name',
        'contribution__id',
        'error_message',
    )

    ordering = ('-sent_at',)

    readonly_fields = (
        'id',
        'created_at',
        'sent_at',
        'user',
        'contribution',
    )

    fieldsets = (
        (_('Reminder Details'), {
            'fields': (
                'contribution',
                'user',
                'reminder_type',
                'sent_at',
            )
        }),
        (_('Status'), {
            'fields': (
                'sent_successfully',
                'error_message',
            )
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
            ),
            'classes': ('collapse',),
        }),
    )

    def contribution_display(self, obj):
        """Display contribution with link."""
        url = reverse('admin:contributions_contribution_change', args=[obj.contribution.id])
        return format_html('<a href="{}">#{}</a>', url, obj.contribution.id)
    contribution_display.short_description = _('Contribution')
    contribution_display.admin_order_field = 'contribution__id'

    def user_display(self, obj):
        """Display user with link."""
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def reminder_type_display(self, obj):
        """Display reminder type with badge."""
        colors = {
            'email': 'blue',
            'sms': 'orange',
            'push': 'green',
            'in_app': 'purple',
        }
        color = colors.get(obj.reminder_type, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 12px; font-size: 12px;">{}</span>',
            color,
            obj.get_reminder_type_display()
        )
    reminder_type_display.short_description = _('Type')
    reminder_type_display.admin_order_field = 'reminder_type'

    def sent_at_display(self, obj):
        """Display formatted sent at."""
        return obj.sent_at.strftime('%Y-%m-%d %H:%M')
    sent_at_display.short_description = _('Sent At')
    sent_at_display.admin_order_field = 'sent_at'

    def sent_successfully_display(self, obj):
        """Display sent status with badge."""
        if obj.sent_successfully:
            return format_html('<span style="color: green; font-weight: bold;">✓ Sent</span>')
        return format_html('<span style="color: red; font-weight: bold;">✗ Failed</span>')
    sent_successfully_display.short_description = _('Status')
    sent_successfully_display.admin_order_field = 'sent_successfully'

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related('user', 'contribution')

    def has_add_permission(self, request):
        """Prevent manual addition."""
        return False

    def has_change_permission(self, request, obj=None):
        """Prevent editing."""
        return False


# ============================================================================
# CONTRIBUTION AUDIT ADMIN
# ============================================================================

@admin.register(ContributionAudit)
class ContributionAuditAdmin(ModelAdmin):
    """Admin configuration for ContributionAudit model."""

    list_display = (
        'id',
        'contribution_display',
        'action_display',
        'user_display',
        'old_status_display',
        'new_status_display',
        'timestamp_display',
    )

    list_filter = (
        'action',
        ('user', admin.RelatedOnlyFieldListFilter),
        ('contribution', admin.RelatedOnlyFieldListFilter),
        'timestamp',
    )

    search_fields = (
        'action',
        'user__email',
        'user__first_name',
        'user__last_name',
        'contribution__id',
        'details',
    )

    ordering = ('-timestamp',)

    readonly_fields = (
        'id',
        'contribution',
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
                'contribution',
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
        (_('Additional Info'), {
            'fields': (
                'details',
                'ip_address',
            ),
            'classes': ('collapse',),
        }),
    )

    def contribution_display(self, obj):
        """Display contribution with link."""
        url = reverse('admin:contributions_contribution_change', args=[obj.contribution.id])
        return format_html('<a href="{}">#{}</a>', url, obj.contribution.id)
    contribution_display.short_description = _('Contribution')
    contribution_display.admin_order_field = 'contribution__id'

    def user_display(self, obj):
        """Display user with link."""
        if obj.user:
            url = reverse('admin:users_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.email)
        return 'System'
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def action_display(self, obj):
        """Display action with styling."""
        return format_html(
            '<code style="background: #f8f9fa; padding: 2px 6px; border-radius: 4px;">{}</code>',
            obj.action
        )
    action_display.short_description = _('Action')
    action_display.admin_order_field = 'action'

    def old_status_display(self, obj):
        """Display old status."""
        return obj.old_status or '-'
    old_status_display.short_description = _('Old Status')

    def new_status_display(self, obj):
        """Display new status."""
        return obj.new_status or '-'
    new_status_display.short_description = _('New Status')

    def timestamp_display(self, obj):
        """Display formatted timestamp."""
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')
    timestamp_display.admin_order_field = 'timestamp'

    def get_queryset(self, request):
        """Optimize queryset."""
        return super().get_queryset(request).select_related('user', 'contribution')

    def has_add_permission(self, request):
        """Prevent manual addition."""
        return False

    def has_change_permission(self, request, obj=None):
        """Prevent editing."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion."""
        return False