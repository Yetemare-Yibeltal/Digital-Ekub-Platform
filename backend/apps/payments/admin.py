"""
Admin configuration for the payments app.

This module provides comprehensive Django admin interfaces for all payment models:
- Payment: Main payment entity with full CRUD operations
- Payout: Payout records with status management
- PaymentTransaction: Transaction records
- PaymentGatewayLog: Gateway API call logs
- PaymentWebhookLog: Webhook event logs
- PaymentReconciliation: Reconciliation records
- PaymentDispute: Dispute management
- Settlement: Settlement records
- PaymentMethod: User payment methods
- PaymentAudit: Audit trail

All admin classes include custom list displays, filters, search fields,
inline relationships, and custom actions for efficient management.
"""

from django.contrib import admin
from django.contrib.admin import ModelAdmin, TabularInline
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
import logging

from apps.users.models import User
from apps.groups.models import Group
from apps.common.constants import PaymentStatus, PaymentMethod, PayoutStatus
from apps.common.utils import format_currency, log_audit_event, get_client_ip

from .models import (
    Payment,
    Payout,
    PaymentTransaction,
    PaymentGatewayLog,
    PaymentWebhookLog,
    PaymentReconciliation,
    PaymentDispute,
    Settlement,
    PaymentMethod,
    PaymentAudit,
)

logger = logging.getLogger(__name__)


# ============================================================================
# INLINE CLASSES
# ============================================================================

class PaymentTransactionInline(TabularInline):
    """Inline for payment transactions."""
    model = PaymentTransaction
    extra = 0
    fields = ('transaction_id', 'gateway', 'amount', 'status', 'initiated_at', 'completed_at')
    readonly_fields = ('transaction_id', 'gateway', 'amount', 'status', 'initiated_at', 'completed_at')
    can_delete = False
    max_num = 0
    verbose_name = _('Transaction')
    verbose_name_plural = _('Transactions')


class PaymentGatewayLogInline(TabularInline):
    """Inline for gateway logs."""
    model = PaymentGatewayLog
    extra = 0
    fields = ('gateway', 'endpoint', 'method', 'response_status', 'created_at')
    readonly_fields = ('gateway', 'endpoint', 'method', 'response_status', 'created_at')
    can_delete = False
    max_num = 10
    verbose_name = _('Gateway Log')
    verbose_name_plural = _('Gateway Logs')


class PaymentReconciliationInline(TabularInline):
    """Inline for reconciliations."""
    model = PaymentReconciliation
    extra = 0
    fields = ('external_reference', 'status', 'reconciled_at')
    readonly_fields = ('external_reference', 'status', 'reconciled_at')
    can_delete = False
    max_num = 5
    verbose_name = _('Reconciliation')
    verbose_name_plural = _('Reconciliations')


class PaymentDisputeInline(TabularInline):
    """Inline for disputes."""
    model = PaymentDispute
    extra = 0
    fields = ('amount', 'reason', 'status', 'created_at')
    readonly_fields = ('amount', 'reason', 'status', 'created_at')
    can_delete = False
    max_num = 5
    verbose_name = _('Dispute')
    verbose_name_plural = _('Disputes')


class PaymentAuditInline(TabularInline):
    """Inline for audit entries."""
    model = PaymentAudit
    extra = 0
    fields = ('action', 'user', 'old_status', 'new_status', 'timestamp')
    readonly_fields = ('action', 'user', 'old_status', 'new_status', 'timestamp')
    can_delete = False
    max_num = 20
    verbose_name = _('Audit')
    verbose_name_plural = _('Audits')


# ============================================================================
# PAYMENT ADMIN
# ============================================================================

@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    """
    Admin configuration for Payment model with comprehensive features.
    """
    list_display = (
        'id',
        'reference_display',
        'user_display',
        'group_display',
        'amount_display',
        'payment_method_display',
        'status_badge',
        'paid_at_display',
        'created_at_display',
        'actions_display',
    )

    list_filter = (
        'status',
        'payment_method',
        'gateway',
        ('user', admin.RelatedOnlyFieldListFilter),
        ('group', admin.RelatedOnlyFieldListFilter),
        'created_at',
        'paid_at',
        'webhook_received',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    search_fields = (
        'id',
        'reference',
        'user__email',
        'user__first_name',
        'user__last_name',
        'group__name',
        'error_message',
    )

    ordering = ('-created_at',)

    readonly_fields = (
        'id',
        'reference',
        'created_at',
        'updated_at',
        'deleted_at',
        'created_by',
        'webhook_received',
        'webhook_processed_at',
        'retry_count',
        'platform_fee',
        'gateway_fee',
        'total_fee',
        'net_amount',
    )

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'id',
                'reference',
                'user',
                'group',
                'contribution',
                'amount',
                'payment_method',
                'gateway',
                'status',
            )
        }),
        (_('Financial Details'), {
            'fields': (
                'platform_fee',
                'gateway_fee',
                'total_fee',
                'net_amount',
            )
        }),
        (_('Timing'), {
            'fields': (
                'created_at',
                'updated_at',
                'paid_at',
                'expires_at',
            )
        }),
        (_('Webhook & Retry'), {
            'fields': (
                'webhook_received',
                'webhook_processed_at',
                'retry_count',
            ),
            'classes': ('collapse',),
        }),
        (_('Refund'), {
            'fields': (
                'refund_reason',
                'refunded_at',
            ),
            'classes': ('collapse',),
        }),
        (_('Metadata'), {
            'fields': (
                'metadata',
                'error_message',
                'created_by',
                'deleted_at',
            ),
            'classes': ('collapse',),
        }),
    )

    inlines = [
        PaymentTransactionInline,
        PaymentGatewayLogInline,
        PaymentReconciliationInline,
        PaymentDisputeInline,
        PaymentAuditInline,
    ]

    actions = [
        'mark_as_completed',
        'mark_as_failed',
        'cancel_payments',
        'refund_payments',
        'retry_payments',
        'expire_payments',
        'export_as_csv',
        'soft_delete_selected',
        'restore_selected',
    ]

    list_per_page = 50

    # --------------------------------------------------------------------------
    # CUSTOM DISPLAY METHODS
    # --------------------------------------------------------------------------

    def reference_display(self, obj):
        return format_html(
            '<code style="background: #f8f9fa; padding: 2px 6px; border-radius: 4px; font-size: 12px;">{}</code>',
            obj.reference
        )
    reference_display.short_description = _('Reference')
    reference_display.admin_order_field = 'reference'

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def group_display(self, obj):
        url = reverse('admin:groups_group_change', args=[obj.group.id])
        return format_html('<a href="{}">{}</a>', url, obj.group.name)
    group_display.short_description = _('Group')
    group_display.admin_order_field = 'group__name'

    def amount_display(self, obj):
        return format_currency(obj.amount)
    amount_display.short_description = _('Amount')
    amount_display.admin_order_field = 'amount'

    def payment_method_display(self, obj):
        colors = {
            'telebirr': 'blue',
            'chapa': 'green',
            'bank_transfer': 'purple',
            'cash': 'orange',
            'mobile_money': 'teal',
            'card': 'red',
        }
        color = colors.get(obj.payment_method, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_payment_method_display()
        )
    payment_method_display.short_description = _('Method')
    payment_method_display.admin_order_field = 'payment_method'

    def status_badge(self, obj):
        colors = {
            'pending': 'orange',
            'processing': 'blue',
            'completed': 'green',
            'failed': 'red',
            'cancelled': 'gray',
            'refunded': 'purple',
            'reversed': 'darkred',
            'expired': 'gray',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def paid_at_display(self, obj):
        if obj.paid_at:
            return obj.paid_at.strftime('%Y-%m-%d %H:%M')
        return '-'
    paid_at_display.short_description = _('Paid At')
    paid_at_display.admin_order_field = 'paid_at'

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def actions_display(self, obj):
        actions = []
        if obj.status in ['pending', 'processing']:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #28a745; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 1px; font-size: 11px;">Complete</button>',
                    f'/admin/payments/payment/{obj.id}/complete/'
                )
            )
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #dc3545; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 1px; font-size: 11px;">Fail</button>',
                    f'/admin/payments/payment/{obj.id}/fail/'
                )
            )
        if obj.can_be_cancelled:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #ffc107; color: black; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 1px; font-size: 11px;">Cancel</button>',
                    f'/admin/payments/payment/{obj.id}/cancel/'
                )
            )
        if obj.can_be_refunded:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #17a2b8; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 1px; font-size: 11px;">Refund</button>',
                    f'/admin/payments/payment/{obj.id}/refund/'
                )
            )
        if obj.can_be_retried:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #6c757d; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 1px; font-size: 11px;">Retry</button>',
                    f'/admin/payments/payment/{obj.id}/retry/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')
    actions_display.allow_tags = True

    # --------------------------------------------------------------------------
    # CUSTOM ACTIONS
    # --------------------------------------------------------------------------

    def mark_as_completed(self, request, queryset):
        count = 0
        for payment in queryset.filter(status__in=['pending', 'processing']):
            try:
                payment.complete()
                count += 1
            except Exception as e:
                self.message_user(request, f'Error completing payment {payment.id}: {str(e)}', messages.ERROR)
        self.message_user(request, f'Marked {count} payment(s) as completed.')
    mark_as_completed.short_description = _('Mark selected as completed')

    def mark_as_failed(self, request, queryset):
        count = 0
        for payment in queryset.filter(status__in=['pending', 'processing']):
            try:
                payment.fail('Marked failed via admin')
                count += 1
            except Exception as e:
                self.message_user(request, f'Error failing payment {payment.id}: {str(e)}', messages.ERROR)
        self.message_user(request, f'Marked {count} payment(s) as failed.')
    mark_as_failed.short_description = _('Mark selected as failed')

    def cancel_payments(self, request, queryset):
        count = 0
        for payment in queryset.filter(status__in=['pending', 'processing']):
            try:
                payment.cancel()
                count += 1
            except Exception as e:
                self.message_user(request, f'Error cancelling payment {payment.id}: {str(e)}', messages.ERROR)
        self.message_user(request, f'Cancelled {count} payment(s).')
    cancel_payments.short_description = _('Cancel selected payments')

    def refund_payments(self, request, queryset):
        count = 0
        for payment in queryset.filter(status='completed'):
            try:
                payment.refund('Refunded via admin')
                count += 1
            except Exception as e:
                self.message_user(request, f'Error refunding payment {payment.id}: {str(e)}', messages.ERROR)
        self.message_user(request, f'Refunded {count} payment(s).')
    refund_payments.short_description = _('Refund selected payments')

    def retry_payments(self, request, queryset):
        count = 0
        for payment in queryset.filter(status='failed', retry_count__lt=3):
            try:
                payment.retry()
                count += 1
            except Exception as e:
                self.message_user(request, f'Error retrying payment {payment.id}: {str(e)}', messages.ERROR)
        self.message_user(request, f'Retried {count} payment(s).')
    retry_payments.short_description = _('Retry selected payments')

    def expire_payments(self, request, queryset):
        count = queryset.filter(status='pending').update(status='expired')
        self.message_user(request, f'Expired {count} payment(s).')
    expire_payments.short_description = _('Expire selected payments')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=payments.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Reference', 'User', 'Group', 'Amount', 'Method', 'Status', 'Paid At', 'Created At'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.reference,
                obj.user.email,
                obj.group.name,
                float(obj.amount),
                obj.get_payment_method_display(),
                obj.get_status_display(),
                obj.paid_at.strftime('%Y-%m-%d %H:%M') if obj.paid_at else '',
                obj.created_at.strftime('%Y-%m-%d %H:%M'),
            ])
        self.message_user(request, f'Exported {queryset.count()} payment(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def soft_delete_selected(self, request, queryset):
        count = 0
        for obj in queryset:
            if not obj.deleted_at:
                obj.deleted_at = timezone.now()
                obj.save(update_fields=['deleted_at'])
                count += 1
        self.message_user(request, f'Soft deleted {count} payment(s).')
    soft_delete_selected.short_description = _('Soft delete selected')

    def restore_selected(self, request, queryset):
        count = queryset.filter(deleted_at__isnull=False).update(deleted_at=None)
        self.message_user(request, f'Restored {count} payment(s).')
    restore_selected.short_description = _('Restore selected')

    # --------------------------------------------------------------------------
    # CUSTOM ADMIN VIEWS
    # --------------------------------------------------------------------------

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:payment_id>/complete/', self.admin_site.admin_view(self.complete_view), name='complete'),
            path('<int:payment_id>/fail/', self.admin_site.admin_view(self.fail_view), name='fail'),
            path('<int:payment_id>/cancel/', self.admin_site.admin_view(self.cancel_view), name='cancel'),
            path('<int:payment_id>/refund/', self.admin_site.admin_view(self.refund_view), name='refund'),
            path('<int:payment_id>/retry/', self.admin_site.admin_view(self.retry_view), name='retry'),
        ]
        return custom_urls + urls

    def complete_view(self, request, payment_id):
        payment = get_object_or_404(Payment, id=payment_id)
        try:
            payment.complete()
            self.message_user(request, f'Payment #{payment.id} completed.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:payments_payment_changelist'))

    def fail_view(self, request, payment_id):
        payment = get_object_or_404(Payment, id=payment_id)
        try:
            payment.fail('Failed via admin')
            self.message_user(request, f'Payment #{payment.id} failed.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:payments_payment_changelist'))

    def cancel_view(self, request, payment_id):
        payment = get_object_or_404(Payment, id=payment_id)
        try:
            payment.cancel()
            self.message_user(request, f'Payment #{payment.id} cancelled.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:payments_payment_changelist'))

    def refund_view(self, request, payment_id):
        payment = get_object_or_404(Payment, id=payment_id)
        try:
            payment.refund('Refunded via admin')
            self.message_user(request, f'Payment #{payment.id} refunded.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:payments_payment_changelist'))

    def retry_view(self, request, payment_id):
        payment = get_object_or_404(Payment, id=payment_id)
        try:
            payment.retry()
            self.message_user(request, f'Payment #{payment.id} retried.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:payments_payment_changelist'))

    # --------------------------------------------------------------------------
    # OVERRIDEN METHODS
    # --------------------------------------------------------------------------

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'group', 'contribution', 'created_by')

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.save()
        log_audit_event(
            user_id=request.user.id,
            action='payment_' + ('created' if not change else 'updated') + '_via_admin',
            resource='payment',
            resource_id=obj.id,
            ip=get_client_ip(request),
        )


# ============================================================================
# PAYOUT ADMIN
# ============================================================================

@admin.register(Payout)
class PayoutAdmin(ModelAdmin):
    list_display = (
        'id',
        'reference_display',
        'user_display',
        'group_display',
        'amount_display',
        'payout_method_display',
        'status_badge',
        'paid_at_display',
        'created_at_display',
        'actions_display',
    )
    list_filter = (
        'status',
        'payout_method',
        ('user', admin.RelatedOnlyFieldListFilter),
        ('group', admin.RelatedOnlyFieldListFilter),
        'created_at',
        'paid_at',
        ('deleted_at', admin.EmptyFieldListFilter),
    )
    search_fields = ('id', 'reference', 'user__email', 'group__name', 'reference_number')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'reference', 'created_at', 'updated_at', 'deleted_at', 'created_by')

    fieldsets = (
        (_('Basic Information'), {'fields': ('user', 'group', 'winner_history', 'amount', 'payout_method', 'status')}),
        (_('Financial Details'), {'fields': ('platform_fee', 'gateway_fee', 'total_fee', 'net_amount')}),
        (_('Timing'), {'fields': ('created_at', 'updated_at', 'paid_at')}),
        (_('Reference'), {'fields': ('reference', 'reference_number', 'notes')}),
        (_('Metadata'), {'fields': ('created_by', 'deleted_at')}),
    )

    actions = ['mark_completed', 'mark_failed', 'cancel_payouts', 'put_on_hold', 'export_as_csv']

    def reference_display(self, obj):
        return format_html('<code style="background: #f8f9fa; padding: 2px 6px; border-radius: 4px; font-size: 12px;">{}</code>', obj.reference)
    reference_display.short_description = _('Reference')

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')

    def group_display(self, obj):
        url = reverse('admin:groups_group_change', args=[obj.group.id])
        return format_html('<a href="{}">{}</a>', url, obj.group.name)
    group_display.short_description = _('Group')

    def amount_display(self, obj):
        return format_currency(obj.amount)
    amount_display.short_description = _('Amount')

    def payout_method_display(self, obj):
        return obj.get_payout_method_display()
    payout_method_display.short_description = _('Method')

    def status_badge(self, obj):
        colors = {
            'pending': 'orange',
            'processing': 'blue',
            'completed': 'green',
            'failed': 'red',
            'cancelled': 'gray',
            'partially_paid': 'purple',
            'on_hold': 'darkred',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')

    def paid_at_display(self, obj):
        return obj.paid_at.strftime('%Y-%m-%d %H:%M') if obj.paid_at else '-'
    paid_at_display.short_description = _('Paid At')

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')

    def actions_display(self, obj):
        actions = []
        if obj.can_be_completed:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #28a745; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Complete</button>',
                    f'/admin/payments/payout/{obj.id}/complete/'
                )
            )
        if obj.can_be_failed:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #dc3545; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Fail</button>',
                    f'/admin/payments/payout/{obj.id}/fail/'
                )
            )
        if obj.can_be_cancelled:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #ffc107; color: black; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Cancel</button>',
                    f'/admin/payments/payout/{obj.id}/cancel/'
                )
            )
        if obj.status in ['pending', 'processing']:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #6c757d; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; margin: 1px; font-size: 11px;">Hold</button>',
                    f'/admin/payments/payout/{obj.id}/hold/'
                )
            )
        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')

    def mark_completed(self, request, queryset):
        count = 0
        for obj in queryset.filter(status__in=['pending', 'processing']):
            try:
                obj.complete()
                count += 1
            except Exception as e:
                self.message_user(request, f'Error completing payout {obj.id}: {str(e)}', messages.ERROR)
        self.message_user(request, f'Completed {count} payout(s).')
    mark_completed.short_description = _('Mark selected as completed')

    def mark_failed(self, request, queryset):
        count = 0
        for obj in queryset.filter(status__in=['pending', 'processing']):
            try:
                obj.fail('Failed via admin')
                count += 1
            except Exception as e:
                self.message_user(request, f'Error failing payout {obj.id}: {str(e)}', messages.ERROR)
        self.message_user(request, f'Failed {count} payout(s).')
    mark_failed.short_description = _('Mark selected as failed')

    def cancel_payouts(self, request, queryset):
        count = 0
        for obj in queryset.filter(status__in=['pending', 'processing']):
            try:
                obj.cancel('Cancelled via admin')
                count += 1
            except Exception as e:
                self.message_user(request, f'Error cancelling payout {obj.id}: {str(e)}', messages.ERROR)
        self.message_user(request, f'Cancelled {count} payout(s).')
    cancel_payouts.short_description = _('Cancel selected payouts')

    def put_on_hold(self, request, queryset):
        count = 0
        for obj in queryset.filter(status__in=['pending', 'processing']):
            try:
                obj.put_on_hold('Put on hold via admin')
                count += 1
            except Exception as e:
                self.message_user(request, f'Error putting payout {obj.id} on hold: {str(e)}', messages.ERROR)
        self.message_user(request, f'Put {count} payout(s) on hold.')
    put_on_hold.short_description = _('Put selected on hold')

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=payouts.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Reference', 'User', 'Group', 'Amount', 'Status', 'Paid At'])
        for obj in queryset:
            writer.writerow([
                obj.id,
                obj.reference,
                obj.user.email,
                obj.group.name,
                float(obj.amount),
                obj.get_status_display(),
                obj.paid_at.strftime('%Y-%m-%d %H:%M') if obj.paid_at else ''
            ])
        self.message_user(request, f'Exported {queryset.count()} payout(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'group', 'winner_history', 'created_by')

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:payout_id>/complete/', self.admin_site.admin_view(self.complete_view), name='complete'),
            path('<int:payout_id>/fail/', self.admin_site.admin_view(self.fail_view), name='fail'),
            path('<int:payout_id>/cancel/', self.admin_site.admin_view(self.cancel_view), name='cancel'),
            path('<int:payout_id>/hold/', self.admin_site.admin_view(self.hold_view), name='hold'),
        ]
        return custom_urls + urls

    def complete_view(self, request, payout_id):
        payout = get_object_or_404(Payout, id=payout_id)
        try:
            payout.complete()
            self.message_user(request, f'Payout #{payout.id} completed.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:payments_payout_changelist'))

    def fail_view(self, request, payout_id):
        payout = get_object_or_404(Payout, id=payout_id)
        try:
            payout.fail('Failed via admin')
            self.message_user(request, f'Payout #{payout.id} failed.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:payments_payout_changelist'))

    def cancel_view(self, request, payout_id):
        payout = get_object_or_404(Payout, id=payout_id)
        try:
            payout.cancel('Cancelled via admin')
            self.message_user(request, f'Payout #{payout.id} cancelled.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:payments_payout_changelist'))

    def hold_view(self, request, payout_id):
        payout = get_object_or_404(Payout, id=payout_id)
        try:
            payout.put_on_hold('Put on hold via admin')
            self.message_user(request, f'Payout #{payout.id} put on hold.')
        except Exception as e:
            self.message_user(request, f'Error: {str(e)}', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:payments_payout_changelist'))


# ============================================================================
# PAYMENT TRANSACTION ADMIN
# ============================================================================

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(ModelAdmin):
    list_display = ('id', 'transaction_id', 'payment_display', 'user_display', 'amount_display', 'status_display', 'initiated_at_display')
    list_filter = ('status', 'gateway', ('user', admin.RelatedOnlyFieldListFilter), ('payment', admin.RelatedOnlyFieldListFilter))
    search_fields = ('transaction_id', 'user__email', 'payment__reference')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'payment', 'user', 'group')

    def payment_display(self, obj):
        url = reverse('admin:payments_payment_change', args=[obj.payment.id])
        return format_html('<a href="{}">#{}</a>', url, obj.payment.id)
    payment_display.short_description = _('Payment')

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')

    def amount_display(self, obj):
        return format_currency(obj.amount)
    amount_display.short_description = _('Amount')

    def status_display(self, obj):
        return obj.get_status_display()
    status_display.short_description = _('Status')

    def initiated_at_display(self, obj):
        return obj.initiated_at.strftime('%Y-%m-%d %H:%M')
    initiated_at_display.short_description = _('Initiated')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('payment', 'user', 'group')


# ============================================================================
# PAYMENT GATEWAY LOG ADMIN
# ============================================================================

@admin.register(PaymentGatewayLog)
class PaymentGatewayLogAdmin(ModelAdmin):
    list_display = ('id', 'gateway', 'endpoint_short', 'method', 'response_status_display', 'payment_display', 'created_at_display')
    list_filter = ('gateway', 'method', ('payment', admin.RelatedOnlyFieldListFilter))
    search_fields = ('endpoint', 'payment__reference', 'error_message')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'payment', 'gateway', 'endpoint', 'method', 'request_headers', 'request_body', 'response_status', 'response_headers', 'response_body', 'error_message', 'duration_ms')
    fieldsets = (
        (_('Request'), {'fields': ('gateway', 'endpoint', 'method', 'request_headers', 'request_body')}),
        (_('Response'), {'fields': ('response_status', 'response_headers', 'response_body', 'error_message', 'duration_ms')}),
        (_('Metadata'), {'fields': ('payment', 'created_at')}),
    )

    def endpoint_short(self, obj):
        return obj.endpoint[:50] + '...' if len(obj.endpoint) > 50 else obj.endpoint
    endpoint_short.short_description = _('Endpoint')

    def response_status_display(self, obj):
        color = 'green' if obj.response_status and obj.response_status < 400 else 'red'
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.response_status)
    response_status_display.short_description = _('Status')

    def payment_display(self, obj):
        url = reverse('admin:payments_payment_change', args=[obj.payment.id])
        return format_html('<a href="{}">#{}</a>', url, obj.payment.id)
    payment_display.short_description = _('Payment')

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')

    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False


# ============================================================================
# PAYMENT WEBHOOK LOG ADMIN
# ============================================================================

@admin.register(PaymentWebhookLog)
class PaymentWebhookLogAdmin(ModelAdmin):
    list_display = ('id', 'gateway', 'event_type', 'verified_display', 'processed_display', 'created_at_display')
    list_filter = ('gateway', 'event_type', 'verified', 'processed')
    search_fields = ('event_type', 'payload', 'error_message')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'gateway', 'event_type', 'payload', 'headers', 'signature', 'verified', 'processed', 'processed_at', 'error_message')
    fieldsets = (
        (_('Webhook'), {'fields': ('gateway', 'event_type', 'payload', 'headers', 'signature')}),
        (_('Processing'), {'fields': ('verified', 'processed', 'processed_at', 'error_message')}),
        (_('Metadata'), {'fields': ('created_at',)}),
    )

    def verified_display(self, obj):
        return format_html('<span style="color: {};">✓</span>' if obj.verified else '<span style="color: red;">✗</span>', 'green' if obj.verified else 'red')
    verified_display.short_description = _('Verified')

    def processed_display(self, obj):
        return format_html('<span style="color: {};">✓</span>' if obj.processed else '<span style="color: orange;">✗</span>', 'green' if obj.processed else 'orange')
    processed_display.short_description = _('Processed')

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')

    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False


# ============================================================================
# PAYMENT RECONCILIATION ADMIN
# ============================================================================

@admin.register(PaymentReconciliation)
class PaymentReconciliationAdmin(ModelAdmin):
    list_display = ('id', 'payment_display', 'user_display', 'external_reference_short', 'status_display', 'reconciled_at_display')
    list_filter = ('status', ('payment', admin.RelatedOnlyFieldListFilter))
    search_fields = ('external_reference', 'payment__reference', 'discrepancy_reason')
    ordering = ('-reconciled_at',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'payment', 'user', 'group')
    actions = ['mark_matched', 'mark_failed']

    def payment_display(self, obj):
        url = reverse('admin:payments_payment_change', args=[obj.payment.id])
        return format_html('<a href="{}">#{}</a>', url, obj.payment.id)
    payment_display.short_description = _('Payment')

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')

    def external_reference_short(self, obj):
        return obj.external_reference[:30] + '...' if obj.external_reference and len(obj.external_reference) > 30 else obj.external_reference
    external_reference_short.short_description = _('External Ref')

    def status_display(self, obj):
        colors = {'pending': 'orange', 'matched': 'green', 'failed': 'red', 'discrepancy': 'purple'}
        color = colors.get(obj.status, 'gray')
        return format_html('<span style="color: {};">{}</span>', color, obj.get_status_display())
    status_display.short_description = _('Status')

    def reconciled_at_display(self, obj):
        return obj.reconciled_at.strftime('%Y-%m-%d %H:%M')
    reconciled_at_display.short_description = _('Reconciled')

    def mark_matched(self, request, queryset):
        count = 0
        for obj in queryset:
            obj.status = 'matched'
            obj.save(update_fields=['status'])
            count += 1
        self.message_user(request, f'Marked {count} reconciliation(s) as matched.')
    mark_matched.short_description = _('Mark selected as matched')

    def mark_failed(self, request, queryset):
        count = 0
        for obj in queryset:
            obj.status = 'failed'
            obj.save(update_fields=['status'])
            count += 1
        self.message_user(request, f'Marked {count} reconciliation(s) as failed.')
    mark_failed.short_description = _('Mark selected as failed')


# ============================================================================
# PAYMENT DISPUTE ADMIN
# ============================================================================

@admin.register(PaymentDispute)
class PaymentDisputeAdmin(ModelAdmin):
    list_display = ('id', 'payment_display', 'user_display', 'amount_display', 'reason_display', 'status_display', 'created_at_display')
    list_filter = ('status', 'reason', ('payment', admin.RelatedOnlyFieldListFilter))
    search_fields = ('description', 'resolution', 'payment__reference')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'payment', 'user', 'created_by')
    actions = ['resolve_disputes', 'reject_disputes']

    def payment_display(self, obj):
        url = reverse('admin:payments_payment_change', args=[obj.payment.id])
        return format_html('<a href="{}">#{}</a>', url, obj.payment.id)
    payment_display.short_description = _('Payment')

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')

    def amount_display(self, obj):
        return format_currency(obj.amount)
    amount_display.short_description = _('Amount')

    def reason_display(self, obj):
        return obj.get_reason_display()
    reason_display.short_description = _('Reason')

    def status_display(self, obj):
        colors = {'pending': 'orange', 'investigating': 'blue', 'resolved': 'green', 'rejected': 'red'}
        color = colors.get(obj.status, 'gray')
        return format_html('<span style="color: {};">{}</span>', color, obj.get_status_display())
    status_display.short_description = _('Status')

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')

    def resolve_disputes(self, request, queryset):
        count = 0
        for obj in queryset.filter(status='pending'):
            obj.status = 'resolved'
            obj.resolved_at = timezone.now()
            obj.resolution = 'Resolved via admin'
            obj.save()
            count += 1
        self.message_user(request, f'Resolved {count} dispute(s).')
    resolve_disputes.short_description = _('Resolve selected disputes')

    def reject_disputes(self, request, queryset):
        count = 0
        for obj in queryset.filter(status='pending'):
            obj.status = 'rejected'
            obj.resolved_at = timezone.now()
            obj.resolution = 'Rejected via admin'
            obj.save()
            count += 1
        self.message_user(request, f'Rejected {count} dispute(s).')
    reject_disputes.short_description = _('Reject selected disputes')


# ============================================================================
# SETTLEMENT ADMIN
# ============================================================================

@admin.register(Settlement)
class SettlementAdmin(ModelAdmin):
    list_display = ('id', 'reference', 'type_display', 'amount_display', 'status_display', 'settlement_date_display')
    list_filter = ('status', 'type', 'gateway')
    search_fields = ('reference', 'reference_number', 'notes')
    ordering = ('-settlement_date',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'created_by')
    actions = ['mark_completed', 'mark_failed']

    def type_display(self, obj):
        return obj.get_type_display()
    type_display.short_description = _('Type')

    def amount_display(self, obj):
        return format_currency(obj.amount)
    amount_display.short_description = _('Amount')

    def status_display(self, obj):
        return obj.get_status_display()
    status_display.short_description = _('Status')

    def settlement_date_display(self, obj):
        return obj.settlement_date.strftime('%Y-%m-%d %H:%M')
    settlement_date_display.short_description = _('Settlement Date')

    def mark_completed(self, request, queryset):
        count = queryset.update(status='completed')
        self.message_user(request, f'Marked {count} settlement(s) as completed.')
    mark_completed.short_description = _('Mark selected as completed')

    def mark_failed(self, request, queryset):
        count = queryset.update(status='failed')
        self.message_user(request, f'Marked {count} settlement(s) as failed.')
    mark_failed.short_description = _('Mark selected as failed')


# ============================================================================
# PAYMENT METHOD ADMIN
# ============================================================================

@admin.register(PaymentMethod)
class PaymentMethodAdmin(ModelAdmin):
    list_display = ('id', 'user_display', 'method_type_display', 'account_identifier', 'is_default_display', 'is_active_display', 'created_at_display')
    list_filter = ('method_type', 'is_default', 'is_active', ('user', admin.RelatedOnlyFieldListFilter))
    search_fields = ('user__email', 'account_identifier', 'provider', 'token')
    ordering = ('-is_default', '-created_at')
    readonly_fields = ('id', 'created_at', 'updated_at', 'deleted_at')
    actions = ['make_default', 'activate', 'deactivate']

    def user_display(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')

    def method_type_display(self, obj):
        return obj.get_method_type_display()
    method_type_display.short_description = _('Method')

    def is_default_display(self, obj):
        return format_html('<span style="color: green; font-weight: bold;">✓</span>' if obj.is_default else '')
    is_default_display.short_description = _('Default')

    def is_active_display(self, obj):
        return format_html('<span style="color: green;">✓</span>' if obj.is_active else '<span style="color: red;">✗</span>')
    is_active_display.short_description = _('Active')

    def created_at_display(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')

    def make_default(self, request, queryset):
        for user in queryset.values_list('user', flat=True).distinct():
            PaymentMethod.objects.filter(user=user, is_default=True).update(is_default=False)
        count = queryset.update(is_default=True)
        self.message_user(request, f'Set {count} payment method(s) as default.')
    make_default.short_description = _('Make default')

    def activate(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'Activated {count} payment method(s).')
    activate.short_description = _('Activate selected')

    def deactivate(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'Deactivated {count} payment method(s).')
    deactivate.short_description = _('Deactivate selected')


# ============================================================================
# PAYMENT AUDIT ADMIN
# ============================================================================

@admin.register(PaymentAudit)
class PaymentAuditAdmin(ModelAdmin):
    list_display = ('id', 'payment_display', 'action', 'user_display', 'old_status', 'new_status', 'timestamp_display')
    list_filter = ('action', ('payment', admin.RelatedOnlyFieldListFilter))
    search_fields = ('action', 'details', 'payment__reference')
    ordering = ('-timestamp',)
    readonly_fields = ('id', 'payment', 'user', 'action', 'old_status', 'new_status', 'details', 'timestamp', 'ip_address')
    fieldsets = (
        (_('Audit Entry'), {'fields': ('payment', 'user', 'action', 'timestamp')}),
        (_('Status Change'), {'fields': ('old_status', 'new_status')}),
        (_('Details'), {'fields': ('details', 'ip_address')}),
    )

    def payment_display(self, obj):
        url = reverse('admin:payments_payment_change', args=[obj.payment.id])
        return format_html('<a href="{}">#{}</a>', url, obj.payment.id)
    payment_display.short_description = _('Payment')

    def user_display(self, obj):
        if obj.user:
            url = reverse('admin:users_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.email)
        return 'System'
    user_display.short_description = _('User')

    def timestamp_display(self, obj):
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')

    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False