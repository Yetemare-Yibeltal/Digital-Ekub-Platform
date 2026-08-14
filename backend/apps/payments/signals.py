"""
Signals for the payments app.

This module provides signal handlers for all payment-related models:
- Payment: handle status changes, completion, refunds, and statistics
- Payout: handle status changes, completion, and notifications
- PaymentTransaction: handle transaction status updates
- PaymentGatewayLog: handle logging and monitoring
- PaymentWebhookLog: handle webhook processing events
- PaymentReconciliation: handle reconciliation updates
- PaymentDispute: handle dispute lifecycle events
- Settlement: handle settlement processing
- PaymentMethod: handle payment method management
- PaymentAudit: handle audit trail creation

All signal handlers include comprehensive logging, error handling,
cache invalidation, and integration with user/group statistics.
"""

import logging
import json
from django.db.models.signals import post_save, pre_save, pre_delete, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum, Count, F
from decimal import Decimal

from apps.users.models import User
from apps.groups.models import Group, GroupMember
from apps.common.utils import log_audit_event, get_current_time, format_currency
from apps.common.constants import PaymentStatus, PayoutStatus

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
from .tasks import update_payment_stats, process_webhook_events

logger = logging.getLogger(__name__)


# ============================================================================
# PAYMENT SIGNALS
# ============================================================================

@receiver(pre_save, sender=Payment)
def payment_pre_save_handler(sender, instance, **kwargs):
    """
    Handle pre-save events for Payment model:
    - Auto-generate reference if not set
    - Set expiry date for pending payments
    - Calculate fees if not set
    - Validate status transitions
    - Set paid_at when completed
    """
    # Auto-generate reference if not set
    if not instance.reference:
        instance.reference = instance._generate_reference()

    # Set expiry date for pending payments
    if instance.status == PaymentStatus.PENDING and not instance.expires_at:
        instance.expires_at = timezone.now() + timezone.timedelta(hours=24)

    # Calculate fees if not set
    if instance.amount and not instance.total_fee:
        from apps.common.utils import calculate_platform_fee
        instance.platform_fee = calculate_platform_fee(instance.amount)
        instance.gateway_fee = instance._calculate_gateway_fee()
        instance.total_fee = instance.platform_fee + instance.gateway_fee
        instance.net_amount = instance.amount - instance.total_fee

    # Set paid_at when completed
    if instance.status == PaymentStatus.COMPLETED and not instance.paid_at:
        instance.paid_at = timezone.now()

    # Validate status transition
    if instance.pk:
        try:
            old = Payment.objects.get(pk=instance.pk)
            if old.status != instance.status:
                allowed_transitions = {
                    PaymentStatus.PENDING: [PaymentStatus.PROCESSING, PaymentStatus.COMPLETED,
                                            PaymentStatus.FAILED, PaymentStatus.CANCELLED,
                                            PaymentStatus.EXPIRED],
                    PaymentStatus.PROCESSING: [PaymentStatus.COMPLETED, PaymentStatus.FAILED,
                                               PaymentStatus.CANCELLED],
                    PaymentStatus.COMPLETED: [PaymentStatus.REFUNDED],
                    PaymentStatus.FAILED: [PaymentStatus.PENDING],
                }
                allowed = allowed_transitions.get(old.status, [])
                if instance.status not in allowed:
                    raise ValueError(
                        f'Invalid status transition from {old.status} to {instance.status}'
                    )
                logger.info(f'Payment {instance.id} status changing from {old.status} to {instance.status}')
        except Payment.DoesNotExist:
            pass


@receiver(post_save, sender=Payment)
def payment_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for Payment model:
    - Invalidate cache
    - Update user statistics
    - Update group statistics
    - Create audit entry for status changes
    - Send notifications
    - Update contribution status if linked
    - Schedule stats update
    """
    # Invalidate cache
    cache.delete(f'payment_{instance.id}')
    cache.delete(f'payment_{instance.reference}')
    cache.delete(f'user_payments_{instance.user.id}')
    cache.delete(f'group_payments_{instance.group.id}')
    cache.delete(f'payment_stats_{instance.id}')

    if created:
        logger.info(f'Payment {instance.id} created by {instance.created_by}')
        log_audit_event(
            user_id=instance.created_by.id if instance.created_by else None,
            action='payment_created',
            resource='payment',
            resource_id=instance.id,
            details={
                'group_id': instance.group.id,
                'user_id': instance.user.id,
                'amount': float(instance.amount),
                'reference': instance.reference,
                'status': instance.status,
            }
        )

        # Send notification to user
        from apps.notifications.models import Notification
        Notification.objects.create(
            user=instance.user,
            notification_type='payment_initiated',
            title='Payment Initiated',
            message=f'Your payment of {format_currency(instance.amount)} has been initiated. Reference: {instance.reference}',
            payment=instance,
            group=instance.group,
            is_read=False,
        )

        # If payment is completed immediately, handle accordingly
        if instance.status == PaymentStatus.COMPLETED:
            _handle_completed_payment(instance)

    else:
        # Check if status changed
        try:
            old = Payment.objects.get(pk=instance.pk)
            if old.status != instance.status:
                # Status changed
                log_audit_event(
                    user_id=instance.created_by.id if instance.created_by else None,
                    action='payment_status_changed',
                    resource='payment',
                    resource_id=instance.id,
                    details={
                        'old_status': old.status,
                        'new_status': instance.status,
                        'group_id': instance.group.id,
                        'user_id': instance.user.id,
                    }
                )

                # Handle specific status changes
                if instance.status == PaymentStatus.COMPLETED:
                    _handle_completed_payment(instance)
                elif instance.status == PaymentStatus.FAILED:
                    _handle_failed_payment(instance, old)
                elif instance.status == PaymentStatus.REFUNDED:
                    _handle_refunded_payment(instance, old)
                elif instance.status == PaymentStatus.CANCELLED:
                    _handle_cancelled_payment(instance, old)

        except Payment.DoesNotExist:
            pass

    # Schedule stats update
    update_payment_stats.delay(instance.group.id)


def _handle_completed_payment(payment):
    """Handle completed payment actions."""
    from apps.notifications.models import Notification
    from apps.common.utils import send_email

    # Update contribution if linked
    if payment.contribution:
        if payment.contribution.status in ['pending', 'overdue']:
            payment.contribution.mark_as_paid(
                payment_method=payment.payment_method,
                reference=payment.reference
            )

    # Update user statistics
    user = payment.user
    user.total_contributed += payment.amount
    user.save(update_fields=['total_contributed'])

    # Send notification
    Notification.objects.create(
        user=payment.user,
        notification_type='payment_completed',
        title='Payment Completed',
        message=f'Your payment of {format_currency(payment.amount)} has been completed successfully.',
        payment=payment,
        group=payment.group,
        is_read=False,
    )

    send_email(
        to_email=payment.user.email,
        subject=f'Payment Completed - {payment.group.name}',
        message=f'Your payment of {format_currency(payment.amount)} has been completed successfully.\n\nReference: {payment.reference}',
        html_message=None,
    )

    logger.info(f'Payment {payment.id} completed, user notified')


def _handle_failed_payment(payment, old):
    """Handle failed payment actions."""
    from apps.notifications.models import Notification

    Notification.objects.create(
        user=payment.user,
        notification_type='payment_failed',
        title='Payment Failed',
        message=f'Your payment of {format_currency(payment.amount)} has failed. Please try again.',
        payment=payment,
        group=payment.group,
        is_read=False,
    )

    logger.info(f'Payment {payment.id} failed, user notified')


def _handle_refunded_payment(payment, old):
    """Handle refunded payment actions."""
    from apps.notifications.models import Notification

    Notification.objects.create(
        user=payment.user,
        notification_type='payment_refunded',
        title='Payment Refunded',
        message=f'Your payment of {format_currency(payment.amount)} has been refunded.',
        payment=payment,
        group=payment.group,
        is_read=False,
    )

    # Update contribution if linked
    if payment.contribution and payment.contribution.status == 'paid':
        payment.contribution.refund(payment.refund_reason)

    logger.info(f'Payment {payment.id} refunded, user notified')


def _handle_cancelled_payment(payment, old):
    """Handle cancelled payment actions."""
    from apps.notifications.models import Notification

    Notification.objects.create(
        user=payment.user,
        notification_type='payment_cancelled',
        title='Payment Cancelled',
        message=f'Your payment of {format_currency(payment.amount)} has been cancelled.',
        payment=payment,
        group=payment.group,
        is_read=False,
    )

    logger.info(f'Payment {payment.id} cancelled, user notified')


@receiver(pre_delete, sender=Payment)
def payment_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for Payment model:
    - Prevent deletion of completed payments
    - Enforce soft delete instead of hard delete
    """
    if instance.status in [PaymentStatus.COMPLETED, PaymentStatus.REFUNDED]:
        raise ValueError('Cannot delete completed or refunded payments.')

    if not instance.deleted_at:
        instance.deleted_at = timezone.now()
        instance.save(update_fields=['deleted_at'])
        logger.warning(f'Hard delete attempted on payment {instance.id}, converted to soft delete')
        raise Exception('Use soft delete by setting deleted_at instead of delete()')


@receiver(post_delete, sender=Payment)
def payment_post_delete_handler(sender, instance, **kwargs):
    """
    Handle post-delete events for Payment model:
    - Clean up cache
    - Log audit event
    """
    cache.delete(f'payment_{instance.id}')
    cache.delete(f'payment_{instance.reference}')
    cache.delete(f'user_payments_{instance.user.id}')
    cache.delete(f'group_payments_{instance.group.id}')
    logger.info(f'Payment {instance.id} permanently deleted')


# ============================================================================
# PAYOUT SIGNALS
# ============================================================================

@receiver(pre_save, sender=Payout)
def payout_pre_save_handler(sender, instance, **kwargs):
    """
    Handle pre-save events for Payout model:
    - Auto-generate reference if not set
    - Calculate fees if not set
    - Set paid_at when completed
    - Validate status transitions
    """
    if not instance.reference:
        import uuid
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        unique_id = str(uuid.uuid4()).replace('-', '')[:8].upper()
        instance.reference = f"POUT-{timestamp}-{unique_id}"

    if instance.amount and not instance.total_fee:
        from apps.common.utils import calculate_platform_fee
        instance.platform_fee = calculate_platform_fee(instance.amount)
        instance.gateway_fee = instance.amount * Decimal('0.005')
        instance.total_fee = instance.platform_fee + instance.gateway_fee
        instance.net_amount = instance.amount - instance.total_fee

    if instance.status == PayoutStatus.COMPLETED and not instance.paid_at:
        instance.paid_at = timezone.now()

    if instance.pk:
        try:
            old = Payout.objects.get(pk=instance.pk)
            if old.status != instance.status:
                allowed_transitions = {
                    PayoutStatus.PENDING: [PayoutStatus.PROCESSING, PayoutStatus.COMPLETED,
                                           PayoutStatus.FAILED, PayoutStatus.CANCELLED,
                                           PayoutStatus.ON_HOLD],
                    PayoutStatus.PROCESSING: [PayoutStatus.COMPLETED, PayoutStatus.FAILED,
                                              PayoutStatus.CANCELLED, PayoutStatus.ON_HOLD],
                    PayoutStatus.COMPLETED: [],
                    PayoutStatus.ON_HOLD: [PayoutStatus.PENDING, PayoutStatus.PROCESSING,
                                           PayoutStatus.CANCELLED],
                    PayoutStatus.FAILED: [PayoutStatus.PENDING],
                }
                allowed = allowed_transitions.get(old.status, [])
                if instance.status not in allowed:
                    raise ValueError(
                        f'Invalid status transition from {old.status} to {instance.status}'
                    )
        except Payout.DoesNotExist:
            pass


@receiver(post_save, sender=Payout)
def payout_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for Payout model:
    - Invalidate cache
    - Update user statistics
    - Create audit entry for status changes
    - Send notifications
    - Update winner history if linked
    """
    cache.delete(f'payout_{instance.id}')
    cache.delete(f'payout_{instance.reference}')
    cache.delete(f'user_payouts_{instance.user.id}')
    cache.delete(f'group_payouts_{instance.group.id}')

    if created:
        logger.info(f'Payout {instance.id} created by {instance.created_by}')
        log_audit_event(
            user_id=instance.created_by.id if instance.created_by else None,
            action='payout_created',
            resource='payout',
            resource_id=instance.id,
            details={
                'group_id': instance.group.id,
                'user_id': instance.user.id,
                'amount': float(instance.amount),
                'reference': instance.reference,
            }
        )

        # Send notification
        from apps.notifications.models import Notification
        Notification.objects.create(
            user=instance.user,
            notification_type='payout_initiated',
            title='Payout Initiated',
            message=f'A payout of {format_currency(instance.amount)} has been initiated for you.',
            payout=instance,
            group=instance.group,
            is_read=False,
        )

    else:
        try:
            old = Payout.objects.get(pk=instance.pk)
            if old.status != instance.status:
                log_audit_event(
                    user_id=instance.created_by.id if instance.created_by else None,
                    action='payout_status_changed',
                    resource='payout',
                    resource_id=instance.id,
                    details={
                        'old_status': old.status,
                        'new_status': instance.status,
                        'group_id': instance.group.id,
                        'user_id': instance.user.id,
                    }
                )

                # Handle specific status changes
                if instance.status == PayoutStatus.COMPLETED:
                    _handle_completed_payout(instance)
                elif instance.status == PayoutStatus.FAILED:
                    _handle_failed_payout(instance)
                elif instance.status == PayoutStatus.CANCELLED:
                    _handle_cancelled_payout(instance)

        except Payout.DoesNotExist:
            pass


def _handle_completed_payout(payout):
    """Handle completed payout actions."""
    from apps.notifications.models import Notification
    from apps.common.utils import send_email

    # Update winner history if linked
    if payout.winner_history:
        payout.winner_history.mark_paid(payout.reference)

    # Update user statistics
    user = payout.user
    user.total_received += payout.amount
    user.save(update_fields=['total_received'])

    # Send notification
    Notification.objects.create(
        user=payout.user,
        notification_type='payout_completed',
        title='Payout Completed',
        message=f'Your payout of {format_currency(payout.amount)} has been completed.',
        payout=payout,
        group=payout.group,
        is_read=False,
    )

    send_email(
        to_email=payout.user.email,
        subject=f'Payout Completed - {payout.group.name}',
        message=f'Your payout of {format_currency(payout.amount)} has been completed.\n\nReference: {payout.reference}',
        html_message=None,
    )

    logger.info(f'Payout {payout.id} completed, user notified')


def _handle_failed_payout(payout):
    """Handle failed payout actions."""
    from apps.notifications.models import Notification

    Notification.objects.create(
        user=payout.user,
        notification_type='payout_failed',
        title='Payout Failed',
        message=f'Your payout of {format_currency(payout.amount)} has failed. Please contact support.',
        payout=payout,
        group=payout.group,
        is_read=False,
    )

    logger.info(f'Payout {payout.id} failed, user notified')


def _handle_cancelled_payout(payout):
    """Handle cancelled payout actions."""
    from apps.notifications.models import Notification

    Notification.objects.create(
        user=payout.user,
        notification_type='payout_cancelled',
        title='Payout Cancelled',
        message=f'Your payout of {format_currency(payout.amount)} has been cancelled.',
        payout=payout,
        group=payout.group,
        is_read=False,
    )

    logger.info(f'Payout {payout.id} cancelled, user notified')


@receiver(pre_delete, sender=Payout)
def payout_pre_delete_handler(sender, instance, **kwargs):
    """Handle pre-delete events for Payout model."""
    if instance.status in [PayoutStatus.COMPLETED]:
        raise ValueError('Cannot delete completed payouts.')

    if not instance.deleted_at:
        instance.deleted_at = timezone.now()
        instance.save(update_fields=['deleted_at'])
        logger.warning(f'Hard delete attempted on payout {instance.id}, converted to soft delete')
        raise Exception('Use soft delete by setting deleted_at instead of delete()')


# ============================================================================
# PAYMENT TRANSACTION SIGNALS
# ============================================================================

@receiver(post_save, sender=PaymentTransaction)
def payment_transaction_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for PaymentTransaction model:
    - Invalidate cache
    - Update payment status if transaction completes
    - Create audit entry
    """
    cache.delete(f'transaction_{instance.id}')
    cache.delete(f'payment_transactions_{instance.payment.id}')

    if created:
        logger.info(f'Transaction {instance.id} created for payment {instance.payment.id}')

    # If transaction completes, update payment status
    if instance.status == 'completed' and instance.payment.status != PaymentStatus.COMPLETED:
        instance.payment.complete()


# ============================================================================
# PAYMENT GATEWAY LOG SIGNALS
# ============================================================================

@receiver(post_save, sender=PaymentGatewayLog)
def payment_gateway_log_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for PaymentGatewayLog model:
    - Invalidate cache
    - Log monitoring alerts for failures
    """
    if created:
        cache.delete(f'gateway_logs_{instance.payment.id}')

        # Alert on gateway errors
        if instance.response_status and instance.response_status >= 400:
            logger.warning(
                f'Gateway error: {instance.gateway} - {instance.endpoint} '
                f'returned {instance.response_status} for payment {instance.payment.id}'
            )


# ============================================================================
# PAYMENT WEBHOOK LOG SIGNALS
# ============================================================================

@receiver(post_save, sender=PaymentWebhookLog)
def payment_webhook_log_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for PaymentWebhookLog model:
    - Process webhook if verified and not processed
    - Invalidate cache
    """
    if created:
        cache.delete(f'webhook_logs_{instance.gateway}')

        # Process verified webhook
        if instance.verified and not instance.processed:
            process_webhook_events.delay(instance.id)


# ============================================================================
# PAYMENT RECONCILIATION SIGNALS
# ============================================================================

@receiver(post_save, sender=PaymentReconciliation)
def payment_reconciliation_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for PaymentReconciliation model:
    - Update payment status if matched
    - Invalidate cache
    """
    cache.delete(f'reconciliation_{instance.id}')
    cache.delete(f'payment_reconciliations_{instance.payment.id}')

    if created:
        logger.info(f'Reconciliation {instance.id} created for payment {instance.payment.id}')

    # If matched, update payment status
    if instance.status == 'matched' and instance.payment.status == PaymentStatus.PENDING:
        instance.payment.complete()


# ============================================================================
# PAYMENT DISPUTE SIGNALS
# ============================================================================

@receiver(post_save, sender=PaymentDispute)
def payment_dispute_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for PaymentDispute model:
    - Send notifications on status changes
    - Invalidate cache
    """
    cache.delete(f'dispute_{instance.id}')
    cache.delete(f'payment_disputes_{instance.payment.id}')

    if created:
        logger.info(f'Dispute {instance.id} created for payment {instance.payment.id}')
        from apps.notifications.models import Notification
        Notification.objects.create(
            user=instance.payment.user,
            notification_type='dispute_created',
            title='Dispute Created',
            message=f'A dispute has been created for your payment of {format_currency(instance.amount)}.',
            dispute=instance,
            is_read=False,
        )

    else:
        try:
            old = PaymentDispute.objects.get(pk=instance.pk)
            if old.status != instance.status:
                from apps.notifications.models import Notification
                Notification.objects.create(
                    user=instance.payment.user,
                    notification_type=f'dispute_{instance.status}',
                    title=f'Dispute {instance.get_status_display()}',
                    message=f'Your dispute for {format_currency(instance.amount)} has been {instance.get_status_display().lower()}.',
                    dispute=instance,
                    is_read=False,
                )
        except PaymentDispute.DoesNotExist:
            pass


# ============================================================================
# SETTLEMENT SIGNALS
# ============================================================================

@receiver(post_save, sender=Settlement)
def settlement_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for Settlement model:
    - Invalidate cache
    - Log settlement events
    """
    cache.delete(f'settlement_{instance.id}')
    cache.delete(f'settlements_{instance.gateway}')

    if created:
        logger.info(f'Settlement {instance.id} created: {instance.reference}')
    else:
        try:
            old = Settlement.objects.get(pk=instance.pk)
            if old.status != instance.status:
                logger.info(f'Settlement {instance.id} status changed to {instance.status}')
        except Settlement.DoesNotExist:
            pass


# ============================================================================
# PAYMENT METHOD SIGNALS
# ============================================================================

@receiver(pre_save, sender=PaymentMethod)
def payment_method_pre_save_handler(sender, instance, **kwargs):
    """
    Handle pre-save events for PaymentMethod model:
    - Ensure only one default payment method per user
    """
    if instance.is_default:
        # Reset other default payment methods for this user
        PaymentMethod.objects.filter(
            user=instance.user,
            is_default=True
        ).exclude(id=instance.id).update(is_default=False)


@receiver(post_save, sender=PaymentMethod)
def payment_method_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for PaymentMethod model:
    - Invalidate cache
    """
    cache.delete(f'payment_methods_{instance.user.id}')
    cache.delete(f'payment_method_{instance.id}')

    if created:
        logger.info(f'Payment method {instance.id} created for user {instance.user.id}')


@receiver(pre_delete, sender=PaymentMethod)
def payment_method_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for PaymentMethod model:
    - Prevent deletion of default payment method if only one
    """
    if instance.is_default:
        count = PaymentMethod.objects.filter(user=instance.user, is_active=True).count()
        if count <= 1:
            raise ValueError('Cannot delete the only payment method. Add another first.')


@receiver(post_delete, sender=PaymentMethod)
def payment_method_post_delete_handler(sender, instance, **kwargs):
    """
    Handle post-delete events for PaymentMethod model:
    - Clean up cache
    """
    cache.delete(f'payment_methods_{instance.user.id}')
    cache.delete(f'payment_method_{instance.id}')
    logger.info(f'Payment method {instance.id} deleted for user {instance.user.id}')


# ============================================================================
# PAYMENT AUDIT SIGNALS
# ============================================================================

@receiver(post_save, sender=PaymentAudit)
def payment_audit_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for PaymentAudit model:
    - Invalidate cache
    """
    if created:
        cache.delete(f'payment_audits_{instance.payment.id}')
        logger.debug(f'Audit {instance.id} created for payment {instance.payment.id}')


# ============================================================================
# CROSS-MODEL SIGNALS FOR STATISTICS
# ============================================================================

@receiver(post_save, sender=Payment)
def payment_group_statistics_handler(sender, instance, created, **kwargs):
    """
    Update group statistics when payment is created or updated.
    """
    group = instance.group
    with transaction.atomic():
        total_payments = Payment.objects.filter(
            group=group,
            deleted_at__isnull=True
        ).count()

        total_completed = Payment.objects.filter(
            group=group,
            status=PaymentStatus.COMPLETED,
            deleted_at__isnull=True
        ).count()

        total_amount = Payment.objects.filter(
            group=group,
            status=PaymentStatus.COMPLETED,
            deleted_at__isnull=True
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        total_fees = Payment.objects.filter(
            group=group,
            status=PaymentStatus.COMPLETED,
            deleted_at__isnull=True
        ).aggregate(total=Sum('total_fee'))['total'] or Decimal('0.00')

        total_net = Payment.objects.filter(
            group=group,
            status=PaymentStatus.COMPLETED,
            deleted_at__isnull=True
        ).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

        if hasattr(group, 'total_payments'):
            group.total_payments = total_payments
            group.total_payments_completed = total_completed
            group.total_payments_amount = total_amount
            group.total_payments_fees = total_fees
            group.total_payments_net = total_net
            group.save(update_fields=[
                'total_payments',
                'total_payments_completed',
                'total_payments_amount',
                'total_payments_fees',
                'total_payments_net'
            ])


@receiver(post_save, sender=Payout)
def payout_group_statistics_handler(sender, instance, created, **kwargs):
    """
    Update group statistics when payout is created or updated.
    """
    group = instance.group
    with transaction.atomic():
        total_payouts = Payout.objects.filter(
            group=group,
            deleted_at__isnull=True
        ).count()

        total_completed = Payout.objects.filter(
            group=group,
            status=PayoutStatus.COMPLETED,
            deleted_at__isnull=True
        ).count()

        total_amount = Payout.objects.filter(
            group=group,
            status=PayoutStatus.COMPLETED,
            deleted_at__isnull=True
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        if hasattr(group, 'total_payouts'):
            group.total_payouts = total_payouts
            group.total_payouts_completed = total_completed
            group.total_payouts_amount = total_amount
            group.save(update_fields=[
                'total_payouts',
                'total_payouts_completed',
                'total_payouts_amount'
            ])


# ============================================================================
# CACHE INVALIDATION UTILITY
# ============================================================================

def invalidate_payment_cache(payment_id: int):
    """Utility to invalidate all cache keys related to a payment."""
    keys = [
        f'payment_{payment_id}',
        f'payment_detail_{payment_id}',
        f'payment_stats_{payment_id}',
        f'payment_transactions_{payment_id}',
        f'payment_reconciliations_{payment_id}',
        f'payment_disputes_{payment_id}',
        f'payment_gateway_logs_{payment_id}',
    ]
    for key in keys:
        cache.delete(key)
    logger.debug(f'Cache invalidated for payment {payment_id}')


# ============================================================================
# LOGGING UTILITY
# ============================================================================

def log_payment_action(payment, action, user=None, details=None):
    """Utility to log a payment action with consistent format."""
    log_data = {
        'payment_id': payment.id,
        'payment_reference': payment.reference,
        'group_id': payment.group.id,
        'user_id': payment.user.id,
        'action': action,
        'user_id_actor': user.id if user else None,
        'timestamp': timezone.now().isoformat(),
        'details': details or {}
    }
    logger.info(f'PAYMENT_ACTION: {json.dumps(log_data)}')


# ============================================================================
# SIGNAL DISPATCHER (for manual triggering)
# ============================================================================

def dispatch_payment_signals(payment_id, signal_name, *args, **kwargs):
    """
    Manually dispatch payment signals for testing or admin actions.
    """
    try:
        payment = Payment.objects.get(id=payment_id)
    except Payment.DoesNotExist:
        return None

    if signal_name == 'post_save':
        payment_post_save_handler(Payment, payment, created=False, **kwargs)
    elif signal_name == 'pre_save':
        payment_pre_save_handler(Payment, payment, **kwargs)
    elif signal_name == 'pre_delete':
        payment_pre_delete_handler(Payment, payment, **kwargs)
    elif signal_name == 'post_delete':
        payment_post_delete_handler(Payment, payment, **kwargs)
    return True


def dispatch_payout_signals(payout_id, signal_name, *args, **kwargs):
    """
    Manually dispatch payout signals for testing or admin actions.
    """
    try:
        payout = Payout.objects.get(id=payout_id)
    except Payout.DoesNotExist:
        return None

    if signal_name == 'post_save':
        payout_post_save_handler(Payout, payout, created=False, **kwargs)
    elif signal_name == 'pre_save':
        payout_pre_save_handler(Payout, payout, **kwargs)
    elif signal_name == 'pre_delete':
        payout_pre_delete_handler(Payout, payout, **kwargs)
    return True


# ============================================================================
# ERROR HANDLING WRAPPER
# ============================================================================

def handle_signal_error(func):
    """
    Decorator to catch and log errors in signal handlers.
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f'Error in signal handler {func.__name__}: {str(e)}', exc_info=True)
            raise
    return wrapper