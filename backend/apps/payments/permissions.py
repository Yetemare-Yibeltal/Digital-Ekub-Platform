"""
Permission classes for the payments app.

This module provides comprehensive permission classes for payment operations:
- Payment ownership checks (IsPaymentOwner)
- Payment group admin checks (IsGroupAdminOfPayment)
- Payment member checks (IsMemberOfPaymentGroup)
- Action-specific permissions (CanViewPayment, CanCreatePayment, CanUpdatePayment, CanDeletePayment, CanProcessPayment)
- Payout-specific permissions (IsPayoutOwner, IsPayoutOwnerOrGroupAdmin, CanProcessPayout, CanViewPayout, CanCreatePayout, CanUpdatePayout, CanDeletePayout)
- Combined permissions for complex scenarios
- Object-level permissions for fine-grained access control
- Helper functions for permission checks
- Permission mixins for viewsets

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
from apps.common.constants import PaymentStatus, PayoutStatus

from .models import Payment, Payout, PaymentTransaction


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_payment_owner(user: User, payment: Payment) -> bool:
    """
    Check if a user is the owner of a payment.

    Args:
        user: User to check
        payment: Payment to check

    Returns:
        bool: True if user is the owner
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    if not payment:
        return False
    return payment.user == user


def is_group_admin_of_payment(user: User, payment: Payment) -> bool:
    """
    Check if a user is an admin of the group that owns the payment.

    Args:
        user: User to check
        payment: Payment to check

    Returns:
        bool: True if user is an admin of the payment's group
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    if not payment:
        return False
    return is_group_admin(user, payment.group)


def is_member_of_payment_group(user: User, payment: Payment) -> bool:
    """
    Check if a user is a member of the group that owns the payment.

    Args:
        user: User to check
        payment: Payment to check

    Returns:
        bool: True if user is a member of the payment's group
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    if not payment:
        return False
    return is_group_member(user, payment.group)


def is_payout_owner(user: User, payout: Payout) -> bool:
    """
    Check if a user is the owner of a payout.

    Args:
        user: User to check
        payout: Payout to check

    Returns:
        bool: True if user is the owner
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    if not payout:
        return False
    return payout.user == user


def is_group_admin_of_payout(user: User, payout: Payout) -> bool:
    """
    Check if a user is an admin of the group that owns the payout.

    Args:
        user: User to check
        payout: Payout to check

    Returns:
        bool: True if user is an admin of the payout's group
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    if not payout:
        return False
    return is_group_admin(user, payout.group)


def get_payment_from_view(view) -> Optional[Payment]:
    """
    Extract payment from view kwargs.

    Args:
        view: DRF view instance

    Returns:
        Payment instance or None
    """
    payment_id = view.kwargs.get('payment_id') or view.kwargs.get('pk')
    if not payment_id:
        if hasattr(view, 'request') and hasattr(view.request, 'data'):
            payment_id = view.request.data.get('payment_id') or view.request.data.get('payment')
        if not payment_id:
            return None
    try:
        return Payment.objects.get(id=payment_id, deleted_at__isnull=True)
    except Payment.DoesNotExist:
        return None


def get_payment_from_object(obj) -> Optional[Payment]:
    """
    Extract payment from an object.

    Args:
        obj: Object to extract payment from

    Returns:
        Payment instance or None
    """
    if hasattr(obj, 'payment'):
        return obj.payment
    if isinstance(obj, Payment):
        return obj
    if isinstance(obj, PaymentTransaction):
        return obj.payment
    if hasattr(obj, 'payment_id'):
        try:
            return Payment.objects.get(id=obj.payment_id, deleted_at__isnull=True)
        except Payment.DoesNotExist:
            return None
    return None


def get_payout_from_view(view) -> Optional[Payout]:
    """
    Extract payout from view kwargs.

    Args:
        view: DRF view instance

    Returns:
        Payout instance or None
    """
    payout_id = view.kwargs.get('payout_id') or view.kwargs.get('pk')
    if not payout_id:
        if hasattr(view, 'request') and hasattr(view.request, 'data'):
            payout_id = view.request.data.get('payout_id') or view.request.data.get('payout')
        if not payout_id:
            return None
    try:
        return Payout.objects.get(id=payout_id, deleted_at__isnull=True)
    except Payout.DoesNotExist:
        return None


def get_payout_from_object(obj) -> Optional[Payout]:
    """
    Extract payout from an object.

    Args:
        obj: Object to extract payout from

    Returns:
        Payout instance or None
    """
    if hasattr(obj, 'payout'):
        return obj.payout
    if isinstance(obj, Payout):
        return obj
    if hasattr(obj, 'payout_id'):
        try:
            return Payout.objects.get(id=obj.payout_id, deleted_at__isnull=True)
        except Payout.DoesNotExist:
            return None
    return None


# ============================================================================
# BASE PAYMENT PERMISSIONS
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
            # If no payment found, allow if user is superuser
            return request.user.is_superuser

        return is_payment_owner(request.user, payment)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payment = get_payment_from_object(obj)
        if not payment:
            return False

        return is_payment_owner(request.user, payment)


class IsGroupAdminOfPayment(BasePermission):
    """
    Allows access only if user is an admin of the payment's group.
    """
    message = _('You must be an admin of the group to perform this action.')

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

        return is_group_admin_of_payment(request.user, payment)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payment = get_payment_from_object(obj)
        if not payment:
            return False

        return is_group_admin_of_payment(request.user, payment)


class IsMemberOfPaymentGroup(BasePermission):
    """
    Allows access only if user is a member of the payment's group.
    """
    message = _('You must be a member of the group to view this payment.')

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

        return is_member_of_payment_group(request.user, payment)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payment = get_payment_from_object(obj)
        if not payment:
            return False

        return is_member_of_payment_group(request.user, payment)


# ============================================================================
# PAYMENT ACTION-SPECIFIC PERMISSIONS
# ============================================================================

class CanViewPayment(BasePermission):
    """
    Allows access only if user can view the payment.
    Checks: user is the owner, or member of the group, or admin/superuser.
    """
    message = _('You do not have permission to view this payment.')

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

        return is_payment_owner(request.user, payment) or is_member_of_payment_group(request.user, payment)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payment = get_payment_from_object(obj)
        if not payment:
            return False

        return is_payment_owner(request.user, payment) or is_member_of_payment_group(request.user, payment)


class CanCreatePayment(BasePermission):
    """
    Allows access only if user can create a payment.
    Checks: user is a member of the group, group is active.
    """
    message = _('You do not have permission to create a payment for this group.')

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

        if not is_group_member(request.user, group):
            return False

        if not group.is_active or group.is_completed or group.is_cancelled:
            return False

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payment = get_payment_from_object(obj)
        if not payment:
            return False

        return is_group_member(request.user, payment.group)


class CanUpdatePayment(BasePermission):
    """
    Allows access only if user can update a payment.
    Checks: user is owner or group admin/superuser.
    """
    message = _('You do not have permission to update this payment.')

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

        return is_payment_owner(request.user, payment) or is_group_admin_of_payment(request.user, payment)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payment = get_payment_from_object(obj)
        if not payment:
            return False

        return is_payment_owner(request.user, payment) or is_group_admin_of_payment(request.user, payment)


class CanDeletePayment(BasePermission):
    """
    Allows access only if user can delete a payment.
    Checks: user is owner or group admin/superuser.
    """
    message = _('You do not have permission to delete this payment.')

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

        if payment.status in [PaymentStatus.COMPLETED, PaymentStatus.REFUNDED]:
            return False

        return is_payment_owner(request.user, payment) or is_group_admin_of_payment(request.user, payment)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payment = get_payment_from_object(obj)
        if not payment:
            return False

        if payment.status in [PaymentStatus.COMPLETED, PaymentStatus.REFUNDED]:
            return False

        return is_payment_owner(request.user, payment) or is_group_admin_of_payment(request.user, payment)


class CanProcessPayment(BasePermission):
    """
    Allows access only if user can process (admin actions) a payment.
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
            return False

        return is_group_admin_of_payment(request.user, payment)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payment = get_payment_from_object(obj)
        if not payment:
            return False

        return is_group_admin_of_payment(request.user, payment)


# ============================================================================
# BASE PAYOUT PERMISSIONS
# ============================================================================

class IsPayoutOwner(BasePermission):
    """
    Allows access only to the owner of the payout.
    """
    message = _('You must be the owner of this payout to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_view(view)
        if not payout:
            return request.user.is_superuser

        return is_payout_owner(request.user, payout)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_object(obj)
        if not payout:
            return False

        return is_payout_owner(request.user, payout)


class IsGroupAdminOfPayout(BasePermission):
    """
    Allows access only if user is an admin of the payout's group.
    """
    message = _('You must be an admin of the group to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_view(view)
        if not payout:
            return False

        return is_group_admin_of_payout(request.user, payout)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_object(obj)
        if not payout:
            return False

        return is_group_admin_of_payout(request.user, payout)


# ============================================================================
# PAYOUT ACTION-SPECIFIC PERMISSIONS
# ============================================================================

class CanViewPayout(BasePermission):
    """
    Allows access only if user can view the payout.
    Checks: user is the owner, or member of the group, or admin/superuser.
    """
    message = _('You do not have permission to view this payout.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_view(view)
        if not payout:
            return True

        return is_payout_owner(request.user, payout) or is_group_member(request.user, payout.group)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_object(obj)
        if not payout:
            return False

        return is_payout_owner(request.user, payout) or is_group_member(request.user, payout.group)


class CanCreatePayout(BasePermission):
    """
    Allows access only if user can create a payout.
    Checks: user is group admin or superuser.
    """
    message = _('You do not have permission to create a payout for this group.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        # Get group from request data
        group_id = request.data.get('group')
        if not group_id:
            return False

        try:
            group = Group.objects.get(id=group_id, deleted_at__isnull=True)
        except Group.DoesNotExist:
            return False

        if not is_group_admin(request.user, group):
            return False

        if not group.is_active or group.is_completed or group.is_cancelled:
            return False

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_object(obj)
        if not payout:
            return False

        return is_group_admin(request.user, payout.group)


class CanUpdatePayout(BasePermission):
    """
    Allows access only if user can update a payout.
    Checks: user is owner or group admin/superuser.
    """
    message = _('You do not have permission to update this payout.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_view(view)
        if not payout:
            return False

        return is_payout_owner(request.user, payout) or is_group_admin_of_payout(request.user, payout)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_object(obj)
        if not payout:
            return False

        return is_payout_owner(request.user, payout) or is_group_admin_of_payout(request.user, payout)


class CanDeletePayout(BasePermission):
    """
    Allows access only if user can delete a payout.
    Checks: user is owner or group admin/superuser.
    """
    message = _('You do not have permission to delete this payout.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_view(view)
        if not payout:
            return False

        if payout.status in [PayoutStatus.COMPLETED, PayoutStatus.ON_HOLD]:
            return False

        return is_payout_owner(request.user, payout) or is_group_admin_of_payout(request.user, payout)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_object(obj)
        if not payout:
            return False

        if payout.status in [PayoutStatus.COMPLETED, PayoutStatus.ON_HOLD]:
            return False

        return is_payout_owner(request.user, payout) or is_group_admin_of_payout(request.user, payout)


class CanProcessPayout(BasePermission):
    """
    Allows access only if user can process (admin actions) a payout.
    Checks: user is group admin or superuser.
    """
    message = _('You do not have permission to process this payout.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_view(view)
        if not payout:
            return False

        return is_group_admin_of_payout(request.user, payout)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        payout = get_payout_from_object(obj)
        if not payout:
            return False

        return is_group_admin_of_payout(request.user, payout)


# ============================================================================
# COMBINED PERMISSIONS
# ============================================================================

class OrPaymentPermission(BasePermission):
    """
    Combined permission that allows if ANY of the given permissions allow.
    """
    def __init__(self, *perms: Type[BasePermission]):
        self.perms = perms

    def has_permission(self, request, view):
        return any(perm().has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        return any(perm().has_object_permission(request, view, obj) for perm in self.perms)


class AndPaymentPermission(BasePermission):
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
# PRE-DEFINED COMBINED PAYMENT PERMISSIONS
# ============================================================================

# Owner or group admin
IsPaymentOwnerOrGroupAdmin = OrPaymentPermission(IsPaymentOwner, IsGroupAdminOfPayment)

# Owner or member of group
IsPaymentOwnerOrMember = OrPaymentPermission(IsPaymentOwner, IsMemberOfPaymentGroup)

# Active owner with permission to view
CanViewPaymentActive = AndPaymentPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    CanViewPayment
)

# Active group admin with permission to process
CanProcessPaymentActive = AndPaymentPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    CanProcessPayment
)

# Can view (owner or member)
CanViewPaymentCombined = OrPaymentPermission(
    IsPaymentOwner,
    IsMemberOfPaymentGroup
)

# Can manage (owner or admin)
CanManagePaymentCombined = OrPaymentPermission(
    IsPaymentOwner,
    IsGroupAdminOfPayment
)

# Can update (owner or admin)
CanUpdatePaymentCombined = OrPaymentPermission(
    IsPaymentOwner,
    IsGroupAdminOfPayment
)

# Can delete (owner or admin) - soft delete only
CanDeletePaymentCombined = AndPaymentPermission(
    OrPaymentPermission(IsPaymentOwner, IsGroupAdminOfPayment)
)

# Can complete/fail/cancel/refund/retry/expire/reverse (admin only)
CanProcessPaymentCombined = AndPaymentPermission(
    IsGroupAdminOfPayment,
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted
)


# ============================================================================
# PRE-DEFINED COMBINED PAYOUT PERMISSIONS
# ============================================================================

# Owner or group admin
IsPayoutOwnerOrGroupAdmin = OrPaymentPermission(IsPayoutOwner, IsGroupAdminOfPayout)

# Active owner with permission to view
CanViewPayoutActive = AndPaymentPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    CanViewPayout
)

# Active group admin with permission to process
CanProcessPayoutActive = AndPaymentPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    CanProcessPayout
)

# Can view (owner or member)
CanViewPayoutCombined = OrPaymentPermission(
    IsPayoutOwner,
    IsMemberOfPaymentGroup
)

# Can manage (owner or admin)
CanManagePayoutCombined = OrPaymentPermission(
    IsPayoutOwner,
    IsGroupAdminOfPayout
)

# Can update (owner or admin)
CanUpdatePayoutCombined = OrPaymentPermission(
    IsPayoutOwner,
    IsGroupAdminOfPayout
)

# Can delete (owner or admin) - soft delete only
CanDeletePayoutCombined = AndPaymentPermission(
    OrPaymentPermission(IsPayoutOwner, IsGroupAdminOfPayout)
)

# Can complete/fail/cancel/put_on_hold (admin only)
CanProcessPayoutCombined = AndPaymentPermission(
    IsGroupAdminOfPayout,
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted
)


# ============================================================================
# PERMISSION MIXIN FOR PAYMENT VIEWSETS
# ============================================================================

class PaymentPermissionsMixin:
    """
    Mixin for payment viewsets to automatically apply appropriate permissions
    based on the action being performed.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, CanViewPayment],
        'retrieve': [IsAuthenticated, CanViewPayment],
        'create': [IsAuthenticated, IsActiveUser, CanCreatePayment],
        'update': [IsAuthenticated, IsActiveUser, CanUpdatePayment],
        'partial_update': [IsAuthenticated, IsActiveUser, CanUpdatePayment],
        'destroy': [IsAuthenticated, IsActiveUser, CanDeletePayment],
        'complete': [IsAuthenticated, IsActiveUser, CanProcessPayment],
        'fail': [IsAuthenticated, IsActiveUser, CanProcessPayment],
        'cancel': [IsAuthenticated, IsActiveUser, CanProcessPayment],
        'refund': [IsAuthenticated, IsActiveUser, CanProcessPayment],
        'retry': [IsAuthenticated, IsActiveUser, CanProcessPayment],
        'expire': [IsAuthenticated, IsActiveUser, CanProcessPayment],
        'reverse': [IsAuthenticated, IsActiveUser, CanProcessPayment],
        'transactions': [IsAuthenticated, IsActiveUser, CanViewPayment],
        'gateway_logs': [IsAuthenticated, IsActiveUser, CanViewPayment],
        'reconciliations': [IsAuthenticated, IsActiveUser, CanViewPayment],
        'disputes': [IsAuthenticated, IsActiveUser, CanViewPayment],
        'stats': [IsAuthenticated, IsActiveUser, CanViewPayment],
        'my_payments': [IsAuthenticated],
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


class PayoutPermissionsMixin:
    """
    Mixin for payout viewsets to automatically apply appropriate permissions
    based on the action being performed.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, CanViewPayout],
        'retrieve': [IsAuthenticated, CanViewPayout],
        'create': [IsAuthenticated, IsActiveUser, CanCreatePayout],
        'update': [IsAuthenticated, IsActiveUser, CanUpdatePayout],
        'partial_update': [IsAuthenticated, IsActiveUser, CanUpdatePayout],
        'destroy': [IsAuthenticated, IsActiveUser, CanDeletePayout],
        'complete': [IsAuthenticated, IsActiveUser, CanProcessPayout],
        'fail': [IsAuthenticated, IsActiveUser, CanProcessPayout],
        'cancel': [IsAuthenticated, IsActiveUser, CanProcessPayout],
        'put_on_hold': [IsAuthenticated, IsActiveUser, CanProcessPayout],
        'my_payouts': [IsAuthenticated],
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


# ============================================================================
# PERMISSION FOR WEBHOOKS (PUBLIC)
# ============================================================================

class AllowAnyForWebhook(BasePermission):
    """
    Allow any access for webhook endpoints (no authentication required).
    """
    def has_permission(self, request, view):
        return True


# ============================================================================
# ADMIN-ONLY PERMISSIONS FOR SETTLEMENTS AND RECONCILIATIONS
# ============================================================================

class IsSuperAdminForSettlement(BasePermission):
    """
    Allows access only to super admin users for settlement operations.
    """
    message = _('Only super admin can perform settlement operations.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_superuser


class IsSuperAdminForReconciliation(BasePermission):
    """
    Allows access only to super admin users for reconciliation operations.
    """
    message = _('Only super admin can perform reconciliation operations.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_superuser


# ============================================================================
# PERMISSION FOR PAYMENT METHODS (USER-OWNED)
# ============================================================================

class IsPaymentMethodOwner(BasePermission):
    """
    Allows access only to the owner of the payment method.
    """
    message = _('You must be the owner of this payment method to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        # For list and create, allow if authenticated
        if view.action in ['list', 'create']:
            return True

        # For other actions, check object permission
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        return obj.user == request.user


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Helper functions
    'is_payment_owner',
    'is_group_admin_of_payment',
    'is_member_of_payment_group',
    'is_payout_owner',
    'is_group_admin_of_payout',
    'get_payment_from_view',
    'get_payment_from_object',
    'get_payout_from_view',
    'get_payout_from_object',

    # Base payment permissions
    'IsPaymentOwner',
    'IsGroupAdminOfPayment',
    'IsMemberOfPaymentGroup',

    # Payment action-specific permissions
    'CanViewPayment',
    'CanCreatePayment',
    'CanUpdatePayment',
    'CanDeletePayment',
    'CanProcessPayment',

    # Base payout permissions
    'IsPayoutOwner',
    'IsGroupAdminOfPayout',

    # Payout action-specific permissions
    'CanViewPayout',
    'CanCreatePayout',
    'CanUpdatePayout',
    'CanDeletePayout',
    'CanProcessPayout',

    # Combined permissions
    'OrPaymentPermission',
    'AndPaymentPermission',

    # Pre-defined combined payment permissions
    'IsPaymentOwnerOrGroupAdmin',
    'IsPaymentOwnerOrMember',
    'CanViewPaymentActive',
    'CanProcessPaymentActive',
    'CanViewPaymentCombined',
    'CanManagePaymentCombined',
    'CanUpdatePaymentCombined',
    'CanDeletePaymentCombined',
    'CanProcessPaymentCombined',

    # Pre-defined combined payout permissions
    'IsPayoutOwnerOrGroupAdmin',
    'CanViewPayoutActive',
    'CanProcessPayoutActive',
    'CanViewPayoutCombined',
    'CanManagePayoutCombined',
    'CanUpdatePayoutCombined',
    'CanDeletePayoutCombined',
    'CanProcessPayoutCombined',

    # Mixins
    'PaymentPermissionsMixin',
    'PayoutPermissionsMixin',

    # Special permissions
    'AllowAnyForWebhook',
    'IsSuperAdminForSettlement',
    'IsSuperAdminForReconciliation',
    'IsPaymentMethodOwner',
]