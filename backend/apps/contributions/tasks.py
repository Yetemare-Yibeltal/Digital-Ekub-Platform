"""
Celery tasks for the contributions app.

This module provides background task functions for contribution operations:
- Processing pending contributions (checking due dates, marking overdue)
- Sending contribution reminders to members
- Processing contribution payments (webhook handling, reconciliation)
- Updating denormalized statistics
- Cleaning up completed/soft-deleted contributions
- Generating contribution reports (periodic)
- Sending contribution digests to admins/members
- Processing refunds
- Auto-waiving overdue contributions (with threshold)

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
from apps.common.constants import ContributionStatus, PaymentStatus, ContributionType

from .models import (
    Contribution,
    ContributionPayment,
    ContributionReminder,
    ContributionAudit,
)
from . import process_contribution_payment as process_payment_helper

logger = get_task_logger(__name__)


# ============================================================================
# PENDING CONTRIBUTIONS PROCESSING
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_pending_contributions(self):
    """
    Process all pending contributions.
    - Check if due date has passed -> mark as overdue
    - For overdue, apply penalties if configured
    - Send reminders to users with pending contributions
    """
    logger.info("Starting process_pending_contributions task")

    results = {
        'overdue_marked': 0,
        'penalties_applied': 0,
        'reminders_sent': 0,
        'errors': 0
    }

    try:
        now = timezone.now()

        # ========================================================================
        # 1. Mark pending contributions as overdue if due date passed
        # ========================================================================
        pending_contributions = Contribution.objects.filter(
            status=ContributionStatus.PENDING,
            due_date__lt=now,
            deleted_at__isnull=True
        )

        for contribution in pending_contributions:
            try:
                with transaction.atomic():
                    contribution.mark_as_overdue()
                    results['overdue_marked'] += 1

                    # Apply penalty if configured and overdue days > threshold
                    if contribution.days_overdue >= 7:
                        penalty = contribution.apply_penalty()
                        if penalty > 0:
                            results['penalties_applied'] += 1

                    logger.info(f'Contribution {contribution.id} marked overdue')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error processing contribution {contribution.id}: {str(e)}')

        # ========================================================================
        # 2. Send reminders for pending contributions
        # ========================================================================
        pending_for_reminder = Contribution.objects.filter(
            status__in=[ContributionStatus.PENDING, ContributionStatus.OVERDUE],
            due_date__lte=now + timedelta(days=3),
            deleted_at__isnull=True,
            reminder_count__lt=3  # Max 3 reminders
        )

        for contribution in pending_for_reminder:
            try:
                send_contribution_reminder.delay(contribution.id)
                results['reminders_sent'] += 1
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error sending reminder for contribution {contribution.id}: {str(e)}')

        logger.info(f'process_pending_contributions completed: {results}')
        return results

    except Exception as e:
        logger.error(f'process_pending_contributions failed: {str(e)}')
        self.retry(exc=e, countdown=60)
        raise


# ============================================================================
# OVERDUE CONTRIBUTIONS CHECK
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def check_overdue_contributions(self):
    """
    Check overdue contributions and take appropriate actions.
    - Apply penalties for overdue contributions
    - Notify users and group admins
    - Update user reputation
    - Auto-waive if overdue beyond threshold
    """
    logger.info("Starting check_overdue_contributions task")

    results = {
        'overdue_found': 0,
        'penalties_applied': 0,
        'notifications_sent': 0,
        'auto_waived': 0,
        'errors': 0
    }

    try:
        now = timezone.now()
        overdue_threshold = now - timedelta(days=30)

        # Find overdue contributions
        overdue_contributions = Contribution.objects.filter(
            status=ContributionStatus.OVERDUE,
            due_date__lt=overdue_threshold,
            deleted_at__isnull=True
        )

        for contribution in overdue_contributions:
            try:
                results['overdue_found'] += 1

                # Apply penalty if not already applied
                if not contribution.penalty_applied and contribution.days_overdue >= 7:
                    contribution.apply_penalty()
                    results['penalties_applied'] += 1

                # Auto-waive if overdue > 90 days
                if contribution.days_overdue >= 90:
                    with transaction.atomic():
                        contribution.waive(contribution.amount, reason='Auto-waived after 90 days overdue')
                        results['auto_waived'] += 1
                        logger.info(f'Contribution {contribution.id} auto-waived after 90 days overdue')

                # Send notification to user and group admin
                if contribution.days_overdue % 7 == 0 and contribution.days_overdue > 0:
                    send_overdue_notification.delay(contribution.id)
                    results['notifications_sent'] += 1

            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error processing overdue contribution {contribution.id}: {str(e)}')

        logger.info(f'check_overdue_contributions completed: {results}')
        return results

    except Exception as e:
        logger.error(f'check_overdue_contributions failed: {str(e)}')
        self.retry(exc=e, countdown=60)
        raise


# ============================================================================
# CONTRIBUTION REMINDER TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_contribution_reminder(self, contribution_id: int):
    """
    Send a reminder for a specific contribution.
    """
    try:
        contribution = Contribution.objects.get(id=contribution_id, deleted_at__isnull=True)
    except Contribution.DoesNotExist:
        logger.error(f'Contribution {contribution_id} not found')
        return

    if not contribution.is_ready_for_reminder:
        return

    from apps.notifications.models import Notification
    from apps.common.utils import send_email, send_sms

    user = contribution.user
    message = f"""
    Reminder: Your contribution of {format_currency(contribution.amount)} 
    for group "{contribution.group.name}" is {'due' if contribution.status == 'pending' else 'overdue'}.
    Due date: {contribution.due_date.strftime('%Y-%m-%d')}
    Please make your payment immediately to avoid penalties.
    """

    try:
        # In-app notification
        Notification.objects.create(
            user=user,
            notification_type='contribution_reminder',
            title='Contribution Reminder',
            message=message,
            contribution=contribution,
            group=contribution.group,
            is_read=False,
        )

        # Email reminder
        send_email(
            to_email=user.email,
            subject=f'Contribution Reminder - {contribution.group.name}',
            message=message,
            html_message=None,
        )

        # SMS if phone available
        if user.phone:
            send_sms(
                phone=user.phone,
                message=message[:160],
            )

        # Update reminder count
        contribution.reminder_count += 1
        contribution.save(update_fields=['reminder_count'])

        # Log reminder
        ContributionReminder.objects.create(
            contribution=contribution,
            user=user,
            reminder_type='email',
            sent_at=timezone.now(),
            sent_successfully=True,
        )

        logger.info(f'Reminder sent for contribution {contribution_id}')
        return True

    except Exception as e:
        logger.error(f'Error sending reminder for contribution {contribution_id}: {str(e)}')
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_overdue_notification(self, contribution_id: int):
    """
    Send a notification about an overdue contribution.
    """
    try:
        contribution = Contribution.objects.get(id=contribution_id, deleted_at__isnull=True)
    except Contribution.DoesNotExist:
        return

    user = contribution.user
    group = contribution.group
    days = contribution.days_overdue_calculated

    from apps.notifications.models import Notification
    from apps.common.utils import send_email

    message = f"""
    Your contribution of {format_currency(contribution.amount)} for group "{group.name}" 
    is overdue by {days} days.
    Penalty: {format_currency(contribution.penalty_amount)}
    Total due: {format_currency(contribution.total_amount_with_penalty)}
    Please make your payment immediately.
    """

    Notification.objects.create(
        user=user,
        notification_type='overdue_warning',
        title='Contribution Overdue',
        message=message,
        contribution=contribution,
        group=group,
        is_read=False,
    )

    send_email(
        to_email=user.email,
        subject=f'URGENT: Contribution Overdue - {group.name}',
        message=message,
        html_message=None,
    )

    logger.info(f'Overdue notification sent for contribution {contribution_id}')


# ============================================================================
# CONTRIBUTION PAYMENT PROCESSING
# ============================================================================

@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def process_contribution_payments(self, payment_id: int):
    """
    Process a contribution payment (external webhook or manual).
    """
    try:
        payment = ContributionPayment.objects.get(id=payment_id)
    except ContributionPayment.DoesNotExist:
        logger.error(f'Payment {payment_id} not found')
        return

    if payment.status != PaymentStatus.PENDING:
        logger.info(f'Payment {payment_id} already processed')
        return

    try:
        with transaction.atomic():
            # Mark payment as completed
            payment.complete()

            # Mark contribution as paid
            contribution = payment.contribution
            if contribution.status in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]:
                contribution.mark_as_paid(
                    payment_method=payment.payment_method,
                    reference=payment.reference,
                    paid_amount=payment.amount,
                )

            logger.info(f'Payment {payment_id} processed successfully')
            return True

    except Exception as e:
        logger.error(f'Error processing payment {payment_id}: {str(e)}')
        # Mark payment as failed
        payment.fail(str(e))
        self.retry(exc=e, countdown=120)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_refunds(self, contribution_id: int):
    """
    Process a refund for a contribution.
    """
    try:
        contribution = Contribution.objects.get(id=contribution_id, deleted_at__isnull=True)
    except Contribution.DoesNotExist:
        logger.error(f'Contribution {contribution_id} not found')
        return

    if contribution.status != ContributionStatus.PAID:
        return

    try:
        with transaction.atomic():
            # Refund payment if exists
            if contribution.payment:
                contribution.payment.refund_payment()

            # Refund contribution
            contribution.refund(reason='Processed refund')

            logger.info(f'Refund processed for contribution {contribution_id}')
            return True

    except Exception as e:
        logger.error(f'Error processing refund for contribution {contribution_id}: {str(e)}')
        raise


# ============================================================================
# STATISTICS UPDATE TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def update_contribution_stats(self, group_id: Optional[int] = None):
    """
    Update denormalized statistics for contributions.
    If group_id provided, update that group's stats; otherwise update all groups.
    """
    if group_id:
        logger.info(f"Starting update_contribution_stats for group {group_id}")
        return _update_group_contribution_stats(group_id)
    else:
        logger.info("Starting update_contribution_stats for all groups")
        return _update_all_group_contribution_stats()


def _update_all_group_contribution_stats() -> Dict[str, Any]:
    """Update stats for all groups."""
    results = {'updated': 0, 'errors': 0}

    groups = Group.objects.filter(deleted_at__isnull=True)
    for group in groups:
        try:
            _update_group_contribution_stats(group.id)
            results['updated'] += 1
        except Exception as e:
            results['errors'] += 1
            logger.error(f'Error updating stats for group {group.id}: {str(e)}')

    return results


def _update_group_contribution_stats(group_id: int) -> Dict[str, Any]:
    """Update denormalized stats for a single group."""
    from apps.groups.models import Group

    try:
        group = Group.objects.get(id=group_id)
    except Group.DoesNotExist:
        return {'error': 'Group not found'}

    contributions = Contribution.objects.filter(group=group, deleted_at__isnull=True)

    total = contributions.count()
    paid = contributions.filter(status=ContributionStatus.PAID).count()
    pending = contributions.filter(status=ContributionStatus.PENDING).count()
    overdue = contributions.filter(status=ContributionStatus.OVERDUE).count()

    total_paid = contributions.filter(status=ContributionStatus.PAID).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    total_pending = contributions.filter(status=ContributionStatus.PENDING).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    total_overdue = contributions.filter(status=ContributionStatus.OVERDUE).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    # Update group fields
    with transaction.atomic():
        group.total_contributions = total
        group.total_paid = total_paid
        group.total_pending = total_pending
        group.total_overdue = total_overdue
        group.save(update_fields=['total_contributions', 'total_paid', 'total_pending', 'total_overdue'])

    logger.info(f'Updated contribution stats for group {group_id}')
    return {
        'group_id': group_id,
        'total': total,
        'paid': paid,
        'pending': pending,
        'overdue': overdue,
        'total_paid_amount': float(total_paid),
        'pending_amount': float(total_pending),
        'overdue_amount': float(total_overdue),
    }


# ============================================================================
# CLEANUP TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def cleanup_completed_contributions(self):
    """
    Clean up completed contributions that are old.
    - Archive contributions older than X days
    - Permanently delete soft-deleted contributions older than Y days
    """
    logger.info("Starting cleanup_completed_contributions task")

    results = {
        'archived': 0,
        'permanently_deleted': 0,
        'errors': 0
    }

    try:
        now = timezone.now()

        # Archive contributions older than 90 days (paid status)
        archive_threshold = now - timedelta(days=90)
        completed_contributions = Contribution.objects.filter(
            status=ContributionStatus.PAID,
            paid_date__lt=archive_threshold,
            deleted_at__isnull=True
        )

        for contribution in completed_contributions:
            try:
                # Mark as archived (could move to archive table)
                # For now, we just log and could create an archive entry
                logger.info(f'Contribution {contribution.id} archived')
                results['archived'] += 1
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error archiving contribution {contribution.id}: {str(e)}')

        # Permanently delete soft-deleted contributions older than 30 days
        delete_threshold = now - timedelta(days=30)
        deleted_contributions = Contribution.objects.filter(
            deleted_at__lt=delete_threshold
        )

        for contribution in deleted_contributions:
            try:
                with transaction.atomic():
                    # Delete related records
                    contribution.reminders.all().delete()
                    contribution.audits.all().delete()
                    if contribution.payment:
                        contribution.payment.delete()
                    # Finally delete the contribution
                    contribution.delete()
                    results['permanently_deleted'] += 1
                    logger.info(f'Contribution {contribution.id} permanently deleted')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error permanently deleting contribution {contribution.id}: {str(e)}')

        logger.info(f'cleanup_completed_contributions completed: {results}')
        return results

    except Exception as e:
        logger.error(f'cleanup_completed_contributions failed: {str(e)}')
        raise


# ============================================================================
# REPORT GENERATION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def generate_contribution_report(self, group_id: int, report_type: str = 'summary'):
    """
    Generate a contribution report for a group or the platform.
    """
    from apps.groups.models import Group
    from django.db.models import Count, Sum

    try:
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        return {'error': 'Group not found'}

    contributions = Contribution.objects.filter(group=group, deleted_at__isnull=True)

    if report_type == 'summary':
        total = contributions.count()
        paid = contributions.filter(status=ContributionStatus.PAID).count()
        pending = contributions.filter(status=ContributionStatus.PENDING).count()
        overdue = contributions.filter(status=ContributionStatus.OVERDUE).count()
        total_paid = contributions.filter(status=ContributionStatus.PAID).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        return {
            'group_id': group.id,
            'group_name': group.name,
            'total_contributions': total,
            'paid': paid,
            'pending': pending,
            'overdue': overdue,
            'total_paid_amount': float(total_paid),
            'completion_rate': round((paid / total * 100) if total > 0 else 0, 2),
        }

    elif report_type == 'detailed':
        member_contributions = []
        members = group.get_members().select_related('user')
        for member in members:
            user_contribs = contributions.filter(user=member.user)
            total = user_contribs.count()
            paid = user_contribs.filter(status=ContributionStatus.PAID).count()
            pending = user_contribs.filter(status=ContributionStatus.PENDING).count()
            overdue = user_contribs.filter(status=ContributionStatus.OVERDUE).count()
            total_paid = user_contribs.filter(status=ContributionStatus.PAID).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0.00')

            member_contributions.append({
                'user_id': member.user.id,
                'user_name': member.user.full_name,
                'user_email': member.user.email,
                'total': total,
                'paid': paid,
                'pending': pending,
                'overdue': overdue,
                'total_paid_amount': float(total_paid),
            })

        return {
            'group_id': group.id,
            'group_name': group.name,
            'members': member_contributions,
        }

    return {'error': 'Unknown report type'}


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_contribution_digest(self):
    """
    Send a digest of contribution activities to users.
    """
    logger.info("Starting send_contribution_digest task")

    # Get users who have opted in for contribution digest
    users = User.objects.filter(
        is_active=True,
        notification_preferences__contribution_digest=True,
        deleted_at__isnull=True
    )

    sent_count = 0
    for user in users:
        try:
            # Get user's pending/overdue contributions
            pending = Contribution.objects.filter(
                user=user,
                status=ContributionStatus.PENDING,
                deleted_at__isnull=True
            ).select_related('group')
            overdue = Contribution.objects.filter(
                user=user,
                status=ContributionStatus.OVERDUE,
                deleted_at__isnull=True
            ).select_related('group')

            if not pending.exists() and not overdue.exists():
                continue

            digest_data = {
                'user': user,
                'pending': pending,
                'overdue': overdue,
                'date': timezone.now(),
                'pending_count': pending.count(),
                'overdue_count': overdue.count(),
            }

            # Send email digest
            subject = f'Contribution Digest: {timezone.now().strftime("%Y-%m-%d")}'
            html_message = render_to_string('emails/contribution_digest.html', digest_data)
            plain_message = f"""
            Contribution Digest for {user.full_name}

            Pending Contributions: {pending.count()}
            Overdue Contributions: {overdue.count()}

            Please visit the app to view details.
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

    logger.info(f'send_contribution_digest completed: sent to {sent_count} users')
    return sent_count


# ============================================================================
# AUTO-WAIVE OVERDUE CONTRIBUTIONS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def auto_waive_overdue_contributions(self):
    """
    Auto-waive overdue contributions that exceed the maximum threshold.
    """
    logger.info("Starting auto_waive_overdue_contributions task")

    results = {
        'waived': 0,
        'errors': 0
    }

    try:
        # Overdue contributions older than 90 days
        threshold = timezone.now() - timedelta(days=90)
        overdue_contributions = Contribution.objects.filter(
            status=ContributionStatus.OVERDUE,
            due_date__lt=threshold,
            deleted_at__isnull=True
        )

        for contribution in overdue_contributions:
            try:
                with transaction.atomic():
                    contribution.waive(
                        contribution.amount,
                        reason='Auto-waived after 90 days overdue'
                    )
                    results['waived'] += 1

                    # Notify user
                    from apps.notifications.models import Notification
                    Notification.objects.create(
                        user=contribution.user,
                        notification_type='contribution_waived',
                        title='Contribution Waived',
                        message=f'Your contribution of {format_currency(contribution.amount)} for group "{contribution.group.name}" has been waived due to prolonged overdue.',
                        contribution=contribution,
                        group=contribution.group,
                        is_read=False,
                    )

                    logger.info(f'Contribution {contribution.id} auto-waived')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error auto-waiving contribution {contribution.id}: {str(e)}')

        logger.info(f'auto_waive_overdue_contributions completed: {results}')
        return results

    except Exception as e:
        logger.error(f'auto_waive_overdue_contributions failed: {str(e)}')
        raise


# ============================================================================
# BULK OPERATION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_bulk_contributions(self, group_id: int, round_number: int, amount: Decimal, created_by_id: Optional[int] = None):
    """
    Bulk create contributions for a group in a round.
    """
    from apps.groups.models import Group
    from apps.users.models import User

    try:
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        return {'error': 'Group not found'}

    created_by = None
    if created_by_id:
        try:
            created_by = User.objects.get(id=created_by_id)
        except User.DoesNotExist:
            pass

    members = GroupMember.objects.filter(group=group, is_active=True).select_related('user')
    created = 0
    errors = 0

    for member in members:
        try:
            contribution = Contribution.objects.create(
                user=member.user,
                group=group,
                round=round_number,
                amount=amount,
                due_date=timezone.now() + timedelta(days=30),
                status=ContributionStatus.PENDING,
                contribution_type=ContributionType.REGULAR,
                created_by=created_by,
            )
            created += 1
        except Exception as e:
            errors += 1
            logger.error(f'Error creating contribution for user {member.user.id}: {str(e)}')

    logger.info(f'Bulk created {created} contributions for group {group_id}')
    return {'created': created, 'errors': errors}


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_bulk_status_update(self, contribution_ids: List[int], status: str, reason: Optional[str] = None):
    """
    Bulk update status for multiple contributions.
    """
    contributions = Contribution.objects.filter(
        id__in=contribution_ids,
        deleted_at__isnull=True
    )

    processed = 0
    errors = 0

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
            errors += 1
            logger.error(f'Error updating contribution {contribution.id}: {str(e)}')

    return {'processed': processed, 'errors': errors}


# ============================================================================
# TASK SCHEDULING (BROKER CONFIG)
# ============================================================================

# These tasks should be scheduled in celery beat schedule:
# - process_pending_contributions: every hour
# - check_overdue_contributions: every 6 hours
# - send_contribution_digest: daily at 7:00 AM
# - cleanup_completed_contributions: weekly on Sunday at 2:00 AM
# - auto_waive_overdue_contributions: daily at 1:00 AM
# - update_contribution_stats: every 6 hours


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'process_pending_contributions',
    'check_overdue_contributions',
    'send_contribution_reminder',
    'send_overdue_notification',
    'process_contribution_payments',
    'process_refunds',
    'update_contribution_stats',
    'cleanup_completed_contributions',
    'generate_contribution_report',
    'send_contribution_digest',
    'auto_waive_overdue_contributions',
    'process_bulk_contributions',
    'process_bulk_status_update',
]