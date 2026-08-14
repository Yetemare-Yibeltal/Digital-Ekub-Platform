"""
Signals for the contributions app.

This module provides signal handlers for all contribution-related models:
- Contribution: handle status changes, payment updates, and statistics
- ContributionPayment: handle payment completion and reconciliation
- ContributionReminder: handle reminder tracking and logging
- ContributionAudit: handle audit trail creation

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
from apps.common.constants import ContributionStatus, PaymentStatus

from .models import (
    Contribution,
    ContributionPayment,
    ContributionReminder,
    ContributionAudit,
)
from .tasks import update_contribution_stats, process_contribution_payments

logger = logging.getLogger(__name__)


# ============================================================================
# CONTRIBUTION SIGNALS
# ============================================================================

@receiver(pre_save, sender=Contribution)
def contribution_pre_save_handler(sender, instance, **kwargs):
    """
    Handle pre-save events for Contribution model:
    - Validate status transitions
    - Auto-calculate due_date from group
    - Auto-calculate days_overdue
    - Set created_by if not set
    - Validate contribution amount matches group
    - Calculate platform fees and net amount
    - Set paid_date when status changes to paid
    """
    # Set created_by if not set and we have a request context
    if not instance.created_by and hasattr(instance, '_current_user'):
        instance.created_by = instance._current_user

    # Auto-set due_date if not set and group has frequency
    if not instance.due_date and instance.group and instance.round is not None:
        from apps.contributions import get_contribution_due_date
        due = get_contribution_due_date(instance.group, instance.round)
        if due:
            instance.due_date = due

    # Validate amount matches group's contribution amount (unless special type)
    if instance.contribution_type == 'regular' and instance.group:
        if instance.amount != instance.group.contribution_amount:
            raise ValueError(
                f'Contribution amount {instance.amount} does not match group contribution amount {instance.group.contribution_amount}'
            )

    # Auto-calculate days overdue
    if instance.status == ContributionStatus.OVERDUE and instance.due_date:
        now = timezone.now()
        if now > instance.due_date:
            instance.days_overdue = (now - instance.due_date).days
        else:
            instance.days_overdue = 0

    # Calculate platform fee and net amount when paid
    if instance.status == ContributionStatus.PAID and instance.amount:
        from apps.common.utils import calculate_platform_fee
        instance.platform_fee = calculate_platform_fee(instance.amount)
        instance.net_amount = instance.amount - instance.platform_fee - instance.penalty_amount + instance.waived_amount

    # Set paid_date when status changes to paid
    if instance.status == ContributionStatus.PAID and not instance.paid_date:
        instance.paid_date = timezone.now()

    # Validate status transition if this is an update
    if instance.pk:
        try:
            old = Contribution.objects.get(pk=instance.pk)
            if old.status != instance.status:
                if not instance.validate_status_transition(instance.status):
                    raise ValueError(
                        f'Invalid status transition from {old.status} to {instance.status}'
                    )
                # Log status change
                logger.info(
                    f'Contribution {instance.id} status changed from {old.status} to {instance.status}'
                )
        except Contribution.DoesNotExist:
            pass


@receiver(post_save, sender=Contribution)
def contribution_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for Contribution model:
    - Invalidate cache
    - Update user statistics (total_contributed, reputation)
    - Update group statistics (total_paid, total_contributions)
    - Create audit entry for status changes
    - Send notifications
    - Schedule stats update
    - Check if group should auto-complete
    """
    # Invalidate cache
    cache.delete(f'contribution_{instance.id}')
    cache.delete(f'contribution_detail_{instance.id}')
    cache.delete(f'user_contributions_{instance.user.id}')
    cache.delete(f'group_contributions_{instance.group.id}')
    cache.delete(f'user_pending_{instance.user.id}')
    cache.delete(f'user_overdue_{instance.user.id}')
    cache.delete(f'group_{instance.group.id}')
    cache.delete(f'group_stats_{instance.group.id}')

    if created:
        logger.info(f'Contribution {instance.id} created for user {instance.user.id}')
        log_audit_event(
            user_id=instance.created_by.id if instance.created_by else None,
            action='contribution_created',
            resource='contribution',
            resource_id=instance.id,
            details={
                'group_id': instance.group.id,
                'user_id': instance.user.id,
                'amount': float(instance.amount),
                'round': instance.round,
            }
        )

    else:
        # Check if status changed
        try:
            old = Contribution.objects.get(pk=instance.pk)
            if old.status != instance.status:
                # Status changed
                log_audit_event(
                    user_id=instance.created_by.id if instance.created_by else None,
                    action='contribution_status_changed',
                    resource='contribution',
                    resource_id=instance.id,
                    details={
                        'old_status': old.status,
                        'new_status': instance.status,
                        'group_id': instance.group.id,
                        'user_id': instance.user.id,
                    }
                )

                # Create audit entry for status change
                ContributionAudit.objects.create(
                    contribution=instance,
                    user=instance.created_by,
                    action='status_change',
                    old_status=old.status,
                    new_status=instance.status,
                    details={
                        'reason': 'Status changed via signal',
                    },
                    timestamp=timezone.now(),
                )

                # Send notifications for specific status changes
                if instance.status == ContributionStatus.PAID:
                    # Payment confirmed notification
                    from apps.notifications.models import Notification
                    Notification.objects.create(
                        user=instance.user,
                        notification_type='payment_confirmed',
                        title='Payment Confirmed',
                        message=f'Your contribution of {format_currency(instance.amount)} for group "{instance.group.name}" has been confirmed.',
                        contribution=instance,
                        group=instance.group,
                        is_read=False,
                    )

                elif instance.status == ContributionStatus.OVERDUE:
                    # Overdue notification
                    from apps.notifications.models import Notification
                    Notification.objects.create(
                        user=instance.user,
                        notification_type='overdue_warning',
                        title='Contribution Overdue',
                        message=f'Your contribution of {format_currency(instance.amount)} for group "{instance.group.name}" is overdue by {instance.days_overdue} days.',
                        contribution=instance,
                        group=instance.group,
                        is_read=False,
                    )

                elif instance.status == ContributionStatus.CANCELLED:
                    # Cancelled notification
                    from apps.notifications.models import Notification
                    Notification.objects.create(
                        user=instance.user,
                        notification_type='contribution_cancelled',
                        title='Contribution Cancelled',
                        message=f'Your contribution of {format_currency(instance.amount)} for group "{instance.group.name}" has been cancelled.',
                        contribution=instance,
                        group=instance.group,
                        is_read=False,
                    )

                elif instance.status == ContributionStatus.REFUNDED:
                    # Refund notification
                    from apps.notifications.models import Notification
                    Notification.objects.create(
                        user=instance.user,
                        notification_type='contribution_refunded',
                        title='Contribution Refunded',
                        message=f'Your contribution of {format_currency(instance.amount)} for group "{instance.group.name}" has been refunded.',
                        contribution=instance,
                        group=instance.group,
                        is_read=False,
                    )

        except Contribution.DoesNotExist:
            pass

    # Update user statistics
    if instance.status == ContributionStatus.PAID:
        with transaction.atomic():
            user = instance.user
            user.total_contributed += instance.amount
            if instance.due_date and timezone.now() <= instance.due_date:
                user.on_time_payments += 1
            user.save(update_fields=['total_contributed', 'on_time_payments'])

    # Update group statistics (handled via task to avoid overhead)
    update_contribution_stats.delay(instance.group.id)

    # Check if group should auto-complete (all contributions paid)
    if instance.status == ContributionStatus.PAID:
        from .models import Contribution
        group = instance.group
        if group.is_active and not group.is_completed:
            pending_count = Contribution.objects.filter(
                group=group,
                status__in=[ContributionStatus.PENDING, ContributionStatus.OVERDUE],
                deleted_at__isnull=True
            ).count()
            if pending_count == 0:
                # All contributions are paid, group can be completed
                from apps.groups.tasks import process_group_completion
                process_group_completion.delay(group.id)
                logger.info(f'Group {group.id} auto-completion triggered by contribution {instance.id}')

    # Update user reputation
    if instance.status == ContributionStatus.PAID:
        user = instance.user
        if instance.due_date and timezone.now() <= instance.due_date:
            user.reputation_score = min(100, user.reputation_score + 1)
        else:
            user.reputation_score = min(100, user.reputation_score + 0.5)
        user.save(update_fields=['reputation_score'])

    # Update user default count if overdue
    if instance.status == ContributionStatus.OVERDUE:
        user = instance.user
        user.defaulted_count += 1
        user.save(update_fields=['defaulted_count'])


@receiver(pre_delete, sender=Contribution)
def contribution_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for Contribution model:
    - Prevent deletion of paid or refunded contributions
    - Enforce soft delete instead of hard delete
    - Log audit event
    """
    if instance.status in [ContributionStatus.PAID, ContributionStatus.REFUNDED]:
        raise ValueError('Cannot delete paid or refunded contributions.')

    if not instance.deleted_at:
        # Soft delete instead of hard delete
        instance.deleted_at = timezone.now()
        instance.save(update_fields=['deleted_at'])
        logger.warning(f'Hard delete attempted on contribution {instance.id}, converted to soft delete')
        raise Exception('Use soft_delete() instead of delete() for Contribution model')


@receiver(post_delete, sender=Contribution)
def contribution_post_delete_handler(sender, instance, **kwargs):
    """
    Handle post-delete events for Contribution model:
    - Clean up cache
    - Log audit event
    """
    cache.delete(f'contribution_{instance.id}')
    cache.delete(f'contribution_detail_{instance.id}')
    cache.delete(f'user_contributions_{instance.user.id}')
    cache.delete(f'group_contributions_{instance.group.id}')
    cache.delete(f'user_pending_{instance.user.id}')
    cache.delete(f'user_overdue_{instance.user.id}')
    logger.info(f'Contribution {instance.id} permanently deleted')


# ============================================================================
# CONTRIBUTION PAYMENT SIGNALS
# ============================================================================

@receiver(pre_save, sender=ContributionPayment)
def contribution_payment_pre_save_handler(sender, instance, **kwargs):
    """
    Handle pre-save events for ContributionPayment model:
    - Set paid_at if not set
    - Validate payment status transitions
    """
    if not instance.paid_at:
        instance.paid_at = timezone.now()

    if instance.pk:
        try:
            old = ContributionPayment.objects.get(pk=instance.pk)
            if old.status != instance.status:
                # Validate status transition
                valid_transitions = {
                    PaymentStatus.PENDING: [PaymentStatus.COMPLETED, PaymentStatus.FAILED],
                    PaymentStatus.PROCESSING: [PaymentStatus.COMPLETED, PaymentStatus.FAILED],
                    PaymentStatus.COMPLETED: [PaymentStatus.REFUNDED],
                    PaymentStatus.FAILED: [],
                    PaymentStatus.REFUNDED: [],
                }
                allowed = valid_transitions.get(old.status, [])
                if instance.status not in allowed:
                    raise ValueError(
                        f'Invalid payment status transition from {old.status} to {instance.status}'
                    )
        except ContributionPayment.DoesNotExist:
            pass


@receiver(post_save, sender=ContributionPayment)
def contribution_payment_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for ContributionPayment model:
    - Invalidate cache
    - Update contribution status
    - Update user and group statistics
    - Create audit entry
    - Send notifications
    - Trigger payment processing
    """
    # Invalidate cache
    cache.delete(f'payment_{instance.id}')
    cache.delete(f'contribution_{instance.contribution.id}')
    cache.delete(f'user_payments_{instance.user.id}')
    cache.delete(f'group_payments_{instance.group.id}')

    if created:
        logger.info(f'Payment {instance.id} created for contribution {instance.contribution.id}')

        # Create audit entry
        ContributionAudit.objects.create(
            contribution=instance.contribution,
            user=instance.user,
            action='payment_created',
            old_status=instance.contribution.status,
            new_status=instance.contribution.status,
            details={
                'payment_id': instance.id,
                'amount': float(instance.amount),
                'method': instance.payment_method,
                'reference': instance.reference,
            },
            timestamp=timezone.now(),
        )

        # Send notification
        from apps.notifications.models import Notification
        Notification.objects.create(
            user=instance.user,
            notification_type='payment_initiated',
            title='Payment Initiated',
            message=f'Your payment of {format_currency(instance.amount)} for contribution #{instance.contribution.id} has been initiated.',
            contribution=instance.contribution,
            group=instance.group,
            is_read=False,
        )

        # Process payment via task
        process_contribution_payments.delay(instance.id)

    else:
        # Status changed
        try:
            old = ContributionPayment.objects.get(pk=instance.pk)
            if old.status != instance.status:
                # Payment status changed
                log_audit_event(
                    user_id=instance.user.id if instance.user else None,
                    action='payment_status_changed',
                    resource='contribution_payment',
                    resource_id=instance.id,
                    details={
                        'old_status': old.status,
                        'new_status': instance.status,
                        'contribution_id': instance.contribution.id,
                    }
                )

                # Create audit entry for status change
                ContributionAudit.objects.create(
                    contribution=instance.contribution,
                    user=instance.user,
                    action='payment_status_change',
                    old_status=instance.contribution.status,
                    new_status=instance.contribution.status,
                    details={
                        'payment_id': instance.id,
                        'old_payment_status': old.status,
                        'new_payment_status': instance.status,
                    },
                    timestamp=timezone.now(),
                )

                # If payment completed, mark contribution as paid
                if instance.status == PaymentStatus.COMPLETED:
                    contribution = instance.contribution
                    if contribution.status in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]:
                        contribution.mark_as_paid(
                            payment_method=instance.payment_method,
                            reference=instance.reference,
                            paid_amount=instance.amount,
                        )
                        # Update contribution stats
                        update_contribution_stats.delay(contribution.group.id)

                # Send notification for status change
                if instance.status == PaymentStatus.FAILED:
                    from apps.notifications.models import Notification
                    Notification.objects.create(
                        user=instance.user,
                        notification_type='payment_failed',
                        title='Payment Failed',
                        message=f'Your payment of {format_currency(instance.amount)} for contribution #{instance.contribution.id} has failed.',
                        contribution=instance.contribution,
                        group=instance.group,
                        is_read=False,
                    )

                elif instance.status == PaymentStatus.COMPLETED:
                    from apps.notifications.models import Notification
                    Notification.objects.create(
                        user=instance.user,
                        notification_type='payment_completed',
                        title='Payment Completed',
                        message=f'Your payment of {format_currency(instance.amount)} for contribution #{instance.contribution.id} has been completed successfully.',
                        contribution=instance.contribution,
                        group=instance.group,
                        is_read=False,
                    )

                elif instance.status == PaymentStatus.REFUNDED:
                    from apps.notifications.models import Notification
                    Notification.objects.create(
                        user=instance.user,
                        notification_type='payment_refunded',
                        title='Payment Refunded',
                        message=f'Your payment of {format_currency(instance.amount)} for contribution #{instance.contribution.id} has been refunded.',
                        contribution=instance.contribution,
                        group=instance.group,
                        is_read=False,
                    )

        except ContributionPayment.DoesNotExist:
            pass


@receiver(pre_delete, sender=ContributionPayment)
def contribution_payment_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for ContributionPayment model:
    - Prevent deletion of completed payments
    - Log audit event
    """
    if instance.status == PaymentStatus.COMPLETED:
        raise ValueError('Cannot delete completed payments. Use refund instead.')


# ============================================================================
# CONTRIBUTION REMINDER SIGNALS
# ============================================================================

@receiver(post_save, sender=ContributionReminder)
def contribution_reminder_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for ContributionReminder model:
    - Update contribution reminder_count
    - Log audit event
    - Invalidate cache
    """
    if created:
        # Update contribution reminder count
        contribution = instance.contribution
        contribution.reminder_count += 1
        contribution.save(update_fields=['reminder_count'])

        # Invalidate cache
        cache.delete(f'contribution_{contribution.id}')
        cache.delete(f'contribution_reminders_{contribution.id}')

        logger.info(f'Reminder {instance.id} created for contribution {instance.contribution.id}')


# ============================================================================
# CONTRIBUTION AUDIT SIGNALS
# ============================================================================

@receiver(post_save, sender=ContributionAudit)
def contribution_audit_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for ContributionAudit model:
    - Invalidate cache
    - Log activity
    """
    if created:
        logger.debug(f'Audit entry {instance.id} created for contribution {instance.contribution.id}')
        cache.delete(f'contribution_audits_{instance.contribution.id}')


# ============================================================================
# CROSS-MODEL SIGNALS
# ============================================================================

@receiver(post_save, sender=Contribution)
def contribution_group_statistics_handler(sender, instance, created, **kwargs):
    """
    Update group statistics when contribution is created or updated.
    """
    # Update group total_contributions
    group = instance.group
    with transaction.atomic():
        total_contributions = Contribution.objects.filter(
            group=group,
            deleted_at__isnull=True
        ).count()

        total_paid = Contribution.objects.filter(
            group=group,
            status=ContributionStatus.PAID,
            deleted_at__isnull=True
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        total_pending = Contribution.objects.filter(
            group=group,
            status=ContributionStatus.PENDING,
            deleted_at__isnull=True
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        total_overdue = Contribution.objects.filter(
            group=group,
            status=ContributionStatus.OVERDUE,
            deleted_at__isnull=True
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        group.total_contributions = total_contributions
        group.total_paid = total_paid
        group.total_pending = total_pending
        group.total_overdue = total_overdue
        group.save(update_fields=[
            'total_contributions',
            'total_paid',
            'total_pending',
            'total_overdue'
        ])


@receiver(post_save, sender=Contribution)
def contribution_user_statistics_handler(sender, instance, created, **kwargs):
    """
    Update user statistics when contribution is created or updated.
    """
    user = instance.user
    with transaction.atomic():
        total_contributions = Contribution.objects.filter(
            user=user,
            deleted_at__isnull=True
        ).count()

        total_paid = Contribution.objects.filter(
            user=user,
            status=ContributionStatus.PAID,
            deleted_at__isnull=True
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        on_time_count = Contribution.objects.filter(
            user=user,
            status=ContributionStatus.PAID,
            deleted_at__isnull=True,
            paid_date__lte=F('due_date')
        ).count()

        defaulted_count = Contribution.objects.filter(
            user=user,
            status=ContributionStatus.OVERDUE,
            deleted_at__isnull=True
        ).count()

        user.total_contributed = total_paid
        user.on_time_payments = on_time_count
        user.defaulted_count = defaulted_count
        user.save(update_fields=[
            'total_contributed',
            'on_time_payments',
            'defaulted_count'
        ])


# ============================================================================
# CACHE INVALIDATION UTILITY
# ============================================================================

def invalidate_contribution_cache(contribution_id: int):
    """
    Utility to invalidate all cache keys related to a contribution.
    """
    keys = [
        f'contribution_{contribution_id}',
        f'contribution_detail_{contribution_id}',
        f'contribution_stats_{contribution_id}',
        f'contribution_payments_{contribution_id}',
        f'contribution_reminders_{contribution_id}',
        f'contribution_audits_{contribution_id}',
    ]
    for key in keys:
        cache.delete(key)
    logger.debug(f'Cache invalidated for contribution {contribution_id}')


# ============================================================================
# LOGGING UTILITY
# ============================================================================

def log_contribution_action(contribution, action, user=None, details=None):
    """
    Utility to log a contribution action with consistent format.
    """
    log_data = {
        'contribution_id': contribution.id,
        'group_id': contribution.group.id,
        'user_id': contribution.user.id,
        'action': action,
        'user_id_actor': user.id if user else None,
        'timestamp': timezone.now().isoformat(),
        'details': details or {}
    }
    logger.info(f'CONTRIBUTION_ACTION: {json.dumps(log_data)}')


# ============================================================================
# SIGNAL DISPATCHER (for manual triggering)
# ============================================================================

def dispatch_contribution_signals(contribution_id, signal_name, *args, **kwargs):
    """
    Manually dispatch contribution signals for testing or admin actions.
    """
    try:
        contribution = Contribution.objects.get(id=contribution_id)
    except Contribution.DoesNotExist:
        return None

    if signal_name == 'post_save':
        contribution_post_save_handler(Contribution, contribution, created=False, **kwargs)
    elif signal_name == 'pre_save':
        contribution_pre_save_handler(Contribution, contribution, **kwargs)
    elif signal_name == 'pre_delete':
        contribution_pre_delete_handler(Contribution, contribution, **kwargs)
    elif signal_name == 'post_delete':
        contribution_post_delete_handler(Contribution, contribution, **kwargs)
    return True


def dispatch_payment_signals(payment_id, signal_name, *args, **kwargs):
    """
    Manually dispatch payment signals for testing or admin actions.
    """
    try:
        payment = ContributionPayment.objects.get(id=payment_id)
    except ContributionPayment.DoesNotExist:
        return None

    if signal_name == 'post_save':
        contribution_payment_post_save_handler(ContributionPayment, payment, created=False, **kwargs)
    elif signal_name == 'pre_save':
        contribution_payment_pre_save_handler(ContributionPayment, payment, **kwargs)
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
            # Re-raise to prevent silent failures
            raise
    return wrapper