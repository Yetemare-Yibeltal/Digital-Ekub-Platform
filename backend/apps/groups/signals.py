"""
Signals for the groups app.

This module provides signal handlers for all group-related models:
- Group: handle status changes, updates, and deletions
- GroupMember: handle membership changes, stats updates, and notifications
- GroupInvitation: handle invitation lifecycle events
- GroupSetting: handle setting changes and cache invalidation
- GroupActivity: handle activity logging and updates
- GroupWinnerHistory: handle winner selection events

All signals include comprehensive logging, error handling, and task dispatching.
"""

import logging
from django.db.models.signals import post_save, pre_save, pre_delete, post_delete, m2m_changed
from django.dispatch import receiver
from django.utils import timezone
from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum, Count, F
from decimal import Decimal

from apps.users.models import User
from apps.common.utils import log_audit_event, get_current_time
from apps.common.constants import GroupStatus, GroupMemberRole, GroupInvitationStatus

from .models import (
    Group, GroupMember, GroupInvitation, GroupSetting,
    GroupActivity, GroupWinnerHistory
)
from .tasks import (
    update_group_stats, auto_select_winner, send_group_reminders,
    process_group_completion, send_bulk_notifications
)

logger = logging.getLogger(__name__)


# ============================================================================
# GROUP SIGNALS
# ============================================================================

@receiver(pre_save, sender=Group)
def group_pre_save_handler(sender, instance, **kwargs):
    """
    Handle pre-save events for Group model:
    - Auto-set end_date based on start_date and cycle_length
    - Validate status transitions
    - Set completed_at when status changes to completed
    - Set cancelled_at when status changes to cancelled
    - Set paused_at when status changes to paused
    """
    if instance.pk:
        try:
            old = Group.objects.get(pk=instance.pk)
        except Group.DoesNotExist:
            old = None

        # Auto-set end_date if not set and start_date and cycle_length exist
        if not instance.end_date and instance.start_date and instance.cycle_length:
            frequency_map = {
                'daily': timezone.timedelta(days=1),
                'weekly': timezone.timedelta(weeks=1),
                'biweekly': timezone.timedelta(weeks=2),
                'monthly': timezone.timedelta(days=30),
                'quarterly': timezone.timedelta(days=90),
                'yearly': timezone.timedelta(days=365),
            }
            duration = frequency_map.get(instance.frequency, timezone.timedelta(days=30))
            instance.end_date = instance.start_date + (duration * instance.cycle_length)

        # Status transition validation
        if old and old.status != instance.status:
            # Prevent reactivation of completed or cancelled groups
            if old.status in [GroupStatus.COMPLETED, GroupStatus.CANCELLED] and instance.status == GroupStatus.ACTIVE:
                raise ValueError(f"Cannot reactivate a {old.status} group.")

            # If changing to completed, set completed_at
            if instance.status == GroupStatus.COMPLETED and not instance.completed_at:
                instance.completed_at = timezone.now()

            # If changing to cancelled, set cancelled_at
            if instance.status == GroupStatus.CANCELLED and not instance.cancelled_at:
                instance.cancelled_at = timezone.now()

            # If changing to paused, set paused_at
            if instance.status == GroupStatus.PAUSED and not instance.paused_at:
                instance.paused_at = timezone.now()

            # If resuming from paused, clear paused_at
            if old.status == GroupStatus.PAUSED and instance.status == GroupStatus.ACTIVE:
                instance.paused_at = None

            # If changing to active from pending, ensure start_date is set
            if old.status == GroupStatus.PENDING and instance.status == GroupStatus.ACTIVE:
                if not instance.start_date:
                    instance.start_date = timezone.now()
                # Auto-set end_date if not set
                if not instance.end_date and instance.cycle_length:
                    frequency_map = {
                        'daily': timezone.timedelta(days=1),
                        'weekly': timezone.timedelta(weeks=1),
                        'biweekly': timezone.timedelta(weeks=2),
                        'monthly': timezone.timedelta(days=30),
                        'quarterly': timezone.timedelta(days=90),
                        'yearly': timezone.timedelta(days=365),
                    }
                    duration = frequency_map.get(instance.frequency, timezone.timedelta(days=30))
                    instance.end_date = instance.start_date + (duration * instance.cycle_length)

            # Log status change
            logger.info(f'Group {instance.id} status changed from {old.status} to {instance.status}')

    else:
        # New group: set default start_date if not provided
        if not instance.start_date:
            instance.start_date = timezone.now()

        # Set status to PENDING if not set
        if not instance.status:
            instance.status = GroupStatus.PENDING


@receiver(post_save, sender=Group)
def group_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for Group model:
    - Update denormalized stats
    - Invalidate cache
    - Trigger auto-activation if pending and members >= 2
    - Send notifications on status changes
    - Log audit event
    """
    # Invalidate cache for this group
    cache.delete(f'group_{instance.id}')
    cache.delete(f'group_detail_{instance.id}')
    cache.delete(f'group_stats_{instance.id}')

    if created:
        logger.info(f'Group {instance.id} created')
        log_audit_event(
            user_id=instance.created_by.id if instance.created_by else None,
            action='group_created',
            resource='group',
            resource_id=instance.id,
            details={'group_name': instance.name}
        )

        # Set initial members count to 1 (creator is automatically added via signal from GroupMember)
        # But we'll let the member signal handle that.

    # Check if group status should be auto-activated (pending -> active) if members >= 2
    if instance.status == GroupStatus.PENDING and instance.members_count >= 2:
        with transaction.atomic():
            instance.status = GroupStatus.ACTIVE
            instance.save(update_fields=['status'])
            logger.info(f'Group {instance.id} auto-activated (members >= 2)')

    # If group becomes active, trigger reminders and winner checks
    if not created:
        try:
            old = Group.objects.get(pk=instance.pk)
            if old.status != instance.status:
                # Status changed
                if instance.status == GroupStatus.ACTIVE:
                    # Schedule reminders
                    send_group_reminders.delay(instance.id)
                    # Check if winner should be selected
                    auto_select_winner.delay(instance.id)
                elif instance.status == GroupStatus.COMPLETED:
                    # Process completion tasks
                    process_group_completion.delay(instance.id)
                elif instance.status == GroupStatus.CANCELLED:
                    # Notify members of cancellation
                    members = instance.get_members()
                    user_ids = list(members.values_list('user_id', flat=True))
                    if user_ids:
                        message = f'Group "{instance.name}" has been cancelled. Please contact support for more information.'
                        send_bulk_notifications.delay(
                            user_ids=user_ids,
                            message=message,
                            notification_type='group_cancelled',
                            group_id=instance.id
                        )
        except Group.DoesNotExist:
            pass

    # Schedule stats update
    update_group_stats.delay(instance.id)


@receiver(pre_delete, sender=Group)
def group_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for Group model:
    - Prevent hard delete if not soft-deleted (enforce soft delete)
    - Log audit event
    """
    if not instance.deleted_at:
        # Enforce soft delete instead of hard delete
        instance.soft_delete(reason='Hard delete attempted, converted to soft delete')
        logger.warning(f'Hard delete attempted on group {instance.id}, converted to soft delete')
        raise Exception('Use soft_delete() instead of delete() for Group model')


@receiver(post_delete, sender=Group)
def group_post_delete_handler(sender, instance, **kwargs):
    """
    Handle post-delete events for Group model:
    - Clean up cache
    - Log audit event
    """
    cache.delete(f'group_{instance.id}')
    cache.delete(f'group_detail_{instance.id}')
    cache.delete(f'group_stats_{instance.id}')
    logger.info(f'Group {instance.id} deleted (permanently)')
    log_audit_event(
        user_id=None,
        action='group_deleted_permanent',
        resource='group',
        resource_id=instance.id,
        details={'group_name': instance.name}
    )


# ============================================================================
# GROUP MEMBER SIGNALS
# ============================================================================

@receiver(pre_save, sender=GroupMember)
def group_member_pre_save_handler(sender, instance, **kwargs):
    """
    Handle pre-save events for GroupMember:
    - Prevent duplicate active memberships
    - Enforce role assignment limits
    - Update user statistics when leaving
    """
    # If instance is being set inactive, we don't need to check duplicates
    if instance.is_active:
        # Check if there is already an active membership for this user and group
        if instance.pk:
            try:
                old = GroupMember.objects.get(pk=instance.pk)
                # If the membership already exists and is active, we allow update
            except GroupMember.DoesNotExist:
                pass
        else:
            # New membership: ensure user is not already active in this group
            if GroupMember.objects.filter(
                group=instance.group,
                user=instance.user,
                is_active=True
            ).exists():
                raise ValueError(f'User {instance.user.id} is already a member of group {instance.group.id}')

    # Ensure only one owner per group
    if instance.role == GroupMemberRole.OWNER and instance.is_active:
        # If this is a new owner or changing role to owner, demote previous owner
        if instance.pk:
            old = GroupMember.objects.get(pk=instance.pk)
            if old.role != GroupMemberRole.OWNER:
                # Demote previous owner(s) to admin
                GroupMember.objects.filter(
                    group=instance.group,
                    role=GroupMemberRole.OWNER,
                    is_active=True
                ).exclude(pk=instance.pk).update(role=GroupMemberRole.ADMIN)
        else:
            # New owner: demote existing owners
            GroupMember.objects.filter(
                group=instance.group,
                role=GroupMemberRole.OWNER,
                is_active=True
            ).update(role=GroupMemberRole.ADMIN)


@receiver(post_save, sender=GroupMember)
def group_member_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for GroupMember:
    - Update group members_count
    - Update user's group statistics (total_groups_joined)
    - Invalidate cache
    - Log activity
    - Auto-activate group if pending and members >= 2
    - Send notifications
    """
    group = instance.group
    user = instance.user

    # Invalidate cache for group and user
    cache.delete(f'group_{group.id}')
    cache.delete(f'group_members_{group.id}')
    cache.delete(f'user_groups_{user.id}')
    cache.delete(f'user_stats_{user.id}')

    # Update group members_count
    count = GroupMember.objects.filter(group=group, is_active=True).count()
    if group.members_count != count:
        group.members_count = count
        group.save(update_fields=['members_count'])

    # Update user's total_groups_joined
    if instance.is_active:
        user.total_groups_joined = GroupMember.objects.filter(
            user=user,
            is_active=True
        ).count()
        user.save(update_fields=['total_groups_joined'])

    if created and instance.is_active:
        # New member added
        logger.info(f'User {user.id} joined group {group.id}')
        log_audit_event(
            user_id=user.id,
            action='group_member_added',
            resource='group_member',
            resource_id=instance.id,
            details={'group_id': group.id, 'role': instance.role}
        )

        # Auto-activate group if pending and members >= 2
        if group.status == GroupStatus.PENDING and group.members_count >= 2:
            with transaction.atomic():
                group.status = GroupStatus.ACTIVE
                group.save(update_fields=['status'])
                logger.info(f'Group {group.id} auto-activated via member addition')

        # Send welcome notification to the user
        from apps.notifications.models import Notification
        Notification.objects.create(
            user=user,
            notification_type='group_joined',
            message=f'You have joined group "{group.name}"',
            group=group,
            is_read=False,
        )
        # Send email notification
        from apps.common.utils import send_email
        send_email(
            to_email=user.email,
            subject=f'Welcome to group "{group.name}"',
            message=f'You have successfully joined the group "{group.name}". Start contributing to build your savings!',
            html_message=None
        )

        # Schedule reminder for new member
        send_group_reminders.delay(group.id)

        # Update group stats
        update_group_stats.delay(group.id)

    elif not created and instance.is_active:
        # Member updated (role change, etc.)
        try:
            old = GroupMember.objects.get(pk=instance.pk)
            if old.role != instance.role:
                logger.info(f'User {user.id} role changed from {old.role} to {instance.role} in group {group.id}')
                log_audit_event(
                    user_id=user.id,
                    action='group_member_role_change',
                    resource='group_member',
                    resource_id=instance.id,
                    details={'old_role': old.role, 'new_role': instance.role}
                )
        except GroupMember.DoesNotExist:
            pass

    elif instance.is_active == False:
        # Member left or was removed
        if instance.left_at is None:
            instance.left_at = timezone.now()
            instance.save(update_fields=['left_at'])

        logger.info(f'User {user.id} left group {group.id}')
        log_audit_event(
            user_id=user.id,
            action='group_member_left',
            resource='group_member',
            resource_id=instance.id,
            details={'group_id': group.id, 'reason': instance.reason}
        )

        # Update user's total_groups_joined
        user.total_groups_joined = GroupMember.objects.filter(
            user=user,
            is_active=True
        ).count()
        user.save(update_fields=['total_groups_joined'])

        # Update group stats
        update_group_stats.delay(group.id)


@receiver(pre_delete, sender=GroupMember)
def group_member_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for GroupMember:
    - Prevent deletion of the only owner
    - Soft-delete instead of hard delete
    """
    if instance.is_active and instance.role == GroupMemberRole.OWNER:
        # Check if this is the only owner
        owners = GroupMember.objects.filter(
            group=instance.group,
            role=GroupMemberRole.OWNER,
            is_active=True
        )
        if owners.count() == 1:
            raise ValueError('Cannot delete the only owner of the group. Transfer ownership first.')

    # Soft-delete instead of hard delete
    if instance.is_active:
        instance.is_active = False
        instance.left_at = timezone.now()
        instance.reason = 'Deleted via admin'
        instance.save(update_fields=['is_active', 'left_at', 'reason'])
        logger.info(f'GroupMember {instance.id} soft-deleted')
        raise Exception('Use soft-delete by setting is_active=False instead of delete()')


@receiver(post_delete, sender=GroupMember)
def group_member_post_delete_handler(sender, instance, **kwargs):
    """
    Handle post-delete events for GroupMember (should be rare, as we enforce soft-delete):
    - Clean up cache
    - Log audit event
    """
    cache.delete(f'group_{instance.group.id}')
    cache.delete(f'group_members_{instance.group.id}')
    cache.delete(f'user_groups_{instance.user.id}')
    cache.delete(f'user_stats_{instance.user.id}')
    logger.info(f'GroupMember {instance.id} permanently deleted')


# ============================================================================
# GROUP INVITATION SIGNALS
# ============================================================================

@receiver(post_save, sender=GroupInvitation)
def group_invitation_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for GroupInvitation:
    - Send email notification on creation
    - Handle status changes (accepted, rejected, expired, cancelled)
    - Invalidate cache
    - Log audit event
    """
    cache.delete(f'group_invitations_{instance.group.id}')
    cache.delete(f'user_invitations_{instance.invitee_email}')

    if created:
        # Send invitation email
        try:
            inviter_name = instance.inviter.full_name if instance.inviter else 'Someone'
            group_name = instance.group.name
            token = instance.token
            # Build accept link
            accept_link = f"{settings.FRONTEND_URL}/groups/invite/accept?token={token}"
            subject = f'Invitation to join group "{group_name}"'
            message = f"""
            Dear potential member,

            {inviter_name} has invited you to join the group "{group_name}" on the Ekub Platform.

            To accept this invitation, please click the link below:
            {accept_link}

            This invitation will expire on {instance.expires_at.strftime('%Y-%m-%d %H:%M')}.

            If you have any questions, please contact support.

            Best regards,
            Ekub Platform Team
            """
            send_email(
                to_email=instance.invitee_email,
                subject=subject,
                message=message,
                html_message=None
            )
            logger.info(f'Invitation email sent to {instance.invitee_email}')
        except Exception as e:
            logger.error(f'Error sending invitation email: {str(e)}')

        log_audit_event(
            user_id=instance.inviter.id,
            action='group_invitation_sent',
            resource='group_invitation',
            resource_id=instance.id,
            details={'group_id': instance.group.id, 'invitee_email': instance.invitee_email}
        )

    else:
        # Status changed
        try:
            old = GroupInvitation.objects.get(pk=instance.pk)
            if old.status != instance.status:
                if instance.status == GroupInvitationStatus.ACCEPTED:
                    logger.info(f'Invitation {instance.id} accepted')
                    # The accept logic is handled in the view, but we can log here
                elif instance.status == GroupInvitationStatus.REJECTED:
                    logger.info(f'Invitation {instance.id} rejected by {instance.invitee_email}')
                elif instance.status == GroupInvitationStatus.EXPIRED:
                    logger.info(f'Invitation {instance.id} expired')
                elif instance.status == GroupInvitationStatus.CANCELLED:
                    logger.info(f'Invitation {instance.id} cancelled by {instance.inviter.id}')
        except GroupInvitation.DoesNotExist:
            pass


@receiver(pre_delete, sender=GroupInvitation)
def group_invitation_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for GroupInvitation:
    - Prevent deletion of accepted invitations
    - Log audit event
    """
    if instance.status == GroupInvitationStatus.ACCEPTED:
        raise ValueError('Cannot delete an accepted invitation.')
    logger.info(f'Invitation {instance.id} deleted (status: {instance.status})')


# ============================================================================
# GROUP SETTING SIGNALS
# ============================================================================

@receiver(post_save, sender=GroupSetting)
def group_setting_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for GroupSetting:
    - Invalidate cache for the specific setting and group
    - Log audit event
    """
    cache.delete(f'group_setting_{instance.group.id}_{instance.key}')
    cache.delete(f'group_settings_{instance.group.id}')
    if created:
        logger.info(f'Setting {instance.key} created for group {instance.group.id}')
    else:
        logger.info(f'Setting {instance.key} updated for group {instance.group.id}')


@receiver(pre_delete, sender=GroupSetting)
def group_setting_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for GroupSetting:
    - Log audit event
    - Invalidate cache
    """
    cache.delete(f'group_setting_{instance.group.id}_{instance.key}')
    cache.delete(f'group_settings_{instance.group.id}')
    logger.info(f'Setting {instance.key} deleted from group {instance.group.id}')


# ============================================================================
# GROUP ACTIVITY SIGNALS
# ============================================================================

@receiver(post_save, sender=GroupActivity)
def group_activity_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for GroupActivity:
    - Update group's last activity timestamp (via cache)
    - Invalidate cache
    """
    if created:
        # Update last activity on group's cache
        cache.set(f'group_last_activity_{instance.group.id}', instance.timestamp, timeout=3600)
        # Invalidate group cache
        cache.delete(f'group_{instance.group.id}')
        cache.delete(f'group_activities_{instance.group.id}')


# ============================================================================
# GROUP WINNER HISTORY SIGNALS
# ============================================================================

@receiver(post_save, sender=GroupWinnerHistory)
def group_winner_history_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for GroupWinnerHistory:
    - Update group statistics
    - Invalidate cache
    - Log audit event
    - Send notification to winner
    """
    if created:
        # Invalidate cache
        cache.delete(f'group_winners_{instance.group.id}')
        cache.delete(f'group_{instance.group.id}')
        cache.delete(f'group_stats_{instance.group.id}')

        # Log audit event
        log_audit_event(
            user_id=instance.user.id,
            action='winner_selected',
            resource='group_winner_history',
            resource_id=instance.id,
            details={
                'group_id': instance.group.id,
                'round': instance.round,
                'amount': float(instance.amount)
            }
        )

        # Send notification to the winner
        from apps.notifications.models import Notification
        Notification.objects.create(
            user=instance.user,
            notification_type='winner',
            message=f'Congratulations! You have won round {instance.round + 1} of group "{instance.group.name}" with amount {instance.amount:.2f} ETB.',
            group=instance.group,
            is_read=False,
        )

        # Send email to winner
        from apps.common.utils import send_email
        send_email(
            to_email=instance.user.email,
            subject=f'You won the round! - {instance.group.name}',
            message=f'Congratulations! You have been selected as the winner for round {instance.round + 1} of group "{instance.group.name}".\n\nAmount: {instance.amount:.2f} ETB\n\nPlease check your account for the payout.\n\nEkub Platform Team',
            html_message=None
        )

        # Update group stats
        update_group_stats.delay(instance.group.id)

        # If this is the last round, trigger group completion check
        if instance.round >= instance.group.cycle_length - 1:
            process_group_completion.delay(instance.group.id)

        logger.info(f'Winner {instance.user.id} recorded for group {instance.group.id}, round {instance.round}')


@receiver(pre_delete, sender=GroupWinnerHistory)
def group_winner_history_pre_delete_handler(sender, instance, **kwargs):
    """
    Handle pre-delete events for GroupWinnerHistory:
    - Prevent deletion of paid-out winners
    - Log audit event
    """
    if instance.paid_out:
        raise ValueError('Cannot delete a winner history that has been paid out.')


# ============================================================================
# SIGNAL DISPATCHER (for manual triggering)
# ============================================================================

def dispatch_group_signals(group_id, signal_name, *args, **kwargs):
    """
    Manually dispatch group signals for testing or admin actions.
    """
    try:
        group = Group.objects.get(id=group_id)
    except Group.DoesNotExist:
        return None

    if signal_name == 'post_save':
        group_post_save_handler(Group, group, created=False, **kwargs)
    elif signal_name == 'pre_save':
        group_pre_save_handler(Group, group, **kwargs)
    elif signal_name == 'pre_delete':
        group_pre_delete_handler(Group, group, **kwargs)
    elif signal_name == 'post_delete':
        group_post_delete_handler(Group, group, **kwargs)
    return True


def dispatch_group_member_signals(member_id, signal_name, *args, **kwargs):
    """
    Manually dispatch group member signals.
    """
    try:
        member = GroupMember.objects.get(id=member_id)
    except GroupMember.DoesNotExist:
        return None

    if signal_name == 'post_save':
        group_member_post_save_handler(GroupMember, member, created=False, **kwargs)
    elif signal_name == 'pre_save':
        group_member_pre_save_handler(GroupMember, member, **kwargs)
    elif signal_name == 'pre_delete':
        group_member_pre_delete_handler(GroupMember, member, **kwargs)
    return True


# ============================================================================
# CACHE INVALIDATION UTILITY
# ============================================================================

def invalidate_group_cache(group_id):
    """
    Utility to invalidate all cache keys related to a group.
    """
    keys = [
        f'group_{group_id}',
        f'group_detail_{group_id}',
        f'group_stats_{group_id}',
        f'group_members_{group_id}',
        f'group_invitations_{group_id}',
        f'group_settings_{group_id}',
        f'group_activities_{group_id}',
        f'group_winners_{group_id}',
        f'group_last_activity_{group_id}',
    ]
    for key in keys:
        cache.delete(key)
    logger.debug(f'Cache invalidated for group {group_id}')


# ============================================================================
# LOGGING UTILITY
# ============================================================================

def log_group_action(group, action, user=None, details=None):
    """
    Utility to log a group action with consistent format.
    """
    log_data = {
        'group_id': group.id,
        'group_name': group.name,
        'action': action,
        'user_id': user.id if user else None,
        'timestamp': timezone.now().isoformat(),
        'details': details or {}
    }
    logger.info(f'GROUP_ACTION: {log_data}')


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
            # Re-raise to prevent silent failures, but we can log and continue
            raise
    return wrapper