"""
Admin Panel app for the Digital Ekub Platform.

This app provides comprehensive administrative functionality including:
- Dashboard statistics and real-time monitoring
- User management and moderation (suspend, activate, verify, delete)
- Group management and oversight (approve, complete, cancel, review)
- Payment monitoring and reconciliation
- Contribution oversight and management
- Notification broadcasting to users and groups
- System health monitoring and alerting
- Report generation and data export
- Audit log viewing and analysis
- Settings management and configuration
- Bulk operations for users, groups, and payments
- System maintenance tools

All administrative operations are centralized in this app and include
comprehensive security, permission checks, logging, and auditing.
"""

__version__ = '1.0.0'
__app_name__ = 'admin_panel'
__author__ = 'Digital Ekub Team'
__description__ = 'Administrative dashboard and management for the Digital Ekub Platform'

# Set default app configuration for Django
default_app_config = 'apps.admin_panel.apps.AdminPanelConfig'

# ============================================================================
# IMPORT ALL PUBLIC COMPONENTS
# ============================================================================

# Models
from .models import (
    AdminAction,
    AdminLog,
    AdminPreference,
    SystemSetting,
    MaintenanceLog,
    Report,
    ReportSchedule,
    AuditTrail,
    DashboardWidget,
)

# Serializers
from .serializers import (
    AdminActionSerializer,
    AdminLogSerializer,
    AdminPreferenceSerializer,
    AdminPreferenceUpdateSerializer,
    SystemSettingSerializer,
    SystemSettingUpdateSerializer,
    MaintenanceLogSerializer,
    ReportSerializer,
    ReportCreateSerializer,
    ReportUpdateSerializer,
    ReportScheduleSerializer,
    ReportScheduleCreateSerializer,
    AuditTrailSerializer,
    DashboardWidgetSerializer,
    DashboardStatsSerializer,
    SystemHealthSerializer,
    AdminBulkActionSerializer,
)

# Views
from .views import (
    AdminDashboardView,
    DashboardStatsView,
    SystemHealthView,
    UserManagementView,
    GroupManagementView,
    PaymentManagementView,
    ContributionManagementView,
    NotificationBroadcastView,
    ReportGenerationView,
    AuditLogView,
    SystemSettingsView,
    AdminPreferenceView,
    MaintenanceView,
    AdminActionViewSet,
    AdminLogViewSet,
    SystemSettingViewSet,
    ReportViewSet,
    ReportScheduleViewSet,
    AuditTrailViewSet,
    DashboardWidgetViewSet,
)

# Permissions
from .permissions import (
    IsAdminUser,
    IsSuperAdmin,
    CanManageUsers,
    CanManageGroups,
    CanManagePayments,
    CanManageContributions,
    CanBroadcastNotifications,
    CanViewReports,
    CanGenerateReports,
    CanViewAuditLogs,
    CanManageSettings,
    CanManageSystem,
    IsAdminOrReadOnly,
    CanPerformBulkActions,
    CanViewDashboard,
)

# Tasks
from .tasks import (
    generate_daily_reports,
    generate_weekly_reports,
    generate_monthly_reports,
    send_admin_alerts,
    cleanup_admin_logs,
    sync_system_settings,
    check_system_health,
    process_scheduled_reports,
    send_dashboard_digest,
    backup_admin_data,
    clear_system_cache,
    run_maintenance_tasks,
)

# Signals
from .signals import (
    admin_action_post_save_handler,
    admin_action_pre_save_handler,
    admin_log_post_save_handler,
    system_setting_post_save_handler,
    maintenance_log_post_save_handler,
    report_post_save_handler,
)

# ============================================================================
# ADMIN CONSTANTS (RE-EXPORT)
# ============================================================================

from apps.common.constants import (
    UserStatus,
    GroupStatus,
    PaymentStatus,
    ContributionStatus,
    NotificationType,
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
from django.contrib.auth.models import User as DjangoUser

from apps.users.models import User
from apps.groups.models import Group, GroupMember
from apps.contributions.models import Contribution
from apps.payments.models import Payment, Payout
from apps.notifications.models import Notification

logger = logging.getLogger(__name__)


# ============================================================================
# DASHBOARD STATISTICS HELPERS
# ============================================================================

def get_dashboard_stats() -> Dict[str, Any]:
    """
    Get comprehensive dashboard statistics for the admin panel.

    Returns:
        Dict with dashboard statistics including counts, trends, and alerts.
    """
    stats = {
        'users': {},
        'groups': {},
        'contributions': {},
        'payments': {},
        'notifications': {},
        'system': {},
        'trends': {},
        'alerts': [],
    }

    # ========================================================================
    # USER STATISTICS
    # ========================================================================
    total_users = User.objects.filter(deleted_at__isnull=True).count()
    active_users = User.objects.filter(is_active=True, deleted_at__isnull=True).count()
    suspended_users = User.objects.filter(is_suspended=True, deleted_at__isnull=True).count()
    locked_users = User.objects.filter(is_locked=True, deleted_at__isnull=True).count()
    verified_users = User.objects.filter(is_verified=True, deleted_at__isnull=True).count()
    pending_verification = User.objects.filter(
        is_active=True,
        is_verified=False,
        deleted_at__isnull=True
    ).count()

    stats['users'] = {
        'total': total_users,
        'active': active_users,
        'suspended': suspended_users,
        'locked': locked_users,
        'verified': verified_users,
        'pending_verification': pending_verification,
        'active_rate': round((active_users / total_users * 100) if total_users > 0 else 0, 2),
        'verification_rate': round((verified_users / total_users * 100) if total_users > 0 else 0, 2),
    }

    # ========================================================================
    # GROUP STATISTICS
    # ========================================================================
    total_groups = Group.objects.filter(deleted_at__isnull=True).count()
    active_groups = Group.objects.filter(status='active', deleted_at__isnull=True).count()
    pending_groups = Group.objects.filter(status='pending', deleted_at__isnull=True).count()
    completed_groups = Group.objects.filter(status='completed', deleted_at__isnull=True).count()
    cancelled_groups = Group.objects.filter(status='cancelled', deleted_at__isnull=True).count()
    paused_groups = Group.objects.filter(status='paused', deleted_at__isnull=True).count()

    total_members = GroupMember.objects.filter(is_active=True).count()

    stats['groups'] = {
        'total': total_groups,
        'active': active_groups,
        'pending': pending_groups,
        'completed': completed_groups,
        'cancelled': cancelled_groups,
        'paused': paused_groups,
        'total_members': total_members,
        'avg_members': round(total_members / total_groups, 2) if total_groups > 0 else 0,
        'completion_rate': round((completed_groups / total_groups * 100) if total_groups > 0 else 0, 2),
    }

    # ========================================================================
    # CONTRIBUTION STATISTICS
    # ========================================================================
    total_contributions = Contribution.objects.filter(deleted_at__isnull=True).count()
    paid_contributions = Contribution.objects.filter(status='paid', deleted_at__isnull=True).count()
    pending_contributions = Contribution.objects.filter(status='pending', deleted_at__isnull=True).count()
    overdue_contributions = Contribution.objects.filter(status='overdue', deleted_at__isnull=True).count()

    total_contribution_amount = Contribution.objects.filter(
        status='paid',
        deleted_at__isnull=True
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    pending_amount = Contribution.objects.filter(
        status='pending',
        deleted_at__isnull=True
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    overdue_amount = Contribution.objects.filter(
        status='overdue',
        deleted_at__isnull=True
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    stats['contributions'] = {
        'total': total_contributions,
        'paid': paid_contributions,
        'pending': pending_contributions,
        'overdue': overdue_contributions,
        'total_amount': float(total_contribution_amount),
        'pending_amount': float(pending_amount),
        'overdue_amount': float(overdue_amount),
        'payment_rate': round((paid_contributions / total_contributions * 100) if total_contributions > 0 else 0, 2),
    }

    # ========================================================================
    # PAYMENT STATISTICS
    # ========================================================================
    total_payments = Payment.objects.filter(deleted_at__isnull=True).count()
    completed_payments = Payment.objects.filter(status='completed', deleted_at__isnull=True).count()
    pending_payments = Payment.objects.filter(status='pending', deleted_at__isnull=True).count()
    failed_payments = Payment.objects.filter(status='failed', deleted_at__isnull=True).count()

    total_payment_amount = Payment.objects.filter(
        status='completed',
        deleted_at__isnull=True
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_payouts = Payout.objects.filter(deleted_at__isnull=True).count()
    completed_payouts = Payout.objects.filter(status='completed', deleted_at__isnull=True).count()

    stats['payments'] = {
        'total': total_payments,
        'completed': completed_payments,
        'pending': pending_payments,
        'failed': failed_payments,
        'total_amount': float(total_payment_amount),
        'total_payouts': total_payouts,
        'completed_payouts': completed_payouts,
        'success_rate': round((completed_payments / total_payments * 100) if total_payments > 0 else 0, 2),
    }

    # ========================================================================
    # NOTIFICATION STATISTICS
    # ========================================================================
    total_notifications = Notification.objects.filter(deleted_at__isnull=True).count()
    unread_notifications = Notification.objects.filter(is_read=False, deleted_at__isnull=True).count()
    read_notifications = Notification.objects.filter(is_read=True, deleted_at__isnull=True).count()

    stats['notifications'] = {
        'total': total_notifications,
        'unread': unread_notifications,
        'read': read_notifications,
        'read_rate': round((read_notifications / total_notifications * 100) if total_notifications > 0 else 0, 2),
    }

    # ========================================================================
    # SYSTEM STATISTICS
    # ========================================================================
    from django.core.cache import cache
    cache_hits = cache.get('cache_hits', 0)
    cache_misses = cache.get('cache_misses', 0)

    stats['system'] = {
        'cache_hits': cache_hits,
        'cache_misses': cache_misses,
        'cache_hit_rate': round((cache_hits / (cache_hits + cache_misses) * 100) if (cache_hits + cache_misses) > 0 else 0, 2),
        'last_activity': timezone.now().isoformat(),
    }

    # ========================================================================
    # TRENDS (last 7 days)
    # ========================================================================
    from datetime import timedelta
    now = timezone.now()
    week_ago = now - timedelta(days=7)

    # New users per day
    new_users = User.objects.filter(
        date_joined__gte=week_ago,
        deleted_at__isnull=True
    ).extra(
        select={'day': 'date(date_joined)'}
    ).values('day').annotate(count=Count('id')).order_by('day')

    stats['trends']['new_users'] = [
        {'date': item['day'].isoformat(), 'count': item['count']}
        for item in new_users
    ]

    # New groups per day
    new_groups = Group.objects.filter(
        created_at__gte=week_ago,
        deleted_at__isnull=True
    ).extra(
        select={'day': 'date(created_at)'}
    ).values('day').annotate(count=Count('id')).order_by('day')

    stats['trends']['new_groups'] = [
        {'date': item['day'].isoformat(), 'count': item['count']}
        for item in new_groups
    ]

    # Payments per day
    payments_per_day = Payment.objects.filter(
        created_at__gte=week_ago,
        deleted_at__isnull=True
    ).extra(
        select={'day': 'date(created_at)'}
    ).values('day').annotate(
        count=Count('id'),
        total=Sum('amount')
    ).order_by('day')

    stats['trends']['payments'] = [
        {
            'date': item['day'].isoformat(),
            'count': item['count'],
            'total': float(item['total'] or 0)
        }
        for item in payments_per_day
    ]

    # ========================================================================
    # ALERTS
    # ========================================================================
    # Check for overdue contributions
    overdue_count = Contribution.objects.filter(
        status='overdue',
        deleted_at__isnull=True
    ).count()
    if overdue_count > 10:
        stats['alerts'].append({
            'type': 'warning',
            'message': f'{overdue_count} overdue contributions need attention.',
            'severity': 'high' if overdue_count > 50 else 'medium',
        })

    # Check for pending groups
    pending_count = Group.objects.filter(
        status='pending',
        deleted_at__isnull=True
    ).count()
    if pending_count > 5:
        stats['alerts'].append({
            'type': 'info',
            'message': f'{pending_count} groups are pending activation.',
            'severity': 'low',
        })

    # Check for suspended users
    suspended_count = User.objects.filter(
        is_suspended=True,
        deleted_at__isnull=True
    ).count()
    if suspended_count > 10:
        stats['alerts'].append({
            'type': 'warning',
            'message': f'{suspended_count} users are suspended.',
            'severity': 'medium',
        })

    # Check for failed payments
    failed_count = Payment.objects.filter(
        status='failed',
        deleted_at__isnull=True
    ).count()
    if failed_count > 20:
        stats['alerts'].append({
            'type': 'critical',
            'message': f'{failed_count} payments have failed. Please check payment gateway.',
            'severity': 'high',
        })

    return stats


def get_system_health() -> Dict[str, Any]:
    """
    Check the health of the system including database, cache, Celery, and external services.

    Returns:
        Dict with health status for each component.
    """
    health = {
        'status': 'ok',
        'checks': {},
        'timestamp': timezone.now().isoformat(),
    }

    # ========================================================================
    # DATABASE HEALTH
    # ========================================================================
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            start = timezone.now()
            cursor.execute('SELECT 1')
            end = timezone.now()
        latency = (end - start).total_seconds() * 1000
        health['checks']['database'] = {
            'status': 'ok',
            'latency_ms': round(latency, 2),
        }
    except Exception as e:
        health['checks']['database'] = {
            'status': 'error',
            'error': str(e),
        }
        health['status'] = 'degraded'

    # ========================================================================
    # CACHE HEALTH
    # ========================================================================
    try:
        from django.core.cache import cache
        start = timezone.now()
        cache.set('health_check', 'ok', 10)
        value = cache.get('health_check')
        end = timezone.now()
        if value == 'ok':
            latency = (end - start).total_seconds() * 1000
            health['checks']['cache'] = {
                'status': 'ok',
                'latency_ms': round(latency, 2),
            }
        else:
            health['checks']['cache'] = {
                'status': 'error',
                'error': 'Cache returned unexpected value',
            }
            health['status'] = 'degraded'
    except Exception as e:
        health['checks']['cache'] = {
            'status': 'error',
            'error': str(e),
        }
        health['status'] = 'degraded'

    # ========================================================================
    # CELERY HEALTH
    # ========================================================================
    try:
        from celery import current_app
        conn = current_app.connection()
        conn.ensure_connection(max_retries=3)
        conn.release()
        health['checks']['celery'] = {
            'status': 'ok',
        }
    except Exception as e:
        health['checks']['celery'] = {
            'status': 'error',
            'error': str(e),
        }
        health['status'] = 'degraded'

    # ========================================================================
    # PAYMENT GATEWAY HEALTH
    # ========================================================================
    try:
        from apps.payments.gateways import get_available_gateways
        gateways = get_available_gateways()
        health['checks']['payment_gateways'] = {
            'status': 'ok' if any(gateways.values()) else 'warning',
            'available_gateways': gateways,
        }
        if not any(gateways.values()):
            health['status'] = 'degraded'
    except Exception as e:
        health['checks']['payment_gateways'] = {
            'status': 'error',
            'error': str(e),
        }
        health['status'] = 'degraded'

    return health


# ============================================================================
# USER MANAGEMENT HELPERS
# ============================================================================

def suspend_user(user_id: int, reason: str, admin_id: int) -> bool:
    """
    Suspend a user account.

    Args:
        user_id: ID of the user to suspend
        reason: Reason for suspension
        admin_id: ID of the admin performing the action

    Returns:
        bool: True if user was suspended
    """
    try:
        user = User.objects.get(id=user_id, deleted_at__isnull=True)
    except User.DoesNotExist:
        return False

    if user.is_superuser:
        return False

    with transaction.atomic():
        user.is_suspended = True
        user.is_active = False
        user.suspended_at = timezone.now()
        user.suspension_reason = reason
        user.save(update_fields=['is_suspended', 'is_active', 'suspended_at', 'suspension_reason'])

        # Create admin action log
        AdminAction.objects.create(
            user=user,
            admin_id=admin_id,
            action='suspend',
            details={'reason': reason},
        )

        logger.info(f'User {user_id} suspended by admin {admin_id}')
        return True


def activate_user(user_id: int, admin_id: int) -> bool:
    """
    Activate a suspended user account.

    Args:
        user_id: ID of the user to activate
        admin_id: ID of the admin performing the action

    Returns:
        bool: True if user was activated
    """
    try:
        user = User.objects.get(id=user_id, deleted_at__isnull=True)
    except User.DoesNotExist:
        return False

    with transaction.atomic():
        user.is_suspended = False
        user.is_active = True
        user.suspended_at = None
        user.suspension_reason = None
        user.save(update_fields=['is_suspended', 'is_active', 'suspended_at', 'suspension_reason'])

        AdminAction.objects.create(
            user=user,
            admin_id=admin_id,
            action='activate',
            details={},
        )

        logger.info(f'User {user_id} activated by admin {admin_id}')
        return True


def verify_user_identity(user_id: int, admin_id: int) -> bool:
    """
    Verify a user's identity.

    Args:
        user_id: ID of the user to verify
        admin_id: ID of the admin performing the action

    Returns:
        bool: True if user was verified
    """
    try:
        user = User.objects.get(id=user_id, deleted_at__isnull=True)
    except User.DoesNotExist:
        return False

    with transaction.atomic():
        user.is_identity_verified = True
        user.is_verified = True
        user.identity_verification_date = timezone.now()
        user.save(update_fields=['is_identity_verified', 'is_verified', 'identity_verification_date'])

        AdminAction.objects.create(
            user=user,
            admin_id=admin_id,
            action='verify_identity',
            details={},
        )

        logger.info(f'User {user_id} identity verified by admin {admin_id}')
        return True


def delete_user(user_id: int, admin_id: int, reason: str) -> bool:
    """
    Soft delete a user account.

    Args:
        user_id: ID of the user to delete
        admin_id: ID of the admin performing the action
        reason: Reason for deletion

    Returns:
        bool: True if user was deleted
    """
    try:
        user = User.objects.get(id=user_id, deleted_at__isnull=True)
    except User.DoesNotExist:
        return False

    if user.is_superuser:
        return False

    with transaction.atomic():
        user.soft_delete(reason=reason)

        AdminAction.objects.create(
            user=user,
            admin_id=admin_id,
            action='delete',
            details={'reason': reason},
        )

        logger.info(f'User {user_id} deleted by admin {admin_id}')
        return True


# ============================================================================
# GROUP MANAGEMENT HELPERS
# ============================================================================

def approve_group(group_id: int, admin_id: int) -> bool:
    """
    Approve a pending group.

    Args:
        group_id: ID of the group to approve
        admin_id: ID of the admin performing the action

    Returns:
        bool: True if group was approved
    """
    try:
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        return False

    if group.status != 'pending':
        return False

    with transaction.atomic():
        group.status = 'active'
        group.save(update_fields=['status'])

        AdminAction.objects.create(
            group=group,
            admin_id=admin_id,
            action='approve_group',
            details={},
        )

        logger.info(f'Group {group_id} approved by admin {admin_id}')
        return True


def complete_group(group_id: int, admin_id: int) -> bool:
    """
    Complete a group.

    Args:
        group_id: ID of the group to complete
        admin_id: ID of the admin performing the action

    Returns:
        bool: True if group was completed
    """
    try:
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        return False

    if group.is_completed:
        return False

    with transaction.atomic():
        group.complete_group()

        AdminAction.objects.create(
            group=group,
            admin_id=admin_id,
            action='complete_group',
            details={},
        )

        logger.info(f'Group {group_id} completed by admin {admin_id}')
        return True


def cancel_group(group_id: int, admin_id: int, reason: str) -> bool:
    """
    Cancel a group.

    Args:
        group_id: ID of the group to cancel
        admin_id: ID of the admin performing the action
        reason: Reason for cancellation

    Returns:
        bool: True if group was cancelled
    """
    try:
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        return False

    if group.is_cancelled:
        return False

    with transaction.atomic():
        group.cancel_group(reason)

        AdminAction.objects.create(
            group=group,
            admin_id=admin_id,
            action='cancel_group',
            details={'reason': reason},
        )

        logger.info(f'Group {group_id} cancelled by admin {admin_id}')
        return True


def pause_group(group_id: int, admin_id: int, reason: str) -> bool:
    """
    Pause a group.

    Args:
        group_id: ID of the group to pause
        admin_id: ID of the admin performing the action
        reason: Reason for pausing

    Returns:
        bool: True if group was paused
    """
    try:
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        return False

    if group.is_paused:
        return False

    with transaction.atomic():
        group.pause_group(reason)

        AdminAction.objects.create(
            group=group,
            admin_id=admin_id,
            action='pause_group',
            details={'reason': reason},
        )

        logger.info(f'Group {group_id} paused by admin {admin_id}')
        return True


def resume_group(group_id: int, admin_id: int) -> bool:
    """
    Resume a paused group.

    Args:
        group_id: ID of the group to resume
        admin_id: ID of the admin performing the action

    Returns:
        bool: True if group was resumed
    """
    try:
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except Group.DoesNotExist:
        return False

    if not group.is_paused:
        return False

    with transaction.atomic():
        group.resume_group()

        AdminAction.objects.create(
            group=group,
            admin_id=admin_id,
            action='resume_group',
            details={},
        )

        logger.info(f'Group {group_id} resumed by admin {admin_id}')
        return True


# ============================================================================
# PAYMENT HELPERS
# ============================================================================

def process_payment_manually(user_id: int, amount: Decimal, group_id: int, admin_id: int) -> Optional[Payment]:
    """
    Manually process a payment for a user.

    Args:
        user_id: ID of the user
        amount: Payment amount
        group_id: ID of the group
        admin_id: ID of the admin processing the payment

    Returns:
        Payment: The created payment record, or None if failed
    """
    from apps.payments.models import Payment

    try:
        user = User.objects.get(id=user_id, deleted_at__isnull=True)
        group = Group.objects.get(id=group_id, deleted_at__isnull=True)
    except (User.DoesNotExist, Group.DoesNotExist):
        return None

    with transaction.atomic():
        payment = Payment.objects.create(
            user=user,
            group=group,
            amount=amount,
            payment_method='cash',
            gateway='manual',
            status='completed',
            paid_at=timezone.now(),
            created_by_id=admin_id,
        )

        AdminAction.objects.create(
            user=user,
            group=group,
            admin_id=admin_id,
            action='manual_payment',
            details={'amount': float(amount), 'payment_id': payment.id},
        )

        logger.info(f'Manual payment {payment.id} processed by admin {admin_id}')
        return payment


def refund_payment_manually(payment_id: int, admin_id: int, reason: str) -> bool:
    """
    Manually refund a payment.

    Args:
        payment_id: ID of the payment to refund
        admin_id: ID of the admin performing the refund
        reason: Reason for refund

    Returns:
        bool: True if payment was refunded
    """
    from apps.payments.models import Payment

    try:
        payment = Payment.objects.get(id=payment_id, deleted_at__isnull=True)
    except Payment.DoesNotExist:
        return False

    if payment.status != 'completed':
        return False

    with transaction.atomic():
        payment.refund(reason)

        AdminAction.objects.create(
            user=payment.user,
            group=payment.group,
            admin_id=admin_id,
            action='manual_refund',
            details={'payment_id': payment.id, 'reason': reason},
        )

        logger.info(f'Manual refund {payment_id} processed by admin {admin_id}')
        return True


def mark_payment_as_failed(payment_id: int, admin_id: int, reason: str) -> bool:
    """
    Mark a payment as failed.

    Args:
        payment_id: ID of the payment to mark as failed
        admin_id: ID of the admin performing the action
        reason: Reason for failure

    Returns:
        bool: True if payment was marked as failed
    """
    from apps.payments.models import Payment

    try:
        payment = Payment.objects.get(id=payment_id, deleted_at__isnull=True)
    except Payment.DoesNotExist:
        return False

    if payment.status not in ['pending', 'processing']:
        return False

    with transaction.atomic():
        payment.fail(reason)

        AdminAction.objects.create(
            user=payment.user,
            group=payment.group,
            admin_id=admin_id,
            action='mark_payment_failed',
            details={'payment_id': payment.id, 'reason': reason},
        )

        logger.info(f'Payment {payment_id} marked as failed by admin {admin_id}')
        return True


# ============================================================================
# NOTIFICATION BROADCAST HELPERS
# ============================================================================

def broadcast_notification_to_users(user_ids: List[int], message: str, title: str,
                                   notification_type: str, admin_id: int) -> int:
    """
    Broadcast a notification to multiple users.

    Args:
        user_ids: List of user IDs
        message: Notification message
        title: Notification title
        notification_type: Type of notification
        admin_id: ID of the admin sending the broadcast

    Returns:
        int: Number of notifications sent
    """
    from apps.notifications.tasks import send_bulk_notifications

    if not user_ids:
        return 0

    result = send_bulk_notifications.delay(
        user_ids=user_ids,
        message=message,
        notification_type=notification_type,
        title=title,
        send_email=True,
        send_sms=False,
        send_push=True,
        send_in_app=True,
    )

    AdminAction.objects.create(
        admin_id=admin_id,
        action='broadcast_notification',
        details={
            'user_count': len(user_ids),
            'notification_type': notification_type,
            'title': title,
            'task_id': result.id,
        },
    )

    logger.info(f'Broadcast notification sent to {len(user_ids)} users by admin {admin_id}')
    return len(user_ids)


def broadcast_notification_to_group(group_id: int, message: str, title: str,
                                   notification_type: str, admin_id: int,
                                   exclude_user_id: Optional[int] = None) -> int:
    """
    Broadcast a notification to all members of a group.

    Args:
        group_id: ID of the group
        message: Notification message
        title: Notification title
        notification_type: Type of notification
        admin_id: ID of the admin sending the broadcast
        exclude_user_id: Optional user ID to exclude

    Returns:
        int: Number of notifications sent
    """
    members = GroupMember.objects.filter(group_id=group_id, is_active=True)
    if exclude_user_id:
        members = members.exclude(user_id=exclude_user_id)

    user_ids = list(members.values_list('user_id', flat=True))

    if not user_ids:
        return 0

    return broadcast_notification_to_users(user_ids, message, title, notification_type, admin_id)


# ============================================================================
# REPORT GENERATION HELPERS
# ============================================================================

def generate_daily_report(date: Optional[datetime.date] = None) -> Dict[str, Any]:
    """
    Generate a daily summary report.

    Args:
        date: Optional date; defaults to yesterday

    Returns:
        Dict with daily report data
    """
    if date is None:
        date = timezone.now().date() - datetime.timedelta(days=1)

    start_date = datetime.datetime.combine(date, datetime.time.min)
    end_date = datetime.datetime.combine(date, datetime.time.max)

    # Convert to timezone-aware
    start_date = timezone.make_aware(start_date)
    end_date = timezone.make_aware(end_date)

    # New users
    new_users = User.objects.filter(
        date_joined__gte=start_date,
        date_joined__lte=end_date,
        deleted_at__isnull=True
    ).count()

    # New groups
    new_groups = Group.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        deleted_at__isnull=True
    ).count()

    # New contributions
    new_contributions = Contribution.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        deleted_at__isnull=True
    ).count()

    # New payments
    payments = Payment.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        deleted_at__isnull=True
    )
    new_payments = payments.count()
    total_payment_amount = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # New notifications
    new_notifications = Notification.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        deleted_at__isnull=True
    ).count()

    # Completed groups
    completed_groups = Group.objects.filter(
        completed_at__gte=start_date,
        completed_at__lte=end_date,
        deleted_at__isnull=True
    ).count()

    return {
        'date': date.isoformat(),
        'new_users': new_users,
        'new_groups': new_groups,
        'new_contributions': new_contributions,
        'new_payments': new_payments,
        'total_payment_amount': float(total_payment_amount),
        'new_notifications': new_notifications,
        'completed_groups': completed_groups,
    }


def generate_weekly_report() -> Dict[str, Any]:
    """
    Generate a weekly summary report.

    Returns:
        Dict with weekly report data
    """
    week_start = timezone.now().date() - datetime.timedelta(days=7)
    week_end = timezone.now().date()

    # Daily breakdown
    daily_data = []
    for i in range(7):
        date = week_start + datetime.timedelta(days=i)
        daily_data.append(generate_daily_report(date))

    # Aggregate totals
    totals = {
        'new_users': sum(d['new_users'] for d in daily_data),
        'new_groups': sum(d['new_groups'] for d in daily_data),
        'new_contributions': sum(d['new_contributions'] for d in daily_data),
        'new_payments': sum(d['new_payments'] for d in daily_data),
        'total_payment_amount': sum(d['total_payment_amount'] for d in daily_data),
        'new_notifications': sum(d['new_notifications'] for d in daily_data),
        'completed_groups': sum(d['completed_groups'] for d in daily_data),
    }

    # Top contributors
    top_contributors = User.objects.filter(
        contributions__deleted_at__isnull=True,
        contributions__status='paid',
        contributions__paid_date__gte=week_start
    ).annotate(
        total=Sum('contributions__amount')
    ).order_by('-total')[:10]

    return {
        'week_start': week_start.isoformat(),
        'week_end': week_end.isoformat(),
        'daily_data': daily_data,
        'totals': totals,
        'top_contributors': [
            {
                'user_id': u.id,
                'user_name': u.full_name,
                'user_email': u.email,
                'total': float(u.total or 0),
            }
            for u in top_contributors
        ],
    }


def generate_monthly_report() -> Dict[str, Any]:
    """
    Generate a monthly summary report.

    Returns:
        Dict with monthly report data
    """
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = now

    # New users
    new_users = User.objects.filter(
        date_joined__gte=month_start,
        date_joined__lte=month_end,
        deleted_at__isnull=True
    ).count()

    # New groups
    new_groups = Group.objects.filter(
        created_at__gte=month_start,
        created_at__lte=month_end,
        deleted_at__isnull=True
    ).count()

    # New contributions
    new_contributions = Contribution.objects.filter(
        created_at__gte=month_start,
        created_at__lte=month_end,
        deleted_at__isnull=True
    ).count()

    # New payments
    payments = Payment.objects.filter(
        created_at__gte=month_start,
        created_at__lte=month_end,
        deleted_at__isnull=True
    )
    new_payments = payments.count()
    total_payment_amount = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Active users
    active_users = User.objects.filter(
        is_active=True,
        deleted_at__isnull=True
    ).count()

    # Monthly growth
    previous_month_start = month_start - datetime.timedelta(days=1)
    previous_month_start = previous_month_start.replace(day=1)

    previous_users = User.objects.filter(
        date_joined__gte=previous_month_start,
        date_joined__lt=month_start,
        deleted_at__isnull=True
    ).count()

    user_growth = ((new_users - previous_users) / previous_users * 100) if previous_users > 0 else 0

    return {
        'month_start': month_start.isoformat(),
        'month_end': month_end.isoformat(),
        'new_users': new_users,
        'new_groups': new_groups,
        'new_contributions': new_contributions,
        'new_payments': new_payments,
        'total_payment_amount': float(total_payment_amount),
        'active_users': active_users,
        'user_growth': round(user_growth, 2),
        'previous_month_users': previous_users,
    }


def generate_quarterly_report() -> Dict[str, Any]:
    """
    Generate a quarterly summary report.

    Returns:
        Dict with quarterly report data
    """
    now = timezone.now()
    quarter_start = now.replace(
        month=((now.month - 1) // 3) * 3 + 1,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    # New users
    new_users = User.objects.filter(
        date_joined__gte=quarter_start,
        date_joined__lte=now,
        deleted_at__isnull=True
    ).count()

    # New groups
    new_groups = Group.objects.filter(
        created_at__gte=quarter_start,
        created_at__lte=now,
        deleted_at__isnull=True
    ).count()

    # New contributions
    new_contributions = Contribution.objects.filter(
        created_at__gte=quarter_start,
        created_at__lte=now,
        deleted_at__isnull=True
    ).count()

    # New payments
    payments = Payment.objects.filter(
        created_at__gte=quarter_start,
        created_at__lte=now,
        deleted_at__isnull=True
    )
    new_payments = payments.count()
    total_payment_amount = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Monthly breakdown
    monthly_data = []
    for month_offset in range(3):
        month_date = quarter_start + datetime.timedelta(days=30 * month_offset)
        monthly_data.append({
            'month': month_date.strftime('%B %Y'),
            'new_users': User.objects.filter(
                date_joined__year=month_date.year,
                date_joined__month=month_date.month,
                deleted_at__isnull=True
            ).count(),
            'new_payments': Payment.objects.filter(
                created_at__year=month_date.year,
                created_at__month=month_date.month,
                deleted_at__isnull=True
            ).count(),
        })

    return {
        'quarter_start': quarter_start.isoformat(),
        'quarter_end': now.isoformat(),
        'new_users': new_users,
        'new_groups': new_groups,
        'new_contributions': new_contributions,
        'new_payments': new_payments,
        'total_payment_amount': float(total_payment_amount),
        'monthly_breakdown': monthly_data,
    }


def get_recent_audit_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get recent audit logs for the admin panel.

    Args:
        limit: Number of logs to retrieve

    Returns:
        List of audit log entries
    """
    from apps.admin_panel.models import AuditTrail

    logs = AuditTrail.objects.order_by('-timestamp')[:limit]

    return [
        {
            'id': log.id,
            'user_id': log.user_id,
            'user_email': log.user.email if log.user else 'System',
            'action': log.action,
            'details': log.details,
            'ip_address': log.ip_address,
            'timestamp': log.timestamp.isoformat(),
        }
        for log in logs
    ]


def get_admin_action_stats(days: int = 30) -> Dict[str, Any]:
    """
    Get statistics for admin actions.

    Args:
        days: Number of days to look back

    Returns:
        Dict with admin action statistics
    """
    from apps.admin_panel.models import AdminAction

    start_date = timezone.now() - datetime.timedelta(days=days)

    actions = AdminAction.objects.filter(created_at__gte=start_date)

    total = actions.count()

    # Actions by type
    action_breakdown = actions.values('action').annotate(
        count=Count('id')
    )

    # Actions by admin
    admin_breakdown = actions.values('admin').annotate(
        count=Count('id')
    )

    # Daily breakdown
    daily_breakdown = actions.extra(
        select={'day': 'date(created_at)'}
    ).values('day').annotate(
        count=Count('id')
    ).order_by('day')

    return {
        'total_actions': total,
        'days': days,
        'action_breakdown': [
            {'action': item['action'], 'count': item['count']}
            for item in action_breakdown
        ],
        'admin_breakdown': [
            {'admin_id': item['admin'], 'count': item['count']}
            for item in admin_breakdown
        ],
        'daily_breakdown': [
            {'date': item['day'].isoformat(), 'count': item['count']}
            for item in daily_breakdown
        ],
    }


def clear_system_cache(admin_id: int) -> bool:
    """
    Clear the system cache.

    Args:
        admin_id: ID of the admin performing the action

    Returns:
        bool: True if cache was cleared
    """
    try:
        from django.core.cache import cache
        cache.clear()

        AdminAction.objects.create(
            admin_id=admin_id,
            action='clear_cache',
            details={},
        )

        logger.info(f'System cache cleared by admin {admin_id}')
        return True
    except Exception as e:
        logger.error(f'Failed to clear system cache: {str(e)}')
        return False


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
    'AdminAction',
    'AdminLog',
    'AdminPreference',
    'SystemSetting',
    'MaintenanceLog',
    'Report',
    'ReportSchedule',
    'AuditTrail',
    'DashboardWidget',

    # Serializers
    'AdminActionSerializer',
    'AdminLogSerializer',
    'AdminPreferenceSerializer',
    'AdminPreferenceUpdateSerializer',
    'SystemSettingSerializer',
    'SystemSettingUpdateSerializer',
    'MaintenanceLogSerializer',
    'ReportSerializer',
    'ReportCreateSerializer',
    'ReportUpdateSerializer',
    'ReportScheduleSerializer',
    'ReportScheduleCreateSerializer',
    'AuditTrailSerializer',
    'DashboardWidgetSerializer',
    'DashboardStatsSerializer',
    'SystemHealthSerializer',
    'AdminBulkActionSerializer',

    # Views
    'AdminDashboardView',
    'DashboardStatsView',
    'SystemHealthView',
    'UserManagementView',
    'GroupManagementView',
    'PaymentManagementView',
    'ContributionManagementView',
    'NotificationBroadcastView',
    'ReportGenerationView',
    'AuditLogView',
    'SystemSettingsView',
    'AdminPreferenceView',
    'MaintenanceView',
    'AdminActionViewSet',
    'AdminLogViewSet',
    'SystemSettingViewSet',
    'ReportViewSet',
    'ReportScheduleViewSet',
    'AuditTrailViewSet',
    'DashboardWidgetViewSet',

    # Permissions
    'IsAdminUser',
    'IsSuperAdmin',
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
    'IsAdminOrReadOnly',
    'CanPerformBulkActions',
    'CanViewDashboard',

    # Tasks
    'generate_daily_reports',
    'generate_weekly_reports',
    'generate_monthly_reports',
    'send_admin_alerts',
    'cleanup_admin_logs',
    'sync_system_settings',
    'check_system_health',
    'process_scheduled_reports',
    'send_dashboard_digest',
    'backup_admin_data',
    'clear_system_cache',
    'run_maintenance_tasks',

    # Signals
    'admin_action_post_save_handler',
    'admin_action_pre_save_handler',
    'admin_log_post_save_handler',
    'system_setting_post_save_handler',
    'maintenance_log_post_save_handler',
    'report_post_save_handler',

    # Constants
    'UserStatus',
    'GroupStatus',
    'PaymentStatus',
    'ContributionStatus',
    'NotificationType',

    # Helper functions
    'get_dashboard_stats',
    'get_system_health',
    'suspend_user',
    'activate_user',
    'verify_user_identity',
    'delete_user',
    'approve_group',
    'complete_group',
    'cancel_group',
    'pause_group',
    'resume_group',
    'process_payment_manually',
    'refund_payment_manually',
    'mark_payment_as_failed',
    'broadcast_notification_to_users',
    'broadcast_notification_to_group',
    'generate_daily_report',
    'generate_weekly_report',
    'generate_monthly_report',
    'generate_quarterly_report',
    'get_recent_audit_logs',
    'get_admin_action_stats',
    'clear_system_cache',
]

# ============================================================================
# LOGGING
# ============================================================================

logger.info(f'Admin Panel app v{__version__} initialized')