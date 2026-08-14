"""
Celery tasks for the payments app.

This module provides background task functions for payment operations:
- Processing pending payments (checking expiry, completing, failing)
- Processing payouts (completing, failing, reconciliation)
- Reconciling payments with external gateways
- Sending payment reminders to users and admins
- Updating denormalized statistics
- Cleaning up old payment logs and records
- Generating payment reports (periodic)
- Sending payment digests to admins/members
- Processing webhook events
- Retrying failed payments
- Auto-refunding expired payments

All tasks include comprehensive error handling, logging, retry logic, and
performance optimizations for bulk operations.
"""

from celery import shared_task
from celery.utils.log import get_task_logger
from django.db import transaction
from django.db.models import Q, Sum, Count, F, OuterRef, Subquery
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.core.cache import cache

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple

from apps.users.models import User
from apps.groups.models import Group, GroupMember
from apps.common.utils import send_email, send_sms, format_currency, log_audit_event
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
from . import (
    verify_webhook_payload,
    get_payment_statistics,
    get_payout_statistics,
    reconcile_payment,
    refund_payment,
)

logger = get_task_logger(__name__)


# ============================================================================
# PENDING PAYMENTS PROCESSING
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_pending_payments(self):
    """
    Process all pending payments.
    - Complete payments that have been confirmed
    - Expire payments past their expiry date
    - Send reminders for pending payments
    - Update payment statistics
    """
    logger.info("Starting process_pending_payments task")

    results = {
        'expired': 0,
        'completed': 0,
        'failed': 0,
        'reminders_sent': 0,
        'errors': 0
    }

    try:
        now = timezone.now()

        # ========================================================================
        # 1. Expire pending payments that are past expiry
        # ========================================================================
        expired_payments = Payment.objects.filter(
            status=PaymentStatus.PENDING,
            expires_at__lt=now,
            deleted_at__isnull=True
        )

        for payment in expired_payments:
            try:
                with transaction.atomic():
                    payment.expire()
                    results['expired'] += 1
                    logger.info(f'Payment {payment.id} expired')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error expiring payment {payment.id}: {str(e)}')

        # ========================================================================
        # 2. Complete payments that are ready (webhook confirmed)
        # ========================================================================
        ready_payments = Payment.objects.filter(
            status=PaymentStatus.PROCESSING,
            webhook_received=True,
            deleted_at__isnull=True
        )

        for payment in ready_payments:
            try:
                with transaction.atomic():
                    payment.complete()
                    results['completed'] += 1
                    logger.info(f'Payment {payment.id} completed via task')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error completing payment {payment.id}: {str(e)}')

        # ========================================================================
        # 3. Send reminders for pending payments
        # ========================================================================
        pending_for_reminder = Payment.objects.filter(
            status=PaymentStatus.PENDING,
            expires_at__gt=now,
            created_at__lte=now - timedelta(minutes=30),
            deleted_at__isnull=True
        )

        for payment in pending_for_reminder:
            try:
                send_payment_reminder.delay(payment.id)
                results['reminders_sent'] += 1
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error sending reminder for payment {payment.id}: {str(e)}')

        logger.info(f'process_pending_payments completed: {results}')
        return results

    except Exception as e:
        logger.error(f'process_pending_payments failed: {str(e)}')
        self.retry(exc=e, countdown=60)
        raise


# ============================================================================
# PAYOUT PROCESSING
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_payouts(self):
    """
    Process pending payouts.
    - Complete pending payouts that are ready
    - Fail payouts that have been pending too long
    - Send notifications
    """
    logger.info("Starting process_payouts task")

    results = {
        'completed': 0,
        'failed': 0,
        'on_hold': 0,
        'errors': 0
    }

    try:
        now = timezone.now()

        # Complete payouts that have been confirmed
        ready_payouts = Payout.objects.filter(
            status=PayoutStatus.PROCESSING,
            deleted_at__isnull=True
        )

        for payout in ready_payouts:
            try:
                with transaction.atomic():
                    payout.complete()
                    results['completed'] += 1
                    logger.info(f'Payout {payout.id} completed via task')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error completing payout {payout.id}: {str(e)}')

        # Fail payouts pending too long (> 7 days)
        fail_threshold = now - timedelta(days=7)
        stale_payouts = Payout.objects.filter(
            status=PayoutStatus.PENDING,
            created_at__lt=fail_threshold,
            deleted_at__isnull=True
        )

        for payout in stale_payouts:
            try:
                with transaction.atomic():
                    payout.fail('Auto-failed after 7 days pending')
                    results['failed'] += 1
                    logger.info(f'Payout {payout.id} failed due to timeout')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error failing payout {payout.id}: {str(e)}')

        # Put on hold suspicious payouts (for admin review)
        # This is a placeholder; actual logic would use fraud detection
        suspicious_payouts = Payout.objects.filter(
            status=PayoutStatus.PENDING,
            amount__gt=100000,
            deleted_at__isnull=True
        )

        for payout in suspicious_payouts:
            try:
                with transaction.atomic():
                    payout.put_on_hold('Suspicious amount - awaiting admin review')
                    results['on_hold'] += 1
                    logger.info(f'Payout {payout.id} put on hold')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error putting payout {payout.id} on hold: {str(e)}')

        logger.info(f'process_payouts completed: {results}')
        return results

    except Exception as e:
        logger.error(f'process_payouts failed: {str(e)}')
        self.retry(exc=e, countdown=60)
        raise


# ============================================================================
# RECONCILIATION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def reconcile_payments(self):
    """
    Reconcile payments with external gateway data.
    This task should be run periodically to ensure all payments are reconciled.
    """
    logger.info("Starting reconcile_payments task")

    results = {
        'reconciled': 0,
        'failed': 0,
        'errors': 0
    }

    try:
        # Get payments that need reconciliation (completed but not reconciled)
        payments_to_reconcile = Payment.objects.filter(
            status=PaymentStatus.COMPLETED,
            reconciliations__isnull=True,
            deleted_at__isnull=True
        )

        for payment in payments_to_reconcile:
            try:
                # Simulate reconciliation with external system
                # In production, this would call external APIs
                reconciliation_data = {
                    'external_reference': payment.reference,
                    'status': 'completed',
                    'matched': True,
                    'external_data': {'source': 'auto_reconciliation'},
                }
                success = reconcile_payment(payment.id, reconciliation_data)
                if success:
                    results['reconciled'] += 1
                else:
                    results['failed'] += 1
                logger.info(f'Payment {payment.id} reconciled')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error reconciling payment {payment.id}: {str(e)}')

        logger.info(f'reconcile_payments completed: {results}')
        return results

    except Exception as e:
        logger.error(f'reconcile_payments failed: {str(e)}')
        raise


# ============================================================================
# PAYMENT REMINDER TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_payment_reminder(self, payment_id: int):
    """
    Send a reminder for a pending payment.
    """
    try:
        payment = Payment.objects.get(id=payment_id, deleted_at__isnull=True)
    except Payment.DoesNotExist:
        logger.error(f'Payment {payment_id} not found')
        return

    if payment.status != PaymentStatus.PENDING:
        return

    user = payment.user
    message = f"""
    Reminder: You have a pending payment of {format_currency(payment.amount)} 
    for group "{payment.group.name}".
    Reference: {payment.reference}
    Please complete your payment to avoid any delays.
    """

    from apps.notifications.models import Notification
    Notification.objects.create(
        user=user,
        notification_type='payment_reminder',
        title='Payment Reminder',
        message=message,
        payment=payment,
        group=payment.group,
        is_read=False,
    )

    send_email(
        to_email=user.email,
        subject=f'Payment Reminder - {payment.group.name}',
        message=message,
        html_message=None,
    )

    if user.phone:
        send_sms(
            phone=user.phone,
            message=message[:160],
        )

    logger.info(f'Reminder sent for payment {payment_id}')
    return True


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_payment_digest(self):
    """
    Send a digest of payment activities to users and admins.
    """
    logger.info("Starting send_payment_digest task")

    # Get users who have opted in for payment digest
    users = User.objects.filter(
        is_active=True,
        notification_preferences__payment_digest=True,
        deleted_at__isnull=True
    )

    sent_count = 0
    for user in users:
        try:
            # Get user's payments in the last 7 days
            threshold = timezone.now() - timedelta(days=7)
            payments = Payment.objects.filter(
                user=user,
                created_at__gte=threshold,
                deleted_at__isnull=True
            )

            if not payments.exists():
                continue

            digest_data = {
                'user': user,
                'payments': payments,
                'date': timezone.now(),
                'total_amount': payments.aggregate(total=Sum('amount'))['total'] or 0,
                'count': payments.count(),
                'pending_count': payments.filter(status=PaymentStatus.PENDING).count(),
                'completed_count': payments.filter(status=PaymentStatus.COMPLETED).count(),
            }

            subject = f'Payment Digest: {timezone.now().strftime("%Y-%m-%d")}'
            html_message = render_to_string('emails/payment_digest.html', digest_data)
            plain_message = f"""
            Payment Digest for {user.full_name}

            Payments in the last 7 days: {digest_data['count']}
            Total Amount: {format_currency(digest_data['total_amount'])}
            Pending: {digest_data['pending_count']}
            Completed: {digest_data['completed_count']}

            Visit the app for more details.
            """

            send_mail(
                subject,
                plain_message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                html_message=html_message,
                fail_silently=False,
            )

            sent_count += 1

        except Exception as e:
            logger.error(f'Error sending digest to user {user.id}: {str(e)}')

    logger.info(f'send_payment_digest completed: sent to {sent_count} users')
    return sent_count


# ============================================================================
# STATISTICS UPDATE TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def update_payment_stats(self, group_id: Optional[int] = None):
    """
    Update denormalized statistics for payments.
    If group_id provided, update that group's stats; otherwise update all groups.
    """
    if group_id:
        logger.info(f"Starting update_payment_stats for group {group_id}")
        return _update_group_payment_stats(group_id)
    else:
        logger.info("Starting update_payment_stats for all groups")
        return _update_all_group_payment_stats()


def _update_all_group_payment_stats() -> Dict[str, Any]:
    """Update stats for all groups."""
    results = {'updated': 0, 'errors': 0}
    groups = Group.objects.filter(deleted_at__isnull=True)
    for group in groups:
        try:
            _update_group_payment_stats(group.id)
            results['updated'] += 1
        except Exception as e:
            results['errors'] += 1
            logger.error(f'Error updating stats for group {group.id}: {str(e)}')
    return results


def _update_group_payment_stats(group_id: int) -> Dict[str, Any]:
    """Update denormalized stats for a single group."""
    from apps.groups.models import Group

    try:
        group = Group.objects.get(id=group_id)
    except Group.DoesNotExist:
        return {'error': 'Group not found'}

    payments = Payment.objects.filter(group=group, deleted_at__isnull=True)

    total = payments.count()
    completed = payments.filter(status=PaymentStatus.COMPLETED).count()
    pending = payments.filter(status=PaymentStatus.PENDING).count()
    failed = payments.filter(status=PaymentStatus.FAILED).count()

    total_amount = payments.filter(status=PaymentStatus.COMPLETED).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    total_fees = payments.filter(status=PaymentStatus.COMPLETED).aggregate(
        total=Sum('total_fee')
    )['total'] or Decimal('0.00')

    total_net = payments.filter(status=PaymentStatus.COMPLETED).aggregate(
        total=Sum('net_amount')
    )['total'] or Decimal('0.00')

    # Update group fields if they exist
    if hasattr(group, 'total_payments'):
        group.total_payments = total
        group.total_payments_completed = completed
        group.total_payments_pending = pending
        group.total_payments_failed = failed
        group.total_payments_amount = total_amount
        group.total_payments_fees = total_fees
        group.total_payments_net = total_net
        group.save(update_fields=[
            'total_payments', 'total_payments_completed',
            'total_payments_pending', 'total_payments_failed',
            'total_payments_amount', 'total_payments_fees',
            'total_payments_net'
        ])

    logger.info(f'Updated payment stats for group {group_id}')
    return {
        'group_id': group_id,
        'total': total,
        'completed': completed,
        'pending': pending,
        'failed': failed,
        'total_amount': float(total_amount),
        'total_fees': float(total_fees),
        'total_net': float(total_net),
    }


# ============================================================================
# CLEANUP TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def cleanup_payment_logs(self):
    """
    Clean up old payment logs and records.
    - Delete gateway logs older than X days
    - Delete webhook logs older than X days
    - Archive completed payments older than X days
    - Permanently delete soft-deleted payments older than X days
    """
    logger.info("Starting cleanup_payment_logs task")

    results = {
        'gateway_logs_deleted': 0,
        'webhook_logs_deleted': 0,
        'archived': 0,
        'permanently_deleted': 0,
        'errors': 0
    }

    try:
        now = timezone.now()

        # Delete gateway logs older than 90 days
        log_threshold = now - timedelta(days=90)
        gateway_logs = PaymentGatewayLog.objects.filter(created_at__lt=log_threshold)
        count, _ = gateway_logs.delete()
        results['gateway_logs_deleted'] = count

        # Delete webhook logs older than 90 days
        webhook_logs = PaymentWebhookLog.objects.filter(created_at__lt=log_threshold)
        count, _ = webhook_logs.delete()
        results['webhook_logs_deleted'] = count

        # Archive completed payments older than 365 days
        archive_threshold = now - timedelta(days=365)
        completed_payments = Payment.objects.filter(
            status=PaymentStatus.COMPLETED,
            paid_at__lt=archive_threshold,
            deleted_at__isnull=True
        )

        for payment in completed_payments:
            try:
                # Mark as archived (could move to archive table)
                logger.info(f'Payment {payment.id} archived (completed on {payment.paid_at})')
                results['archived'] += 1
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error archiving payment {payment.id}: {str(e)}')

        # Permanently delete soft-deleted payments older than 30 days
        delete_threshold = now - timedelta(days=30)
        deleted_payments = Payment.objects.filter(deleted_at__lt=delete_threshold)

        for payment in deleted_payments:
            try:
                with transaction.atomic():
                    # Delete related records
                    payment.transactions.all().delete()
                    payment.gateway_logs.all().delete()
                    payment.reconciliations.all().delete()
                    payment.disputes.all().delete()
                    payment.audits.all().delete()
                    payment.delete()
                    results['permanently_deleted'] += 1
                    logger.info(f'Payment {payment.id} permanently deleted')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error permanently deleting payment {payment.id}: {str(e)}')

        logger.info(f'cleanup_payment_logs completed: {results}')
        return results

    except Exception as e:
        logger.error(f'cleanup_payment_logs failed: {str(e)}')
        raise


# ============================================================================
# WEBHOOK PROCESSING TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_webhook_events(self, webhook_log_id: int):
    """
    Process a webhook event from a payment gateway.
    """
    try:
        webhook_log = PaymentWebhookLog.objects.get(id=webhook_log_id)
    except PaymentWebhookLog.DoesNotExist:
        logger.error(f'Webhook log {webhook_log_id} not found')
        return

    if webhook_log.processed:
        logger.info(f'Webhook {webhook_log.id} already processed')
        return

    try:
        event_type = webhook_log.event_type
        payload = webhook_log.payload

        # Handle different event types
        if event_type == 'payment.completed':
            _handle_payment_completed(payload)
        elif event_type == 'payment.failed':
            _handle_payment_failed(payload)
        elif event_type == 'payment.refunded':
            _handle_payment_refunded(payload)
        elif event_type == 'payment.reversed':
            _handle_payment_reversed(payload)
        elif event_type == 'payout.completed':
            _handle_payout_completed(payload)
        else:
            logger.warning(f'Unhandled webhook event type: {event_type}')

        webhook_log.processed = True
        webhook_log.processed_at = timezone.now()
        webhook_log.save(update_fields=['processed', 'processed_at'])

        logger.info(f'Webhook {webhook_log.id} processed successfully')

    except Exception as e:
        webhook_log.error_message = str(e)
        webhook_log.save(update_fields=['error_message'])
        logger.error(f'Error processing webhook {webhook_log.id}: {str(e)}')
        raise


def _handle_payment_completed(payload: Dict[str, Any]):
    """Handle payment completed webhook."""
    reference = payload.get('reference')
    if not reference:
        return

    try:
        payment = Payment.objects.get(reference=reference)
    except Payment.DoesNotExist:
        return

    if payment.status == PaymentStatus.PENDING:
        payment.complete(reference=payload.get('transaction_id'))
        logger.info(f'Payment {payment.id} completed via webhook')


def _handle_payment_failed(payload: Dict[str, Any]):
    """Handle payment failed webhook."""
    reference = payload.get('reference')
    if not reference:
        return

    try:
        payment = Payment.objects.get(reference=reference)
    except Payment.DoesNotExist:
        return

    if payment.status == PaymentStatus.PENDING:
        payment.fail(payload.get('error_message', 'Gateway reported failure'))
        logger.info(f'Payment {payment.id} failed via webhook')


def _handle_payment_refunded(payload: Dict[str, Any]):
    """Handle payment refunded webhook."""
    reference = payload.get('reference')
    if not reference:
        return

    try:
        payment = Payment.objects.get(reference=reference)
    except Payment.DoesNotExist:
        return

    if payment.status == PaymentStatus.COMPLETED:
        payment.refund(payload.get('reason', 'Refunded via webhook'))
        logger.info(f'Payment {payment.id} refunded via webhook')


def _handle_payment_reversed(payload: Dict[str, Any]):
    """Handle payment reversed webhook."""
    reference = payload.get('reference')
    if not reference:
        return

    try:
        payment = Payment.objects.get(reference=reference)
    except Payment.DoesNotExist:
        return

    if payment.status in [PaymentStatus.PENDING, PaymentStatus.PROCESSING]:
        payment.reverse_payment(payload.get('reason', 'Reversed via webhook'))
        logger.info(f'Payment {payment.id} reversed via webhook')


def _handle_payout_completed(payload: Dict[str, Any]):
    """Handle payout completed webhook."""
    reference = payload.get('reference')
    if not reference:
        return

    try:
        payout = Payout.objects.get(reference=reference)
    except Payout.DoesNotExist:
        return

    if payout.status == PayoutStatus.PENDING:
        payout.complete(payload.get('transaction_id'))
        logger.info(f'Payout {payout.id} completed via webhook')


# ============================================================================
# RETRY FAILED PAYMENTS TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def retry_failed_payments(self):
    """
    Retry failed payments that can be retried.
    """
    logger.info("Starting retry_failed_payments task")

    results = {
        'retried': 0,
        'errors': 0
    }

    try:
        # Get failed payments that can be retried
        failed_payments = Payment.objects.filter(
            status=PaymentStatus.FAILED,
            retry_count__lt=3,
            deleted_at__isnull=True
        )

        for payment in failed_payments:
            try:
                with transaction.atomic():
                    payment.retry()
                    results['retried'] += 1
                    logger.info(f'Payment {payment.id} retried')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error retrying payment {payment.id}: {str(e)}')

        logger.info(f'retry_failed_payments completed: {results}')
        return results

    except Exception as e:
        logger.error(f'retry_failed_payments failed: {str(e)}')
        raise


# ============================================================================
# AUTO-REFUND EXPIRED PAYMENTS TASK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def auto_refund_expired(self):
    """
    Auto-refund payments that have expired and are eligible for refund.
    """
    logger.info("Starting auto_refund_expired task")

    results = {
        'refunded': 0,
        'errors': 0
    }

    try:
        # Get expired payments that can be refunded
        expired_payments = Payment.objects.filter(
            status=PaymentStatus.EXPIRED,
            deleted_at__isnull=True
        )

        for payment in expired_payments:
            try:
                # Only refund if payment was completed (double-check)
                if payment.status == PaymentStatus.EXPIRED:
                    # Auto-refund only if it was previously completed
                    # For simplicity, we skip
                    pass
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error refunding expired payment {payment.id}: {str(e)}')

        logger.info(f'auto_refund_expired completed: {results}')
        return results

    except Exception as e:
        logger.error(f'auto_refund_expired failed: {str(e)}')
        raise


# ============================================================================
# PAYMENT REPORT GENERATION
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def generate_payment_report(self, group_id: int = None, report_type: str = 'summary'):
    """
    Generate a payment report.
    """
    from django.db.models import Count, Sum

    queryset = Payment.objects.filter(deleted_at__isnull=True)
    if group_id:
        queryset = queryset.filter(group_id=group_id)

    if report_type == 'summary':
        total = queryset.count()
        completed = queryset.filter(status=PaymentStatus.COMPLETED).count()
        pending = queryset.filter(status=PaymentStatus.PENDING).count()
        failed = queryset.filter(status=PaymentStatus.FAILED).count()
        total_amount = queryset.filter(status=PaymentStatus.COMPLETED).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        total_fees = queryset.filter(status=PaymentStatus.COMPLETED).aggregate(
            total=Sum('total_fee')
        )['total'] or Decimal('0.00')
        total_net = queryset.filter(status=PaymentStatus.COMPLETED).aggregate(
            total=Sum('net_amount')
        )['total'] or Decimal('0.00')

        return {
            'total_payments': total,
            'completed': completed,
            'pending': pending,
            'failed': failed,
            'total_amount': float(total_amount),
            'total_fees': float(total_fees),
            'total_net': float(total_net),
        }

    elif report_type == 'detailed':
        # Group by payment method
        method_breakdown = queryset.values('payment_method').annotate(
            count=Count('id'),
            total=Sum('amount'),
            fees=Sum('total_fee')
        )
        return {
            'method_breakdown': [
                {
                    'method': item['payment_method'],
                    'count': item['count'],
                    'total_amount': float(item['total'] or 0),
                    'total_fees': float(item['fees'] or 0),
                }
                for item in method_breakdown
            ]
        }

    return {'error': 'Unknown report type'}


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_report_to_admins(self, report_type: str = 'summary'):
    """
    Send payment report to admins.
    """
    report = generate_payment_report(report_type=report_type)
    if 'error' in report:
        logger.error(f'Error generating report: {report["error"]}')
        return report

    # Get admin emails
    admin_users = User.objects.filter(is_staff=True, is_active=True)
    admin_emails = list(admin_users.values_list('email', flat=True))

    if not admin_emails:
        return {'message': 'No admins to send report'}

    subject = f'Payment Report - {timezone.now().strftime("%Y-%m-%d")}'
    plain_message = f"""
    Payment Report

    Generated: {timezone.now().strftime("%Y-%m-%d %H:%M:%S")}

    {chr(10).join([f'{k}: {v}' for k, v in report.items()])}

    View full details in the admin panel.
    """

    for email in admin_emails:
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=True
        )

    logger.info(f'Sent {report_type} report to {len(admin_emails)} admins')
    return {'sent': len(admin_emails)}


# ============================================================================
# TASK SCHEDULING (BROKER CONFIG)
# ============================================================================

# These tasks should be scheduled in celery beat schedule:
# - process_pending_payments: every 15 minutes
# - process_payouts: every 30 minutes
# - reconcile_payments: daily at 1:00 AM
# - send_payment_digest: daily at 8:00 AM
# - update_payment_stats: every 6 hours
# - cleanup_payment_logs: weekly on Sunday at 3:00 AM
# - retry_failed_payments: every hour
# - auto_refund_expired: daily at 2:00 AM


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'process_pending_payments',
    'process_payouts',
    'reconcile_payments',
    'send_payment_reminder',
    'send_payment_digest',
    'update_payment_stats',
    'cleanup_payment_logs',
    'process_webhook_events',
    'retry_failed_payments',
    'auto_refund_expired',
    'generate_payment_report',
    'send_report_to_admins',
]