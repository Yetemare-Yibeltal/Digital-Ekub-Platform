"""
Groups app for the Digital Ekub Platform.

This app handles group management including:
- Creating and managing savings groups
- Group membership and roles (owner, admin, member)
- Group invitations and join requests
- Group settings (contribution amount, frequency, cycle length)
- Winner selection (fixed rotation, random, auction)
- Group status management (active, completed, cancelled, paused)

All group-related operations are centralized in this app.
"""

__version__ = '1.0.0'
__app_name__ = 'groups'
__author__ = 'Digital Ekub Team'
__description__ = 'Group management for the Digital Ekub Platform'

# Set default app configuration for Django
default_app_config = 'apps.groups.apps.GroupsConfig'

# ============================================================================
# IMPORT ALL PUBLIC COMPONENTS
# ============================================================================

# Models
from .models import (
    Group,
    GroupMember,
    GroupInvitation,
    GroupSetting,
    GroupActivity,
    GroupWinnerHistory,
)

# Serializers
from .serializers import (
    GroupSerializer,
    GroupDetailSerializer,
    GroupCreateSerializer,
    GroupUpdateSerializer,
    GroupListSerializer,
    GroupMemberSerializer,
    GroupMemberCreateSerializer,
    GroupMemberUpdateSerializer,
    GroupInvitationSerializer,
    GroupInvitationCreateSerializer,
    GroupSettingSerializer,
    GroupActivitySerializer,
    GroupWinnerHistorySerializer,
    GroupStatsSerializer,
)

# Views
from .views import (
    GroupViewSet,
    GroupMemberViewSet,
    GroupInvitationViewSet,
    GroupSettingViewSet,
    GroupActivityViewSet,
    GroupWinnerHistoryViewSet,
    GroupStatsView,
    GroupJoinView,
    GroupLeaveView,
    GroupSelectWinnerView,
    GroupCompleteView,
)

# Permissions
from .permissions import (
    IsGroupMember,
    IsGroupAdmin,
    IsGroupOwner,
    IsGroupActive,
    IsGroupNotFull,
    IsGroupNotCompleted,
    CanJoinGroup,
    CanLeaveGroup,
    CanManageGroup,
    CanViewGroup,
    CanCreateContribution,
    CanProcessContribution,
)

# Tasks
from .tasks import (
    process_expired_groups,
    auto_select_winner,
    send_group_reminders,
    process_group_completion,
    cleanup_inactive_groups,
    update_group_stats,
)

# Signals
from .signals import (
    group_post_save_handler,
    group_pre_delete_handler,
    group_member_post_save_handler,
    group_member_pre_delete_handler,
)

# ============================================================================
# GROUP CONSTANTS (RE-EXPORT)
# ============================================================================

from apps.common.constants import (
    GroupStatus,
    GroupMemberRole,
    GroupType,
    GroupFrequency,
    GroupWinnerSelection,
    GroupInvitationStatus,
)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_group_stats(group_id: int) -> dict:
    """
    Get statistics for a group including member count, total contributions,
    total paid, pending, overdue, and payout details.

    Args:
        group_id: ID of the group

    Returns:
        dict: Group statistics
    """
    from django.db.models import Sum, Count, Q
    from .models import Group, GroupMember, Contribution

    try:
        group = Group.objects.get(id=group_id)
    except Group.DoesNotExist:
        return {}

    members_count = GroupMember.objects.filter(group=group, is_active=True).count()

    contributions = Contribution.objects.filter(group=group)
    total_contributions = contributions.count()
    paid_contributions = contributions.filter(status='paid').count()
    pending_contributions = contributions.filter(status='pending').count()
    overdue_contributions = contributions.filter(status='overdue').count()
    total_amount = contributions.filter(status='paid').aggregate(total=Sum('amount'))['total'] or 0
    total_paid_amount = contributions.filter(status='paid').aggregate(total=Sum('amount'))['total'] or 0
    pending_amount = contributions.filter(status='pending').aggregate(total=Sum('amount'))['total'] or 0
    overdue_amount = contributions.filter(status='overdue').aggregate(total=Sum('amount'))['total'] or 0

    # Payouts
    from apps.payments.models import Payout
    payouts = Payout.objects.filter(group=group)
    total_payouts = payouts.count()
    completed_payouts = payouts.filter(status='completed').count()
    pending_payouts = payouts.filter(status='pending').count()
    total_payout_amount = payouts.filter(status='completed').aggregate(total=Sum('amount'))['total'] or 0

    return {
        'group_id': group.id,
        'group_name': group.name,
        'status': group.status,
        'members_count': members_count,
        'total_contributions': total_contributions,
        'paid_contributions': paid_contributions,
        'pending_contributions': pending_contributions,
        'overdue_contributions': overdue_contributions,
        'total_amount': float(total_amount),
        'total_paid_amount': float(total_paid_amount),
        'pending_amount': float(pending_amount),
        'overdue_amount': float(overdue_amount),
        'total_payouts': total_payouts,
        'completed_payouts': completed_payouts,
        'pending_payouts': pending_payouts,
        'total_payout_amount': float(total_payout_amount),
        'completion_percentage': (paid_contributions / total_contributions * 100) if total_contributions > 0 else 0,
    }


def get_member_stats(user_id: int, group_id: int) -> dict:
    """
    Get statistics for a specific member within a group.

    Args:
        user_id: ID of the user
        group_id: ID of the group

    Returns:
        dict: Member statistics
    """
    from .models import GroupMember, Contribution

    try:
        member = GroupMember.objects.get(user_id=user_id, group_id=group_id, is_active=True)
    except GroupMember.DoesNotExist:
        return {}

    contributions = Contribution.objects.filter(user_id=user_id, group_id=group_id)
    total = contributions.count()
    paid = contributions.filter(status='paid').count()
    pending = contributions.filter(status='pending').count()
    overdue = contributions.filter(status='overdue').count()
    total_amount = contributions.filter(status='paid').aggregate(total=Sum('amount'))['total'] or 0

    return {
        'user_id': user_id,
        'group_id': group_id,
        'role': member.role,
        'joined_at': member.joined_at,
        'total_contributions': total,
        'paid_contributions': paid,
        'pending_contributions': pending,
        'overdue_contributions': overdue,
        'total_amount_paid': float(total_amount),
        'contribution_status': 'good' if pending == 0 and overdue == 0 else 'has_pending' if pending > 0 else 'overdue',
    }


def is_group_owner(user_id: int, group_id: int) -> bool:
    """
    Check if a user is the owner of a group.

    Args:
        user_id: ID of the user
        group_id: ID of the group

    Returns:
        bool: True if user is owner
    """
    from .models import GroupMember
    return GroupMember.objects.filter(
        user_id=user_id,
        group_id=group_id,
        role='owner',
        is_active=True
    ).exists()


def is_group_admin(user_id: int, group_id: int) -> bool:
    """
    Check if a user is an admin or owner of a group.

    Args:
        user_id: ID of the user
        group_id: ID of the group

    Returns:
        bool: True if user is admin or owner
    """
    from .models import GroupMember
    return GroupMember.objects.filter(
        user_id=user_id,
        group_id=group_id,
        role__in=['admin', 'owner'],
        is_active=True
    ).exists()


def is_group_member(user_id: int, group_id: int) -> bool:
    """
    Check if a user is a member of a group.

    Args:
        user_id: ID of the user
        group_id: ID of the group

    Returns:
        bool: True if user is a member
    """
    from .models import GroupMember
    return GroupMember.objects.filter(
        user_id=user_id,
        group_id=group_id,
        is_active=True
    ).exists()


def can_user_join_group(user_id: int, group_id: int) -> bool:
    """
    Check if a user can join a group.

    Args:
        user_id: ID of the user
        group_id: ID of the group

    Returns:
        bool: True if user can join
    """
    from .models import Group, GroupMember
    from apps.users.models import User

    try:
        user = User.objects.get(id=user_id)
        group = Group.objects.get(id=group_id)
    except (User.DoesNotExist, Group.DoesNotExist):
        return False

    if not user.is_active or user.is_suspended or user.is_locked or user.is_deleted():
        return False
    if not user.is_phone_verified:
        return False
    if group.status != 'active':
        return False
    if group.members.count() >= group.max_members:
        return False
    if GroupMember.objects.filter(user=user, group=group, is_active=True).exists():
        return False
    return True


def can_user_leave_group(user_id: int, group_id: int) -> bool:
    """
    Check if a user can leave a group.

    Args:
        user_id: ID of the user
        group_id: ID of the group

    Returns:
        bool: True if user can leave
    """
    from .models import GroupMember

    if not is_group_member(user_id, group_id):
        return False

    # Check if user is the only owner
    if is_group_owner(user_id, group_id):
        owners = GroupMember.objects.filter(group_id=group_id, role='owner', is_active=True)
        if owners.count() == 1:
            return False
    return True


# ============================================================================
# GROUP ACTIVITY LOGGING
# ============================================================================

def log_group_activity(group_id: int, action: str, user_id: Optional[int] = None, details: Optional[dict] = None):
    """
    Log an activity for a group.

    Args:
        group_id: ID of the group
        action: Action performed (e.g., 'member_joined', 'member_left', 'contribution_paid')
        user_id: ID of the user who performed the action
        details: Additional details
    """
    from .models import GroupActivity
    GroupActivity.objects.create(
        group_id=group_id,
        user_id=user_id,
        action=action,
        details=details or {},
        timestamp=timezone.now()
    )


# ============================================================================
# WINNER SELECTION HELPERS
# ============================================================================

def select_winner_fixed_rotation(group_id: int) -> Optional[int]:
    """
    Select winner using fixed rotation based on join order.

    Args:
        group_id: ID of the group

    Returns:
        Optional[int]: User ID of the winner, or None if no eligible
    """
    from .models import Group, GroupMember
    from django.db.models import Count, Q

    try:
        group = Group.objects.get(id=group_id)
    except Group.DoesNotExist:
        return None

    # Get members ordered by join date
    members = GroupMember.objects.filter(
        group=group,
        is_active=True,
        user__is_active=True,
        user__is_suspended=False
    ).order_by('joined_at')

    if not members:
        return None

    # Find the next winner based on current cycle
    current_round = group.current_round or 0
    cycle_length = group.cycle_length

    # Skip members who have already won or are not eligible
    eligible_members = []
    for member in members:
        # Check if member has already won in this cycle
        from .models import GroupWinnerHistory
        already_won = GroupWinnerHistory.objects.filter(
            group=group,
            user=member.user,
            round=current_round
        ).exists()
        if not already_won:
            eligible_members.append(member)

    if not eligible_members:
        # All members have won, reset cycle
        eligible_members = list(members)

    # Select by round index
    round_index = current_round % len(eligible_members)
    return eligible_members[round_index].user.id


def select_winner_random(group_id: int) -> Optional[int]:
    """
    Select winner randomly from eligible members.

    Args:
        group_id: ID of the group

    Returns:
        Optional[int]: User ID of the winner, or None if no eligible
    """
    from .models import Group, GroupMember
    import random

    try:
        group = Group.objects.get(id=group_id)
    except Group.DoesNotExist:
        return None

    members = GroupMember.objects.filter(
        group=group,
        is_active=True,
        user__is_active=True,
        user__is_suspended=False
    )

    if not members:
        return None

    # Exclude members who have already won this round
    from .models import GroupWinnerHistory
    current_round = group.current_round or 0
    eligible = []
    for member in members:
        already_won = GroupWinnerHistory.objects.filter(
            group=group,
            user=member.user,
            round=current_round
        ).exists()
        if not already_won:
            eligible.append(member)

    if not eligible:
        eligible = list(members)

    winner = random.choice(eligible)
    return winner.user.id


def select_winner(group_id: int) -> Optional[int]:
    """
    Select winner based on group's winner selection method.

    Args:
        group_id: ID of the group

    Returns:
        Optional[int]: User ID of the winner, or None if no eligible
    """
    from .models import Group
    try:
        group = Group.objects.get(id=group_id)
    except Group.DoesNotExist:
        return None

    if group.winner_selection == 'fixed':
        return select_winner_fixed_rotation(group_id)
    elif group.winner_selection == 'random':
        return select_winner_random(group_id)
    else:
        # Default to random if method is unknown
        return select_winner_random(group_id)


# ============================================================================
# NOTIFICATION HELPERS
# ============================================================================

def notify_group_members(group_id: int, message: str, notification_type: str = 'group'):
    """
    Send a notification to all members of a group.

    Args:
        group_id: ID of the group
        message: Message to send
        notification_type: Type of notification
    """
    from .models import GroupMember
    from apps.notifications.tasks import send_bulk_notifications

    members = GroupMember.objects.filter(
        group_id=group_id,
        is_active=True,
        user__is_active=True,
        user__notification_preferences__get=notification_type
    )

    user_ids = members.values_list('user_id', flat=True)
    if user_ids:
        send_bulk_notifications.delay(
            user_ids=list(user_ids),
            message=message,
            notification_type=notification_type,
            group_id=group_id
        )


def notify_group_admin(group_id: int, message: str, notification_type: str = 'group'):
    """
    Send a notification to all admins and owners of a group.

    Args:
        group_id: ID of the group
        message: Message to send
        notification_type: Type of notification
    """
    from .models import GroupMember
    from apps.notifications.tasks import send_bulk_notifications

    admins = GroupMember.objects.filter(
        group_id=group_id,
        role__in=['admin', 'owner'],
        is_active=True,
        user__is_active=True
    )

    user_ids = admins.values_list('user_id', flat=True)
    if user_ids:
        send_bulk_notifications.delay(
            user_ids=list(user_ids),
            message=message,
            notification_type=notification_type,
            group_id=group_id
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Package metadata
    '__version__',
    '__app_name__',
    '__author__',
    '__description__',

    # Models
    'Group',
    'GroupMember',
    'GroupInvitation',
    'GroupSetting',
    'GroupActivity',
    'GroupWinnerHistory',

    # Serializers
    'GroupSerializer',
    'GroupDetailSerializer',
    'GroupCreateSerializer',
    'GroupUpdateSerializer',
    'GroupListSerializer',
    'GroupMemberSerializer',
    'GroupMemberCreateSerializer',
    'GroupMemberUpdateSerializer',
    'GroupInvitationSerializer',
    'GroupInvitationCreateSerializer',
    'GroupSettingSerializer',
    'GroupActivitySerializer',
    'GroupWinnerHistorySerializer',
    'GroupStatsSerializer',

    # Views
    'GroupViewSet',
    'GroupMemberViewSet',
    'GroupInvitationViewSet',
    'GroupSettingViewSet',
    'GroupActivityViewSet',
    'GroupWinnerHistoryViewSet',
    'GroupStatsView',
    'GroupJoinView',
    'GroupLeaveView',
    'GroupSelectWinnerView',
    'GroupCompleteView',

    # Permissions
    'IsGroupMember',
    'IsGroupAdmin',
    'IsGroupOwner',
    'IsGroupActive',
    'IsGroupNotFull',
    'IsGroupNotCompleted',
    'CanJoinGroup',
    'CanLeaveGroup',
    'CanManageGroup',
    'CanViewGroup',
    'CanCreateContribution',
    'CanProcessContribution',

    # Tasks
    'process_expired_groups',
    'auto_select_winner',
    'send_group_reminders',
    'process_group_completion',
    'cleanup_inactive_groups',
    'update_group_stats',

    # Signals
    'group_post_save_handler',
    'group_pre_delete_handler',
    'group_member_post_save_handler',
    'group_member_pre_delete_handler',

    # Constants
    'GroupStatus',
    'GroupMemberRole',
    'GroupType',
    'GroupFrequency',
    'GroupWinnerSelection',
    'GroupInvitationStatus',

    # Helpers
    'get_group_stats',
    'get_member_stats',
    'is_group_owner',
    'is_group_admin',
    'is_group_member',
    'can_user_join_group',
    'can_user_leave_group',
    'select_winner_fixed_rotation',
    'select_winner_random',
    'select_winner',
    'log_group_activity',
    'notify_group_members',
    'notify_group_admin',
]

# ============================================================================
# LOGGING
# ============================================================================

import logging
logger = logging.getLogger(__name__)
logger.info(f'Groups app v{__version__} initialized')