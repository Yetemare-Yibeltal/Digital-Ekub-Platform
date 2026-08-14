"""
Models for the contributions app.

This module defines all database models related to contribution management:
- Contribution: Main contribution entity with full lifecycle management
- ContributionPayment: Payment records for contributions
- ContributionReminder: Tracking of reminders sent for contributions
- ContributionAudit: Audit trail for contribution actions

All models include comprehensive fields, methods, properties, validation,
and business logic for full lifecycle management with proper transaction
handling, caching, and integration with user/group models.
"""

from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, F, Sum, Count, Avg, Max, Min, OuterRef, Subquery
from django.core.exceptions import ValidationError
from django.core.cache import cache
from decimal import Decimal
import uuid
import logging
from typing import Optional, List, Tuple, Dict, Any, Union
from datetime import timedelta, date, datetime

from apps.users.models import User
from apps.groups.models import Group, GroupMember
from apps.common.constants import ContributionStatus, ContributionType, PaymentStatus, PaymentMethod
from apps.common.utils import format_currency, get_current_time, calculate_platform_fee
from apps.common.exceptions import ValidationError as CustomValidationError

logger = logging.getLogger(__name__)


# ============================================================================
# CONTRIBUTION MODEL
# ============================================================================

class Contribution(models.Model):
    """
    Main Contribution model representing a member's contribution to a group.

    This model manages the entire lifecycle of a contribution including:
    - Creation and validation
    - Status transitions (pending -> paid/overdue/cancelled)
    - Payment processing
    - Penalty calculation and application
    - Overdue management
    - Refund processing
    - Integration with user reputation and group statistics
    - Audit logging
    - Cache management
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

    platform_fee = models.DecimalField(
        _('platform fee'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Platform fee deducted from this contribution')
    )

    net_amount = models.DecimalField(
        _('net amount'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Amount after fees and penalties')
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

    reminder_count = models.PositiveIntegerField(
        _('reminder count'),
        default=0,
        help_text=_('Number of reminders sent')
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
            models.Index(fields=['created_at', 'status']),
        ]
        unique_together = [
            ['group', 'round', 'user'],
        ]
        verbose_name = _('contribution')
        verbose_name_plural = _('contributions')

    def __str__(self):
        return f"Contribution #{self.id} - {self.user.email} for {self.group.name}"

    def save(self, *args, **kwargs):
        """Override save to auto-calculate fields and validate."""
        # Auto-set due_date if not set and group has frequency
        if not self.due_date and self.group and self.round is not None:
            due = self._calculate_due_date()
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

        # Calculate platform fee and net amount
        if self.amount and self.status == ContributionStatus.PAID:
            self.platform_fee = calculate_platform_fee(self.amount)
            self.net_amount = self.amount - self.platform_fee - self.penalty_amount + self.waived_amount

        # Set created_by if not set
        if not self.created_by and hasattr(self, '_current_user'):
            self.created_by = self._current_user

        super().save(*args, **kwargs)

        # Invalidate cache
        self._invalidate_cache()

        # Trigger stats update
        from .tasks import update_contribution_stats
        update_contribution_stats.delay(self.group.id)

    def _calculate_due_date(self) -> Optional[datetime]:
        """Calculate due date based on group frequency and round."""
        if not self.group:
            return None

        frequency_map = {
            'daily': timedelta(days=1),
            'weekly': timedelta(weeks=1),
            'biweekly': timedelta(weeks=2),
            'monthly': timedelta(days=30),
            'quarterly': timedelta(days=90),
            'yearly': timedelta(days=365),
        }

        interval = frequency_map.get(self.group.frequency, timedelta(days=30))
        due_date = self.group.start_date + (interval * self.round)
        return due_date

    def _invalidate_cache(self):
        """Invalidate all cache keys related to this contribution."""
        keys = [
            f'contribution_{self.id}',
            f'contribution_detail_{self.id}',
            f'user_contributions_{self.user.id}',
            f'group_contributions_{self.group.id}',
            f'user_pending_{self.user.id}',
            f'user_overdue_{self.user.id}',
        ]
        for key in keys:
            cache.delete(key)

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_pending(self) -> bool:
        return self.status == ContributionStatus.PENDING

    @property
    def is_paid(self) -> bool:
        return self.status == ContributionStatus.PAID

    @property
    def is_overdue(self) -> bool:
        return self.status == ContributionStatus.OVERDUE

    @property
    def is_cancelled(self) -> bool:
        return self.status == ContributionStatus.CANCELLED

    @property
    def is_refunded(self) -> bool:
        return self.status == ContributionStatus.REFUNDED

    @property
    def is_waived(self) -> bool:
        return self.status == ContributionStatus.WAIVED

    @property
    def is_partially_paid(self) -> bool:
        return self.status == ContributionStatus.PARTIALLY_PAID

    @property
    def is_deleted(self) -> bool:
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
        if self.is_deleted:
            return False
        return True

    @property
    def can_be_cancelled(self) -> bool:
        """Check if contribution can be cancelled."""
        if self.status in [ContributionStatus.PAID, ContributionStatus.CANCELLED, ContributionStatus.REFUNDED]:
            return False
        if self.is_deleted:
            return False
        return True

    @property
    def can_be_refunded(self) -> bool:
        """Check if contribution can be refunded."""
        return self.status == ContributionStatus.PAID and not self.is_deleted

    @property
    def can_be_waived(self) -> bool:
        """Check if contribution can be waived."""
        return self.status in [ContributionStatus.PENDING, ContributionStatus.OVERDUE] and not self.is_deleted

    @property
    def can_be_overdue(self) -> bool:
        """Check if contribution can be marked as overdue."""
        return self.status == ContributionStatus.PENDING and not self.is_deleted

    @property
    def total_amount_with_penalty(self) -> Decimal:
        """Total amount including penalty."""
        return self.amount + self.penalty_amount

    @property
    def net_amount_calculated(self) -> Decimal:
        """Net amount after waivers and fees."""
        return self.amount - self.waived_amount + self.penalty_amount - self.platform_fee

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

    @property
    def is_ready_for_reminder(self) -> bool:
        """Check if contribution is ready for a reminder."""
        if not self.can_be_paid:
            return False
        if self.status == ContributionStatus.OVERDUE:
            return True
        if self.is_due_today or self.is_due_this_week:
            return True
        return False

    @property
    def status_history(self) -> List[Dict[str, Any]]:
        """Get status history from audit logs."""
        from .models import ContributionAudit
        audits = ContributionAudit.objects.filter(
            contribution=self
        ).order_by('timestamp')
        return [
            {
                'old_status': audit.old_status,
                'new_status': audit.new_status,
                'action': audit.action,
                'timestamp': audit.timestamp,
                'user': audit.user.email if audit.user else 'System',
                'details': audit.details,
            }
            for audit in audits
        ]

    # ========================================================================
    # CORE BUSINESS METHODS
    # ========================================================================

    @transaction.atomic
    def mark_as_paid(
        self,
        payment_method: str = PaymentMethod.CASH,
        reference: str = None,
        paid_amount: Decimal = None
    ) -> bool:
        """
        Mark the contribution as paid with full processing.

        Args:
            payment_method: Payment method used
            reference: Payment reference
            paid_amount: Amount paid (defaults to total amount)

        Returns:
            bool: True if marked as paid successfully
        """
        if not self.can_be_paid:
            raise ValidationError(_('Contribution cannot be paid.'))

        if self.status == ContributionStatus.PAID:
            return True

        amount = paid_amount or self.total_amount_with_penalty

        # Create payment record
        from .models import ContributionPayment
        payment = ContributionPayment.objects.create(
            contribution=self,
            user=self.user,
            group=self.group,
            amount=amount,
            payment_method=payment_method,
            reference=reference,
            status=PaymentStatus.COMPLETED,
            paid_at=timezone.now(),
        )

        # Update contribution
        old_status = self.status
        self.status = ContributionStatus.PAID
        self.paid_date = timezone.now()
        self.payment = payment
        self.penalty_applied = self.penalty_amount > 0
        self.platform_fee = calculate_platform_fee(self.amount)
        self.net_amount = self.amount - self.platform_fee - self.penalty_amount + self.waived_amount
        self.save(update_fields=[
            'status', 'paid_date', 'payment', 'penalty_applied',
            'platform_fee', 'net_amount'
        ])

        # Update user statistics
        self._update_user_stats()

        # Update group statistics
        self._update_group_stats()

        # Log activity
        self._log_activity('contribution_paid', {
            'amount': float(amount),
            'method': payment_method,
            'reference': reference,
            'old_status': old_status,
        })

        # Create audit entry
        self._create_audit_entry('paid', old_status, self.status, {
            'payment_id': payment.id,
            'amount': float(amount),
        })

        # Send notifications
        self._send_payment_notification(payment)

        # Clear cache
        self._invalidate_cache()

        logger.info(f'Contribution {self.id} paid by user {self.user.id} via {payment_method}')
        return True

    @transaction.atomic
    def mark_as_overdue(self) -> bool:
        """
        Mark the contribution as overdue with penalty application.

        Returns:
            bool: True if marked as overdue successfully
        """
        if not self.can_be_overdue:
            return False

        old_status = self.status
        self.status = ContributionStatus.OVERDUE
        self.days_overdue = self.days_overdue_calculated
        self.save(update_fields=['status', 'days_overdue'])

        # Apply penalty if configured
        if self.days_overdue >= 7:
            self.apply_penalty()

        # Reduce user reputation
        self._update_user_reputation(-2)

        # Update user default count
        user = self.user
        user.defaulted_count += 1
        user.save(update_fields=['defaulted_count'])

        # Log activity
        self._log_activity('contribution_overdue', {
            'days_overdue': self.days_overdue,
            'penalty_applied': self.penalty_amount > 0,
        })

        # Create audit entry
        self._create_audit_entry('overdue', old_status, self.status, {
            'days_overdue': self.days_overdue,
        })

        # Send notification
        self._send_overdue_notification()

        # Clear cache
        self._invalidate_cache()

        logger.info(f'Contribution {self.id} marked as overdue')
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

        days = self.days_overdue_calculated
        penalty = self._calculate_penalty(days)

        if penalty > 0:
            self.penalty_amount = penalty
            self.penalty_applied = True
            self.save(update_fields=['penalty_amount', 'penalty_applied'])

            self._log_activity('penalty_applied', {
                'days_overdue': days,
                'penalty_amount': float(penalty),
            })

            logger.info(f'Penalty of {penalty} applied to contribution {self.id}')

        return penalty

    def _calculate_penalty(self, days_overdue: int) -> Decimal:
        """
        Calculate penalty based on days overdue.

        Rules:
        - 0-6 days: No penalty
        - 7-14 days: 2% of amount
        - 15-30 days: 5% of amount
        - 31+ days: 10% of amount
        """
        if days_overdue < 7:
            return Decimal('0.00')
        elif days_overdue <= 14:
            rate = Decimal('0.02')
        elif days_overdue <= 30:
            rate = Decimal('0.05')
        else:
            rate = Decimal('0.10')

        penalty = self.amount * rate
        return penalty.quantize(Decimal('0.01'))

    @transaction.atomic
    def cancel(self, reason: Optional[str] = None) -> bool:
        """Cancel the contribution."""
        if not self.can_be_cancelled:
            raise ValidationError(_('Contribution cannot be cancelled.'))

        old_status = self.status
        self.status = ContributionStatus.CANCELLED
        self.notes = reason or self.notes
        self.save(update_fields=['status', 'notes'])

        self._log_activity('contribution_cancelled', {'reason': reason})
        self._create_audit_entry('cancelled', old_status, self.status, {'reason': reason})
        self._invalidate_cache()

        logger.info(f'Contribution {self.id} cancelled')
        return True

    @transaction.atomic
    def refund(self, reason: Optional[str] = None) -> bool:
        """Refund the contribution."""
        if not self.can_be_refunded:
            raise ValidationError(_('Contribution cannot be refunded.'))

        old_status = self.status
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

        self._log_activity('contribution_refunded', {
            'amount': float(self.amount),
            'reason': reason,
        })
        self._create_audit_entry('refunded', old_status, self.status, {'reason': reason})
        self._invalidate_cache()

        logger.info(f'Contribution {self.id} refunded')
        return True

    @transaction.atomic
    def waive(self, amount: Decimal, reason: Optional[str] = None) -> bool:
        """Waive part or all of the contribution."""
        if not self.can_be_waived:
            raise ValidationError(_('Contribution cannot be waived.'))

        if amount > self.amount:
            raise ValidationError(_('Waived amount cannot exceed contribution amount.'))

        old_status = self.status
        self.waived_amount = amount
        self.notes = reason or self.notes

        if amount == self.amount:
            self.status = ContributionStatus.WAIVED
        else:
            self.status = ContributionStatus.PARTIALLY_PAID

        self.save(update_fields=['waived_amount', 'status', 'notes'])

        self._log_activity('contribution_waived', {
            'amount': float(amount),
            'reason': reason,
        })
        self._create_audit_entry('waived', old_status, self.status, {
            'amount': float(amount),
            'reason': reason,
        })
        self._invalidate_cache()

        logger.info(f'Contribution {self.id} waived {amount}')
        return True

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def _update_user_stats(self):
        """Update user statistics after payment."""
        user = self.user
        user.total_contributed += self.amount
        if self.due_date and timezone.now() <= self.due_date:
            user.on_time_payments += 1
            user.reputation_score = min(100, user.reputation_score + 1)
        else:
            user.reputation_score = min(100, user.reputation_score + 0.5)
        user.save(update_fields=['total_contributed', 'on_time_payments', 'reputation_score'])

    def _update_group_stats(self):
        """Update group statistics after payment."""
        group = self.group
        group.total_paid += self.amount
        group.total_contributions += 1
        group.save(update_fields=['total_paid', 'total_contributions'])

    def _update_user_reputation(self, delta: int):
        """Update user reputation by delta."""
        user = self.user
        user.reputation_score = max(0, min(100, user.reputation_score + delta))
        user.save(update_fields=['reputation_score'])

    def _log_activity(self, action: str, details: Dict[str, Any]):
        """Log activity for the contribution."""
        from apps.groups.models import GroupActivity
        GroupActivity.objects.create(
            group=self.group,
            user=self.user,
            action=action,
            details={'contribution_id': self.id, **details},
            timestamp=timezone.now()
        )

    def _create_audit_entry(self, action: str, old_status: str, new_status: str, details: Dict[str, Any]):
        """Create audit entry for the contribution."""
        from .models import ContributionAudit
        ContributionAudit.objects.create(
            contribution=self,
            user=getattr(self, '_current_user', None),
            action=action,
            old_status=old_status,
            new_status=new_status,
            details=details,
            timestamp=timezone.now(),
        )

    def _send_payment_notification(self, payment):
        """Send notification about payment."""
        from apps.notifications.models import Notification
        from apps.common.utils import send_email

        # In-app notification
        Notification.objects.create(
            user=self.user,
            notification_type='payment_confirmation',
            title='Payment Received',
            message=f'Your payment of {format_currency(payment.amount)} for contribution #{self.id} has been received.',
            contribution=self,
            group=self.group,
            is_read=False,
        )

        # Email notification
        send_email(
            to_email=self.user.email,
            subject=f'Payment Received - Contribution #{self.id}',
            message=f'Your payment of {format_currency(payment.amount)} for contribution #{self.id} has been received.\n\nThank you for your contribution!',
            html_message=None,
        )

    def _send_overdue_notification(self):
        """Send notification about overdue."""
        from apps.notifications.models import Notification
        Notification.objects.create(
            user=self.user,
            notification_type='overdue_warning',
            title='Contribution Overdue',
            message=f'Your contribution #{self.id} is overdue by {self.days_overdue} days. Please make your payment.',
            contribution=self,
            group=self.group,
            is_read=False,
        )

    # ========================================================================
    # VALIDATION METHODS
    # ========================================================================

    def validate_status_transition(self, new_status: str) -> bool:
        """Validate if status transition is allowed."""
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
            'platform_fee': float(self.platform_fee),
            'net_amount': float(self.net_amount),
            'total_amount': float(self.total_amount_with_penalty),
            'days_overdue': self.days_overdue_calculated,
            'is_paid': self.is_paid,
            'is_overdue': self.is_overdue,
            'is_pending': self.is_pending,
            'is_cancelled': self.is_cancelled,
            'is_refunded': self.is_refunded,
            'is_waived': self.is_waived,
            'reference': self.reference,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def get_detailed_summary(self) -> Dict[str, Any]:
        """Get detailed summary including status history."""
        summary = self.get_summary()
        summary['status_history'] = self.status_history
        summary['payment'] = self.payment.get_summary() if self.payment else None
        summary['reminders_sent'] = self.reminders.count()
        summary['group_stats'] = {
            'members_count': self.group.members_count,
            'total_contributions': self.group.total_contributions,
            'total_paid': float(self.group.total_paid),
        }
        summary['user_stats'] = {
            'total_contributed': float(self.user.total_contributed),
            'reputation_score': self.user.reputation_score,
            'defaulted_count': self.user.defaulted_count,
            'on_time_payments': self.user.on_time_payments,
        }
        return summary

    # ========================================================================
    # SOFT DELETE
    # ========================================================================

    @transaction.atomic
    def soft_delete(self, reason: Optional[str] = None) -> None:
        """Soft delete the contribution."""
        self.deleted_at = timezone.now()
        self.notes = reason or self.notes
        self.save(update_fields=['deleted_at', 'notes'])
        self._invalidate_cache()
        logger.info(f'Contribution {self.id} soft deleted')

    @transaction.atomic
    def restore(self) -> None:
        """Restore a soft-deleted contribution."""
        self.deleted_at = None
        self.save(update_fields=['deleted_at'])
        self._invalidate_cache()
        logger.info(f'Contribution {self.id} restored')


# ============================================================================
# CONTRIBUTION PAYMENT MODEL
# ============================================================================

class ContributionPayment(models.Model):
    """
    Payment record for a contribution with full tracking and reconciliation.
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
            models.Index(fields=['reference']),
        ]
        verbose_name = _('contribution payment')
        verbose_name_plural = _('contribution payments')

    def __str__(self):
        return f"Payment #{self.id} - {self.user.email} for contribution #{self.contribution.id}"

    def save(self, *args, **kwargs):
        if not self.paid_at:
            self.paid_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def is_completed(self) -> bool:
        return self.status == PaymentStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == PaymentStatus.FAILED

    @property
    def is_pending(self) -> bool:
        return self.status == PaymentStatus.PENDING

    @property
    def is_refunded(self) -> bool:
        return self.status == PaymentStatus.REFUNDED

    @transaction.atomic
    def complete(self, reference: str = None) -> bool:
        """Mark payment as completed."""
        if self.status != PaymentStatus.PENDING:
            return False
        self.status = PaymentStatus.COMPLETED
        if reference:
            self.reference = reference
        self.save(update_fields=['status', 'reference'])
        logger.info(f'Payment {self.id} completed')
        return True

    @transaction.atomic
    def fail(self, reason: Optional[str] = None) -> bool:
        """Mark payment as failed."""
        self.status = PaymentStatus.FAILED
        self.save(update_fields=['status'])
        logger.info(f'Payment {self.id} failed: {reason}')
        return True

    @transaction.atomic
    def refund_payment(self, reason: Optional[str] = None) -> bool:
        """Refund the payment."""
        if self.status != PaymentStatus.COMPLETED:
            return False
        self.status = PaymentStatus.REFUNDED
        self.save(update_fields=['status'])
        logger.info(f'Payment {self.id} refunded: {reason}')
        return True

    def get_summary(self) -> Dict[str, Any]:
        """Get payment summary."""
        return {
            'id': self.id,
            'contribution_id': self.contribution.id,
            'user_id': self.user.id,
            'user_name': self.user.full_name,
            'amount': float(self.amount),
            'payment_method': self.payment_method,
            'status': self.status,
            'status_display': self.get_status_display(),
            'reference': self.reference,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# CONTRIBUTION REMINDER MODEL
# ============================================================================

class ContributionReminder(models.Model):
    """Tracking of reminders sent for contributions."""

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
            models.Index(fields=['reminder_type']),
        ]
        verbose_name = _('contribution reminder')
        verbose_name_plural = _('contribution reminders')

    def __str__(self):
        return f"Reminder for contribution #{self.contribution.id} to {self.user.email}"


# ============================================================================
# CONTRIBUTION AUDIT MODEL
# ============================================================================

class ContributionAudit(models.Model):
    """Audit trail for contribution actions."""

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
            models.Index(fields=['old_status', 'new_status']),
        ]
        verbose_name = _('contribution audit')
        verbose_name_plural = _('contribution audits')

    def __str__(self):
        return f"Audit #{self.id} - {self.action} on contribution #{self.contribution.id}"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

@transaction.atomic
def create_contribution(
    user: User,
    group: Group,
    round_number: int,
    amount: Decimal,
    due_date: Optional[datetime] = None,
    created_by: Optional[User] = None,
    contribution_type: str = ContributionType.REGULAR
) -> Contribution:
    """
    Create a new contribution for a user in a group with full validation.
    """
    if not due_date:
        from apps.contributions import get_contribution_due_date
        due_date = get_contribution_due_date(group, round_number)

    if not due_date:
        raise ValidationError(_('Could not determine due date.'))

    # Check if contribution already exists
    if Contribution.objects.filter(
        group=group,
        user=user,
        round=round_number
    ).exists():
        raise ValidationError(_('Contribution already exists for this user and round.'))

    contribution = Contribution(
        user=user,
        group=group,
        round=round_number,
        amount=amount,
        due_date=due_date,
        status=ContributionStatus.PENDING,
        contribution_type=contribution_type,
        created_by=created_by,
    )
    contribution.save()

    logger.info(f'Contribution created for user {user.id} in group {group.id}')
    return contribution


@transaction.atomic
def create_bulk_contributions_for_group(
    group: Group,
    round_number: int,
    amount: Decimal,
    created_by: Optional[User] = None
) -> List[Contribution]:
    """
    Create contributions for all active members of a group for a specific round.
    """
    members = GroupMember.objects.filter(
        group=group,
        is_active=True
    ).select_related('user')

    contributions = []
    for member in members:
        try:
            contribution = create_contribution(
                user=member.user,
                group=group,
                round_number=round_number,
                amount=amount,
                created_by=created_by,
            )
            contributions.append(contribution)
        except Exception as e:
            logger.error(f'Error creating contribution for user {member.user.id}: {str(e)}')

    logger.info(f'Created {len(contributions)} contributions for group {group.id}')
    return contributions


@transaction.atomic
def process_overdue_contributions() -> Dict[str, int]:
    """
    Process all overdue contributions and apply penalties.

    Returns:
        Dict with counts of processed contributions.
    """
    now = timezone.now()
    overdue_contributions = Contribution.objects.filter(
        status=ContributionStatus.PENDING,
        due_date__lt=now,
        deleted_at__isnull=True
    )

    processed = 0
    errors = 0

    for contribution in overdue_contributions:
        try:
            contribution.mark_as_overdue()
            processed += 1
        except Exception as e:
            logger.error(f'Error processing overdue contribution {contribution.id}: {str(e)}')
            errors += 1

    return {'processed': processed, 'errors': errors}


def get_contribution_stats(user_id: int = None, group_id: int = None) -> Dict[str, Any]:
    """
    Get contribution statistics aggregated.
    """
    from django.db.models import Sum, Count

    queryset = Contribution.objects.filter(deleted_at__isnull=True)

    if user_id:
        queryset = queryset.filter(user_id=user_id)
    if group_id:
        queryset = queryset.filter(group_id=group_id)

    total = queryset.count()
    paid = queryset.filter(status=ContributionStatus.PAID).count()
    pending = queryset.filter(status=ContributionStatus.PENDING).count()
    overdue = queryset.filter(status=ContributionStatus.OVERDUE).count()

    total_amount = queryset.filter(
        status=ContributionStatus.PAID
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    return {
        'total_contributions': total,
        'paid': paid,
        'pending': pending,
        'overdue': overdue,
        'total_paid_amount': float(total_amount),
        'completion_rate': (paid / total * 100) if total > 0 else 0,
    }