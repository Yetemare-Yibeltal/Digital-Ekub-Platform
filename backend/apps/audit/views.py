"""
Views for the audit app.

This module provides all API views for audit and monitoring functionality:
- Audit Log CRUD and filtering
- Audit Event processing and management
- Audit Rule CRUD and evaluation
- Audit Alert management (acknowledge, resolve, dismiss)
- Audit Report generation and management
- Audit Retention Policy management
- Security Event logging and monitoring
- User Activity tracking
- System Health monitoring
- Performance Metrics collection
- Anomaly Detection and management
- Audit and Security statistics

All views use appropriate permissions and include comprehensive logging,
pagination, filtering, and error handling with transaction management.
"""

from django.db import transaction
from django.db.models import Q, Count, Sum, Avg, F, OuterRef, Subquery, Min, Max
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
from apps.groups.models import Group
from apps.common.pagination import CustomPagination
from apps.common.permissions import IsAuthenticated, IsActiveUser, IsSuperAdminUser, IsAdminUser
from apps.common.exceptions import BadRequestError, NotFoundError, PermissionDeniedError, ConflictError
from apps.common.utils import log_audit_event, get_client_ip, format_currency

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
from .serializers import (
    AuditLogListSerializer,
    AuditLogDetailSerializer,
    AuditLogCreateSerializer,
    AuditEventListSerializer,
    AuditEventDetailSerializer,
    AuditEventCreateSerializer,
    AuditRuleListSerializer,
    AuditRuleDetailSerializer,
    AuditRuleCreateSerializer,
    AuditRuleUpdateSerializer,
    AuditAlertListSerializer,
    AuditAlertDetailSerializer,
    AuditAlertAcknowledgeSerializer,
    AuditReportListSerializer,
    AuditReportCreateSerializer,
    AuditRetentionPolicySerializer,
    AuditRetentionPolicyCreateSerializer,
    SecurityEventListSerializer,
    SecurityEventCreateSerializer,
    UserActivitySerializer,
    UserActivityCreateSerializer,
    SystemHealthSerializer,
    SystemHealthCreateSerializer,
    PerformanceMetricSerializer,
    PerformanceMetricCreateSerializer,
    AnomalyDetectionListSerializer,
    AnomalyDetectionCreateSerializer,
    AnomalyDetectionUpdateSerializer,
    AuditStatisticsSerializer,
    SecurityStatisticsSerializer,
)
from .permissions import (
    CanViewAuditLogs,
    CanManageAuditRules,
    CanManageAuditAlerts,
    CanGenerateAuditReports,
    CanViewSecurityEvents,
    CanViewSystemHealth,
    CanViewPerformanceMetrics,
    CanManageAnomalies,
    IsAuditor,
    IsSecurityAdmin,
    IsSystemAdmin,
)
from . import (
    create_audit_log,
    create_audit_event,
    evaluate_rules,
    generate_audit_report,
    enforce_retention_policies,
    check_system_health,
    record_performance_metric,
    detect_anomalies,
    get_audit_statistics,
    get_security_statistics,
    get_user_activity_summary,
)

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# AUDIT LOG VIEW SET
# ============================================================================

class AuditLogViewSet(viewsets.ModelViewSet):
    """
    ViewSet for AuditLog model with full CRUD and filtering.
    """
    queryset = AuditLog.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return AuditLogListSerializer
        elif self.action == 'retrieve':
            return AuditLogDetailSerializer
        elif self.action == 'create':
            return AuditLogCreateSerializer
        return AuditLogListSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsActiveUser()]
        else:
            return [IsAuthenticated(), IsAdminUser(), CanViewAuditLogs()]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        # Filter by user
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        # Filter by action
        action = self.request.query_params.get('action')
        if action:
            queryset = queryset.filter(action=action)

        # Filter by resource
        resource = self.request.query_params.get('resource')
        if resource:
            queryset = queryset.filter(resource=resource)

        # Filter by resource_id
        resource_id = self.request.query_params.get('resource_id')
        if resource_id:
            queryset = queryset.filter(resource_id=resource_id)

        # Filter by severity
        severity = self.request.query_params.get('severity')
        if severity:
            queryset = queryset.filter(severity=severity)

        # Date range filters
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(timestamp__lte=date_to)

        # Search
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(action__icontains=search) |
                Q(resource__icontains=search) |
                Q(details__icontains=search) |
                Q(ip_address__icontains=search)
            )

        # Ordering
        ordering = self.request.query_params.get('ordering', '-timestamp')
        queryset = queryset.order_by(ordering)

        return queryset.select_related('user')

    def perform_create(self, serializer):
        with transaction.atomic():
            log_entry = serializer.save(timestamp=timezone.now())
            logger.info(f'Audit log created: {log_entry.action} on {log_entry.resource}')
            log_audit_event(
                user_id=self.request.user.id,
                action='audit_log_create',
                resource='audit_log',
                resource_id=log_entry.id,
                ip=get_client_ip(self.request)
            )

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        Get audit log statistics.
        """
        from . import get_audit_statistics
        stats = get_audit_statistics()
        serializer = AuditStatisticsSerializer(stats)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """
        Get a summary of audit logs (for dashboard).
        """
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timezone.timedelta(days=7)

        total = AuditLog.objects.count()
        today_count = AuditLog.objects.filter(timestamp__gte=today_start).count()
        week_count = AuditLog.objects.filter(timestamp__gte=week_start).count()

        by_severity = AuditLog.objects.values('severity').annotate(count=Count('id')).order_by('-count')
        by_action = AuditLog.objects.values('action').annotate(count=Count('id')).order_by('-count')[:10]

        return Response({
            'total': total,
            'today_count': today_count,
            'week_count': week_count,
            'by_severity': list(by_severity),
            'top_actions': list(by_action),
        }, status=status.HTTP_200_OK)


# ============================================================================
# AUDIT EVENT VIEW SET
# ============================================================================

class AuditEventViewSet(viewsets.ModelViewSet):
    """
    ViewSet for AuditEvent model.
    """
    queryset = AuditEvent.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return AuditEventListSerializer
        elif self.action == 'retrieve':
            return AuditEventDetailSerializer
        elif self.action == 'create':
            return AuditEventCreateSerializer
        return AuditEventListSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsActiveUser()]
        else:
            return [IsAuthenticated(), IsAdminUser(), CanViewAuditLogs()]

    def get_queryset(self):
        queryset = super().get_queryset()
        event_type = self.request.query_params.get('event_type')
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        processed = self.request.query_params.get('processed')
        if processed is not None:
            queryset = queryset.filter(processed=processed.lower() == 'true')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(created_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__lte=date_to)
        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('user', 'group')

    def perform_create(self, serializer):
        with transaction.atomic():
            event = serializer.save()
            logger.info(f'Audit event created: {event.event_type}')
            # Trigger processing if not automatically processed
            if not event.processed:
                from .tasks import process_audit_event
                process_audit_event.delay(event.id)

    @action(detail=True, methods=['post'])
    def process(self, request, id=None):
        """
        Process an audit event manually.
        """
        event = self.get_object()
        if event.processed:
            return Response({'message': 'Event already processed.'}, status=status.HTTP_200_OK)
        success = event.process()
        return Response({
            'message': 'Event processed successfully.' if success else 'Event processing failed.',
            'event': AuditEventListSerializer(event).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def retry(self, request, id=None):
        """
        Retry processing a failed event.
        """
        event = self.get_object()
        if event.processed:
            return Response({'message': 'Event already processed.'}, status=status.HTTP_200_OK)
        success = event.retry()
        return Response({
            'message': 'Event retry initiated.' if success else 'Retry failed.',
            'event': AuditEventListSerializer(event).data
        }, status=status.HTTP_200_OK)


# ============================================================================
# AUDIT RULE VIEW SET
# ============================================================================

class AuditRuleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for AuditRule model.
    """
    queryset = AuditRule.objects.filter(deleted_at__isnull=True)
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return AuditRuleListSerializer
        elif self.action == 'retrieve':
            return AuditRuleDetailSerializer
        elif self.action == 'create':
            return AuditRuleCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AuditRuleUpdateSerializer
        return AuditRuleListSerializer

    def get_permissions(self):
        return [IsAuthenticated(), IsAdminUser(), CanManageAuditRules()]

    def get_queryset(self):
        queryset = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        severity = self.request.query_params.get('severity')
        if severity:
            queryset = queryset.filter(severity=severity)
        action = self.request.query_params.get('action')
        if action:
            queryset = queryset.filter(action=action)
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search)
            )
        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)
        return queryset

    def perform_create(self, serializer):
        with transaction.atomic():
            rule = serializer.save()
            logger.info(f'Audit rule created: {rule.name}')

    def perform_update(self, serializer):
        with transaction.atomic():
            rule = serializer.save()
            logger.info(f'Audit rule updated: {rule.name}')

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance.deleted_at = timezone.now()
            instance.save()
            logger.info(f'Audit rule deleted: {instance.name}')

    @action(detail=True, methods=['post'])
    def evaluate(self, request, id=None):
        """
        Evaluate a rule against a specific audit log.
        """
        rule = self.get_object()
        audit_log_id = request.data.get('audit_log_id')
        if not audit_log_id:
            raise BadRequestError(_('audit_log_id is required.'))
        try:
            audit_log = AuditLog.objects.get(id=audit_log_id)
        except AuditLog.DoesNotExist:
            raise NotFoundError(_('Audit log not found.'))
        matches = rule.evaluate(audit_log)
        return Response({
            'matches': matches,
            'rule': AuditRuleListSerializer(rule).data,
            'audit_log': AuditLogListSerializer(audit_log).data,
        }, status=status.HTTP_200_OK)


# ============================================================================
# AUDIT ALERT VIEW SET
# ============================================================================

class AuditAlertViewSet(viewsets.ModelViewSet):
    """
    ViewSet for AuditAlert model.
    """
    queryset = AuditAlert.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return AuditAlertListSerializer
        elif self.action == 'retrieve':
            return AuditAlertDetailSerializer
        return AuditAlertListSerializer

    def get_permissions(self):
        return [IsAuthenticated(), IsAdminUser(), CanManageAuditAlerts()]

    def get_queryset(self):
        queryset = super().get_queryset()
        rule_id = self.request.query_params.get('rule_id')
        if rule_id:
            queryset = queryset.filter(rule_id=rule_id)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        severity = self.request.query_params.get('severity')
        if severity:
            queryset = queryset.filter(severity=severity)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(timestamp__lte=date_to)
        ordering = self.request.query_params.get('ordering', '-timestamp')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('rule', 'audit_log', 'acknowledged_by')

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, id=None):
        """
        Acknowledge an alert.
        """
        alert = self.get_object()
        if alert.status != 'new':
            raise BadRequestError(_('Alert is not in new status.'))
        user = request.user
        alert.acknowledge(user)
        logger.info(f'Alert {alert.id} acknowledged by {user.email}')
        return Response({
            'message': 'Alert acknowledged.',
            'alert': AuditAlertListSerializer(alert).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def resolve(self, request, id=None):
        """
        Resolve an alert.
        """
        alert = self.get_object()
        if alert.status in ['resolved', 'dismissed']:
            raise BadRequestError(_('Alert already resolved or dismissed.'))
        alert.resolve()
        logger.info(f'Alert {alert.id} resolved')
        return Response({
            'message': 'Alert resolved.',
            'alert': AuditAlertListSerializer(alert).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def dismiss(self, request, id=None):
        """
        Dismiss an alert.
        """
        alert = self.get_object()
        if alert.status != 'new':
            raise BadRequestError(_('Only new alerts can be dismissed.'))
        alert.dismiss()
        logger.info(f'Alert {alert.id} dismissed')
        return Response({
            'message': 'Alert dismissed.',
            'alert': AuditAlertListSerializer(alert).data
        }, status=status.HTTP_200_OK)


# ============================================================================
# AUDIT REPORT VIEW SET
# ============================================================================

class AuditReportViewSet(viewsets.ModelViewSet):
    """
    ViewSet for AuditReport model.
    """
    queryset = AuditReport.objects.filter(deleted_at__isnull=True)
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return AuditReportListSerializer
        elif self.action == 'create':
            return AuditReportCreateSerializer
        return AuditReportListSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsAdminUser(), CanGenerateAuditReports()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsAdminUser(), CanGenerateAuditReports()]
        return [IsAuthenticated(), IsAdminUser(), CanViewAuditLogs()]

    def get_queryset(self):
        queryset = super().get_queryset()
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
        with transaction.atomic():
            if not serializer.validated_data.get('generated_by'):
                serializer.save(generated_by=self.request.user)
            else:
                serializer.save()
            report = serializer.instance
            logger.info(f'Audit report generated: {report.name}')
            log_audit_event(
                user_id=self.request.user.id,
                action='generate_audit_report',
                resource='audit_report',
                resource_id=report.id,
                ip=get_client_ip(self.request)
            )

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance.deleted_at = timezone.now()
            instance.save()
            logger.info(f'Audit report deleted: {instance.name}')

    @action(detail=True, methods=['post'])
    def download(self, request, id=None):
        """
        Download an audit report.
        """
        report = self.get_object()
        if report.expires_at and report.expires_at <= timezone.now():
            raise BadRequestError(_('Report has expired.'))
        report.download_count += 1
        report.save(update_fields=['download_count'])
        # In a real implementation, return the actual file
        return Response({
            'message': 'Download initiated.',
            'report_id': report.id,
            'download_url': f'/api/v1/audit/reports/{report.id}/file/',
        }, status=status.HTTP_200_OK)


# ============================================================================
# AUDIT RETENTION POLICY VIEW SET
# ============================================================================

class AuditRetentionPolicyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for AuditRetentionPolicy model.
    """
    queryset = AuditRetentionPolicy.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'create':
            return AuditRetentionPolicyCreateSerializer
        return AuditRetentionPolicySerializer

    def get_permissions(self):
        return [IsAuthenticated(), IsSuperAdminUser()]

    def get_queryset(self):
        queryset = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        ordering = self.request.query_params.get('ordering', 'resource_type')
        queryset = queryset.order_by(ordering)
        return queryset

    def perform_create(self, serializer):
        with transaction.atomic():
            policy = serializer.save()
            logger.info(f'Retention policy created: {policy.resource_type} - {policy.retention_days} days')

    def perform_update(self, serializer):
        with transaction.atomic():
            policy = serializer.save()
            logger.info(f'Retention policy updated: {policy.resource_type} - {policy.retention_days} days')

    @action(detail=True, methods=['post'])
    def enforce(self, request, id=None):
        """
        Enforce a retention policy immediately.
        """
        policy = self.get_object()
        if not policy.is_active:
            raise BadRequestError(_('Policy is not active.'))
        deleted = policy.enforce()
        return Response({
            'message': f'Retention policy enforced. Deleted {deleted} records.',
            'deleted_count': deleted,
        }, status=status.HTTP_200_OK)


# ============================================================================
# SECURITY EVENT VIEW SET
# ============================================================================

class SecurityEventViewSet(viewsets.ModelViewSet):
    """
    ViewSet for SecurityEvent model.
    """
    queryset = SecurityEvent.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return SecurityEventListSerializer
        elif self.action == 'create':
            return SecurityEventCreateSerializer
        return SecurityEventListSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsActiveUser()]
        else:
            return [IsAuthenticated(), IsAdminUser(), CanViewSecurityEvents()]

    def get_queryset(self):
        queryset = super().get_queryset()
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        event_type = self.request.query_params.get('event_type')
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        severity = self.request.query_params.get('severity')
        if severity:
            queryset = queryset.filter(severity=severity)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(timestamp__lte=date_to)
        ordering = self.request.query_params.get('ordering', '-timestamp')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('user')

    def perform_create(self, serializer):
        with transaction.atomic():
            event = serializer.save(timestamp=timezone.now())
            logger.warning(f'Security event: {event.event_type} - {event.user.email}')
            # If severity is critical, trigger immediate alert
            if event.severity == 'critical':
                from .tasks import send_security_alert
                send_security_alert.delay(event.id)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        Get security event statistics.
        """
        from . import get_security_statistics
        stats = get_security_statistics()
        serializer = SecurityStatisticsSerializer(stats)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# USER ACTIVITY VIEW SET
# ============================================================================

class UserActivityViewSet(viewsets.ModelViewSet):
    """
    ViewSet for UserActivity model.
    """
    queryset = UserActivity.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return UserActivitySerializer
        elif self.action == 'create':
            return UserActivityCreateSerializer
        return UserActivitySerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsActiveUser()]
        else:
            return [IsAuthenticated(), IsAdminUser(), CanViewAuditLogs()]

    def get_queryset(self):
        queryset = super().get_queryset()
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        action = self.request.query_params.get('action')
        if action:
            queryset = queryset.filter(action=action)
        resource = self.request.query_params.get('resource')
        if resource:
            queryset = queryset.filter(resource=resource)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(timestamp__lte=date_to)
        ordering = self.request.query_params.get('ordering', '-timestamp')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('user')

    def perform_create(self, serializer):
        with transaction.atomic():
            activity = serializer.save(timestamp=timezone.now())
            logger.debug(f'User activity: {activity.user.email} - {activity.action}')

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """
        Get user activity summary.
        """
        from . import get_user_activity_summary
        user_id = request.query_params.get('user_id')
        if user_id:
            summary = get_user_activity_summary(user_id=user_id)
        else:
            summary = get_user_activity_summary()
        return Response(summary, status=status.HTTP_200_OK)


# ============================================================================
# SYSTEM HEALTH VIEW SET
# ============================================================================

class SystemHealthViewSet(viewsets.ModelViewSet):
    """
    ViewSet for SystemHealth model.
    """
    queryset = SystemHealth.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'create':
            return SystemHealthCreateSerializer
        return SystemHealthSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsSystemAdmin()]
        else:
            return [IsAuthenticated(), IsAdminUser(), CanViewSystemHealth()]

    def get_queryset(self):
        queryset = super().get_queryset()
        component = self.request.query_params.get('component')
        if component:
            queryset = queryset.filter(component=component)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(checked_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(checked_at__lte=date_to)
        ordering = self.request.query_params.get('ordering', '-checked_at')
        queryset = queryset.order_by(ordering)
        return queryset

    def perform_create(self, serializer):
        with transaction.atomic():
            health = serializer.save(checked_at=timezone.now())
            logger.info(f'System health check: {health.component} - {health.status}')
            if health.status in ['error', 'degraded']:
                from .tasks import send_health_alert
                send_health_alert.delay(health.id)


# ============================================================================
# PERFORMANCE METRIC VIEW SET
# ============================================================================

class PerformanceMetricViewSet(viewsets.ModelViewSet):
    """
    ViewSet for PerformanceMetric model.
    """
    queryset = PerformanceMetric.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return PerformanceMetricSerializer
        elif self.action == 'create':
            return PerformanceMetricCreateSerializer
        return PerformanceMetricSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsActiveUser()]
        else:
            return [IsAuthenticated(), IsAdminUser(), CanViewPerformanceMetrics()]

    def get_queryset(self):
        queryset = super().get_queryset()
        metric_name = self.request.query_params.get('metric_name')
        if metric_name:
            queryset = queryset.filter(metric_name=metric_name)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(timestamp__lte=date_to)
        ordering = self.request.query_params.get('ordering', '-timestamp')
        queryset = queryset.order_by(ordering)
        return queryset

    def perform_create(self, serializer):
        with transaction.atomic():
            metric = serializer.save(timestamp=timezone.now())
            logger.debug(f'Performance metric: {metric.metric_name} = {metric.value} {metric.unit}')

    @action(detail=False, methods=['get'])
    def aggregate(self, request):
        """
        Get aggregate statistics for a metric.
        """
        metric_name = request.query_params.get('metric_name')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        if not metric_name:
            raise BadRequestError(_('metric_name is required.'))
        if not date_from or not date_to:
            raise BadRequestError(_('date_from and date_to are required.'))

        try:
            start = timezone.datetime.fromisoformat(date_from)
            end = timezone.datetime.fromisoformat(date_to)
        except ValueError:
            raise BadRequestError(_('Invalid date format. Use ISO format.'))

        from .models import PerformanceMetric
        stats = PerformanceMetric.get_aggregate(metric_name, start, end)
        return Response(stats, status=status.HTTP_200_OK)


# ============================================================================
# ANOMALY DETECTION VIEW SET
# ============================================================================

class AnomalyDetectionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for AnomalyDetection model.
    """
    queryset = AnomalyDetection.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return AnomalyDetectionListSerializer
        elif self.action == 'create':
            return AnomalyDetectionCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AnomalyDetectionUpdateSerializer
        return AnomalyDetectionListSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsSystemAdmin()]
        else:
            return [IsAuthenticated(), IsAdminUser(), CanManageAnomalies()]

    def get_queryset(self):
        queryset = super().get_queryset()
        anomaly_type = self.request.query_params.get('anomaly_type')
        if anomaly_type:
            queryset = queryset.filter(anomaly_type=anomaly_type)
        metric_name = self.request.query_params.get('metric_name')
        if metric_name:
            queryset = queryset.filter(metric_name=metric_name)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        severity = self.request.query_params.get('severity')
        if severity:
            queryset = queryset.filter(severity=severity)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(detected_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(detected_at__lte=date_to)
        ordering = self.request.query_params.get('ordering', '-detected_at')
        queryset = queryset.order_by(ordering)
        return queryset

    def perform_create(self, serializer):
        with transaction.atomic():
            anomaly = serializer.save(detected_at=timezone.now())
            logger.warning(f'Anomaly detected: {anomaly.anomaly_type} on {anomaly.metric_name}')
            if anomaly.severity in ['error', 'critical']:
                from .tasks import send_anomaly_alert
                send_anomaly_alert.delay(anomaly.id)

    def perform_update(self, serializer):
        with transaction.atomic():
            anomaly = serializer.save()
            logger.info(f'Anomaly {anomaly.id} updated to status: {anomaly.status}')

    @action(detail=True, methods=['post'])
    def resolve(self, request, id=None):
        """
        Resolve an anomaly.
        """
        anomaly = self.get_object()
        if anomaly.status in ['resolved', 'false_positive']:
            raise BadRequestError(_('Anomaly already resolved or marked as false positive.'))
        anomaly.resolve()
        return Response({
            'message': 'Anomaly resolved.',
            'anomaly': AnomalyDetectionListSerializer(anomaly).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def mark_false_positive(self, request, id=None):
        """
        Mark an anomaly as a false positive.
        """
        anomaly = self.get_object()
        if anomaly.status in ['resolved', 'false_positive']:
            raise BadRequestError(_('Anomaly already resolved or marked as false positive.'))
        anomaly.mark_false_positive()
        return Response({
            'message': 'Anomaly marked as false positive.',
            'anomaly': AnomalyDetectionListSerializer(anomaly).data
        }, status=status.HTTP_200_OK)


# ============================================================================
# AUDIT STATISTICS VIEW
# ============================================================================

class AuditStatisticsView(APIView):
    """
    View for audit statistics (admin only).
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanViewAuditLogs]

    def get(self, request):
        from . import get_audit_statistics
        stats = get_audit_statistics()
        serializer = AuditStatisticsSerializer(stats)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# SECURITY STATISTICS VIEW
# ============================================================================

class SecurityStatisticsView(APIView):
    """
    View for security statistics (admin only).
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanViewSecurityEvents]

    def get(self, request):
        from . import get_security_statistics
        stats = get_security_statistics()
        serializer = SecurityStatisticsSerializer(stats)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# SYSTEM HEALTH OVERVIEW VIEW
# ============================================================================

class SystemHealthOverviewView(APIView):
    """
    View for system health overview (admin only).
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanViewSystemHealth]

    def get(self, request):
        # Get latest health check for each component
        components = SystemHealth.objects.values('component').distinct()
        latest = []
        for comp in components:
            health = SystemHealth.objects.filter(component=comp['component']).order_by('-checked_at').first()
            if health:
                latest.append(health)
        serializer = SystemHealthSerializer(latest, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# PERFORMANCE METRICS OVERVIEW VIEW
# ============================================================================

class PerformanceMetricsOverviewView(APIView):
    """
    View for performance metrics overview (admin only).
    """
    permission_classes = [IsAuthenticated, IsAdminUser, CanViewPerformanceMetrics]

    def get(self, request):
        # Get latest metrics for each metric_name
        metric_names = PerformanceMetrics.objects.values('metric_name').distinct()
        latest = []
        for mn in metric_names:
            metric = PerformanceMetrics.objects.filter(metric_name=mn['metric_name']).order_by('-timestamp').first()
            if metric:
                latest.append(metric)
        serializer = PerformanceMetricSerializer(latest, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)