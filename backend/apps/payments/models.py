"""
Models for the payments app.

This module defines all database models related to payment processing:
- Payment: Main payment entity linked to user, group, and contribution
- PaymentTransaction: Transaction records for each payment attempt
- Payout: Payout records for group winners
- PaymentGatewayLog: Logs of gateway API calls
- PaymentWebhookLog: Logs of webhook events
- PaymentReconciliation: Reconciliation records
- PaymentDispute: Dispute management
- Settlement: Settlement records
- PaymentMethod: User payment methods
- PaymentAudit: Audit trail for payment actions

All models include comprehensive fields, methods, properties, validation,
and business logic for full payment lifecycle management.
"""

from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, F, Sum, Count, Avg, Max, Min
from django.core.exceptions import ValidationError
from decimal import Decimal
import uuid
import json
import logging
from typing import Optional, List, Tuple, Dict, Any, Union
from datetime import timedelta, date, datetime

from apps.users.models import User
from apps.groups.models import Group
from apps.contributions.models import Contribution
from apps.common.constants import PaymentStatus, PaymentMethod, PayoutStatus
from apps.common.utils import format_currency, calculate_platform_fee, get_current_time
from apps.common.exceptions import ValidationError as CustomValidationError

logger = logging.getLogger(__name__)


# ============================================================================
# PAYMENT MODEL
# ============================================================================

class Payment(models.Model):
    """
    Main Payment model representing a payment made by a user.

    Fields:
    - user: The user making the payment
    - group: The group the payment is for
    - contribution: Optional contribution this payment is linked to
    - amount: Payment amount
    - payment_method: Method used (telebirr, chapa, bank_transfer, cash, mobile_money, card)
    - gateway: Payment gateway used
    - reference: Unique payment reference
    - status: Payment status (initiated, pending, processing, completed, failed, cancelled, refunded, reversed, expired)
    - platform_fee: Platform fee deducted
    - gateway_fee: Gateway transaction fee
    - total_fee: Total fees
    - net_amount: Net amount after fees
    - paid_at: When payment was completed
    - expires_at: Expiry timestamp
    - webhook_received: Whether webhook was received
    - webhook_processed_at: When webhook was processed
    - retry_count: Number of retry attempts
    - error_message: Error message if failed
    - metadata: Additional metadata
    - created_by: User who created this payment
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Methods:
    - complete(): Mark payment as completed
    - fail(): Mark payment as failed
    - cancel(): Cancel the payment
    - refund(): Refund the payment
    - expire(): Mark as expired
    - retry(): Increment retry count
    - is_completed, is_pending, is_failed, is_refunded: Properties
    - can_be_cancelled, can_be_refunded: Check methods
    - get_summary(): Get summary dictionary

    Indexes: user, group, status, reference, created_at, paid_at
    """

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User making the payment')
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name=_('group'),
        db_index=True,
        help_text=_('Group the payment is for')
    )

    contribution = models.ForeignKey(
        Contribution,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments',
        verbose_name=_('contribution'),
        help_text=_('Optional contribution this payment is linked to')
    )

    # ========================================================================
    # BASIC FIELDS
    # ========================================================================

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
        help_text=_('Payment method used')
    )

    gateway = models.CharField(
        _('gateway'),
        max_length=20,
        choices=[
            ('chapa', 'Chapa'),
            ('telebirr', 'Telebirr'),
            ('bank_transfer', 'Bank Transfer'),
            ('manual', 'Manual'),
        ],
        default='manual',
        help_text=_('Payment gateway used')
    )

    reference = models.CharField(
        _('reference'),
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_('Unique payment reference')
    )

    # ========================================================================
    # STATUS
    # ========================================================================

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=PaymentStatus.CHOICES,
        default=PaymentStatus.PENDING,
        db_index=True,
        help_text=_('Payment status')
    )

    # ========================================================================
    # FEES
    # ========================================================================

    platform_fee = models.DecimalField(
        _('platform fee'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Platform fee deducted')
    )

    gateway_fee = models.DecimalField(
        _('gateway fee'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Gateway transaction fee')
    )

    total_fee = models.DecimalField(
        _('total fee'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Total fees deducted')
    )

    net_amount = models.DecimalField(
        _('net amount'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Net amount after fees')
    )

    # ========================================================================
    # TIMESTAMPS
    # ========================================================================

    paid_at = models.DateTimeField(
        _('paid at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('When payment was completed')
    )

    expires_at = models.DateTimeField(
        _('expires at'),
        null=True,
        blank=True,
        help_text=_('Expiry timestamp for pending payments')
    )

    # ========================================================================
    # WEBHOOK
    # ========================================================================

    webhook_received = models.BooleanField(
        _('webhook received'),
        default=False,
        help_text=_('Whether webhook was received')
    )

    webhook_processed_at = models.DateTimeField(
        _('webhook processed at'),
        null=True,
        blank=True,
        help_text=_('When webhook was processed')
    )

    # ========================================================================
    # RETRY AND ERRORS
    # ========================================================================

    retry_count = models.PositiveIntegerField(
        _('retry count'),
        default=0,
        help_text=_('Number of retry attempts')
    )

    error_message = models.TextField(
        _('error message'),
        blank=True,
        null=True,
        help_text=_('Error message if failed')
    )

    # ========================================================================
    # METADATA
    # ========================================================================

    metadata = models.JSONField(
        _('metadata'),
        default=dict,
        help_text=_('Additional metadata')
    )

    # ========================================================================
    # REFUND
    # ========================================================================

    refund_reason = models.TextField(
        _('refund reason'),
        blank=True,
        null=True,
        help_text=_('Reason for refund')
    )

    refunded_at = models.DateTimeField(
        _('refunded at'),
        null=True,
        blank=True,
        help_text=_('When refund was processed')
    )

    # ========================================================================
    # METADATA
    # ========================================================================

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments_created',
        verbose_name=_('created by'),
        help_text=_('User who created this payment')
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
    # META
    # ========================================================================

    class Meta:
        db_table = 'payments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['group', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['reference']),
            models.Index(fields=['payment_method', 'status']),
            models.Index(fields=['paid_at', 'status']),
        ]
        verbose_name = _('payment')
        verbose_name_plural = _('payments')

    def __str__(self):
        return f"Payment #{self.id} - {self.reference} - {self.user.email}"

    def save(self, *args, **kwargs):
        """Override save to auto-calculate fees and set expiry."""
        if not self.reference:
            self.reference = self._generate_reference()

        if not self.expires_at and self.status == PaymentStatus.PENDING:
            self.expires_at = timezone.now() + timedelta(hours=24)

        # Calculate fees if not set
        if self.amount and not self.total_fee:
            self.platform_fee = calculate_platform_fee(self.amount)
            self.gateway_fee = self._calculate_gateway_fee()
            self.total_fee = self.platform_fee + self.gateway_fee
            self.net_amount = self.amount - self.total_fee

        # Set paid_at when completed
        if self.status == PaymentStatus.COMPLETED and not self.paid_at:
            self.paid_at = timezone.now()

        super().save(*args, **kwargs)

        # Invalidate cache
        from django.core.cache import cache
        cache.delete(f'payment_{self.id}')
        cache.delete(f'payment_{self.reference}')
        cache.delete(f'user_payments_{self.user.id}')
        cache.delete(f'group_payments_{self.group.id}')

    def _generate_reference(self) -> str:
        """Generate a unique payment reference."""
        import uuid
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        unique_id = str(uuid.uuid4()).replace('-', '')[:8].upper()
        return f"PAY-{timestamp}-{unique_id}"

    def _calculate_gateway_fee(self) -> Decimal:
        """Calculate gateway fee based on gateway type."""
        fee_rates = {
            'chapa': Decimal('0.025'),      # 2.5%
            'telebirr': Decimal('0.015'),   # 1.5%
            'bank_transfer': Decimal('0.005'), # 0.5%
            'manual': Decimal('0.00'),
        }
        rate = fee_rates.get(self.gateway, Decimal('0.02'))
        fee = self.amount * rate
        return fee.quantize(Decimal('0.01'))

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_pending(self) -> bool:
        return self.status == PaymentStatus.PENDING

    @property
    def is_processing(self) -> bool:
        return self.status == PaymentStatus.PROCESSING

    @property
    def is_completed(self) -> bool:
        return self.status == PaymentStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == PaymentStatus.FAILED

    @property
    def is_cancelled(self) -> bool:
        return self.status == PaymentStatus.CANCELLED

    @property
    def is_refunded(self) -> bool:
        return self.status == PaymentStatus.REFUNDED

    @property
    def is_expired(self) -> bool:
        return self.status == PaymentStatus.EXPIRED

    @property
    def is_reversed(self) -> bool:
        return self.status == PaymentStatus.REVERSED

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def can_be_cancelled(self) -> bool:
        return self.status in [PaymentStatus.PENDING, PaymentStatus.PROCESSING]

    @property
    def can_be_refunded(self) -> bool:
        return self.status == PaymentStatus.COMPLETED

    @property
    def can_be_retried(self) -> bool:
        return self.status == PaymentStatus.FAILED and self.retry_count < 3

    @property
    def is_expired_check(self) -> bool:
        if self.expires_at and self.status == PaymentStatus.PENDING:
            return timezone.now() > self.expires_at
        return False

    @property
    def total_amount_with_fees(self) -> Decimal:
        return self.amount + self.total_fee

    @property
    def amount_net_display(self) -> str:
        return format_currency(self.net_amount)

    # ========================================================================
    # BUSINESS METHODS
    # ========================================================================

    @transaction.atomic
    def complete(self, reference: Optional[str] = None) -> bool:
        """
        Mark payment as completed.

        Args:
            reference: Optional external reference

        Returns:
            bool: True if completed successfully
        """
        if self.status not in [PaymentStatus.PENDING, PaymentStatus.PROCESSING]:
            return False

        self.status = PaymentStatus.COMPLETED
        self.paid_at = timezone.now()
        if reference:
            self.metadata['external_reference'] = reference
        self.save(update_fields=['status', 'paid_at', 'metadata'])

        # Update linked contribution if exists
        if self.contribution:
            from apps.contributions.models import Contribution
            if self.contribution.status in ['pending', 'overdue']:
                self.contribution.mark_as_paid(
                    payment_method=self.payment_method,
                    reference=self.reference
                )

        logger.info(f'Payment {self.id} completed successfully')
        return True

    @transaction.atomic
    def fail(self, error_message: Optional[str] = None) -> bool:
        """
        Mark payment as failed.

        Args:
            error_message: Optional error message

        Returns:
            bool: True if failed successfully
        """
        if self.status == PaymentStatus.COMPLETED:
            return False

        self.status = PaymentStatus.FAILED
        if error_message:
            self.error_message = error_message
        self.save(update_fields=['status', 'error_message'])

        logger.warning(f'Payment {self.id} failed: {error_message}')
        return True

    @transaction.atomic
    def cancel(self) -> bool:
        """
        Cancel the payment.

        Returns:
            bool: True if cancelled successfully
        """
        if not self.can_be_cancelled:
            return False

        self.status = PaymentStatus.CANCELLED
        self.save(update_fields=['status'])

        logger.info(f'Payment {self.id} cancelled')
        return True

    @transaction.atomic
    def refund(self, reason: str = 'Refund requested') -> bool:
        """
        Refund the payment.

        Args:
            reason: Reason for refund

        Returns:
            bool: True if refunded successfully
        """
        if not self.can_be_refunded:
            return False

        self.status = PaymentStatus.REFUNDED
        self.refund_reason = reason
        self.refunded_at = timezone.now()
        self.save(update_fields=['status', 'refund_reason', 'refunded_at'])

        # Update linked contribution if exists
        if self.contribution and self.contribution.status == 'paid':
            self.contribution.refund(reason)

        logger.info(f'Payment {self.id} refunded: {reason}')
        return True

    @transaction.atomic
    def expire(self) -> bool:
        """
        Mark payment as expired.

        Returns:
            bool: True if expired successfully
        """
        if self.status != PaymentStatus.PENDING:
            return False

        self.status = PaymentStatus.EXPIRED
        self.save(update_fields=['status'])

        logger.info(f'Payment {self.id} expired')
        return True

    @transaction.atomic
    def retry(self) -> bool:
        """
        Increment retry count for a failed payment.

        Returns:
            bool: True if retry available
        """
        if not self.can_be_retried:
            return False

        self.retry_count += 1
        self.status = PaymentStatus.PENDING
        self.error_message = None
        self.save(update_fields=['retry_count', 'status', 'error_message'])

        logger.info(f'Payment {self.id} retry attempt {self.retry_count}')
        return True

    @transaction.atomic
    def reverse_payment(self, reason: str = 'Reversed') -> bool:
        """
        Reverse the payment (for failed/reversed transactions).

        Args:
            reason: Reason for reversal

        Returns:
            bool: True if reversed successfully
        """
        if self.status not in [PaymentStatus.PENDING, PaymentStatus.PROCESSING, PaymentStatus.FAILED]:
            return False

        self.status = PaymentStatus.REVERSED
        self.error_message = reason
        self.save(update_fields=['status', 'error_message'])

        logger.info(f'Payment {self.id} reversed: {reason}')
        return True

    # ========================================================================
    # SUMMARY METHODS
    # ========================================================================

    def get_summary(self) -> Dict[str, Any]:
        """Get summary dictionary for the payment."""
        return {
            'id': self.id,
            'reference': self.reference,
            'user_id': self.user.id,
            'user_name': self.user.full_name,
            'user_email': self.user.email,
            'group_id': self.group.id,
            'group_name': self.group.name,
            'contribution_id': self.contribution.id if self.contribution else None,
            'amount': float(self.amount),
            'payment_method': self.payment_method,
            'gateway': self.gateway,
            'status': self.status,
            'status_display': self.get_status_display(),
            'platform_fee': float(self.platform_fee),
            'gateway_fee': float(self.gateway_fee),
            'total_fee': float(self.total_fee),
            'net_amount': float(self.net_amount),
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'error_message': self.error_message,
        }

    def get_detailed_summary(self) -> Dict[str, Any]:
        """Get detailed summary including transactions."""
        summary = self.get_summary()
        transactions = self.transactions.all()
        summary['transactions'] = [
            {
                'id': t.id,
                'transaction_id': t.transaction_id,
                'status': t.status,
                'amount': float(t.amount),
                'created_at': t.created_at.isoformat() if t.created_at else None,
            }
            for t in transactions
        ]
        return summary


# ============================================================================
# PAYMENT TRANSACTION MODEL
# ============================================================================

class PaymentTransaction(models.Model):
    """
    Transaction record for each payment attempt.
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name=_('payment'),
        db_index=True,
        help_text=_('Payment this transaction belongs to')
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='payment_transactions',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User who initiated the transaction')
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='payment_transactions',
        verbose_name=_('group'),
        db_index=True,
        help_text=_('Group the transaction is for')
    )

    amount = models.DecimalField(
        _('amount'),
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text=_('Transaction amount')
    )

    gateway = models.CharField(
        _('gateway'),
        max_length=20,
        choices=[
            ('chapa', 'Chapa'),
            ('telebirr', 'Telebirr'),
            ('bank_transfer', 'Bank Transfer'),
            ('manual', 'Manual'),
        ],
        default='manual',
        help_text=_('Gateway used')
    )

    transaction_id = models.CharField(
        _('transaction ID'),
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_('Unique transaction ID from gateway')
    )

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
            ('refunded', 'Refunded'),
        ],
        default='pending',
        db_index=True,
        help_text=_('Transaction status')
    )

    request_payload = models.JSONField(
        _('request payload'),
        default=dict,
        help_text=_('Request payload sent to gateway')
    )

    response_payload = models.JSONField(
        _('response payload'),
        default=dict,
        help_text=_('Response payload from gateway')
    )

    error_message = models.TextField(
        _('error message'),
        blank=True,
        null=True,
        help_text=_('Error message if failed')
    )

    initiated_at = models.DateTimeField(
        _('initiated at'),
        default=timezone.now,
        db_index=True,
        help_text=_('When transaction was initiated')
    )

    completed_at = models.DateTimeField(
        _('completed at'),
        null=True,
        blank=True,
        help_text=_('When transaction was completed')
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
        db_table = 'payment_transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['payment', 'status']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['transaction_id']),
        ]
        verbose_name = _('payment transaction')
        verbose_name_plural = _('payment transactions')

    def __str__(self):
        return f"Transaction #{self.id} - {self.transaction_id}"

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            import uuid
            self.transaction_id = str(uuid.uuid4()).replace('-', '')[:16].upper()

        if self.status == 'completed' and not self.completed_at:
            self.completed_at = timezone.now()

        super().save(*args, **kwargs)

    @property
    def is_completed(self) -> bool:
        return self.status == 'completed'

    @property
    def is_failed(self) -> bool:
        return self.status == 'failed'

    @property
    def is_pending(self) -> bool:
        return self.status == 'pending'


# ============================================================================
# PAYOUT MODEL
# ============================================================================

class Payout(models.Model):
    """
    Payout model for distributing funds to group winners.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='payouts',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User receiving the payout')
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='payouts',
        verbose_name=_('group'),
        db_index=True,
        help_text=_('Group the payout is from')
    )

    winner_history = models.ForeignKey(
        'groups.GroupWinnerHistory',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payouts',
        verbose_name=_('winner history'),
        help_text=_('Winner history entry this payout is for')
    )

    amount = models.DecimalField(
        _('amount'),
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text=_('Payout amount')
    )

    payout_method = models.CharField(
        _('payout method'),
        max_length=20,
        choices=[
            ('bank_transfer', 'Bank Transfer'),
            ('telebirr', 'Telebirr'),
            ('cash', 'Cash'),
            ('mobile_money', 'Mobile Money'),
            ('cheque', 'Cheque'),
        ],
        default='bank_transfer',
        help_text=_('Payout method used')
    )

    reference = models.CharField(
        _('reference'),
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_('Unique payout reference')
    )

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=PayoutStatus.CHOICES,
        default=PayoutStatus.PENDING,
        db_index=True,
        help_text=_('Payout status')
    )

    platform_fee = models.DecimalField(
        _('platform fee'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Platform fee deducted')
    )

    gateway_fee = models.DecimalField(
        _('gateway fee'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Gateway transaction fee')
    )

    total_fee = models.DecimalField(
        _('total fee'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Total fees deducted')
    )

    net_amount = models.DecimalField(
        _('net amount'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Net amount after fees')
    )

    paid_at = models.DateTimeField(
        _('paid at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('When payout was processed')
    )

    reference_number = models.CharField(
        _('reference number'),
        max_length=100,
        blank=True,
        null=True,
        help_text=_('External reference number')
    )

    notes = models.TextField(
        _('notes'),
        blank=True,
        null=True,
        help_text=_('Additional notes')
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payouts_created',
        verbose_name=_('created by'),
        help_text=_('User who created this payout')
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
        db_table = 'payouts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['group', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['reference']),
            models.Index(fields=['paid_at', 'status']),
        ]
        verbose_name = _('payout')
        verbose_name_plural = _('payouts')

    def __str__(self):
        return f"Payout #{self.id} - {self.reference} - {self.user.email}"

    def save(self, *args, **kwargs):
        if not self.reference:
            import uuid
            timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
            unique_id = str(uuid.uuid4()).replace('-', '')[:8].upper()
            self.reference = f"POUT-{timestamp}-{unique_id}"

        if self.status == PayoutStatus.COMPLETED and not self.paid_at:
            self.paid_at = timezone.now()

        super().save(*args, **kwargs)

    @property
    def is_pending(self) -> bool:
        return self.status == PayoutStatus.PENDING

    @property
    def is_processing(self) -> bool:
        return self.status == PayoutStatus.PROCESSING

    @property
    def is_completed(self) -> bool:
        return self.status == PayoutStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == PayoutStatus.FAILED

    @property
    def is_cancelled(self) -> bool:
        return self.status == PayoutStatus.CANCELLED

    @property
    def is_partially_paid(self) -> bool:
        return self.status == PayoutStatus.PARTIALLY_PAID

    @property
    def is_on_hold(self) -> bool:
        return self.status == PayoutStatus.ON_HOLD

    @property
    def can_be_completed(self) -> bool:
        return self.status in [PayoutStatus.PENDING, PayoutStatus.PROCESSING]

    @property
    def can_be_cancelled(self) -> bool:
        return self.status in [PayoutStatus.PENDING, PayoutStatus.PROCESSING, PayoutStatus.ON_HOLD]

    @property
    def can_be_failed(self) -> bool:
        return self.status in [PayoutStatus.PENDING, PayoutStatus.PROCESSING]

    @transaction.atomic
    def complete(self, reference_number: Optional[str] = None) -> bool:
        """Mark payout as completed."""
        if not self.can_be_completed:
            return False

        self.status = PayoutStatus.COMPLETED
        self.paid_at = timezone.now()
        if reference_number:
            self.reference_number = reference_number
        self.save(update_fields=['status', 'paid_at', 'reference_number'])

        # Update winner history if exists
        if self.winner_history:
            self.winner_history.mark_paid(self.reference)

        logger.info(f'Payout {self.id} completed')
        return True

    @transaction.atomic
    def fail(self, reason: str = 'Failed') -> bool:
        """Mark payout as failed."""
        if not self.can_be_failed:
            return False

        self.status = PayoutStatus.FAILED
        self.notes = reason
        self.save(update_fields=['status', 'notes'])

        logger.warning(f'Payout {self.id} failed: {reason}')
        return True

    @transaction.atomic
    def cancel(self, reason: str = 'Cancelled') -> bool:
        """Cancel the payout."""
        if not self.can_be_cancelled:
            return False

        self.status = PayoutStatus.CANCELLED
        self.notes = reason
        self.save(update_fields=['status', 'notes'])

        logger.info(f'Payout {self.id} cancelled: {reason}')
        return True

    @transaction.atomic
    def put_on_hold(self, reason: str = 'On hold') -> bool:
        """Put payout on hold."""
        if self.status not in [PayoutStatus.PENDING, PayoutStatus.PROCESSING]:
            return False

        self.status = PayoutStatus.ON_HOLD
        self.notes = reason
        self.save(update_fields=['status', 'notes'])

        logger.info(f'Payout {self.id} put on hold: {reason}')
        return True

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of the payout."""
        return {
            'id': self.id,
            'reference': self.reference,
            'user_id': self.user.id,
            'user_name': self.user.full_name,
            'user_email': self.user.email,
            'group_id': self.group.id,
            'group_name': self.group.name,
            'amount': float(self.amount),
            'payout_method': self.payout_method,
            'status': self.status,
            'status_display': self.get_status_display(),
            'platform_fee': float(self.platform_fee),
            'gateway_fee': float(self.gateway_fee),
            'total_fee': float(self.total_fee),
            'net_amount': float(self.net_amount),
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'reference_number': self.reference_number,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# PAYMENT GATEWAY LOG MODEL
# ============================================================================

class PaymentGatewayLog(models.Model):
    """
    Log of API calls to payment gateways.
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='gateway_logs',
        verbose_name=_('payment'),
        db_index=True,
        help_text=_('Payment this log belongs to')
    )

    gateway = models.CharField(
        _('gateway'),
        max_length=20,
        choices=[
            ('chapa', 'Chapa'),
            ('telebirr', 'Telebirr'),
            ('bank_transfer', 'Bank Transfer'),
            ('manual', 'Manual'),
        ],
        default='manual',
        help_text=_('Gateway used')
    )

    endpoint = models.CharField(
        _('endpoint'),
        max_length=255,
        help_text=_('API endpoint called')
    )

    method = models.CharField(
        _('method'),
        max_length=10,
        choices=[
            ('GET', 'GET'),
            ('POST', 'POST'),
            ('PUT', 'PUT'),
            ('PATCH', 'PATCH'),
            ('DELETE', 'DELETE'),
        ],
        default='POST',
        help_text=_('HTTP method used')
    )

    request_headers = models.JSONField(
        _('request headers'),
        default=dict,
        help_text=_('Request headers sent')
    )

    request_body = models.JSONField(
        _('request body'),
        default=dict,
        help_text=_('Request body sent')
    )

    response_status = models.IntegerField(
        _('response status'),
        null=True,
        blank=True,
        help_text=_('HTTP status code received')
    )

    response_headers = models.JSONField(
        _('response headers'),
        default=dict,
        help_text=_('Response headers received')
    )

    response_body = models.JSONField(
        _('response body'),
        default=dict,
        help_text=_('Response body received')
    )

    error_message = models.TextField(
        _('error message'),
        blank=True,
        null=True,
        help_text=_('Error message if any')
    )

    duration_ms = models.IntegerField(
        _('duration ms'),
        null=True,
        blank=True,
        help_text=_('Request duration in milliseconds')
    )

    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )

    class Meta:
        db_table = 'payment_gateway_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['payment', 'created_at']),
            models.Index(fields=['gateway', 'created_at']),
        ]
        verbose_name = _('payment gateway log')
        verbose_name_plural = _('payment gateway logs')

    def __str__(self):
        return f"Gateway Log #{self.id} - {self.gateway} - {self.endpoint}"


# ============================================================================
# PAYMENT WEBHOOK LOG MODEL
# ============================================================================

class PaymentWebhookLog(models.Model):
    """
    Log of webhook events received from payment gateways.
    """

    gateway = models.CharField(
        _('gateway'),
        max_length=20,
        choices=[
            ('chapa', 'Chapa'),
            ('telebirr', 'Telebirr'),
            ('bank_transfer', 'Bank Transfer'),
            ('manual', 'Manual'),
        ],
        default='manual',
        help_text=_('Gateway that sent the webhook')
    )

    event_type = models.CharField(
        _('event type'),
        max_length=50,
        db_index=True,
        help_text=_('Type of webhook event')
    )

    payload = models.JSONField(
        _('payload'),
        default=dict,
        help_text=_('Webhook payload received')
    )

    headers = models.JSONField(
        _('headers'),
        default=dict,
        help_text=_('Request headers received')
    )

    signature = models.CharField(
        _('signature'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Webhook signature')
    )

    verified = models.BooleanField(
        _('verified'),
        default=False,
        db_index=True,
        help_text=_('Whether signature was verified')
    )

    processed = models.BooleanField(
        _('processed'),
        default=False,
        db_index=True,
        help_text=_('Whether webhook was processed')
    )

    processed_at = models.DateTimeField(
        _('processed at'),
        null=True,
        blank=True,
        help_text=_('When webhook was processed')
    )

    error_message = models.TextField(
        _('error message'),
        blank=True,
        null=True,
        help_text=_('Error message if processing failed')
    )

    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )

    class Meta:
        db_table = 'payment_webhook_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['gateway', 'created_at']),
            models.Index(fields=['event_type', 'processed']),
        ]
        verbose_name = _('payment webhook log')
        verbose_name_plural = _('payment webhook logs')

    def __str__(self):
        return f"Webhook Log #{self.id} - {self.gateway} - {self.event_type}"


# ============================================================================
# PAYMENT RECONCILIATION MODEL
# ============================================================================

class PaymentReconciliation(models.Model):
    """
    Reconciliation record for payment settlement.
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='reconciliations',
        verbose_name=_('payment'),
        db_index=True,
        help_text=_('Payment being reconciled')
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='payment_reconciliations',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User associated with reconciliation')
    )

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='payment_reconciliations',
        verbose_name=_('group'),
        db_index=True,
        help_text=_('Group associated with reconciliation')
    )

    external_reference = models.CharField(
        _('external reference'),
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        help_text=_('Reference from external system')
    )

    external_status = models.CharField(
        _('external status'),
        max_length=50,
        blank=True,
        null=True,
        help_text=_('Status from external system')
    )

    external_data = models.JSONField(
        _('external data'),
        default=dict,
        help_text=_('Additional data from reconciliation')
    )

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('matched', 'Matched'),
            ('failed', 'Failed'),
            ('discrepancy', 'Discrepancy'),
        ],
        default='pending',
        db_index=True,
        help_text=_('Reconciliation status')
    )

    discrepancy_reason = models.TextField(
        _('discrepancy reason'),
        blank=True,
        null=True,
        help_text=_('Reason for discrepancy')
    )

    reconciled_at = models.DateTimeField(
        _('reconciled at'),
        default=timezone.now,
        db_index=True,
        help_text=_('When reconciliation was performed')
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
        db_table = 'payment_reconciliations'
        ordering = ['-reconciled_at']
        indexes = [
            models.Index(fields=['payment', 'status']),
            models.Index(fields=['external_reference']),
            models.Index(fields=['status', 'reconciled_at']),
        ]
        verbose_name = _('payment reconciliation')
        verbose_name_plural = _('payment reconciliations')

    def __str__(self):
        return f"Reconciliation #{self.id} - Payment #{self.payment.id}"


# ============================================================================
# PAYMENT DISPUTE MODEL
# ============================================================================

class PaymentDispute(models.Model):
    """
    Dispute record for payment issues.
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='disputes',
        verbose_name=_('payment'),
        db_index=True,
        help_text=_('Payment under dispute')
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='payment_disputes',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User who raised the dispute')
    )

    amount = models.DecimalField(
        _('amount'),
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text=_('Disputed amount')
    )

    reason = models.CharField(
        _('reason'),
        max_length=20,
        choices=[
            ('unauthorized', 'Unauthorized Transaction'),
            ('fraudulent', 'Fraudulent Transaction'),
            ('incorrect_amount', 'Incorrect Amount'),
            ('duplicate', 'Duplicate Payment'),
            ('service_not_received', 'Service Not Received'),
            ('other', 'Other'),
        ],
        default='other',
        help_text=_('Reason for dispute')
    )

    description = models.TextField(
        _('description'),
        help_text=_('Detailed description of the dispute')
    )

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('investigating', 'Investigating'),
            ('resolved', 'Resolved'),
            ('rejected', 'Rejected'),
        ],
        default='pending',
        db_index=True,
        help_text=_('Dispute status')
    )

    resolution = models.TextField(
        _('resolution'),
        blank=True,
        null=True,
        help_text=_('Resolution details')
    )

    resolved_at = models.DateTimeField(
        _('resolved at'),
        null=True,
        blank=True,
        help_text=_('When dispute was resolved')
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='disputes_created',
        verbose_name=_('created by'),
        help_text=_('User who created this dispute')
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
        db_table = 'payment_disputes'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['payment', 'status']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]
        verbose_name = _('payment dispute')
        verbose_name_plural = _('payment disputes')

    def __str__(self):
        return f"Dispute #{self.id} - Payment #{self.payment.id}"


# ============================================================================
# SETTLEMENT MODEL
# ============================================================================

class Settlement(models.Model):
    """
    Settlement record for batch payments or payouts.
    """

    reference = models.CharField(
        _('reference'),
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_('Unique settlement reference')
    )

    type = models.CharField(
        _('type'),
        max_length=20,
        choices=[
            ('incoming', 'Incoming'),
            ('outgoing', 'Outgoing'),
        ],
        default='incoming',
        help_text=_('Type of settlement')
    )

    amount = models.DecimalField(
        _('amount'),
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text=_('Total settlement amount')
    )

    fee = models.DecimalField(
        _('fee'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Settlement fee')
    )

    net_amount = models.DecimalField(
        _('net amount'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Net amount after fees')
    )

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending',
        db_index=True,
        help_text=_('Settlement status')
    )

    gateway = models.CharField(
        _('gateway'),
        max_length=20,
        choices=[
            ('chapa', 'Chapa'),
            ('telebirr', 'Telebirr'),
            ('bank_transfer', 'Bank Transfer'),
            ('manual', 'Manual'),
        ],
        default='manual',
        help_text=_('Gateway used')
    )

    reference_number = models.CharField(
        _('reference number'),
        max_length=100,
        blank=True,
        null=True,
        help_text=_('External reference number')
    )

    settlement_date = models.DateTimeField(
        _('settlement date'),
        db_index=True,
        help_text=_('When settlement occurred')
    )

    notes = models.TextField(
        _('notes'),
        blank=True,
        null=True,
        help_text=_('Additional notes')
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='settlements_created',
        verbose_name=_('created by'),
        help_text=_('User who created this settlement')
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
        db_table = 'settlements'
        ordering = ['-settlement_date']
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['status', 'settlement_date']),
            models.Index(fields=['gateway', 'settlement_date']),
        ]
        verbose_name = _('settlement')
        verbose_name_plural = _('settlements')

    def __str__(self):
        return f"Settlement #{self.id} - {self.reference}"


# ============================================================================
# PAYMENT METHOD MODEL
# ============================================================================

class PaymentMethod(models.Model):
    """
    User's saved payment methods.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='payment_methods',
        verbose_name=_('user'),
        db_index=True,
        help_text=_('User who owns this payment method')
    )

    method_type = models.CharField(
        _('method type'),
        max_length=20,
        choices=PaymentMethod.CHOICES,
        help_text=_('Type of payment method')
    )

    provider = models.CharField(
        _('provider'),
        max_length=50,
        help_text=_('Provider name')
    )

    account_identifier = models.CharField(
        _('account identifier'),
        max_length=100,
        help_text=_('Account number or identifier')
    )

    account_name = models.CharField(
        _('account name'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Account holder name')
    )

    is_default = models.BooleanField(
        _('is default'),
        default=False,
        help_text=_('Whether this is the default payment method')
    )

    is_active = models.BooleanField(
        _('is active'),
        default=True,
        db_index=True,
        help_text=_('Whether this payment method is active')
    )

    token = models.CharField(
        _('token'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Gateway token for this payment method')
    )

    expires_at = models.DateTimeField(
        _('expires at'),
        null=True,
        blank=True,
        help_text=_('Expiry date for the payment method')
    )

    metadata = models.JSONField(
        _('metadata'),
        default=dict,
        help_text=_('Additional metadata')
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
        db_table = 'payment_methods'
        ordering = ['-is_default', '-created_at']
        indexes = [
            models.Index(fields=['user', 'method_type']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['token']),
        ]
        verbose_name = _('payment method')
        verbose_name_plural = _('payment methods')

    def __str__(self):
        return f"{self.method_type} - {self.account_identifier} ({self.user.email})"


# ============================================================================
# PAYMENT AUDIT MODEL
# ============================================================================

class PaymentAudit(models.Model):
    """
    Audit trail for payment actions.
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='audits',
        verbose_name=_('payment'),
        help_text=_('Payment being audited')
    )

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_audits',
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
        db_table = 'payment_audits'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['payment', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]
        verbose_name = _('payment audit')
        verbose_name_plural = _('payment audits')

    def __str__(self):
        return f"Payment Audit #{self.id} - {self.action} on payment #{self.payment.id}"