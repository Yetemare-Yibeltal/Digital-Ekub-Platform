"""
Permission classes for the admin panel app.

This module provides comprehensive permission classes for administrative operations:
- Role-based permissions (IsAdminUser, IsSuperAdmin)
- Action-specific permissions (CanManageUsers, CanManageGroups, etc.)
- Combined permissions for complex scenarios
- Object-level permissions for fine-grained access control
- Helper functions for permission checks
- Permission mixins for viewsets

All permission classes implement both has_permission and has_object_permission
where appropriate for fine-grained access control.

The permission system supports:
- Staff (admin) users with basic admin access
- Super admin users with full system access
- Permission-based access control for specific operations
- Object-level ownership checks for user-specific resources
"""

from rest_framework import permissions
from rest_framework.permissions import BasePermission, SAFE_METHODS
from django.shortcuts import get_object_or_404
from django.core.exceptions import PermissionDenied
from typing import Optional, Type, List, Union, Any

from apps.users.models import User
from apps.groups.models import Group
from apps.payments.models import Payment
from apps.contributions.models import Contribution
from apps.notifications.models import Notification

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_admin_user(user: User) -> bool:
    """
    Check if a user is an admin (staff or superuser).

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


def is_super_admin(user: User) -> bool:
    """
    Check if a user is a super admin.

    Args:
        user: User to check

    Returns:
        bool: True if user is superuser
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_deleted():
        return False
    return user.is_superuser


def has_permission(user: User, permission: str) -> bool:
    """
    Check if a user has a specific permission.
    This can be extended with a permission system.

    Args:
        user: User to check
        permission: Permission string (e.g., 'manage_users')

    Returns:
        bool: True if user has the permission
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_deleted():
        return False
    if user.is_superuser:
        return True
    # For now, staff users have all admin permissions
    if user.is_staff:
        return True
    # Could implement a custom permission model here
    return False


def is_owner_of_object(user: User, obj: Any) -> bool:
    """
    Check if a user is the owner of an object (for object-level permissions).

    Args:
        user: User to check
        obj: Object to check ownership

    Returns:
        bool: True if user is the owner
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_deleted():
        return False
    if user.is_superuser:
        return True
    # Check if object has a user, created_by, or owner attribute
    if hasattr(obj, 'user'):
        return obj.user == user
    if hasattr(obj, 'created_by'):
        return obj.created_by == user
    if hasattr(obj, 'owner'):
        return obj.owner == user
    return False


def is_related_to_user(user: User, obj: Any) -> bool:
    """
    Check if an object is related to a user (e.g., user's group, user's payment).

    Args:
        user: User to check
        obj: Object to check relationship

    Returns:
        bool: True if object is related to the user
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_deleted():
        return False
    if user.is_superuser:
        return True
    if hasattr(obj, 'user'):
        return obj.user == user
    if hasattr(obj, 'admin'):
        return obj.admin == user
    if hasattr(obj, 'generated_by'):
        return obj.generated_by == user
    if hasattr(obj, 'created_by'):
        return obj.created_by == user
    return False


# ============================================================================
# ROLE-BASED PERMISSIONS
# ============================================================================

class IsAdminUser(BasePermission):
    """
    Allows access only to admin users (staff or superuser).
    """
    message = _('You must be an admin to perform this action.')

    def has_permission(self, request, view):
        return is_admin_user(request.user)


class IsSuperAdmin(BasePermission):
    """
    Allows access only to super admin users.
    """
    message = _('Super admin access required for this operation.')

    def has_permission(self, request, view):
        return is_super_admin(request.user)


class IsAdminOrReadOnly(BasePermission):
    """
    Allows read-only access for all authenticated users, write access for admins.
    """
    message = _('Write access requires admin privileges.')

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return is_admin_user(request.user)


# ============================================================================
# PERMISSION-BASED PERMISSIONS
# ============================================================================

class CanViewDashboard(BasePermission):
    """
    Allows access only if user can view the admin dashboard.
    """
    message = _('You do not have permission to view the dashboard.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return is_admin_user(request.user)


class CanManageUsers(BasePermission):
    """
    Allows access only if user can manage users (suspend, activate, verify, delete, restore).
    """
    message = _('You do not have permission to manage users.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return has_permission(request.user, 'manage_users')


class CanManageGroups(BasePermission):
    """
    Allows access only if user can manage groups (approve, complete, cancel, pause, resume).
    """
    message = _('You do not have permission to manage groups.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return has_permission(request.user, 'manage_groups')


class CanManagePayments(BasePermission):
    """
    Allows access only if user can manage payments (manual process, refund, mark failed).
    """
    message = _('You do not have permission to manage payments.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return has_permission(request.user, 'manage_payments')


class CanManageContributions(BasePermission):
    """
    Allows access only if user can manage contributions (mark paid, refund, waive).
    """
    message = _('You do not have permission to manage contributions.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return has_permission(request.user, 'manage_contributions')


class CanBroadcastNotifications(BasePermission):
    """
    Allows access only if user can broadcast notifications to users or groups.
    """
    message = _('You do not have permission to broadcast notifications.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return has_permission(request.user, 'broadcast_notifications')


class CanViewReports(BasePermission):
    """
    Allows access only if user can view reports.
    """
    message = _('You do not have permission to view reports.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return has_permission(request.user, 'view_reports')


class CanGenerateReports(BasePermission):
    """
    Allows access only if user can generate reports.
    """
    message = _('You do not have permission to generate reports.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return has_permission(request.user, 'generate_reports')


class CanViewAuditLogs(BasePermission):
    """
    Allows access only if user can view audit logs.
    """
    message = _('You do not have permission to view audit logs.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return has_permission(request.user, 'view_audit_logs')


class CanManageSettings(BasePermission):
    """
    Allows access only if user can manage system settings.
    """
    message = _('You do not have permission to manage system settings.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return has_permission(request.user, 'manage_settings')


class CanManageSystem(BasePermission):
    """
    Allows access only if user can manage system (maintenance, health, etc.).
    """
    message = _('You do not have permission to manage the system.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return has_permission(request.user, 'manage_system')


class CanPerformBulkActions(BasePermission):
    """
    Allows access only if user can perform bulk actions on resources.
    """
    message = _('You do not have permission to perform bulk actions.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        return is_super_admin(request.user)


# ============================================================================
# OBJECT-LEVEL PERMISSIONS
# ============================================================================

class IsOwnerOfReport(BasePermission):
    """
    Allows access only to the owner of a report, or superadmin.
    """
    message = _('You must be the owner of this report to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        # For list and create, allow if admin
        if view.action in ['list', 'create']:
            return is_admin_user(request.user)
        # For other actions, check object permission
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return is_related_to_user(request.user, obj)


class IsOwnerOfReportSchedule(BasePermission):
    """
    Allows access only to the owner of a report schedule, or superadmin.
    """
    message = _('You must be the owner of this report schedule to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        if view.action in ['list', 'create']:
            return is_admin_user(request.user)
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return is_related_to_user(request.user, obj)


class IsOwnerOfDashboardWidget(BasePermission):
    """
    Allows access only to the owner of a dashboard widget, or superadmin.
    """
    message = _('You must be the owner of this widget to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        if view.action in ['list', 'create']:
            return is_admin_user(request.user)
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        if obj.is_system:
            return is_admin_user(request.user)
        return is_related_to_user(request.user, obj)


class IsOwnerOfAdminPreference(BasePermission):
    """
    Allows access only to the owner of admin preferences.
    """
    message = _('You can only access your own admin preferences.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_superuser:
            return True
        # For the preference view, the user is determined by request.user
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return obj.admin == request.user


# ============================================================================
# COMBINED PERMISSIONS
# ============================================================================

class OrAdminPermission(BasePermission):
    """
    Combined permission that allows if ANY of the given permissions allow.
    """
    def __init__(self, *perms: Type[BasePermission]):
        self.perms = perms

    def has_permission(self, request, view):
        return any(perm().has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        return any(perm().has_object_permission(request, view, obj) for perm in self.perms)


class AndAdminPermission(BasePermission):
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

# Admin or superuser
IsAdminOrSuper = OrAdminPermission(IsAdminUser, IsSuperAdmin)

# Admin and can manage users
CanManageUsersAdmin = AndAdminPermission(IsAdminUser, CanManageUsers)

# Admin and can manage groups
CanManageGroupsAdmin = AndAdminPermission(IsAdminUser, CanManageGroups)

# Admin and can manage payments
CanManagePaymentsAdmin = AndAdminPermission(IsAdminUser, CanManagePayments)

# Admin and can manage contributions
CanManageContributionsAdmin = AndAdminPermission(IsAdminUser, CanManageContributions)

# Admin and can broadcast notifications
CanBroadcastNotificationsAdmin = AndAdminPermission(IsAdminUser, CanBroadcastNotifications)

# Admin and can view reports
CanViewReportsAdmin = AndAdminPermission(IsAdminUser, CanViewReports)

# Admin and can generate reports
CanGenerateReportsAdmin = AndAdminPermission(IsAdminUser, CanGenerateReports)

# Admin and can view audit logs
CanViewAuditLogsAdmin = AndAdminPermission(IsAdminUser, CanViewAuditLogs)

# Admin and can manage settings
CanManageSettingsAdmin = AndAdminPermission(IsAdminUser, CanManageSettings)

# Admin and can manage system
CanManageSystemAdmin = AndAdminPermission(IsAdminUser, CanManageSystem)

# Superadmin and can perform bulk actions
CanPerformBulkActionsSuper = AndAdminPermission(IsSuperAdmin, CanPerformBulkActions)

# Owner or admin
IsOwnerOrAdmin = OrAdminPermission(IsOwnerOfReport, IsAdminUser)


# ============================================================================
# PERMISSION MIXINS FOR VIEWSETS
# ============================================================================

class AdminPermissionsMixin:
    """
    Mixin for admin viewsets to automatically apply appropriate permissions
    based on the action being performed.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsAdminUser, CanViewDashboard],
        'retrieve': [IsAuthenticated, IsAdminUser, CanViewDashboard],
        'create': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'update': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'partial_update': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'destroy': [IsAuthenticated, IsAdminUser, CanManageSettings],
    }

    def get_permissions(self):
        """
        Get permissions based on the current action.
        """
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated, IsAdminUser]
        )
        return [permission() for permission in permission_classes]


class ReportPermissionsMixin:
    """
    Mixin for report viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsAdminUser, CanViewReports],
        'retrieve': [IsAuthenticated, IsAdminUser, CanViewReports],
        'create': [IsAuthenticated, IsAdminUser, CanGenerateReports],
        'update': [IsAuthenticated, IsAdminUser, CanGenerateReports],
        'partial_update': [IsAuthenticated, IsAdminUser, CanGenerateReports],
        'destroy': [IsAuthenticated, IsAdminUser, CanGenerateReports],
        'download': [IsAuthenticated, IsAdminUser, CanViewReports],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated, IsAdminUser]
        )
        return [permission() for permission in permission_classes]


class ReportSchedulePermissionsMixin:
    """
    Mixin for report schedule viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsAdminUser, CanViewReports],
        'retrieve': [IsAuthenticated, IsAdminUser, CanViewReports],
        'create': [IsAuthenticated, IsAdminUser, CanGenerateReports],
        'update': [IsAuthenticated, IsAdminUser, CanGenerateReports],
        'partial_update': [IsAuthenticated, IsAdminUser, CanGenerateReports],
        'destroy': [IsAuthenticated, IsAdminUser, CanGenerateReports],
        'run_now': [IsAuthenticated, IsAdminUser, CanGenerateReports],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated, IsAdminUser]
        )
        return [permission() for permission in permission_classes]


class SystemSettingPermissionsMixin:
    """
    Mixin for system setting viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'retrieve': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'create': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'update': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'partial_update': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'destroy': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'bulk_update': [IsAuthenticated, IsAdminUser, CanManageSettings],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated, IsAdminUser]
        )
        return [permission() for permission in permission_classes]


class AuditPermissionsMixin:
    """
    Mixin for audit viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsAdminUser, CanViewAuditLogs],
        'retrieve': [IsAuthenticated, IsAdminUser, CanViewAuditLogs],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated, IsAdminUser]
        )
        return [permission() for permission in permission_classes]


class WidgetPermissionsMixin:
    """
    Mixin for dashboard widget viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsAdminUser, CanViewDashboard],
        'retrieve': [IsAuthenticated, IsAdminUser, CanViewDashboard],
        'create': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'update': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'partial_update': [IsAuthenticated, IsAdminUser, CanManageSettings],
        'destroy': [IsAuthenticated, IsAdminUser, CanManageSettings],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated, IsAdminUser]
        )
        return [permission() for permission in permission_classes]


# ============================================================================
# CUSTOM DECORATORS
# ============================================================================

def admin_required(view_func):
    """
    Decorator to require admin access for a view function.
    """
    from functools import wraps
    from django.http import JsonResponse

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_admin_user(request.user):
            return JsonResponse(
                {'error': 'Admin access required.'},
                status=403
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def super_admin_required(view_func):
    """
    Decorator to require super admin access for a view function.
    """
    from functools import wraps
    from django.http import JsonResponse

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_super_admin(request.user):
            return JsonResponse(
                {'error': 'Super admin access required.'},
                status=403
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def permission_required(permission: str):
    """
    Decorator to require a specific permission for a view function.
    """
    from functools import wraps
    from django.http import JsonResponse

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not has_permission(request.user, permission):
                return JsonResponse(
                    {'error': f'Permission {permission} required.'},
                    status=403
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# ============================================================================
# PERMISSION REGISTRY (for dynamic permission checks)
# ============================================================================

class PermissionRegistry:
    """
    Registry for managing admin permissions.
    This can be extended to add custom permissions dynamically.
    """
    _permissions = {
        'view_dashboard': CanViewDashboard,
        'manage_users': CanManageUsers,
        'manage_groups': CanManageGroups,
        'manage_payments': CanManagePayments,
        'manage_contributions': CanManageContributions,
        'broadcast_notifications': CanBroadcastNotifications,
        'view_reports': CanViewReports,
        'generate_reports': CanGenerateReports,
        'view_audit_logs': CanViewAuditLogs,
        'manage_settings': CanManageSettings,
        'manage_system': CanManageSystem,
        'perform_bulk_actions': CanPerformBulkActions,
    }

    @classmethod
    def get_permission(cls, name: str) -> Optional[Type[BasePermission]]:
        """
        Get a permission class by name.

        Args:
            name: Permission name

        Returns:
            Permission class or None
        """
        return cls._permissions.get(name)

    @classmethod
    def register(cls, name: str, permission_class: Type[BasePermission]) -> None:
        """
        Register a new permission.

        Args:
            name: Permission name
            permission_class: Permission class
        """
        cls._permissions[name] = permission_class

    @classmethod
    def list_permissions(cls) -> List[str]:
        """
        List all registered permission names.

        Returns:
            List of permission names
        """
        return list(cls._permissions.keys())

    @classmethod
    def check_permission(cls, user: User, permission: str) -> bool:
        """
        Check if a user has a specific permission using the registry.

        Args:
            user: User to check
            permission: Permission name

        Returns:
            bool: True if user has the permission
        """
        perm_class = cls.get_permission(permission)
        if not perm_class:
            return False
        return perm_class().has_permission(None, None)  # Placeholder request/view


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Helper functions
    'is_admin_user',
    'is_super_admin',
    'has_permission',
    'is_owner_of_object',
    'is_related_to_user',

    # Role-based permissions
    'IsAdminUser',
    'IsSuperAdmin',
    'IsAdminOrReadOnly',

    # Permission-based permissions
    'CanViewDashboard',
    'CanManageUsers',
    'CanManageGroups',
    'CanManagePayments',
    'CanManageContributions',
    'CanBroadcastNotifications',
    'CanViewReports',
    'CanGenerateReports',
    'CanViewAuditLogs',
    'CanManageSettings',
    'CanManageSystem',
    'CanPerformBulkActions',

    # Object-level permissions
    'IsOwnerOfReport',
    'IsOwnerOfReportSchedule',
    'IsOwnerOfDashboardWidget',
    'IsOwnerOfAdminPreference',

    # Combined permissions
    'OrAdminPermission',
    'AndAdminPermission',

    # Pre-defined combined permissions
    'IsAdminOrSuper',
    'CanManageUsersAdmin',
    'CanManageGroupsAdmin',
    'CanManagePaymentsAdmin',
    'CanManageContributionsAdmin',
    'CanBroadcastNotificationsAdmin',
    'CanViewReportsAdmin',
    'CanGenerateReportsAdmin',
    'CanViewAuditLogsAdmin',
    'CanManageSettingsAdmin',
    'CanManageSystemAdmin',
    'CanPerformBulkActionsSuper',
    'IsOwnerOrAdmin',

    # Mixins
    'AdminPermissionsMixin',
    'ReportPermissionsMixin',
    'ReportSchedulePermissionsMixin',
    'SystemSettingPermissionsMixin',
    'AuditPermissionsMixin',
    'WidgetPermissionsMixin',

    # Decorators
    'admin_required',
    'super_admin_required',
    'permission_required',

    # Registry
    'PermissionRegistry',
]