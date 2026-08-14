"""
Shared permission classes for the Digital Ekub Platform.

This module provides reusable permission classes used across multiple apps
for consistent access control based on user roles, group membership,
contribution status, payment ownership, and other domain-specific rules.
"""

from rest_framework import permissions
from rest_framework.permissions import BasePermission, SAFE_METHODS
from django.shortcuts import get_object_or_404
from django.core.exceptions import PermissionDenied
from typing import Any, Optional, Union, Callable, Type
from functools import wraps

from apps.groups.models import Group, GroupMember
from apps.contributions.models import Contribution
from apps.payments.models import Payment, Payout
from apps.users.models import User


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_group_admin(user: User, group: Group) -> bool:
    """Check if user is an admin of the group."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return GroupMember.objects.filter(
        user=user,
        group=group,
        role__in=['admin', 'owner'],
        is_active=True
    ).exists()


def is_group_member(user: User, group: Group) -> bool:
    """Check if user is a member of the group."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return GroupMember.objects.filter(
        user=user,
        group=group,
        is_active=True
    ).exists()


def is_group_owner(user: User, group: Group) -> bool:
    """Check if user is the owner of the group."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return GroupMember.objects.filter(
        user=user,
        group=group,
        role='owner',
        is_active=True
    ).exists()


def is_group_active(group: Group) -> bool:
    """Check if the group is active."""
    return group.status == 'active'


def is_contribution_owner(user: User, contribution: Contribution) -> bool:
    """Check if user owns the contribution."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return contribution.user == user


def is_payment_owner(user: User, payment: Payment) -> bool:
    """Check if user owns the payment."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return payment.user == user


# ============================================================================
# BASE PERMISSION CLASSES
# ============================================================================

class IsAuthenticated(BasePermission):
    """Allows access only to authenticated users."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class IsAdminUser(BasePermission):
    """Allows access only to admin/staff users."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_staff and
            not request.user.is_deleted()
        )


class IsSuperAdminUser(BasePermission):
    """Allows access only to super admin users."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_superuser and
            not request.user.is_deleted()
        )


class IsActiveUser(BasePermission):
    """Allows access only to active users."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_active and
            not request.user.is_suspended and
            not request.user.is_locked and
            not request.user.is_deleted()
        )


class IsVerifiedUser(BasePermission):
    """Allows access only to verified users."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_verified and
            request.user.is_active and
            not request.user.is_suspended and
            not request.user.is_locked and
            not request.user.is_deleted()
        )


class IsPhoneVerifiedUser(BasePermission):
    """Allows access only to phone-verified users."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_phone_verified and
            request.user.is_active and
            not request.user.is_suspended and
            not request.user.is_locked and
            not request.user.is_deleted()
        )


class IsEmailVerifiedUser(BasePermission):
    """Allows access only to email-verified users."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_email_verified and
            request.user.is_active and
            not request.user.is_suspended and
            not request.user.is_locked and
            not request.user.is_deleted()
        )


class IsIdentityVerifiedUser(BasePermission):
    """Allows access only to identity-verified users."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_identity_verified and
            request.user.is_active and
            not request.user.is_suspended and
            not request.user.is_locked and
            not request.user.is_deleted()
        )


class IsActiveAndVerified(BasePermission):
    """Allows access only to active and verified users."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_active and
            request.user.is_verified and
            not request.user.is_suspended and
            not request.user.is_locked and
            not request.user.is_deleted()
        )


class IsNotSuspended(BasePermission):
    """Allows access only to non-suspended users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return not request.user.is_suspended


class IsNotLocked(BasePermission):
    """Allows access only to non-locked users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return not request.user.is_locked


class IsNotDeleted(BasePermission):
    """Allows access only to non-deleted users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return not request.user.is_deleted()


class IsActiveAndPhoneVerified(BasePermission):
    """Allows access only to active and phone-verified users."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_active and
            request.user.is_phone_verified and
            not request.user.is_suspended and
            not request.user.is_locked and
            not request.user.is_deleted()
        )


class IsActiveAndEmailVerified(BasePermission):
    """Allows access only to active and email-verified users."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_active and
            request.user.is_email_verified and
            not request.user.is_suspended and
            not request.user.is_locked and
            not request.user.is_deleted()
        )


class IsAdminOrReadOnly(BasePermission):
    """Read for all, write only for admin users."""
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_staff and
            not request.user.is_deleted()
        )


class IsSuperAdminOrReadOnly(BasePermission):
    """Read for all, write only for super admin users."""
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_superuser and
            not request.user.is_deleted()
        )


class IsOwnerOrReadOnly(BasePermission):
    """Object-level read for all, write only for the owner."""
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if hasattr(obj, 'user'):
            return obj.user == request.user
        if hasattr(obj, 'owner'):
            return obj.owner == request.user
        return False


class IsOwnerOrAdmin(BasePermission):
    """Object-level access for owner or admin users."""
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        if hasattr(obj, 'user'):
            return obj.user == request.user
        if hasattr(obj, 'owner'):
            return obj.owner == request.user
        return False


class IsOwnerOrSuperAdmin(BasePermission):
    """Object-level access for owner or super admin users."""
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if hasattr(obj, 'user'):
            return obj.user == request.user
        if hasattr(obj, 'owner'):
            return obj.owner == request.user
        return False


class IsSameUser(BasePermission):
    """Allows access only if user is accessing their own data."""
    def has_object_permission(self, request, view, obj):
        if isinstance(obj, User):
            return obj.id == request.user.id
        if hasattr(obj, 'user'):
            return obj.user == request.user
        return False


class IsSameUserOrReadOnly(BasePermission):
    """Allows read for all, write only for the user themselves."""
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if isinstance(obj, User):
            return obj.id == request.user.id
        if hasattr(obj, 'user'):
            return obj.user == request.user
        return False


class IsSameUserOrAdmin(BasePermission):
    """Allows access for user themselves or admin users."""
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        if isinstance(obj, User):
            return obj.id == request.user.id
        if hasattr(obj, 'user'):
            return obj.user == request.user
        return False


class IsSameUserOrSuperAdmin(BasePermission):
    """Allows access for user themselves or super admin users."""
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if isinstance(obj, User):
            return obj.id == request.user.id
        if hasattr(obj, 'user'):
            return obj.user == request.user
        return False


# ============================================================================
# GROUP-SPECIFIC PERMISSIONS
# ============================================================================

class IsGroupMember(BasePermission):
    """Allows access only if user is a member of the group."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        group_id = view.kwargs.get('group_id') or view.kwargs.get('pk')
        if not group_id:
            return True
        try:
            group = Group.objects.get(id=group_id)
            return is_group_member(request.user, group)
        except Group.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        if hasattr(obj, 'group'):
            return is_group_member(request.user, obj.group)
        return False


class IsGroupAdmin(BasePermission):
    """Allows access only if user is an admin of the group."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        group_id = view.kwargs.get('group_id') or view.kwargs.get('pk')
        if not group_id:
            return True
        try:
            group = Group.objects.get(id=group_id)
            return is_group_admin(request.user, group)
        except Group.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if hasattr(obj, 'group'):
            return is_group_admin(request.user, obj.group)
        return False


class IsGroupOwner(BasePermission):
    """Allows access only if user is the owner of the group."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        group_id = view.kwargs.get('group_id') or view.kwargs.get('pk')
        if not group_id:
            return True
        try:
            group = Group.objects.get(id=group_id)
            return is_group_owner(request.user, group)
        except Group.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if hasattr(obj, 'group'):
            return is_group_owner(request.user, obj.group)
        return False


class IsGroupActive(BasePermission):
    """Allows access only if the group is active."""
    def has_permission(self, request, view):
        group_id = view.kwargs.get('group_id') or view.kwargs.get('pk')
        if not group_id:
            return True
        try:
            group = Group.objects.get(id=group_id)
            return is_group_active(group)
        except Group.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        if hasattr(obj, 'group'):
            return is_group_active(obj.group)
        return False


class IsGroupNotFull(BasePermission):
    """Allows access only if the group is not full."""
    def has_permission(self, request, view):
        group_id = view.kwargs.get('group_id') or view.kwargs.get('pk')
        if not group_id:
            return True
        try:
            group = Group.objects.get(id=group_id)
            return group.members.count() < group.max_members
        except Group.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        if hasattr(obj, 'group'):
            return obj.group.members.count() < obj.group.max_members
        return False


class IsGroupNotCompleted(BasePermission):
    """Allows access only if the group is not completed."""
    def has_permission(self, request, view):
        group_id = view.kwargs.get('group_id') or view.kwargs.get('pk')
        if not group_id:
            return True
        try:
            group = Group.objects.get(id=group_id)
            return group.status != 'completed'
        except Group.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        if hasattr(obj, 'group'):
            return obj.group.status != 'completed'
        return False


class CanJoinGroup(BasePermission):
    """
    Allows access only if user can join the group.
    Checks: user is active, phone verified, group active, group not full,
    group not completed, user not already a member.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_suspended or request.user.is_locked or request.user.is_deleted():
            return False
        if not request.user.is_active:
            return False
        if not request.user.is_phone_verified:
            return False

        group_id = view.kwargs.get('group_id') or view.kwargs.get('pk')
        if not group_id:
            return True
        try:
            group = Group.objects.get(id=group_id)
            if group.status != 'active':
                return False
            if group.members.count() >= group.max_members:
                return False
            if GroupMember.objects.filter(user=request.user, group=group, is_active=True).exists():
                return False
            return True
        except Group.DoesNotExist:
            return False


class CanLeaveGroup(BasePermission):
    """
    Allows access only if user can leave the group.
    Checks: user is a member, user is not the only admin/owner.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        group_id = view.kwargs.get('group_id') or view.kwargs.get('pk')
        if not group_id:
            return True
        try:
            group = Group.objects.get(id=group_id)
            if not is_group_member(request.user, group):
                return False
            # If user is the only owner, cannot leave without transferring
            if is_group_owner(request.user, group):
                owners = GroupMember.objects.filter(group=group, role='owner', is_active=True)
                if owners.count() == 1:
                    return False
            return True
        except Group.DoesNotExist:
            return False


# ============================================================================
# CONTRIBUTION-SPECIFIC PERMISSIONS
# ============================================================================

class IsContributionOwner(BasePermission):
    """Allows access only if user owns the contribution."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        contribution_id = view.kwargs.get('contribution_id') or view.kwargs.get('pk')
        if not contribution_id:
            return True
        try:
            contribution = Contribution.objects.get(id=contribution_id)
            return contribution.user == request.user
        except Contribution.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        return is_contribution_owner(request.user, obj)


class CanPayContribution(BasePermission):
    """
    Allows access only if user can pay the contribution.
    Checks: user is member of group, contribution belongs to user,
    contribution is pending, contribution is not overdue beyond grace period.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_suspended or request.user.is_locked or request.user.is_deleted():
            return False
        if not request.user.is_active:
            return False

        contribution_id = view.kwargs.get('contribution_id') or view.kwargs.get('pk')
        if not contribution_id:
            return True
        try:
            contribution = Contribution.objects.get(id=contribution_id)
            if contribution.user != request.user:
                return False
            if contribution.status != 'pending':
                return False
            if not is_group_member(request.user, contribution.group):
                return False
            return True
        except Contribution.DoesNotExist:
            return False


class CanProcessContribution(BasePermission):
    """
    Allows access only if user can process (approve/reject) contributions.
    Allowed: group admin, super admin, or system user.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        contribution_id = view.kwargs.get('contribution_id') or view.kwargs.get('pk')
        if not contribution_id:
            return True
        try:
            contribution = Contribution.objects.get(id=contribution_id)
            return is_group_admin(request.user, contribution.group)
        except Contribution.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        return is_group_admin(request.user, obj.group)


# ============================================================================
# PAYMENT-SPECIFIC PERMISSIONS
# ============================================================================

class IsPaymentOwner(BasePermission):
    """Allows access only if user owns the payment."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        payment_id = view.kwargs.get('payment_id') or view.kwargs.get('pk')
        if not payment_id:
            return True
        try:
            payment = Payment.objects.get(id=payment_id)
            return payment.user == request.user
        except Payment.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        return is_payment_owner(request.user, obj)


class CanInitiatePayment(BasePermission):
    """
    Allows access only if user can initiate a payment.
    Checks: user is active, phone verified, has sufficient balance/reputation.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_suspended or request.user.is_locked or request.user.is_deleted():
            return False
        if not request.user.is_active:
            return False
        if not request.user.is_phone_verified:
            return False
        if request.user.reputation_score < 30:
            return False
        return True


class CanProcessPayment(BasePermission):
    """
    Allows access only if user can process payments.
    Allowed: group admin, super admin, or system user.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        # Check if user is group admin of the payment's group
        payment_id = view.kwargs.get('payment_id') or view.kwargs.get('pk')
        if not payment_id:
            return True
        try:
            payment = Payment.objects.get(id=payment_id)
            contribution = payment.contribution
            return is_group_admin(request.user, contribution.group)
        except (Payment.DoesNotExist, AttributeError):
            return False

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        contribution = getattr(obj, 'contribution', None)
        if contribution:
            return is_group_admin(request.user, contribution.group)
        return False


# ============================================================================
# NOTIFICATION-SPECIFIC PERMISSIONS
# ============================================================================

class IsNotificationOwner(BasePermission):
    """Allows access only if user owns the notification."""
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        return hasattr(obj, 'user') and obj.user == request.user


class CanSendNotification(BasePermission):
    """Allows access only if user can send notifications."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_staff:
            return True
        return False


# ============================================================================
# COMPOSITE PERMISSIONS (MIXIN)
# ============================================================================

class OrPermission(BasePermission):
    """
    Combined permission that allows if ANY of the given permissions allow.
    """
    def __init__(self, *perms: Type[BasePermission]):
        self.perms = perms

    def has_permission(self, request, view):
        return any(perm().has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        return any(perm().has_object_permission(request, view, obj) for perm in self.perms)


class AndPermission(BasePermission):
    """
    Combined permission that allows if ALL of the given permissions allow.
    """
    def __init__(self, *perms: Type[BasePermission]):
        self.perms = perms

    def has_permission(self, request, view):
        return all(perm().has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        return all(perm().has_object_permission(request, view, obj) for perm in self.perms)


class NotPermission(BasePermission):
    """
    Negation of a permission.
    """
    def __init__(self, perm: Type[BasePermission]):
        self.perm = perm

    def has_permission(self, request, view):
        return not self.perm().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        return not self.perm().has_object_permission(request, view, obj)


# ============================================================================
# PERMISSION DECORATORS
# ============================================================================

def permission_required(perm_class: Type[BasePermission]):
    """
    Decorator to check permission on view function.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not perm_class().has_permission(request, None):
                raise PermissionDenied('Permission denied')
            return view_func(request, *args, **kwargs)
        return wrapped_view
    return decorator


def object_permission_required(perm_class: Type[BasePermission]):
    """
    Decorator to check object permission on view function.
    Expects 'obj' in kwargs or view method to return object.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            obj = kwargs.get('obj')
            if obj is None:
                # Try to get object from view method
                view = args[0] if args else None
                if view and hasattr(view, 'get_object'):
                    obj = view.get_object()
                else:
                    raise PermissionDenied('Object not found')
            if not perm_class().has_object_permission(request, None, obj):
                raise PermissionDenied('Object permission denied')
            return view_func(request, *args, **kwargs)
        return wrapped_view
    return decorator


# ============================================================================
# PRE-DEFINED COMBINED PERMISSIONS
# ============================================================================

# Admin or owner
IsAdminOrOwner = OrPermission(IsAdminUser, IsOwnerOrReadOnly)

# Super admin or owner
IsSuperAdminOrOwner = OrPermission(IsSuperAdminUser, IsOwnerOrReadOnly)

# Active and verified user
IsActiveVerifiedUser = AndPermission(IsActiveUser, IsVerifiedUser)

# Group member with active status
IsActiveGroupMember = AndPermission(IsActiveUser, IsGroupMember)

# Group admin or active member
IsGroupAdminOrMember = OrPermission(IsGroupAdmin, IsGroupMember)

# Active and phone-verified group member
IsActivePhoneVerifiedMember = AndPermission(IsActiveAndPhoneVerified, IsGroupMember)

# Contribution owner or group admin
IsContributionOwnerOrGroupAdmin = OrPermission(IsContributionOwner, IsGroupAdmin)

# Payment owner or super admin
IsPaymentOwnerOrSuperAdmin = OrPermission(IsPaymentOwner, IsSuperAdminUser)

# Can manage group (admin or owner)
CanManageGroup = OrPermission(IsGroupAdmin, IsGroupOwner)

# Can view group details (any authenticated user)
CanViewGroup = IsAuthenticated

# Can create contribution (active member of group)
CanCreateContribution = AndPermission(IsActiveGroupMember, IsGroupActive, IsGroupNotCompleted)

# Can view contribution (owner or group admin)
CanViewContribution = OrPermission(IsContributionOwner, IsGroupAdmin)

# Can update contribution (owner)
CanUpdateContribution = IsContributionOwner

# Can delete contribution (owner or admin)
CanDeleteContribution = OrPermission(IsContributionOwner, IsSuperAdminUser)

# Can create payment (authenticated with sufficient reputation)
CanCreatePayment = AndPermission(IsActiveUser, IsPhoneVerifiedUser, IsNotDefaultedUser)

# Can view payment (owner or admin)
CanViewPayment = OrPermission(IsPaymentOwner, IsSuperAdminUser)

# Can process payout (group admin or super admin)
CanProcessPayout = OrPermission(IsGroupAdmin, IsSuperAdminUser)