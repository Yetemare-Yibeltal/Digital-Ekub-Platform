"""
Views for the contributions app.

This module provides all API views for contribution management including:
- Contribution CRUD operations (create, list, retrieve, update, delete)
- Payment processing (initiate, complete, refund)
- Reminder management (send reminders)
- Audit log viewing
- Statistics and reporting
- Bulk operations (create multiple contributions, bulk status updates)
- Admin actions (mark as paid/overdue/cancelled/refunded/waived)

All views use appropriate permissions and include comprehensive logging,
pagination, filtering, and error handling.
"""

from django.db import transaction
from django.db.models import Q, Sum, Count, Avg, F, OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets, status, permissions, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound

from apps.users.models import User
from apps.groups.models import Group, GroupMember
from apps.common.pagination import CustomPagination
from apps.common.permissions import (
    IsAuthenticated, IsActiveUser, IsSuperAdminUser,
    IsAdminUser, IsOwnerOrReadOnly, IsOwnerOrAdmin
)
from apps.common.exceptions import (
    BadRequestError, NotFoundError, PermissionDeniedError,
    ConflictError, ValidationError as CustomValidationError
)
from apps.common.utils import log_audit_event, get_client_ip, format_currency

from .models import (
    Contribution,
    ContributionPayment,
    ContributionReminder,
    ContributionAudit
)
from .serializers import (
    ContributionListSerializer,
    ContributionDetailSerializer,
    ContributionCreateSerializer,
    ContributionUpdateSerializer,
    ContributionPaymentSerializer,
    ContributionPaymentCreateSerializer,
    ContributionReminderSerializer,
    ContributionReminderCreateSerializer,
    ContributionAuditSerializer,
    ContributionStatsSerializer,
    ContributionSummarySerializer,
    MemberContributionSummarySerializer,
    GroupContributionSummarySerializer,
    BulkContributionCreateSerializer,
    BulkContributionStatusUpdateSerializer,
)
from .permissions import (
    IsContributionOwner,
    IsContributionOwnerOrGroupAdmin,
    CanPayContribution,
    CanProcessContribution,
    CanViewContribution,
    CanCreateContribution,
    CanUpdateContribution,
    CanDeleteContribution,
    IsGroupAdminOfContribution,
    IsMemberOfContributionGroup,
)
from .tasks import (
    process_pending_contributions,
    check_overdue_contributions,
    send_contribution_reminders,
    process_contribution_payments,
    update_contribution_stats,
    cleanup_completed_contributions,
    generate_contribution_report,
    send_contribution_digest,
    process_refunds,
    auto_waive_overdue_contributions,
)

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# CONTRIBUTION VIEW SET
# ============================================================================

class ContributionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Contribution model with full CRUD and additional actions.

    Provides endpoints for:
    - Listing contributions with filtering
    - Creating new contributions
    - Retrieving contribution details
    - Updating contribution status and fields
    - Soft deleting contributions
    - Processing payments
    - Sending reminders
    - Viewing audit logs
    - Getting statistics
    - Bulk operations (admin only)
    """

    queryset = Contribution.objects.filter(deleted_at__isnull=True)
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return ContributionListSerializer
        elif self.action == 'retrieve':
            return ContributionDetailSerializer
        elif self.action == 'create':
            return ContributionCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ContributionUpdateSerializer
        elif self.action == 'stats':
            return ContributionStatsSerializer
        elif self.action == 'summary':
            return ContributionSummarySerializer
        elif self.action in ['mark_paid', 'mark_overdue', 'cancel', 'refund', 'waive']:
            return serializers.Serializer
        else:
            return ContributionDetailSerializer

    def get_permissions(self):
        if self.action == 'create':
            permission_classes = [IsAuthenticated, IsActiveUser, CanCreateContribution]
        elif self.action in ['update', 'partial_update']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanUpdateContribution]
        elif self.action == 'destroy':
            permission_classes = [IsAuthenticated, IsActiveUser, CanDeleteContribution]
        elif self.action in ['retrieve', 'list']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanViewContribution]
        elif self.action in ['pay', 'process_payment']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanPayContribution]
        elif self.action in ['mark_paid', 'mark_overdue', 'cancel', 'refund', 'waive']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanProcessContribution]
        elif self.action in ['reminders', 'send_reminder']:
            permission_classes = [IsAuthenticated, IsActiveUser]
        elif self.action in ['audit_trail']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanViewContribution]
        elif self.action in ['stats', 'summary']:
            permission_classes = [IsAuthenticated, IsActiveUser]
        elif self.action in ['bulk_create', 'bulk_update_status']:
            permission_classes = [IsAuthenticated, IsSuperAdminUser]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()

        # Filter based on user role
        if not user or not user.is_authenticated:
            return Contribution.objects.none()

        if user.is_superuser:
            # Super admin sees all
            pass
        elif user.is_staff:
            # Staff can see all
            pass
        else:
            # Regular users see only their own contributions and those in groups they are members of
            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)

            queryset = queryset.filter(
                Q(user=user) | Q(group_id__in=member_group_ids)
            )

        # Filter by group
        group_id = self.request.query_params.get('group_id')
        if group_id:
            queryset = queryset.filter(group_id=group_id)

        # Filter by user
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Filter by contribution type
        type_filter = self.request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(contribution_type=type_filter)

        # Filter by date range
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(due_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(due_date__lte=date_to)

        # Filter by round
        round_filter = self.request.query_params.get('round')
        if round_filter:
            queryset = queryset.filter(round=round_filter)

        # Search
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search) |
                Q(notes__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(group__name__icontains=search)
            )

        # Ordering
        ordering = self.request.query_params.get('ordering', '-due_date')
        queryset = queryset.order_by(ordering)

        return queryset.select_related('user', 'group', 'created_by', 'payment')

    # ========================================================================
    # OVERRIDDEN METHODS
    # ========================================================================

    def perform_create(self, serializer):
        """Create a contribution with the current user as creator."""
        with transaction.atomic():
            contribution = serializer.save(created_by=self.request.user)
            logger.info(f'Contribution {contribution.id} created by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='contribution_create',
                resource='contribution',
                resource_id=contribution.id,
                ip=get_client_ip(self.request)
            )
            update_contribution_stats.delay(contribution.group.id)

    def perform_update(self, serializer):
        """Update a contribution and log changes."""
        with transaction.atomic():
            instance = self.get_object()
            old_status = instance.status
            contribution = serializer.save()
            logger.info(f'Contribution {contribution.id} updated by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='contribution_update',
                resource='contribution',
                resource_id=contribution.id,
                ip=get_client_ip(self.request),
                details={
                    'old_status': old_status,
                    'new_status': contribution.status,
                    'updated_fields': list(serializer.validated_data.keys())
                }
            )
            update_contribution_stats.delay(contribution.group.id)

    def perform_destroy(self, instance):
        """Soft delete a contribution."""
        with transaction.atomic():
            instance.soft_delete(reason='Deleted by user')
            logger.info(f'Contribution {instance.id} soft deleted by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='contribution_delete',
                resource='contribution',
                resource_id=instance.id,
                ip=get_client_ip(self.request)
            )
            update_contribution_stats.delay(instance.group.id)

    # ========================================================================
    # CUSTOM ACTIONS
    # ========================================================================

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, id=None):
        """Mark a contribution as paid."""
        contribution = self.get_object()

        if not contribution.can_be_paid:
            raise BadRequestError(_('This contribution cannot be paid.'))

        payment_method = request.data.get('payment_method', 'cash')
        reference = request.data.get('reference')

        with transaction.atomic():
            contribution.mark_as_paid(
                payment_method=payment_method,
                reference=reference
            )
            logger.info(f'Contribution {contribution.id} marked as paid by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='contribution_mark_paid',
                resource='contribution',
                resource_id=contribution.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'paid',
                'message': 'Contribution marked as paid successfully.',
                'contribution': ContributionDetailSerializer(contribution).data
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def mark_overdue(self, request, id=None):
        """Mark a contribution as overdue."""
        contribution = self.get_object()

        if not contribution.can_be_overdue:
            raise BadRequestError(_('This contribution cannot be marked as overdue.'))

        with transaction.atomic():
            contribution.mark_as_overdue()
            logger.info(f'Contribution {contribution.id} marked as overdue by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='contribution_mark_overdue',
                resource='contribution',
                resource_id=contribution.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'overdue',
                'message': 'Contribution marked as overdue.',
                'contribution': ContributionDetailSerializer(contribution).data
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def cancel_contribution(self, request, id=None):
        """Cancel a contribution."""
        contribution = self.get_object()

        if not contribution.can_be_cancelled:
            raise BadRequestError(_('This contribution cannot be cancelled.'))

        reason = request.data.get('reason')

        with transaction.atomic():
            contribution.cancel(reason)
            logger.info(f'Contribution {contribution.id} cancelled by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='contribution_cancel',
                resource='contribution',
                resource_id=contribution.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'cancelled',
                'message': 'Contribution cancelled.',
                'contribution': ContributionDetailSerializer(contribution).data
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def refund_contribution(self, request, id=None):
        """Refund a contribution."""
        contribution = self.get_object()

        if not contribution.can_be_refunded:
            raise BadRequestError(_('This contribution cannot be refunded.'))

        reason = request.data.get('reason')

        with transaction.atomic():
            contribution.refund(reason)
            logger.info(f'Contribution {contribution.id} refunded by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='contribution_refund',
                resource='contribution',
                resource_id=contribution.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'refunded',
                'message': 'Contribution refunded.',
                'contribution': ContributionDetailSerializer(contribution).data
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def waive_contribution(self, request, id=None):
        """Waive part or all of a contribution."""
        contribution = self.get_object()

        if not contribution.can_be_waived:
            raise BadRequestError(_('This contribution cannot be waived.'))

        amount = request.data.get('amount')
        reason = request.data.get('reason')

        if not amount:
            raise BadRequestError(_('Amount to waive is required.'))

        try:
            amount = Decimal(str(amount))
        except Exception:
            raise BadRequestError(_('Invalid amount format.'))

        if amount <= 0:
            raise BadRequestError(_('Amount must be greater than zero.'))

        if amount > contribution.amount:
            raise BadRequestError(_('Cannot waive more than contribution amount.'))

        with transaction.atomic():
            contribution.waive(amount, reason)
            logger.info(f'Contribution {contribution.id} waived {amount} by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='contribution_waive',
                resource='contribution',
                resource_id=contribution.id,
                ip=get_client_ip(request),
                details={'amount': float(amount)}
            )
            return Response({
                'status': 'waived' if amount == contribution.amount else 'partially_paid',
                'message': f'Waived {format_currency(amount)}.',
                'contribution': ContributionDetailSerializer(contribution).data
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def send_reminder(self, request, id=None):
        """Send a reminder for a contribution."""
        contribution = self.get_object()

        if not contribution.is_ready_for_reminder:
            raise BadRequestError(_('This contribution is not ready for a reminder.'))

        reminder_type = request.data.get('reminder_type', 'email')

        with transaction.atomic():
            from .serializers import ContributionReminderCreateSerializer
            serializer = ContributionReminderCreateSerializer(
                data={'contribution': contribution.id, 'reminder_type': reminder_type},
                context={'request': request}
            )
            if serializer.is_valid():
                reminder = serializer.save()
                logger.info(f'Reminder sent for contribution {contribution.id} by user {request.user.id}')
                return Response({
                    'message': 'Reminder sent successfully.',
                    'reminder': ContributionReminderSerializer(reminder).data
                }, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def reminders(self, request, id=None):
        """Get all reminders for a contribution."""
        contribution = self.get_object()
        reminders = contribution.reminders.all().order_by('-sent_at')
        serializer = ContributionReminderSerializer(reminders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def audit_trail(self, request, id=None):
        """Get audit trail for a contribution."""
        contribution = self.get_object()
        audits = contribution.audits.all().order_by('-timestamp')
        serializer = ContributionAuditSerializer(audits, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def payment_detail(self, request, id=None):
        """Get payment details for a contribution."""
        contribution = self.get_object()
        payment = contribution.payment
        if not payment:
            return Response({'message': 'No payment found for this contribution.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ContributionPaymentSerializer(payment)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def stats(self, request, id=None):
        """Get statistics for a single contribution."""
        contribution = self.get_object()
        stats = {
            'id': contribution.id,
            'amount': float(contribution.amount),
            'penalty': float(contribution.penalty_amount),
            'waived': float(contribution.waived_amount),
            'platform_fee': float(contribution.platform_fee),
            'net_amount': float(contribution.net_amount),
            'total_due': float(contribution.total_amount_with_penalty),
            'days_overdue': contribution.days_overdue_calculated,
            'reminder_count': contribution.reminder_count,
        }
        return Response(stats, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def my_contributions(self, request):
        """Get contributions for the current user."""
        user = request.user
        queryset = Contribution.objects.filter(
            user=user,
            deleted_at__isnull=True
        ).order_by('-due_date')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = ContributionListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ContributionListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def pending(self, request):
        """Get all pending contributions for the current user."""
        user = request.user
        queryset = Contribution.objects.filter(
            user=user,
            status=ContributionStatus.PENDING,
            deleted_at__isnull=True
        ).order_by('due_date')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = ContributionListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ContributionListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def overdue(self, request):
        """Get all overdue contributions for the current user."""
        user = request.user
        queryset = Contribution.objects.filter(
            user=user,
            status=ContributionStatus.OVERDUE,
            deleted_at__isnull=True
        ).order_by('due_date')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = ContributionListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ContributionListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get summary statistics for contributions."""
        user = request.user
        group_id = request.query_params.get('group_id')

        # Base queryset
        queryset = Contribution.objects.filter(deleted_at__isnull=True)

        if not user.is_superuser:
            # Filter to user's contributions or groups they are members of
            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)
            queryset = queryset.filter(
                Q(user=user) | Q(group_id__in=member_group_ids)
            )

        if group_id:
            queryset = queryset.filter(group_id=group_id)

        total = queryset.count()
        paid = queryset.filter(status=ContributionStatus.PAID).count()
        pending = queryset.filter(status=ContributionStatus.PENDING).count()
        overdue = queryset.filter(status=ContributionStatus.OVERDUE).count()
        cancelled = queryset.filter(status=ContributionStatus.CANCELLED).count()
        refunded = queryset.filter(status=ContributionStatus.REFUNDED).count()
        waived = queryset.filter(status=ContributionStatus.WAIVED).count()
        partially_paid = queryset.filter(status=ContributionStatus.PARTIALLY_PAID).count()

        total_paid_amount = queryset.filter(status=ContributionStatus.PAID).aggregate(
            total=Sum('amount')
        )['total'] or 0

        pending_amount = queryset.filter(status=ContributionStatus.PENDING).aggregate(
            total=Sum('amount')
        )['total'] or 0

        overdue_amount = queryset.filter(status=ContributionStatus.OVERDUE).aggregate(
            total=Sum('amount')
        )['total'] or 0

        return Response({
            'total_contributions': total,
            'paid': paid,
            'pending': pending,
            'overdue': overdue,
            'cancelled': cancelled,
            'refunded': refunded,
            'waived': waived,
            'partially_paid': partially_paid,
            'total_paid_amount': float(total_paid_amount),
            'pending_amount': float(pending_amount),
            'overdue_amount': float(overdue_amount),
            'completion_rate': round((paid / total * 100) if total > 0 else 0, 2),
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def group_summary(self, request):
        """Get contribution summary for a group."""
        group_id = request.query_params.get('group_id')
        if not group_id:
            raise BadRequestError(_('group_id is required.'))

        try:
            group = Group.objects.get(id=group_id, deleted_at__isnull=True)
        except Group.DoesNotExist:
            raise NotFoundError(_('Group not found.'))

        from apps.groups.models import GroupMember
        if not user.is_superuser and not GroupMember.objects.filter(
            group=group,
            user=request.user,
            is_active=True
        ).exists():
            raise PermissionDeniedError(_('You do not have access to this group.'))

        contributions = Contribution.objects.filter(group=group, deleted_at__isnull=True)
        total = contributions.count()
        paid = contributions.filter(status=ContributionStatus.PAID).count()
        pending = contributions.filter(status=ContributionStatus.PENDING).count()
        overdue = contributions.filter(status=ContributionStatus.OVERDUE).count()
        total_paid = contributions.filter(status=ContributionStatus.PAID).aggregate(
            total=Sum('amount')
        )['total'] or 0
        pending_amount = contributions.filter(status=ContributionStatus.PENDING).aggregate(
            total=Sum('amount')
        )['total'] or 0
        overdue_amount = contributions.filter(status=ContributionStatus.OVERDUE).aggregate(
            total=Sum('amount')
        )['total'] or 0

        return Response({
            'group_id': group.id,
            'group_name': group.name,
            'total_contributions': total,
            'paid': paid,
            'pending': pending,
            'overdue': overdue,
            'total_paid_amount': float(total_paid),
            'pending_amount': float(pending_amount),
            'overdue_amount': float(overdue_amount),
            'completion_rate': round((paid / total * 100) if total > 0 else 0, 2),
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        """
        Create contributions for all active members of a group for a specific round.
        Admin only.
        """
        serializer = BulkContributionCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            result = serializer.save()
            logger.info(f'Bulk contributions created for group {result["group_id"]} by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='contribution_bulk_create',
                resource='contribution',
                resource_id=None,
                ip=get_client_ip(request),
                details={'group_id': result['group_id'], 'count': result['contributions_created']}
            )
            return Response(result, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def bulk_update_status(self, request):
        """
        Bulk update status of multiple contributions.
        Admin only.
        """
        serializer = BulkContributionStatusUpdateSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            result = serializer.save()
            logger.info(f'Bulk status update completed by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='contribution_bulk_status_update',
                resource='contribution',
                resource_id=None,
                ip=get_client_ip(request),
                details=result
            )
            return Response(result, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def stats_overview(self, request):
        """
        Get overview statistics for all contributions.
        Admin only.
        """
        if not request.user.is_superuser:
            raise PermissionDeniedError(_('Super admin access required.'))

        # Overall stats for the entire platform
        total = Contribution.objects.filter(deleted_at__isnull=True).count()
        paid = Contribution.objects.filter(status=ContributionStatus.PAID, deleted_at__isnull=True).count()
        pending = Contribution.objects.filter(status=ContributionStatus.PENDING, deleted_at__isnull=True).count()
        overdue = Contribution.objects.filter(status=ContributionStatus.OVERDUE, deleted_at__isnull=True).count()

        total_paid = Contribution.objects.filter(
            status=ContributionStatus.PAID,
            deleted_at__isnull=True
        ).aggregate(total=Sum('amount'))['total'] or 0

        platform_fees = Contribution.objects.filter(
            status=ContributionStatus.PAID,
            deleted_at__isnull=True
        ).aggregate(total=Sum('platform_fee'))['total'] or 0

        today = timezone.now().date()
        today_total = Contribution.objects.filter(
            created_at__date=today,
            deleted_at__isnull=True
        ).count()

        return Response({
            'total_contributions': total,
            'paid': paid,
            'pending': pending,
            'overdue': overdue,
            'total_paid_amount': float(total_paid),
            'platform_fees_collected': float(platform_fees),
            'today_contributions': today_total,
            'overdue_rate': round((overdue / total * 100) if total > 0 else 0, 2),
            'payment_rate': round((paid / total * 100) if total > 0 else 0, 2),
        }, status=status.HTTP_200_OK)


# ============================================================================
# CONTRIBUTION PAYMENT VIEW SET
# ============================================================================

class ContributionPaymentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ContributionPayment model.

    Provides endpoints for:
    - Listing payments
    - Creating a payment (process payment)
    - Retrieving payment details
    - Updating payment status
    - Refunding a payment
    """

    queryset = ContributionPayment.objects.all()
    serializer_class = ContributionPaymentSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'create':
            return ContributionPaymentCreateSerializer
        return ContributionPaymentSerializer

    def get_permissions(self):
        if self.action in ['create']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanPayContribution]
        elif self.action in ['update', 'partial_update', 'destroy']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanProcessContribution]
        else:
            permission_classes = [IsAuthenticated, IsActiveUser, CanViewContribution]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()

        if not user.is_superuser:
            # Regular users see only their own payments
            # and payments in groups they are members of
            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)
            queryset = queryset.filter(
                Q(user=user) | Q(group_id__in=member_group_ids)
            )

        # Filter by contribution
        contribution_id = self.request.query_params.get('contribution_id')
        if contribution_id:
            queryset = queryset.filter(contribution_id=contribution_id)

        # Filter by user
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Ordering
        ordering = self.request.query_params.get('ordering', '-paid_at')
        queryset = queryset.order_by(ordering)

        return queryset.select_related('user', 'group', 'contribution')

    def perform_create(self, serializer):
        """Process a payment."""
        with transaction.atomic():
            payment = serializer.save()
            logger.info(f'Payment {payment.id} created by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='payment_create',
                resource='contribution_payment',
                resource_id=payment.id,
                ip=get_client_ip(self.request)
            )

    @action(detail=True, methods=['post'])
    def refund_payment(self, request, id=None):
        """Refund a payment."""
        payment = self.get_object()

        if payment.status != PaymentStatus.COMPLETED:
            raise BadRequestError(_('Only completed payments can be refunded.'))

        reason = request.data.get('reason')

        with transaction.atomic():
            payment.refund_payment(reason)
            # Also refund the contribution
            contribution = payment.contribution
            if contribution.status == ContributionStatus.PAID:
                contribution.refund(reason)
            logger.info(f'Payment {payment.id} refunded by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='payment_refund',
                resource='contribution_payment',
                resource_id=payment.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'refunded',
                'message': 'Payment refunded successfully.',
                'payment': ContributionPaymentSerializer(payment).data
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def mark_completed(self, request, id=None):
        """Mark a payment as completed."""
        payment = self.get_object()

        if payment.status != PaymentStatus.PENDING:
            raise BadRequestError(_('Only pending payments can be marked as completed.'))

        reference = request.data.get('reference')

        with transaction.atomic():
            payment.complete(reference)
            # Also mark contribution as paid
            contribution = payment.contribution
            if contribution.status in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]:
                contribution.mark_as_paid(
                    payment_method=payment.payment_method,
                    reference=reference or payment.reference
                )
            logger.info(f'Payment {payment.id} marked as completed by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='payment_complete',
                resource='contribution_payment',
                resource_id=payment.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'completed',
                'message': 'Payment marked as completed.',
                'payment': ContributionPaymentSerializer(payment).data
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def mark_failed(self, request, id=None):
        """Mark a payment as failed."""
        payment = self.get_object()

        if payment.status != PaymentStatus.PENDING:
            raise BadRequestError(_('Only pending payments can be marked as failed.'))

        reason = request.data.get('reason')

        with transaction.atomic():
            payment.fail(reason)
            logger.info(f'Payment {payment.id} marked as failed by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='payment_fail',
                resource='contribution_payment',
                resource_id=payment.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'failed',
                'message': 'Payment marked as failed.',
                'payment': ContributionPaymentSerializer(payment).data
            }, status=status.HTTP_200_OK)


# ============================================================================
# CONTRIBUTION REMINDER VIEW SET
# ============================================================================

class ContributionReminderViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing contribution reminders.
    """

    queryset = ContributionReminder.objects.all()
    serializer_class = ContributionReminderSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()

        if not user.is_superuser:
            # Regular users see only their own reminders
            queryset = queryset.filter(user=user)

        # Filter by contribution
        contribution_id = self.request.query_params.get('contribution_id')
        if contribution_id:
            queryset = queryset.filter(contribution_id=contribution_id)

        # Ordering
        ordering = self.request.query_params.get('ordering', '-sent_at')
        queryset = queryset.order_by(ordering)

        return queryset.select_related('user', 'contribution')

    def get_permissions(self):
        return [IsAuthenticated()]


# ============================================================================
# CONTRIBUTION AUDIT VIEW SET
# ============================================================================

class ContributionAuditViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing contribution audit logs.
    """

    queryset = ContributionAudit.objects.all()
    serializer_class = ContributionAuditSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()

        if not user.is_superuser:
            # Regular users see audits for their own contributions
            # and contributions in groups they are members of
            my_contribution_ids = Contribution.objects.filter(
                user=user,
                deleted_at__isnull=True
            ).values_list('id', flat=True)

            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)

            group_contribution_ids = Contribution.objects.filter(
                group_id__in=member_group_ids,
                deleted_at__isnull=True
            ).values_list('id', flat=True)

            allowed_ids = set(my_contribution_ids) | set(group_contribution_ids)
            queryset = queryset.filter(contribution_id__in=allowed_ids)

        # Filter by contribution
        contribution_id = self.request.query_params.get('contribution_id')
        if contribution_id:
            queryset = queryset.filter(contribution_id=contribution_id)

        # Filter by action
        action_filter = self.request.query_params.get('action')
        if action_filter:
            queryset = queryset.filter(action=action_filter)

        # Ordering
        ordering = self.request.query_params.get('ordering', '-timestamp')
        queryset = queryset.order_by(ordering)

        return queryset.select_related('user', 'contribution')

    def get_permissions(self):
        return [IsAuthenticated()]