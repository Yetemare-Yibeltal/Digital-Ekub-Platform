"""
Celery tasks for the groups app.

This module provides background task functions for group operations:
- Processing expired groups (auto-cancel or auto-complete)
- Auto-selecting winners when round ends
- Sending daily/weekly reminders to members
- Processing group completion (closing groups, final payouts)
- Cleaning up inactive groups
- Updating group statistics (denormalized fields)
- Sending notification digests
- Monitoring group health
- Generating group reports
- Archiving completed groups

All tasks include comprehensive error handling, logging, and retry logic.
"""

from celery import shared_task
from celery.utils.log import get_task_logger
from django.db import transaction
from django.db.models import Q, Count, Sum, Avg, F, OuterRef, Subquery
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple

from apps.users.models import User
from apps.common.utils import send_email, send_sms, format_currency, log_audit_event
from apps.common.constants import GroupStatus, ContributionStatus, PaymentStatus, PayoutStatus

from .models import Group, GroupMember, GroupInvitation, GroupActivity, GroupWinnerHistory

logger = get_task_logger(__name__)


# ============================================================================
# GROUP EXPIRATION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_expired_groups(self):
    """
    Process groups that have passed their end date or have been pending too long.
    - Auto-cancel groups that haven't started after X days
    - Auto-complete groups that have reached end date but haven't been completed
    - Handle groups that have been paused for too long
    """
    logger.info("Starting process_expired_groups task")

    results = {
        'cancelled': 0,
        'completed': 0,
        'paused_expired': 0,
        'pending_expired': 0,
        'errors': 0
    }

    try:
        now = timezone.now()
        pending_threshold = now - timedelta(days=7)
        paused_threshold = now - timedelta(days=30)
        completion_threshold = now - timedelta(days=14)  # Auto-complete after 14 days past end date

        # ========================================================================
        # 1. Cancel pending groups that haven't been activated within 7 days
        # ========================================================================
        pending_groups = Group.objects.filter(
            status=GroupStatus.PENDING,
            created_at__lt=pending_threshold,
            deleted_at__isnull=True
        )

        for group in pending_groups:
            try:
                with transaction.atomic():
                    group.cancel_group(reason='Auto-cancelled: Group not activated within 7 days')
                    results['pending_expired'] += 1
                    logger.info(f'Pending group {group.id} auto-cancelled')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error cancelling pending group {group.id}: {str(e)}')

        # ========================================================================
        # 2. Auto-complete groups that are past their end date by more than 14 days
        # ========================================================================
        expired_groups = Group.objects.filter(
            status=GroupStatus.ACTIVE,
            end_date__lt=completion_threshold,
            deleted_at__isnull=True
        )

        for group in expired_groups:
            try:
                # Check if all contributions are settled
                from apps.contributions.models import Contribution
                pending_contributions = Contribution.objects.filter(
                    group=group,
                    status__in=[ContributionStatus.PENDING, ContributionStatus.OVERDUE]
                )

                if pending_contributions.exists():
                    # Mark as overdue and send reminders first
                    pending_contributions.update(status=ContributionStatus.OVERDUE)
                    logger.info(f'Group {group.id}: marked {pending_contributions.count()} contributions as overdue')
                else:
                    with transaction.atomic():
                        group.complete_group()
                        results['completed'] += 1
                        logger.info(f'Group {group.id} auto-completed')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error completing group {group.id}: {str(e)}')

        # ========================================================================
        # 3. Process groups that have been paused for more than 30 days
        # ========================================================================
        paused_groups = Group.objects.filter(
            status=GroupStatus.PAUSED,
            paused_at__lt=paused_threshold,
            deleted_at__isnull=True
        )

        for group in paused_groups:
            try:
                with transaction.atomic():
                    group.cancel_group(reason='Auto-cancelled: Group paused for more than 30 days')
                    results['paused_expired'] += 1
                    logger.info(f'Paused group {group.id} auto-cancelled')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error cancelling paused group {group.id}: {str(e)}')

        logger.info(f'process_expired_groups completed: {results}')
        return results

    except Exception as e:
        logger.error(f'process_expired_groups failed: {str(e)}')
        self.retry(exc=e, countdown=60)
        raise


# ============================================================================
# AUTO-SELECT WINNER TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def auto_select_winner(self, group_id=None):
    """
    Auto-select winners for groups that are ready for the next round.
    If group_id is provided, only process that group; otherwise process all groups.
    """
    if group_id:
        logger.info(f"Starting auto_select_winner for group {group_id}")
        return _process_single_group_winner(group_id)
    else:
        logger.info("Starting auto_select_winner for all eligible groups")
        return _process_all_groups_winners()


def _process_all_groups_winners():
    """Process all groups that are ready for winner selection."""
    results = {
        'selected': 0,
        'already_selected': 0,
        'errors': 0,
        'details': []
    }

    # Groups that are active and have members
    groups = Group.objects.filter(
        status=GroupStatus.ACTIVE,
        members_count__gte=2,
        deleted_at__isnull=True
    )

    for group in groups:
        try:
            result = _process_single_group_winner(group.id)
            if result:
                results['selected'] += 1
                results['details'].append(result)
            else:
                results['already_selected'] += 1
        except Exception as e:
            results['errors'] += 1
            logger.error(f'Error selecting winner for group {group.id}: {str(e)}')

    logger.info(f'auto_select_winner completed: {results}')
    return results


def _process_single_group_winner(group_id: int) -> Optional[Dict[str, Any]]:
    """
    Process winner selection for a single group.

    Returns:
        Dict with winner info or None if no winner selected.
    """
    from apps.contributions.models import Contribution

    try:
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        logger.warning(f'Group {group_id} not found')
        return None

    # Check if group is active and has members
    if not group.is_active or group.members_count < 2:
        return None

    # Check if group is already completed
    if group.is_completed:
        return None

    # Check if all members have contributed for the current round
    # Count how many members have paid for the current round
    paid_contributions = Contribution.objects.filter(
        group=group,
        round=group.current_round,
        status=ContributionStatus.PAID
    ).count()

    # Check if winner already selected for this round
    already_selected = GroupWinnerHistory.objects.filter(
        group=group,
        round=group.current_round
    ).exists()

    if already_selected:
        return None

    # Check if all members have paid (full pot) - if not, skip auto-selection
    if paid_contributions < group.members_count:
        # Wait until all contributions are paid before auto-selecting
        logger.info(f'Group {group.id}: not all members paid ({paid_contributions}/{group.members_count})')
        return None

    # All members have paid, select winner
    winner = group.select_winner()
    if not winner:
        logger.warning(f'Group {group.id}: no eligible winner found')
        return None

    # Record winner
    with transaction.atomic():
        history = GroupWinnerHistory.objects.create(
            group=group,
            user=winner,
            round=group.current_round,
            amount=group.current_pot_amount,
        )

        group.log_activity(
            action='winner_auto_selected',
            user=None,
            details={
                'winner_id': winner.id,
                'round': group.current_round,
                'amount': str(group.current_pot_amount),
            }
        )

        # Advance round
        group.advance_round()

        logger.info(f'Winner auto-selected for group {group.id}: user {winner.id}')

    return {
        'group_id': group.id,
        'group_name': group.name,
        'winner_id': winner.id,
        'winner_name': winner.full_name,
        'round': history.round,
        'amount': float(group.current_pot_amount),
    }


# ============================================================================
# REMINDER TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_group_reminders(self, group_id=None):
    """
    Send reminders to group members for upcoming contributions.
    """
    if group_id:
        logger.info(f"Starting send_group_reminders for group {group_id}")
        return _send_reminders_for_group(group_id)
    else:
        logger.info("Starting send_group_reminders for all groups")
        return _send_reminders_for_all_groups()


def _send_reminders_for_all_groups() -> Dict[str, Any]:
    """Send reminders to all active groups."""
    results = {
        'groups_processed': 0,
        'reminders_sent': 0,
        'errors': 0
    }

    groups = Group.objects.filter(
        status=GroupStatus.ACTIVE,
        deleted_at__isnull=True
    )

    for group in groups:
        try:
            result = _send_reminders_for_group(group.id)
            results['groups_processed'] += 1
            results['reminders_sent'] += result.get('sent', 0)
        except Exception as e:
            results['errors'] += 1
            logger.error(f'Error sending reminders for group {group.id}: {str(e)}')

    logger.info(f'send_group_reminders completed: {results}')
    return results


def _send_reminders_for_group(group_id: int) -> Dict[str, Any]:
    """
    Send reminders for a specific group.

    Returns:
        Dict with number of reminders sent.
    """
    from apps.contributions.models import Contribution
    from apps.notifications.tasks import send_bulk_notifications

    try:
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        return {'sent': 0, 'error': 'Group not found'}

    if not group.is_active:
        return {'sent': 0, 'error': 'Group not active'}

    # Find members who haven't paid for the current round
    paid_user_ids = Contribution.objects.filter(
        group=group,
        round=group.current_round,
        status=ContributionStatus.PAID
    ).values_list('user_id', flat=True)

    # Active members who haven't paid yet
    unpaid_members = GroupMember.objects.filter(
        group=group,
        is_active=True
    ).exclude(user_id__in=paid_user_ids)

    if not unpaid_members.exists():
        return {'sent': 0, 'message': 'All members have paid'}

    # Send reminders
    message = f"""
    Reminder: Your contribution of {format_currency(group.contribution_amount)} for group "{group.name}" is due.
    Please make your payment before the deadline.
    """

    user_ids = list(unpaid_members.values_list('user_id', flat=True))
    send_bulk_notifications.delay(
        user_ids=user_ids,
        message=message,
        notification_type='reminder',
        group_id=group.id
    )

    return {
        'sent': len(user_ids),
        'users': user_ids
    }


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_daily_digest(self):
    """
    Send daily digest emails to users with their group activities.
    """
    logger.info("Starting send_daily_digest task")

    # Get users who have opted in for daily digest
    users = User.objects.filter(
        is_active=True,
        notification_preferences__daily_digest=True,
        deleted_at__isnull=True
    )

    sent_count = 0
    for user in users:
        try:
            _send_user_daily_digest(user.id)
            sent_count += 1
        except Exception as e:
            logger.error(f'Error sending digest to user {user.id}: {str(e)}')

    logger.info(f'send_daily_digest completed: sent to {sent_count} users')
    return sent_count


def _send_user_daily_digest(user_id: int) -> bool:
    """
    Send daily digest to a single user.

    Returns:
        bool: True if sent successfully.
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return False

    # Get user's active groups
    member_groups = GroupMember.objects.filter(
        user=user,
        is_active=True
    ).values_list('group_id', flat=True)

    groups = Group.objects.filter(id__in=member_groups, deleted_at__isnull=True)

    if not groups.exists():
        return False

    # Prepare digest data
    digest_data = []
    for group in groups:
        pending_contributions = group.get_pending_contributions().filter(user=user)
        overdue_contributions = group.get_overdue_contributions().filter(user=user)

        digest_data.append({
            'group_name': group.name,
            'pending_count': pending_contributions.count(),
            'overdue_count': overdue_contributions.count(),
            'next_round_date': group.next_round_date,
            'status': group.status,
        })

    # Send email
    subject = f'Daily Digest: Your Ekub Groups ({timezone.now().strftime("%Y-%m-%d")})'
    html_message = render_to_string('emails/daily_digest.html', {
        'user': user,
        'groups': digest_data,
        'date': timezone.now(),
        'app_name': 'Ekub Platform',
        'support_email': settings.DEFAULT_FROM_EMAIL,
    })
    plain_message = f"""
    Daily Digest for {user.full_name}

    Your Groups:
    {chr(10).join([f'- {g["group_name"]}: Pending: {g["pending_count"]}, Overdue: {g["overdue_count"]}' for g in digest_data])}

    Visit the app for more details.
    """

    send_mail(
        subject,
        plain_message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html_message,
        fail_silently=False
    )

    return True


# ============================================================================
# GROUP COMPLETION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_group_completion(self, group_id):
    """
    Process group completion: distribute payouts, close group, archive.

    Args:
        group_id: ID of the group to complete
    """
    logger.info(f"Starting process_group_completion for group {group_id}")

    try:
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        logger.error(f'Group {group_id} not found')
        return {'error': 'Group not found'}

    if group.is_completed:
        logger.info(f'Group {group_id} already completed')
        return {'status': 'already_completed'}

    # Check if all contributions are paid
    from apps.contributions.models import Contribution
    pending = Contribution.objects.filter(group=group, status__in=[ContributionStatus.PENDING, ContributionStatus.OVERDUE])
    if pending.exists():
        logger.warning(f'Group {group_id} has {pending.count()} pending/overdue contributions')
        # Send reminders to defaulting members
        user_ids = pending.values_list('user_id', flat=True).distinct()
        for user_id in user_ids:
            try:
                user = User.objects.get(id=user_id)
                send_reminder_to_user.delay(user.id, group.id)
            except User.DoesNotExist:
                pass
        return {'status': 'has_pending', 'count': pending.count()}

    # All contributions are paid, complete the group
    with transaction.atomic():
        group.complete_group()
        logger.info(f'Group {group_id} completed')

        # Notify all members
        members = group.get_members()
        user_ids = list(members.values_list('user_id', flat=True))
        message = f'Group "{group.name}" has been completed successfully! Thank you for participating.'
        send_bulk_notifications.delay(
            user_ids=user_ids,
            message=message,
            notification_type='group_completed',
            group_id=group.id
        )

    return {'status': 'completed', 'group_id': group.id}


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_reminder_to_user(self, user_id: int, group_id: int):
    """
    Send a reminder to a specific user about pending contributions.

    Args:
        user_id: ID of the user
        group_id: ID of the group
    """
    try:
        user = User.objects.get(id=user_id)
        group = Group.objects.get(id=group_id)
    except (User.DoesNotExist, Group.DoesNotExist):
        return

    from apps.contributions.models import Contribution
    pending_contributions = Contribution.objects.filter(
        group=group,
        user=user,
        status__in=[ContributionStatus.PENDING, ContributionStatus.OVERDUE]
    )

    if not pending_contributions.exists():
        return

    amount = pending_contributions.aggregate(total=Sum('amount'))['total'] or 0

    subject = f'Action Required: Pending Contributions for "{group.name}"'
    message = f"""
    Dear {user.full_name},

    You have pending contributions for group "{group.name}".
    Total amount: {format_currency(amount)}
    Number of pending: {pending_contributions.count()}

    Please make your payment as soon as possible to avoid penalties.

    Thank you,
    Ekub Platform Team
    """

    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True
    )


# ============================================================================
# STATISTICS UPDATE TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def update_group_stats(self, group_id=None):
    """
    Update denormalized statistics for groups.

    If group_id is provided, update only that group; otherwise update all groups.
    """
    if group_id:
        logger.info(f"Starting update_group_stats for group {group_id}")
        return _update_single_group_stats(group_id)
    else:
        logger.info("Starting update_group_stats for all groups")
        return _update_all_group_stats()


def _update_all_group_stats() -> Dict[str, Any]:
    """Update stats for all groups."""
    results = {
        'updated': 0,
        'errors': 0
    }

    groups = Group.objects.filter(deleted_at__isnull=True)
    for group in groups:
        try:
            _update_single_group_stats(group.id)
            results['updated'] += 1
        except Exception as e:
            results['errors'] += 1
            logger.error(f'Error updating stats for group {group.id}: {str(e)}')

    return results


def _update_single_group_stats(group_id: int) -> Dict[str, Any]:
    """
    Update denormalized stats for a single group.

    Returns:
        Dict with updated statistics.
    """
    from apps.contributions.models import Contribution
    from apps.payments.models import Payout

    try:
        group = Group.objects.get(id=group_id)
    except Group.DoesNotExist:
        return {'error': 'Group not found'}

    # Update members count
    members_count = GroupMember.objects.filter(group=group, is_active=True).count()

    # Update contribution statistics
    contributions = Contribution.objects.filter(group=group)
    total_contributions = contributions.count()
    paid_count = contributions.filter(status=ContributionStatus.PAID).count()
    pending_count = contributions.filter(status=ContributionStatus.PENDING).count()
    overdue_count = contributions.filter(status=ContributionStatus.OVERDUE).count()

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
        group.members_count = members_count
        group.total_contributions = total_contributions
        group.total_paid = total_paid
        group.total_pending = total_pending
        group.total_overdue = total_overdue
        group.save(update_fields=[
            'members_count', 'total_contributions',
            'total_paid', 'total_pending', 'total_overdue'
        ])

    return {
        'group_id': group.id,
        'members_count': members_count,
        'total_contributions': total_contributions,
        'paid_count': paid_count,
        'pending_count': pending_count,
        'overdue_count': overdue_count,
        'total_paid': float(total_paid),
        'total_pending': float(total_pending),
        'total_overdue': float(total_overdue),
    }


# ============================================================================
# CLEANUP TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def cleanup_inactive_groups(self):
    """
    Clean up inactive groups that have been deleted or inactive for a long time.
    - Archive completed groups after X days
    - Permanently delete groups that have been soft-deleted for X days
    """
    logger.info("Starting cleanup_inactive_groups task")

    results = {
        'archived': 0,
        'permanently_deleted': 0,
        'errors': 0
    }

    try:
        now = timezone.now()

        # Archive completed groups after 30 days
        archive_threshold = now - timedelta(days=30)
        completed_groups = Group.objects.filter(
            status=GroupStatus.COMPLETED,
            completed_at__lt=archive_threshold,
            deleted_at__isnull=True
        )

        for group in completed_groups:
            try:
                # Mark as archived (could set a flag or move to archive table)
                # For now, we just log it and could create an archive entry
                logger.info(f'Group {group.id} archived (completed on {group.completed_at})')
                results['archived'] += 1
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error archiving group {group.id}: {str(e)}')

        # Permanently delete groups that have been soft-deleted for 90 days
        delete_threshold = now - timedelta(days=90)
        deleted_groups = Group.objects.filter(
            deleted_at__lt=delete_threshold
        )

        for group in deleted_groups:
            try:
                # Delete related data first
                with transaction.atomic():
                    # Delete related records
                    GroupMember.objects.filter(group=group).delete()
                    GroupInvitation.objects.filter(group=group).delete()
                    GroupSetting.objects.filter(group=group).delete()
                    GroupActivity.objects.filter(group=group).delete()
                    GroupWinnerHistory.objects.filter(group=group).delete()
                    # Finally delete the group
                    group.delete()
                    results['permanently_deleted'] += 1
                    logger.info(f'Group {group.id} permanently deleted')
            except Exception as e:
                results['errors'] += 1
                logger.error(f'Error permanently deleting group {group.id}: {str(e)}')

    except Exception as e:
        logger.error(f'cleanup_inactive_groups failed: {str(e)}')
        raise

    logger.info(f'cleanup_inactive_groups completed: {results}')
    return results


# ============================================================================
# NOTIFICATION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_bulk_notifications(self, user_ids: List[int], message: str, notification_type: str = 'info', group_id: Optional[int] = None):
    """
    Send bulk notifications to multiple users.

    Args:
        user_ids: List of user IDs
        message: Message to send
        notification_type: Type of notification
        group_id: Optional group ID for context
    """
    if not user_ids:
        return {'sent': 0, 'message': 'No users'}

    from apps.notifications.models import Notification
    from apps.notifications.services import send_notification

    sent_count = 0
    for user_id in user_ids:
        try:
            user = User.objects.get(id=user_id)
            send_notification(
                user=user,
                message=message,
                notification_type=notification_type,
                group_id=group_id,
                send_email=True,
                send_push=True,
                send_sms=False,
            )
            sent_count += 1
        except User.DoesNotExist:
            continue
        except Exception as e:
            logger.error(f'Error sending notification to user {user_id}: {str(e)}')

    return {'sent': sent_count, 'total': len(user_ids)}


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_group_activity_digest(self, group_id):
    """
    Send a digest of group activities to all members.

    Args:
        group_id: ID of the group
    """
    try:
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        return {'error': 'Group not found'}

    # Get recent activities (last 7 days)
    threshold = timezone.now() - timedelta(days=7)
    activities = GroupActivity.objects.filter(
        group=group,
        timestamp__gte=threshold
    ).order_by('-timestamp')[:20]

    if not activities.exists():
        return {'message': 'No recent activities'}

    # Get all active members
    members = group.get_members()
    user_ids = list(members.values_list('user_id', flat=True))

    if not user_ids:
        return {'message': 'No members to notify'}

    # Prepare digest message
    activity_messages = [f'- {act.action} at {act.timestamp.strftime("%Y-%m-%d %H:%M")}' for act in activities]
    message = f"""
    Group Activity Digest for "{group.name}"

    Recent activities ({len(activities)} events):
    {chr(10).join(activity_messages)}

    View full details in the app.
    """

    for user_id in user_ids:
        try:
            user = User.objects.get(id=user_id)
            send_notification.delay(
                user_id=user.id,
                message=message,
                notification_type='digest',
                group_id=group.id,
                send_email=True,
                send_push=True,
                send_sms=False,
            )
        except User.DoesNotExist:
            continue

    return {'sent': len(user_ids), 'activities': len(activities)}


# ============================================================================
# MONITORING TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def monitor_group_health(self):
    """
    Monitor group health and alert on issues.
    - Detect groups with high default rates
    - Detect groups that haven't had activity in X days
    - Detect groups with overdue contributions
    """
    logger.info("Starting monitor_group_health task")

    results = {
        'warning_groups': [],
        'critical_groups': [],
        'healthy_groups': 0
    }

    groups = Group.objects.filter(
        status=GroupStatus.ACTIVE,
        deleted_at__isnull=True
    )

    for group in groups:
        issues = []
        is_critical = False

        # Check for overdue contributions
        from apps.contributions.models import Contribution
        overdue_count = Contribution.objects.filter(
            group=group,
            status=ContributionStatus.OVERDUE
        ).count()

        if overdue_count > 0:
            issues.append(f'{overdue_count} overdue contributions')
            if overdue_count > group.members_count * 0.5:
                is_critical = True

        # Check for inactivity
        last_activity = GroupActivity.objects.filter(group=group).order_by('-timestamp').first()
        if last_activity and (timezone.now() - last_activity.timestamp).days > 7:
            issues.append('No activity for over 7 days')

        # Check for completion progress
        if group.progress_percentage > 90 and group.current_round < group.cycle_length:
            issues.append('Progress > 90% but not complete')

        # Check for low member count
        if group.members_count < 3:
            issues.append('Less than 3 members')

        if issues:
            group_data = {
                'group_id': group.id,
                'group_name': group.name,
                'issues': issues,
                'is_critical': is_critical
            }
            if is_critical:
                results['critical_groups'].append(group_data)
                # Send alert to admins
                _send_health_alert.delay(group.id, issues, critical=True)
            else:
                results['warning_groups'].append(group_data)
        else:
            results['healthy_groups'] += 1

    logger.info(f'monitor_group_health completed: {results}')
    return results


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def _send_health_alert(self, group_id, issues, critical=False):
    """
    Send health alert for a group.
    """
    try:
        group = Group.objects.get(id=group_id)
    except Group.DoesNotExist:
        return

    # Get group admins
    admins = group.get_admins()
    admin_emails = list(admins.values_list('user__email', flat=True))

    if not admin_emails:
        return

    subject = f'{"CRITICAL" if critical else "WARNING"}: Group "{group.name}" Health Alert'
    message = f"""
    Group: {group.name} (ID: {group.id})
    Status: {group.status}
    Members: {group.members_count}
    Current Round: {group.current_round + 1}/{group.cycle_length}
    Progress: {group.progress_percentage}%

    Issues found:
    {chr(10).join([f'- {issue}' for issue in issues])}

    Please take action to resolve these issues.
    """

    for email in admin_emails:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=True
        )

    logger.info(f'Sent health alert to {len(admin_emails)} admins for group {group_id}')


# ============================================================================
# REPORT GENERATION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def generate_group_report(self, group_id, report_type='summary'):
    """
    Generate a report for a group (summary, financial, member activity).

    Args:
        group_id: ID of the group
        report_type: Type of report (summary, financial, member_activity)

    Returns:
        Dict with report data.
    """
    try:
        group = Group.objects.get(id=group_id)
    except Group.DoesNotExist:
        return {'error': 'Group not found'}

    from apps.contributions.models import Contribution
    from apps.payments.models import Payout

    if report_type == 'summary':
        # Group summary
        members = group.get_members()
        total_contributions = Contribution.objects.filter(group=group).count()
        total_paid = Contribution.objects.filter(group=group, status=ContributionStatus.PAID).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        total_payouts = Payout.objects.filter(group=group, status=PayoutStatus.COMPLETED).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        return {
            'group': {
                'id': group.id,
                'name': group.name,
                'status': group.status,
                'created_at': group.created_at,
                'members_count': group.members_count,
            },
            'statistics': {
                'total_contributions': total_contributions,
                'total_paid': float(total_paid),
                'total_payouts': float(total_payouts),
                'current_round': group.current_round + 1,
                'total_cycles': group.cycle_length,
                'progress': group.progress_percentage,
            }
        }

    elif report_type == 'financial':
        # Financial report with contributions per member
        member_contributions = []
        for member in group.get_members().select_related('user'):
            contribs = Contribution.objects.filter(group=group, user=member.user)
            total = contribs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            paid = contribs.filter(status=ContributionStatus.PAID).count()
            pending = contribs.filter(status=ContributionStatus.PENDING).count()
            overdue = contribs.filter(status=ContributionStatus.OVERDUE).count()
            member_contributions.append({
                'user_id': member.user.id,
                'user_name': member.user.full_name,
                'user_email': member.user.email,
                'role': member.role,
                'total_contributions': contribs.count(),
                'paid': paid,
                'pending': pending,
                'overdue': overdue,
                'total_amount': float(total),
            })

        return {
            'group': {
                'id': group.id,
                'name': group.name,
                'contribution_amount': float(group.contribution_amount),
                'frequency': group.frequency,
            },
            'member_contributions': member_contributions
        }

    elif report_type == 'member_activity':
        # Member activity report
        activities = GroupActivity.objects.filter(group=group).order_by('-timestamp')[:100]
        return {
            'group_id': group.id,
            'group_name': group.name,
            'activities': [
                {
                    'action': act.action,
                    'user': act.user.full_name if act.user else 'System',
                    'timestamp': act.timestamp,
                    'details': act.details,
                }
                for act in activities
            ]
        }

    return {'error': 'Unknown report type'}


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_report_to_admins(self, group_id, report_type='summary'):
    """
    Generate and send a report to group admins via email.

    Args:
        group_id: ID of the group
        report_type: Type of report
    """
    report = generate_group_report(group_id, report_type)
    if 'error' in report:
        logger.error(f'Error generating report for group {group_id}: {report["error"]}')
        return report

    try:
        group = Group.objects.get(id=group_id)
    except Group.DoesNotExist:
        return {'error': 'Group not found'}

    admins = group.get_admins()
    admin_emails = list(admins.values_list('user__email', flat=True))

    if not admin_emails:
        return {'message': 'No admins to send report'}

    subject = f'Group Report: "{group.name}" ({report_type})'
    plain_message = f"""
    Group Report for "{group.name}"

    Report Type: {report_type}
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

    logger.info(f'Sent {report_type} report for group {group_id} to {len(admin_emails)} admins')
    return {'sent': len(admin_emails)}


# ============================================================================
# TASK SCHEDULING (BROKER CONFIG)
# ============================================================================

# These tasks should be scheduled in celery beat schedule:
# - process_expired_groups: every 6 hours
# - auto_select_winner: every 12 hours
# - send_group_reminders: daily at 8:00 AM
# - send_daily_digest: daily at 7:00 AM
# - update_group_stats: every 6 hours
# - cleanup_inactive_groups: weekly on Sunday at 3:00 AM
# - monitor_group_health: daily at 10:00 AM

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'process_expired_groups',
    'auto_select_winner',
    'send_group_reminders',
    'send_daily_digest',
    'process_group_completion',
    'send_reminder_to_user',
    'update_group_stats',
    'cleanup_inactive_groups',
    'send_bulk_notifications',
    'send_group_activity_digest',
    'monitor_group_health',
    'generate_group_report',
    'send_report_to_admins',
]