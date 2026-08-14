"""
Views for the notifications app.

This module provides all API views for notification management including:
- Notification CRUD operations (create, list, retrieve, update, delete)
- Notification preferences management
- Notification templates management
- Notification delivery tracking
- Scheduled notifications
- Notification digests (daily, weekly)
- Bulk notification sending
- Notification statistics and analytics
- Mark all as read, clear all notifications
- Webhook handling for notification events

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

from apps.users.models import User
from apps.groups.models import Group, GroupMember
from apps.common.pagination import CustomPagination
from apps.common.permissions import IsAuthenticated, IsActiveUser, IsSuperAdminUser, IsAdminUser
from apps.common.exceptions import BadRequestError, NotFoundError, PermissionDeniedError, ConflictError
from apps.common.utils import log_audit_event, get_client_ip

from .models import (
    Notification,
    NotificationTemplate,
    NotificationPreference,
    NotificationChannel,
    NotificationDelivery,
    NotificationEvent,
    NotificationSchedule,
    NotificationDigest,
    NotificationAudit,
)
from .serializers import (
    NotificationListSerializer,
    NotificationDetailSerializer,
    NotificationCreateSerializer,
    NotificationUpdateSerializer,
    NotificationTemplateSerializer,
    NotificationTemplateCreateSerializer,
    NotificationTemplateUpdateSerializer,
    NotificationPreferenceSerializer,
    NotificationPreferenceUpdateSerializer,
    NotificationChannelSerializer,
    NotificationDeliverySerializer,
    NotificationEventSerializer,
    NotificationEventCreateSerializer,
    NotificationScheduleSerializer,
    NotificationScheduleCreateSerializer,
    NotificationDigestSerializer,
    NotificationAuditSerializer,
    BulkNotificationSerializer,
    NotificationStatsSerializer,
    MarkAllReadSerializer,
    ClearNotificationsSerializer,
)
from .permissions import (
    IsNotificationOwner,
    IsNotificationOwnerOrAdmin,
    CanViewNotification,
    CanCreateNotification,
    CanUpdateNotification,
    CanDeleteNotification,
    CanSendNotification,
    CanManageTemplates,
    CanManagePreferences,
    CanViewStats,
    IsAdminNotification,
)
from .tasks import (
    process_pending_notifications,
    send_notification,
    send_bulk_notifications,
    send_daily_digest,
    send_weekly_digest,
    process_scheduled_notifications,
    retry_failed_notifications,
    cleanup_notifications,
    send_event_notifications,
)

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# NOTIFICATION VIEW SET
# ============================================================================

class NotificationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Notification model with full CRUD and additional actions.

    Provides endpoints for:
    - Listing notifications with filtering
    - Creating new notifications
    - Retrieving notification details
    - Updating notification status (mark as read/unread)
    - Soft deleting notifications
    - Marking all notifications as read
    - Clearing all notifications
    - Getting notification statistics
    """

    queryset = Notification.objects.filter(deleted_at__isnull=True)
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return NotificationListSerializer
        elif self.action == 'retrieve':
            return NotificationDetailSerializer
        elif self.action == 'create':
            return NotificationCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return NotificationUpdateSerializer
        elif self.action == 'stats':
            return NotificationStatsSerializer
        else:
            return NotificationDetailSerializer

    def get_permissions(self):
        if self.action == 'create':
            permission_classes = [IsAuthenticated, IsActiveUser, CanCreateNotification]
        elif self.action in ['update', 'partial_update']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanUpdateNotification]
        elif self.action == 'destroy':
            permission_classes = [IsAuthenticated, IsActiveUser, CanDeleteNotification]
        elif self.action in ['retrieve', 'list']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanViewNotification]
        elif self.action in ['mark_read', 'mark_unread']:
            permission_classes = [IsAuthenticated, IsActiveUser, IsNotificationOwner]
        elif self.action in ['mark_all_read', 'clear_all']:
            permission_classes = [IsAuthenticated, IsActiveUser]
        elif self.action == 'stats':
            permission_classes = [IsAuthenticated, IsActiveUser, CanViewStats]
        elif self.action == 'deliveries':
            permission_classes = [IsAuthenticated, IsActiveUser, IsNotificationOwner]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()

        if not user.is_superuser:
            # Regular users see only their own notifications
            queryset = queryset.filter(user=user)

        # Filter by notification_type
        type_filter = self.request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(notification_type=type_filter)

        # Filter by priority
        priority_filter = self.request.query_params.get('priority')
        if priority_filter:
            queryset = queryset.filter(priority=priority_filter)

        # Filter by is_read
        read_filter = self.request.query_params.get('is_read')
        if read_filter is not None:
            queryset = queryset.filter(is_read=read_filter.lower() == 'true')

        # Filter by date range
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(created_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__lte=date_to)

        # Search in title and message
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(message__icontains=search)
            )

        # Filter by object_type
        object_type = self.request.query_params.get('object_type')
        if object_type:
            queryset = queryset.filter(object_type=object_type)

        # Filter by group
        group_id = self.request.query_params.get('group_id')
        if group_id:
            queryset = queryset.filter(group_id=group_id)

        # Ordering
        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)

        return queryset.select_related('user', 'group', 'created_by')

    def perform_create(self, serializer):
        """Create a notification with the current user as creator."""
        with transaction.atomic():
            notification = serializer.save(created_by=self.request.user)
            logger.info(f'Notification {notification.id} created by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='notification_create',
                resource='notification',
                resource_id=notification.id,
                ip=get_client_ip(self.request)
            )

    def perform_update(self, serializer):
        """Update a notification and log changes."""
        with transaction.atomic():
            instance = self.get_object()
            old_read_status = instance.is_read
            notification = serializer.save()
            logger.info(f'Notification {notification.id} updated by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='notification_update',
                resource='notification',
                resource_id=notification.id,
                ip=get_client_ip(self.request),
                details={'old_read_status': old_read_status, 'new_read_status': notification.is_read}
            )

    def perform_destroy(self, instance):
        """Soft delete a notification."""
        with transaction.atomic():
            instance.deleted_at = timezone.now()
            instance.save(update_fields=['deleted_at'])
            logger.info(f'Notification {instance.id} soft deleted by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='notification_delete',
                resource='notification',
                resource_id=instance.id,
                ip=get_client_ip(self.request)
            )

    # ========================================================================
    # CUSTOM ACTIONS
    # ========================================================================

    @action(detail=True, methods=['post'])
    def mark_read(self, request, id=None):
        """Mark a notification as read."""
        notification = self.get_object()
        notification.mark_as_read()
        logger.info(f'Notification {notification.id} marked as read by user {request.user.id}')
        return Response({
            'message': 'Notification marked as read.',
            'notification': NotificationListSerializer(notification).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def mark_unread(self, request, id=None):
        """Mark a notification as unread."""
        notification = self.get_object()
        notification.mark_as_unread()
        logger.info(f'Notification {notification.id} marked as unread by user {request.user.id}')
        return Response({
            'message': 'Notification marked as unread.',
            'notification': NotificationListSerializer(notification).data
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """Mark all notifications as read for the current user."""
        user = request.user
        count = Notification.objects.filter(
            user=user,
            is_read=False,
            deleted_at__isnull=True
        ).update(
            is_read=True,
            read_at=timezone.now()
        )
        logger.info(f'All notifications marked as read for user {user.id}')
        return Response({
            'message': f'Marked {count} notifications as read.',
            'count': count
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def clear_all(self, request):
        """Clear all notifications for the current user."""
        user = request.user
        before_date = request.data.get('before_date')
        count = 0
        if before_date:
            count = Notification.objects.filter(
                user=user,
                created_at__lt=before_date,
                deleted_at__isnull=True
            ).delete()[0]
        else:
            count = Notification.objects.filter(
                user=user,
                deleted_at__isnull=True
            ).delete()[0]
        logger.info(f'All notifications cleared for user {user.id}')
        return Response({
            'message': f'Cleared {count} notifications.',
            'count': count
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get notification statistics for the current user."""
        user = request.user
        from . import get_notification_stats
        stats = get_notification_stats(user.id)
        serializer = NotificationStatsSerializer(stats)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def deliveries(self, request, id=None):
        """Get all delivery records for a notification."""
        notification = self.get_object()
        deliveries = notification.deliveries.all().order_by('-created_at')
        from .serializers import NotificationDeliverySerializer
        serializer = NotificationDeliverySerializer(deliveries, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def unread(self, request):
        """Get unread notifications for the current user."""
        user = request.user
        queryset = Notification.objects.filter(
            user=user,
            is_read=False,
            deleted_at__isnull=True
        ).order_by('-created_at')
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = NotificationListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = NotificationListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        """Get the number of unread notifications for the current user."""
        user = request.user
        count = Notification.objects.filter(
            user=user,
            is_read=False,
            deleted_at__isnull=True
        ).count()
        return Response({'unread_count': count}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def send(self, request):
        """Send a notification (admin only)."""
        if not request.user.is_superuser:
            raise PermissionDeniedError(_('Super admin access required.'))

        serializer = NotificationCreateSerializer(data=request.data)
        if serializer.is_valid():
            notification = serializer.save(created_by=request.user)
            # Queue delivery
            from .tasks import send_notification
            notification_data = {
                'id': notification.id,
                'user_id': notification.user.id,
                'email': notification.user.email,
                'phone': notification.user.phone,
                'message': notification.message,
                'title': notification.title,
                'notification_type': notification.notification_type,
                'group_id': notification.group.id if notification.group else None,
                'object_id': notification.object_id,
                'object_type': notification.object_type,
                'priority': notification.priority,
                'send_email': request.data.get('send_email', False),
                'send_sms': request.data.get('send_sms', False),
                'send_push': request.data.get('send_push', False),
                'send_in_app': request.data.get('send_in_app', True),
            }
            send_notification.delay(notification_data)
            return Response({
                'message': 'Notification sent successfully.',
                'notification': NotificationListSerializer(notification).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# NOTIFICATION TEMPLATE VIEW SET
# ============================================================================

class NotificationTemplateViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing notification templates.
    """

    queryset = NotificationTemplate.objects.filter(deleted_at__isnull=True)
    serializer_class = NotificationTemplateSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'create':
            return NotificationTemplateCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return NotificationTemplateUpdateSerializer
        return NotificationTemplateSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsSuperAdminUser()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        notification_type = self.request.query_params.get('notification_type')
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search)
            )
        ordering = self.request.query_params.get('ordering', 'name')
        queryset = queryset.order_by(ordering)
        return queryset

    def perform_create(self, serializer):
        with transaction.atomic():
            template = serializer.save()
            logger.info(f'Notification template {template.id} created by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='notification_template_create',
                resource='notification_template',
                resource_id=template.id,
                ip=get_client_ip(self.request)
            )

    def perform_update(self, serializer):
        with transaction.atomic():
            template = serializer.save()
            logger.info(f'Notification template {template.id} updated by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='notification_template_update',
                resource='notification_template',
                resource_id=template.id,
                ip=get_client_ip(self.request)
            )

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance.deleted_at = timezone.now()
            instance.save(update_fields=['deleted_at'])
            logger.info(f'Notification template {instance.id} soft deleted by user {self.request.user.id}')


# ============================================================================
# NOTIFICATION PREFERENCE VIEW SET
# ============================================================================

class NotificationPreferenceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing user notification preferences.
    """

    queryset = NotificationPreference.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return NotificationPreferenceUpdateSerializer
        return NotificationPreferenceSerializer

    def get_permissions(self):
        if self.action in ['retrieve', 'update', 'partial_update']:
            return [IsAuthenticated(), IsActiveUser]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            queryset = super().get_queryset()
        else:
            queryset = NotificationPreference.objects.filter(user=user)
        user_id = self.request.query_params.get('user_id')
        if user_id and user.is_superuser:
            queryset = queryset.filter(user_id=user_id)
        return queryset.select_related('user')

    def perform_update(self, serializer):
        with transaction.atomic():
            prefs = serializer.save()
            logger.info(f'Notification preferences updated for user {prefs.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='notification_preferences_update',
                resource='notification_preference',
                resource_id=prefs.id,
                ip=get_client_ip(self.request)
            )

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Get notification preferences for the current user."""
        prefs, created = NotificationPreference.objects.get_or_create(user=request.user)
        serializer = NotificationPreferenceSerializer(prefs)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['put'])
    def update_me(self, request):
        """Update notification preferences for the current user."""
        prefs, created = NotificationPreference.objects.get_or_create(user=request.user)
        serializer = NotificationPreferenceUpdateSerializer(prefs, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# NOTIFICATION CHANNEL VIEW SET
# ============================================================================

class NotificationChannelViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing notification channels (admin only).
    """

    queryset = NotificationChannel.objects.filter(deleted_at__isnull=True)
    serializer_class = NotificationChannelSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_permissions(self):
        return [IsAuthenticated(), IsSuperAdminUser()]

    def get_queryset(self):
        queryset = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        ordering = self.request.query_params.get('ordering', 'priority')
        queryset = queryset.order_by(ordering)
        return queryset

    def perform_create(self, serializer):
        with transaction.atomic():
            channel = serializer.save()
            logger.info(f'Notification channel {channel.id} created by user {self.request.user.id}')

    def perform_update(self, serializer):
        with transaction.atomic():
            channel = serializer.save()
            logger.info(f'Notification channel {channel.id} updated by user {self.request.user.id}')

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance.deleted_at = timezone.now()
            instance.save(update_fields=['deleted_at'])
            logger.info(f'Notification channel {instance.id} soft deleted by user {self.request.user.id}')


# ============================================================================
# NOTIFICATION DELIVERY VIEW SET
# ============================================================================

class NotificationDeliveryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing notification deliveries.
    """

    queryset = NotificationDelivery.objects.all()
    serializer_class = NotificationDeliverySerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()

        if not user.is_superuser:
            queryset = queryset.filter(notification__user=user)

        notification_id = self.request.query_params.get('notification_id')
        if notification_id:
            queryset = queryset.filter(notification_id=notification_id)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        channel_filter = self.request.query_params.get('channel')
        if channel_filter:
            queryset = queryset.filter(channel=channel_filter)

        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)

        return queryset.select_related('notification', 'notification__user')

    def get_permissions(self):
        return [IsAuthenticated()]


# ============================================================================
# NOTIFICATION EVENT VIEW SET
# ============================================================================

class NotificationEventViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing notification events.
    """

    queryset = NotificationEvent.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'create':
            return NotificationEventCreateSerializer
        return NotificationEventSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsActiveUser]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsSuperAdminUser()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_superuser:
            queryset = queryset.filter(user=user)
        event_type = self.request.query_params.get('event_type')
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        processed = self.request.query_params.get('processed')
        if processed is not None:
            queryset = queryset.filter(processed=processed.lower() == 'true')
        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('user', 'group')

    def perform_create(self, serializer):
        with transaction.atomic():
            event = serializer.save()
            logger.info(f'Notification event {event.id} created by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='notification_event_create',
                resource='notification_event',
                resource_id=event.id,
                ip=get_client_ip(self.request)
            )

    @action(detail=True, methods=['post'])
    def process(self, request, id=None):
        """Process a notification event."""
        event = self.get_object()
        if event.processed:
            return Response({'message': 'Event already processed.'}, status=status.HTTP_200_OK)
        event.process()
        return Response({
            'message': 'Event processed successfully.',
            'event': NotificationEventSerializer(event).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def retry(self, request, id=None):
        """Retry processing a failed event."""
        event = self.get_object()
        if event.processed:
            return Response({'message': 'Event already processed.'}, status=status.HTTP_200_OK)
        event.retry()
        return Response({
            'message': 'Event retry initiated.',
            'event': NotificationEventSerializer(event).data
        }, status=status.HTTP_200_OK)


# ============================================================================
# NOTIFICATION SCHEDULE VIEW SET
# ============================================================================

class NotificationScheduleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing scheduled notifications.
    """

    queryset = NotificationSchedule.objects.all()
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'create':
            return NotificationScheduleCreateSerializer
        return NotificationScheduleSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsActiveUser, CanSendNotification]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsSuperAdminUser()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_superuser:
            queryset = queryset.filter(notification__user=user)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        ordering = self.request.query_params.get('ordering', 'scheduled_at')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('notification', 'notification__user')

    def perform_create(self, serializer):
        with transaction.atomic():
            schedule = serializer.save()
            logger.info(f'Notification schedule {schedule.id} created by user {self.request.user.id}')

    @action(detail=True, methods=['post'])
    def execute(self, request, id=None):
        """Execute a scheduled notification."""
        schedule = self.get_object()
        if schedule.status != 'pending':
            return Response({'message': 'Schedule is not pending.'}, status=status.HTTP_400_BAD_REQUEST)
        success = schedule.execute()
        return Response({
            'message': 'Schedule executed successfully.' if success else 'Execution failed.',
            'schedule': NotificationScheduleSerializer(schedule).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def cancel(self, request, id=None):
        """Cancel a scheduled notification."""
        schedule = self.get_object()
        if schedule.status == 'cancelled':
            return Response({'message': 'Schedule already cancelled.'}, status=status.HTTP_200_OK)
        schedule.cancel()
        return Response({
            'message': 'Schedule cancelled.',
            'schedule': NotificationScheduleSerializer(schedule).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def reschedule(self, request, id=None):
        """Reschedule a scheduled notification."""
        schedule = self.get_object()
        if schedule.status not in ['pending', 'failed']:
            return Response({'message': 'Only pending or failed schedules can be rescheduled.'}, status=status.HTTP_400_BAD_REQUEST)
        new_time = request.data.get('scheduled_at')
        if new_time:
            import dateutil.parser
            new_time = dateutil.parser.parse(new_time)
        schedule.reschedule(new_time)
        return Response({
            'message': 'Schedule rescheduled.',
            'schedule': NotificationScheduleSerializer(schedule).data
        }, status=status.HTTP_200_OK)


# ============================================================================
# NOTIFICATION DIGEST VIEW SET
# ============================================================================

class NotificationDigestViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing notification digests.
    """

    queryset = NotificationDigest.objects.all()
    serializer_class = NotificationDigestSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_superuser:
            queryset = queryset.filter(user=user)
        digest_type = self.request.query_params.get('digest_type')
        if digest_type:
            queryset = queryset.filter(digest_type=digest_type)
        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('user')

    def get_permissions(self):
        return [IsAuthenticated()]

    @action(detail=True, methods=['post'])
    def send(self, request, id=None):
        """Send a digest to the user."""
        digest = self.get_object()
        if digest.sent_at:
            return Response({'message': 'Digest already sent.'}, status=status.HTTP_200_OK)
        success = digest.send()
        return Response({
            'message': 'Digest sent successfully.' if success else 'Send failed.',
            'digest': NotificationDigestSerializer(digest).data
        }, status=status.HTTP_200_OK)


# ============================================================================
# NOTIFICATION AUDIT VIEW SET
# ============================================================================

class NotificationAuditViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing notification audit logs.
    """

    queryset = NotificationAudit.objects.all()
    serializer_class = NotificationAuditSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_superuser:
            queryset = queryset.filter(notification__user=user)
        notification_id = self.request.query_params.get('notification_id')
        if notification_id:
            queryset = queryset.filter(notification_id=notification_id)
        action_filter = self.request.query_params.get('action')
        if action_filter:
            queryset = queryset.filter(action=action_filter)
        ordering = self.request.query_params.get('ordering', '-timestamp')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('notification', 'user')

    def get_permissions(self):
        return [IsAuthenticated()]


# ============================================================================
# NOTIFICATION STATISTICS VIEW
# ============================================================================

class NotificationStatsView(APIView):
    """
    View for notification statistics (admin only).
    """
    permission_classes = [IsAuthenticated, IsSuperAdminUser]

    def get(self, request):
        user_id = request.query_params.get('user_id')
        from . import get_notification_stats
        stats = get_notification_stats(user_id)
        serializer = NotificationStatsSerializer(stats)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# BULK NOTIFICATION SEND VIEW
# ============================================================================

class BulkNotificationSendView(APIView):
    """
    View for sending bulk notifications (admin only).
    """
    permission_classes = [IsAuthenticated, IsSuperAdminUser]

    def post(self, request):
        serializer = BulkNotificationSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            user_ids = data['user_ids']
            message = data['message']
            notification_type = data.get('notification_type', 'info')
            title = data.get('title', '')
            group_id = data.get('group_id')
            send_email = data.get('send_email', True)
            send_sms = data.get('send_sms', False)
            send_push = data.get('send_push', False)
            send_in_app = data.get('send_in_app', True)

            # Get users
            users = User.objects.filter(id__in=user_ids, is_active=True)

            if not users.exists():
                return Response({'error': 'No valid users found.'}, status=status.HTTP_400_BAD_REQUEST)

            # Send bulk notifications
            from .tasks import send_bulk_notifications
            result = send_bulk_notifications.delay(
                user_ids=list(users.values_list('id', flat=True)),
                message=message,
                notification_type=notification_type,
                title=title,
                group_id=group_id,
                send_email=send_email,
                send_sms=send_sms,
                send_push=send_push,
                send_in_app=send_in_app,
            )

            logger.info(f'Bulk notification queued by user {request.user.id} for {len(user_ids)} users')
            log_audit_event(
                user_id=request.user.id,
                action='bulk_notification_send',
                resource='bulk_notification',
                resource_id=None,
                ip=get_client_ip(request),
                details={'user_count': len(user_ids), 'notification_type': notification_type}
            )

            return Response({
                'message': f'Bulk notification queued for {len(user_ids)} users.',
                'task_id': result.id,
                'user_count': len(user_ids)
            }, status=status.HTTP_202_ACCEPTED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)