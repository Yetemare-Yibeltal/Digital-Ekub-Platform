"""
Views for the admin panel app.

This module provides all API views for administrative functionality including:
- Dashboard statistics and real-time monitoring
- User management (suspend, activate, verify, delete, restore)
- Group management (approve, complete, cancel, pause, resume)
- Payment management (manual process, refund, mark failed)
- Contribution management (mark paid, refund, waive)
- Notification broadcasting to users and groups
- Report generation and management
- Audit log viewing
- System settings management
- Admin preferences
- Maintenance operations
- Full CRUD for admin models via ViewSets

All views use appropriate permissions and include comprehensive logging,
pagination, filtering, and error handling with transaction management.
"""

from django.db import transaction
from django.db.models import Q, Count, Sum, Avg, F, OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets, status, permissions, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound
from rest_framework.views import APIView
from decimal import Decimal

from apps.users.models import User
from apps.groups.models import Group, GroupMember
from apps.contributions.models import Contribution
from apps.payments.models import Payment, Payout
from apps.notifications.models import Notification
from apps.common.pagination import CustomPagination
from apps.common.permissions import IsAuthenticated, IsActiveUser, IsSuperAdminUser, IsAdminUser
from apps.common.exceptions import BadRequestError, NotFoundError, PermissionDeniedError, ConflictError
from apps.common.utils import log_audit_event, get_client_ip, format_currency

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
from .serializers import (
    AdminActionListSerializer,
    AdminActionDetailSerializer,
    AdminActionCreateSerializer,
    AdminLogListSerializer,
    AdminLogCreateSerializer,
    AdminPreferenceSerializer,
    AdminPreferenceUpdateSerializer,
    SystemSettingSerializer,
    SystemSettingCreateSerializer,
    SystemSettingUpdateSerializer,
    SystemSettingBulkUpdateSerializer,
    MaintenanceLogListSerializer,
    MaintenanceLogCreateSerializer,
    ReportListSerializer,
    ReportDetailSerializer,
    ReportCreateSerializer,
    ReportUpdateSerializer,
    ReportScheduleListSerializer,
    ReportScheduleCreateSerializer,
    ReportScheduleUpdateSerializer,
    AuditTrailSerializer,
    DashboardWidgetSerializer,
    DashboardWidgetCreateSerializer,
    DashboardWidgetUpdateSerializer,
    DashboardStatsSerializer,
    SystemHealthSerializer,
    AdminBulkActionSerializer,
    ReportDataSerializer,
)
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
from . import (
    get_dashboard_stats,
    get_system_health,
    suspend_user,
    activate_user,
    verify_user_identity,
    delete_user,
    approve_group,
    complete_group,
    cancel_group,
    pause_group,
    resume_group,
    process_payment_manually,
    refund_payment_manually,
    mark_payment_as_failed,
    broadcast_notification_to_users,
    broadcast_notification_to_group,
    generate_daily_report,
    generate_weekly_report,
    generate_monthly_report,
    generate_quarterly_report,
    get_recent_audit_logs,
    get_admin_action_stats,
    clear_system_cache,
)
from .tasks import (
    generate_daily_reports,
    generate_weekly_reports,
    generate_monthly_reports,
    send_admin_alerts,
    cleanup_admin_logs,
    sync_system_settings,
    check_system_health as check_health_task,
    process_scheduled_reports,
    send_dashboard_digest,
    backup_admin_data,
    clear_system_cache as clear_cache_task,
    run_maintenance_tasks,
)

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# DASHBOARD VIEWS
# ============================================================================

class AdminDashboardView(APIView):
    """
    View for admin dashboard with statistics and health.
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanViewDashboard]

    def get(self, request):
        stats = get_dashboard_stats()
        health = get_system_health()

        # Get recent admin actions
        recent_actions = AdminAction.objects.select_related('admin', 'user', 'group').order_by('-timestamp')[:10]
        actions_serializer = AdminActionListSerializer(recent_actions, many=True)

        return Response({
            'stats': stats,
            'health': health,
            'recent_actions': actions_serializer.data,
        }, status=status.HTTP_200_OK)


class DashboardStatsView(APIView):
    """
    View for dashboard statistics only.
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanViewDashboard]

    def get(self, request):
        stats = get_dashboard_stats()
        serializer = DashboardStatsSerializer(stats)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SystemHealthView(APIView):
    """
    View for system health check.
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanManageSystem]

    def get(self, request):
        health = get_system_health()
        serializer = SystemHealthSerializer(health)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# USER MANAGEMENT VIEWS
# ============================================================================

class UserManagementView(APIView):
    """
    View for user management actions (suspend, activate, verify, delete).
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanManageUsers]

    def post(self, request, user_id, action):
        """
        Perform an action on a user.
        Valid actions: suspend, activate, verify, delete, restore.
        """
        admin = request.user
        reason = request.data.get('reason', '')

        try:
            user = User.objects.get(id=user_id, deleted_at__isnull=True)
        except User.DoesNotExist:
            raise NotFoundError(_('User not found.'))

        if action == 'suspend':
            if user.is_superuser:
                raise PermissionDeniedError(_('Cannot suspend a super admin.'))
            success = suspend_user(user.id, reason, admin.id)
            message = _('User suspended successfully.')
        elif action == 'activate':
            success = activate_user(user.id, admin.id)
            message = _('User activated successfully.')
        elif action == 'verify':
            success = verify_user_identity(user.id, admin.id)
            message = _('User identity verified successfully.')
        elif action == 'delete':
            if user.is_superuser:
                raise PermissionDeniedError(_('Cannot delete a super admin.'))
            success = delete_user(user.id, admin.id, reason)
            message = _('User soft deleted successfully.')
        elif action == 'restore':
            if user.deleted_at:
                user.restore()
                success = True
            else:
                success = False
            message = _('User restored successfully.')
        else:
            raise BadRequestError(_('Invalid action.'))

        if not success:
            raise BadRequestError(_('Action failed.'))

        # Log the action
        log_audit_event(
            user_id=admin.id,
            action=f'user_{action}',
            resource='user',
            resource_id=user.id,
            ip=get_client_ip(request),
            details={'reason': reason}
        )

        return Response({
            'message': message,
            'user': {
                'id': user.id,
                'email': user.email,
                'full_name': user.full_name,
                'is_active': user.is_active,
                'is_suspended': user.is_suspended,
            }
        }, status=status.HTTP_200_OK)


# ============================================================================
# GROUP MANAGEMENT VIEWS
# ============================================================================

class GroupManagementView(APIView):
    """
    View for group management actions (approve, complete, cancel, pause, resume).
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanManageGroups]

    def post(self, request, group_id, action):
        """
        Perform an action on a group.
        Valid actions: approve, complete, cancel, pause, resume.
        """
        admin = request.user
        reason = request.data.get('reason', '')

        try:
            group = Group.objects.get(id=group_id, deleted_at__isnull=True)
        except Group.DoesNotExist:
            raise NotFoundError(_('Group not found.'))

        if action == 'approve':
            success = approve_group(group.id, admin.id)
            message = _('Group approved successfully.')
        elif action == 'complete':
            success = complete_group(group.id, admin.id)
            message = _('Group completed successfully.')
        elif action == 'cancel':
            success = cancel_group(group.id, admin.id, reason)
            message = _('Group cancelled successfully.')
        elif action == 'pause':
            success = pause_group(group.id, admin.id, reason)
            message = _('Group paused successfully.')
        elif action == 'resume':
            success = resume_group(group.id, admin.id)
            message = _('Group resumed successfully.')
        else:
            raise BadRequestError(_('Invalid action.'))

        if not success:
            raise BadRequestError(_('Action failed.'))

        log_audit_event(
            user_id=admin.id,
            action=f'group_{action}',
            resource='group',
            resource_id=group.id,
            ip=get_client_ip(request),
            details={'reason': reason}
        )

        return Response({
            'message': message,
            'group': {
                'id': group.id,
                'name': group.name,
                'status': group.status,
            }
        }, status=status.HTTP_200_OK)


# ============================================================================
# PAYMENT MANAGEMENT VIEWS
# ============================================================================

class PaymentManagementView(APIView):
    """
    View for payment management actions (manual process, refund, mark failed).
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanManagePayments]

    def post(self, request):
        """
        Perform payment management actions.
        """
        admin = request.user
        action = request.data.get('action')
        payment_id = request.data.get('payment_id')
        user_id = request.data.get('user_id')
        group_id = request.data.get('group_id')
        amount = request.data.get('amount')
        reason = request.data.get('reason', '')

        if action == 'manual_payment':
            # Manual payment processing
            if not user_id or not group_id or amount is None:
                raise BadRequestError(_('user_id, group_id, and amount are required.'))
            try:
                amount = Decimal(str(amount))
            except Exception:
                raise BadRequestError(_('Invalid amount.'))
            payment = process_payment_manually(user_id, amount, group_id, admin.id)
            if not payment:
                raise BadRequestError(_('Manual payment failed.'))
            message = _('Manual payment processed successfully.')
            response_data = {
                'payment_id': payment.id,
                'amount': float(payment.amount),
                'status': payment.status,
            }

        elif action == 'refund':
            if not payment_id:
                raise BadRequestError(_('payment_id is required.'))
            success = refund_payment_manually(payment_id, admin.id, reason)
            if not success:
                raise BadRequestError(_('Refund failed.'))
            message = _('Payment refunded successfully.')
            response_data = {'payment_id': payment_id}

        elif action == 'mark_failed':
            if not payment_id:
                raise BadRequestError(_('payment_id is required.'))
            success = mark_payment_as_failed(payment_id, admin.id, reason)
            if not success:
                raise BadRequestError(_('Mark as failed failed.'))
            message = _('Payment marked as failed successfully.')
            response_data = {'payment_id': payment_id}

        else:
            raise BadRequestError(_('Invalid action.'))

        log_audit_event(
            user_id=admin.id,
            action=f'payment_{action}',
            resource='payment',
            resource_id=payment_id,
            ip=get_client_ip(request),
            details=request.data
        )

        return Response({
            'message': message,
            'data': response_data,
        }, status=status.HTTP_200_OK)


# ============================================================================
# CONTRIBUTION MANAGEMENT VIEWS
# ============================================================================

class ContributionManagementView(APIView):
    """
    View for contribution management actions (mark paid, refund, waive).
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanManageContributions]

    def post(self, request):
        """
        Perform contribution management actions.
        """
        admin = request.user
        contribution_id = request.data.get('contribution_id')
        action = request.data.get('action')
        reason = request.data.get('reason', '')

        if not contribution_id:
            raise BadRequestError(_('contribution_id is required.'))

        try:
            contribution = Contribution.objects.get(id=contribution_id, deleted_at__isnull=True)
        except Contribution.DoesNotExist:
            raise NotFoundError(_('Contribution not found.'))

        if action == 'mark_paid':
            success = contribution.mark_as_paid()
            message = _('Contribution marked as paid.')
        elif action == 'refund':
            success = contribution.refund(reason)
            message = _('Contribution refunded.')
        elif action == 'waive':
            amount = request.data.get('amount')
            if not amount:
                raise BadRequestError(_('amount is required for waive action.'))
            try:
                amount = Decimal(str(amount))
            except Exception:
                raise BadRequestError(_('Invalid amount.'))
            success = contribution.waive(amount, reason)
            message = _('Contribution waived.')
        else:
            raise BadRequestError(_('Invalid action.'))

        if not success:
            raise BadRequestError(_('Action failed.'))

        log_audit_event(
            user_id=admin.id,
            action=f'contribution_{action}',
            resource='contribution',
            resource_id=contribution.id,
            ip=get_client_ip(request),
            details=request.data
        )

        return Response({
            'message': message,
            'contribution': {
                'id': contribution.id,
                'status': contribution.status,
                'amount': float(contribution.amount),
            }
        }, status=status.HTTP_200_OK)


# ============================================================================
# NOTIFICATION BROADCAST VIEW
# ============================================================================

class NotificationBroadcastView(APIView):
    """
    View for broadcasting notifications to users or groups.
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanBroadcastNotifications]

    def post(self, request):
        """
        Broadcast a notification.
        """
        admin = request.user
        target_type = request.data.get('target_type')  # 'users' or 'group'
        user_ids = request.data.get('user_ids', [])
        group_id = request.data.get('group_id')
        message = request.data.get('message')
        title = request.data.get('title', '')
        notification_type = request.data.get('notification_type', 'info')
        exclude_user_id = request.data.get('exclude_user_id')

        if not message:
            raise BadRequestError(_('Message is required.'))

        if target_type == 'users':
            if not user_ids:
                raise BadRequestError(_('user_ids are required for user broadcast.'))
            count = broadcast_notification_to_users(
                user_ids=user_ids,
                message=message,
                title=title,
                notification_type=notification_type,
                admin_id=admin.id,
            )
            message_text = _(f'Notification broadcasted to {count} users.')

        elif target_type == 'group':
            if not group_id:
                raise BadRequestError(_('group_id is required for group broadcast.'))
            count = broadcast_notification_to_group(
                group_id=group_id,
                message=message,
                title=title,
                notification_type=notification_type,
                admin_id=admin.id,
                exclude_user_id=exclude_user_id,
            )
            message_text = _(f'Notification broadcasted to {count} group members.')

        else:
            raise BadRequestError(_('Invalid target_type. Must be "users" or "group".'))

        log_audit_event(
            user_id=admin.id,
            action='broadcast_notification',
            resource='notification',
            resource_id=None,
            ip=get_client_ip(request),
            details={'target_type': target_type, 'count': count}
        )

        return Response({
            'message': message_text,
            'count': count,
        }, status=status.HTTP_200_OK)


# ============================================================================
# REPORT GENERATION VIEW
# ============================================================================

class ReportGenerationView(APIView):
    """
    View for generating reports.
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanGenerateReports]

    def post(self, request):
        """
        Generate a report based on parameters.
        """
        admin = request.user
        serializer = ReportDataSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            report_type = data['report_type']
            date_range_start = data.get('date_range_start')
            date_range_end = data.get('date_range_end')
            parameters = data.get('parameters', {})

            # Generate the appropriate report
            if report_type == 'daily':
                report_data = generate_daily_report(date_range_start.date() if date_range_start else None)
            elif report_type == 'weekly':
                report_data = generate_weekly_report()
            elif report_type == 'monthly':
                report_data = generate_monthly_report()
            elif report_type == 'quarterly':
                report_data = generate_quarterly_report()
            else:
                # Custom report - use parameters
                report_data = {
                    'report_type': 'custom',
                    'parameters': parameters,
                    'data': {},
                }

            # Create report record
            report = Report.objects.create(
                name=f"{report_type.capitalize()} Report",
                report_type=report_type,
                generated_by=admin,
                title=request.data.get('title', f"{report_type.capitalize()} Report"),
                description=request.data.get('description', ''),
                data=report_data,
                format=request.data.get('format', 'json'),
                date_range_start=date_range_start,
                date_range_end=date_range_end,
                parameters=parameters,
                is_public=request.data.get('is_public', False),
                generated_at=timezone.now(),
            )

            log_audit_event(
                user_id=admin.id,
                action='generate_report',
                resource='report',
                resource_id=report.id,
                ip=get_client_ip(request),
                details={'report_type': report_type}
            )

            return Response({
                'message': 'Report generated successfully.',
                'report': ReportListSerializer(report).data,
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# AUDIT LOG VIEW
# ============================================================================

class AuditLogView(APIView):
    """
    View for viewing audit logs.
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanViewAuditLogs]

    def get(self, request):
        """
        Retrieve audit logs with filtering.
        """
        limit = int(request.query_params.get('limit', 50))
        user_id = request.query_params.get('user_id')
        action = request.query_params.get('action')
        content_type = request.query_params.get('content_type')

        queryset = AuditTrail.objects.select_related('user', 'content_type')

        if user_id:
            queryset = queryset.filter(user_id=user_id)
        if action:
            queryset = queryset.filter(action=action)
        if content_type:
            queryset = queryset.filter(content_type__model=content_type)

        queryset = queryset.order_by('-timestamp')[:limit]

        serializer = AuditTrailSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# SYSTEM SETTINGS VIEW
# ============================================================================

class SystemSettingsView(APIView):
    """
    View for managing system settings.
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanManageSettings]

    def get(self, request):
        """
        Get all system settings (public and admin-visible).
        """
        settings = SystemSetting.objects.filter(deleted_at__isnull=True)
        if not request.user.is_superuser:
            settings = settings.filter(is_public=True)
        serializer = SystemSettingSerializer(settings, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        """
        Create a new system setting.
        """
        serializer = SystemSettingCreateSerializer(data=request.data)
        if serializer.is_valid():
            setting = serializer.save()
            log_audit_event(
                user_id=request.user.id,
                action='create_system_setting',
                resource='system_setting',
                resource_id=setting.id,
                ip=get_client_ip(request),
                details={'key': setting.key}
            )
            return Response(SystemSettingSerializer(setting).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, key):
        """
        Update a system setting by key.
        """
        try:
            setting = SystemSetting.objects.get(key=key, deleted_at__isnull=True)
        except SystemSetting.DoesNotExist:
            raise NotFoundError(_('Setting not found.'))

        if not setting.editable:
            raise PermissionDeniedError(_('This setting is not editable.'))

        serializer = SystemSettingUpdateSerializer(setting, data=request.data, partial=True)
        if serializer.is_valid():
            setting = serializer.save()
            log_audit_event(
                user_id=request.user.id,
                action='update_system_setting',
                resource='system_setting',
                resource_id=setting.id,
                ip=get_client_ip(request),
                details={'key': setting.key}
            )
            return Response(SystemSettingSerializer(setting).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, key):
        """
        Soft delete a system setting.
        """
        try:
            setting = SystemSetting.objects.get(key=key, deleted_at__isnull=True)
        except SystemSetting.DoesNotExist:
            raise NotFoundError(_('Setting not found.'))

        if not setting.editable:
            raise PermissionDeniedError(_('This setting is not deletable.'))

        setting.deleted_at = timezone.now()
        setting.save()
        log_audit_event(
            user_id=request.user.id,
            action='delete_system_setting',
            resource='system_setting',
            resource_id=setting.id,
            ip=get_client_ip(request),
            details={'key': setting.key}
        )
        return Response({'message': 'Setting deleted.'}, status=status.HTTP_200_OK)


# ============================================================================
# ADMIN PREFERENCE VIEW
# ============================================================================

class AdminPreferenceView(APIView):
    """
    View for managing admin preferences.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        """
        Get current admin's preferences.
        """
        prefs, created = AdminPreference.objects.get_or_create(admin=request.user)
        serializer = AdminPreferenceSerializer(prefs)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        """
        Update current admin's preferences.
        """
        prefs, created = AdminPreference.objects.get_or_create(admin=request.user)
        serializer = AdminPreferenceUpdateSerializer(prefs, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# MAINTENANCE VIEW
# ============================================================================

class MaintenanceView(APIView):
    """
    View for system maintenance operations (admin only).
    """
    permission_classes = [IsAuthenticated, IsSuperAdmin, CanManageSystem]

    def post(self, request):
        """
        Perform maintenance tasks.
        """
        admin = request.user
        task = request.data.get('task')
        details = request.data.get('details', {})

        if task == 'clear_cache':
            success = clear_system_cache(admin.id)
            message = _('Cache cleared successfully.' if success else 'Cache clear failed.')
        elif task == 'run_maintenance':
            # Trigger maintenance tasks via Celery
            run_maintenance_tasks.delay()
            message = _('Maintenance tasks triggered.')
        elif task == 'backup':
            backup_admin_data.delay()
            message = _('Backup triggered.')
        elif task == 'sync_settings':
            sync_system_settings.delay()
            message = _('Settings sync triggered.')
        else:
            raise BadRequestError(_('Invalid task.'))

        log_audit_event(
            user_id=admin.id,
            action='maintenance',
            resource='system',
            resource_id=None,
            ip=get_client_ip(request),
            details={'task': task}
        )

        return Response({'message': message}, status=status.HTTP_200_OK)


# ============================================================================
# VIEWSETS FOR ADMIN MODELS
# ============================================================================

class AdminActionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing admin action logs.
    """
    queryset = AdminAction.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return AdminActionListSerializer
        return AdminActionDetailSerializer

    def get_permissions(self):
        return [IsAuthenticated(), IsAdminUser(), CanViewAuditLogs()]

    def get_queryset(self):
        queryset = super().get_queryset()
        admin_id = self.request.query_params.get('admin_id')
        user_id = self.request.query_params.get('user_id')
        action = self.request.query_params.get('action')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if admin_id:
            queryset = queryset.filter(admin_id=admin_id)
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        if action:
            queryset = queryset.filter(action=action)
        if date_from:
            queryset = queryset.filter(timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(timestamp__lte=date_to)

        ordering = self.request.query_params.get('ordering', '-timestamp')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('admin', 'user', 'group')


class AdminLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing admin logs.
    """
    queryset = AdminLog.objects.all()
    serializer_class = AdminLogListSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_permissions(self):
        return [IsAuthenticated(), IsAdminUser(), CanViewAuditLogs()]

    def get_queryset(self):
        queryset = super().get_queryset()
        admin_id = self.request.query_params.get('admin_id')
        level = self.request.query_params.get('level')
        module = self.request.query_params.get('module')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if admin_id:
            queryset = queryset.filter(admin_id=admin_id)
        if level:
            queryset = queryset.filter(level=level)
        if module:
            queryset = queryset.filter(module__icontains=module)
        if date_from:
            queryset = queryset.filter(timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(timestamp__lte=date_to)

        ordering = self.request.query_params.get('ordering', '-timestamp')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('admin')


class SystemSettingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing system settings (admin only).
    """
    queryset = SystemSetting.objects.filter(deleted_at__isnull=True)
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'create':
            return SystemSettingCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return SystemSettingUpdateSerializer
        return SystemSettingSerializer

    def get_permissions(self):
        return [IsAuthenticated(), IsAdminUser(), CanManageSettings()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(is_public=True)
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        ordering = self.request.query_params.get('ordering', 'key')
        queryset = queryset.order_by(ordering)
        return queryset

    def perform_create(self, serializer):
        setting = serializer.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='create_system_setting',
            resource='system_setting',
            resource_id=setting.id,
            ip=get_client_ip(self.request),
            details={'key': setting.key}
        )

    def perform_update(self, serializer):
        setting = serializer.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='update_system_setting',
            resource='system_setting',
            resource_id=setting.id,
            ip=get_client_ip(self.request),
            details={'key': setting.key}
        )

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='delete_system_setting',
            resource='system_setting',
            resource_id=instance.id,
            ip=get_client_ip(self.request),
            details={'key': instance.key}
        )

    @action(detail=False, methods=['post'])
    def bulk_update(self, request):
        """
        Bulk update multiple system settings.
        """
        serializer = SystemSettingBulkUpdateSerializer(data=request.data)
        if serializer.is_valid():
            settings_data = serializer.validated_data['settings']
            updated = []
            for key, value in settings_data.items():
                try:
                    setting = SystemSetting.objects.get(key=key, deleted_at__isnull=True)
                    if setting.editable:
                        setting.value = value
                        setting.save()
                        updated.append(key)
                except SystemSetting.DoesNotExist:
                    pass
            return Response({
                'message': f'Updated {len(updated)} settings.',
                'updated': updated,
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ReportViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing reports.
    """
    queryset = Report.objects.filter(deleted_at__isnull=True)
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return ReportListSerializer
        elif self.action == 'retrieve':
            return ReportDetailSerializer
        elif self.action == 'create':
            return ReportCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ReportUpdateSerializer
        return ReportListSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsAdminUser(), CanGenerateReports()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsAdminUser(), CanGenerateReports()]
        return [IsAuthenticated(), IsAdminUser(), CanViewReports()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(is_public=True) | queryset.filter(generated_by=self.request.user)
        report_type = self.request.query_params.get('report_type')
        if report_type:
            queryset = queryset.filter(report_type=report_type)
        generated_by = self.request.query_params.get('generated_by')
        if generated_by:
            queryset = queryset.filter(generated_by_id=generated_by)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(generated_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(generated_at__lte=date_to)
        ordering = self.request.query_params.get('ordering', '-generated_at')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('generated_by')

    def perform_create(self, serializer):
        if not serializer.validated_data.get('generated_by'):
            serializer.save(generated_by=self.request.user)
        else:
            serializer.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='create_report',
            resource='report',
            resource_id=serializer.instance.id,
            ip=get_client_ip(self.request),
            details={'report_type': serializer.instance.report_type}
        )

    def perform_update(self, serializer):
        report = serializer.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='update_report',
            resource='report',
            resource_id=report.id,
            ip=get_client_ip(self.request)
        )

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='delete_report',
            resource='report',
            resource_id=instance.id,
            ip=get_client_ip(self.request)
        )

    @action(detail=True, methods=['post'])
    def download(self, request, id=None):
        """
        Download a report file.
        """
        report = self.get_object()
        if report.is_expired:
            raise BadRequestError(_('Report has expired.'))
        if not report.is_public and report.generated_by != request.user and not request.user.is_superuser:
            raise PermissionDeniedError(_('You do not have permission to download this report.'))

        report.increment_download()
        # In a real implementation, we would return the actual file
        return Response({
            'message': 'Download initiated.',
            'download_url': f'/api/v1/admin/reports/{report.id}/file/',
        }, status=status.HTTP_200_OK)


class ReportScheduleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing report schedules.
    """
    queryset = ReportSchedule.objects.filter(deleted_at__isnull=True)
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return ReportScheduleListSerializer
        elif self.action == 'create':
            return ReportScheduleCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ReportScheduleUpdateSerializer
        return ReportScheduleListSerializer

    def get_permissions(self):
        return [IsAuthenticated(), IsAdminUser(), CanGenerateReports()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(created_by=self.request.user)
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        frequency = self.request.query_params.get('frequency')
        if frequency:
            queryset = queryset.filter(frequency=frequency)
        ordering = self.request.query_params.get('ordering', 'next_run')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('created_by')

    def perform_create(self, serializer):
        if not serializer.validated_data.get('created_by'):
            serializer.save(created_by=self.request.user)
        else:
            serializer.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='create_report_schedule',
            resource='report_schedule',
            resource_id=serializer.instance.id,
            ip=get_client_ip(self.request)
        )

    def perform_update(self, serializer):
        schedule = serializer.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='update_report_schedule',
            resource='report_schedule',
            resource_id=schedule.id,
            ip=get_client_ip(self.request)
        )

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='delete_report_schedule',
            resource='report_schedule',
            resource_id=instance.id,
            ip=get_client_ip(self.request)
        )

    @action(detail=True, methods=['post'])
    def run_now(self, request, id=None):
        """
        Run a report schedule immediately.
        """
        schedule = self.get_object()
        if not schedule.is_active:
            raise BadRequestError(_('Schedule is not active.'))
        result = schedule.run()
        return Response({
            'message': 'Schedule executed successfully.',
            'schedule': ReportScheduleListSerializer(schedule).data,
        }, status=status.HTTP_200_OK)


class AuditTrailViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing audit trails.
    """
    queryset = AuditTrail.objects.all()
    serializer_class = AuditTrailSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_permissions(self):
        return [IsAuthenticated(), IsAdminUser(), CanViewAuditLogs()]

    def get_queryset(self):
        queryset = super().get_queryset()
        user_id = self.request.query_params.get('user_id')
        action = self.request.query_params.get('action')
        content_type = self.request.query_params.get('content_type')
        object_id = self.request.query_params.get('object_id')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if user_id:
            queryset = queryset.filter(user_id=user_id)
        if action:
            queryset = queryset.filter(action=action)
        if content_type:
            queryset = queryset.filter(content_type__model=content_type)
        if object_id:
            queryset = queryset.filter(object_id=object_id)
        if date_from:
            queryset = queryset.filter(timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(timestamp__lte=date_to)

        ordering = self.request.query_params.get('ordering', '-timestamp')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('user', 'content_type')


class DashboardWidgetViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing dashboard widgets.
    """
    queryset = DashboardWidget.objects.filter(deleted_at__isnull=True)
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return DashboardWidgetSerializer
        elif self.action == 'create':
            return DashboardWidgetCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return DashboardWidgetUpdateSerializer
        return DashboardWidgetSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsAdminUser(), CanManageSettings()]
        return [IsAuthenticated(), IsAdminUser(), CanViewDashboard()]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_superuser:
            queryset = queryset.filter(Q(admin=user) | Q(is_system=True))
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        widget_type = self.request.query_params.get('widget_type')
        if widget_type:
            queryset = queryset.filter(widget_type=widget_type)
        ordering = self.request.query_params.get('ordering', 'order')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('admin')

    def perform_create(self, serializer):
        if not serializer.validated_data.get('admin') and not serializer.validated_data.get('is_system'):
            serializer.save(admin=self.request.user)
        else:
            serializer.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='create_dashboard_widget',
            resource='dashboard_widget',
            resource_id=serializer.instance.id,
            ip=get_client_ip(self.request)
        )

    def perform_update(self, serializer):
        widget = serializer.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='update_dashboard_widget',
            resource='dashboard_widget',
            resource_id=widget.id,
            ip=get_client_ip(self.request)
        )

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save()
        log_audit_event(
            user_id=self.request.user.id,
            action='delete_dashboard_widget',
            resource='dashboard_widget',
            resource_id=instance.id,
            ip=get_client_ip(self.request)
        )


# ============================================================================
# BULK ACTION VIEW
# ============================================================================

class AdminBulkActionView(APIView):
    """
    View for performing bulk actions on resources (admin only).
    """
    permission_classes = [IsAuthenticated, IsSuperAdmin, CanPerformBulkActions]

    def post(self, request):
        """
        Perform a bulk action on users, groups, or payments.
        """
        admin = request.user
        serializer = AdminBulkActionSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            action = data['action']
            ids = data['ids']
            resource_type = data['resource_type']
            details = data.get('details', {})

            results = {
                'total': len(ids),
                'success': 0,
                'failed': 0,
                'errors': [],
            }

            if resource_type == 'user':
                queryset = User.objects.filter(id__in=ids, deleted_at__isnull=True)
                for user in queryset:
                    try:
                        if action == 'suspend':
                            suspend_user(user.id, details.get('reason', ''), admin.id)
                        elif action == 'activate':
                            activate_user(user.id, admin.id)
                        elif action == 'delete':
                            delete_user(user.id, admin.id, details.get('reason', ''))
                        elif action == 'verify':
                            verify_user_identity(user.id, admin.id)
                        else:
                            raise ValueError(f'Invalid action {action} for users.')
                        results['success'] += 1
                    except Exception as e:
                        results['failed'] += 1
                        results['errors'].append({'id': user.id, 'error': str(e)})

            elif resource_type == 'group':
                queryset = Group.objects.filter(id__in=ids, deleted_at__isnull=True)
                for group in queryset:
                    try:
                        if action == 'approve':
                            approve_group(group.id, admin.id)
                        elif action == 'complete':
                            complete_group(group.id, admin.id)
                        elif action == 'cancel':
                            cancel_group(group.id, admin.id, details.get('reason', ''))
                        elif action == 'pause':
                            pause_group(group.id, admin.id, details.get('reason', ''))
                        elif action == 'resume':
                            resume_group(group.id, admin.id)
                        else:
                            raise ValueError(f'Invalid action {action} for groups.')
                        results['success'] += 1
                    except Exception as e:
                        results['failed'] += 1
                        results['errors'].append({'id': group.id, 'error': str(e)})

            elif resource_type == 'payment':
                queryset = Payment.objects.filter(id__in=ids, deleted_at__isnull=True)
                for payment in queryset:
                    try:
                        if action == 'refund':
                            refund_payment_manually(payment.id, admin.id, details.get('reason', ''))
                        elif action == 'fail':
                            mark_payment_as_failed(payment.id, admin.id, details.get('reason', ''))
                        else:
                            raise ValueError(f'Invalid action {action} for payments.')
                        results['success'] += 1
                    except Exception as e:
                        results['failed'] += 1
                        results['errors'].append({'id': payment.id, 'error': str(e)})

            elif resource_type == 'contribution':
                queryset = Contribution.objects.filter(id__in=ids, deleted_at__isnull=True)
                for contribution in queryset:
                    try:
                        if action == 'mark_paid':
                            contribution.mark_as_paid()
                        elif action == 'refund':
                            contribution.refund(details.get('reason', ''))
                        elif action == 'waive':
                            amount = details.get('amount', 0)
                            contribution.waive(Decimal(str(amount)), details.get('reason', ''))
                        else:
                            raise ValueError(f'Invalid action {action} for contributions.')
                        results['success'] += 1
                    except Exception as e:
                        results['failed'] += 1
                        results['errors'].append({'id': contribution.id, 'error': str(e)})

            else:
                raise BadRequestError(_('Invalid resource_type.'))

            log_audit_event(
                user_id=admin.id,
                action='bulk_operation',
                resource=resource_type,
                resource_id=None,
                ip=get_client_ip(request),
                details={'action': action, 'count': results['success'], 'failed': results['failed']}
            )

            return Response(results, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)