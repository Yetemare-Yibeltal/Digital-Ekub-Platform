"""
Models for the groups app.

This module defines all database models related to group management:
- Group: Main group entity with full lifecycle management
- GroupMember: Membership and roles with permissions
- GroupInvitation: Invitations to join groups
- GroupSetting: Configurable settings per group
- GroupActivity: Audit log for group actions
- GroupWinnerHistory: History of selected winners
"""

from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, F, Sum, Count, Avg, Max, Min, OuterRef, Subquery
from django.core.exceptions import ValidationError
from decimal import Decimal
import uuid
import random
import logging
from typing import Optional, List, Tuple, Dict, Any, Union

from apps.users.models import User
from apps.common.constants import (
    GroupStatus,
    GroupMemberRole,
    GroupType,
    GroupFrequency,
    GroupWinnerSelection,
    GroupInvitationStatus,
    PlatformConfig,
)
from apps.common.utils import generate_referral_code, format_currency, get_current_time

logger = logging.getLogger(__name__)


# ============================================================================
# GROUP MODEL
# ============================================================================

class Group(models.Model):
    """
    Main Group model representing a savings group with full lifecycle management.
    """

    # ========================================================================
    # BASIC INFO
    # ========================================================================

    name = models.CharField(
        _('group name'),
        max_length=255,
        db_index=True,
        help_text=_('Name of the savings group')
    )
    description = models.TextField(
        _('description'),
        blank=True,
        null=True,
        help_text=_('Detailed description of the group')
    )
    type = models.CharField(
        _('group type'),
        max_length=20,
        choices=GroupType.CHOICES,
        default=GroupType.PUBLIC,
        db_index=True,
        help_text=_('Public groups are visible to all, private require invitation')
    )

    # ========================================================================
    # STATUS AND LIFECYCLE
    # ========================================================================

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=GroupStatus.CHOICES,
        default=GroupStatus.PENDING,
        db_index=True,
        help_text=_('Current status of the group')
    )

    # ========================================================================
    # FINANCIAL SETTINGS
    # ========================================================================

    frequency = models.CharField(
        _('contribution frequency'),
        max_length=20,
        choices=GroupFrequency.CHOICES,
        default=GroupFrequency.MONTHLY,
        help_text=_('How often contributions are collected')
    )
    contribution_amount = models.DecimalField(
        _('contribution amount'),
        max_digits=15,
        decimal_places=2,
        default=100.00,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text=_('Amount each member contributes per cycle')
    )
    cycle_length = models.PositiveIntegerField(
        _('cycle length'),
        default=10,
        validators=[MinValueValidator(2), MaxValueValidator(100)],
        help_text=_('Number of rounds/cycles in the group')
    )
    max_members = models.PositiveIntegerField(
        _('maximum members'),
        default=20,
        validators=[MinValueValidator(2), MaxValueValidator(100)],
        help_text=_('Maximum number of members allowed')
    )

    # ========================================================================
    # WINNER SELECTION
    # ========================================================================

    winner_selection = models.CharField(
        _('winner selection method'),
        max_length=20,
        choices=GroupWinnerSelection.CHOICES,
        default=GroupWinnerSelection.FIXED,
        help_text=_('Method used to select winners')
    )

    # ========================================================================
    # ROUND TRACKING
    # ========================================================================

    current_round = models.PositiveIntegerField(
        _('current round'),
        default=0,
        db_index=True,
        help_text=_('Current round number (0-indexed)')
    )

    # ========================================================================
    # DATES
    # ========================================================================

    start_date = models.DateTimeField(
        _('start date'),
        default=timezone.now,
        db_index=True,
        help_text=_('When the group started or will start')
    )
    end_date = models.DateTimeField(
        _('end date'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('When the group is expected to end')
    )
    completed_at = models.DateTimeField(
        _('completed at'),
        null=True,
        blank=True,
        help_text=_('When the group was completed')
    )
    paused_at = models.DateTimeField(
        _('paused at'),
        null=True,
        blank=True,
        help_text=_('When the group was paused')
    )
    cancelled_at = models.DateTimeField(
        _('cancelled at'),
        null=True,
        blank=True,
        help_text=_('When the group was cancelled')
    )

    # ========================================================================
    # METADATA
    # ========================================================================

    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='groups_created',
        verbose_name=_('created by'),
        db_index=True,
        help_text=_('User who created the group')
    )
    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )
    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True,
        db_index=True
    )
    deleted_at = models.DateTimeField(
        _('deleted at'),
        null=True,
        blank=True,
        db_index=True,
        help_text=_('Soft delete timestamp')
    )

    # ========================================================================
    # DENORMALIZED STATISTICS (for performance)
    # ========================================================================

    members_count = models.PositiveIntegerField(
        _('members count'),
        default=0,
        help_text=_('Number of active members')
    )
    total_contributions = models.PositiveIntegerField(
        _('total contributions'),
        default=0,
        help_text=_('Total number of contributions made')
    )
    total_paid = models.DecimalField(
        _('total paid'),
        max_digits=15,
        decimal_places=2,
        default=0.00,
        help_text=_('Total amount paid')
    )
    total_pending = models.DecimalField(
        _('total pending'),
        max_digits=15,
        decimal_places=2,
        default=0.00,
        help_text=_('Total amount pending')
    )
    total_overdue = models.DecimalField(
        _('total overdue'),
        max_digits=15,
        decimal_places=2,
        default=0.00,
        help_text=_('Total amount overdue')
    )

    # ========================================================================
    # META
    # ========================================================================

    class Meta:
        db_table = 'groups'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['created_by', 'status']),
            models.Index(fields=['name']),
            models.Index(fields=['status', 'members_count']),
        ]
        verbose_name = _('group')
        verbose_name_plural = _('groups')

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        """
        Override save to auto-calculate end_date and update statistics.
        """
        # Auto-set end_date if not set
        if not self.end_date and self.start_date and self.cycle_length:
            delta = self._calculate_duration()
            self.end_date = self.start_date + delta

        # If status is completed, set completed_at
        if self.status == GroupStatus.COMPLETED and not self.completed_at:
            self.completed_at = timezone.now()

        # If status is cancelled, set cancelled_at
        if self.status == GroupStatus.CANCELLED and not self.cancelled_at:
            self.cancelled_at = timezone.now()

        super().save(*args, **kwargs)

    def _calculate_duration(self) -> timezone.timedelta:
        """Calculate duration based on frequency and cycle_length."""
        frequency_map = {
            'daily': timezone.timedelta(days=1),
            'weekly': timezone.timedelta(weeks=1),
            'biweekly': timezone.timedelta(weeks=2),
            'monthly': timezone.timedelta(days=30),
            'quarterly': timezone.timedelta(days=90),
            'yearly': timezone.timedelta(days=365),
        }
        duration = frequency_map.get(self.frequency, timezone.timedelta(days=30))
        return duration * self.cycle_length

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_full(self) -> bool:
        """Check if group has reached max members."""
        return self.members_count >= self.max_members

    @property
    def is_active(self) -> bool:
        """Check if group is active."""
        return self.status == GroupStatus.ACTIVE

    @property
    def is_completed(self) -> bool:
        """Check if group is completed."""
        return self.status == GroupStatus.COMPLETED

    @property
    def is_cancelled(self) -> bool:
        """Check if group is cancelled."""
        return self.status == GroupStatus.CANCELLED

    @property
    def is_paused(self) -> bool:
        """Check if group is paused."""
        return self.status == GroupStatus.PAUSED

    @property
    def is_pending(self) -> bool:
        """Check if group is pending."""
        return self.status == GroupStatus.PENDING

    @property
    def is_expired(self) -> bool:
        """Check if group is expired."""
        return self.status == GroupStatus.EXPIRED

    @property
    def is_deleted(self) -> bool:
        """Check if group is soft-deleted."""
        return self.deleted_at is not None

    @property
    def total_cycles(self) -> int:
        """Total number of cycles in the group."""
        return self.cycle_length

    @property
    def remaining_cycles(self) -> int:
        """Remaining cycles."""
        return max(0, self.cycle_length - self.current_round)

    @property
    def progress_percentage(self) -> float:
        """Progress percentage based on current round."""
        if self.cycle_length == 0:
            return 0.0
        return round((self.current_round / self.cycle_length) * 100, 2)

    @property
    def total_potential_amount(self) -> Decimal:
        """Total potential amount that will be collected."""
        return self.contribution_amount * self.cycle_length * self.max_members

    @property
    def current_pot_amount(self) -> Decimal:
        """Current pot amount for the current round."""
        return self.contribution_amount * self.members_count

    @property
    def next_round_date(self) -> Optional[timezone.datetime]:
        """Calculate the next round date based on frequency."""
        if self.is_completed or self.is_cancelled:
            return None

        last_round_date = self.start_date + self._calculate_duration() * self.current_round
        return last_round_date + self._calculate_duration()

    @property
    def days_remaining(self) -> int:
        """Days remaining until group completion."""
        if self.is_completed or self.is_cancelled:
            return 0
        if not self.end_date:
            return 0
        delta = self.end_date - timezone.now()
        return max(0, delta.days)

    @property
    def completion_status(self) -> str:
        """Get human-readable completion status."""
        if self.is_completed:
            return 'completed'
        if self.is_cancelled:
            return 'cancelled'
        if self.is_paused:
            return 'paused'
        if self.current_round >= self.cycle_length:
            return 'ready_to_complete'
        return f'round_{self.current_round+1}_of_{self.cycle_length}'

    # ========================================================================
    # MEMBERSHIP MANAGEMENT
    # ========================================================================

    @transaction.atomic
    def add_member(self, user: User, role: str = 'member') -> 'GroupMember':
        """
        Add a user as a member of the group.

        Args:
            user: User to add
            role: Role to assign (default: 'member')

        Returns:
            GroupMember: The created membership

        Raises:
            ValidationError: If group is full, inactive, or user already a member
        """
        # Validation checks
        if self.is_full:
            raise ValidationError(_('Group is full. Maximum members reached.'))
        if not self.is_active and not self.is_pending:
            raise ValidationError(_('Group is not active or pending.'))
        if self.is_deleted:
            raise ValidationError(_('Group has been deleted.'))
        if self.is_completed:
            raise ValidationError(_('Group is completed.'))
        if self.is_cancelled:
            raise ValidationError(_('Group is cancelled.'))

        if role not in dict(GroupMemberRole.CHOICES):
            role = 'member'

        # Check if user is already a member
        if GroupMember.objects.filter(group=self, user=user, is_active=True).exists():
            raise ValidationError(_('User is already a member of this group.'))

        # Create membership
        member = GroupMember.objects.create(
            group=self,
            user=user,
            role=role,
            joined_at=timezone.now()
        )

        # Update denormalized count
        self.members_count = GroupMember.objects.filter(group=self, is_active=True).count()
        self.save(update_fields=['members_count'])

        # If group was pending and now has at least 2 members, activate it
        if self.is_pending and self.members_count >= 2:
            self.status = GroupStatus.ACTIVE
            self.save(update_fields=['status'])

        # Create welcome activity
        self.log_activity(
            action='member_joined',
            user=user,
            details={'role': role}
        )

        logger.info(f'User {user.id} joined group {self.id} as {role}')
        return member

    @transaction.atomic
    def remove_member(self, user: User, reason: Optional[str] = None) -> bool:
        """
        Remove a member from the group (soft delete membership).

        Args:
            user: User to remove
            reason: Optional reason for removal

        Returns:
            bool: True if removed successfully

        Raises:
            ValidationError: If user is not a member or is the only owner
        """
        try:
            member = GroupMember.objects.get(group=self, user=user, is_active=True)
        except GroupMember.DoesNotExist:
            raise ValidationError(_('User is not a member of this group.'))

        # Prevent removal of the only owner
        if member.role == 'owner':
            owners = GroupMember.objects.filter(group=self, role='owner', is_active=True)
            if owners.count() == 1:
                raise ValidationError(_('Cannot remove the only owner. Transfer ownership first.'))

        # Soft delete membership
        member.is_active = False
        member.left_at = timezone.now()
        member.reason = reason
        member.save(update_fields=['is_active', 'left_at', 'reason'])

        # Update denormalized count
        self.members_count = GroupMember.objects.filter(group=self, is_active=True).count()
        self.save(update_fields=['members_count'])

        # Log activity
        self.log_activity(
            action='member_left' if not reason else 'member_removed',
            user=user,
            details={'reason': reason}
        )

        logger.info(f'User {user.id} removed from group {self.id}')
        return True

    def promote_to_admin(self, user: User) -> bool:
        """Promote a member to admin."""
        try:
            member = GroupMember.objects.get(group=self, user=user, is_active=True)
        except GroupMember.DoesNotExist:
            raise ValidationError(_('User is not a member.'))

        if member.role in ['admin', 'owner']:
            return True

        member.role = 'admin'
        member.save(update_fields=['role'])

        self.log_activity(
            action='promoted_to_admin',
            user=user,
            details={'new_role': 'admin'}
        )

        logger.info(f'User {user.id} promoted to admin in group {self.id}')
        return True

    def demote_to_member(self, user: User) -> bool:
        """Demote an admin to member."""
        try:
            member = GroupMember.objects.get(group=self, user=user, is_active=True)
        except GroupMember.DoesNotExist:
            raise ValidationError(_('User is not a member.'))

        if member.role == 'owner':
            raise ValidationError(_('Cannot demote the owner.'))

        if member.role == 'member':
            return True

        member.role = 'member'
        member.save(update_fields=['role'])

        self.log_activity(
            action='demoted_to_member',
            user=user,
            details={'new_role': 'member'}
        )

        logger.info(f'User {user.id} demoted to member in group {self.id}')
        return True

    @transaction.atomic
    def transfer_ownership(self, new_owner: User) -> bool:
        """Transfer ownership to another member."""
        try:
            new_member = GroupMember.objects.get(group=self, user=new_owner, is_active=True)
        except GroupMember.DoesNotExist:
            raise ValidationError(_('New owner must be a member.'))

        old_owner = GroupMember.objects.get(group=self, role='owner', is_active=True)

        # Demote old owner to admin
        old_owner.role = 'admin'
        old_owner.save(update_fields=['role'])

        # Promote new owner
        new_member.role = 'owner'
        new_member.save(update_fields=['role'])

        self.log_activity(
            action='ownership_transferred',
            user=new_owner,
            details={'previous_owner': old_owner.user.id}
        )

        logger.info(f'Ownership transferred to {new_owner.id} in group {self.id}')
        return True

    # ========================================================================
    # QUERY METHODS
    # ========================================================================

    def get_members(self, role: Optional[str] = None) -> models.QuerySet:
        """Get all active members, optionally filtered by role."""
        qs = GroupMember.objects.filter(group=self, is_active=True)
        if role:
            qs = qs.filter(role=role)
        return qs.select_related('user')

    def get_admins(self) -> models.QuerySet:
        """Get all admins and owners."""
        return self.get_members(role__in=['admin', 'owner'])

    def get_owner(self) -> Optional['GroupMember']:
        """Get the owner of the group."""
        return GroupMember.objects.filter(group=self, role='owner', is_active=True).first()

    def get_member(self, user: User) -> Optional['GroupMember']:
        """Get the membership record for a user."""
        try:
            return GroupMember.objects.get(group=self, user=user, is_active=True)
        except GroupMember.DoesNotExist:
            return None

    def is_member(self, user: User) -> bool:
        """Check if a user is a member."""
        return GroupMember.objects.filter(group=self, user=user, is_active=True).exists()

    def is_admin(self, user: User) -> bool:
        """Check if a user is an admin or owner."""
        return GroupMember.objects.filter(
            group=self, user=user, role__in=['admin', 'owner'], is_active=True
        ).exists()

    def is_owner(self, user: User) -> bool:
        """Check if a user is the owner."""
        return GroupMember.objects.filter(group=self, user=user, role='owner', is_active=True).exists()

    # ========================================================================
    # WINNER SELECTION
    # ========================================================================

    def select_winner(self, method: Optional[str] = None) -> Optional[User]:
        """
        Select the winner for the current round based on the group's selection method.

        Args:
            method: Override selection method (optional)

        Returns:
            Optional[User]: The winning user, or None if no eligible
        """
        if self.is_completed or self.is_cancelled:
            return None

        if self.members_count < 2:
            return None

        selection_method = method or self.winner_selection

        if selection_method == GroupWinnerSelection.FIXED:
            return self._select_winner_fixed()
        elif selection_method == GroupWinnerSelection.RANDOM:
            return self._select_winner_random()
        else:
            return self._select_winner_random()

    def _select_winner_fixed(self) -> Optional[User]:
        """Select winner using fixed rotation based on join order."""
        from .models import GroupWinnerHistory

        # Get active members ordered by join date
        members = self.get_members().order_by('joined_at')

        if not members:
            return None

        # Get members who have already won in this round
        won_user_ids = GroupWinnerHistory.objects.filter(
            group=self,
            round=self.current_round
        ).values_list('user_id', flat=True)

        # Filter out users who have already won
        eligible_members = members.exclude(user__id__in=won_user_ids)

        if not eligible_members.exists():
            # All members have won, reset the cycle
            eligible_members = members

        # Select based on round index
        member_list = list(eligible_members)
        round_index = self.current_round % len(member_list)
        return member_list[round_index].user

    def _select_winner_random(self) -> Optional[User]:
        """Select winner randomly from eligible members."""
        from .models import GroupWinnerHistory

        # Get active members
        members = self.get_members()

        if not members:
            return None

        # Get members who have already won in this round
        won_user_ids = GroupWinnerHistory.objects.filter(
            group=self,
            round=self.current_round
        ).values_list('user_id', flat=True)

        # Filter out users who have already won
        eligible_members = members.exclude(user__id__in=won_user_ids)

        if not eligible_members.exists():
            # All members have won, reset the cycle
            eligible_members = members

        # Random selection
        member_list = list(eligible_members)
        winner = random.choice(member_list)
        return winner.user

    @transaction.atomic
    def advance_round(self) -> bool:
        """
        Advance to the next round.

        Returns:
            bool: True if advanced successfully
        """
        if self.is_completed or self.is_cancelled:
            return False

        if self.current_round >= self.cycle_length:
            return self.complete_group()

        self.current_round += 1
        self.save(update_fields=['current_round'])

        self.log_activity(
            action='round_advanced',
            user=None,
            details={'round': self.current_round}
        )

        logger.info(f'Group {self.id} advanced to round {self.current_round}')
        return True

    @transaction.atomic
    def complete_group(self) -> bool:
        """Mark the group as completed."""
        if self.is_completed:
            return True

        # Ensure all contributions are paid before completion
        pending = self.get_pending_contributions()
        if pending.exists():
            raise ValidationError(_('Cannot complete group with pending contributions.'))

        overdue = self.get_overdue_contributions()
        if overdue.exists():
            raise ValidationError(_('Cannot complete group with overdue contributions.'))

        self.status = GroupStatus.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at'])

        self.log_activity(
            action='group_completed',
            user=None,
            details={'completed_at': self.completed_at.isoformat()}
        )

        logger.info(f'Group {self.id} completed')
        return True

    @transaction.atomic
    def cancel_group(self, reason: Optional[str] = None) -> bool:
        """Cancel the group."""
        if self.is_cancelled:
            return True

        self.status = GroupStatus.CANCELLED
        self.cancelled_at = timezone.now()
        self.save(update_fields=['status', 'cancelled_at'])

        self.log_activity(
            action='group_cancelled',
            user=None,
            details={'reason': reason}
        )

        logger.info(f'Group {self.id} cancelled')
        return True

    @transaction.atomic
    def pause_group(self, reason: Optional[str] = None) -> bool:
        """Pause the group."""
        if self.is_paused:
            return True

        self.status = GroupStatus.PAUSED
        self.paused_at = timezone.now()
        self.save(update_fields=['status', 'paused_at'])

        self.log_activity(
            action='group_paused',
            user=None,
            details={'reason': reason}
        )

        logger.info(f'Group {self.id} paused')
        return True

    @transaction.atomic
    def resume_group(self) -> bool:
        """Resume a paused group."""
        if not self.is_paused:
            return True

        self.status = GroupStatus.ACTIVE
        self.paused_at = None
        self.save(update_fields=['status', 'paused_at'])

        self.log_activity(
            action='group_resumed',
            user=None,
            details={}
        )

        logger.info(f'Group {self.id} resumed')
        return True

    # ========================================================================
    # CONTRIBUTION METHODS
    # ========================================================================

    def get_contribution_summary(self) -> Dict[str, Any]:
        """Get a summary of contributions for the group."""
        from apps.contributions.models import Contribution

        contributions = Contribution.objects.filter(group=self)
        total = contributions.count()
        paid = contributions.filter(status='paid').count()
        pending = contributions.filter(status='pending').count()
        overdue = contributions.filter(status='overdue').count()
        cancelled = contributions.filter(status='cancelled').count()

        total_amount = contributions.filter(status='paid').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        pending_amount = contributions.filter(status='pending').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        overdue_amount = contributions.filter(status='overdue').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        return {
            'total_contributions': total,
            'paid_contributions': paid,
            'pending_contributions': pending,
            'overdue_contributions': overdue,
            'cancelled_contributions': cancelled,
            'total_paid_amount': float(total_amount),
            'pending_amount': float(pending_amount),
            'overdue_amount': float(overdue_amount),
            'completion_rate': round((paid / total * 100) if total > 0 else 0, 2),
        }

    def get_pending_contributions(self) -> models.QuerySet:
        """Get all pending contributions for the group."""
        from apps.contributions.models import Contribution
        return Contribution.objects.filter(group=self, status='pending')

    def get_overdue_contributions(self) -> models.QuerySet:
        """Get all overdue contributions for the group."""
        from apps.contributions.models import Contribution
        return Contribution.objects.filter(group=self, status='overdue')

    def get_member_contributions(self, user: User) -> Dict[str, Any]:
        """Get contribution summary for a specific member."""
        from apps.contributions.models import Contribution

        contributions = Contribution.objects.filter(group=self, user=user)
        total = contributions.count()
        paid = contributions.filter(status='paid').count()
        pending = contributions.filter(status='pending').count()
        overdue = contributions.filter(status='overdue').count()

        total_amount = contributions.filter(status='paid').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        return {
            'user_id': user.id,
            'total': total,
            'paid': paid,
            'pending': pending,
            'overdue': overdue,
            'total_paid_amount': float(total_amount),
            'status': 'good' if pending == 0 and overdue == 0 else 'has_pending' if pending > 0 else 'overdue',
        }

    # ========================================================================
    # ACTIVITY LOGGING
    # ========================================================================

    def log_activity(self, action: str, user: Optional[User] = None, details: Optional[Dict] = None) -> None:
        """Log an activity for the group."""
        GroupActivity.objects.create(
            group=self,
            user=user,
            action=action,
            details=details or {},
            timestamp=timezone.now()
        )

    # ========================================================================
    # SOFT DELETE
    # ========================================================================

    @transaction.atomic
    def soft_delete(self, reason: Optional[str] = None) -> None:
        """Soft delete the group."""
        self.deleted_at = timezone.now()
        self.status = GroupStatus.CANCELLED
        self.save(update_fields=['deleted_at', 'status'])

        self.log_activity(
            action='group_deleted',
            user=None,
            details={'reason': reason}
        )

        logger.info(f'Group {self.id} soft deleted')

    @transaction.atomic
    def restore(self) -> None:
        """Restore a soft-deleted group."""
        if not self.is_deleted:
            return

        self.deleted_at = None
        self.status = GroupStatus.ACTIVE
        self.save(update_fields=['deleted_at', 'status'])

        self.log_activity(
            action='group_restored',
            user=None,
            details={}
        )

        logger.info(f'Group {self.id} restored')


# ============================================================================
# GROUP MEMBER MODEL
# ============================================================================

class GroupMember(models.Model):
    """Membership model connecting users to groups with roles and status."""

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name=_('group'),
        db_index=True
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='group_memberships',
        verbose_name=_('user'),
        db_index=True
    )
    role = models.CharField(
        _('role'),
        max_length=20,
        choices=GroupMemberRole.CHOICES,
        default=GroupMemberRole.MEMBER,
        db_index=True
    )
    joined_at = models.DateTimeField(
        _('joined at'),
        default=timezone.now,
        db_index=True
    )
    left_at = models.DateTimeField(
        _('left at'),
        null=True,
        blank=True
    )
    is_active = models.BooleanField(
        _('is active'),
        default=True,
        db_index=True
    )
    reason = models.TextField(
        _('reason'),
        blank=True,
        null=True
    )
    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True
    )
    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True
    )

    class Meta:
        db_table = 'group_members'
        ordering = ['-joined_at']
        unique_together = [
            ['group', 'user', 'is_active'],
        ]
        indexes = [
            models.Index(fields=['group', 'role', 'is_active']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['group', 'joined_at']),
        ]
        verbose_name = _('group member')
        verbose_name_plural = _('group members')

    def __str__(self):
        return f"{self.user.email} - {self.group.name} ({self.get_role_display()})"

    @property
    def is_owner(self) -> bool:
        return self.role == 'owner'

    @property
    def is_admin(self) -> bool:
        return self.role in ['admin', 'owner']

    @property
    def is_member(self) -> bool:
        return self.role == 'member'

    def can_manage_group(self) -> bool:
        """Check if user can manage the group (admin or owner)."""
        return self.is_admin

    def can_manage_contributions(self) -> bool:
        """Check if user can manage contributions (admin or owner)."""
        return self.is_admin

    def can_manage_members(self) -> bool:
        """Check if user can manage members (admin or owner)."""
        return self.is_admin


# ============================================================================
# GROUP INVITATION MODEL
# ============================================================================

class GroupInvitation(models.Model):
    """Invitation model for users to join groups."""

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='invitations',
        verbose_name=_('group'),
        db_index=True
    )
    inviter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_invitations',
        verbose_name=_('inviter'),
        db_index=True
    )
    invitee_email = models.EmailField(
        _('invitee email'),
        max_length=255,
        db_index=True
    )
    invitee_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_invitations',
        verbose_name=_('invitee user'),
        db_index=True
    )
    token = models.CharField(
        _('token'),
        max_length=64,
        unique=True,
        db_index=True
    )
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=GroupInvitationStatus.CHOICES,
        default=GroupInvitationStatus.PENDING,
        db_index=True
    )
    expires_at = models.DateTimeField(
        _('expires at'),
        db_index=True
    )
    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True,
        db_index=True
    )
    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True
    )
    accepted_at = models.DateTimeField(
        _('accepted at'),
        null=True,
        blank=True
    )
    message = models.TextField(
        _('message'),
        blank=True,
        null=True,
        help_text=_('Personal message from inviter')
    )

    class Meta:
        db_table = 'group_invitations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['group', 'status']),
            models.Index(fields=['invitee_email', 'status']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['token']),
        ]
        verbose_name = _('group invitation')
        verbose_name_plural = _('group invitations')

    def __str__(self):
        return f"Invitation to {self.invitee_email} for {self.group.name}"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = self._generate_token()
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(days=7)
        super().save(*args, **kwargs)

    def _generate_token(self) -> str:
        """Generate a unique invitation token."""
        return str(uuid.uuid4()).replace('-', '') + str(uuid.uuid4()).replace('-', '')[:16]

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    @property
    def is_pending(self) -> bool:
        return self.status == GroupInvitationStatus.PENDING

    @transaction.atomic
    def accept(self, user: User) -> bool:
        """Accept the invitation and add the user to the group."""
        if self.status != GroupInvitationStatus.PENDING:
            raise ValidationError(_('Invitation is not pending.'))

        if self.is_expired:
            self.status = GroupInvitationStatus.EXPIRED
            self.save(update_fields=['status'])
            raise ValidationError(_('Invitation has expired.'))

        if self.group.is_full:
            raise ValidationError(_('Group is full.'))

        if not self.group.is_active:
            raise ValidationError(_('Group is not active.'))

        # Add member if not already
        if not self.group.is_member(user):
            self.group.add_member(user)
            self.accepted_at = timezone.now()
            self.status = GroupInvitationStatus.ACCEPTED
            self.invitee_user = user
            self.save(update_fields=['status', 'accepted_at', 'invitee_user'])
            return True

        return False

    @transaction.atomic
    def reject(self) -> bool:
        """Reject the invitation."""
        if self.status != GroupInvitationStatus.PENDING:
            return False

        self.status = GroupInvitationStatus.REJECTED
        self.save(update_fields=['status'])
        return True

    @transaction.atomic
    def cancel(self) -> bool:
        """Cancel the invitation."""
        if self.status != GroupInvitationStatus.PENDING:
            return False

        self.status = GroupInvitationStatus.CANCELLED
        self.save(update_fields=['status'])
        return True


# ============================================================================
# GROUP SETTING MODEL
# ============================================================================

class GroupSetting(models.Model):
    """Key-value store for group-specific settings."""

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='settings',
        verbose_name=_('group'),
        db_index=True
    )
    key = models.CharField(
        _('key'),
        max_length=255,
        db_index=True
    )
    value = models.JSONField(
        _('value'),
        default=dict
    )
    description = models.TextField(
        _('description'),
        blank=True,
        null=True
    )
    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True
    )
    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True
    )

    class Meta:
        db_table = 'group_settings'
        unique_together = [
            ['group', 'key'],
        ]
        verbose_name = _('group setting')
        verbose_name_plural = _('group settings')

    def __str__(self):
        return f"{self.group.name} - {self.key}"

    @classmethod
    def get_setting(cls, group_id: int, key: str, default: Any = None) -> Any:
        """Get a setting value for a group."""
        try:
            setting = cls.objects.get(group_id=group_id, key=key)
            return setting.value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set_setting(cls, group_id: int, key: str, value: Any, description: Optional[str] = None) -> 'GroupSetting':
        """Set a setting value for a group."""
        setting, created = cls.objects.update_or_create(
            group_id=group_id,
            key=key,
            defaults={'value': value, 'description': description}
        )
        return setting


# ============================================================================
# GROUP ACTIVITY MODEL
# ============================================================================

class GroupActivity(models.Model):
    """Audit log for group activities."""

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='activities',
        verbose_name=_('group'),
        db_index=True
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='group_activities',
        verbose_name=_('user'),
        db_index=True
    )
    action = models.CharField(
        _('action'),
        max_length=255,
        db_index=True
    )
    details = models.JSONField(
        _('details'),
        default=dict
    )
    timestamp = models.DateTimeField(
        _('timestamp'),
        default=timezone.now,
        db_index=True
    )

    class Meta:
        db_table = 'group_activities'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['group', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]
        verbose_name = _('group activity')
        verbose_name_plural = _('group activities')

    def __str__(self):
        return f"{self.group.name} - {self.action} at {self.timestamp}"


# ============================================================================
# GROUP WINNER HISTORY MODEL
# ============================================================================

class GroupWinnerHistory(models.Model):
    """History of selected winners for each round."""

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='winner_history',
        verbose_name=_('group'),
        db_index=True
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='winner_history',
        verbose_name=_('winner user'),
        db_index=True
    )
    round = models.PositiveIntegerField(
        _('round number'),
        db_index=True
    )
    amount = models.DecimalField(
        _('amount received'),
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    selected_at = models.DateTimeField(
        _('selected at'),
        default=timezone.now,
        db_index=True
    )
    paid_out = models.BooleanField(
        _('paid out'),
        default=False,
        db_index=True
    )
    paid_out_at = models.DateTimeField(
        _('paid out at'),
        null=True,
        blank=True
    )
    payment_reference = models.CharField(
        _('payment reference'),
        max_length=255,
        blank=True,
        null=True
    )

    class Meta:
        db_table = 'group_winner_history'
        ordering = ['-selected_at']
        unique_together = [
            ['group', 'round', 'user'],
        ]
        indexes = [
            models.Index(fields=['group', 'round']),
            models.Index(fields=['user', 'selected_at']),
            models.Index(fields=['paid_out', 'selected_at']),
        ]
        verbose_name = _('group winner history')
        verbose_name_plural = _('group winner histories')

    def __str__(self):
        return f"{self.group.name} - Round {self.round}: {self.user.email} ({self.amount})"

    def mark_paid(self, reference: Optional[str] = None) -> None:
        """Mark the winner as paid."""
        self.paid_out = True
        self.paid_out_at = timezone.now()
        if reference:
            self.payment_reference = reference
        self.save(update_fields=['paid_out', 'paid_out_at', 'payment_reference'])