"""
Audit app for the Digital Ekub Platform.

This app provides comprehensive auditing and monitoring functionality:
- Audit logging of all user, admin, and system actions
- Security event monitoring and alerting
- Compliance reporting and data retention
- User activity tracking and analytics
- System performance monitoring
- Anomaly detection and alerting
- Audit trail viewing and analysis
- Export and reporting of audit data
- Integration with SIEM systems
- Real-time event streaming

All audit operations are centralized in this app and include
comprehensive security, permission checks, logging, and data retention.
"""

__version__ = '1.0.0'
__app_name__ = 'audit'
__author__ = 'Digital Ekub Team'
__description__ = 'Comprehensive auditing and monitoring for the Digital Ekub Platform'

# Set default app configuration for Django
default_app_config = 'apps.audit.apps.AuditConfig'

# ============================================================================
# IMPORT ALL PUBLIC COMPONENTS
# ============================================================================

# Models
from .models import (
    AuditLog,
    AuditEvent,
    AuditRule,
    AuditAlert,
    AuditReport,
    AuditRetentionPolicy,
    SecurityEvent,
    UserActivity,
    SystemHealth,
    PerformanceMetric,
    AnomalyDetection,
)

# Serializers
from .serializers import (
    AuditLogSerializer,
    AuditLogListSerializer,
    AuditLogDetailSerializer,
    AuditLogCreateSerializer,
    AuditEventSerializer,
    AuditEventListSerializer,
    AuditEventDetailSerializer,
    AuditRuleSerializer,
    AuditRuleCreateSerializer,
    AuditRuleUpdateSerializer,
    AuditAlertSerializer,
    AuditAlertListSerializer,
    AuditAlertDetailSerializer,
    AuditReportSerializer,
    AuditReportCreateSerializer,
    AuditReportUpdateSerializer,
    AuditRetentionPolicySerializer,
    AuditRetentionPolicyUpdateSerializer,
    SecurityEventSerializer,
    SecurityEventListSerializer,
    SecurityEventDetailSerializer,
    UserActivitySerializer,
    UserActivityListSerializer,
    SystemHealthSerializer,
    PerformanceMetricSerializer,
    PerformanceMetricListSerializer,
    AnomalyDetectionSerializer,
    AuditStatsSerializer,
)

# Views
from .views import (
    AuditLogViewSet,
    AuditEventViewSet,
    AuditRuleViewSet,
    AuditAlertViewSet,
    AuditReportViewSet,
    AuditRetentionPolicyViewSet,
    SecurityEventViewSet,
    UserActivityViewSet,
    SystemHealthView,
    PerformanceMetricViewSet,
    AnomalyDetectionViewSet,
    AuditStatsView,
    AuditExportView,
    AuditDashboardView,
)

# Permissions
from .permissions import (
    IsAuditor,
    IsAuditAdmin,
    CanViewAuditLogs,
    CanManageAuditRules,
    CanManageRetention,
    CanViewSecurityEvents,
    CanViewUserActivity,
    CanExportAuditData,
    CanManageAlerts,
)

# Tasks
from .tasks import (
    process_audit_events,
    rotate_audit_logs,
    enforce_retention_policies,
    generate_audit_reports,
    send_audit_alerts,
    detect_anomalies,
    archive_audit_logs,
    cleanup_audit_data,
    sync_audit_events,
    check_audit_health,
)

# Signals
from .signals import (
    audit_log_post_save_handler,
    audit_event_post_save_handler,
    security_event_post_save_handler,
    user_activity_post_save_handler,
)

# ============================================================================
# AUDIT CONSTANTS (RE-EXPORT)
# ============================================================================

from apps.common.constants import (
    AuditAction,
    NotificationType,
    NotificationPriority,
)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

import logging
import json
import datetime
from typing import Optional, Dict, Any, List, Union, Tuple
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
from django.conf import settings
from django.db.models import Q, Count, Sum, Avg, Max, Min
from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)


# ============================================================================
# AUDIT LOGGING HELPERS
# ============================================================================

def log_audit_event(
    user: Optional[User],
    action: str,
    resource: str,
    resource_id: Optional[int] = None,
    details: Optional[Dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    severity: str = 'info',
) -> 'AuditLog':
    """
    Log an audit event.

    Args:
        user: User performing the action (or None for system)
        action: Action performed (e.g., 'CREATE', 'UPDATE', 'DELETE', 'VIEW')
        resource: Resource type (e.g., 'USER', 'GROUP', 'PAYMENT')
        resource_id: Optional ID of the resource
        details: Additional details
        ip_address: IP address of the user
        user_agent: User agent of the user's browser
        severity: Severity level (info, warning, error, critical)

    Returns:
        AuditLog: The created audit log entry
    """
    from .models import AuditLog

    audit_entry = AuditLog.objects.create(
        user=user,
        action=action,
        resource=resource,
        resource_id=resource_id,
        details=details or {},
        ip_address=ip_address,
        user_agent=user_agent,
        severity=severity,
        timestamp=timezone.now(),
    )

    logger.info(f'Audit log created: {action} on {resource} by {user.email if user else "System"}')
    return audit_entry


def log_security_event(
    user: Optional[User],
    event_type: str,
    description: str,
    severity: str = 'warning',
    details: Optional[Dict] = None,
    ip_address: Optional[str] = None,
) -> 'SecurityEvent':
    """
    Log a security event.

    Args:
        user: User associated with the event (or None)
        event_type: Type of security event (e.g., 'LOGIN_FAILED', 'SUSPICIOUS_ACTIVITY')
        description: Description of the event
        severity: Severity level (info, warning, error, critical)
        details: Additional details
        ip_address: IP address

    Returns:
        SecurityEvent: The created security event
    """
    from .models import SecurityEvent

    security_event = SecurityEvent.objects.create(
        user=user,
        event_type=event_type,
        description=description,
        severity=severity,
        details=details or {},
        ip_address=ip_address,
        timestamp=timezone.now(),
    )

    logger.warning(f'Security event: {event_type} - {description}')
    return security_event


def log_user_activity(
    user: User,
    action: str,
    resource: str,
    resource_id: Optional[int] = None,
    details: Optional[Dict] = None,
) -> 'UserActivity':
    """
    Log user activity for tracking and analytics.

    Args:
        user: User performing the action
        action: Action performed
        resource: Resource type
        resource_id: Optional ID of the resource
        details: Additional details

    Returns:
        UserActivity: The created user activity entry
    """
    from .models import UserActivity

    activity = UserActivity.objects.create(
        user=user,
        action=action,
        resource=resource,
        resource_id=resource_id,
        details=details or {},
        timestamp=timezone.now(),
    )

    logger.debug(f'User activity: {user.email} - {action} on {resource}')
    return activity


# ============================================================================
# AUDIT RETENTION HELPERS
# ============================================================================

def get_audit_retention_days(resource_type: str) -> int:
    """
    Get the retention period for a resource type.

    Args:
        resource_type: Type of resource (e.g., 'AUDIT_LOG', 'SECURITY_EVENT')

    Returns:
        int: Number of days to retain data
    """
    from .models import AuditRetentionPolicy

    try:
        policy = AuditRetentionPolicy.objects.get(resource_type=resource_type, is_active=True)
        return policy.retention_days
    except AuditRetentionPolicy.DoesNotExist:
        # Default retention: 365 days
        return 365


def enforce_retention(resource_type: str) -> int:
    """
    Enforce retention policy for a resource type by deleting old records.

    Args:
        resource_type: Type of resource

    Returns:
        int: Number of records deleted
    """
    from .models import AuditLog, AuditRetentionPolicy

    retention_days = get_audit_retention_days(resource_type)
    cutoff_date = timezone.now() - datetime.timedelta(days=retention_days)

    if resource_type == 'AUDIT_LOG':
        count, _ = AuditLog.objects.filter(timestamp__lt=cutoff_date).delete()
        return count
    elif resource_type == 'SECURITY_EVENT':
        from .models import SecurityEvent
        count, _ = SecurityEvent.objects.filter(timestamp__lt=cutoff_date).delete()
        return count
    elif resource_type == 'USER_ACTIVITY':
        from .models import UserActivity
        count, _ = UserActivity.objects.filter(timestamp__lt=cutoff_date).delete()
        return count

    return 0


# ============================================================================
# AUDIT STATISTICS HELPERS
# ============================================================================

def get_audit_stats(days: int = 30) -> Dict[str, Any]:
    """
    Get audit statistics for the last N days.

    Args:
        days: Number of days to look back

    Returns:
        Dict with audit statistics
    """
    from .models import AuditLog, SecurityEvent, UserActivity

    start_date = timezone.now() - datetime.timedelta(days=days)

    audit_logs = AuditLog.objects.filter(timestamp__gte=start_date)
    security_events = SecurityEvent.objects.filter(timestamp__gte=start_date)
    user_activities = UserActivity.objects.filter(timestamp__gte=start_date)

    stats = {
        'total_audit_logs': audit_logs.count(),
        'total_security_events': security_events.count(),
        'total_user_activities': user_activities.count(),
        'audit_by_action': audit_logs.values('action').annotate(count=Count('id')),
        'security_by_severity': security_events.values('severity').annotate(count=Count('id')),
        'activity_by_user': user_activities.values('user__email').annotate(count=Count('id')).order_by('-count')[:10],
        'top_resources': audit_logs.values('resource').annotate(count=Count('id')).order_by('-count')[:10],
    }

    return stats


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
    'AuditLog',
    'AuditEvent',
    'AuditRule',
    'AuditAlert',
    'AuditReport',
    'AuditRetentionPolicy',
    'SecurityEvent',
    'UserActivity',
    'SystemHealth',
    'PerformanceMetric',
    'AnomalyDetection',

    # Serializers
    'AuditLogSerializer',
    'AuditLogListSerializer',
    'AuditLogDetailSerializer',
    'AuditLogCreateSerializer',
    'AuditEventSerializer',
    'AuditEventListSerializer',
    'AuditEventDetailSerializer',
    'AuditRuleSerializer',
    'AuditRuleCreateSerializer',
    'AuditRuleUpdateSerializer',
    'AuditAlertSerializer',
    'AuditAlertListSerializer',
    'AuditAlertDetailSerializer',
    'AuditReportSerializer',
    'AuditReportCreateSerializer',
    'AuditReportUpdateSerializer',
    'AuditRetentionPolicySerializer',
    'AuditRetentionPolicyUpdateSerializer',
    'SecurityEventSerializer',
    'SecurityEventListSerializer',
    'SecurityEventDetailSerializer',
    'UserActivitySerializer',
    'UserActivityListSerializer',
    'SystemHealthSerializer',
    'PerformanceMetricSerializer',
    'PerformanceMetricListSerializer',
    'AnomalyDetectionSerializer',
    'AuditStatsSerializer',

    # Views
    'AuditLogViewSet',
    'AuditEventViewSet',
    'AuditRuleViewSet',
    'AuditAlertViewSet',
    'AuditReportViewSet',
    'AuditRetentionPolicyViewSet',
    'SecurityEventViewSet',
    'UserActivityViewSet',
    'SystemHealthView',
    'PerformanceMetricViewSet',
    'AnomalyDetectionViewSet',
    'AuditStatsView',
    'AuditExportView',
    'AuditDashboardView',

    # Permissions
    'IsAuditor',
    'IsAuditAdmin',
    'CanViewAuditLogs',
    'CanManageAuditRules',
    'CanManageRetention',
    'CanViewSecurityEvents',
    'CanViewUserActivity',
    'CanExportAuditData',
    'CanManageAlerts',

    # Tasks
    'process_audit_events',
    'rotate_audit_logs',
    'enforce_retention_policies',
    'generate_audit_reports',
    'send_audit_alerts',
    'detect_anomalies',
    'archive_audit_logs',
    'cleanup_audit_data',
    'sync_audit_events',
    'check_audit_health',

    # Signals
    'audit_log_post_save_handler',
    'audit_event_post_save_handler',
    'security_event_post_save_handler',
    'user_activity_post_save_handler',

    # Constants
    'AuditAction',
    'NotificationType',
    'NotificationPriority',

    # Helper functions
    'log_audit_event',
    'log_security_event',
    'log_user_activity',
    'get_audit_retention_days',
    'enforce_retention',
    'get_audit_stats',
]

# ============================================================================
# LOGGING
# ============================================================================

logger.info(f'Audit app v{__version__} initialized')