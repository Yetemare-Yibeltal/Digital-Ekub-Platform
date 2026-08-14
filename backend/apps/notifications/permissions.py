"""
Permission classes for the notifications app.

This module provides comprehensive permission classes for notification operations:
- Notification ownership checks (IsNotificationOwner)
- Notification admin checks (IsAdminNotification)
- Action-specific permissions (CanViewNotification, CanCreateNotification, CanUpdateNotification, CanDeleteNotification, CanSendNotification)
- Template-specific permissions (CanManageTemplates)
- Preference-specific permissions (CanManagePreferences)
- Statistics permissions (CanViewStats)
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
from apps.common.constants import NotificationType, NotificationPriority

from .models import Notification, NotificationTemplate, NotificationPreference


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_notification_owner(user: User, notification: Notification) -> bool:
    """
    Check if a user is the owner of a notification.

    Args:
        user: User to check
        notification: Notification to check

    Returns:
        bool: True if user is the owner
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    if not notification:
        return False
    return notification.user == user


def is_notification_admin(user: User) -> bool:
    """
    Check if a user is an admin for notification operations.

    Args:
        user: User to check

    Returns:
        bool: True if user is staff or superuser
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_deleted():
        return False
    return user.is_staff or user.is_superuser


def is_template_manager(user: User) -> bool:
    """
    Check if a user can manage notification templates.

    Args:
        user: User to check

    Returns:
        bool: True if user can manage templates
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_deleted():
        return False
    return user.is_superuser


def is_preference_owner(user: User, preference: NotificationPreference) -> bool:
    """
    Check if a user is the owner of a notification preference.

    Args:
        user: User to check
        preference: NotificationPreference to check

    Returns:
        bool: True if user is the owner
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_deleted():
        return False
    if not preference:
        return False
    return preference.user == user


def get_notification_from_view(view) -> Optional[Notification]:
    """
    Extract notification from view kwargs.

    Args:
        view: DRF view instance

    Returns:
        Notification instance or None
    """
    notification_id = view.kwargs.get('notification_id') or view.kwargs.get('pk')
    if not notification_id:
        if hasattr(view, 'request') and hasattr(view.request, 'data'):
            notification_id = view.request.data.get('notification_id') or view.request.data.get('notification')
        if not notification_id:
            return None
    try:
        return Notification.objects.get(id=notification_id, deleted_at__isnull=True)
    except Notification.DoesNotExist:
        return None


def get_notification_from_object(obj) -> Optional[Notification]:
    """
    Extract notification from an object.

    Args:
        obj: Object to extract notification from

    Returns:
        Notification instance or None
    """
    if hasattr(obj, 'notification'):
        return obj.notification
    if isinstance(obj, Notification):
        return obj
    if hasattr(obj, 'notification_id'):
        try:
            return Notification.objects.get(id=obj.notification_id, deleted_at__isnull=True)
        except Notification.DoesNotExist:
            return None
    return None


def get_preference_from_view(view) -> Optional[NotificationPreference]:
    """
    Extract notification preference from view kwargs.

    Args:
        view: DRF view instance

    Returns:
        NotificationPreference instance or None
    """
    pref_id = view.kwargs.get('preference_id') or view.kwargs.get('pk')
    if not pref_id:
        return None
    try:
        return NotificationPreference.objects.get(id=pref_id)
    except NotificationPreference.DoesNotExist:
        return None


def get_preference_from_object(obj) -> Optional[NotificationPreference]:
    """
    Extract notification preference from an object.

    Args:
        obj: Object to extract preference from

    Returns:
        NotificationPreference instance or None
    """
    if isinstance(obj, NotificationPreference):
        return obj
    if hasattr(obj, 'preference'):
        return obj.preference
    if hasattr(obj, 'preference_id'):
        try:
            return NotificationPreference.objects.get(id=obj.preference_id)
        except NotificationPreference.DoesNotExist:
            return None
    return None


# ============================================================================
# BASE NOTIFICATION PERMISSIONS
# ============================================================================

class IsNotificationOwner(BasePermission):
    """
    Allows access only to the owner of the notification.
    """
    message = _('You must be the owner of this notification to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_view(view)
        if not notification:
            # If no notification found, allow if user is superuser
            return request.user.is_superuser

        return is_notification_owner(request.user, notification)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_object(obj)
        if not notification:
            return False

        return is_notification_owner(request.user, notification)


class IsAdminNotification(BasePermission):
    """
    Allows access only to admin users (staff or superuser).
    """
    message = _('Admin access required for this operation.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_staff or request.user.is_superuser

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return request.user.is_staff


class IsAdminNotificationOrOwner(BasePermission):
    """
    Allows access if user is admin or the notification owner.
    """
    message = _('You must be an admin or the owner of this notification.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_view(view)
        if not notification:
            return request.user.is_staff

        return is_notification_owner(request.user, notification) or request.user.is_staff

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_object(obj)
        if not notification:
            return False

        return is_notification_owner(request.user, notification) or request.user.is_staff


# ============================================================================
# NOTIFICATION ACTION-SPECIFIC PERMISSIONS
# ============================================================================

class CanViewNotification(BasePermission):
    """
    Allows access only if user can view the notification.
    Checks: user is the owner, or admin/superuser.
    """
    message = _('You do not have permission to view this notification.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_view(view)
        if not notification:
            return True

        return is_notification_owner(request.user, notification) or request.user.is_staff

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_object(obj)
        if not notification:
            return False

        return is_notification_owner(request.user, notification) or request.user.is_staff


class CanCreateNotification(BasePermission):
    """
    Allows access only if user can create a notification.
    Checks: user is authenticated.
    """
    message = _('You must be authenticated to create a notification.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return True


class CanUpdateNotification(BasePermission):
    """
    Allows access only if user can update a notification.
    Checks: user is owner or admin/superuser.
    """
    message = _('You do not have permission to update this notification.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_view(view)
        if not notification:
            return False

        return is_notification_owner(request.user, notification) or request.user.is_staff

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_object(obj)
        if not notification:
            return False

        return is_notification_owner(request.user, notification) or request.user.is_staff


class CanDeleteNotification(BasePermission):
    """
    Allows access only if user can delete a notification.
    Checks: user is owner or admin/superuser.
    """
    message = _('You do not have permission to delete this notification.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_view(view)
        if not notification:
            return False

        return is_notification_owner(request.user, notification) or request.user.is_staff

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_object(obj)
        if not notification:
            return False

        return is_notification_owner(request.user, notification) or request.user.is_staff


class CanSendNotification(BasePermission):
    """
    Allows access only if user can send notifications.
    Checks: user is staff or superuser.
    """
    message = _('You do not have permission to send notifications.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_staff or request.user.is_superuser


class CanMarkRead(BasePermission):
    """
    Allows access only if user can mark a notification as read.
    Checks: user is the notification owner.
    """
    message = _('You do not have permission to mark this notification as read.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_view(view)
        if not notification:
            return False

        return is_notification_owner(request.user, notification)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        notification = get_notification_from_object(obj)
        if not notification:
            return False

        return is_notification_owner(request.user, notification)


class CanMarkAllRead(BasePermission):
    """
    Allows access only if user can mark all notifications as read.
    Checks: user is authenticated (current user only).
    """
    message = _('You do not have permission to mark all notifications as read.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return True


class CanClearAll(BasePermission):
    """
    Allows access only if user can clear all notifications.
    Checks: user is authenticated (current user only).
    """
    message = _('You do not have permission to clear all notifications.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return True


# ============================================================================
# TEMPLATE PERMISSIONS
# ============================================================================

class CanManageTemplates(BasePermission):
    """
    Allows access only if user can manage notification templates.
    Checks: user is superuser.
    """
    message = _('You do not have permission to manage notification templates.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_superuser

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return False


class CanViewTemplates(BasePermission):
    """
    Allows access only if user can view notification templates.
    Checks: user is authenticated.
    """
    message = _('You do not have permission to view notification templates.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return True


# ============================================================================
# PREFERENCE PERMISSIONS
# ============================================================================

class IsPreferenceOwner(BasePermission):
    """
    Allows access only to the owner of the notification preference.
    """
    message = _('You must be the owner of these preferences to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        preference = get_preference_from_view(view)
        if not preference:
            # If no preference found, allow if user is superuser
            return request.user.is_superuser

        return is_preference_owner(request.user, preference)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        preference = get_preference_from_object(obj)
        if not preference:
            return False

        return is_preference_owner(request.user, preference)


class CanManagePreferences(BasePermission):
    """
    Allows access only if user can manage notification preferences.
    Checks: user is the owner or superuser.
    """
    message = _('You do not have permission to manage these preferences.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        preference = get_preference_from_view(view)
        if not preference:
            return True

        return is_preference_owner(request.user, preference)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        preference = get_preference_from_object(obj)
        if not preference:
            return False

        return is_preference_owner(request.user, preference)


class CanUpdateOwnPreferences(BasePermission):
    """
    Allows access only if user is updating their own preferences.
    """
    message = _('You can only update your own preferences.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        # For the "me" endpoint, allow
        if view.action == 'update_me':
            return True

        preference = get_preference_from_view(view)
        if not preference:
            return True

        return is_preference_owner(request.user, preference)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False

        preference = get_preference_from_object(obj)
        if not preference:
            return False

        return is_preference_owner(request.user, preference)


# ============================================================================
# CHANNEL PERMISSIONS
# ============================================================================

class CanManageChannels(BasePermission):
    """
    Allows access only if user can manage notification channels.
    Checks: user is superuser.
    """
    message = _('You do not have permission to manage notification channels.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_superuser

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return False


# ============================================================================
# STATISTICS PERMISSIONS
# ============================================================================

class CanViewStats(BasePermission):
    """
    Allows access only if user can view notification statistics.
    Checks: user is superuser.
    """
    message = _('You do not have permission to view notification statistics.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_superuser


# ============================================================================
# EVENT PERMISSIONS
# ============================================================================

class CanManageEvents(BasePermission):
    """
    Allows access only if user can manage notification events.
    Checks: user is superuser.
    """
    message = _('You do not have permission to manage notification events.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_superuser

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return False


class CanViewEvents(BasePermission):
    """
    Allows access only if user can view notification events.
    Checks: user is authenticated.
    """
    message = _('You do not have permission to view notification events.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return True


class CanCreateEvent(BasePermission):
    """
    Allows access only if user can create a notification event.
    Checks: user is authenticated.
    """
    message = _('You do not have permission to create notification events.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return True


# ============================================================================
# SCHEDULE PERMISSIONS
# ============================================================================

class CanManageSchedules(BasePermission):
    """
    Allows access only if user can manage notification schedules.
    Checks: user is superuser.
    """
    message = _('You do not have permission to manage notification schedules.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_superuser

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return False


class CanViewSchedules(BasePermission):
    """
    Allows access only if user can view notification schedules.
    Checks: user is authenticated.
    """
    message = _('You do not have permission to view notification schedules.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return True


class CanCreateSchedule(BasePermission):
    """
    Allows access only if user can create a notification schedule.
    Checks: user has CanSendNotification permission.
    """
    message = _('You do not have permission to create notification schedules.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_staff or request.user.is_superuser


# ============================================================================
# DIGEST PERMISSIONS
# ============================================================================

class CanViewDigests(BasePermission):
    """
    Allows access only if user can view notification digests.
    Checks: user is authenticated.
    """
    message = _('You do not have permission to view notification digests.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return True


class CanSendDigest(BasePermission):
    """
    Allows access only if user can send a digest.
    Checks: user is superuser.
    """
    message = _('You do not have permission to send notification digests.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_superuser

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return False


# ============================================================================
# AUDIT PERMISSIONS
# ============================================================================

class CanViewAudits(BasePermission):
    """
    Allows access only if user can view notification audits.
    Checks: user is authenticated.
    """
    message = _('You do not have permission to view notification audits.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return True


# ============================================================================
# BULK NOTIFICATION PERMISSIONS
# ============================================================================

class CanSendBulkNotifications(BasePermission):
    """
    Allows access only if user can send bulk notifications.
    Checks: user is superuser.
    """
    message = _('You do not have permission to send bulk notifications.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return request.user.is_superuser


# ============================================================================
# COMBINED PERMISSIONS
# ============================================================================

class OrNotificationPermission(BasePermission):
    """
    Combined permission that allows if ANY of the given permissions allow.
    """
    def __init__(self, *perms: Type[BasePermission]):
        self.perms = perms

    def has_permission(self, request, view):
        return any(perm().has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        return any(perm().has_object_permission(request, view, obj) for perm in self.perms)


class AndNotificationPermission(BasePermission):
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
# PRE-DEFINED COMBINED NOTIFICATION PERMISSIONS
# ============================================================================

# Owner or admin
IsNotificationOwnerOrAdmin = OrNotificationPermission(IsNotificationOwner, IsAdminNotification)

# Active owner with permission to view
CanViewNotificationActive = AndNotificationPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    CanViewNotification
)

# Active admin with permission to send
CanSendNotificationActive = AndNotificationPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    CanSendNotification
)

# Can view (owner or admin)
CanViewNotificationCombined = OrNotificationPermission(
    IsNotificationOwner,
    IsAdminNotification
)

# Can manage (owner or admin)
CanManageNotificationCombined = OrNotificationPermission(
    IsNotificationOwner,
    IsAdminNotification
)

# Can update (owner or admin)
CanUpdateNotificationCombined = OrNotificationPermission(
    IsNotificationOwner,
    IsAdminNotification
)

# Can delete (owner or admin) - soft delete only
CanDeleteNotificationCombined = OrNotificationPermission(
    IsNotificationOwner,
    IsAdminNotification
)

# Can mark read (owner only)
CanMarkReadCombined = AndNotificationPermission(
    IsNotificationOwner,
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted
)

# Can manage templates (superuser only)
CanManageTemplatesCombined = AndNotificationPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    CanManageTemplates
)

# Can manage preferences (owner only)
CanManagePreferencesCombined = AndNotificationPermission(
    IsPreferenceOwner,
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted
)

# Can view stats (superuser only)
CanViewStatsCombined = AndNotificationPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    CanViewStats
)

# Can send bulk notifications (superuser only)
CanSendBulkCombined = AndNotificationPermission(
    IsActive,
    IsNotSuspended,
    IsNotLocked,
    IsNotDeleted,
    CanSendBulkNotifications
)


# ============================================================================
# PERMISSION MIXIN FOR NOTIFICATION VIEWSETS
# ============================================================================

class NotificationPermissionsMixin:
    """
    Mixin for notification viewsets to automatically apply appropriate permissions
    based on the action being performed.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, CanViewNotification],
        'retrieve': [IsAuthenticated, CanViewNotification],
        'create': [IsAuthenticated, CanCreateNotification],
        'update': [IsAuthenticated, CanUpdateNotification],
        'partial_update': [IsAuthenticated, CanUpdateNotification],
        'destroy': [IsAuthenticated, CanDeleteNotification],
        'mark_read': [IsAuthenticated, CanMarkRead],
        'mark_unread': [IsAuthenticated, CanMarkRead],
        'mark_all_read': [IsAuthenticated, CanMarkAllRead],
        'clear_all': [IsAuthenticated, CanClearAll],
        'stats': [IsAuthenticated, CanViewStats],
        'deliveries': [IsAuthenticated, IsNotificationOwner],
        'unread': [IsAuthenticated],
        'unread_count': [IsAuthenticated],
        'send': [IsAuthenticated, CanSendNotification],
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


class TemplatePermissionsMixin:
    """
    Mixin for template viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, CanViewTemplates],
        'retrieve': [IsAuthenticated, CanViewTemplates],
        'create': [IsAuthenticated, CanManageTemplates],
        'update': [IsAuthenticated, CanManageTemplates],
        'partial_update': [IsAuthenticated, CanManageTemplates],
        'destroy': [IsAuthenticated, CanManageTemplates],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated]
        )
        return [permission() for permission in permission_classes]


class PreferencePermissionsMixin:
    """
    Mixin for preference viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsPreferenceOwner],
        'retrieve': [IsAuthenticated, IsPreferenceOwner],
        'create': [IsAuthenticated, IsPreferenceOwner],
        'update': [IsAuthenticated, IsPreferenceOwner],
        'partial_update': [IsAuthenticated, IsPreferenceOwner],
        'destroy': [IsAuthenticated, IsPreferenceOwner],
        'me': [IsAuthenticated],
        'update_me': [IsAuthenticated],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated]
        )
        return [permission() for permission in permission_classes]


class ChannelPermissionsMixin:
    """
    Mixin for channel viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, CanManageChannels],
        'retrieve': [IsAuthenticated, CanManageChannels],
        'create': [IsAuthenticated, CanManageChannels],
        'update': [IsAuthenticated, CanManageChannels],
        'partial_update': [IsAuthenticated, CanManageChannels],
        'destroy': [IsAuthenticated, CanManageChannels],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated]
        )
        return [permission() for permission in permission_classes]


class EventPermissionsMixin:
    """
    Mixin for event viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, CanViewEvents],
        'retrieve': [IsAuthenticated, CanViewEvents],
        'create': [IsAuthenticated, CanCreateEvent],
        'update': [IsAuthenticated, CanManageEvents],
        'partial_update': [IsAuthenticated, CanManageEvents],
        'destroy': [IsAuthenticated, CanManageEvents],
        'process': [IsAuthenticated],
        'retry': [IsAuthenticated],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated]
        )
        return [permission() for permission in permission_classes]


class SchedulePermissionsMixin:
    """
    Mixin for schedule viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, CanViewSchedules],
        'retrieve': [IsAuthenticated, CanViewSchedules],
        'create': [IsAuthenticated, CanCreateSchedule],
        'update': [IsAuthenticated, CanManageSchedules],
        'partial_update': [IsAuthenticated, CanManageSchedules],
        'destroy': [IsAuthenticated, CanManageSchedules],
        'execute': [IsAuthenticated],
        'cancel': [IsAuthenticated],
        'reschedule': [IsAuthenticated],
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
    'is_notification_owner',
    'is_notification_admin',
    'is_template_manager',
    'is_preference_owner',
    'get_notification_from_view',
    'get_notification_from_object',
    'get_preference_from_view',
    'get_preference_from_object',

    # Base permissions
    'IsNotificationOwner',
    'IsAdminNotification',
    'IsAdminNotificationOrOwner',

    # Action-specific permissions
    'CanViewNotification',
    'CanCreateNotification',
    'CanUpdateNotification',
    'CanDeleteNotification',
    'CanSendNotification',
    'CanMarkRead',
    'CanMarkAllRead',
    'CanClearAll',

    # Template permissions
    'CanManageTemplates',
    'CanViewTemplates',

    # Preference permissions
    'IsPreferenceOwner',
    'CanManagePreferences',
    'CanUpdateOwnPreferences',

    # Channel permissions
    'CanManageChannels',

    # Statistics permissions
    'CanViewStats',

    # Event permissions
    'CanManageEvents',
    'CanViewEvents',
    'CanCreateEvent',

    # Schedule permissions
    'CanManageSchedules',
    'CanViewSchedules',
    'CanCreateSchedule',

    # Digest permissions
    'CanViewDigests',
    'CanSendDigest',

    # Audit permissions
    'CanViewAudits',

    # Bulk permissions
    'CanSendBulkNotifications',

    # Combined permissions
    'OrNotificationPermission',
    'AndNotificationPermission',

    # Pre-defined combined permissions
    'IsNotificationOwnerOrAdmin',
    'CanViewNotificationActive',
    'CanSendNotificationActive',
    'CanViewNotificationCombined',
    'CanManageNotificationCombined',
    'CanUpdateNotificationCombined',
    'CanDeleteNotificationCombined',
    'CanMarkReadCombined',
    'CanManageTemplatesCombined',
    'CanManagePreferencesCombined',
    'CanViewStatsCombined',
    'CanSendBulkCombined',

    # Mixins
    'NotificationPermissionsMixin',
    'TemplatePermissionsMixin',
    'PreferencePermissionsMixin',
    'ChannelPermissionsMixin',
    'EventPermissionsMixin',
    'SchedulePermissionsMixin',
]