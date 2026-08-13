from rest_framework import permissions
from rest_framework.permissions import BasePermission, SAFE_METHODS
from django.shortcuts import get_object_or_404
from .models import User


class IsAuthenticated(permissions.IsAuthenticated):
    """Allows access only to authenticated users."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class IsVerified(BasePermission):
    """Allows access only to fully verified users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        if request.user.is_locked:
            return False
        return request.user.is_verified


class IsPhoneVerified(BasePermission):
    """Allows access only to phone-verified users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        return request.user.is_phone_verified


class IsEmailVerified(BasePermission):
    """Allows access only to email-verified users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        return request.user.is_email_verified


class IsIdentityVerified(BasePermission):
    """Allows access only to identity-verified users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        return request.user.is_identity_verified


class IsAdmin(BasePermission):
    """Allows access only to staff/admin users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_staff


class IsSuperAdmin(BasePermission):
    """Allows access only to super admin users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_superuser


class IsActive(BasePermission):
    """Allows access only to active users (not suspended, locked, or deleted)."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        if request.user.is_locked:
            return False
        return request.user.is_active


class IsNotDeleted(BasePermission):
    """Allows access only to non-deleted users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return not request.user.is_deleted()


class IsNotSuspended(BasePermission):
    """Allows access only to non-suspended users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return not request.user.is_suspended


class IsNotLocked(BasePermission):
    """Allows access only to non-locked users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return not request.user.is_locked


class IsSameUser(BasePermission):
    """Allows access only if user is accessing their own data."""
    def has_object_permission(self, request, view, obj):
        if isinstance(obj, User):
            return obj.id == request.user.id
        return getattr(obj, 'user', None) == request.user

    def has_permission(self, request, view):
        user_id = view.kwargs.get('user_id') or view.kwargs.get('pk')
        if not user_id:
            return True
        if not request.user or not request.user.is_authenticated:
            return False
        return str(request.user.id) == str(user_id)


class IsSameUserOrReadOnly(BasePermission):
    """Allows read for all, write only for the user themselves."""
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if isinstance(obj, User):
            return obj.id == request.user.id
        return getattr(obj, 'user', None) == request.user


class IsSameUserOrAdmin(BasePermission):
    """Allows access for user themselves or admin users."""
    def has_object_permission(self, request, view, obj):
        if isinstance(obj, User):
            return obj.id == request.user.id or request.user.is_staff
        return getattr(obj, 'user', None) == request.user or request.user.is_staff

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_staff:
            return True
        user_id = view.kwargs.get('user_id') or view.kwargs.get('pk')
        if user_id:
            return str(request.user.id) == str(user_id)
        return True


class IsSameUserOrSuperAdmin(BasePermission):
    """Allows access for user themselves or super admin users."""
    def has_object_permission(self, request, view, obj):
        if isinstance(obj, User):
            return obj.id == request.user.id or request.user.is_superuser
        return getattr(obj, 'user', None) == request.user or request.user.is_superuser

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        user_id = view.kwargs.get('user_id') or view.kwargs.get('pk')
        if user_id:
            return str(request.user.id) == str(user_id)
        return True


class IsAdminOrReadOnly(BasePermission):
    """Read for all, write only for admin users."""
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_staff


class IsSuperAdminOrReadOnly(BasePermission):
    """Read for all, write only for super admin users."""
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_superuser


class IsOwnerOrReadOnly(BasePermission):
    """Object-level read for all, write only for the owner."""
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if isinstance(obj, User):
            return obj.id == request.user.id
        return getattr(obj, 'user', None) == request.user


class IsOwnerOrAdmin(BasePermission):
    """Object-level access for owner or admin users."""
    def has_object_permission(self, request, view, obj):
        if isinstance(obj, User):
            return obj.id == request.user.id or request.user.is_staff
        return getattr(obj, 'user', None) == request.user or request.user.is_staff


class IsOwnerOrSuperAdmin(BasePermission):
    """Object-level access for owner or super admin users."""
    def has_object_permission(self, request, view, obj):
        if isinstance(obj, User):
            return obj.id == request.user.id or request.user.is_superuser
        return getattr(obj, 'user', None) == request.user or request.user.is_superuser


class IsActiveAndVerified(BasePermission):
    """Allows access only to active and verified users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        if request.user.is_locked:
            return False
        return request.user.is_active and request.user.is_verified


class IsVerifiedPhoneOrAdmin(BasePermission):
    """Allows access if phone verified or user is admin."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        return request.user.is_phone_verified or request.user.is_staff


class IsVerifiedEmailOrAdmin(BasePermission):
    """Allows access if email verified or user is admin."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        return request.user.is_email_verified or request.user.is_staff


class IsIdentityVerifiedOrAdmin(BasePermission):
    """Allows access if identity verified or user is admin."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        return request.user.is_identity_verified or request.user.is_staff


class HasMinimumReputation(BasePermission):
    """
    Allows access only if user has a minimum reputation score.
    View must define `reputation_threshold` attribute or use default 50.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        threshold = getattr(view, 'reputation_threshold', 50)
        return request.user.reputation_score >= threshold


class IsNotDefaulted(BasePermission):
    """Allows access only to users who haven't defaulted on contributions."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.defaulted_count < 3


class IsActiveAndPhoneVerified(BasePermission):
    """Allows access only to active and phone-verified users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        if request.user.is_locked:
            return False
        return request.user.is_active and request.user.is_phone_verified


class IsActiveAndEmailVerified(BasePermission):
    """Allows access only to active and email-verified users."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        if request.user.is_locked:
            return False
        return request.user.is_active and request.user.is_email_verified


class CanCreateGroup(BasePermission):
    """
    Allows access only to users who can create groups.
    Users must be active, verified, and have phone verified.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        if request.user.is_locked:
            return False
        if not request.user.is_active:
            return False
        if not request.user.is_phone_verified:
            return False
        return True


class CanJoinGroup(BasePermission):
    """
    Allows access only to users who can join groups.
    Users must be active and phone verified.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        if request.user.is_locked:
            return False
        if not request.user.is_active:
            return False
        if not request.user.is_phone_verified:
            return False
        return True


class CanContribute(BasePermission):
    """
    Allows access only to users who can make contributions.
    Users must be active, phone verified, and not defaulted.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_suspended:
            return False
        if request.user.is_locked:
            return False
        if not request.user.is_active:
            return False
        if not request.user.is_phone_verified:
            return False
        if request.user.defaulted_count >= 3:
            return False
        return True


class IsOwnerOrReadOnlyForObject(BasePermission):
    """Object-level permission for owner read/write, others read-only."""
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user_field = getattr(view, 'user_field', 'user')
        obj_user = getattr(obj, user_field, None)
        if obj_user is None:
            obj_user = getattr(obj, 'user_id', None)
        return obj_user == request.user