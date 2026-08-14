"""
Views for the payments app.

This module provides all API views for payment management including:
- Payment CRUD operations (create, list, retrieve, update, delete)
- Payment actions (complete, fail, cancel, refund, retry, expire, reverse)
- Payout CRUD operations and actions (complete, fail, cancel, put_on_hold)
- Webhook handling (verify signature, process events)
- Reconciliation, disputes, settlements, payment methods, audit logs
- Statistics and reporting (payment stats, payout stats)

All views use appropriate permissions and include comprehensive logging,
pagination, filtering, and error handling with transaction management.
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
from rest_framework.views import APIView

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
    Payment,
    Payout,
    PaymentTransaction,
    PaymentGatewayLog,
    PaymentWebhookLog,
    PaymentReconciliation,
    PaymentDispute,
    Settlement,
    PaymentMethod,
    PaymentAudit,
)
from .serializers import (
    PaymentListSerializer,
    PaymentDetailSerializer,
    PaymentCreateSerializer,
    PaymentUpdateSerializer,
    PaymentTransactionSerializer,
    PayoutListSerializer,
    PayoutDetailSerializer,
    PayoutCreateSerializer,
    PayoutUpdateSerializer,
    PaymentGatewayLogSerializer,
    PaymentWebhookLogSerializer,
    PaymentReconciliationSerializer,
    PaymentDisputeSerializer,
    SettlementSerializer,
    PaymentMethodSerializer,
    PaymentAuditSerializer,
    PaymentStatisticsSerializer,
    PayoutStatisticsSerializer,
    WebhookPayloadSerializer,
)
from .permissions import (
    IsPaymentOwner,
    IsPaymentOwnerOrGroupAdmin,
    CanProcessPayment,
    CanViewPayment,
    CanCreatePayment,
    CanUpdatePayment,
    CanDeletePayment,
    IsPayoutOwner,
    IsPayoutOwnerOrGroupAdmin,
    CanProcessPayout,
    CanViewPayout,
    CanCreatePayout,
    CanUpdatePayout,
    CanDeletePayout,
)
from .tasks import (
    process_pending_payments,
    process_payouts,
    reconcile_payments,
    send_payment_reminders,
    update_payment_stats,
    cleanup_payment_logs,
    generate_payment_report,
    send_payment_digest,
    process_webhook_events,
    retry_failed_payments,
    auto_refund_expired,
)
from . import verify_webhook_signature, verify_webhook_payload, get_payment_statistics, get_payout_statistics

import json
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# PAYMENT VIEW SET
# ============================================================================

class PaymentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Payment model with full CRUD and additional actions.

    Provides endpoints for:
    - Listing payments with filtering
    - Creating new payments
    - Retrieving payment details
    - Updating payment status and fields
    - Soft deleting payments
    - Processing payments (complete, fail, cancel, refund, retry, expire, reverse)
    - Viewing transactions, logs, reconciliations, disputes
    - Getting statistics
    """

    queryset = Payment.objects.filter(deleted_at__isnull=True)
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return PaymentListSerializer
        elif self.action == 'retrieve':
            return PaymentDetailSerializer
        elif self.action == 'create':
            return PaymentCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return PaymentUpdateSerializer
        else:
            return PaymentDetailSerializer

    def get_permissions(self):
        if self.action in ['create']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanCreatePayment]
        elif self.action in ['update', 'partial_update']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanUpdatePayment]
        elif self.action == 'destroy':
            permission_classes = [IsAuthenticated, IsActiveUser, CanDeletePayment]
        elif self.action in ['retrieve', 'list']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanViewPayment]
        elif self.action in ['complete', 'fail', 'cancel', 'refund', 'retry', 'expire', 'reverse']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanProcessPayment]
        elif self.action in ['transactions', 'gateway_logs', 'reconciliations', 'disputes']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanViewPayment]
        elif self.action in ['stats']:
            permission_classes = [IsAuthenticated, IsActiveUser]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()

        if not user.is_superuser:
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

        # Filter by payment_method
        method_filter = self.request.query_params.get('payment_method')
        if method_filter:
            queryset = queryset.filter(payment_method=method_filter)

        # Filter by date range
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(created_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__lte=date_to)

        # Search by reference
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search)
            )

        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)

        return queryset.select_related('user', 'group', 'contribution', 'created_by')

    def perform_create(self, serializer):
        """Create a payment with the current user as creator."""
        with transaction.atomic():
            payment = serializer.save(created_by=self.request.user)
            logger.info(f'Payment {payment.id} created by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='payment_create',
                resource='payment',
                resource_id=payment.id,
                ip=get_client_ip(self.request)
            )
            if payment.status == PaymentStatus.COMPLETED:
                update_payment_stats.delay(payment.group.id)

    def perform_update(self, serializer):
        """Update a payment and log changes."""
        with transaction.atomic():
            instance = self.get_object()
            old_status = instance.status
            payment = serializer.save()
            logger.info(f'Payment {payment.id} updated by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='payment_update',
                resource='payment',
                resource_id=payment.id,
                ip=get_client_ip(self.request),
                details={'old_status': old_status, 'new_status': payment.status}
            )
            update_payment_stats.delay(payment.group.id)

    def perform_destroy(self, instance):
        """Soft delete a payment."""
        with transaction.atomic():
            instance.deleted_at = timezone.now()
            instance.save(update_fields=['deleted_at'])
            logger.info(f'Payment {instance.id} soft deleted by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='payment_delete',
                resource='payment',
                resource_id=instance.id,
                ip=get_client_ip(self.request)
            )

    # ========================================================================
    # CUSTOM ACTIONS
    # ========================================================================

    @action(detail=True, methods=['post'])
    def complete(self, request, id=None):
        """Complete a pending payment."""
        payment = self.get_object()
        if payment.status not in [PaymentStatus.PENDING, PaymentStatus.PROCESSING]:
            raise BadRequestError(_('Payment cannot be completed.'))
        reference = request.data.get('reference')
        with transaction.atomic():
            payment.complete(reference)
            logger.info(f'Payment {payment.id} completed by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='payment_complete',
                resource='payment',
                resource_id=payment.id,
                ip=get_client_ip(request)
            )
            return Response({'message': 'Payment completed.', 'payment': PaymentDetailSerializer(payment).data})

    @action(detail=True, methods=['post'])
    def fail(self, request, id=None):
        """Mark a payment as failed."""
        payment = self.get_object()
        if payment.status not in [PaymentStatus.PENDING, PaymentStatus.PROCESSING]:
            raise BadRequestError(_('Payment cannot be failed.'))
        error = request.data.get('error_message', 'Payment failed')
        with transaction.atomic():
            payment.fail(error)
            logger.info(f'Payment {payment.id} failed by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='payment_fail',
                resource='payment',
                resource_id=payment.id,
                ip=get_client_ip(request)
            )
            return Response({'message': 'Payment failed.', 'payment': PaymentDetailSerializer(payment).data})

    @action(detail=True, methods=['post'])
    def cancel(self, request, id=None):
        """Cancel a payment."""
        payment = self.get_object()
        if not payment.can_be_cancelled:
            raise BadRequestError(_('Payment cannot be cancelled.'))
        with transaction.atomic():
            payment.cancel()
            logger.info(f'Payment {payment.id} cancelled by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='payment_cancel',
                resource='payment',
                resource_id=payment.id,
                ip=get_client_ip(request)
            )
            return Response({'message': 'Payment cancelled.', 'payment': PaymentDetailSerializer(payment).data})

    @action(detail=True, methods=['post'])
    def refund(self, request, id=None):
        """Refund a completed payment."""
        payment = self.get_object()
        if not payment.can_be_refunded:
            raise BadRequestError(_('Payment cannot be refunded.'))
        reason = request.data.get('reason', 'Refund requested')
        with transaction.atomic():
            payment.refund(reason)
            logger.info(f'Payment {payment.id} refunded by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='payment_refund',
                resource='payment',
                resource_id=payment.id,
                ip=get_client_ip(request)
            )
            return Response({'message': 'Payment refunded.', 'payment': PaymentDetailSerializer(payment).data})

    @action(detail=True, methods=['post'])
    def retry(self, request, id=None):
        """Retry a failed payment."""
        payment = self.get_object()
        if not payment.can_be_retried:
            raise BadRequestError(_('Payment cannot be retried.'))
        with transaction.atomic():
            payment.retry()
            logger.info(f'Payment {payment.id} retried by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='payment_retry',
                resource='payment',
                resource_id=payment.id,
                ip=get_client_ip(request)
            )
            return Response({'message': 'Payment retry initiated.', 'payment': PaymentDetailSerializer(payment).data})

    @action(detail=True, methods=['post'])
    def expire(self, request, id=None):
        """Expire a pending payment."""
        payment = self.get_object()
        if payment.status != PaymentStatus.PENDING:
            raise BadRequestError(_('Only pending payments can be expired.'))
        with transaction.atomic():
            payment.expire()
            logger.info(f'Payment {payment.id} expired by user {request.user.id}')
            return Response({'message': 'Payment expired.', 'payment': PaymentDetailSerializer(payment).data})

    @action(detail=True, methods=['post'])
    def reverse(self, request, id=None):
        """Reverse a payment."""
        payment = self.get_object()
        if payment.status not in [PaymentStatus.PENDING, PaymentStatus.PROCESSING, PaymentStatus.FAILED]:
            raise BadRequestError(_('Payment cannot be reversed.'))
        reason = request.data.get('reason', 'Reversed')
        with transaction.atomic():
            payment.reverse_payment(reason)
            logger.info(f'Payment {payment.id} reversed by user {request.user.id}')
            return Response({'message': 'Payment reversed.', 'payment': PaymentDetailSerializer(payment).data})

    @action(detail=True, methods=['get'])
    def transactions(self, request, id=None):
        """Get all transactions for a payment."""
        payment = self.get_object()
        transactions = payment.transactions.all().order_by('-created_at')
        serializer = PaymentTransactionSerializer(transactions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def gateway_logs(self, request, id=None):
        """Get all gateway logs for a payment."""
        payment = self.get_object()
        logs = payment.gateway_logs.all().order_by('-created_at')[:50]
        serializer = PaymentGatewayLogSerializer(logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def reconciliations(self, request, id=None):
        """Get all reconciliations for a payment."""
        payment = self.get_object()
        recs = payment.reconciliations.all().order_by('-reconciled_at')
        serializer = PaymentReconciliationSerializer(recs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def disputes(self, request, id=None):
        """Get all disputes for a payment."""
        payment = self.get_object()
        disputes = payment.disputes.all().order_by('-created_at')
        serializer = PaymentDisputeSerializer(disputes, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def stats(self, request, id=None):
        """Get statistics for a specific payment."""
        payment = self.get_object()
        stats = {
            'id': payment.id,
            'amount': float(payment.amount),
            'platform_fee': float(payment.platform_fee),
            'gateway_fee': float(payment.gateway_fee),
            'total_fee': float(payment.total_fee),
            'net_amount': float(payment.net_amount),
            'retry_count': payment.retry_count,
            'transaction_count': payment.transactions.count(),
            'reconciliation_count': payment.reconciliations.count(),
            'dispute_count': payment.disputes.count(),
        }
        return Response(stats)

    @action(detail=False, methods=['get'])
    def my_payments(self, request):
        """Get payments for the current user."""
        user = request.user
        queryset = Payment.objects.filter(user=user, deleted_at__isnull=True).order_by('-created_at')
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = PaymentListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = PaymentListSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def stats_overview(self, request):
        """Get overview payment statistics (admin only)."""
        if not request.user.is_superuser:
            raise PermissionDeniedError(_('Super admin access required.'))
        stats = get_payment_statistics()
        serializer = PaymentStatisticsSerializer(stats)
        return Response(serializer.data)


# ============================================================================
# PAYOUT VIEW SET
# ============================================================================

class PayoutViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Payout model with full CRUD and additional actions.
    """

    queryset = Payout.objects.filter(deleted_at__isnull=True)
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return PayoutListSerializer
        elif self.action == 'retrieve':
            return PayoutDetailSerializer
        elif self.action == 'create':
            return PayoutCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return PayoutUpdateSerializer
        else:
            return PayoutDetailSerializer

    def get_permissions(self):
        if self.action in ['create']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanCreatePayout]
        elif self.action in ['update', 'partial_update']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanUpdatePayout]
        elif self.action == 'destroy':
            permission_classes = [IsAuthenticated, IsActiveUser, CanDeletePayout]
        elif self.action in ['retrieve', 'list']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanViewPayout]
        elif self.action in ['complete', 'fail', 'cancel', 'put_on_hold']:
            permission_classes = [IsAuthenticated, IsActiveUser, CanProcessPayout]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()

        if not user.is_superuser:
            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)
            queryset = queryset.filter(
                Q(user=user) | Q(group_id__in=member_group_ids)
            )

        group_id = self.request.query_params.get('group_id')
        if group_id:
            queryset = queryset.filter(group_id=group_id)

        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search) |
                Q(user__email__icontains=search)
            )

        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)

        return queryset.select_related('user', 'group', 'winner_history', 'created_by')

    def perform_create(self, serializer):
        with transaction.atomic():
            payout = serializer.save(created_by=self.request.user)
            logger.info(f'Payout {payout.id} created by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='payout_create',
                resource='payout',
                resource_id=payout.id,
                ip=get_client_ip(self.request)
            )

    def perform_update(self, serializer):
        with transaction.atomic():
            instance = self.get_object()
            old_status = instance.status
            payout = serializer.save()
            logger.info(f'Payout {payout.id} updated by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='payout_update',
                resource='payout',
                resource_id=payout.id,
                ip=get_client_ip(self.request),
                details={'old_status': old_status, 'new_status': payout.status}
            )

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance.deleted_at = timezone.now()
            instance.save(update_fields=['deleted_at'])
            logger.info(f'Payout {instance.id} soft deleted by user {self.request.user.id}')

    @action(detail=True, methods=['post'])
    def complete(self, request, id=None):
        """Complete a pending payout."""
        payout = self.get_object()
        if not payout.can_be_completed:
            raise BadRequestError(_('Payout cannot be completed.'))
        ref = request.data.get('reference_number')
        with transaction.atomic():
            payout.complete(ref)
            logger.info(f'Payout {payout.id} completed by user {request.user.id}')
            return Response({'message': 'Payout completed.', 'payout': PayoutDetailSerializer(payout).data})

    @action(detail=True, methods=['post'])
    def fail(self, request, id=None):
        """Mark a payout as failed."""
        payout = self.get_object()
        if not payout.can_be_failed:
            raise BadRequestError(_('Payout cannot be failed.'))
        reason = request.data.get('reason', 'Failed')
        with transaction.atomic():
            payout.fail(reason)
            logger.info(f'Payout {payout.id} failed by user {request.user.id}')
            return Response({'message': 'Payout failed.', 'payout': PayoutDetailSerializer(payout).data})

    @action(detail=True, methods=['post'])
    def cancel(self, request, id=None):
        """Cancel a payout."""
        payout = self.get_object()
        if not payout.can_be_cancelled:
            raise BadRequestError(_('Payout cannot be cancelled.'))
        reason = request.data.get('reason', 'Cancelled')
        with transaction.atomic():
            payout.cancel(reason)
            logger.info(f'Payout {payout.id} cancelled by user {request.user.id}')
            return Response({'message': 'Payout cancelled.', 'payout': PayoutDetailSerializer(payout).data})

    @action(detail=True, methods=['post'])
    def put_on_hold(self, request, id=None):
        """Put a payout on hold."""
        payout = self.get_object()
        if payout.status not in [PayoutStatus.PENDING, PayoutStatus.PROCESSING]:
            raise BadRequestError(_('Payout cannot be put on hold.'))
        reason = request.data.get('reason', 'On hold')
        with transaction.atomic():
            payout.put_on_hold(reason)
            logger.info(f'Payout {payout.id} put on hold by user {request.user.id}')
            return Response({'message': 'Payout put on hold.', 'payout': PayoutDetailSerializer(payout).data})

    @action(detail=False, methods=['get'])
    def my_payouts(self, request):
        """Get payouts for the current user."""
        user = request.user
        queryset = Payout.objects.filter(user=user, deleted_at__isnull=True).order_by('-created_at')
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = PayoutListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = PayoutListSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def stats_overview(self, request):
        """Get overview payout statistics (admin only)."""
        if not request.user.is_superuser:
            raise PermissionDeniedError(_('Super admin access required.'))
        stats = get_payout_statistics()
        serializer = PayoutStatisticsSerializer(stats)
        return Response(serializer.data)


# ============================================================================
# PAYMENT TRANSACTION VIEW SET
# ============================================================================

class PaymentTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing payment transactions.
    """
    queryset = PaymentTransaction.objects.all()
    serializer_class = PaymentTransactionSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_superuser:
            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)
            queryset = queryset.filter(
                Q(user=user) | Q(group_id__in=member_group_ids)
            )

        payment_id = self.request.query_params.get('payment_id')
        if payment_id:
            queryset = queryset.filter(payment_id=payment_id)
        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('user', 'group', 'payment')

    def get_permissions(self):
        return [IsAuthenticated()]


# ============================================================================
# PAYMENT GATEWAY LOG VIEW SET
# ============================================================================

class PaymentGatewayLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing gateway logs.
    """
    queryset = PaymentGatewayLog.objects.all()
    serializer_class = PaymentGatewayLogSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_superuser:
            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)
            queryset = queryset.filter(
                Q(payment__user=user) | Q(payment__group_id__in=member_group_ids)
            )

        payment_id = self.request.query_params.get('payment_id')
        if payment_id:
            queryset = queryset.filter(payment_id=payment_id)
        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('payment')

    def get_permissions(self):
        return [IsAuthenticated()]


# ============================================================================
# PAYMENT WEBHOOK VIEW
# ============================================================================

class PaymentWebhookView(APIView):
    """
    Endpoint for receiving webhooks from payment gateways.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, gateway=None):
        """
        Handle webhook from a specific gateway.
        """
        raw_payload = request.body
        payload = request.data
        headers = request.headers

        # Log raw webhook
        webhook_log = PaymentWebhookLog.objects.create(
            gateway=gateway or 'unknown',
            event_type=payload.get('event', 'unknown'),
            payload=payload,
            headers=dict(headers),
            signature=headers.get('X-Webhook-Signature', ''),
            verified=False,
            processed=False,
            created_at=timezone.now(),
        )

        # Verify signature if secret configured
        secret = getattr(settings, f'{gateway.upper()}_WEBHOOK_SECRET', '')
        if secret:
            signature = headers.get('X-Webhook-Signature', '')
            is_valid = verify_webhook_signature(raw_payload, signature, secret)
            webhook_log.verified = is_valid
            webhook_log.save(update_fields=['verified'])
            if not is_valid:
                logger.warning(f'Invalid webhook signature from {gateway}')
                return Response({'error': 'Invalid signature'}, status=status.HTTP_401_UNAUTHORIZED)

        # Process event
        try:
            with transaction.atomic():
                processed = process_webhook_events.delay(webhook_log.id)
                webhook_log.processed = True
                webhook_log.processed_at = timezone.now()
                webhook_log.save(update_fields=['processed', 'processed_at'])
                logger.info(f'Webhook {webhook_log.id} processed for gateway {gateway}')
                return Response({'status': 'accepted'}, status=status.HTTP_200_OK)
        except Exception as e:
            webhook_log.error_message = str(e)
            webhook_log.save(update_fields=['error_message'])
            logger.error(f'Webhook processing failed: {e}')
            return Response({'error': 'Processing failed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================================
# PAYMENT RECONCILIATION VIEW SET
# ============================================================================

class PaymentReconciliationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing payment reconciliations.
    """
    queryset = PaymentReconciliation.objects.all()
    serializer_class = PaymentReconciliationSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_superuser:
            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)
            queryset = queryset.filter(
                Q(user=user) | Q(group_id__in=member_group_ids)
            )

        payment_id = self.request.query_params.get('payment_id')
        if payment_id:
            queryset = queryset.filter(payment_id=payment_id)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        ordering = self.request.query_params.get('ordering', '-reconciled_at')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('user', 'group', 'payment')

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsSuperAdminUser()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        with transaction.atomic():
            rec = serializer.save()
            logger.info(f'Reconciliation {rec.id} created by user {self.request.user.id}')

    @action(detail=True, methods=['post'])
    def match(self, request, id=None):
        """Mark reconciliation as matched."""
        rec = self.get_object()
        if rec.status == 'matched':
            return Response({'message': 'Already matched.'})
        rec.status = 'matched'
        rec.reconciled_at = timezone.now()
        rec.save(update_fields=['status', 'reconciled_at'])
        # Update payment status if needed
        if rec.payment.status == PaymentStatus.PENDING:
            rec.payment.complete()
        return Response({'message': 'Reconciliation matched.', 'reconciliation': PaymentReconciliationSerializer(rec).data})


# ============================================================================
# PAYMENT DISPUTE VIEW SET
# ============================================================================

class PaymentDisputeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing payment disputes.
    """
    queryset = PaymentDispute.objects.all()
    serializer_class = PaymentDisputeSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_superuser:
            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)
            queryset = queryset.filter(
                Q(user=user) | Q(payment__group_id__in=member_group_ids)
            )

        payment_id = self.request.query_params.get('payment_id')
        if payment_id:
            queryset = queryset.filter(payment_id=payment_id)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('user', 'payment', 'created_by')

    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), IsActiveUser]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsSuperAdminUser()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        with transaction.atomic():
            dispute = serializer.save(created_by=self.request.user)
            logger.info(f'Dispute {dispute.id} created by user {self.request.user.id}')

    @action(detail=True, methods=['post'])
    def resolve(self, request, id=None):
        """Resolve a dispute."""
        dispute = self.get_object()
        if dispute.status != 'pending':
            raise BadRequestError(_('Dispute already resolved.'))
        resolution = request.data.get('resolution', 'Resolved')
        dispute.status = 'resolved'
        dispute.resolution = resolution
        dispute.resolved_at = timezone.now()
        dispute.save(update_fields=['status', 'resolution', 'resolved_at'])
        return Response({'message': 'Dispute resolved.', 'dispute': PaymentDisputeSerializer(dispute).data})

    @action(detail=True, methods=['post'])
    def reject(self, request, id=None):
        """Reject a dispute."""
        dispute = self.get_object()
        if dispute.status != 'pending':
            raise BadRequestError(_('Dispute already resolved.'))
        reason = request.data.get('resolution', 'Rejected')
        dispute.status = 'rejected'
        dispute.resolution = reason
        dispute.resolved_at = timezone.now()
        dispute.save(update_fields=['status', 'resolution', 'resolved_at'])
        return Response({'message': 'Dispute rejected.', 'dispute': PaymentDisputeSerializer(dispute).data})


# ============================================================================
# SETTLEMENT VIEW SET
# ============================================================================

class SettlementViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing settlements.
    """
    queryset = Settlement.objects.all()
    serializer_class = SettlementSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_superuser:
            queryset = queryset.none()
        ordering = self.request.query_params.get('ordering', '-settlement_date')
        queryset = queryset.order_by(ordering)
        return queryset

    def get_permissions(self):
        return [IsAuthenticated(), IsSuperAdminUser()]

    def perform_create(self, serializer):
        with transaction.atomic():
            settlement = serializer.save(created_by=self.request.user)
            logger.info(f'Settlement {settlement.id} created by user {self.request.user.id}')


# ============================================================================
# PAYMENT METHOD VIEW SET
# ============================================================================

class PaymentMethodViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing user payment methods.
    """
    serializer_class = PaymentMethodSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            queryset = PaymentMethod.objects.all()
        else:
            queryset = PaymentMethod.objects.filter(user=user)
        ordering = self.request.query_params.get('ordering', '-is_default')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('user')

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsActiveUser]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        user = self.request.user
        if serializer.validated_data.get('is_default', False):
            PaymentMethod.objects.filter(user=user, is_default=True).update(is_default=False)
        serializer.save(user=user)

    def perform_update(self, serializer):
        user = self.request.user
        if serializer.validated_data.get('is_default', False):
            PaymentMethod.objects.filter(user=user, is_default=True).exclude(id=self.get_object().id).update(is_default=False)
        serializer.save()


# ============================================================================
# PAYMENT AUDIT VIEW SET
# ============================================================================

class PaymentAuditViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing payment audit logs.
    """
    queryset = PaymentAudit.objects.all()
    serializer_class = PaymentAuditSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if not user.is_superuser:
            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)
            queryset = queryset.filter(
                Q(user=user) | Q(payment__group_id__in=member_group_ids)
            )

        payment_id = self.request.query_params.get('payment_id')
        if payment_id:
            queryset = queryset.filter(payment_id=payment_id)
        ordering = self.request.query_params.get('ordering', '-timestamp')
        queryset = queryset.order_by(ordering)
        return queryset.select_related('user', 'payment')

    def get_permissions(self):
        return [IsAuthenticated()]


# ============================================================================
# PAYMENT STATISTICS VIEW
# ============================================================================

class PaymentStatisticsView(APIView):
    """
    View for payment statistics (admin only).
    """
    permission_classes = [IsAuthenticated, IsSuperAdminUser]

    def get(self, request):
        group_id = request.query_params.get('group_id')
        user_id = request.query_params.get('user_id')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        stats = get_payment_statistics(
            user_id=user_id,
            group_id=group_id,
            start_date=date_from,
            end_date=date_to
        )
        serializer = PaymentStatisticsSerializer(stats)
        return Response(serializer.data)


# ============================================================================
# PAYOUT STATISTICS VIEW
# ============================================================================

class PayoutStatisticsView(APIView):
    """
    View for payout statistics (admin only).
    """
    permission_classes = [IsAuthenticated, IsSuperAdminUser]

    def get(self, request):
        group_id = request.query_params.get('group_id')
        user_id = request.query_params.get('user_id')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        stats = get_payout_statistics(
            user_id=user_id,
            group_id=group_id,
            start_date=date_from,
            end_date=date_to
        )
        serializer = PayoutStatisticsSerializer(stats)
        return Response(serializer.data)