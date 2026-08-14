"""
Models for the contributions app.

This module defines all database models related to contribution management:
- Contribution: Main contribution entity linked to user and group
- ContributionPayment: Payment records for contributions
- ContributionReminder: Tracking of reminder sent for contributions
- ContributionAudit: Audit trail for contribution actions

All models include comprehensive fields, methods, properties, validation,
and business logic for full lifecycle management.
"""

from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, F, Sum, Count, Avg, Max, Min
from django.core.exceptions import ValidationError
from decimal import Decimal
import uuid
import logging
from typing import Optional, List, Tuple, Dict, Any, Union
from datetime import timedelta, date

from apps.users.models import User
from apps.groups.models import Group, GroupMember
from apps.common.constants import ContributionStatus, ContributionType, PaymentStatus, PaymentMethod
from apps.common.utils import format_currency, get_current_time
from apps.common.exceptions import ValidationError as CustomValidationError

logger = logging.getLogger(__name__)


# ============================================================================
# CONTRIBUTION MODEL
# ============================================================================

class Contribution(models.Model):
    """
    Main Contribution model representing a member's contribution to a group.

    Fields:
    - group: The group this contribution belongs to
    - user: The member making the contribution
    - amount: Contribution amount (must match group's contribution amount)
    - round: The round/cycle number (0-indexed)
    - due_date: The date by which the contribution is due
    - paid_date: When the contribution was paid (if paid)
    - status: PENDING, PAID, OVERDUE, CANCELLED, REFUNDED, PARTIALLY_PAID, WAIVED
    - contribution_type: REGULAR, SPECIAL, PENALTY, BONUS, ADVANCE
    - penalty_amount: Any penalty applied for late payment
    - waived_amount: Amount waived (if any)
    - reference: External reference (payment gateway ref)
    - notes: Additional notes
    - created_by: User who created this contribution (system or admin)
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - mark_as_paid(): Mark contribution as paid
    - mark_as_overdue(): Mark as overdue
    - cancel(): Cancel the contribution
    - refund(): Refund the contribution
    - waive(): Waive the contribution
    - apply_penalty(): Apply late payment penalty
    - is_paid, is_pending, is_overdue, is_cancelled, is_refunded: Properties
    - get_days_overdue(): Calculate days overdue
    - get_penalty_amount(): Calculate penalty amount
    - can_be_paid(): Check if contribution can be paid
    - get_summary(): Get summary dictionary

    Indexes: group, user, status, due_date, round
    """

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='contributions',
        verbose_name=_('group'),
        db_index=True,
        help_text=_('The group this contribution belongs to')
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='contributions',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('The member making the contribution')
    )

    # ========================================================================
    # BASIC FIELDS
    # ========================================================================

    amount = models.DecimalField(
        _('amount'),
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text=_('Contribution amount')
    )

    round = models.PositiveIntegerField(
        _('round number'),
        db_index=True,
        help_text=_('Round/cycle number (0-indexed)')
    )

    due_date = models.DateTimeField(
        _('due date'),
        db_index=True,
        help_text=_('The date by which the contribution is due')
    )

    paid_date = models.DateTimeField(
        _('paid date'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('When the contribution was paid')
    )

    # ========================================================================
    # STATUS AND TYPE
    # ========================================================================

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=ContributionStatus.CHOICES,
        default=ContributionStatus.PENDING,
        db_index=True,
        help_text=_('Current status of the contribution')
    )

    contribution_type = models.CharField(
        _('contribution type'),
        max_length=20,
        choices=ContributionType.CHOICES,
        default=ContributionType.REGULAR,
        help_text=_('Type of contribution')
    )

    # ========================================================================
    # FINANCIAL CALCULATIONS
    # ========================================================================

    penalty_amount = models.DecimalField(
        _('penalty amount'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Any penalty applied for late payment')
    )

    waived_amount = models.DecimalField(
        _('waived amount'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Amount waived (if any)')
    )

    # ========================================================================
    # REFERENCES AND NOTES
    # ========================================================================

    reference = models.CharField(
        _('reference'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('External reference (payment gateway ref)')
    )

    notes = models.TextField(
        _('notes'),
        blank=True,
        null=True,
        help_text=_('Additional notes')
    )

    payment = models.ForeignKey(
        'ContributionPayment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contribution_payment',
        verbose_name=_('payment'),
        help_text=_('Payment record for this contribution')
    )

    # ========================================================================
    # METADATA
    # ========================================================================

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contributions_created',
        verbose_name=_('created by'),
        help_text=_('User who created this contribution (system or admin)')
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

    # ========================================================================
    # DENORMALIZED STATISTICS (for performance)
    # ========================================================================

    days_overdue = models.PositiveIntegerField(
        _('days overdue'),
        default=0,
        help_text=_('Number of days overdue (calculated)')
    )

    penalty_applied = models.BooleanField(
        _('penalty applied'),
        default=False,
        help_text=_('Whether penalty has been applied')
    )

    # ========================================================================
    # META
    # ========================================================================

    class Meta:
        db_table = 'contributions'
        ordering = ['-due_date']
        indexes = [
            models.Index(fields=['group', 'status']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['due_date', 'status']),
            models.Index(fields=['round', 'group']),
            models.Index(fields=['status', 'due_date']),
        ]
        unique_together = [
            ['group', 'round', 'user'],
        ]
        verbose_name = _('contribution')
        verbose_name_plural = _('contributions')

    def __str__(self):
        return f"Contribution #{self.id} - {self.user.email} for {self.group.name}"

    # ========================================================================
    # SAVE OVERRIDE
    # ========================================================================

    def save(self, *args, **kwargs):
        """Override save to auto-calculate days overdue and validate."""
        # Auto-set due_date if not set and group has frequency
        if not self.due_date and self.group and self.round is not None:
            from apps.contributions import get_contribution_due_date
            due = get_contribution_due_date(self.group, self.round)
            if due:
                self.due_date = due

        # Validate amount matches group's contribution amount (unless special type)
        if self.contribution_type == ContributionType.REGULAR and self.group:
            if self.amount != self.group.contribution_amount:
                raise ValidationError(
                    _('Contribution amount must match group\'s contribution amount.')
                )

        # Auto-calculate days overdue
        if self.status == ContributionStatus.OVERDUE and self.due_date:
            now = timezone.now()
            if now > self.due_date:
                self.days_overdue = (now - self.due_date).days

        # Set created_by if not set
        if not self.created_by and hasattr(self, '_current_user'):
            self.created_by = self._current_user

        super().save(*args, **kwargs)

        # Trigger stats update
        from .tasks import update_contribution_stats
        update_contribution_stats.delay(self.group.id)

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_pending(self) -> bool:
        """Check if contribution is pending."""
        return self.status == ContributionStatus.PENDING

    @property
    def is_paid(self) -> bool:
        """Check if contribution is paid."""
        return self.status == ContributionStatus.PAID

    @property
    def is_overdue(self) -> bool:
        """Check if contribution is overdue."""
        return self.status == ContributionStatus.OVERDUE

    @property
    def is_cancelled(self) -> bool:
        """Check if contribution is cancelled."""
        return self.status == ContributionStatus.CANCELLED

    @property
    def is_refunded(self) -> bool:
        """Check if contribution is refunded."""
        return self.status == ContributionStatus.REFUNDED

    @property
    def is_waived(self) -> bool:
        """Check if contribution is waived."""
        return self.status == ContributionStatus.WAIVED

    @property
    def is_deleted(self) -> bool:
        """Check if contribution is soft-deleted."""
        return self.deleted_at is not None

    @property
    def can_be_paid(self) -> bool:
        """Check if contribution can be paid."""
        if not self.group.is_active:
            return False
        if self.group.is_completed or self.group.is_cancelled:
            return False
        if self.status not in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]:
            return False
        return True

    @property
    def can_be_cancelled(self) -> bool:
        """Check if contribution can be cancelled."""
        if self.status in [ContributionStatus.PAID, ContributionStatus.CANCELLED, ContributionStatus.REFUNDED]:
            return False
        return True

    @property
    def can_be_refunded(self) -> bool:
        """Check if contribution can be refunded."""
        return self.status == ContributionStatus.PAID

    @property
    def can_be_waived(self) -> bool:
        """Check if contribution can be waived."""
        return self.status in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]

    @property
    def total_amount_with_penalty(self) -> Decimal:
        """Total amount including penalty."""
        return self.amount + self.penalty_amount

    @property
    def net_amount(self) -> Decimal:
        """Net amount after waivers."""
        return self.amount - self.waived_amount

    @property
    def days_overdue_calculated(self) -> int:
        """Calculate days overdue from current time."""
        if not self.due_date:
            return 0
        now = timezone.now()
        if now <= self.due_date:
            return 0
        return (now - self.due_date).days

    @property
    def is_due_today(self) -> bool:
        """Check if contribution is due today."""
        if not self.due_date:
            return False
        return self.due_date.date() == timezone.now().date()

    @property
    def is_due_this_week(self) -> bool:
        """Check if contribution is due within the next 7 days."""
        if not self.due_date:
            return False
        now = timezone.now()
        return now <= self.due_date <= now + timedelta(days=7)

    # ========================================================================
    # METHODS
    # ========================================================================

    @transaction.atomic
    def mark_as_paid(self, payment_method: str = None, reference: str = None) -> bool:
        """
        Mark the contribution as paid.

        Args:
            payment_method: Payment method used
            reference: Payment reference

        Returns:
            bool: True if marked as paid successfully
        """
        if not self.can_be_paid:
            raise ValidationError(_('Contribution cannot be paid.'))

        if self.status == ContributionStatus.PAID:
            return True

        # Create payment record
        from .models import ContributionPayment
        payment = ContributionPayment.objects.create(
            contribution=self,
            user=self.user,
            group=self.group,
            amount=self.total_amount_with_penalty,
            payment_method=payment_method or PaymentMethod.CASH,
            reference=reference,
            status='completed',
            paid_at=timezone.now(),
        )

        # Update contribution
        self.status = ContributionStatus.PAID
        self.paid_date = timezone.now()
        self.payment = payment
        self.penalty_applied = self.penalty_amount > 0
        self.save(update_fields=['status', 'paid_date', 'payment', 'penalty_applied'])

        # Update user statistics
        user = self.user
        user.total_contributed += self.amount
        if self.due_date and timezone.now() <= self.due_date:
            user.on_time_payments += 1
            user.reputation_score = min(100, user.reputation_score + 1)
        else:
            user.reputation_score = min(100, user.reputation_score + 0.5)
        user.save(update_fields=['total_contributed', 'on_time_payments', 'reputation_score'])

        # Update group statistics
        group = self.group
        group.total_paid += self.amount
        group.total_contributions += 1
        group.save(update_fields=['total_paid', 'total_contributions'])

        # Log activity
        from apps.groups.models import GroupActivity
        GroupActivity.objects.create(
            group=group,
            user=self.user,
            action='contribution_paid',
            details={
                'contribution_id': self.id,
                'amount': float(self.amount),
                'method': payment_method,
                'reference': reference,
            },
            timestamp=timezone.now()
        )

        logger.info(f'Contribution {self.id} paid by user {self.user.id}')
        return True

    @transaction.atomic
    def mark_as_overdue(self) -> bool:
        """
        Mark the contribution as overdue.

        Returns:
            bool: True if marked as overdue successfully
        """
        if self.status != ContributionStatus.PENDING:
            return False

        if self.due_date and timezone.now() <= self.due_date:
            return False

        self.status = ContributionStatus.OVERDUE
        self.days_overdue = self.days_overdue_calculated
        self.save(update_fields=['status', 'days_overdue'])

        # Reduce user reputation
        user = self.user
        user.reputation_score = max(0, user.reputation_score - 2)
        user.defaulted_count += 1
        user.save(update_fields=['reputation_score', 'defaulted_count'])

        logger.info(f'Contribution {self.id} marked as overdue')
        return True

    @transaction.atomic
    def cancel(self, reason: Optional[str] = None) -> bool:
        """
        Cancel the contribution.

        Args:
            reason: Reason for cancellation

        Returns:
            bool: True if cancelled successfully
        """
        if not self.can_be_cancelled:
            raise ValidationError(_('Contribution cannot be cancelled.'))

        self.status = ContributionStatus.CANCELLED
        self.notes = reason or self.notes
        self.save(update_fields=['status', 'notes'])

        # Log activity
        from apps.groups.models import GroupActivity
        GroupActivity.objects.create(
            group=self.group,
            user=self.user,
            action='contribution_cancelled',
            details={
                'contribution_id': self.id,
                'reason': reason,
            },
            timestamp=timezone.now()
        )

        logger.info(f'Contribution {self.id} cancelled')
        return True

    @transaction.atomic
    def refund(self, reason: Optional[str] = None) -> bool:
        """
        Refund the contribution.

        Args:
            reason: Reason for refund

        Returns:
            bool: True if refunded successfully
        """
        if not self.can_be_refunded:
            raise ValidationError(_('Contribution cannot be refunded.'))

        self.status = ContributionStatus.REFUNDED
        self.notes = reason or self.notes
        self.save(update_fields=['status', 'notes'])

        # Update user statistics
        user = self.user
        user.total_contributed -= self.amount
        user.save(update_fields=['total_contributed'])

        # Update group statistics
        group = self.group
        group.total_paid -= self.amount
        group.save(update_fields=['total_paid'])

        # Log activity
        from apps.groups.models import GroupActivity
        GroupActivity.objects.create(
            group=group,
            user=user,
            action='contribution_refunded',
            details={
                'contribution_id': self.id,
                'amount': float(self.amount),
                'reason': reason,
            },
            timestamp=timezone.now()
        )

        logger.info(f'Contribution {self.id} refunded')
        return True

    @transaction.atomic
    def waive(self, amount: Decimal, reason: Optional[str] = None) -> bool:
        """
        Waive part or all of the contribution.

        Args:
            amount: Amount to waive
            reason: Reason for waiver

        Returns:
            bool: True if waived successfully
        """
        if not self.can_be_waived:
            raise ValidationError(_('Contribution cannot be waived.'))

        if amount > self.amount:
            raise ValidationError(_('Waived amount cannot exceed contribution amount.'))

        self.waived_amount = amount
        self.notes = reason or self.notes
        if amount == self.amount:
            self.status = ContributionStatus.WAIVED
        else:
            self.status = ContributionStatus.PARTIALLY_PAID
        self.save(update_fields=['waived_amount', 'status', 'notes'])

        # Log activity
        from apps.groups.models import GroupActivity
        GroupActivity.objects.create(
            group=self.group,
            user=self.user,
            action='contribution_waived',
            details={
                'contribution_id': self.id,
                'amount': float(amount),
                'reason': reason,
            },
            timestamp=timezone.now()
        )

        logger.info(f'Contribution {self.id} waived {amount}')
        return True

    @transaction.atomic
    def apply_penalty(self) -> Decimal:
        """
        Apply late payment penalty to the contribution.

        Returns:
            Decimal: Penalty amount applied
        """
        if self.status != ContributionStatus.OVERDUE:
            raise ValidationError(_('Only overdue contributions can have penalties applied.'))

        if self.penalty_applied:
            return self.penalty_amount

        from apps.contributions import calculate_contribution_penalty
        days = self.days_overdue_calculated
        penalty = calculate_contribution_penalty(self.amount, days)

        if penalty > 0:
            self.penalty_amount = penalty
            self.penalty_applied = True
            self.save(update_fields=['penalty_amount', 'penalty_applied'])
            logger.info(f'Penalty of {penalty} applied to contribution {self.id}')

        return penalty

    # ========================================================================
    # VALIDATION METHODS
    # ========================================================================

    def validate_status_transition(self, new_status: str) -> bool:
        """
        Validate if status transition is allowed.

        Args:
            new_status: New status to transition to

        Returns:
            bool: True if transition is allowed
        """
        allowed_transitions = {
            ContributionStatus.PENDING: [
                ContributionStatus.PAID,
                ContributionStatus.OVERDUE,
                ContributionStatus.CANCELLED,
                ContributionStatus.WAIVED,
                ContributionStatus.PARTIALLY_PAID,
            ],
            ContributionStatus.OVERDUE: [
                ContributionStatus.PAID,
                ContributionStatus.CANCELLED,
                ContributionStatus.WAIVED,
                ContributionStatus.PARTIALLY_PAID,
            ],
            ContributionStatus.PAID: [
                ContributionStatus.REFUNDED,
            ],
            ContributionStatus.REFUNDED: [],
            ContributionStatus.CANCELLED: [],
            ContributionStatus.WAIVED: [],
            ContributionStatus.PARTIALLY_PAID: [
                ContributionStatus.PAID,
                ContributionStatus.WAIVED,
                ContributionStatus.CANCELLED,
            ],
        }
        allowed = allowed_transitions.get(self.status, [])
        return new_status in allowed

    # ========================================================================
    # SUMMARY AND REPORTING
    # ========================================================================

    def get_summary(self) -> Dict[str, Any]:
        """Get summary dictionary for the contribution."""
        return {
            'id': self.id,
            'group_id': self.group.id,
            'group_name': self.group.name,
            'user_id': self.user.id,
            'user_name': self.user.full_name,
            'user_email': self.user.email,
            'amount': float(self.amount),
            'round': self.round,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'paid_date': self.paid_date.isoformat() if self.paid_date else None,
            'status': self.status,
            'status_display': self.get_status_display(),
            'penalty_amount': float(self.penalty_amount),
            'waived_amount': float(self.waived_amount),
            'total_amount': float(self.total_amount_with_penalty),
            'net_amount': float(self.net_amount),
            'days_overdue': self.days_overdue_calculated,
            'is_paid': self.is_paid,
            'is_overdue': self.is_overdue,
            'is_pending': self.is_pending,
            'is_cancelled': self.is_cancelled,
            'is_refunded': self.is_refunded,
        }

    # ========================================================================
    # SOFT DELETE
    # ========================================================================

    @transaction.atomic
    def soft_delete(self, reason: Optional[str] = None) -> None:
        """Soft delete the contribution."""
        self.deleted_at = timezone.now()
        self.notes = reason or self.notes
        self.save(update_fields=['deleted_at', 'notes'])
        logger.info(f'Contribution {self.id} soft deleted')

    @transaction.atomic
    def restore(self) -> None:
        """Restore a soft-deleted contribution."""
        self.deleted_at = None
        self.save(update_fields=['deleted_at'])
        logger.info(f'Contribution {self.id} restored')


# ============================================================================
# CONTRIBUTION PAYMENT MODEL
# ============================================================================

class ContributionPayment(models.Model):
    """
    Payment record for a contribution.
    """

    contribution = models.OneToOneField(
        Contribution,
        on_delete=models.CASCADE,
        related_name='payment_record',
        verbose_name=_('contribution'),
        help_text=_('The contribution this payment is for')
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='contribution_payments',
        verbose_name=_('user'),
        help_text=_('User who made the payment')
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='contribution_payments',
        verbose_name=_('group'),
        help_text=_('Group the payment belongs to')
    )

    amount = models.DecimalField(
        _('amount'),
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text=_('Payment amount')
    )

    payment_method = models.CharField(
        _('payment method'),
        max_length=20,
        choices=PaymentMethod.CHOICES,
        default=PaymentMethod.CASH,
        help_text=_('Method used for payment')
    )

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=PaymentStatus.CHOICES,
        default=PaymentStatus.PENDING,
        db_index=True,
        help_text=_('Payment status')
    )

    reference = models.CharField(
        _('reference'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('External payment reference')
    )

    paid_at = models.DateTimeField(
        _('paid at'),
        db_index=True,
        help_text=_('When the payment was made')
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
        db_table = 'contribution_payments'
        ordering = ['-paid_at']
        indexes = [
            models.Index(fields=['user', 'paid_at']),
            models.Index(fields=['group', 'paid_at']),
            models.Index(fields=['status', 'paid_at']),
        ]
        verbose_name = _('contribution payment')
        verbose_name_plural = _('contribution payments')

    def __str__(self):
        return f"Payment #{self.id} - {self.user.email} for contribution #{self.contribution.id}"

    @property
    def is_completed(self) -> bool:
        return self.status == PaymentStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == PaymentStatus.FAILED

    @property
    def is_pending(self) -> bool:
        return self.status == PaymentStatus.PENDING

    @transaction.atomic
    def complete(self) -> bool:
        """Mark payment as completed."""
        if self.status != PaymentStatus.PENDING:
            return False
        self.status = PaymentStatus.COMPLETED
        self.save(update_fields=['status'])
        return True

    @transaction.atomic
    def fail(self, reason: Optional[str] = None) -> bool:
        """Mark payment as failed."""
        self.status = PaymentStatus.FAILED
        self.save(update_fields=['status'])
        return True


# ============================================================================
# CONTRIBUTION REMINDER MODEL
# ============================================================================

class ContributionReminder(models.Model):
    """
    Tracking of reminders sent for contributions.
    """

    contribution = models.ForeignKey(
        Contribution,
        on_delete=models.CASCADE,
        related_name='reminders',
        verbose_name=_('contribution'),
        help_text=_('Contribution this reminder is for')
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='contribution_reminders',
        verbose_name=_('user'),
        help_text=_('User to whom the reminder was sent')
    )

    reminder_type = models.CharField(
        _('reminder type'),
        max_length=20,
        choices=[
            ('email', 'Email'),
            ('sms', 'SMS'),
            ('push', 'Push Notification'),
            ('in_app', 'In-App Notification'),
        ],
        default='email',
        help_text=_('Type of reminder sent')
    )

    sent_at = models.DateTimeField(
        _('sent at'),
        default=timezone.now,
        db_index=True,
        help_text=_('When the reminder was sent')
    )

    sent_successfully = models.BooleanField(
        _('sent successfully'),
        default=True,
        help_text=_('Whether the reminder was sent successfully')
    )

    error_message = models.TextField(
        _('error message'),
        blank=True,
        null=True,
        help_text=_('Error message if sending failed')
    )

    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )

    class Meta:
        db_table = 'contribution_reminders'
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['contribution', 'sent_at']),
            models.Index(fields=['user', 'sent_at']),
        ]
        verbose_name = _('contribution reminder')
        verbose_name_plural = _('contribution reminders')

    def __str__(self):
        return f"Reminder for contribution #{self.contribution.id} to {self.user.email}"


# ============================================================================
# CONTRIBUTION AUDIT MODEL
# ============================================================================

class ContributionAudit(models.Model):
    """
    Audit trail for contribution actions.
    """

    contribution = models.ForeignKey(
        Contribution,
        on_delete=models.CASCADE,
        related_name='audits',
        verbose_name=_('contribution'),
        help_text=_('Contribution being audited')
    )

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contribution_audits',
        verbose_name=_('user'),
        help_text=_('User who performed the action')
    )

    action = models.CharField(
        _('action'),
        max_length=50,
        db_index=True,
        help_text=_('Action performed')
    )

    old_status = models.CharField(
        _('old status'),
        max_length=20,
        blank=True,
        null=True,
        help_text=_('Previous status')
    )

    new_status = models.CharField(
        _('new status'),
        max_length=20,
        blank=True,
        null=True,
        help_text=_('New status')
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
        help_text=_('When the action occurred')
    )

    ip_address = models.GenericIPAddressField(
        _('IP address'),
        null=True,
        blank=True,
        help_text=_('IP address of the requester')
    )

    class Meta:
        db_table = 'contribution_audits'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['contribution', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]
        verbose_name = _('contribution audit')
        verbose_name_plural = _('contribution audits')

    def __str__(self):
        return f"Audit #{self.id} - {self.action} on contribution #{self.contribution.id}"


# ============================================================================
# HELPER FUNCTIONS (EXPOSED FOR USE)
# ============================================================================

def create_contribution(user: User, group: Group, round_number: int, amount: Decimal, due_date: Optional[date] = None) -> Contribution:
    """
    Create a new contribution for a user in a group.

    Args:
        user: User making the contribution
        group: Group the contribution belongs to
        round_number: Round number (0-indexed)
        amount: Contribution amount
        due_date: Optional due date (calculated from group if not provided)

    Returns:
        Contribution: Created contribution instance
    """
    if not due_date:
        from apps.contributions import get_contribution_due_date
        due_date = get_contribution_due_date(group, round_number)

    contribution = Contribution.objects.create(
        user=user,
        group=group,
        round=round_number,
        amount=amount,
        due_date=due_date,
        status=ContributionStatus.PENDING,
        contribution_type=ContributionType.REGULAR,
    )
    return contribution


def create_bulk_contributions_for_group(group: Group, round_number: int, amount: Decimal) -> List[Contribution]:
    """
    Create contributions for all active members of a group for a specific round.

    Args:
        group: Group instance
        round_number: Round number (0-indexed)
        amount: Contribution amount

    Returns:
        List[Contribution]: List of created contributions
    """
    from apps.groups.models import GroupMember
    members = GroupMember.objects.filter(group=group, is_active=True).select_related('user')
    contributions = []
    for member in members:
        try:
            contribution = create_contribution(
                user=member.user,
                group=group,
                round_number=round_number,
                amount=amount,
            )
            contributions.append(contribution)
        except Exception as e:
            logger.error(f'Error creating contribution for user {member.user.id}: {str(e)}')
    return contributions