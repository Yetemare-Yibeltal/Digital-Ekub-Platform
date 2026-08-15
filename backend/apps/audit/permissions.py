"""
Permission classes for the audit app.

This module provides comprehensive permission classes for audit operations:
- Role-based permissions (IsAuditor, IsSecurityAdmin, IsSystemAdmin)
- Action-specific permissions (CanViewAuditLogs, CanManageAuditRules, etc.)
- Combined permissions for complex scenarios
- Object-level permissions for fine-grained access control
- Helper functions for permission checks
- Permission mixins for viewsets

All permission classes implement both has_permission and has_object_permission
where appropriate for fine-grained access control.

The permission system supports:
- Auditors who can view logs and reports
- Security admins who can manage security events
- System admins who can manage health and metrics
- Super admins with full access
- Object-level ownership for user-specific resources
"""

from rest_framework import permissions
from rest_framework.permissions import BasePermission, SAFE_METHODS
from django.shortcuts import get_object_or_404
from django.core.exceptions import PermissionDenied
from typing import Optional, Type, List, Union, Any
from django.contrib.auth.models import Permission as DjangoPermission
from django.contrib.contenttypes.models import ContentType

from apps.users.models import User
from apps.common.permissions import IsAdminUser, IsSuperAdminUser, IsActiveUser, IsNotDeleted

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_auditor(user: User) -> bool:
    """
    Check if a user is an auditor (can view audit logs and reports).

    Args:
        user: User to check

    Returns:
        bool: True if user is an auditor
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_deleted():
        return False
    if user.is_superuser:
        return True
    if user.is_staff:
        return True
    # Check for specific audit permission
    return user.has_perm('audit.view_auditlog') or user.has_perm('audit.can_view_audit')


def is_security_admin(user: User) -> bool:
    """
    Check if a user is a security admin (can view and manage security events).

    Args:
        user: User to check

    Returns:
        bool: True if user is a security admin
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_deleted():
        return False
    if user.is_superuser:
        return True
    if user.is_staff:
        return True
    return user.has_perm('audit.can_manage_security_events')


def is_system_admin(user: User) -> bool:
    """
    Check if a user is a system admin (can manage system health and performance).

    Args:
        user: User to check

    Returns:
        bool: True if user is a system admin
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_deleted():
        return False
    if user.is_superuser:
        return True
    if user.is_staff:
        return True
    return user.has_perm('audit.can_manage_system_health')


def is_anomaly_manager(user: User) -> bool:
    """
    Check if a user can manage anomaly detections.

    Args:
        user: User to check

    Returns:
        bool: True if user can manage anomalies
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_deleted():
        return False
    if user.is_superuser:
        return True
    if user.is_staff:
        return True
    return user.has_perm('audit.can_manage_anomalies')


def has_audit_permission(user: User, permission: str) -> bool:
    """
    Check if a user has a specific audit permission.

    Args:
        user: User to check
        permission: Permission string (e.g., 'view_audit_logs')

    Returns:
        bool: True if user has the permission
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_deleted():
        return False
    if user.is_superuser:
        return True
    if user.is_staff:
        return True
    # Map permission to Django permission
    permission_map = {
        'view_audit_logs': ('audit', 'view_auditlog'),
        'manage_audit_rules': ('audit', 'change_auditrule'),
        'manage_audit_alerts': ('audit', 'change_auditalert'),
        'generate_audit_reports': ('audit', 'add_auditreport'),
        'view_security_events': ('audit', 'view_securityevent'),
        'view_system_health': ('audit', 'view_systemhealth'),
        'view_performance_metrics': ('audit', 'view_performancemetric'),
        'manage_anomalies': ('audit', 'change_anomalydetection'),
    }
    app_label, codename = permission_map.get(permission, (None, None))
    if app_label and codename:
        return user.has_perm(f'{app_label}.{codename}')
    return False


def is_owner_of_audit_object(user: User, obj: Any) -> bool:
    """
    Check if a user is the owner of an audit object.

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
    # Check if object has a user, generated_by, or created_by attribute
    if hasattr(obj, 'user') and obj.user:
        return obj.user == user
    if hasattr(obj, 'generated_by') and obj.generated_by:
        return obj.generated_by == user
    if hasattr(obj, 'created_by') and obj.created_by:
        return obj.created_by == user
    if hasattr(obj, 'admin') and obj.admin:
        return obj.admin == user
    if hasattr(obj, 'acknowledged_by') and obj.acknowledged_by:
        return obj.acknowledged_by == user
    return False


# ============================================================================
# ROLE-BASED PERMISSIONS
# ============================================================================

class IsAuditor(BasePermission):
    """
    Allows access only to users with auditor role.
    """
    message = _('Auditor access required for this operation.')

    def has_permission(self, request, view):
        return is_auditor(request.user)

    def has_object_permission(self, request, view, obj):
        return is_auditor(request.user)


class IsSecurityAdmin(BasePermission):
    """
    Allows access only to security admin users.
    """
    message = _('Security admin access required for this operation.')

    def has_permission(self, request, view):
        return is_security_admin(request.user)

    def has_object_permission(self, request, view, obj):
        return is_security_admin(request.user)


class IsSystemAdmin(BasePermission):
    """
    Allows access only to system admin users.
    """
    message = _('System admin access required for this operation.')

    def has_permission(self, request, view):
        return is_system_admin(request.user)

    def has_object_permission(self, request, view, obj):
        return is_system_admin(request.user)


class IsAnomalyManager(BasePermission):
    """
    Allows access only to users who can manage anomalies.
    """
    message = _('Anomaly management access required for this operation.')

    def has_permission(self, request, view):
        return is_anomaly_manager(request.user)

    def has_object_permission(self, request, view, obj):
        return is_anomaly_manager(request.user)


# ============================================================================
# PERMISSION-BASED PERMISSIONS
# ============================================================================

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
        if request.user.is_superuser:
            return True
        if request.user.is_staff:
            return True
        return has_audit_permission(request.user, 'view_audit_logs')


class CanManageAuditRules(BasePermission):
    """
    Allows access only if user can manage audit rules.
    """
    message = _('You do not have permission to manage audit rules.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_superuser:
            return True
        return has_audit_permission(request.user, 'manage_audit_rules')

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        return has_audit_permission(request.user, 'manage_audit_rules')


class CanManageAuditAlerts(BasePermission):
    """
    Allows access only if user can manage audit alerts.
    """
    message = _('You do not have permission to manage audit alerts.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_superuser:
            return True
        return has_audit_permission(request.user, 'manage_audit_alerts')

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        return has_audit_permission(request.user, 'manage_audit_alerts')


class CanGenerateAuditReports(BasePermission):
    """
    Allows access only if user can generate audit reports.
    """
    message = _('You do not have permission to generate audit reports.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_superuser:
            return True
        return has_audit_permission(request.user, 'generate_audit_reports')

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        return has_audit_permission(request.user, 'generate_audit_reports')


class CanViewSecurityEvents(BasePermission):
    """
    Allows access only if user can view security events.
    """
    message = _('You do not have permission to view security events.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_superuser:
            return True
        return has_audit_permission(request.user, 'view_security_events')


class CanViewSystemHealth(BasePermission):
    """
    Allows access only if user can view system health.
    """
    message = _('You do not have permission to view system health.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_superuser:
            return True
        return has_audit_permission(request.user, 'view_system_health')


class CanViewPerformanceMetrics(BasePermission):
    """
    Allows access only if user can view performance metrics.
    """
    message = _('You do not have permission to view performance metrics.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_superuser:
            return True
        return has_audit_permission(request.user, 'view_performance_metrics')


class CanManageAnomalies(BasePermission):
    """
    Allows access only if user can manage anomalies.
    """
    message = _('You do not have permission to manage anomalies.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.user.is_superuser:
            return True
        return has_audit_permission(request.user, 'manage_anomalies')

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        return has_audit_permission(request.user, 'manage_anomalies')


# ============================================================================
# OBJECT-LEVEL PERMISSIONS
# ============================================================================

class IsOwnerOfAuditObject(BasePermission):
    """
    Allows access only to the owner of an audit object.
    """
    message = _('You must be the owner of this resource to perform this action.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        # For list and create, allow if user has appropriate permissions
        if view.action in ['list', 'create']:
            return is_auditor(request.user) or is_system_admin(request.user)
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return is_owner_of_audit_object(request.user, obj)


class IsOwnerOrAuditor(BasePermission):
    """
    Allows access to the owner or an auditor.
    """
    message = _('You must be the owner or an auditor to access this resource.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        if view.action in ['list', 'create']:
            return is_auditor(request.user)
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return is_owner_of_audit_object(request.user, obj) or is_auditor(request.user)


class IsOwnerOrSecurityAdmin(BasePermission):
    """
    Allows access to the owner or a security admin.
    """
    message = _('You must be the owner or a security admin to access this resource.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        if view.action in ['list', 'create']:
            return is_security_admin(request.user)
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return is_owner_of_audit_object(request.user, obj) or is_security_admin(request.user)


class IsOwnerOrSystemAdmin(BasePermission):
    """
    Allows access to the owner or a system admin.
    """
    message = _('You must be the owner or a system admin to access this resource.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        if view.action in ['list', 'create']:
            return is_system_admin(request.user)
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.is_deleted():
            return False
        return is_owner_of_audit_object(request.user, obj) or is_system_admin(request.user)


# ============================================================================
# READ-ONLY PERMISSIONS
# ============================================================================

class AuditorReadOnly(BasePermission):
    """
    Allows auditors to read (GET) but not modify audit resources.
    """
    message = _('Auditors have read-only access.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.method in SAFE_METHODS:
            return is_auditor(request.user)
        return is_super_admin(request.user) or request.user.is_superuser

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return is_auditor(request.user)
        return request.user.is_superuser


class SecurityAdminReadOnly(BasePermission):
    """
    Allows security admins to read (GET) but not modify security resources.
    """
    message = _('Security admins have read-only access to this resource.')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_deleted():
            return False
        if request.method in SAFE_METHODS:
            return is_security_admin(request.user)
        return request.user.is_superuser

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return is_security_admin(request.user)
        return request.user.is_superuser


# ============================================================================
# COMBINED PERMISSIONS
# ============================================================================

class OrAuditPermission(BasePermission):
    """
    Combined permission that allows if ANY of the given permissions allow.
    """
    def __init__(self, *perms: Type[BasePermission]):
        self.perms = perms

    def has_permission(self, request, view):
        return any(perm().has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        return any(perm().has_object_permission(request, view, obj) for perm in self.perms)


class AndAuditPermission(BasePermission):
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

# Auditor or system admin
IsAuditorOrSystemAdmin = OrAuditPermission(IsAuditor, IsSystemAdmin)

# Auditor or security admin
IsAuditorOrSecurityAdmin = OrAuditPermission(IsAuditor, IsSecurityAdmin)

# Owner or admin
IsOwnerOrAuditorAdmin = OrAuditPermission(IsOwnerOfAuditObject, IsAuditor)

# Owner or super admin
IsOwnerOrSuperAdmin = OrAuditPermission(IsOwnerOfAuditObject, IsSuperAdminUser)

# Active and has view permission
CanViewAuditLogsActive = AndAuditPermission(IsActiveUser, IsNotDeleted, CanViewAuditLogs)

# Active and can manage rules
CanManageAuditRulesActive = AndAuditPermission(IsActiveUser, IsNotDeleted, CanManageAuditRules)

# Active and can manage alerts
CanManageAuditAlertsActive = AndAuditPermission(IsActiveUser, IsNotDeleted, CanManageAuditAlerts)

# Active and can generate reports
CanGenerateAuditReportsActive = AndAuditPermission(IsActiveUser, IsNotDeleted, CanGenerateAuditReports)

# Active and can view security events
CanViewSecurityEventsActive = AndAuditPermission(IsActiveUser, IsNotDeleted, CanViewSecurityEvents)

# Active and can view system health
CanViewSystemHealthActive = AndAuditPermission(IsActiveUser, IsNotDeleted, CanViewSystemHealth)

# Active and can view performance metrics
CanViewPerformanceMetricsActive = AndAuditPermission(IsActiveUser, IsNotDeleted, CanViewPerformanceMetrics)

# Active and can manage anomalies
CanManageAnomaliesActive = AndAuditPermission(IsActiveUser, IsNotDeleted, CanManageAnomalies)

# System admin and superuser
IsSystemAdminSuper = AndAuditPermission(IsSystemAdmin, IsSuperAdminUser)

# Security admin and superuser
IsSecurityAdminSuper = AndAuditPermission(IsSecurityAdmin, IsSuperAdminUser)

# Auditor with read-only permissions
IsAuditorReadOnly = AndAuditPermission(IsAuditor, AuditorReadOnly)


# ============================================================================
# PERMISSION MIXINS FOR VIEWSETS
# ============================================================================

class AuditPermissionsMixin:
    """
    Mixin for audit viewsets to automatically apply appropriate permissions
    based on the action being performed.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsAdminUser, CanViewAuditLogs],
        'retrieve': [IsAuthenticated, IsAdminUser, CanViewAuditLogs],
        'create': [IsAuthenticated],
        'update': [IsAuthenticated, IsAdminUser, CanViewAuditLogs],
        'partial_update': [IsAuthenticated, IsAdminUser, CanViewAuditLogs],
        'destroy': [IsAuthenticated, IsAdminUser, CanViewAuditLogs],
        'stats': [IsAuthenticated, IsAdminUser, CanViewAuditLogs],
        'summary': [IsAuthenticated, IsAdminUser, CanViewAuditLogs],
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


class SecurityPermissionsMixin:
    """
    Mixin for security viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsAdminUser, CanViewSecurityEvents],
        'retrieve': [IsAuthenticated, IsAdminUser, CanViewSecurityEvents],
        'create': [IsAuthenticated],
        'update': [IsAuthenticated, IsAdminUser, CanViewSecurityEvents],
        'partial_update': [IsAuthenticated, IsAdminUser, CanViewSecurityEvents],
        'destroy': [IsAuthenticated, IsAdminUser, CanViewSecurityEvents],
        'stats': [IsAuthenticated, IsAdminUser, CanViewSecurityEvents],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated, IsAdminUser]
        )
        return [permission() for permission in permission_classes]


class HealthPermissionsMixin:
    """
    Mixin for health viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsAdminUser, CanViewSystemHealth],
        'retrieve': [IsAuthenticated, IsAdminUser, CanViewSystemHealth],
        'create': [IsAuthenticated, IsSystemAdmin],
        'update': [IsAuthenticated, IsSystemAdmin],
        'partial_update': [IsAuthenticated, IsSystemAdmin],
        'destroy': [IsAuthenticated, IsSystemAdmin],
        'overview': [IsAuthenticated, IsAdminUser, CanViewSystemHealth],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated, IsAdminUser]
        )
        return [permission() for permission in permission_classes]


class MetricsPermissionsMixin:
    """
    Mixin for metrics viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsAdminUser, CanViewPerformanceMetrics],
        'retrieve': [IsAuthenticated, IsAdminUser, CanViewPerformanceMetrics],
        'create': [IsAuthenticated],
        'update': [IsAuthenticated, IsAdminUser, CanViewPerformanceMetrics],
        'partial_update': [IsAuthenticated, IsAdminUser, CanViewPerformanceMetrics],
        'destroy': [IsAuthenticated, IsAdminUser, CanViewPerformanceMetrics],
        'aggregate': [IsAuthenticated, IsAdminUser, CanViewPerformanceMetrics],
        'overview': [IsAuthenticated, IsAdminUser, CanViewPerformanceMetrics],
    }

    def get_permissions(self):
        action = self.action
        permission_classes = self.permission_classes_by_action.get(
            action,
            [IsAuthenticated, IsAdminUser]
        )
        return [permission() for permission in permission_classes]


class AnomalyPermissionsMixin:
    """
    Mixin for anomaly viewsets to automatically apply appropriate permissions.
    """
    permission_classes_by_action = {
        'list': [IsAuthenticated, IsAdminUser, CanManageAnomalies],
        'retrieve': [IsAuthenticated, IsAdminUser, CanManageAnomalies],
        'create': [IsAuthenticated, IsSystemAdmin],
        'update': [IsAuthenticated, IsAdminUser, CanManageAnomalies],
        'partial_update': [IsAuthenticated, IsAdminUser, CanManageAnomalies],
        'destroy': [IsAuthenticated, IsAdminUser, CanManageAnomalies],
        'resolve': [IsAuthenticated, IsAdminUser, CanManageAnomalies],
        'mark_false_positive': [IsAuthenticated, IsAdminUser, CanManageAnomalies],
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

def auditor_required(view_func):
    """
    Decorator to require auditor access for a view function.
    """
    from functools import wraps
    from django.http import JsonResponse

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_auditor(request.user):
            return JsonResponse(
                {'error': 'Auditor access required.'},
                status=403
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def security_admin_required(view_func):
    """
    Decorator to require security admin access for a view function.
    """
    from functools import wraps
    from django.http import JsonResponse

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_security_admin(request.user):
            return JsonResponse(
                {'error': 'Security admin access required.'},
                status=403
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def system_admin_required(view_func):
    """
    Decorator to require system admin access for a view function.
    """
    from functools import wraps
    from django.http import JsonResponse

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_system_admin(request.user):
            return JsonResponse(
                {'error': 'System admin access required.'},
                status=403
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def audit_permission_required(permission: str):
    """
    Decorator to require a specific audit permission for a view function.
    """
    from functools import wraps
    from django.http import JsonResponse

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not has_audit_permission(request.user, permission):
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

class AuditPermissionRegistry:
    """
    Registry for managing audit permissions.
    This can be extended to add custom permissions dynamically.
    """
    _permissions = {
        'view_audit_logs': CanViewAuditLogs,
        'manage_audit_rules': CanManageAuditRules,
        'manage_audit_alerts': CanManageAuditAlerts,
        'generate_audit_reports': CanGenerateAuditReports,
        'view_security_events': CanViewSecurityEvents,
        'view_system_health': CanViewSystemHealth,
        'view_performance_metrics': CanViewPerformanceMetrics,
        'manage_anomalies': CanManageAnomalies,
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
    'is_auditor',
    'is_security_admin',
    'is_system_admin',
    'is_anomaly_manager',
    'has_audit_permission',
    'is_owner_of_audit_object',

    # Role-based permissions
    'IsAuditor',
    'IsSecurityAdmin',
    'IsSystemAdmin',
    'IsAnomalyManager',

    # Permission-based permissions
    'CanViewAuditLogs',
    'CanManageAuditRules',
    'CanManageAuditAlerts',
    'CanGenerateAuditReports',
    'CanViewSecurityEvents',
    'CanViewSystemHealth',
    'CanViewPerformanceMetrics',
    'CanManageAnomalies',

    # Object-level permissions
    'IsOwnerOfAuditObject',
    'IsOwnerOrAuditor',
    'IsOwnerOrSecurityAdmin',
    'IsOwnerOrSystemAdmin',

    # Read-only permissions
    'AuditorReadOnly',
    'SecurityAdminReadOnly',

    # Combined permissions
    'OrAuditPermission',
    'AndAuditPermission',

    # Pre-defined combined permissions
    'IsAuditorOrSystemAdmin',
    'IsAuditorOrSecurityAdmin',
    'IsOwnerOrAuditorAdmin',
    'IsOwnerOrSuperAdmin',
    'CanViewAuditLogsActive',
    'CanManageAuditRulesActive',
    'CanManageAuditAlertsActive',
    'CanGenerateAuditReportsActive',
    'CanViewSecurityEventsActive',
    'CanViewSystemHealthActive',
    'CanViewPerformanceMetricsActive',
    'CanManageAnomaliesActive',
    'IsSystemAdminSuper',
    'IsSecurityAdminSuper',
    'IsAuditorReadOnly',

    # Mixins
    'AuditPermissionsMixin',
    'SecurityPermissionsMixin',
    'HealthPermissionsMixin',
    'MetricsPermissionsMixin',
    'AnomalyPermissionsMixin',

    # Decorators
    'auditor_required',
    'security_admin_required',
    'system_admin_required',
    'audit_permission_required',

    # Registry
    'AuditPermissionRegistry',
]