"""
Permission classes for the contributions app.

This module provides comprehensive permission classes for contribution operations:
- Contribution ownership checks (IsContributionOwner)
- Group admin checks (IsGroupAdminOfContribution)
- Member group checks (IsMemberOfContributionGroup)
- Action-specific permissions (CanPayContribution, CanProcessContribution, etc.)
- Combined permissions for complex scenarios
- Object-level permissions for fine-grained access control
- Helper functions for permission checks

All permission classes implement both has_permission and has_object_permission
where appropriate for fine-grained access control.
"""

from rest_framework import permissions
from rest_framework.permissions import BasePermission, SAFE_METHODS
from django.shortcuts import get_object_or_404
from django.core.exceptions import PermissionDenied
from typing import Optional, Type, List, Union, Any

from apps.users.models import User
from apps.users.permissions import IsActive, IsVerified, IsNotSuspended, IsNotLocked, IsNotDeleted
from apps.groups.models import Group, GroupMember
from apps.groups.permissions import is_group_member, is_group_admin, is_group_owner, get_group_from_view, get_group_from_object
from apps.common.constants import ContributionStatus

from .models import Contribution, ContributionPayment


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_contribution_owner(user: User, contribution: Contribution) -> bool:
    """
    Check if a user is the owner of a contribution.

    Args:
        user: User to check
        contribution: Contribution to check

    Returns:
        bool: True if user is the owner
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    if not contribution:
        return False
    return contribution.user == user


def is_group_admin_of_contribution(user: User, contribution: Contribution) -> bool:
    """
    Check if a user is an admin of the group that owns the contribution.

    Args:
        user: User to check
        contribution: Contribution to check

    Returns:
        bool: True if user is an admin of the contribution's group
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    if not contribution:
        return False
    return is_group_admin(user, contribution.group)


def is_member_of_contribution_group(user: User, contribution: Contribution) -> bool:
    """
    Check if a user is a member of the group that owns the contribution.

    Args:
        user: User to check
        contribution: Contribution to check

    Returns:
        bool: True if user is a member of the contribution's group
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    if not contribution:
        return False
    return is_group_member(user, contribution.group)


def get_contribution_from_view(view) -> Optional[Contribution]:
    """
    Extract contribution from view kwargs or request data.

    Args:
        view: DRF view instance

    Returns:
        Contribution instance or None
    """
    contribution_id = view.kwargs.get('contribution_id') or view.kwargs.get('pk')
    if not contribution_id:
        if hasattr(view, 'request') and hasattr(view.request, 'data'):
            contribution_id = view.request.data.get('contribution_id') or view.request.data.get('contribution')
        if not contribution_id:
            return None
    try:
        return Contribution.objects.get(id=contribution_id, deleted_at__isnull=True)
    except Contribution.DoesNotExist:
        return None


def get_contribution_from_object(obj) -> Optional[Contribution]:
    """
    Extract contribution from an object.

    Args:
        obj: Object to extract contribution from

    Returns:
        Contribution instance or None
    """
    if hasattr(obj, 'contribution'):
        return obj.contribution
    if isinstance(obj, Contribution):
        return obj
    if hasattr(obj, 'contribution_id'):
        try:
            return Contribution.objects.get(id=obj.contribution_id, deleted_at__isnull=True)
        except Contribution.DoesNotExist:
            return None
    return None


def get_payment_from_view(view) -> Optional[ContributionPayment]:
    """
    Extract payment from view kwargs.

    Args:
        view: DRF view instance

    Returns:
        ContributionPayment instance or None
    """
    payment_id = view.kwargs.get('payment_id') or view.kwargs.get('pk')
    if not payment_id:
        return None
    try:
        return ContributionPayment.objects.get(id=payment_id)
    except ContributionPayment.DoesNotExist:
        return None


# ============================================================================
# BASE CONTRIBUTION PERMISSIONS
# ============================================================================

class IsContributionOwner(BasePermission):
    """
    Allows access only to the owner of the contribution.
    """
    message = _('You must be the owner of this contribution to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_view(view)
        if not contribution:
            # If no contribution found in view, check if it's a list or create action
            if view.action in ['list', 'create']:
                return True
            return False

        return is_contribution_owner(request.user, contribution)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        return is_contribution_owner(request.user, contribution)


class IsGroupAdminOfContribution(BasePermission):
    """
    Allows access only if user is an admin of the contribution's group.
    """
    message = _('You must be an admin of the group to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_view(view)
        if not contribution:
            return False

        return is_group_admin_of_contribution(request.user, contribution)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        return is_group_admin_of_contribution(request.user, contribution)


class IsMemberOfContributionGroup(BasePermission):
    """
    Allows access only if user is a member of the contribution's group.
    """
    message = _('You must be a member of the group to view this contribution.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_view(view)
        if not contribution:
            return True

        return is_member_of_contribution_group(request.user, contribution)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        return is_member_of_contribution_group(request.user, contribution)


# ============================================================================
# ACTION-SPECIFIC PERMISSIONS
# ============================================================================

class CanViewContribution(BasePermission):
    """
    Allows access only if user can view the contribution.
    Checks: user is the owner, or member of the group, or admin/superuser.
    """
    message = _('You do not have permission to view this contribution.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_view(view)
        if not contribution:
            return True

        return is_contribution_owner(request.user, contribution) or is_member_of_contribution_group(request.user, contribution)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        return is_contribution_owner(request.user, contribution) or is_member_of_contribution_group(request.user, contribution)


class CanCreateContribution(BasePermission):
    """
    Allows access only if user can create a contribution.
    Checks: user is a member of the group, group is active, not completed.
    """
    message = _('You do not have permission to create a contribution for this group.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        if not request.user.is_active:
            return False
        if request.user.is_suspended or request.user.is_locked:
            return False

        # Get group from request data
        group_id = request.data.get('group')
        if not group_id:
            return False

        try:
            group = Group.objects.get(id=group_id, deleted_at__isnull=True)
        except Group.DoesNotExist:
            return False

        # Check if user is a member
        if not is_group_member(request.user, group):
            return False

        # Check group status
        if not group.is_active:
            return False
        if group.is_completed:
            return False
        if group.is_cancelled:
            return False

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        return is_group_member(request.user, contribution.group)


class CanUpdateContribution(BasePermission):
    """
    Allows access only if user can update a contribution.
    Checks: user is owner or group admin/superuser.
    """
    message = _('You do not have permission to update this contribution.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_view(view)
        if not contribution:
            return False

        return is_contribution_owner(request.user, contribution) or is_group_admin_of_contribution(request.user, contribution)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        return is_contribution_owner(request.user, contribution) or is_group_admin_of_contribution(request.user, contribution)


class CanDeleteContribution(BasePermission):
    """
    Allows access only if user can delete a contribution.
    Checks: user is owner or group admin/superuser (soft delete only).
    """
    message = _('You do not have permission to delete this contribution.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_view(view)
        if not contribution:
            return False

        # Check if contribution can be deleted (not paid)
        if contribution.status in [ContributionStatus.PAID, ContributionStatus.REFUNDED]:
            return False

        return is_contribution_owner(request.user, contribution) or is_group_admin_of_contribution(request.user, contribution)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        if contribution.status in [ContributionStatus.PAID, ContributionStatus.REFUNDED]:
            return False

        return is_contribution_owner(request.user, contribution) or is_group_admin_of_contribution(request.user, contribution)


class CanPayContribution(BasePermission):
    """
    Allows access only if user can pay a contribution.
    Checks: user is owner, contribution is pending or overdue, group is active.
    """
    message = _('You do not have permission to pay this contribution.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        if not request.user.is_active:
            return False
        if request.user.is_suspended or request.user.is_locked:
            return False

        contribution = get_contribution_from_view(view)
        if not contribution:
            return False

        # Must be owner
        if not is_contribution_owner(request.user, contribution):
            return False

        # Check contribution status
        if contribution.status not in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]:
            return False

        # Check group status
        if not contribution.group.is_active:
            return False
        if contribution.group.is_completed:
            return False
        if contribution.group.is_cancelled:
            return False

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        if not is_contribution_owner(request.user, contribution):
            return False

        if contribution.status not in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]:
            return False

        if not contribution.group.is_active or contribution.group.is_completed or contribution.group.is_cancelled:
            return False

        return True


class CanProcessContribution(BasePermission):
    """
    Allows access only if user can process (admin actions) a contribution.
    Checks: user is group admin or superuser.
    """
    message = _('You do not have permission to process this contribution.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_view(view)
        if not contribution:
            return False

        return is_group_admin_of_contribution(request.user, contribution)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        return is_group_admin_of_contribution(request.user, contribution)


class CanRefundContribution(BasePermission):
    """
    Allows access only if user can refund a contribution.
    Checks: user is group admin or superuser, contribution is paid.
    """
    message = _('You do not have permission to refund this contribution.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_view(view)
        if not contribution:
            return False

        if contribution.status != ContributionStatus.PAID:
            return False

        return is_group_admin_of_contribution(request.user, contribution)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        if contribution.status != ContributionStatus.PAID:
            return False

        return is_group_admin_of_contribution(request.user, contribution)


class CanWaiveContribution(BasePermission):
    """
    Allows access only if user can waive a contribution.
    Checks: user is group admin or superuser, contribution is pending or overdue.
    """
    message = _('You do not have permission to waive this contribution.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_view(view)
        if not contribution:
            return False

        if contribution.status not in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]:
            return False

        return is_group_admin_of_contribution(request.user, contribution)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        if contribution.status not in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]:
            return False

        return is_group_admin_of_contribution(request.user, contribution)


class CanSendReminder(BasePermission):
    """
    Allows access only if user can send a reminder for a contribution.
    Checks: user is owner or group admin/superuser.
    """
    message = _('You do not have permission to send a reminder for this contribution.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_view(view)
        if not contribution:
            return False

        return is_contribution_owner(request.user, contribution) or is_group_admin_of_contribution(request.user, contribution)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        contribution = get_contribution_from_object(obj)
        if not contribution:
            return False

        return is_contribution_owner(request.user, contribution) or is_group_admin_of_contribution(request.user, contribution)


# ============================================================================
# PAYMENT-SPECIFIC PERMISSIONS
# ============================================================================

class IsPaymentOwner(BasePermission):
    """
    Allows access only to the owner of the payment.
    """
    message = _('You must be the owner of this payment to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payment = get_payment_from_view(view)
        if not payment:
            return True

        return payment.user == request.user

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        return obj.user == request.user


class CanCreatePayment(BasePermission):
    """
    Allows access only if user can create a payment.
    Checks: user is the contribution owner, contribution can be paid.
    """
    message = _('You do not have permission to create a payment for this contribution.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        if not request.user.is_active:
            return False

        contribution_id = request.data.get('contribution')
        if not contribution_id:
            return False

        try:
            contribution = Contribution.objects.get(id=contribution_id, deleted_at__isnull=True)
        except Contribution.DoesNotExist:
            return False

        if not is_contribution_owner(request.user, contribution):
            return False

        if contribution.status not in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]:
            return False

        if not contribution.group.is_active or contribution.group.is_completed or contribution.group.is_cancelled:
            return False

        return True


class CanProcessPayment(BasePermission):
    """
    Allows access only if user can process a payment.
    Checks: user is group admin or superuser.
    """
    message = _('You do not have permission to process this payment.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payment = get_payment_from_view(view)
        if not payment:
            return True

        return is_group_admin(payment.user, payment.group)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        return is_group_admin(obj.user, obj.group)


class CanRefundPayment(BasePermission):
    """
    Allows access only if user can refund a payment.
    Checks: user is group admin or superuser, payment is completed.
    """
    message = _('You do not have permission to refund this payment.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payment = get_payment_from_view(view)
        if not payment:
            return False

        if payment.status != PaymentStatus.COMPLETED:
            return False

        return is_group_admin(payment.user, payment.group)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        if obj.status != PaymentStatus.COMPLETED:
            return False

        return is_group_admin(obj.user, obj.group)


# ============================================================================
# COMBINED PERMISSIONS
# ============================================================================

class OrContributionPermission(BasePermission):
    """
    Combined permission that allows if ANY of the given permissions allow.
    """
    def __init__(self, *perms: Type[BasePermission]):
        self.perms = perms

    def has_permission(self, request, view):
        return any(perm().has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        return any(perm().has_object_permission(request, view, obj) for perm in self.perms)


class AndContributionPermission(BasePermission):
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

# Owner or group admin
IsContributionOwnerOrGroupAdmin = OrContributionPermission(IsContributionOwner, IsGroupAdminOfContribution)

# Owner or member of group
IsContributionOwnerOrMember = OrContributionPermission(IsContributionOwner, IsMemberOfContributionGroup)

# Active owner with permission to pay
CanPayContributionActive = AndContributionPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    CanPayContribution
)

# Active group admin with permission to process
CanProcessContributionActive = AndContributionPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    CanProcessContribution
)

# Can view (owner or member)
CanViewContributionCombined = OrContributionPermission(
    IsContributionOwner,
    IsMemberOfContributionGroup
)

# Can manage (owner or admin)
CanManageContributionCombined = OrContributionPermission(
    IsContributionOwner,
    IsGroupAdminOfContribution
)

# Can update (owner or admin)
CanUpdateContributionCombined = OrContributionPermission(
    IsContributionOwner,
    IsGroupAdminOfContribution
)

# Can delete (owner or admin) - soft delete only
CanDeleteContributionCombined = AndContributionPermission(
    OrContributionPermission(IsContributionOwner, IsGroupAdminOfContribution)
)

# Can mark paid (owner)
CanMarkPaidContributionCombined = AndContributionPermission(
    IsContributionOwner,
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted
)

# Can mark overdue (admin or superuser)
CanMarkOverdueContributionCombined = AndContributionPermission(
    IsGroupAdminOfContribution,
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted
)

# Can refund (admin or superuser)
CanRefundContributionCombined = AndContributionPermission(
    IsGroupAdminOfContribution,
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted
)

# Can waive (admin or superuser)
CanWaiveContributionCombined = AndContributionPermission(
    IsGroupAdminOfContribution,
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted
)

# Can send reminder (owner or admin)
CanSendReminderCombined = OrContributionPermission(
    IsContributionOwner,
    IsGroupAdminOfContribution
)


# ============================================================================
# PERMISSION MIXIN FOR VIEWSETS
# ============================================================================

class ContributionPermissionsMixin:
    """
    Mixin for viewsets to automatically apply appropriate permissions
    based on the action being performed.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, CanViewContribution],
        'retrieve': [IsAuthenticated, CanViewContribution],
        'create': [IsAuthenticated, IsActiveUser, CanCreateContribution],
        'update': [IsAuthenticated, IsActiveUser, CanUpdateContribution],
        'partial_update': [IsAuthenticated, IsActiveUser, CanUpdateContribution],
        'destroy': [IsAuthenticated, IsActiveUser, CanDeleteContribution],
        'mark_paid': [IsAuthenticated, IsActiveUser, CanPayContribution],
        'mark_overdue': [IsAuthenticated, IsActiveUser, CanProcessContribution],
        'cancel_contribution': [IsAuthenticated, IsActiveUser, CanProcessContribution],
        'refund_contribution': [IsAuthenticated, IsActiveUser, CanRefundContribution],
        'waive_contribution': [IsAuthenticated, IsActiveUser, CanWaiveContribution],
        'send_reminder': [IsAuthenticated, IsActiveUser, CanSendReminder],
        'reminders': [IsAuthenticated, IsActiveUser, CanViewContribution],
        'audit_trail': [IsAuthenticated, IsActiveUser, CanViewContribution],
        'payment_detail': [IsAuthenticated, IsActiveUser, CanViewContribution],
        'stats': [IsAuthenticated, IsActiveUser, CanViewContribution],
        'my_contributions': [IsAuthenticated],
        'pending': [IsAuthenticated],
        'overdue': [IsAuthenticated],
        'summary': [IsAuthenticated],
        'group_summary': [IsAuthenticated],
        'bulk_create': [IsAuthenticated, IsSuperAdminUser],
        'bulk_update_status': [IsAuthenticated, IsSuperAdminUser],
        'stats_overview': [IsAuthenticated, IsSuperAdminUser],
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


class PaymentPermissionsMixin:
    """
    Mixin for payment viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated],
        'retrieve': [IsAuthenticated],
        'create': [IsAuthenticated, IsActiveUser, CanCreatePayment],
        'update': [IsAuthenticated, IsActiveUser, CanProcessPayment],
        'partial_update': [IsAuthenticated, IsActiveUser, CanProcessPayment],
        'destroy': [IsAuthenticated, IsActiveUser, CanProcessPayment],
        'refund_payment': [IsAuthenticated, IsActiveUser, CanRefundPayment],
        'mark_completed': [IsAuthenticated, IsActiveUser, CanProcessPayment],
        'mark_failed': [IsAuthenticated, IsActiveUser, CanProcessPayment],
    }

    def get_permissions(self):
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
    'is_contribution_owner',
    'is_group_admin_of_contribution',
    'is_member_of_contribution_group',
    'get_contribution_from_view',
    'get_contribution_from_object',
    'get_payment_from_view',

    # Base permissions
    'IsContributionOwner',
    'IsGroupAdminOfContribution',
    'IsMemberOfContributionGroup',

    # Action-specific permissions
    'CanViewContribution',
    'CanCreateContribution',
    'CanUpdateContribution',
    'CanDeleteContribution',
    'CanPayContribution',
    'CanProcessContribution',
    'CanRefundContribution',
    'CanWaiveContribution',
    'CanSendReminder',

    # Payment permissions
    'IsPaymentOwner',
    'CanCreatePayment',
    'CanProcessPayment',
    'CanRefundPayment',

    # Combined permissions
    'OrContributionPermission',
    'AndContributionPermission',

    # Pre-defined combined permissions
    'IsContributionOwnerOrGroupAdmin',
    'IsContributionOwnerOrMember',
    'CanPayContributionActive',
    'CanProcessContributionActive',
    'CanViewContributionCombined',
    'CanManageContributionCombined',
    'CanUpdateContributionCombined',
    'CanDeleteContributionCombined',
    'CanMarkPaidContributionCombined',
    'CanMarkOverdueContributionCombined',
    'CanRefundContributionCombined',
    'CanWaiveContributionCombined',
    'CanSendReminderCombined',

    # Mixins
    'ContributionPermissionsMixin',
    'PaymentPermissionsMixin',
]