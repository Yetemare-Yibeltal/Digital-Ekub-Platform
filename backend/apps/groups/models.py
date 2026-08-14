"""
Models for the groups app.

This module defines all database models related to group management:
- Group: Main group entity
- GroupMember: Membership and roles
- GroupInvitation: Invitations to join groups
- GroupSetting: Configurable settings per group
- GroupActivity: Audit log for group actions
- GroupWinnerHistory: History of selected winners
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, F, Sum, Count, Avg, Max, Min
from django.core.exceptions import ValidationError

from apps.users.models import User
from apps.common.constants import (
    GroupStatus,
    GroupMemberRole,
    GroupType,
    GroupFrequency,
    GroupWinnerSelection,
    GroupInvitationStatus,
)
from apps.common.utils import generate_referral_code, format_currency

import logging
from typing import Optional, List, Tuple, Dict, Any
from decimal import Decimal

logger = logging.getLogger(__name__)


# ============================================================================
# GROUP MODEL
# ============================================================================

class Group(models.Model):
    """
    Main Group model representing a savings group.

    Fields:
    - name: Group name (required, max 255)
    - description: Group description (optional)
    - type: PUBLIC, PRIVATE, INVITE_ONLY
    - status: ACTIVE, COMPLETED, CANCELLED, PAUSED, PENDING, EXPIRED
    - frequency: DAILY, WEEKLY, BIWEEKLY, MONTHLY, QUARTERLY, YEARLY
    - contribution_amount: Amount per contribution
    - cycle_length: Number of cycles/rounds
    - max_members: Maximum members allowed
    - winner_selection: FIXED, RANDOM, AUCTION, BIDDING
    - current_round: Current round number (0-indexed)
    - start_date: When group started
    - end_date: When group ends/completes
    - created_by: User who created the group
    - created_at, updated_at: Timestamps
    - deleted_at: Soft delete timestamp

    Indexes:
    - status, created_at, start_date, end_date
    - name (for search)
    - created_by

    Methods:
    - add_member(), remove_member(), promote_to_admin(), demote_to_member()
    - is_full(), is_completed(), is_active()
    - get_members(), get_admins(), get_owner()
    - select_winner(), advance_round()
    - get_next_winner(), get_current_winner()
    - get_pending_contributions(), get_overdue_contributions()
    - get_contribution_summary()
    - complete_group(), cancel_group(), pause_group(), resume_group()
    """
    # Basic info
    name = models.CharField(_('group name'), max_length=255, db_index=True)
    description = models.TextField(_('description'), blank=True, null=True)
    type = models.CharField(
        _('group type'),
        max_length=20,
        choices=GroupType.CHOICES,
        default=GroupType.PUBLIC,
        db_index=True
    )
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=GroupStatus.CHOICES,
        default=GroupStatus.ACTIVE,
        db_index=True
    )

    # Financial settings
    frequency = models.CharField(
        _('contribution frequency'),
        max_length=20,
        choices=GroupFrequency.CHOICES,
        default=GroupFrequency.MONTHLY
    )
    contribution_amount = models.DecimalField(
        _('contribution amount'),
        max_digits=15,
        decimal_places=2,
        default=100.00,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    cycle_length = models.PositiveIntegerField(
        _('cycle length'),
        default=10,
        validators=[MinValueValidator(2), MaxValueValidator(100)]
    )
    max_members = models.PositiveIntegerField(
        _('maximum members'),
        default=20,
        validators=[MinValueValidator(2), MaxValueValidator(100)]
    )

    # Winner selection
    winner_selection = models.CharField(
        _('winner selection method'),
        max_length=20,
        choices=GroupWinnerSelection.CHOICES,
        default=GroupWinnerSelection.FIXED
    )

    # Round tracking
    current_round = models.PositiveIntegerField(_('current round'), default=0, db_index=True)

    # Dates
    start_date = models.DateTimeField(_('start date'), default=timezone.now, db_index=True)
    end_date = models.DateTimeField(_('end date'), null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(_('completed at'), null=True, blank=True)
    paused_at = models.DateTimeField(_('paused at'), null=True, blank=True)
    cancelled_at = models.DateTimeField(_('cancelled at'), null=True, blank=True)

    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='groups_created',
        verbose_name=_('created by'),
        db_index=True
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True, db_index=True)
    deleted_at = models.DateTimeField(_('deleted at'), null=True, blank=True, db_index=True)

    # Statistics (denormalized for performance)
    members_count = models.PositiveIntegerField(_('members count'), default=0)
    total_contributions = models.PositiveIntegerField(_('total contributions'), default=0)
    total_paid = models.DecimalField(_('total paid'), max_digits=15, decimal_places=2, default=0.00)
    total_pending = models.DecimalField(_('total pending'), max_digits=15, decimal_places=2, default=0.00)
    total_overdue = models.DecimalField(_('total overdue'), max_digits=15, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'groups'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['created_by', 'status']),
            models.Index(fields=['name']),
        ]
        verbose_name = _('group')
        verbose_name_plural = _('groups')

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        # Auto-set end_date if not set and cycle_length and frequency known
        if not self.end_date and self.start_date and self.cycle_length:
            if self.frequency == 'daily':
                delta = timezone.timedelta(days=self.cycle_length)
            elif self.frequency == 'weekly':
                delta = timezone.timedelta(weeks=self.cycle_length)
            elif self.frequency == 'biweekly':
                delta = timezone.timedelta(weeks=self.cycle_length * 2)
            elif self.frequency == 'monthly':
                delta = timezone.timedelta(days=self.cycle_length * 30)
            elif self.frequency == 'quarterly':
                delta = timezone.timedelta(days=self.cycle_length * 90)
            elif self.frequency == 'yearly':
                delta = timezone.timedelta(days=self.cycle_length * 365)
            else:
                delta = timezone.timedelta(days=self.cycle_length * 30)
            self.end_date = self.start_date + delta
        super().save(*args, **kwargs)

    # ============================================================================
    # PROPERTIES
    # ============================================================================

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
            return 0
        return (self.current_round / self.cycle_length) * 100

    @property
    def total_potential_amount(self) -> Decimal:
        """Total potential amount that will be collected."""
        return self.contribution_amount * self.cycle_length * self.members_count

    @property
    def current_pot_amount(self) -> Decimal:
        """Current pot amount for the current round."""
        return self.contribution_amount * self.members_count

    # ============================================================================
    # MEMBERSHIP METHODS
    # ============================================================================

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
        if self.is_full:
            raise ValidationError(_('Group is full.'))
        if not self.is_active:
            raise ValidationError(_('Group is not active.'))
        if self.is_deleted:
            raise ValidationError(_('Group has been deleted.'))
        if self.is_completed:
            raise ValidationError(_('Group is completed.'))
        if self.is_cancelled:
            raise ValidationError(_('Group is cancelled.'))

        if GroupMember.objects.filter(group=self, user=user, is_active=True).exists():
            raise ValidationError(_('User is already a member.'))

        if role not in dict(GroupMemberRole.CHOICES):
            role = 'member'

        member = GroupMember.objects.create(
            group=self,
            user=user,
            role=role,
            joined_at=timezone.now()
        )
        self.members_count = GroupMember.objects.filter(group=self, is_active=True).count()
        self.save(update_fields=['members_count'])
        logger.info(f'User {user.id} joined group {self.id} as {role}')
        return member

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

        # Check if user is the only owner
        if member.role == 'owner':
            owners = GroupMember.objects.filter(group=self, role='owner', is_active=True)
            if owners.count() == 1:
                raise ValidationError(_('Cannot remove the only owner. Transfer ownership first.'))

        member.is_active = False
        member.left_at = timezone.now()
        member.reason = reason
        member.save(update_fields=['is_active', 'left_at', 'reason'])

        self.members_count = GroupMember.objects.filter(group=self, is_active=True).count()
        self.save(update_fields=['members_count'])
        logger.info(f'User {user.id} removed from group {self.id}')
        return True

    def promote_to_admin(self, user: User) -> bool:
        """
        Promote a member to admin.

        Args:
            user: User to promote

        Returns:
            bool: True if promoted
        """
        try:
            member = GroupMember.objects.get(group=self, user=user, is_active=True)
        except GroupMember.DoesNotExist:
            raise ValidationError(_('User is not a member.'))
        if member.role == 'admin' or member.role == 'owner':
            return True
        member.role = 'admin'
        member.save(update_fields=['role'])
        logger.info(f'User {user.id} promoted to admin in group {self.id}')
        return True

    def demote_to_member(self, user: User) -> bool:
        """
        Demote an admin to member.

        Args:
            user: User to demote

        Returns:
            bool: True if demoted
        """
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
        logger.info(f'User {user.id} demoted to member in group {self.id}')
        return True

    def transfer_ownership(self, new_owner: User) -> bool:
        """
        Transfer ownership to another member.

        Args:
            new_owner: User to become new owner

        Returns:
            bool: True if transferred
        """
        try:
            new_member = GroupMember.objects.get(group=self, user=new_owner, is_active=True)
        except GroupMember.DoesNotExist:
            raise ValidationError(_('New owner must be a member.'))

        old_owner = GroupMember.objects.get(group=self, role='owner', is_active=True)
        old_owner.role = 'admin'
        old_owner.save(update_fields=['role'])

        new_member.role = 'owner'
        new_member.save(update_fields=['role'])
        logger.info(f'Ownership transferred to {new_owner.id} in group {self.id}')
        return True

    # ============================================================================
    # QUERY METHODS
    # ============================================================================

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

    # ============================================================================
    # WINNER SELECTION METHODS
    # ============================================================================

    def select_winner(self) -> Optional[User]:
        """
        Select the winner for the current round based on the group's selection method.

        Returns:
            Optional[User]: The winning user, or None if no eligible
        """
        from apps.common.utils import select_winner as select_winner_util
        winner_id = select_winner_util(self.id)
        if winner_id:
            return User.objects.get(id=winner_id)
        return None

    def advance_round(self) -> bool:
        """
        Advance to the next round.

        Returns:
            bool: True if advanced successfully
        """
        if self.is_completed or self.is_cancelled:
            return False
        if self.current_round >= self.cycle_length:
            self.complete_group()
            return True
        self.current_round += 1
        self.save(update_fields=['current_round'])
        logger.info(f'Group {self.id} advanced to round {self.current_round}')
        return True

    def complete_group(self) -> bool:
        """
        Mark the group as completed.

        Returns:
            bool: True if completed
        """
        if self.is_completed:
            return True
        self.status = GroupStatus.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at'])
        logger.info(f'Group {self.id} completed')
        return True

    def cancel_group(self) -> bool:
        """
        Cancel the group.

        Returns:
            bool: True if cancelled
        """
        if self.is_cancelled:
            return True
        self.status = GroupStatus.CANCELLED
        self.cancelled_at = timezone.now()
        self.save(update_fields=['status', 'cancelled_at'])
        logger.info(f'Group {self.id} cancelled')
        return True

    def pause_group(self) -> bool:
        """
        Pause the group.

        Returns:
            bool: True if paused
        """
        if self.is_paused:
            return True
        self.status = GroupStatus.PAUSED
        self.paused_at = timezone.now()
        self.save(update_fields=['status', 'paused_at'])
        logger.info(f'Group {self.id} paused')
        return True

    def resume_group(self) -> bool:
        """
        Resume a paused group.

        Returns:
            bool: True if resumed
        """
        if not self.is_paused:
            return True
        self.status = GroupStatus.ACTIVE
        self.paused_at = None
        self.save(update_fields=['status', 'paused_at'])
        logger.info(f'Group {self.id} resumed')
        return True

    # ============================================================================
    # CONTRIBUTION METHODS
    # ============================================================================

    def get_contribution_summary(self) -> Dict[str, Any]:
        """
        Get a summary of contributions for the group.

        Returns:
            dict: Summary statistics
        """
        from apps.contributions.models import Contribution
        contributions = Contribution.objects.filter(group=self)
        total = contributions.count()
        paid = contributions.filter(status='paid').count()
        pending = contributions.filter(status='pending').count()
        overdue = contributions.filter(status='overdue').count()
        total_amount = contributions.filter(status='paid').aggregate(total=Sum('amount'))['total'] or 0
        pending_amount = contributions.filter(status='pending').aggregate(total=Sum('amount'))['total'] or 0
        overdue_amount = contributions.filter(status='overdue').aggregate(total=Sum('amount'))['total'] or 0

        return {
            'total_contributions': total,
            'paid_contributions': paid,
            'pending_contributions': pending,
            'overdue_contributions': overdue,
            'total_paid_amount': float(total_amount),
            'pending_amount': float(pending_amount),
            'overdue_amount': float(overdue_amount),
        }

    def get_pending_contributions(self) -> models.QuerySet:
        """Get all pending contributions for the group."""
        from apps.contributions.models import Contribution
        return Contribution.objects.filter(group=self, status='pending')

    def get_overdue_contributions(self) -> models.QuerySet:
        """Get all overdue contributions for the group."""
        from apps.contributions.models import Contribution
        return Contribution.objects.filter(group=self, status='overdue')

    # ============================================================================
    # SOFT DELETE
    # ============================================================================

    def soft_delete(self, reason: Optional[str] = None) -> None:
        """Soft delete the group."""
        self.deleted_at = timezone.now()
        self.status = GroupStatus.CANCELLED
        self.save(update_fields=['deleted_at', 'status'])
        logger.info(f'Group {self.id} soft deleted')

    def restore(self) -> None:
        """Restore a soft-deleted group."""
        self.deleted_at = None
        self.status = GroupStatus.ACTIVE
        self.save(update_fields=['deleted_at', 'status'])
        logger.info(f'Group {self.id} restored')


# ============================================================================
# GROUP MEMBER MODEL
# ============================================================================

class GroupMember(models.Model):
    """
    Membership model connecting users to groups with roles and status.

    Fields:
    - group: The group
    - user: The user
    - role: OWNER, ADMIN, MEMBER, OBSERVER
    - joined_at: When they joined
    - left_at: When they left (if any)
    - is_active: Whether membership is active
    - reason: Reason for leaving/removal
    - created_at, updated_at: Timestamps

    Indexes:
    - group, user (unique active)
    - role, is_active

    Methods:
    - is_owner(), is_admin(), is_member()
    - can_manage_group(), can_manage_contributions()
    """
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name=_('group')
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='group_memberships',
        verbose_name=_('user')
    )
    role = models.CharField(
        _('role'),
        max_length=20,
        choices=GroupMemberRole.CHOICES,
        default=GroupMemberRole.MEMBER,
        db_index=True
    )
    joined_at = models.DateTimeField(_('joined at'), default=timezone.now, db_index=True)
    left_at = models.DateTimeField(_('left at'), null=True, blank=True)
    is_active = models.BooleanField(_('is active'), default=True, db_index=True)
    reason = models.TextField(_('reason'), blank=True, null=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'group_members'
        ordering = ['-joined_at']
        unique_together = [
            ['group', 'user', 'is_active'],
        ]
        indexes = [
            models.Index(fields=['group', 'role', 'is_active']),
            models.Index(fields=['user', 'is_active']),
        ]
        verbose_name = _('group member')
        verbose_name_plural = _('group members')

    def __str__(self):
        return f"{self.user.email} - {self.group.name} ({self.get_role_display()})"

    def save(self, *args, **kwargs):
        if self.left_at and not self.is_active:
            # If left_at is set and is_active is False, we can keep it
            pass
        super().save(*args, **kwargs)

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
        """Check if user can manage contributions (admin, owner)."""
        return self.is_admin


# ============================================================================
# GROUP INVITATION MODEL
# ============================================================================

class GroupInvitation(models.Model):
    """
    Invitation model for users to join groups.

    Fields:
    - group: Target group
    - inviter: User who sent invitation
    - invitee_email: Email of invited user (if not registered)
    - invitee_user: Optional user if already registered
    - token: Unique invitation token
    - status: PENDING, ACCEPTED, REJECTED, EXPIRED, CANCELLED
    - expires_at: Expiration timestamp
    - created_at, updated_at: Timestamps
    - accepted_at: When accepted

    Indexes:
    - token (unique)
    - group, status
    - invitee_email, status
    """
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='invitations',
        verbose_name=_('group')
    )
    inviter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_invitations',
        verbose_name=_('inviter')
    )
    invitee_email = models.EmailField(_('invitee email'), max_length=255, db_index=True)
    invitee_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_invitations',
        verbose_name=_('invitee user')
    )
    token = models.CharField(_('token'), max_length=64, unique=True, db_index=True)
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=GroupInvitationStatus.CHOICES,
        default=GroupInvitationStatus.PENDING,
        db_index=True
    )
    expires_at = models.DateTimeField(_('expires at'))
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)
    accepted_at = models.DateTimeField(_('accepted at'), null=True, blank=True)

    class Meta:
        db_table = 'group_invitations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['group', 'status']),
            models.Index(fields=['invitee_email', 'status']),
            models.Index(fields=['expires_at']),
        ]
        verbose_name = _('group invitation')
        verbose_name_plural = _('group invitations')

    def __str__(self):
        return f"Invitation to {self.invitee_email} for {self.group.name}"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = generate_referral_code(prefix='INV', length=16)
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(days=7)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    @property
    def is_pending(self) -> bool:
        return self.status == GroupInvitationStatus.PENDING

    def accept(self, user: User) -> bool:
        """
        Accept the invitation and add the user to the group.

        Args:
            user: User accepting the invitation

        Returns:
            bool: True if accepted
        """
        if self.status != GroupInvitationStatus.PENDING:
            raise ValidationError(_('Invitation is not pending.'))
        if self.is_expired:
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

    def reject(self) -> bool:
        """Reject the invitation."""
        if self.status != GroupInvitationStatus.PENDING:
            return False
        self.status = GroupInvitationStatus.REJECTED
        self.save(update_fields=['status'])
        return True

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
    """
    Key-value store for group-specific settings.

    Fields:
    - group: The group
    - key: Setting key
    - value: Setting value (JSON serialized)
    - description: Optional description
    - created_at, updated_at: Timestamps
    """
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='settings',
        verbose_name=_('group')
    )
    key = models.CharField(_('key'), max_length=255, db_index=True)
    value = models.JSONField(_('value'), default=dict)
    description = models.TextField(_('description'), blank=True, null=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

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
    def get_setting(cls, group_id, key, default=None):
        """Get a setting value for a group."""
        try:
            setting = cls.objects.get(group_id=group_id, key=key)
            return setting.value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set_setting(cls, group_id, key, value, description=None):
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
    """
    Audit log for group activities.
    """
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='activities',
        verbose_name=_('group')
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='group_activities',
        verbose_name=_('user')
    )
    action = models.CharField(_('action'), max_length=255, db_index=True)
    details = models.JSONField(_('details'), default=dict)
    timestamp = models.DateTimeField(_('timestamp'), default=timezone.now, db_index=True)

    class Meta:
        db_table = 'group_activities'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['group', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
        ]
        verbose_name = _('group activity')
        verbose_name_plural = _('group activities')

    def __str__(self):
        return f"{self.group.name} - {self.action} at {self.timestamp}"


# ============================================================================
# GROUP WINNER HISTORY MODEL
# ============================================================================

class GroupWinnerHistory(models.Model):
    """
    History of selected winners for each round.
    """
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name='winner_history',
        verbose_name=_('group')
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='winner_history',
        verbose_name=_('winner user')
    )
    round = models.PositiveIntegerField(_('round number'), db_index=True)
    amount = models.DecimalField(
        _('amount received'),
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    selected_at = models.DateTimeField(_('selected at'), default=timezone.now, db_index=True)
    paid_out = models.BooleanField(_('paid out'), default=False)
    paid_out_at = models.DateTimeField(_('paid out at'), null=True, blank=True)

    class Meta:
        db_table = 'group_winner_history'
        ordering = ['-selected_at']
        unique_together = [
            ['group', 'round', 'user'],
        ]
        indexes = [
            models.Index(fields=['group', 'round']),
            models.Index(fields=['user', 'selected_at']),
        ]
        verbose_name = _('group winner history')
        verbose_name_plural = _('group winner histories')

    def __str__(self):
        return f"{self.group.name} - Round {self.round}: {self.user.email} ({self.amount})"

    def mark_paid(self) -> None:
        """Mark the winner as paid."""
        self.paid_out = True
        self.paid_out_at = timezone.now()
        self.save(update_fields=['paid_out', 'paid_out_at'])