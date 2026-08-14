"""
Serializers for the payments app.

This module provides comprehensive serializers for all payment models:
- Payment serializers (list, detail, create, update)
- Payout serializers (list, detail, create, update)
- PaymentTransaction serializers
- PaymentGatewayLog serializers
- PaymentWebhookLog serializers
- PaymentReconciliation serializers
- PaymentDispute serializers
- Settlement serializers
- PaymentMethod serializers
- PaymentAudit serializers
- Statistics and summary serializers
- Webhook payload serializers

All serializers include full validation, computed fields, nested relationships,
and proper error handling for all payment operations.
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
from apps.contributions.models import Contribution
from apps.contributions.serializers import ContributionListSerializer
from apps.common.constants import PaymentStatus, PaymentMethod, PayoutStatus
from apps.common.utils import format_currency, calculate_platform_fee
from apps.common.exceptions import ValidationError, ConflictError, BadRequestError

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

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# PAYMENT SERIALIZERS
# ============================================================================

class PaymentBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer with common fields for Payment model.
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    gateway_display = serializers.CharField(source='get_gateway_display', read_only=True)
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()
    amount_formatted = serializers.SerializerMethodField()
    platform_fee_formatted = serializers.SerializerMethodField()
    gateway_fee_formatted = serializers.SerializerMethodField()
    total_fee_formatted = serializers.SerializerMethodField()
    net_amount_formatted = serializers.SerializerMethodField()
    is_pending = serializers.BooleanField(read_only=True)
    is_completed = serializers.BooleanField(read_only=True)
    is_failed = serializers.BooleanField(read_only=True)
    is_refunded = serializers.BooleanField(read_only=True)
    is_cancelled = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    can_be_cancelled = serializers.BooleanField(read_only=True)
    can_be_refunded = serializers.BooleanField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'user', 'user_name', 'user_email', 'group', 'group_name',
            'contribution', 'amount', 'amount_formatted', 'payment_method', 'method_display',
            'gateway', 'gateway_display', 'reference', 'status', 'status_display',
            'platform_fee', 'platform_fee_formatted', 'gateway_fee', 'gateway_fee_formatted',
            'total_fee', 'total_fee_formatted', 'net_amount', 'net_amount_formatted',
            'paid_at', 'expires_at', 'webhook_received', 'webhook_processed_at',
            'retry_count', 'error_message', 'metadata',
            'refund_reason', 'refunded_at',
            'created_by', 'created_at', 'updated_at', 'deleted_at',
            'is_pending', 'is_completed', 'is_failed', 'is_refunded',
            'is_cancelled', 'is_expired', 'can_be_cancelled', 'can_be_refunded',
        ]
        read_only_fields = [
            'id', 'status_display', 'method_display', 'gateway_display',
            'user_name', 'user_email', 'group_name',
            'amount_formatted', 'platform_fee_formatted', 'gateway_fee_formatted',
            'total_fee_formatted', 'net_amount_formatted',
            'created_at', 'updated_at', 'deleted_at',
            'is_pending', 'is_completed', 'is_failed', 'is_refunded',
            'is_cancelled', 'is_expired', 'can_be_cancelled', 'can_be_refunded',
            'webhook_received', 'webhook_processed_at', 'retry_count',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_group_name(self, obj) -> str:
        return obj.group.name if obj.group else ''

    def get_amount_formatted(self, obj) -> str:
        return format_currency(obj.amount)

    def get_platform_fee_formatted(self, obj) -> str:
        return format_currency(obj.platform_fee)

    def get_gateway_fee_formatted(self, obj) -> str:
        return format_currency(obj.gateway_fee)

    def get_total_fee_formatted(self, obj) -> str:
        return format_currency(obj.total_fee)

    def get_net_amount_formatted(self, obj) -> str:
        return format_currency(obj.net_amount)


class PaymentListSerializer(PaymentBaseSerializer):
    """
    Lightweight serializer for listing payments.
    """
    class Meta(PaymentBaseSerializer.Meta):
        fields = [
            'id', 'reference', 'user_name', 'user_email', 'group_name',
            'amount', 'amount_formatted', 'payment_method', 'method_display',
            'status', 'status_display', 'paid_at', 'created_at',
            'is_pending', 'is_completed', 'is_failed', 'is_refunded',
        ]


class PaymentDetailSerializer(PaymentBaseSerializer):
    """
    Detailed serializer with nested relationships.
    """
    transactions = serializers.SerializerMethodField()
    gateway_logs = serializers.SerializerMethodField()
    reconciliations = serializers.SerializerMethodField()
    disputes = serializers.SerializerMethodField()
    user_detail = serializers.SerializerMethodField()
    group_detail = serializers.SerializerMethodField()
    contribution_detail = serializers.SerializerMethodField()

    class Meta(PaymentBaseSerializer.Meta):
        fields = PaymentBaseSerializer.Meta.fields + [
            'transactions', 'gateway_logs', 'reconciliations',
            'disputes', 'user_detail', 'group_detail', 'contribution_detail',
        ]

    def get_transactions(self, obj):
        transactions = obj.transactions.all().order_by('-created_at')
        return PaymentTransactionSerializer(transactions, many=True).data

    def get_gateway_logs(self, obj):
        logs = obj.gateway_logs.all().order_by('-created_at')[:20]
        return PaymentGatewayLogSerializer(logs, many=True).data

    def get_reconciliations(self, obj):
        recs = obj.reconciliations.all().order_by('-reconciled_at')
        return PaymentReconciliationSerializer(recs, many=True).data

    def get_disputes(self, obj):
        disputes = obj.disputes.all().order_by('-created_at')
        return PaymentDisputeSerializer(disputes, many=True).data

    def get_user_detail(self, obj):
        return UserBaseSerializer(obj.user).data

    def get_group_detail(self, obj):
        return GroupListSerializer(obj.group).data

    def get_contribution_detail(self, obj):
        if obj.contribution:
            return ContributionListSerializer(obj.contribution).data
        return None


class PaymentCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a new payment.
    """
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=True,
        help_text=_('User making the payment')
    )
    group = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.filter(deleted_at__isnull=True),
        required=True,
        help_text=_('Group the payment is for')
    )
    contribution = serializers.PrimaryKeyRelatedField(
        queryset=Contribution.objects.filter(deleted_at__isnull=True),
        required=False,
        help_text=_('Optional contribution this payment is linked to')
    )
    amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        min_value=0.01,
        required=True,
        help_text=_('Payment amount')
    )
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.CHOICES,
        default=PaymentMethod.CASH,
        required=False,
        help_text=_('Payment method used')
    )
    gateway = serializers.ChoiceField(
        choices=[
            ('chapa', 'Chapa'),
            ('telebirr', 'Telebirr'),
            ('bank_transfer', 'Bank Transfer'),
            ('manual', 'Manual'),
        ],
        default='manual',
        required=False,
        help_text=_('Payment gateway used')
    )

    class Meta:
        model = Payment
        fields = [
            'user', 'group', 'contribution', 'amount',
            'payment_method', 'gateway', 'reference', 'metadata',
        ]
        extra_kwargs = {
            'reference': {'required': False, 'allow_blank': True},
            'metadata': {'required': False},
        }

    def validate(self, attrs):
        user = attrs.get('user')
        group = attrs.get('group')
        amount = attrs.get('amount')

        # Validate user is a member of the group
        from apps.groups.models import GroupMember
        if not GroupMember.objects.filter(group=group, user=user, is_active=True).exists():
            raise serializers.ValidationError(
                {'user': _('User is not a member of this group.')}
            )

        # Validate contribution if provided
        contribution = attrs.get('contribution')
        if contribution:
            if contribution.group != group:
                raise serializers.ValidationError(
                    {'contribution': _('Contribution does not belong to this group.')}
                )
            if contribution.user != user:
                raise serializers.ValidationError(
                    {'contribution': _('Contribution does not belong to this user.')}
                )
            if contribution.status not in ['pending', 'overdue']:
                raise serializers.ValidationError(
                    {'contribution': _('Contribution is already paid or cancelled.')}
                )

        # Validate amount
        if contribution and amount != contribution.total_amount_with_penalty:
            raise serializers.ValidationError(
                {'amount': _('Amount must match contribution total amount with penalty.')}
            )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        from apps.payments import process_payment

        user = validated_data['user']
        group = validated_data['group']
        amount = validated_data['amount']
        payment_method = validated_data.get('payment_method', PaymentMethod.CASH)
        gateway = validated_data.get('gateway', 'manual')
        contribution = validated_data.get('contribution')
        reference = validated_data.get('reference', '')
        metadata = validated_data.get('metadata', {})

        # Use helper to process payment
        result = process_payment(
            user=user,
            group=group,
            amount=amount,
            payment_method=payment_method,
            gateway=gateway,
            contribution_id=contribution.id if contribution else None,
        )

        payment = result['payment']
        if reference:
            payment.reference = reference
        if metadata:
            payment.metadata.update(metadata)
        payment.save(update_fields=['reference', 'metadata'])

        # Mark contribution as paid if completed
        if payment.status == PaymentStatus.COMPLETED and contribution:
            contribution.mark_as_paid(payment_method=payment_method, reference=payment.reference)

        logger.info(f'Payment {payment.id} created by {user.id}')
        return payment


class PaymentUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a payment (status changes, etc.).
    """
    status = serializers.ChoiceField(
        choices=PaymentStatus.CHOICES,
        required=False,
        help_text=_('New payment status')
    )

    class Meta:
        model = Payment
        fields = [
            'status', 'payment_method', 'gateway', 'reference',
            'error_message', 'metadata',
        ]
        extra_kwargs = {
            'payment_method': {'required': False},
            'gateway': {'required': False},
            'reference': {'required': False, 'allow_blank': True},
            'error_message': {'required': False, 'allow_blank': True},
            'metadata': {'required': False},
        }

    def validate(self, attrs):
        instance = self.instance

        # Validate status transition
        if 'status' in attrs and attrs['status'] != instance.status:
            from .models import Payment
            allowed_transitions = {
                PaymentStatus.PENDING: [PaymentStatus.PROCESSING, PaymentStatus.COMPLETED,
                                       PaymentStatus.FAILED, PaymentStatus.CANCELLED,
                                       PaymentStatus.EXPIRED],
                PaymentStatus.PROCESSING: [PaymentStatus.COMPLETED, PaymentStatus.FAILED,
                                          PaymentStatus.CANCELLED],
                PaymentStatus.COMPLETED: [PaymentStatus.REFUNDED],
                PaymentStatus.FAILED: [PaymentStatus.PENDING],  # retry
            }
            allowed = allowed_transitions.get(instance.status, [])
            if attrs['status'] not in allowed:
                raise serializers.ValidationError(
                    {'status': _('Invalid status transition from {old} to {new}.').format(
                        old=instance.get_status_display(),
                        new=dict(PaymentStatus.CHOICES).get(attrs['status'], attrs['status'])
                    )}
                )

        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        old_status = instance.status
        instance = super().update(instance, validated_data)

        # Handle specific status changes
        if 'status' in validated_data and validated_data['status'] != old_status:
            if validated_data['status'] == PaymentStatus.COMPLETED:
                instance.complete()
            elif validated_data['status'] == PaymentStatus.FAILED:
                instance.fail(validated_data.get('error_message'))
            elif validated_data['status'] == PaymentStatus.CANCELLED:
                instance.cancel()
            elif validated_data['status'] == PaymentStatus.REFUNDED:
                instance.refund()
            elif validated_data['status'] == PaymentStatus.EXPIRED:
                instance.expire()

        return instance


# ============================================================================
# PAYMENT TRANSACTION SERIALIZER
# ============================================================================

class PaymentTransactionSerializer(serializers.ModelSerializer):
    """
    Serializer for PaymentTransaction model.
    """
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()
    amount_formatted = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PaymentTransaction
        fields = [
            'id', 'payment', 'user', 'user_name', 'user_email',
            'group', 'group_name', 'amount', 'amount_formatted',
            'gateway', 'transaction_id', 'status', 'status_display',
            'request_payload', 'response_payload', 'error_message',
            'initiated_at', 'completed_at', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user_name', 'user_email', 'group_name',
            'amount_formatted', 'status_display',
            'created_at', 'updated_at',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_group_name(self, obj) -> str:
        return obj.group.name if obj.group else ''

    def get_amount_formatted(self, obj) -> str:
        return format_currency(obj.amount)


# ============================================================================
# PAYOUT SERIALIZERS
# ============================================================================

class PayoutBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer with common fields for Payout model.
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    method_display = serializers.CharField(source='get_payout_method_display', read_only=True)
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()
    amount_formatted = serializers.SerializerMethodField()
    platform_fee_formatted = serializers.SerializerMethodField()
    gateway_fee_formatted = serializers.SerializerMethodField()
    total_fee_formatted = serializers.SerializerMethodField()
    net_amount_formatted = serializers.SerializerMethodField()
    is_pending = serializers.BooleanField(read_only=True)
    is_completed = serializers.BooleanField(read_only=True)
    is_failed = serializers.BooleanField(read_only=True)
    is_cancelled = serializers.BooleanField(read_only=True)

    class Meta:
        model = Payout
        fields = [
            'id', 'user', 'user_name', 'user_email', 'group', 'group_name',
            'winner_history', 'amount', 'amount_formatted',
            'payout_method', 'method_display', 'reference', 'status', 'status_display',
            'platform_fee', 'platform_fee_formatted', 'gateway_fee', 'gateway_fee_formatted',
            'total_fee', 'total_fee_formatted', 'net_amount', 'net_amount_formatted',
            'paid_at', 'reference_number', 'notes',
            'created_by', 'created_at', 'updated_at', 'deleted_at',
            'is_pending', 'is_completed', 'is_failed', 'is_cancelled',
        ]
        read_only_fields = [
            'id', 'status_display', 'method_display',
            'user_name', 'user_email', 'group_name',
            'amount_formatted', 'platform_fee_formatted', 'gateway_fee_formatted',
            'total_fee_formatted', 'net_amount_formatted',
            'created_at', 'updated_at', 'deleted_at',
            'is_pending', 'is_completed', 'is_failed', 'is_cancelled',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_group_name(self, obj) -> str:
        return obj.group.name if obj.group else ''

    def get_amount_formatted(self, obj) -> str:
        return format_currency(obj.amount)

    def get_platform_fee_formatted(self, obj) -> str:
        return format_currency(obj.platform_fee)

    def get_gateway_fee_formatted(self, obj) -> str:
        return format_currency(obj.gateway_fee)

    def get_total_fee_formatted(self, obj) -> str:
        return format_currency(obj.total_fee)

    def get_net_amount_formatted(self, obj) -> str:
        return format_currency(obj.net_amount)


class PayoutListSerializer(PayoutBaseSerializer):
    """
    Lightweight serializer for listing payouts.
    """
    class Meta(PayoutBaseSerializer.Meta):
        fields = [
            'id', 'reference', 'user_name', 'user_email', 'group_name',
            'amount', 'amount_formatted', 'payout_method', 'method_display',
            'status', 'status_display', 'paid_at', 'created_at',
            'is_pending', 'is_completed', 'is_failed',
        ]


class PayoutDetailSerializer(PayoutBaseSerializer):
    """
    Detailed serializer with nested relationships.
    """
    user_detail = serializers.SerializerMethodField()
    group_detail = serializers.SerializerMethodField()

    class Meta(PayoutBaseSerializer.Meta):
        fields = PayoutBaseSerializer.Meta.fields + [
            'user_detail', 'group_detail',
        ]

    def get_user_detail(self, obj):
        return UserBaseSerializer(obj.user).data

    def get_group_detail(self, obj):
        return GroupListSerializer(obj.group).data


class PayoutCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a new payout.
    """
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=True,
        help_text=_('User receiving the payout')
    )
    group = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.filter(deleted_at__isnull=True),
        required=True,
        help_text=_('Group the payout is from')
    )
    winner_history = serializers.PrimaryKeyRelatedField(
        queryset='groups.GroupWinnerHistory'.split('.')[-1] if hasattr('groups', 'GroupWinnerHistory') else None,
        required=False,
        help_text=_('Winner history entry this payout is for')
    )
    amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        min_value=0.01,
        required=True,
        help_text=_('Payout amount')
    )
    payout_method = serializers.ChoiceField(
        choices=[
            ('bank_transfer', 'Bank Transfer'),
            ('telebirr', 'Telebirr'),
            ('cash', 'Cash'),
            ('mobile_money', 'Mobile Money'),
            ('cheque', 'Cheque'),
        ],
        default='bank_transfer',
        required=False,
        help_text=_('Payout method used')
    )

    class Meta:
        model = Payout
        fields = [
            'user', 'group', 'winner_history', 'amount',
            'payout_method', 'notes',
        ]
        extra_kwargs = {
            'notes': {'required': False, 'allow_blank': True},
        }

    def validate(self, attrs):
        user = attrs.get('user')
        group = attrs.get('group')
        amount = attrs.get('amount')

        # Validate user is a member of the group
        from apps.groups.models import GroupMember
        if not GroupMember.objects.filter(group=group, user=user, is_active=True).exists():
            raise serializers.ValidationError(
                {'user': _('User is not a member of this group.')}
            )

        # Validate winner history if provided
        winner_history = attrs.get('winner_history')
        if winner_history:
            if winner_history.group != group:
                raise serializers.ValidationError(
                    {'winner_history': _('Winner history does not belong to this group.')}
                )
            if winner_history.user != user:
                raise serializers.ValidationError(
                    {'winner_history': _('Winner history does not belong to this user.')}
                )
            if winner_history.paid_out:
                raise serializers.ValidationError(
                    {'winner_history': _('Winner already paid out.')}
                )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        from apps.payments import process_payout

        user = validated_data['user']
        group = validated_data['group']
        amount = validated_data['amount']
        payout_method = validated_data.get('payout_method', 'bank_transfer')
        winner_history = validated_data.get('winner_history')
        notes = validated_data.get('notes', '')

        # Use helper to process payout
        result = process_payout(
            user=user,
            group=group,
            amount=amount,
            payout_method=payout_method,
            winner_history_id=winner_history.id if winner_history else None,
        )

        payout = result['payout']
        if notes:
            payout.notes = notes
            payout.save(update_fields=['notes'])

        logger.info(f'Payout {payout.id} created by {self.context.get("request").user}')
        return payout


class PayoutUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a payout (status changes, etc.).
    """
    status = serializers.ChoiceField(
        choices=PayoutStatus.CHOICES,
        required=False,
        help_text=_('New payout status')
    )

    class Meta:
        model = Payout
        fields = [
            'status', 'payout_method', 'reference_number', 'notes',
        ]
        extra_kwargs = {
            'payout_method': {'required': False},
            'reference_number': {'required': False, 'allow_blank': True},
            'notes': {'required': False, 'allow_blank': True},
        }

    def validate(self, attrs):
        instance = self.instance

        # Validate status transition
        if 'status' in attrs and attrs['status'] != instance.status:
            allowed_transitions = {
                PayoutStatus.PENDING: [PayoutStatus.PROCESSING, PayoutStatus.COMPLETED,
                                      PayoutStatus.FAILED, PayoutStatus.CANCELLED,
                                      PayoutStatus.ON_HOLD],
                PayoutStatus.PROCESSING: [PayoutStatus.COMPLETED, PayoutStatus.FAILED,
                                         PayoutStatus.CANCELLED, PayoutStatus.ON_HOLD],
                PayoutStatus.COMPLETED: [],  # Cannot change once completed
                PayoutStatus.FAILED: [PayoutStatus.PENDING],  # retry
                PayoutStatus.ON_HOLD: [PayoutStatus.PENDING, PayoutStatus.PROCESSING,
                                      PayoutStatus.CANCELLED],
            }
            allowed = allowed_transitions.get(instance.status, [])
            if attrs['status'] not in allowed:
                raise serializers.ValidationError(
                    {'status': _('Invalid status transition from {old} to {new}.').format(
                        old=instance.get_status_display(),
                        new=dict(PayoutStatus.CHOICES).get(attrs['status'], attrs['status'])
                    )}
                )

        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        old_status = instance.status
        instance = super().update(instance, validated_data)

        if 'status' in validated_data and validated_data['status'] != old_status:
            if validated_data['status'] == PayoutStatus.COMPLETED:
                instance.complete(validated_data.get('reference_number'))
            elif validated_data['status'] == PayoutStatus.FAILED:
                instance.fail(validated_data.get('notes', 'Failed'))
            elif validated_data['status'] == PayoutStatus.CANCELLED:
                instance.cancel(validated_data.get('notes', 'Cancelled'))
            elif validated_data['status'] == PayoutStatus.ON_HOLD:
                instance.put_on_hold(validated_data.get('notes', 'On hold'))

        return instance


# ============================================================================
# GATEWAY LOG SERIALIZER
# ============================================================================

class PaymentGatewayLogSerializer(serializers.ModelSerializer):
    """
    Serializer for PaymentGatewayLog model.
    """
    class Meta:
        model = PaymentGatewayLog
        fields = [
            'id', 'payment', 'gateway', 'endpoint', 'method',
            'request_headers', 'request_body', 'response_status',
            'response_headers', 'response_body', 'error_message',
            'duration_ms', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


# ============================================================================
# WEBHOOK LOG SERIALIZER
# ============================================================================

class PaymentWebhookLogSerializer(serializers.ModelSerializer):
    """
    Serializer for PaymentWebhookLog model.
    """
    class Meta:
        model = PaymentWebhookLog
        fields = [
            'id', 'gateway', 'event_type', 'payload', 'headers',
            'signature', 'verified', 'processed', 'processed_at',
            'error_message', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


# ============================================================================
# RECONCILIATION SERIALIZER
# ============================================================================

class PaymentReconciliationSerializer(serializers.ModelSerializer):
    """
    Serializer for PaymentReconciliation model.
    """
    user_name = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PaymentReconciliation
        fields = [
            'id', 'payment', 'user', 'user_name', 'group', 'group_name',
            'external_reference', 'external_status', 'external_data',
            'status', 'status_display', 'discrepancy_reason',
            'reconciled_at', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user_name', 'group_name', 'status_display',
            'created_at', 'updated_at',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_group_name(self, obj) -> str:
        return obj.group.name if obj.group else ''


# ============================================================================
# DISPUTE SERIALIZER
# ============================================================================

class PaymentDisputeSerializer(serializers.ModelSerializer):
    """
    Serializer for PaymentDispute model.
    """
    user_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    amount_formatted = serializers.SerializerMethodField()

    class Meta:
        model = PaymentDispute
        fields = [
            'id', 'payment', 'user', 'user_name', 'amount', 'amount_formatted',
            'reason', 'reason_display', 'description', 'status', 'status_display',
            'resolution', 'resolved_at', 'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user_name', 'amount_formatted', 'reason_display',
            'status_display', 'created_at', 'updated_at',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_amount_formatted(self, obj) -> str:
        return format_currency(obj.amount)


# ============================================================================
# SETTLEMENT SERIALIZER
# ============================================================================

class SettlementSerializer(serializers.ModelSerializer):
    """
    Serializer for Settlement model.
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    amount_formatted = serializers.SerializerMethodField()
    fee_formatted = serializers.SerializerMethodField()
    net_amount_formatted = serializers.SerializerMethodField()

    class Meta:
        model = Settlement
        fields = [
            'id', 'reference', 'type', 'type_display', 'amount', 'amount_formatted',
            'fee', 'fee_formatted', 'net_amount', 'net_amount_formatted',
            'status', 'status_display', 'gateway', 'reference_number',
            'settlement_date', 'notes', 'created_by',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'status_display', 'type_display', 'amount_formatted',
            'fee_formatted', 'net_amount_formatted', 'created_at', 'updated_at',
        ]

    def get_amount_formatted(self, obj) -> str:
        return format_currency(obj.amount)

    def get_fee_formatted(self, obj) -> str:
        return format_currency(obj.fee)

    def get_net_amount_formatted(self, obj) -> str:
        return format_currency(obj.net_amount)


# ============================================================================
# PAYMENT METHOD SERIALIZER
# ============================================================================

class PaymentMethodSerializer(serializers.ModelSerializer):
    """
    Serializer for PaymentMethod model.
    """
    method_display = serializers.CharField(source='get_method_type_display', read_only=True)

    class Meta:
        model = PaymentMethod
        fields = [
            'id', 'user', 'method_type', 'method_display', 'provider',
            'account_identifier', 'account_name', 'is_default', 'is_active',
            'token', 'expires_at', 'metadata', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ============================================================================
# PAYMENT AUDIT SERIALIZER
# ============================================================================

class PaymentAuditSerializer(serializers.ModelSerializer):
    """
    Serializer for PaymentAudit model.
    """
    user_name = serializers.SerializerMethodField()
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = PaymentAudit
        fields = [
            'id', 'payment', 'user', 'user_name', 'action', 'action_display',
            'old_status', 'new_status', 'details', 'timestamp', 'ip_address',
        ]
        read_only_fields = [
            'id', 'user_name', 'action_display', 'timestamp', 'ip_address',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else 'System'


# ============================================================================
# STATISTICS SERIALIZERS
# ============================================================================

class PaymentStatisticsSerializer(serializers.Serializer):
    """
    Serializer for payment statistics.
    """
    total_payments = serializers.IntegerField()
    completed = serializers.IntegerField()
    pending = serializers.IntegerField()
    failed = serializers.IntegerField()
    refunded = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_fees = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_net = serializers.DecimalField(max_digits=15, decimal_places=2)


class PayoutStatisticsSerializer(serializers.Serializer):
    """
    Serializer for payout statistics.
    """
    total_payouts = serializers.IntegerField()
    completed = serializers.IntegerField()
    pending = serializers.IntegerField()
    failed = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_fees = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_net = serializers.DecimalField(max_digits=15, decimal_places=2)


# ============================================================================
# WEBHOOK PAYLOAD SERIALIZER
# ============================================================================

class WebhookPayloadSerializer(serializers.Serializer):
    """
    Serializer for validating webhook payloads.
    """
    event = serializers.CharField(required=True)
    data = serializers.JSONField(required=True)
    timestamp = serializers.DateTimeField(required=True)
    signature = serializers.CharField(required=False, allow_blank=True)

    def validate_event(self, value):
        allowed_events = [
            'payment.created', 'payment.updated', 'payment.completed',
            'payment.failed', 'payment.refunded', 'payment.reversed',
            'payout.created', 'payout.completed', 'payout.failed',
            'webhook.test',
        ]
        if value not in allowed_events:
            raise serializers.ValidationError(_('Unsupported event type.'))
        return value


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'PaymentBaseSerializer',
    'PaymentListSerializer',
    'PaymentDetailSerializer',
    'PaymentCreateSerializer',
    'PaymentUpdateSerializer',
    'PaymentTransactionSerializer',
    'PayoutBaseSerializer',
    'PayoutListSerializer',
    'PayoutDetailSerializer',
    'PayoutCreateSerializer',
    'PayoutUpdateSerializer',
    'PaymentGatewayLogSerializer',
    'PaymentWebhookLogSerializer',
    'PaymentReconciliationSerializer',
    'PaymentDisputeSerializer',
    'SettlementSerializer',
    'PaymentMethodSerializer',
    'PaymentAuditSerializer',
    'PaymentStatisticsSerializer',
    'PayoutStatisticsSerializer',
    'WebhookPayloadSerializer',
]