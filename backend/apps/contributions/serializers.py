"""
Serializers for the contributions app.

This module provides comprehensive serializers for all contribution models:
- Contribution serializers (list, detail, create, update)
- ContributionPayment serializers (list, create, update)
- ContributionReminder serializers (list, create)
- ContributionAudit serializers (list, detail)
- Statistics and summary serializers
- Bulk operation serializers

All serializers include full validation, computed fields, nested relationships,
and proper error handling for all contribution operations.
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
from apps.common.constants import (
    ContributionStatus,
    ContributionType,
    PaymentStatus,
    PaymentMethod,
)
from apps.common.utils import format_currency, calculate_platform_fee
from apps.common.exceptions import (
    ValidationError,
    ConflictError,
    BadRequestError,
    NotFoundError,
)

from .models import (
    Contribution,
    ContributionPayment,
    ContributionReminder,
    ContributionAudit,
)
from .tasks import process_contribution_payments, update_contribution_stats

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# CONTRIBUTION SERIALIZERS
# ============================================================================

class ContributionBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer with common fields for Contribution model.
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    type_display = serializers.CharField(source='get_contribution_type_display', read_only=True)
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()
    amount_formatted = serializers.SerializerMethodField()
    penalty_amount_formatted = serializers.SerializerMethodField()
    waived_amount_formatted = serializers.SerializerMethodField()
    total_amount_formatted = serializers.SerializerMethodField()
    days_overdue = serializers.IntegerField(read_only=True)
    is_paid = serializers.BooleanField(read_only=True)
    is_pending = serializers.BooleanField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    is_cancelled = serializers.BooleanField(read_only=True)
    is_refunded = serializers.BooleanField(read_only=True)
    is_waived = serializers.BooleanField(read_only=True)
    can_be_paid = serializers.BooleanField(read_only=True)
    can_be_cancelled = serializers.BooleanField(read_only=True)
    can_be_refunded = serializers.BooleanField(read_only=True)
    can_be_waived = serializers.BooleanField(read_only=True)

    class Meta:
        model = Contribution
        fields = [
            'id', 'group', 'user', 'user_name', 'user_email', 'group_name',
            'amount', 'amount_formatted', 'round', 'due_date', 'paid_date',
            'status', 'status_display', 'contribution_type', 'type_display',
            'penalty_amount', 'penalty_amount_formatted',
            'waived_amount', 'waived_amount_formatted',
            'platform_fee', 'net_amount',
            'total_amount_formatted',
            'reference', 'notes', 'payment',
            'created_by', 'created_at', 'updated_at', 'deleted_at',
            'days_overdue', 'penalty_applied', 'reminder_count',
            'is_paid', 'is_pending', 'is_overdue', 'is_cancelled',
            'is_refunded', 'is_waived', 'is_deleted',
            'can_be_paid', 'can_be_cancelled', 'can_be_refunded', 'can_be_waived',
        ]
        read_only_fields = [
            'id', 'status_display', 'type_display', 'user_name', 'user_email',
            'group_name', 'amount_formatted', 'penalty_amount_formatted',
            'waived_amount_formatted', 'total_amount_formatted',
            'created_at', 'updated_at', 'deleted_at',
            'days_overdue', 'penalty_applied', 'reminder_count',
            'is_paid', 'is_pending', 'is_overdue', 'is_cancelled',
            'is_refunded', 'is_waived', 'is_deleted',
            'can_be_paid', 'can_be_cancelled', 'can_be_refunded', 'can_be_waived',
            'payment', 'created_by',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_group_name(self, obj) -> str:
        return obj.group.name if obj.group else ''

    def get_amount_formatted(self, obj) -> str:
        return format_currency(obj.amount)

    def get_penalty_amount_formatted(self, obj) -> str:
        return format_currency(obj.penalty_amount)

    def get_waived_amount_formatted(self, obj) -> str:
        return format_currency(obj.waived_amount)

    def get_total_amount_formatted(self, obj) -> str:
        return format_currency(obj.total_amount_with_penalty)


class ContributionListSerializer(ContributionBaseSerializer):
    """
    Lightweight serializer for listing contributions.
    """
    class Meta(ContributionBaseSerializer.Meta):
        fields = [
            'id', 'group_name', 'user_name', 'user_email',
            'amount', 'amount_formatted', 'round', 'due_date',
            'status', 'status_display', 'paid_date',
            'is_paid', 'is_pending', 'is_overdue',
            'days_overdue', 'can_be_paid',
        ]


class ContributionDetailSerializer(ContributionBaseSerializer):
    """
    Detailed serializer with nested relationships.
    """
    payment_detail = serializers.SerializerMethodField()
    reminders = serializers.SerializerMethodField()
    audit_trail = serializers.SerializerMethodField()
    status_history = serializers.SerializerMethodField()
    group_detail = serializers.SerializerMethodField()
    user_detail = serializers.SerializerMethodField()

    class Meta(ContributionBaseSerializer.Meta):
        fields = ContributionBaseSerializer.Meta.fields + [
            'payment_detail', 'reminders', 'audit_trail',
            'status_history', 'group_detail', 'user_detail',
        ]

    def get_payment_detail(self, obj):
        if obj.payment:
            from .serializers import ContributionPaymentSerializer
            return ContributionPaymentSerializer(obj.payment).data
        return None

    def get_reminders(self, obj):
        reminders = obj.reminders.all().order_by('-sent_at')[:10]
        from .serializers import ContributionReminderSerializer
        return ContributionReminderSerializer(reminders, many=True).data

    def get_audit_trail(self, obj):
        audits = obj.audits.all().order_by('-timestamp')[:20]
        from .serializers import ContributionAuditSerializer
        return ContributionAuditSerializer(audits, many=True).data

    def get_status_history(self, obj):
        return obj.status_history

    def get_group_detail(self, obj):
        return GroupListSerializer(obj.group).data

    def get_user_detail(self, obj):
        return UserBaseSerializer(obj.user).data


class ContributionCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a new contribution.
    """
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=True,
        help_text=_('User making the contribution')
    )
    group = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.filter(deleted_at__isnull=True),
        required=True,
        help_text=_('Group the contribution belongs to')
    )
    amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        min_value=0.01,
        required=True,
        help_text=_('Contribution amount')
    )
    round = serializers.IntegerField(
        min_value=0,
        required=True,
        help_text=_('Round number (0-indexed)')
    )
    due_date = serializers.DateTimeField(
        required=False,
        help_text=_('Due date (auto-calculated if not provided)')
    )
    contribution_type = serializers.ChoiceField(
        choices=ContributionType.CHOICES,
        default=ContributionType.REGULAR,
        required=False,
        help_text=_('Type of contribution')
    )

    class Meta:
        model = Contribution
        fields = [
            'user', 'group', 'amount', 'round', 'due_date',
            'contribution_type', 'reference', 'notes',
        ]
        extra_kwargs = {
            'reference': {'required': False, 'allow_blank': True},
            'notes': {'required': False, 'allow_blank': True},
        }

    def validate(self, attrs):
        user = attrs.get('user')
        group = attrs.get('group')
        round_number = attrs.get('round')
        amount = attrs.get('amount')
        contribution_type = attrs.get('contribution_type', ContributionType.REGULAR)

        # Validate user is a member of the group
        from apps.groups.models import GroupMember
        if not GroupMember.objects.filter(group=group, user=user, is_active=True).exists():
            raise serializers.ValidationError(
                {'user': _('User is not a member of this group.')}
            )

        # Validate contribution amount for regular contributions
        if contribution_type == ContributionType.REGULAR:
            if amount != group.contribution_amount:
                raise serializers.ValidationError(
                    {'amount': _('Contribution amount must match group\'s contribution amount.')}
                )

        # Check if contribution already exists for this user and round
        if Contribution.objects.filter(
            group=group,
            user=user,
            round=round_number,
            deleted_at__isnull=True
        ).exists():
            raise serializers.ValidationError(
                {'round': _('Contribution already exists for this user and round.')}
            )

        # Validate due date
        if 'due_date' in attrs:
            due_date = attrs['due_date']
            if due_date < timezone.now():
                raise serializers.ValidationError(
                    {'due_date': _('Due date cannot be in the past.')}
                )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        from apps.contributions import create_contribution

        user = validated_data['user']
        group = validated_data['group']
        round_number = validated_data['round']
        amount = validated_data['amount']
        due_date = validated_data.get('due_date')
        contribution_type = validated_data.get('contribution_type', ContributionType.REGULAR)
        reference = validated_data.get('reference', '')
        notes = validated_data.get('notes', '')
        created_by = self.context.get('request').user if self.context.get('request') else None

        contribution = create_contribution(
            user=user,
            group=group,
            round_number=round_number,
            amount=amount,
            due_date=due_date,
            created_by=created_by,
            contribution_type=contribution_type,
        )

        if reference:
            contribution.reference = reference
        if notes:
            contribution.notes = notes
        contribution.save(update_fields=['reference', 'notes'])

        logger.info(f'Contribution {contribution.id} created by {created_by}')

        return contribution


class ContributionUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a contribution.
    """
    status = serializers.ChoiceField(
        choices=ContributionStatus.CHOICES,
        required=False,
        help_text=_('New status')
    )

    class Meta:
        model = Contribution
        fields = [
            'amount', 'due_date', 'status', 'penalty_amount',
            'waived_amount', 'reference', 'notes',
        ]
        extra_kwargs = {
            'amount': {'required': False, 'min_value': 0.01},
            'due_date': {'required': False},
            'penalty_amount': {'required': False, 'min_value': 0},
            'waived_amount': {'required': False, 'min_value': 0},
            'reference': {'required': False, 'allow_blank': True},
            'notes': {'required': False, 'allow_blank': True},
        }

    def validate(self, attrs):
        instance = self.instance

        # Validate amount change
        if 'amount' in attrs and attrs['amount'] != instance.amount:
            if instance.status in [ContributionStatus.PAID, ContributionStatus.REFUNDED]:
                raise serializers.ValidationError(
                    {'amount': _('Cannot change amount of a paid or refunded contribution.')}
                )

        # Validate status transition
        if 'status' in attrs and attrs['status'] != instance.status:
            if not instance.validate_status_transition(attrs['status']):
                raise serializers.ValidationError(
                    {'status': _('Invalid status transition from {old} to {new}.').format(
                        old=instance.get_status_display(),
                        new=dict(ContributionStatus.CHOICES).get(attrs['status'], attrs['status'])
                    )}
                )

        # Validate due date
        if 'due_date' in attrs and attrs['due_date'] < timezone.now():
            raise serializers.ValidationError(
                {'due_date': _('Due date cannot be in the past.')}
            )

        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        old_status = instance.status
        instance = super().update(instance, validated_data)

        # If status changed to paid, handle payment processing
        if 'status' in validated_data and validated_data['status'] == ContributionStatus.PAID:
            if old_status != ContributionStatus.PAID:
                instance.mark_as_paid()

        # If status changed to overdue, mark as overdue
        if 'status' in validated_data and validated_data['status'] == ContributionStatus.OVERDUE:
            if old_status != ContributionStatus.OVERDUE:
                instance.mark_as_overdue()

        # If status changed to cancelled, cancel
        if 'status' in validated_data and validated_data['status'] == ContributionStatus.CANCELLED:
            if old_status != ContributionStatus.CANCELLED:
                instance.cancel()

        # If status changed to refunded, refund
        if 'status' in validated_data and validated_data['status'] == ContributionStatus.REFUNDED:
            if old_status != ContributionStatus.REFUNDED:
                instance.refund()

        logger.info(f'Contribution {instance.id} updated by {self.context.get("request").user}')

        return instance


# ============================================================================
# CONTRIBUTION PAYMENT SERIALIZERS
# ============================================================================

class ContributionPaymentBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer for ContributionPayment model.
    """
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()
    amount_formatted = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    method_display = serializers.CharField(source='get_payment_method_display', read_only=True)

    class Meta:
        model = ContributionPayment
        fields = [
            'id', 'contribution', 'user', 'user_name', 'user_email',
            'group', 'group_name', 'amount', 'amount_formatted',
            'payment_method', 'method_display', 'status', 'status_display',
            'reference', 'paid_at', 'created_at', 'updated_at',
            'is_completed', 'is_failed', 'is_pending', 'is_refunded',
        ]
        read_only_fields = [
            'id', 'user_name', 'user_email', 'group_name',
            'amount_formatted', 'status_display', 'method_display',
            'created_at', 'updated_at', 'paid_at',
            'is_completed', 'is_failed', 'is_pending', 'is_refunded',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''

    def get_group_name(self, obj) -> str:
        return obj.group.name if obj.group else ''

    def get_amount_formatted(self, obj) -> str:
        return format_currency(obj.amount)


class ContributionPaymentSerializer(ContributionPaymentBaseSerializer):
    """
    Full serializer for ContributionPayment.
    """
    contribution_detail = serializers.SerializerMethodField()

    class Meta(ContributionPaymentBaseSerializer.Meta):
        fields = ContributionPaymentBaseSerializer.Meta.fields + ['contribution_detail']

    def get_contribution_detail(self, obj):
        return ContributionListSerializer(obj.contribution).data


class ContributionPaymentCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a contribution payment.
    """
    contribution = serializers.PrimaryKeyRelatedField(
        queryset=Contribution.objects.filter(deleted_at__isnull=True),
        required=True,
        help_text=_('Contribution to pay')
    )
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.CHOICES,
        default=PaymentMethod.CASH,
        required=False,
        help_text=_('Payment method')
    )
    amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=False,
        help_text=_('Payment amount (auto-calculated if not provided)')
    )

    class Meta:
        model = ContributionPayment
        fields = [
            'contribution', 'payment_method', 'amount', 'reference',
        ]
        extra_kwargs = {
            'reference': {'required': False, 'allow_blank': True},
        }

    def validate(self, attrs):
        contribution = attrs.get('contribution')
        amount = attrs.get('amount')
        payment_method = attrs.get('payment_method', PaymentMethod.CASH)

        # Check if contribution can be paid
        if not contribution.can_be_paid:
            raise serializers.ValidationError(
                _('This contribution cannot be paid. Current status: {status}').format(
                    status=contribution.get_status_display()
                )
            )

        # Check if payment already exists
        if ContributionPayment.objects.filter(
            contribution=contribution,
            status=PaymentStatus.COMPLETED
        ).exists():
            raise serializers.ValidationError(
                _('Payment already exists for this contribution.')
            )

        # Set amount to total if not provided
        if amount is None:
            attrs['amount'] = contribution.total_amount_with_penalty
        elif amount < contribution.amount:
            raise serializers.ValidationError(
                {'amount': _('Payment amount cannot be less than contribution amount.')}
            )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        contribution = validated_data['contribution']
        amount = validated_data.get('amount', contribution.total_amount_with_penalty)
        payment_method = validated_data.get('payment_method', PaymentMethod.CASH)
        reference = validated_data.get('reference', '')

        # Create payment record
        payment = ContributionPayment.objects.create(
            contribution=contribution,
            user=contribution.user,
            group=contribution.group,
            amount=amount,
            payment_method=payment_method,
            reference=reference,
            status=PaymentStatus.COMPLETED,
            paid_at=timezone.now(),
        )

        # Mark contribution as paid
        contribution.mark_as_paid(
            payment_method=payment_method,
            reference=reference,
            paid_amount=amount,
        )

        logger.info(f'Payment {payment.id} created for contribution {contribution.id}')

        return payment


# ============================================================================
# CONTRIBUTION REMINDER SERIALIZERS
# ============================================================================

class ContributionReminderSerializer(serializers.ModelSerializer):
    """
    Serializer for ContributionReminder model.
    """
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    type_display = serializers.CharField(source='get_reminder_type_display', read_only=True)

    class Meta:
        model = ContributionReminder
        fields = [
            'id', 'contribution', 'user', 'user_name', 'user_email',
            'reminder_type', 'type_display', 'sent_at',
            'sent_successfully', 'error_message', 'created_at',
        ]
        read_only_fields = [
            'id', 'user_name', 'user_email', 'type_display',
            'sent_at', 'created_at',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''


class ContributionReminderCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a contribution reminder.
    """
    contribution = serializers.PrimaryKeyRelatedField(
        queryset=Contribution.objects.filter(deleted_at__isnull=True),
        required=True,
        help_text=_('Contribution to send reminder for')
    )
    reminder_type = serializers.ChoiceField(
        choices=['email', 'sms', 'push', 'in_app'],
        default='email',
        required=False,
        help_text=_('Type of reminder to send')
    )

    class Meta:
        model = ContributionReminder
        fields = ['contribution', 'reminder_type']

    def validate(self, attrs):
        contribution = attrs.get('contribution')

        if not contribution.can_be_paid:
            raise serializers.ValidationError(
                _('Contribution cannot be paid. No reminder needed.')
            )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        contribution = validated_data['contribution']
        reminder_type = validated_data.get('reminder_type', 'email')

        # Create reminder record
        reminder = ContributionReminder.objects.create(
            contribution=contribution,
            user=contribution.user,
            reminder_type=reminder_type,
            sent_at=timezone.now(),
            sent_successfully=True,
        )

        # Update reminder count
        contribution.reminder_count += 1
        contribution.save(update_fields=['reminder_count'])

        # Send actual reminder
        self._send_reminder(contribution, reminder_type)

        logger.info(f'Reminder {reminder.id} created for contribution {contribution.id}')

        return reminder

    def _send_reminder(self, contribution, reminder_type):
        """Send the actual reminder via the specified channel."""
        from apps.common.utils import send_email, send_sms
        from apps.notifications.models import Notification

        message = f"""
        Reminder: Your contribution of {format_currency(contribution.amount)} 
        for group "{contribution.group.name}" is due on {contribution.due_date.strftime('%Y-%m-%d')}.
        Please make your payment to avoid penalties.
        """

        if reminder_type == 'email':
            send_email(
                to_email=contribution.user.email,
                subject=f'Contribution Reminder - {contribution.group.name}',
                message=message,
                html_message=None,
            )
        elif reminder_type == 'sms':
            send_sms(
                phone=contribution.user.phone,
                message=message[:160],
            )
        elif reminder_type in ['push', 'in_app']:
            Notification.objects.create(
                user=contribution.user,
                notification_type='contribution_reminder',
                title='Contribution Reminder',
                message=message,
                contribution=contribution,
                group=contribution.group,
                is_read=False,
            )


# ============================================================================
# CONTRIBUTION AUDIT SERIALIZER
# ============================================================================

class ContributionAuditSerializer(serializers.ModelSerializer):
    """
    Serializer for ContributionAudit model.
    """
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = ContributionAudit
        fields = [
            'id', 'contribution', 'user', 'user_name', 'user_email',
            'action', 'action_display', 'old_status', 'new_status',
            'details', 'timestamp', 'ip_address',
        ]
        read_only_fields = [
            'id', 'user_name', 'user_email', 'action_display',
            'timestamp', 'ip_address',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else 'System'

    def get_user_email(self, obj) -> str:
        return obj.user.email if obj.user else ''


# ============================================================================
# STATISTICS SERIALIZERS
# ============================================================================

class ContributionStatsSerializer(serializers.Serializer):
    """
    Serializer for contribution statistics.
    """
    total_contributions = serializers.IntegerField()
    pending = serializers.IntegerField()
    paid = serializers.IntegerField()
    overdue = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    refunded = serializers.IntegerField()
    waived = serializers.IntegerField()
    partially_paid = serializers.IntegerField()
    total_paid_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    pending_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    overdue_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    completion_rate = serializers.FloatField()


class ContributionSummarySerializer(serializers.Serializer):
    """
    Serializer for contribution summary.
    """
    user_id = serializers.IntegerField()
    user_name = serializers.CharField()
    user_email = serializers.EmailField()
    total_contributions = serializers.IntegerField()
    paid = serializers.IntegerField()
    pending = serializers.IntegerField()
    overdue = serializers.IntegerField()
    total_paid_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    pending_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    status = serializers.CharField()
    completion_rate = serializers.FloatField()


class MemberContributionSummarySerializer(serializers.Serializer):
    """
    Serializer for member contribution summary.
    """
    user_id = serializers.IntegerField()
    user_name = serializers.CharField()
    user_email = serializers.EmailField()
    role = serializers.CharField()
    joined_at = serializers.DateTimeField()
    total_contributions = serializers.IntegerField()
    paid = serializers.IntegerField()
    pending = serializers.IntegerField()
    overdue = serializers.IntegerField()
    total_paid_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    status = serializers.CharField()


class GroupContributionSummarySerializer(serializers.Serializer):
    """
    Serializer for group contribution summary.
    """
    group_id = serializers.IntegerField()
    group_name = serializers.CharField()
    total_contributions = serializers.IntegerField()
    paid = serializers.IntegerField()
    pending = serializers.IntegerField()
    overdue = serializers.IntegerField()
    total_paid_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    pending_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    overdue_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    completion_rate = serializers.FloatField()


# ============================================================================
# BULK OPERATION SERIALIZERS
# ============================================================================

class BulkContributionCreateSerializer(serializers.Serializer):
    """
    Serializer for creating multiple contributions at once.
    """
    group_id = serializers.IntegerField(required=True)
    round_number = serializers.IntegerField(required=True, min_value=0)
    amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=False,
        help_text=_('Amount (auto-calculated from group if not provided)')
    )
    due_date = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        group_id = attrs.get('group_id')

        try:
            group = Group.objects.get(id=group_id, deleted_at__isnull=True)
        except Group.DoesNotExist:
            raise serializers.ValidationError(
                {'group_id': _('Group not found.')}
            )

        if not group.is_active:
            raise serializers.ValidationError(
                {'group_id': _('Group is not active.')}
            )

        if group.is_completed or group.is_cancelled:
            raise serializers.ValidationError(
                {'group_id': _('Group is completed or cancelled.')}
            )

        attrs['group'] = group

        # Auto-set amount from group if not provided
        if 'amount' not in attrs:
            attrs['amount'] = group.contribution_amount

        return attrs

    @transaction.atomic
    def save(self, **kwargs):
        group = self.validated_data['group']
        round_number = self.validated_data['round_number']
        amount = self.validated_data['amount']
        due_date = self.validated_data.get('due_date')
        created_by = self.context.get('request').user if self.context.get('request') else None

        from apps.contributions import create_bulk_contributions_for_group

        contributions = create_bulk_contributions_for_group(
            group=group,
            round_number=round_number,
            amount=amount,
            created_by=created_by,
        )

        return {
            'group_id': group.id,
            'group_name': group.name,
            'round_number': round_number,
            'contributions_created': len(contributions),
            'contributions': ContributionListSerializer(contributions, many=True).data,
        }


class BulkContributionStatusUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating status of multiple contributions.
    """
    contribution_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        help_text=_('List of contribution IDs to update')
    )
    status = serializers.ChoiceField(
        choices=ContributionStatus.CHOICES,
        required=True,
        help_text=_('New status to apply')
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=_('Reason for status change')
    )

    def validate(self, attrs):
        contribution_ids = attrs.get('contribution_ids')
        status = attrs.get('status')

        if not contribution_ids:
            raise serializers.ValidationError(
                {'contribution_ids': _('At least one contribution ID is required.')}
            )

        # Validate contributions exist
        contributions = Contribution.objects.filter(
            id__in=contribution_ids,
            deleted_at__isnull=True
        )

        if contributions.count() != len(contribution_ids):
            missing = set(contribution_ids) - set(contributions.values_list('id', flat=True))
            raise serializers.ValidationError(
                {'contribution_ids': _(f'Contributions not found: {missing}')}
            )

        # Validate status transition for each contribution
        for contribution in contributions:
            if not contribution.validate_status_transition(status):
                raise serializers.ValidationError(
                    {'status': _(f'Invalid status transition for contribution {contribution.id}')}
                )

        attrs['contributions'] = contributions
        return attrs

    @transaction.atomic
    def save(self, **kwargs):
        contributions = self.validated_data['contributions']
        status = self.validated_data['status']
        reason = self.validated_data.get('reason', '')

        processed = 0
        errors = []

        for contribution in contributions:
            try:
                if status == ContributionStatus.PAID:
                    contribution.mark_as_paid()
                elif status == ContributionStatus.OVERDUE:
                    contribution.mark_as_overdue()
                elif status == ContributionStatus.CANCELLED:
                    contribution.cancel(reason)
                elif status == ContributionStatus.REFUNDED:
                    contribution.refund(reason)
                elif status == ContributionStatus.WAIVED:
                    contribution.waive(contribution.amount, reason)
                processed += 1
            except Exception as e:
                errors.append(f'Contribution {contribution.id}: {str(e)}')

        return {
            'processed': processed,
            'errors': errors,
            'status': status,
        }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ContributionBaseSerializer',
    'ContributionListSerializer',
    'ContributionDetailSerializer',
    'ContributionCreateSerializer',
    'ContributionUpdateSerializer',
    'ContributionPaymentBaseSerializer',
    'ContributionPaymentSerializer',
    'ContributionPaymentCreateSerializer',
    'ContributionReminderSerializer',
    'ContributionReminderCreateSerializer',
    'ContributionAuditSerializer',
    'ContributionStatsSerializer',
    'ContributionSummarySerializer',
    'MemberContributionSummarySerializer',
    'GroupContributionSummarySerializer',
    'BulkContributionCreateSerializer',
    'BulkContributionStatusUpdateSerializer',
]