"""
Payments app for the Digital Ekub Platform.

This app handles all payment-related operations including:
- Payment processing via multiple gateways (Chapa, Telebirr, Bank Transfer)
- Payout management for group winners
- Transaction reconciliation and auditing
- Webhook handling and verification
- Fee calculation and deduction (platform fees, transaction fees)
- Payment refunds and reversals
- Settlement and reconciliation reporting
- Dispute management
- Payment analytics and reporting
- Integration with external payment providers

All payment operations are centralized in this app and include comprehensive
security, logging, and reconciliation features.
"""

__version__ = '1.0.0'
__app_name__ = 'payments'
__author__ = 'Digital Ekub Team'
__description__ = 'Payment processing and management for the Digital Ekub Platform'

# Set default app configuration for Django
default_app_config = 'apps.payments.apps.PaymentsConfig'

# ============================================================================
# IMPORT ALL PUBLIC COMPONENTS
# ============================================================================

# Models
from .models import (
    Payment,
    PaymentTransaction,
    Payout,
    PaymentGatewayLog,
    PaymentWebhookLog,
    PaymentReconciliation,
    PaymentDispute,
    Settlement,
    PaymentMethod,
    PaymentAudit,
)

# Serializers
from .serializers import (
    PaymentSerializer,
    PaymentDetailSerializer,
    PaymentCreateSerializer,
    PaymentUpdateSerializer,
    PaymentListSerializer,
    PaymentTransactionSerializer,
    PayoutSerializer,
    PayoutDetailSerializer,
    PayoutCreateSerializer,
    PayoutUpdateSerializer,
    PayoutListSerializer,
    PaymentGatewayLogSerializer,
    PaymentWebhookLogSerializer,
    PaymentReconciliationSerializer,
    PaymentDisputeSerializer,
    SettlementSerializer,
    PaymentMethodSerializer,
    PaymentAuditSerializer,
    WebhookPayloadSerializer,
    PaymentStatisticsSerializer,
    PayoutStatisticsSerializer,
)

# Views
from .views import (
    PaymentViewSet,
    PayoutViewSet,
    PaymentTransactionViewSet,
    PaymentGatewayLogViewSet,
    PaymentWebhookView,
    PaymentReconciliationViewSet,
    PaymentDisputeViewSet,
    SettlementViewSet,
    PaymentMethodViewSet,
    PaymentAuditViewSet,
    PaymentStatisticsView,
    PayoutStatisticsView,
    WebhookReceiverView,
)

# Permissions
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
    IsGroupAdminOfPayment,
    IsMemberOfPaymentGroup,
)

# Tasks
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

# Signals
from .signals import (
    payment_post_save_handler,
    payment_pre_save_handler,
    payment_pre_delete_handler,
    payout_post_save_handler,
    payout_pre_save_handler,
    payout_pre_delete_handler,
    payment_transaction_post_save_handler,
    payment_transaction_pre_save_handler,
)

# ============================================================================
# PAYMENT CONSTANTS (RE-EXPORT)
# ============================================================================

from apps.common.constants import (
    PaymentStatus,
    PaymentMethod,
    PayoutStatus,
)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

import logging
import hashlib
import hmac
import json
import base64
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple, Union
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
from django.conf import settings

from apps.users.models import User
from apps.groups.models import Group
from apps.common.utils import format_currency, calculate_platform_fee

logger = logging.getLogger(__name__)


def get_payment(payment_id: int) -> Optional['Payment']:
    """
    Get a payment by ID with error handling.

    Args:
        payment_id: ID of the payment

    Returns:
        Payment instance or None if not found
    """
    from .models import Payment
    try:
        return Payment.objects.get(id=payment_id)
    except Payment.DoesNotExist:
        return None


def get_payout(payout_id: int) -> Optional['Payout']:
    """
    Get a payout by ID with error handling.

    Args:
        payout_id: ID of the payout

    Returns:
        Payout instance or None if not found
    """
    from .models import Payout
    try:
        return Payout.objects.get(id=payout_id)
    except Payout.DoesNotExist:
        return None


def get_user_payments(user_id: int, status: Optional[str] = None) -> List['Payment']:
    """
    Get all payments for a user, optionally filtered by status.

    Args:
        user_id: ID of the user
        status: Optional status filter

    Returns:
        List of Payment instances
    """
    from .models import Payment
    queryset = Payment.objects.filter(user_id=user_id)
    if status:
        queryset = queryset.filter(status=status)
    return list(queryset.select_related('group', 'contribution'))


def get_group_payments(group_id: int, status: Optional[str] = None) -> List['Payment']:
    """
    Get all payments for a group, optionally filtered by status.

    Args:
        group_id: ID of the group
        status: Optional status filter

    Returns:
        List of Payment instances
    """
    from .models import Payment
    queryset = Payment.objects.filter(group_id=group_id)
    if status:
        queryset = queryset.filter(status=status)
    return list(queryset.select_related('user', 'contribution'))


def get_user_payouts(user_id: int, status: Optional[str] = None) -> List['Payout']:
    """
    Get all payouts for a user, optionally filtered by status.

    Args:
        user_id: ID of the user
        status: Optional status filter

    Returns:
        List of Payout instances
    """
    from .models import Payout
    queryset = Payout.objects.filter(user_id=user_id)
    if status:
        queryset = queryset.filter(status=status)
    return list(queryset.select_related('group'))


def get_group_payouts(group_id: int, status: Optional[str] = None) -> List['Payout']:
    """
    Get all payouts for a group, optionally filtered by status.

    Args:
        group_id: ID of the group
        status: Optional status filter

    Returns:
        List of Payout instances
    """
    from .models import Payout
    queryset = Payout.objects.filter(group_id=group_id)
    if status:
        queryset = queryset.filter(status=status)
    return list(queryset.select_related('user'))


def calculate_payment_fees(amount: Decimal, gateway: str = 'chapa') -> Dict[str, Decimal]:
    """
    Calculate transaction fees for a payment.

    Args:
        amount: Payment amount
        gateway: Payment gateway (chapa, telebirr, bank_transfer)

    Returns:
        Dict with fee breakdown
    """
    platform_fee = calculate_platform_fee(amount)

    # Gateway-specific fees
    gateway_fee = Decimal('0.00')
    if gateway == 'chapa':
        gateway_fee = amount * Decimal('0.025')  # 2.5%
    elif gateway == 'telebirr':
        gateway_fee = amount * Decimal('0.015')  # 1.5%
    elif gateway == 'bank_transfer':
        gateway_fee = amount * Decimal('0.005')  # 0.5%
    else:
        gateway_fee = amount * Decimal('0.02')   # 2% default

    gateway_fee = gateway_fee.quantize(Decimal('0.01'))

    total_fee = platform_fee + gateway_fee
    net_amount = amount - total_fee

    return {
        'platform_fee': platform_fee,
        'gateway_fee': gateway_fee,
        'total_fee': total_fee,
        'net_amount': net_amount,
    }


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify webhook signature using HMAC-SHA256.

    Args:
        payload: Raw payload bytes
        signature: Provided signature header
        secret: Webhook secret

    Returns:
        bool: True if signature is valid
    """
    if not secret:
        return False
    expected = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def generate_payment_reference(prefix: str = 'PAY') -> str:
    """
    Generate a unique payment reference.

    Args:
        prefix: Prefix for the reference

    Returns:
        str: Unique reference
    """
    import uuid
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
    unique_id = str(uuid.uuid4()).replace('-', '')[:8].upper()
    return f"{prefix}-{timestamp}-{unique_id}"


def generate_payout_reference(prefix: str = 'POUT') -> str:
    """
    Generate a unique payout reference.

    Args:
        prefix: Prefix for the reference

    Returns:
        str: Unique reference
    """
    return generate_payment_reference(prefix)


def process_payment(
    user: User,
    group: Group,
    amount: Decimal,
    payment_method: str,
    gateway: str = 'chapa',
    contribution_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Process a payment for a user.

    Args:
        user: User making the payment
        group: Group the payment is for
        amount: Amount to pay
        payment_method: Payment method (e.g., 'telebirr', 'chapa', 'bank_transfer')
        gateway: Payment gateway to use
        contribution_id: Optional contribution ID

    Returns:
        Dict with payment result
    """
    from .models import Payment, PaymentTransaction

    # Calculate fees
    fees = calculate_payment_fees(amount, gateway)

    # Generate reference
    reference = generate_payment_reference()

    with transaction.atomic():
        # Create payment record
        payment = Payment.objects.create(
            user=user,
            group=group,
            amount=amount,
            payment_method=payment_method,
            gateway=gateway,
            reference=reference,
            platform_fee=fees['platform_fee'],
            gateway_fee=fees['gateway_fee'],
            total_fee=fees['total_fee'],
            net_amount=fees['net_amount'],
            status=PaymentStatus.PENDING,
            contribution_id=contribution_id,
            created_at=timezone.now(),
        )

        # Create transaction record
        transaction = PaymentTransaction.objects.create(
            payment=payment,
            user=user,
            group=group,
            amount=amount,
            gateway=gateway,
            transaction_id=reference,
            status='pending',
            request_payload={},
            created_at=timezone.now(),
        )

        # Log the transaction
        logger.info(f'Payment {payment.id} initiated for user {user.id}')

        # Optionally trigger the actual payment via gateway
        # This would be handled by a separate task

        return {
            'payment': payment,
            'transaction': transaction,
            'reference': reference,
            'amount': amount,
            'fees': fees,
        }


def process_payout(
    user: User,
    group: Group,
    amount: Decimal,
    payout_method: str = 'bank_transfer',
    reference: Optional[str] = None,
    winner_history_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Process a payout to a user.

    Args:
        user: User receiving the payout
        group: Group the payout is from
        amount: Amount to pay out
        payout_method: Payout method (e.g., 'bank_transfer', 'telebirr', 'cash')
        reference: Optional reference
        winner_history_id: Optional winner history ID

    Returns:
        Dict with payout result
    """
    from .models import Payout

    if not reference:
        reference = generate_payout_reference()

    # Calculate fees (payout fees are typically lower)
    fees = calculate_payment_fees(amount, 'bank_transfer')

    with transaction.atomic():
        payout = Payout.objects.create(
            user=user,
            group=group,
            amount=amount,
            payout_method=payout_method,
            reference=reference,
            platform_fee=fees['platform_fee'],
            gateway_fee=fees['gateway_fee'],
            total_fee=fees['total_fee'],
            net_amount=fees['net_amount'],
            status=PayoutStatus.PENDING,
            winner_history_id=winner_history_id,
            created_at=timezone.now(),
        )

        logger.info(f'Payout {payout.id} initiated for user {user.id}')

        return {
            'payout': payout,
            'reference': reference,
            'amount': amount,
            'fees': fees,
        }


def verify_webhook_payload(payload: Dict[str, Any], expected_event: str) -> bool:
    """
    Verify webhook payload for expected event type.

    Args:
        payload: Webhook payload
        expected_event: Expected event type

    Returns:
        bool: True if event matches expected
    """
    event = payload.get('event')
    return event == expected_event


def get_payment_statistics(
    user_id: Optional[int] = None,
    group_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Get payment statistics aggregated.

    Args:
        user_id: Optional user filter
        group_id: Optional group filter
        start_date: Optional start date
        end_date: Optional end date

    Returns:
        Dict with payment statistics
    """
    from django.db.models import Sum, Count
    from .models import Payment

    queryset = Payment.objects.all()

    if user_id:
        queryset = queryset.filter(user_id=user_id)
    if group_id:
        queryset = queryset.filter(group_id=group_id)
    if start_date:
        queryset = queryset.filter(created_at__gte=start_date)
    if end_date:
        queryset = queryset.filter(created_at__lte=end_date)

    total_payments = queryset.count()
    completed = queryset.filter(status=PaymentStatus.COMPLETED).count()
    pending = queryset.filter(status=PaymentStatus.PENDING).count()
    failed = queryset.filter(status=PaymentStatus.FAILED).count()

    total_amount = queryset.filter(status=PaymentStatus.COMPLETED).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    total_fees = queryset.filter(status=PaymentStatus.COMPLETED).aggregate(
        total=Sum('total_fee')
    )['total'] or Decimal('0.00')

    total_net = queryset.filter(status=PaymentStatus.COMPLETED).aggregate(
        total=Sum('net_amount')
    )['total'] or Decimal('0.00')

    return {
        'total_payments': total_payments,
        'completed': completed,
        'pending': pending,
        'failed': failed,
        'total_amount': float(total_amount),
        'total_fees': float(total_fees),
        'total_net': float(total_net),
    }


def get_payout_statistics(
    user_id: Optional[int] = None,
    group_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Get payout statistics aggregated.

    Args:
        user_id: Optional user filter
        group_id: Optional group filter
        start_date: Optional start date
        end_date: Optional end date

    Returns:
        Dict with payout statistics
    """
    from django.db.models import Sum, Count
    from .models import Payout

    queryset = Payout.objects.all()

    if user_id:
        queryset = queryset.filter(user_id=user_id)
    if group_id:
        queryset = queryset.filter(group_id=group_id)
    if start_date:
        queryset = queryset.filter(created_at__gte=start_date)
    if end_date:
        queryset = queryset.filter(created_at__lte=end_date)

    total_payouts = queryset.count()
    completed = queryset.filter(status=PayoutStatus.COMPLETED).count()
    pending = queryset.filter(status=PayoutStatus.PENDING).count()
    failed = queryset.filter(status=PayoutStatus.FAILED).count()

    total_amount = queryset.filter(status=PayoutStatus.COMPLETED).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    total_fees = queryset.filter(status=PayoutStatus.COMPLETED).aggregate(
        total=Sum('total_fee')
    )['total'] or Decimal('0.00')

    total_net = queryset.filter(status=PayoutStatus.COMPLETED).aggregate(
        total=Sum('net_amount')
    )['total'] or Decimal('0.00')

    return {
        'total_payouts': total_payouts,
        'completed': completed,
        'pending': pending,
        'failed': failed,
        'total_amount': float(total_amount),
        'total_fees': float(total_fees),
        'total_net': float(total_net),
    }


def reconcile_payment(payment_id: int, reconciliation_data: Dict[str, Any]) -> bool:
    """
    Reconcile a payment with external gateway data.

    Args:
        payment_id: ID of the payment
        reconciliation_data: Data from reconciliation

    Returns:
        bool: True if reconciled successfully
    """
    from .models import Payment, PaymentReconciliation

    payment = get_payment(payment_id)
    if not payment:
        return False

    with transaction.atomic():
        reconciliation = PaymentReconciliation.objects.create(
            payment=payment,
            user=payment.user,
            group=payment.group,
            external_reference=reconciliation_data.get('external_reference'),
            external_status=reconciliation_data.get('status'),
            external_data=reconciliation_data,
            reconciled_at=timezone.now(),
            status='completed' if reconciliation_data.get('matched', False) else 'failed',
        )

        if reconciliation_data.get('matched', False):
            payment.status = PaymentStatus.COMPLETED
            payment.save(update_fields=['status'])

        logger.info(f'Payment {payment_id} reconciled successfully')
        return True


def refund_payment(payment_id: int, reason: str = 'Refund requested') -> bool:
    """
    Refund a payment.

    Args:
        payment_id: ID of the payment
        reason: Reason for refund

    Returns:
        bool: True if refunded successfully
    """
    from .models import Payment

    payment = get_payment(payment_id)
    if not payment:
        return False

    if payment.status != PaymentStatus.COMPLETED:
        return False

    with transaction.atomic():
        payment.status = PaymentStatus.REFUNDED
        payment.refund_reason = reason
        payment.refunded_at = timezone.now()
        payment.save(update_fields=['status', 'refund_reason', 'refunded_at'])

        logger.info(f'Payment {payment_id} refunded: {reason}')
        return True


def get_payment_report(
    start_date: datetime,
    end_date: datetime,
    group_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Generate a payment report for a date range.

    Args:
        start_date: Start date
        end_date: End date
        group_id: Optional group filter
        user_id: Optional user filter

    Returns:
        Dict with payment report
    """
    from .models import Payment
    from django.db.models import Sum, Count

    queryset = Payment.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        status=PaymentStatus.COMPLETED,
    )

    if group_id:
        queryset = queryset.filter(group_id=group_id)
    if user_id:
        queryset = queryset.filter(user_id=user_id)

    total_amount = queryset.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_fees = queryset.aggregate(total=Sum('total_fee'))['total'] or Decimal('0.00')
    total_net = queryset.aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')
    count = queryset.count()

    # Group by payment method
    method_breakdown = queryset.values('payment_method').annotate(
        total=Sum('amount'),
        count=Count('id')
    )

    return {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'total_payments': count,
        'total_amount': float(total_amount),
        'total_fees': float(total_fees),
        'total_net': float(total_net),
        'method_breakdown': [
            {
                'method': item['payment_method'],
                'count': item['count'],
                'total_amount': float(item['total']),
            }
            for item in method_breakdown
        ],
    }


# ============================================================================
# CACHE INVALIDATION UTILITY
# ============================================================================

def invalidate_payment_cache(payment_id: int):
    """
    Invalidate all cache keys related to a payment.
    """
    keys = [
        f'payment_{payment_id}',
        f'payment_detail_{payment_id}',
        f'payment_stats_{payment_id}',
        f'payment_transactions_{payment_id}',
    ]
    for key in keys:
        cache.delete(key)
    logger.debug(f'Cache invalidated for payment {payment_id}')


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
    'Payment',
    'PaymentTransaction',
    'Payout',
    'PaymentGatewayLog',
    'PaymentWebhookLog',
    'PaymentReconciliation',
    'PaymentDispute',
    'Settlement',
    'PaymentMethod',
    'PaymentAudit',

    # Serializers
    'PaymentSerializer',
    'PaymentDetailSerializer',
    'PaymentCreateSerializer',
    'PaymentUpdateSerializer',
    'PaymentListSerializer',
    'PaymentTransactionSerializer',
    'PayoutSerializer',
    'PayoutDetailSerializer',
    'PayoutCreateSerializer',
    'PayoutUpdateSerializer',
    'PayoutListSerializer',
    'PaymentGatewayLogSerializer',
    'PaymentWebhookLogSerializer',
    'PaymentReconciliationSerializer',
    'PaymentDisputeSerializer',
    'SettlementSerializer',
    'PaymentMethodSerializer',
    'PaymentAuditSerializer',
    'WebhookPayloadSerializer',
    'PaymentStatisticsSerializer',
    'PayoutStatisticsSerializer',

    # Views
    'PaymentViewSet',
    'PayoutViewSet',
    'PaymentTransactionViewSet',
    'PaymentGatewayLogViewSet',
    'PaymentWebhookView',
    'PaymentReconciliationViewSet',
    'PaymentDisputeViewSet',
    'SettlementViewSet',
    'PaymentMethodViewSet',
    'PaymentAuditViewSet',
    'PaymentStatisticsView',
    'PayoutStatisticsView',
    'WebhookReceiverView',

    # Permissions
    'IsPaymentOwner',
    'IsPaymentOwnerOrGroupAdmin',
    'CanProcessPayment',
    'CanViewPayment',
    'CanCreatePayment',
    'CanUpdatePayment',
    'CanDeletePayment',
    'IsPayoutOwner',
    'IsPayoutOwnerOrGroupAdmin',
    'CanProcessPayout',
    'CanViewPayout',
    'CanCreatePayout',
    'CanUpdatePayout',
    'CanDeletePayout',
    'IsGroupAdminOfPayment',
    'IsMemberOfPaymentGroup',

    # Tasks
    'process_pending_payments',
    'process_payouts',
    'reconcile_payments',
    'send_payment_reminders',
    'update_payment_stats',
    'cleanup_payment_logs',
    'generate_payment_report',
    'send_payment_digest',
    'process_webhook_events',
    'retry_failed_payments',
    'auto_refund_expired',

    # Signals
    'payment_post_save_handler',
    'payment_pre_save_handler',
    'payment_pre_delete_handler',
    'payout_post_save_handler',
    'payout_pre_save_handler',
    'payout_pre_delete_handler',
    'payment_transaction_post_save_handler',
    'payment_transaction_pre_save_handler',

    # Constants
    'PaymentStatus',
    'PaymentMethod',
    'PayoutStatus',

    # Helper functions
    'get_payment',
    'get_payout',
    'get_user_payments',
    'get_group_payments',
    'get_user_payouts',
    'get_group_payouts',
    'calculate_payment_fees',
    'verify_webhook_signature',
    'generate_payment_reference',
    'generate_payout_reference',
    'process_payment',
    'process_payout',
    'verify_webhook_payload',
    'get_payment_statistics',
    'get_payout_statistics',
    'reconcile_payment',
    'refund_payment',
    'get_payment_report',
    'invalidate_payment_cache',
]

# ============================================================================
# LOGGING
# ============================================================================

logger.info(f'Payments app v{__version__} initialized')