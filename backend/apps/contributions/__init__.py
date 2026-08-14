"""
Contributions app for the Digital Ekub Platform.

This app handles all contribution-related operations including:
- Creating and managing contributions
- Processing contribution payments
- Tracking contribution status (pending, paid, overdue, refunded)
- Calculating contribution statistics
- Managing contribution reminders
- Processing contribution payments
- Handling overdue contributions
- Contribution validation and verification
- Contribution reporting and analytics

All contribution-related operations are centralized in this app.
"""

__version__ = '1.0.0'
__app_name__ = 'contributions'
__author__ = 'Digital Ekub Team'
__description__ = 'Contribution management for the Digital Ekub Platform'

# Set default app configuration for Django
default_app_config = 'apps.contributions.apps.ContributionsConfig'

# ============================================================================
# IMPORT ALL PUBLIC COMPONENTS
# ============================================================================

# Models
from .models import Contribution, ContributionPayment, ContributionReminder, ContributionAudit

# Serializers
from .serializers import (
    ContributionSerializer,
    ContributionDetailSerializer,
    ContributionCreateSerializer,
    ContributionUpdateSerializer,
    ContributionListSerializer,
    ContributionPaymentSerializer,
    ContributionPaymentCreateSerializer,
    ContributionPaymentUpdateSerializer,
    ContributionReminderSerializer,
    ContributionReminderCreateSerializer,
    ContributionAuditSerializer,
    ContributionStatsSerializer,
    ContributionSummarySerializer,
    MemberContributionSummarySerializer,
    GroupContributionSummarySerializer,
)

# Views
from .views import (
    ContributionViewSet,
    ContributionPaymentViewSet,
    ContributionReminderViewSet,
    ContributionAuditViewSet,
    ContributionStatsView,
    ContributionSummaryView,
    MemberContributionView,
    GroupContributionView,
    ProcessContributionPaymentView,
    MarkContributionPaidView,
    CancelContributionView,
    RefundContributionView,
)

# Permissions
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

# Tasks
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

# Signals
from .signals import (
    contribution_post_save_handler,
    contribution_pre_save_handler,
    contribution_pre_delete_handler,
    contribution_payment_post_save_handler,
    contribution_payment_pre_save_handler,
)

# ============================================================================
# CONTRIBUTION CONSTANTS (RE-EXPORT)
# ============================================================================

from apps.common.constants import ContributionStatus, ContributionType

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_contribution(contribution_id: int) -> Optional['Contribution']:
    """
    Get a contribution by ID with error handling.

    Args:
        contribution_id: ID of the contribution

    Returns:
        Contribution instance or None if not found
    """
    try:
        return Contribution.objects.get(id=contribution_id)
    except Contribution.DoesNotExist:
        return None


def get_contribution_payment(contribution_id: int) -> Optional['ContributionPayment']:
    """
    Get payment for a contribution.

    Args:
        contribution_id: ID of the contribution

    Returns:
        ContributionPayment instance or None if not found
    """
    from .models import ContributionPayment
    try:
        return ContributionPayment.objects.get(contribution_id=contribution_id)
    except ContributionPayment.DoesNotExist:
        return None


def get_user_contributions(user_id: int, status: Optional[str] = None) -> QuerySet:
    """
    Get all contributions for a user, optionally filtered by status.

    Args:
        user_id: ID of the user
        status: Optional status filter

    Returns:
        QuerySet of contributions
    """
    from .models import Contribution
    queryset = Contribution.objects.filter(user_id=user_id)
    if status:
        queryset = queryset.filter(status=status)
    return queryset.select_related('group')


def get_group_contributions(group_id: int, status: Optional[str] = None) -> QuerySet:
    """
    Get all contributions for a group, optionally filtered by status.

    Args:
        group_id: ID of the group
        status: Optional status filter

    Returns:
        QuerySet of contributions
    """
    from .models import Contribution
    queryset = Contribution.objects.filter(group_id=group_id)
    if status:
        queryset = queryset.filter(status=status)
    return queryset.select_related('user')


def get_member_contributions(group_id: int, user_id: int) -> QuerySet:
    """
    Get all contributions for a specific member in a group.

    Args:
        group_id: ID of the group
        user_id: ID of the user

    Returns:
        QuerySet of contributions
    """
    from .models import Contribution
    return Contribution.objects.filter(
        group_id=group_id,
        user_id=user_id
    ).order_by('due_date')


def get_pending_contributions_for_user(user_id: int) -> QuerySet:
    """
    Get all pending contributions for a user.

    Args:
        user_id: ID of the user

    Returns:
        QuerySet of pending contributions
    """
    from .models import Contribution
    return Contribution.objects.filter(
        user_id=user_id,
        status=ContributionStatus.PENDING
    ).order_by('due_date')


def get_overdue_contributions_for_user(user_id: int) -> QuerySet:
    """
    Get all overdue contributions for a user.

    Args:
        user_id: ID of the user

    Returns:
        QuerySet of overdue contributions
    """
    from .models import Contribution
    from django.utils import timezone
    return Contribution.objects.filter(
        user_id=user_id,
        status=ContributionStatus.OVERDUE,
        due_date__lt=timezone.now()
    ).order_by('due_date')


def get_contribution_summary_for_group(group_id: int) -> Dict[str, Any]:
    """
    Get a summary of contributions for a group.

    Args:
        group_id: ID of the group

    Returns:
        Dict with contribution summary
    """
    from .models import Contribution
    from django.db.models import Sum, Count

    contributions = Contribution.objects.filter(group_id=group_id)

    total = contributions.count()
    pending = contributions.filter(status=ContributionStatus.PENDING).count()
    paid = contributions.filter(status=ContributionStatus.PAID).count()
    overdue = contributions.filter(status=ContributionStatus.OVERDUE).count()
    cancelled = contributions.filter(status=ContributionStatus.CANCELLED).count()
    refunded = contributions.filter(status=ContributionStatus.REFUNDED).count()

    total_amount = contributions.filter(status=ContributionStatus.PAID).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    pending_amount = contributions.filter(status=ContributionStatus.PENDING).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    overdue_amount = contributions.filter(status=ContributionStatus.OVERDUE).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    return {
        'total_contributions': total,
        'pending': pending,
        'paid': paid,
        'overdue': overdue,
        'cancelled': cancelled,
        'refunded': refunded,
        'total_paid_amount': float(total_amount),
        'pending_amount': float(pending_amount),
        'overdue_amount': float(overdue_amount),
        'completion_rate': round((paid / total * 100) if total > 0 else 0, 2),
    }


def get_member_contribution_summary(group_id: int, user_id: int) -> Dict[str, Any]:
    """
    Get a summary of contributions for a specific member.

    Args:
        group_id: ID of the group
        user_id: ID of the user

    Returns:
        Dict with member contribution summary
    """
    from .models import Contribution
    from django.db.models import Sum

    contributions = Contribution.objects.filter(group_id=group_id, user_id=user_id)

    total = contributions.count()
    paid = contributions.filter(status=ContributionStatus.PAID).count()
    pending = contributions.filter(status=ContributionStatus.PENDING).count()
    overdue = contributions.filter(status=ContributionStatus.OVERDUE).count()

    total_paid = contributions.filter(status=ContributionStatus.PAID).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    pending_amount = contributions.filter(status=ContributionStatus.PENDING).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    return {
        'total_contributions': total,
        'paid': paid,
        'pending': pending,
        'overdue': overdue,
        'total_paid_amount': float(total_paid),
        'pending_amount': float(pending_amount),
        'status': 'good' if pending == 0 and overdue == 0 else 'has_pending' if pending > 0 else 'overdue',
    }


def calculate_contribution_penalty(amount: Decimal, overdue_days: int) -> Decimal:
    """
    Calculate penalty for overdue contribution.

    Args:
        amount: Contribution amount
        overdue_days: Number of days overdue

    Returns:
        Decimal: Penalty amount
    """
    if overdue_days <= 0:
        return Decimal('0.00')

    # 2% per day up to 50% maximum
    penalty_rate = min(Decimal(str(overdue_days)) * Decimal('0.02'), Decimal('0.50'))
    penalty = amount * penalty_rate
    return penalty.quantize(Decimal('0.01'))


def can_pay_contribution(contribution: 'Contribution') -> bool:
    """
    Check if a contribution can be paid.

    Args:
        contribution: Contribution instance

    Returns:
        bool: True if contribution can be paid
    """
    if not contribution:
        return False
    if contribution.status not in [ContributionStatus.PENDING, ContributionStatus.OVERDUE]:
        return False
    if contribution.group.is_cancelled or contribution.group.is_completed:
        return False
    if not contribution.group.is_active:
        return False
    return True


def process_contribution_payment(contribution_id: int, payment_method: str, reference: Optional[str] = None) -> bool:
    """
    Process a contribution payment.

    Args:
        contribution_id: ID of the contribution
        payment_method: Payment method (telebirr, chapa, bank_transfer, cash)
        reference: Optional payment reference

    Returns:
        bool: True if payment was processed successfully
    """
    from .models import Contribution, ContributionPayment
    from django.db import transaction
    from decimal import Decimal

    try:
        contribution = Contribution.objects.get(id=contribution_id)
    except Contribution.DoesNotExist:
        return False

    if not can_pay_contribution(contribution):
        return False

    with transaction.atomic():
        # Create payment record
        payment = ContributionPayment.objects.create(
            contribution=contribution,
            user=contribution.user,
            group=contribution.group,
            amount=contribution.amount,
            payment_method=payment_method,
            reference=reference,
            status='completed',
            paid_at=timezone.now()
        )

        # Update contribution status
        contribution.status = ContributionStatus.PAID
        contribution.paid_date = timezone.now()
        contribution.payment = payment
        contribution.save(update_fields=['status', 'paid_date', 'payment'])

        # Update user statistics
        from apps.users.models import User
        user = contribution.user
        user.total_contributed += contribution.amount
        user.on_time_payments += 1
        if contribution.due_date and timezone.now().date() <= contribution.due_date:
            user.reputation_score = min(100, user.reputation_score + 1)
        user.save(update_fields=['total_contributed', 'on_time_payments', 'reputation_score'])

        # Update group statistics
        group = contribution.group
        group.total_paid += contribution.amount
        group.total_contributions += 1
        group.save(update_fields=['total_paid', 'total_contributions'])

        # Log activity
        from apps.groups.models import GroupActivity
        GroupActivity.objects.create(
            group=group,
            user=contribution.user,
            action='contribution_paid',
            details={
                'contribution_id': contribution.id,
                'amount': float(contribution.amount),
                'method': payment_method,
            },
            timestamp=timezone.now()
        )

        logger.info(f'Contribution {contribution_id} paid by user {contribution.user.id} via {payment_method}')
        return True

    except Exception as e:
        logger.error(f'Error processing contribution payment {contribution_id}: {str(e)}')
        return False


def mark_contribution_overdue(contribution_id: int) -> bool:
    """
    Mark a contribution as overdue.

    Args:
        contribution_id: ID of the contribution

    Returns:
        bool: True if marked overdue
    """
    from .models import Contribution
    from django.db import transaction

    try:
        contribution = Contribution.objects.get(id=contribution_id)
    except Contribution.DoesNotExist:
        return False

    if contribution.status != ContributionStatus.PENDING:
        return False

    with transaction.atomic():
        contribution.status = ContributionStatus.OVERDUE
        contribution.save(update_fields=['status'])

        # Reduce user reputation for overdue
        user = contribution.user
        user.reputation_score = max(0, user.reputation_score - 2)
        user.defaulted_count += 1
        user.save(update_fields=['reputation_score', 'defaulted_count'])

        logger.info(f'Contribution {contribution_id} marked overdue')
        return True

    except Exception as e:
        logger.error(f'Error marking contribution {contribution_id} overdue: {str(e)}')
        return False


def cancel_contribution(contribution_id: int, reason: Optional[str] = None) -> bool:
    """
    Cancel a contribution.

    Args:
        contribution_id: ID of the contribution
        reason: Optional reason for cancellation

    Returns:
        bool: True if cancelled
    """
    from .models import Contribution
    from django.db import transaction

    try:
        contribution = Contribution.objects.get(id=contribution_id)
    except Contribution.DoesNotExist:
        return False

    if contribution.status in [ContributionStatus.PAID, ContributionStatus.CANCELLED]:
        return False

    with transaction.atomic():
        contribution.status = ContributionStatus.CANCELLED
        contribution.save(update_fields=['status'])

        # Log activity
        from apps.groups.models import GroupActivity
        GroupActivity.objects.create(
            group=contribution.group,
            user=contribution.user,
            action='contribution_cancelled',
            details={
                'contribution_id': contribution.id,
                'reason': reason,
            },
            timestamp=timezone.now()
        )

        logger.info(f'Contribution {contribution_id} cancelled')
        return True

    except Exception as e:
        logger.error(f'Error cancelling contribution {contribution_id}: {str(e)}')
        return False


def refund_contribution(contribution_id: int, reason: Optional[str] = None) -> bool:
    """
    Refund a contribution.

    Args:
        contribution_id: ID of the contribution
        reason: Optional reason for refund

    Returns:
        bool: True if refunded
    """
    from .models import Contribution
    from django.db import transaction

    try:
        contribution = Contribution.objects.get(id=contribution_id)
    except Contribution.DoesNotExist:
        return False

    if contribution.status != ContributionStatus.PAID:
        return False

    with transaction.atomic():
        contribution.status = ContributionStatus.REFUNDED
        contribution.save(update_fields=['status'])

        # Update user statistics
        user = contribution.user
        user.total_contributed -= contribution.amount
        user.save(update_fields=['total_contributed'])

        # Update group statistics
        group = contribution.group
        group.total_paid -= contribution.amount
        group.save(update_fields=['total_paid'])

        # Log activity
        from apps.groups.models import GroupActivity
        GroupActivity.objects.create(
            group=group,
            user=user,
            action='contribution_refunded',
            details={
                'contribution_id': contribution.id,
                'amount': float(contribution.amount),
                'reason': reason,
            },
            timestamp=timezone.now()
        )

        logger.info(f'Contribution {contribution_id} refunded')
        return True

    except Exception as e:
        logger.error(f'Error refunding contribution {contribution_id}: {str(e)}')
        return False


# ============================================================================
# CONTRIBUTION VALIDATION FUNCTIONS
# ============================================================================

def validate_contribution_amount(amount: Decimal, group_contribution_amount: Decimal) -> bool:
    """
    Validate contribution amount matches group's contribution amount.

    Args:
        amount: Contribution amount
        group_contribution_amount: Group's contribution amount

    Returns:
        bool: True if amount is valid
    """
    return amount == group_contribution_amount


def validate_contribution_due_date(due_date: date, group: Group) -> bool:
    """
    Validate contribution due date is within group's cycle.

    Args:
        due_date: Due date
        group: Group instance

    Returns:
        bool: True if due date is valid
    """
    from django.utils import timezone
    if due_date < timezone.now().date():
        return False
    if group.end_date and due_date > group.end_date.date():
        return False
    return True


def validate_contribution_user(user: User, group: Group) -> bool:
    """
    Validate user is a member of the group.

    Args:
        user: User instance
        group: Group instance

    Returns:
        bool: True if user is a member
    """
    from apps.groups.models import GroupMember
    return GroupMember.objects.filter(group=group, user=user, is_active=True).exists()


# ============================================================================
# CONTRIBUTION UTILITY FUNCTIONS
# ============================================================================

def get_next_contribution_date(group: Group) -> Optional[date]:
    """
    Calculate the next contribution due date for a group.

    Args:
        group: Group instance

    Returns:
        Optional[date]: Next contribution due date
    """
    from django.utils import timezone
    from datetime import timedelta

    if group.is_completed or group.is_cancelled:
        return None

    # Calculate next date based on frequency
    frequency_map = {
        'daily': timedelta(days=1),
        'weekly': timedelta(weeks=1),
        'biweekly': timedelta(weeks=2),
        'monthly': timedelta(days=30),
        'quarterly': timedelta(days=90),
        'yearly': timedelta(days=365),
    }

    interval = frequency_map.get(group.frequency, timedelta(days=30))
    current_date = timezone.now().date()

    # Calculate next date from start date
    days_since_start = (current_date - group.start_date.date()).days
    cycles_completed = days_since_start // interval.days if interval.days > 0 else 0
    next_date = group.start_date.date() + (interval * (cycles_completed + 1))

    # Ensure next date is in the future
    while next_date <= current_date:
        next_date += interval

    return next_date


def get_contribution_due_date(group: Group, round_number: int) -> Optional[date]:
    """
    Calculate the due date for a specific contribution round.

    Args:
        group: Group instance
        round_number: Round number (0-indexed)

    Returns:
        Optional[date]: Due date for the round
    """
    from datetime import timedelta

    if group.is_completed or group.is_cancelled:
        return None

    frequency_map = {
        'daily': timedelta(days=1),
        'weekly': timedelta(weeks=1),
        'biweekly': timedelta(weeks=2),
        'monthly': timedelta(days=30),
        'quarterly': timedelta(days=90),
        'yearly': timedelta(days=365),
    }

    interval = frequency_map.get(group.frequency, timedelta(days=30))
    due_date = group.start_date + (interval * round_number)
    return due_date.date() if due_date else None


# ============================================================================
# CONTRIBUTION STATISTICS FUNCTIONS
# ============================================================================

def get_contribution_stats_for_user(user_id: int) -> Dict[str, Any]:
    """
    Get contribution statistics for a user.

    Args:
        user_id: ID of the user

    Returns:
        Dict with user contribution statistics
    """
    from .models import Contribution
    from django.db.models import Sum

    contributions = Contribution.objects.filter(user_id=user_id)

    total = contributions.count()
    paid = contributions.filter(status=ContributionStatus.PAID).count()
    pending = contributions.filter(status=ContributionStatus.PENDING).count()
    overdue = contributions.filter(status=ContributionStatus.OVERDUE).count()

    total_paid = contributions.filter(status=ContributionStatus.PAID).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    return {
        'total_contributions': total,
        'paid': paid,
        'pending': pending,
        'overdue': overdue,
        'total_paid_amount': float(total_paid),
        'completion_rate': round((paid / total * 100) if total > 0 else 0, 2),
    }


def get_contribution_stats_for_group(group_id: int) -> Dict[str, Any]:
    """
    Get contribution statistics for a group.

    Args:
        group_id: ID of the group

    Returns:
        Dict with group contribution statistics
    """
    from .models import Contribution
    from django.db.models import Sum, Count

    contributions = Contribution.objects.filter(group_id=group_id)

    total = contributions.count()
    paid = contributions.filter(status=ContributionStatus.PAID).count()
    pending = contributions.filter(status=ContributionStatus.PENDING).count()
    overdue = contributions.filter(status=ContributionStatus.OVERDUE).count()

    total_paid = contributions.filter(status=ContributionStatus.PAID).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    total_pending = contributions.filter(status=ContributionStatus.PENDING).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    total_overdue = contributions.filter(status=ContributionStatus.OVERDUE).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    return {
        'total_contributions': total,
        'paid': paid,
        'pending': pending,
        'overdue': overdue,
        'total_paid_amount': float(total_paid),
        'pending_amount': float(total_pending),
        'overdue_amount': float(total_overdue),
        'completion_rate': round((paid / total * 100) if total > 0 else 0, 2),
    }


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
    'Contribution',
    'ContributionPayment',
    'ContributionReminder',
    'ContributionAudit',

    # Serializers
    'ContributionSerializer',
    'ContributionDetailSerializer',
    'ContributionCreateSerializer',
    'ContributionUpdateSerializer',
    'ContributionListSerializer',
    'ContributionPaymentSerializer',
    'ContributionPaymentCreateSerializer',
    'ContributionPaymentUpdateSerializer',
    'ContributionReminderSerializer',
    'ContributionReminderCreateSerializer',
    'ContributionAuditSerializer',
    'ContributionStatsSerializer',
    'ContributionSummarySerializer',
    'MemberContributionSummarySerializer',
    'GroupContributionSummarySerializer',

    # Views
    'ContributionViewSet',
    'ContributionPaymentViewSet',
    'ContributionReminderViewSet',
    'ContributionAuditViewSet',
    'ContributionStatsView',
    'ContributionSummaryView',
    'MemberContributionView',
    'GroupContributionView',
    'ProcessContributionPaymentView',
    'MarkContributionPaidView',
    'CancelContributionView',
    'RefundContributionView',

    # Permissions
    'IsContributionOwner',
    'IsContributionOwnerOrGroupAdmin',
    'CanPayContribution',
    'CanProcessContribution',
    'CanViewContribution',
    'CanCreateContribution',
    'CanUpdateContribution',
    'CanDeleteContribution',
    'IsGroupAdminOfContribution',
    'IsMemberOfContributionGroup',

    # Tasks
    'process_pending_contributions',
    'check_overdue_contributions',
    'send_contribution_reminders',
    'process_contribution_payments',
    'update_contribution_stats',
    'cleanup_completed_contributions',
    'generate_contribution_report',
    'send_contribution_digest',
    'process_refunds',
    'auto_waive_overdue_contributions',

    # Signals
    'contribution_post_save_handler',
    'contribution_pre_save_handler',
    'contribution_pre_delete_handler',
    'contribution_payment_post_save_handler',
    'contribution_payment_pre_save_handler',

    # Constants
    'ContributionStatus',
    'ContributionType',

    # Helper functions
    'get_contribution',
    'get_contribution_payment',
    'get_user_contributions',
    'get_group_contributions',
    'get_member_contributions',
    'get_pending_contributions_for_user',
    'get_overdue_contributions_for_user',
    'get_contribution_summary_for_group',
    'get_member_contribution_summary',
    'calculate_contribution_penalty',
    'can_pay_contribution',
    'process_contribution_payment',
    'mark_contribution_overdue',
    'cancel_contribution',
    'refund_contribution',

    # Validation functions
    'validate_contribution_amount',
    'validate_contribution_due_date',
    'validate_contribution_user',

    # Utility functions
    'get_next_contribution_date',
    'get_contribution_due_date',

    # Statistics functions
    'get_contribution_stats_for_user',
    'get_contribution_stats_for_group',
]

# ============================================================================
# LOGGING
# ============================================================================

import logging
logger = logging.getLogger(__name__)
logger.info(f'Contributions app v{__version__} initialized')