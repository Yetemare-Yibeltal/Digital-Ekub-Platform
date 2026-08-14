"""
Permission classes for the groups app.

This module provides comprehensive permission classes for group operations:
- Membership checks (IsGroupMember, IsGroupAdmin, IsGroupOwner)
- Object-level permissions for group resources
- Action-specific permissions (join, leave, select winner, etc.)
- Combined permissions for complex scenarios
- Helper functions for permission checks
- Permission mixins for viewsets

All permission classes implement both has_permission and has_object_permission
where appropriate for fine-grained access control.
"""

from rest_framework import permissions
from rest_framework.permissions import BasePermission, SAFE_METHODS
from django.shortcuts import get_object_or_404
from django.core.exceptions import PermissionDenied
from typing import Optional, Type, List, Union

from apps.users.models import User
from apps.users.permissions import IsActive, IsVerified, IsNotSuspended, IsNotLocked, IsNotDeleted
from apps.common.constants import GroupStatus, GroupMemberRole

from .models import Group, GroupMember


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_group_member(user: User, group: Group) -> bool:
    """
    Check if a user is an active member of a group.

    Args:
        user: User to check
        group: Group to check

    Returns:
        bool: True if user is an active member
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    return GroupMember.objects.filter(
        group=group,
        user=user,
        is_active=True
    ).exists()


def is_group_admin(user: User, group: Group) -> bool:
    """
    Check if a user is an admin or owner of a group.

    Args:
        user: User to check
        group: Group to check

    Returns:
        bool: True if user is an admin or owner
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    return GroupMember.objects.filter(
        group=group,
        user=user,
        role__in=['admin', 'owner'],
        is_active=True
    ).exists()


def is_group_owner(user: User, group: Group) -> bool:
    """
    Check if a user is the owner of a group.

    Args:
        user: User to check
        group: Group to check

    Returns:
        bool: True if user is the owner
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    return GroupMember.objects.filter(
        group=group,
        user=user,
        role='owner',
        is_active=True
    ).exists()


def get_group_from_view(view) -> Optional[Group]:
    """
    Extract group from view kwargs.

    Args:
        view: DRF view instance

    Returns:
        Group instance or None
    """
    group_id = view.kwargs.get('group_id') or view.kwargs.get('pk')
    if not group_id:
        # Try to get from request data
        if hasattr(view, 'request') and hasattr(view.request, 'data'):
            group_id = view.request.data.get('group_id') or view.request.data.get('group')
        if not group_id:
            return None
    try:
        return Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        return None


def get_group_from_object(obj) -> Optional[Group]:
    """
    Extract group from an object.

    Args:
        obj: Object to extract group from

    Returns:
        Group instance or None
    """
    if hasattr(obj, 'group'):
        return obj.group
    if hasattr(obj, 'group_id'):
        try:
            return Group.objects.get(id=obj.group_id, deleted_at__isnull=True)
        except Group.DoesNotExist:
            return None
    return None


# ============================================================================
# BASE GROUP PERMISSIONS
# ============================================================================

class IsGroupMember(BasePermission):
    """
    Allows access only to members of the group.
    """
    message = _('You must be a member of this group to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_view(view)
        if not group:
            # If no group found, allow if user is superuser
            return request.user.is_superuser

        return is_group_member(request.user, group)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_object(obj)
        if not group:
            return False

        return is_group_member(request.user, group)


class IsGroupAdmin(BasePermission):
    """
    Allows access only to admins and owners of the group.
    """
    message = _('You must be an admin of this group to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_view(view)
        if not group:
            return False

        return is_group_admin(request.user, group)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_object(obj)
        if not group:
            return False

        return is_group_admin(request.user, group)


class IsGroupOwner(BasePermission):
    """
    Allows access only to the owner of the group.
    """
    message = _('You must be the owner of this group to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_view(view)
        if not group:
            return False

        return is_group_owner(request.user, group)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_object(obj)
        if not group:
            return False

        return is_group_owner(request.user, group)


# ============================================================================
# GROUP STATUS PERMISSIONS
# ============================================================================

class IsGroupActive(BasePermission):
    """
    Allows access only to active groups.
    """
    message = _('Group is not active.')

    def has_permission(self, request, view):
        group = get_group_from_view(view)
        if not group:
            return True
        return group.is_active

    def has_object_permission(self, request, view, obj):
        group = get_group_from_object(obj)
        if not group:
            return True
        return group.is_active


class IsGroupNotFull(BasePermission):
    """
    Allows access only if group is not full.
    """
    message = _('Group is full.')

    def has_permission(self, request, view):
        group = get_group_from_view(view)
        if not group:
            return True
        return not group.is_full

    def has_object_permission(self, request, view, obj):
        group = get_group_from_object(obj)
        if not group:
            return True
        return not group.is_full


class IsGroupNotCompleted(BasePermission):
    """
    Allows access only if group is not completed.
    """
    message = _('Group is already completed.')

    def has_permission(self, request, view):
        group = get_group_from_view(view)
        if not group:
            return True
        return not group.is_completed

    def has_object_permission(self, request, view, obj):
        group = get_group_from_object(obj)
        if not group:
            return True
        return not group.is_completed


class IsGroupNotCancelled(BasePermission):
    """
    Allows access only if group is not cancelled.
    """
    message = _('Group is cancelled.')

    def has_permission(self, request, view):
        group = get_group_from_view(view)
        if not group:
            return True
        return not group.is_cancelled

    def has_object_permission(self, request, view, obj):
        group = get_group_from_object(obj)
        if not group:
            return True
        return not group.is_cancelled


# ============================================================================
# ACTION-SPECIFIC PERMISSIONS
# ============================================================================

class CanJoinGroup(BasePermission):
    """
    Allows access only if user can join the group.
    Checks: user is active, verified, phone verified, group is active, not full,
    not completed, not cancelled, user not already a member.
    """
    message = _('You cannot join this group.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        if request.user.is_suspended or request.user.is_locked:
            return False
        if not request.user.is_active:
            return False
        if not request.user.is_phone_verified:
            return False

        group = get_group_from_view(view)
        if not group:
            return False

        if not group.is_active:
            return False
        if group.is_full:
            return False
        if group.is_completed:
            return False
        if group.is_cancelled:
            return False
        if is_group_member(request.user, group):
            return False

        return True


class CanLeaveGroup(BasePermission):
    """
    Allows access only if user can leave the group.
    Checks: user is a member, user is not the only owner.
    """
    message = _('You cannot leave this group.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_view(view)
        if not group:
            return False

        if not is_group_member(request.user, group):
            return False

        # Check if user is the only owner
        if is_group_owner(request.user, group):
            owners = GroupMember.objects.filter(
                group=group,
                role='owner',
                is_active=True
            )
            if owners.count() == 1:
                return False

        return True


class CanSelectWinner(BasePermission):
    """
    Allows access only if user can select a winner.
    Checks: user is admin/owner, group is active, not completed,
    has at least 2 members.
    """
    message = _('You cannot select a winner for this group.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_view(view)
        if not group:
            return False

        # Must be admin
        if not is_group_admin(request.user, group):
            return False

        # Check group status
        if not group.is_active:
            return False
        if group.is_completed:
            return False
        if group.members_count < 2:
            return False

        return True


class CanManageGroup(BasePermission):
    """
    Allows access only if user can manage the group.
    Checks: user is admin/owner, group is not completed/cancelled/deleted.
    """
    message = _('You cannot manage this group.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_view(view)
        if not group:
            return False

        if not is_group_admin(request.user, group):
            return False

        if group.is_deleted:
            return False
        if group.is_completed:
            return False
        if group.is_cancelled:
            return False

        return True


class CanManageMembers(BasePermission):
    """
    Allows access only if user can manage members.
    Checks: user is admin/owner, group is active.
    """
    message = _('You cannot manage members of this group.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_view(view)
        if not group:
            return False

        if not is_group_admin(request.user, group):
            return False

        if not group.is_active:
            return False

        return True


class CanTransferOwnership(BasePermission):
    """
    Allows access only if user can transfer ownership.
    Checks: user is the owner, target user is a member.
    """
    message = _('You cannot transfer ownership.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_view(view)
        if not group:
            return False

        if not is_group_owner(request.user, group):
            return False

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        # obj is GroupMember
        if hasattr(obj, 'group') and hasattr(obj, 'user'):
            group = obj.group
            target_user = obj.user
            if not is_group_owner(request.user, group):
                return False
            if target_user == request.user:
                return False
            if not is_group_member(target_user, group):
                return False
            return True

        return False


# ============================================================================
# CONTRIBUTION PERMISSIONS
# ============================================================================

class CanCreateContribution(BasePermission):
    """
    Allows access only if user can create a contribution.
    Checks: user is member, group is active, not completed.
    """
    message = _('You cannot create a contribution for this group.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        if not request.user.is_active:
            return False

        group = get_group_from_view(view)
        if not group:
            return False

        if not is_group_member(request.user, group):
            return False
        if not group.is_active:
            return False
        if group.is_completed:
            return False
        if group.is_cancelled:
            return False

        return True


class CanViewContribution(BasePermission):
    """
    Allows access only if user can view contributions.
    Checks: user is member or admin/superuser.
    """
    message = _('You cannot view contributions for this group.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_view(view)
        if not group:
            return True

        return is_group_member(request.user, group)


class CanProcessContribution(BasePermission):
    """
    Allows access only if user can process contributions.
    Checks: user is admin/owner, group is active.
    """
    message = _('You cannot process contributions for this group.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_view(view)
        if not group:
            return False

        if not is_group_admin(request.user, group):
            return False
        if not group.is_active:
            return False

        return True


# ============================================================================
# INVITATION PERMISSIONS
# ============================================================================

class CanSendInvitation(BasePermission):
    """
    Allows access only if user can send invitations.
    Checks: user is member, group is active, not full.
    """
    message = _('You cannot send invitations for this group.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        group = get_group_from_view(view)
        if not group:
            return False

        # Must be a member to send invitations
        if not is_group_member(request.user, group):
            return False

        if not group.is_active:
            return False
        if group.is_full:
            return False

        return True


class CanAcceptInvitation(BasePermission):
    """
    Allows access only if user can accept an invitation.
    Checks: invitation is pending, not expired, user matches invitee_email.
    """
    message = _('You cannot accept this invitation.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False

        invitation_id = view.kwargs.get('id')
        if not invitation_id:
            return False

        from .models import GroupInvitation
        try:
            invitation = GroupInvitation.objects.get(id=invitation_id)
        except GroupInvitation.DoesNotExist:
            return False

        if invitation.status != 'pending':
            return False
        if invitation.is_expired:
            return False
        if invitation.invitee_email != request.user.email and not request.user.is_superuser:
            return False

        return True


# ============================================================================
# NESTED RESOURCE PERMISSIONS
# ============================================================================

class IsGroupMemberOfResource(BasePermission):
    """
    Allows access only if user is a member of the group that owns the resource.
    """
    message = _('You must be a member of the group to access this resource.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        # Try to get group from view
        group = get_group_from_view(view)
        if group:
            return is_group_member(request.user, group)

        # If no group in view, allow if authenticated
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        group = get_group_from_object(obj)
        if not group:
            return True

        return is_group_member(request.user, group)


class IsGroupAdminOfResource(BasePermission):
    """
    Allows access only if user is an admin of the group that owns the resource.
    """
    message = _('You must be an admin of the group to access this resource.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        group = get_group_from_view(view)
        if not group:
            return False

        return is_group_admin(request.user, group)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        group = get_group_from_object(obj)
        if not group:
            return False

        return is_group_admin(request.user, group)


# ============================================================================
# COMBINED PERMISSIONS
# ============================================================================

class OrGroupPermission(BasePermission):
    """
    Combined permission that allows if ANY of the given permissions allow.
    """
    def __init__(self, *perms: Type[BasePermission]):
        self.perms = perms

    def has_permission(self, request, view):
        return any(perm().has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        return any(perm().has_object_permission(request, view, obj) for perm in self.perms)


class AndGroupPermission(BasePermission):
    """
    Combined permission that allows if ALL of the given permissions allow.
    """
    def __init__(self, *perms: Type[BasePermission]):
        self.perms = perms

    def has_permission(self, request, view):
        return all(perm().has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        return all(perm().has_object_permission(request, view, obj) for perm in self.perms)


# ============================================================================
# PRE-DEFINED COMBINED PERMISSIONS
# ============================================================================

# Member with active status
IsActiveGroupMember = AndGroupPermission(IsActive, IsNotSuspended, IsNotLocked, IsNotDeleted, IsGroupMember)

# Admin with active status
IsActiveGroupAdmin = AndGroupPermission(IsActive, IsNotSuspended, IsNotLocked, IsNotDeleted, IsGroupAdmin)

# Owner with active status
IsActiveGroupOwner = AndGroupPermission(IsActive, IsNotSuspended, IsNotLocked, IsNotDeleted, IsGroupOwner)

# Member, group active, not full, not completed
IsActiveGroupStatus = AndGroupPermission(IsGroupActive, IsGroupNotFull, IsGroupNotCompleted, IsGroupNotCancelled)

# Can join: active, verified, group active, not full, not completed, not member
CanJoinGroupCombined = AndGroupPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    IsActiveGroupStatus,
    OrGroupPermission(IsGroupMember, IsNotGroupMember)  # This is a placeholder, actual logic is in CanJoinGroup
)

# Can leave: member, not only owner
CanLeaveGroupCombined = AndGroupPermission(IsActiveGroupMember, CanLeaveGroup)

# Can manage: admin, group active, not completed, not cancelled
CanManageGroupCombined = AndGroupPermission(IsActiveGroupAdmin, IsGroupActive, IsGroupNotCompleted, IsGroupNotCancelled)

# Can select winner: admin, group active, not completed, has members
CanSelectWinnerCombined = AndGroupPermission(IsActiveGroupAdmin, IsGroupActive, IsGroupNotCompleted)

# Can transfer ownership: owner, target is member
CanTransferOwnershipCombined = AndGroupPermission(IsActiveGroupOwner, CanTransferOwnership)

# Can create contribution: member, group active
CanCreateContributionCombined = AndGroupPermission(IsActiveGroupMember, IsGroupActive, IsGroupNotCompleted, IsGroupNotCancelled)

# Can process contribution: admin, group active
CanProcessContributionCombined = AndGroupPermission(IsActiveGroupAdmin, IsGroupActive)

# Can send invitation: member, group active, not full
CanSendInvitationCombined = AndGroupPermission(IsActiveGroupMember, IsGroupActive, IsGroupNotFull)


# ============================================================================
# PERMISSION MIXIN FOR VIEWSETS
# ============================================================================

class GroupPermissionsMixin:
    """
    Mixin for viewsets to automatically apply appropriate permissions
    based on the action being performed.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated],
        'retrieve': [IsAuthenticated],
        'create': [IsGroupMember],
        'update': [IsGroupAdmin],
        'partial_update': [IsGroupAdmin],
        'destroy': [IsGroupAdmin],
        'join': [CanJoinGroup],
        'leave': [CanLeaveGroup],
        'select_winner': [CanSelectWinner],
        'complete': [CanManageGroup],
        'cancel': [CanManageGroup],
        'pause': [CanManageGroup],
        'resume': [CanManageGroup],
        'stats': [IsGroupMember],
        'member_stats': [IsGroupMember],
        'contribution_summary': [IsGroupMember],
        'activities': [IsGroupMember],
        'winners': [IsGroupMember],
        'public': [permissions.AllowAny],
        'my_groups': [IsAuthenticated],
        'stats_overview': [IsAuthenticated],
        'promote': [IsGroupAdmin],
        'demote': [IsGroupAdmin],
        'transfer_ownership': [CanTransferOwnership],
        'accept': [CanAcceptInvitation],
        'reject': [IsAuthenticated],
        'cancel_invite': [IsGroupAdmin],
    }

    def get_permissions(self):
        """
        Get permissions based on the current action.
        """
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated]
        )
        return [permission() for permission in permission_classes]


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Helper functions
    'is_group_member',
    'is_group_admin',
    'is_group_owner',
    'get_group_from_view',
    'get_group_from_object',

    # Base permissions
    'IsGroupMember',
    'IsGroupAdmin',
    'IsGroupOwner',

    # Status permissions
    'IsGroupActive',
    'IsGroupNotFull',
    'IsGroupNotCompleted',
    'IsGroupNotCancelled',

    # Action-specific permissions
    'CanJoinGroup',
    'CanLeaveGroup',
    'CanSelectWinner',
    'CanManageGroup',
    'CanManageMembers',
    'CanTransferOwnership',
    'CanCreateContribution',
    'CanViewContribution',
    'CanProcessContribution',
    'CanSendInvitation',
    'CanAcceptInvitation',

    # Nested resource permissions
    'IsGroupMemberOfResource',
    'IsGroupAdminOfResource',

    # Combined permissions
    'OrGroupPermission',
    'AndGroupPermission',

    # Pre-defined combined permissions
    'IsActiveGroupMember',
    'IsActiveGroupAdmin',
    'IsActiveGroupOwner',
    'IsActiveGroupStatus',
    'CanJoinGroupCombined',
    'CanLeaveGroupCombined',
    'CanManageGroupCombined',
    'CanSelectWinnerCombined',
    'CanTransferOwnershipCombined',
    'CanCreateContributionCombined',
    'CanProcessContributionCombined',
    'CanSendInvitationCombined',

    # Mixin
    'GroupPermissionsMixin',
]