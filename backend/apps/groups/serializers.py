"""
Serializers for the groups app.

This module provides serializers for all group-related models:
- Group serializers (create, update, list, detail)
- GroupMember serializers (create, update, list)
- GroupInvitation serializers (create, list, accept/reject)
- GroupSetting serializers
- GroupActivity serializers
- GroupWinnerHistory serializers
- Combined/utility serializers
"""

from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from decimal import Decimal

from apps.users.models import User
from apps.users.serializers import UserBaseSerializer
from apps.common.constants import (
    GroupStatus,
    GroupMemberRole,
    GroupType,
    GroupFrequency,
    GroupWinnerSelection,
    GroupInvitationStatus,
)
from apps.common.utils import format_currency, calculate_platform_fee
from apps.common.exceptions import (
    ValidationError,
    ConflictError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
)

from .models import (
    Group,
    GroupMember,
    GroupInvitation,
    GroupSetting,
    GroupActivity,
    GroupWinnerHistory,
)

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


# ============================================================================
# GROUP SERIALIZERS
# ============================================================================

class GroupBaseSerializer(serializers.ModelSerializer):
    """Base serializer with common fields for Group model."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    frequency_display = serializers.CharField(source='get_frequency_display', read_only=True)
    winner_selection_display = serializers.CharField(source='get_winner_selection_display', read_only=True)
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            'id', 'name', 'description', 'type', 'type_display',
            'status', 'status_display', 'frequency', 'frequency_display',
            'contribution_amount', 'cycle_length', 'max_members',
            'winner_selection', 'winner_selection_display',
            'current_round', 'start_date', 'end_date',
            'completed_at', 'paused_at', 'cancelled_at',
            'created_by', 'created_by_email', 'created_by_name',
            'created_at', 'updated_at', 'deleted_at',
            'members_count', 'total_contributions',
            'total_paid', 'total_pending', 'total_overdue',
            'is_full', 'is_active', 'is_completed', 'is_cancelled',
            'is_paused', 'is_pending', 'is_expired', 'is_deleted',
            'remaining_cycles', 'progress_percentage',
            'current_pot_amount', 'total_potential_amount',
            'days_remaining', 'completion_status',
        ]
        read_only_fields = [
            'id', 'status_display', 'type_display', 'frequency_display',
            'winner_selection_display', 'created_by_email', 'created_by_name',
            'created_at', 'updated_at', 'deleted_at',
            'members_count', 'total_contributions', 'total_paid',
            'total_pending', 'total_overdue', 'is_full', 'is_active',
            'is_completed', 'is_cancelled', 'is_paused', 'is_pending',
            'is_expired', 'is_deleted', 'remaining_cycles',
            'progress_percentage', 'current_pot_amount',
            'total_potential_amount', 'days_remaining', 'completion_status',
        ]

    def get_created_by_name(self, obj) -> str:
        return obj.created_by.full_name if obj.created_by else ''


class GroupListSerializer(GroupBaseSerializer):
    """Lightweight serializer for listing groups."""
    class Meta(GroupBaseSerializer.Meta):
        fields = [
            'id', 'name', 'type', 'type_display', 'status', 'status_display',
            'frequency', 'frequency_display', 'contribution_amount',
            'cycle_length', 'max_members', 'current_round',
            'start_date', 'end_date', 'created_by', 'created_by_email',
            'created_by_name', 'created_at', 'members_count',
            'is_full', 'is_active', 'is_completed', 'is_cancelled',
            'is_paused', 'is_pending', 'progress_percentage',
            'current_pot_amount',
        ]


class GroupDetailSerializer(GroupBaseSerializer):
    """Detailed serializer with nested relationships."""
    members = serializers.SerializerMethodField()
    admins = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField()
    contribution_summary = serializers.SerializerMethodField()
    next_round_date = serializers.SerializerMethodField()

    class Meta(GroupBaseSerializer.Meta):
        fields = GroupBaseSerializer.Meta.fields + [
            'members', 'admins', 'owner',
            'contribution_summary', 'next_round_date',
        ]

    def get_members(self, obj):
        members = obj.get_members().select_related('user')[:50]
        from .serializers import GroupMemberListSerializer
        return GroupMemberListSerializer(members, many=True).data

    def get_admins(self, obj):
        admins = obj.get_admins().select_related('user')[:20]
        from .serializers import GroupMemberListSerializer
        return GroupMemberListSerializer(admins, many=True).data

    def get_owner(self, obj):
        owner = obj.get_owner()
        if owner:
            from .serializers import GroupMemberListSerializer
            return GroupMemberListSerializer(owner).data
        return None

    def get_contribution_summary(self, obj):
        return obj.get_contribution_summary()

    def get_next_round_date(self, obj):
        return obj.next_round_date


class GroupCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new group."""
    created_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        help_text=_('User creating the group. If not provided, uses the current user.')
    )
    contribution_amount = serializers.DecimalField(
        max_digits=15, decimal_places=2, min_value=0.01,
        help_text=_('Amount each member contributes per cycle')
    )
    cycle_length = serializers.IntegerField(
        min_value=2, max_value=100,
        help_text=_('Number of cycles/rounds in the group')
    )
    max_members = serializers.IntegerField(
        min_value=2, max_value=100,
        help_text=_('Maximum number of members allowed')
    )

    class Meta:
        model = Group
        fields = [
            'name', 'description', 'type', 'frequency',
            'contribution_amount', 'cycle_length', 'max_members',
            'winner_selection', 'start_date', 'created_by',
        ]
        extra_kwargs = {
            'name': {'required': True, 'max_length': 255},
            'type': {'required': False, 'default': GroupType.PUBLIC},
            'frequency': {'required': False, 'default': GroupFrequency.MONTHLY},
            'winner_selection': {'required': False, 'default': GroupWinnerSelection.FIXED},
            'start_date': {'required': False},
        }

    def validate_name(self, value):
        if Group.objects.filter(name__iexact=value, deleted_at__isnull=True).exists():
            raise serializers.ValidationError(_('A group with this name already exists.'))
        return value

    def validate(self, attrs):
        # Validate that contribution_amount is positive
        if attrs.get('contribution_amount', 0) <= 0:
            raise serializers.ValidationError(
                {'contribution_amount': _('Contribution amount must be greater than 0.')}
            )

        # Validate that max_members >= 2
        if attrs.get('max_members', 0) < 2:
            raise serializers.ValidationError(
                {'max_members': _('Group must allow at least 2 members.')}
            )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # Extract created_by from data or use current user from context
        created_by = validated_data.pop('created_by', None)
        if not created_by and self.context.get('request'):
            created_by = self.context['request'].user

        if not created_by:
            raise serializers.ValidationError(
                {'created_by': _('User creating the group is required.')}
            )

        # Set start_date if not provided
        if 'start_date' not in validated_data:
            validated_data['start_date'] = timezone.now()

        # Create the group
        group = Group.objects.create(
            created_by=created_by,
            status=GroupStatus.PENDING,
            **validated_data
        )

        # Add the creator as the owner
        group.add_member(created_by, role='owner')

        # Activate group if it has at least 2 members (creator + pending)
        if group.members_count >= 2:
            group.status = GroupStatus.ACTIVE
            group.save(update_fields=['status'])

        logger.info(f'Group {group.id} created by user {created_by.id}')
        return group


class GroupUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating a group."""
    contribution_amount = serializers.DecimalField(
        max_digits=15, decimal_places=2, min_value=0.01, required=False
    )
    cycle_length = serializers.IntegerField(
        min_value=2, max_value=100, required=False
    )
    max_members = serializers.IntegerField(
        min_value=2, max_value=100, required=False
    )

    class Meta:
        model = Group
        fields = [
            'name', 'description', 'type', 'frequency',
            'contribution_amount', 'cycle_length', 'max_members',
            'winner_selection',
        ]

    def validate_name(self, value):
        if Group.objects.filter(
            name__iexact=value,
            deleted_at__isnull=True
        ).exclude(id=self.instance.id).exists():
            raise serializers.ValidationError(_('A group with this name already exists.'))
        return value

    def validate(self, attrs):
        # Cannot modify active/completed/cancelled groups
        if self.instance and self.instance.is_completed:
            raise serializers.ValidationError(
                _('Cannot modify a completed group.')
            )
        if self.instance and self.instance.is_cancelled:
            raise serializers.ValidationError(
                _('Cannot modify a cancelled group.')
            )
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        # Check if any sensitive fields are being modified
        if 'cycle_length' in validated_data and validated_data['cycle_length'] != instance.cycle_length:
            if instance.current_round > 0:
                raise serializers.ValidationError(
                    {'cycle_length': _('Cannot change cycle length after group has started.')}
                )

        if 'contribution_amount' in validated_data and validated_data['contribution_amount'] != instance.contribution_amount:
            if instance.current_round > 0:
                raise serializers.ValidationError(
                    {'contribution_amount': _('Cannot change contribution amount after group has started.')}
                )

        return super().update(instance, validated_data)


# ============================================================================
# GROUP MEMBER SERIALIZERS
# ============================================================================

class GroupMemberBaseSerializer(serializers.ModelSerializer):
    """Base serializer for GroupMember model."""
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    user_profile_picture = serializers.SerializerMethodField()
    role_display = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = GroupMember
        fields = [
            'id', 'group', 'user', 'user_email', 'user_name',
            'user_profile_picture', 'role', 'role_display',
            'joined_at', 'left_at', 'is_active', 'reason',
            'created_at', 'updated_at',
            'is_owner', 'is_admin', 'is_member',
            'can_manage_group', 'can_manage_contributions',
        ]
        read_only_fields = [
            'id', 'user_email', 'user_name', 'user_profile_picture',
            'role_display', 'joined_at', 'left_at', 'is_active',
            'created_at', 'updated_at',
            'is_owner', 'is_admin', 'is_member',
            'can_manage_group', 'can_manage_contributions',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_profile_picture(self, obj) -> str:
        if obj.user and obj.user.profile_picture:
            return obj.user.profile_picture.url
        return ''


class GroupMemberListSerializer(GroupMemberBaseSerializer):
    """Lightweight serializer for listing members."""
    class Meta(GroupMemberBaseSerializer.Meta):
        fields = [
            'id', 'user', 'user_email', 'user_name',
            'user_profile_picture', 'role', 'role_display',
            'joined_at', 'is_active',
            'is_owner', 'is_admin', 'is_member',
        ]


class GroupMemberDetailSerializer(GroupMemberBaseSerializer):
    """Detailed serializer with contribution stats."""
    contribution_stats = serializers.SerializerMethodField()

    class Meta(GroupMemberBaseSerializer.Meta):
        fields = GroupMemberBaseSerializer.Meta.fields + ['contribution_stats']

    def get_contribution_stats(self, obj):
        from apps.groups.models import get_member_stats
        return get_member_stats(obj.user_id, obj.group_id)


class GroupMemberCreateSerializer(serializers.ModelSerializer):
    """Serializer for adding a member to a group."""
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    role = serializers.ChoiceField(choices=GroupMemberRole.CHOICES, default='member')

    class Meta:
        model = GroupMember
        fields = ['user', 'role']
        extra_kwargs = {
            'user': {'required': True},
            'role': {'required': False},
        }

    def validate(self, attrs):
        user = attrs.get('user')
        group = self.context.get('group')

        if not group:
            raise serializers.ValidationError(_('Group is required.'))

        if not user:
            raise serializers.ValidationError(_('User is required.'))

        # Check if user is already a member
        if GroupMember.objects.filter(group=group, user=user, is_active=True).exists():
            raise serializers.ValidationError(
                {'user': _('User is already a member of this group.')}
            )

        # Check group capacity
        if group.is_full:
            raise serializers.ValidationError(_('Group is full.'))

        # Check if group is active
        if not group.is_active and not group.is_pending:
            raise serializers.ValidationError(_('Group is not accepting members.'))

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        group = self.context.get('group')
        user = validated_data.get('user')
        role = validated_data.get('role', 'member')

        return group.add_member(user, role)


class GroupMemberUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating a member's role."""
    role = serializers.ChoiceField(choices=GroupMemberRole.CHOICES, required=True)

    class Meta:
        model = GroupMember
        fields = ['role']
        extra_kwargs = {
            'role': {'required': True},
        }

    def validate(self, attrs):
        instance = self.instance
        new_role = attrs.get('role')

        # Cannot change role of inactive member
        if not instance.is_active:
            raise serializers.ValidationError(_('Cannot modify an inactive member.'))

        # Cannot demote the only owner
        if instance.role == 'owner' and new_role != 'owner':
            owners = GroupMember.objects.filter(
                group=instance.group,
                role='owner',
                is_active=True
            )
            if owners.count() == 1:
                raise serializers.ValidationError(
                    _('Cannot demote the only owner. Transfer ownership first.')
                )

        return attrs


# ============================================================================
# GROUP INVITATION SERIALIZERS
# ============================================================================

class GroupInvitationBaseSerializer(serializers.ModelSerializer):
    """Base serializer for GroupInvitation model."""
    inviter_email = serializers.EmailField(source='inviter.email', read_only=True)
    inviter_name = serializers.SerializerMethodField()
    invitee_user_email = serializers.EmailField(source='invitee_user.email', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = GroupInvitation
        fields = [
            'id', 'group', 'inviter', 'inviter_email', 'inviter_name',
            'invitee_email', 'invitee_user', 'invitee_user_email',
            'token', 'status', 'status_display', 'expires_at',
            'created_at', 'updated_at', 'accepted_at', 'message',
            'is_expired',
        ]
        read_only_fields = [
            'id', 'inviter_email', 'inviter_name', 'invitee_user_email',
            'status_display', 'token', 'status', 'expires_at',
            'created_at', 'updated_at', 'accepted_at', 'is_expired',
        ]

    def get_inviter_name(self, obj) -> str:
        return obj.inviter.full_name if obj.inviter else ''


class GroupInvitationListSerializer(GroupInvitationBaseSerializer):
    """Lightweight serializer for listing invitations."""
    class Meta(GroupInvitationBaseSerializer.Meta):
        fields = [
            'id', 'group', 'invitee_email', 'status', 'status_display',
            'expires_at', 'created_at', 'is_expired',
        ]


class GroupInvitationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a group invitation."""
    invitee_email = serializers.EmailField(required=True)
    message = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = GroupInvitation
        fields = ['invitee_email', 'message']
        extra_kwargs = {
            'invitee_email': {'required': True},
            'message': {'required': False},
        }

    def validate(self, attrs):
        group = self.context.get('group')
        inviter = self.context.get('inviter')
        invitee_email = attrs.get('invitee_email')

        if not group:
            raise serializers.ValidationError(_('Group is required.'))

        if not inviter:
            raise serializers.ValidationError(_('Inviter is required.'))

        # Check if inviter is a member/admin
        if not group.is_member(inviter) and not inviter.is_superuser:
            raise serializers.ValidationError(
                _('You must be a member of the group to send invitations.')
            )

        # Check if email is already invited
        existing = GroupInvitation.objects.filter(
            group=group,
            invitee_email=invitee_email,
            status=GroupInvitationStatus.PENDING
        ).exists()
        if existing:
            raise serializers.ValidationError(
                {'invitee_email': _('This email has already been invited.')}
            )

        # Check if user is already a member
        try:
            user = User.objects.get(email=invitee_email)
            if group.is_member(user):
                raise serializers.ValidationError(
                    {'invitee_email': _('This user is already a member.')}
                )
            attrs['invitee_user'] = user
        except User.DoesNotExist:
            pass

        # Check if group is full
        if group.is_full:
            raise serializers.ValidationError(_('Group is full.'))

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        group = self.context.get('group')
        inviter = self.context.get('inviter')

        invitation = GroupInvitation(
            group=group,
            inviter=inviter,
            invitee_email=validated_data['invitee_email'],
            invitee_user=validated_data.get('invitee_user'),
            message=validated_data.get('message', ''),
        )
        invitation.save()

        # Log activity
        group.log_activity(
            action='invitation_sent',
            user=inviter,
            details={'invitee_email': validated_data['invitee_email']}
        )

        logger.info(f'Invitation sent by {inviter.id} to {validated_data["invitee_email"]}')
        return invitation


class GroupInvitationAcceptSerializer(serializers.Serializer):
    """Serializer for accepting an invitation."""
    token = serializers.CharField(required=True)

    def validate_token(self, value):
        try:
            invitation = GroupInvitation.objects.get(token=value)
        except GroupInvitation.DoesNotExist:
            raise serializers.ValidationError(_('Invalid invitation token.'))

        if invitation.is_expired:
            raise serializers.ValidationError(_('Invitation has expired.'))

        if invitation.status != GroupInvitationStatus.PENDING:
            raise serializers.ValidationError(_('Invitation is not pending.'))

        self.context['invitation'] = invitation
        return value

    @transaction.atomic
    def save(self, **kwargs):
        invitation = self.context['invitation']
        user = self.context.get('user')

        if not user:
            raise serializers.ValidationError(_('User is required.'))

        # Check if user matches invitee_email
        if user.email != invitation.invitee_email:
            if not user.is_superuser:
                raise serializers.ValidationError(
                    _('This invitation was sent to a different email address.')
                )

        # Accept the invitation
        invitation.accept(user)
        logger.info(f'Invitation {invitation.id} accepted by user {user.id}')
        return {'status': 'accepted', 'group': invitation.group.id}


class GroupInvitationRejectSerializer(serializers.Serializer):
    """Serializer for rejecting an invitation."""
    token = serializers.CharField(required=True)

    def validate_token(self, value):
        try:
            invitation = GroupInvitation.objects.get(token=value)
        except GroupInvitation.DoesNotExist:
            raise serializers.ValidationError(_('Invalid invitation token.'))

        if invitation.status != GroupInvitationStatus.PENDING:
            raise serializers.ValidationError(_('Invitation is not pending.'))

        self.context['invitation'] = invitation
        return value

    @transaction.atomic
    def save(self, **kwargs):
        invitation = self.context['invitation']
        invitation.reject()
        logger.info(f'Invitation {invitation.id} rejected')
        return {'status': 'rejected'}


# ============================================================================
# GROUP SETTING SERIALIZER
# ============================================================================

class GroupSettingSerializer(serializers.ModelSerializer):
    """Serializer for GroupSetting model."""
    class Meta:
        model = GroupSetting
        fields = ['id', 'group', 'key', 'value', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'key': {'required': True},
            'value': {'required': True},
        }


class GroupSettingCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating a group setting."""
    class Meta:
        model = GroupSetting
        fields = ['key', 'value', 'description']
        extra_kwargs = {
            'key': {'required': True},
            'value': {'required': True},
            'description': {'required': False},
        }

    def validate_key(self, value):
        if not value or len(value) < 2:
            raise serializers.ValidationError(_('Setting key must be at least 2 characters.'))
        return value

    def validate_value(self, value):
        if not value:
            raise serializers.ValidationError(_('Setting value cannot be empty.'))
        return value


# ============================================================================
# GROUP ACTIVITY SERIALIZER
# ============================================================================

class GroupActivitySerializer(serializers.ModelSerializer):
    """Serializer for GroupActivity model."""
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = GroupActivity
        fields = [
            'id', 'group', 'user', 'user_email', 'user_name',
            'action', 'details', 'timestamp',
        ]
        read_only_fields = ['id', 'user_email', 'user_name', 'timestamp']

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else 'System'


# ============================================================================
# GROUP WINNER HISTORY SERIALIZER
# ============================================================================

class GroupWinnerHistorySerializer(serializers.ModelSerializer):
    """Serializer for GroupWinnerHistory model."""
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    user_profile_picture = serializers.SerializerMethodField()
    amount_formatted = serializers.SerializerMethodField()

    class Meta:
        model = GroupWinnerHistory
        fields = [
            'id', 'group', 'user', 'user_email', 'user_name',
            'user_profile_picture', 'round', 'amount', 'amount_formatted',
            'selected_at', 'paid_out', 'paid_out_at', 'payment_reference',
        ]
        read_only_fields = [
            'id', 'user_email', 'user_name', 'user_profile_picture',
            'amount_formatted', 'selected_at',
        ]

    def get_user_name(self, obj) -> str:
        return obj.user.full_name if obj.user else ''

    def get_user_profile_picture(self, obj) -> str:
        if obj.user and obj.user.profile_picture:
            return obj.user.profile_picture.url
        return ''

    def get_amount_formatted(self, obj) -> str:
        return format_currency(obj.amount)


class GroupWinnerHistoryCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a winner history entry."""
    class Meta:
        model = GroupWinnerHistory
        fields = ['group', 'user', 'round', 'amount']

    def validate(self, attrs):
        group = attrs.get('group')
        user = attrs.get('user')
        round_num = attrs.get('round')

        if not group or not user:
            raise serializers.ValidationError(_('Group and user are required.'))

        # Check if entry already exists
        if GroupWinnerHistory.objects.filter(
            group=group,
            round=round_num,
            user=user
        ).exists():
            raise serializers.ValidationError(
                _('Winner history entry already exists for this group, round, and user.')
            )

        return attrs


# ============================================================================
# GROUP STATS SERIALIZER
# ============================================================================

class GroupStatsSerializer(serializers.Serializer):
    """Serializer for group statistics."""
    group_id = serializers.IntegerField()
    group_name = serializers.CharField()
    status = serializers.CharField()
    members_count = serializers.IntegerField()
    total_contributions = serializers.IntegerField()
    paid_contributions = serializers.IntegerField()
    pending_contributions = serializers.IntegerField()
    overdue_contributions = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_paid_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    pending_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    overdue_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_payouts = serializers.IntegerField()
    completed_payouts = serializers.IntegerField()
    pending_payouts = serializers.IntegerField()
    total_payout_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    completion_percentage = serializers.FloatField()


class MemberStatsSerializer(serializers.Serializer):
    """Serializer for member statistics."""
    user_id = serializers.IntegerField()
    group_id = serializers.IntegerField()
    role = serializers.CharField()
    joined_at = serializers.DateTimeField()
    total_contributions = serializers.IntegerField()
    paid_contributions = serializers.IntegerField()
    pending_contributions = serializers.IntegerField()
    overdue_contributions = serializers.IntegerField()
    total_amount_paid = serializers.DecimalField(max_digits=15, decimal_places=2)
    contribution_status = serializers.CharField()


# ============================================================================
# GROUP JOIN/LEAVE SERIALIZERS
# ============================================================================

class GroupJoinSerializer(serializers.Serializer):
    """Serializer for joining a group."""
    group_id = serializers.IntegerField(required=True)

    def validate_group_id(self, value):
        try:
            group = Group.objects.get(id=value)
        except Group.DoesNotExist:
            raise serializers.ValidationError(_('Group not found.'))

        user = self.context.get('user')
        if not user:
            raise serializers.ValidationError(_('User is required.'))

        # Check if user can join
        if not group.is_active:
            raise serializers.ValidationError(_('Group is not active.'))

        if group.is_full:
            raise serializers.ValidationError(_('Group is full.'))

        if group.is_member(user):
            raise serializers.ValidationError(_('You are already a member.'))

        self.context['group'] = group
        return value

    @transaction.atomic
    def save(self, **kwargs):
        group = self.context['group']
        user = self.context['user']

        member = group.add_member(user)
        return {'status': 'joined', 'member_id': member.id}


class GroupLeaveSerializer(serializers.Serializer):
    """Serializer for leaving a group."""
    group_id = serializers.IntegerField(required=True)

    def validate_group_id(self, value):
        try:
            group = Group.objects.get(id=value)
        except Group.DoesNotExist:
            raise serializers.ValidationError(_('Group not found.'))

        user = self.context.get('user')
        if not user:
            raise serializers.ValidationError(_('User is required.'))

        if not group.is_member(user):
            raise serializers.ValidationError(_('You are not a member of this group.'))

        # Check if user is the only owner
        if group.is_owner(user):
            owners = GroupMember.objects.filter(group=group, role='owner', is_active=True)
            if owners.count() == 1:
                raise serializers.ValidationError(
                    _('You are the only owner. Transfer ownership before leaving.')
                )

        self.context['group'] = group
        return value

    @transaction.atomic
    def save(self, **kwargs):
        group = self.context['group']
        user = self.context['user']
        reason = self.context.get('reason')

        group.remove_member(user, reason)
        return {'status': 'left'}


# ============================================================================
# GROUP SELECT WINNER SERIALIZER
# ============================================================================

class GroupSelectWinnerSerializer(serializers.Serializer):
    """Serializer for selecting a winner."""
    group_id = serializers.IntegerField(required=True)
    method = serializers.ChoiceField(
        choices=[('fixed', 'Fixed'), ('random', 'Random')],
        required=False,
        default='default'
    )

    def validate_group_id(self, value):
        try:
            group = Group.objects.get(id=value)
        except Group.DoesNotExist:
            raise serializers.ValidationError(_('Group not found.'))

        if not group.is_active:
            raise serializers.ValidationError(_('Group is not active.'))

        if group.is_completed:
            raise serializers.ValidationError(_('Group is already completed.'))

        if group.members_count < 2:
            raise serializers.ValidationError(_('Group needs at least 2 members.'))

        self.context['group'] = group
        return value

    @transaction.atomic
    def save(self, **kwargs):
        group = self.context['group']
        method = self.validated_data.get('method')
        user = self.context.get('user')

        # Select winner
        winner = group.select_winner(method)
        if not winner:
            raise serializers.ValidationError(_('No eligible winner found.'))

        # Record winner history
        history = GroupWinnerHistory.objects.create(
            group=group,
            user=winner,
            round=group.current_round,
            amount=group.current_pot_amount,
        )

        # Log activity
        group.log_activity(
            action='winner_selected',
            user=user,
            details={
                'winner_id': winner.id,
                'round': group.current_round,
                'amount': str(group.current_pot_amount),
            }
        )

        # Advance round
        group.advance_round()

        return {
            'winner': winner.id,
            'winner_name': winner.full_name,
            'winner_email': winner.email,
            'amount': group.current_pot_amount,
            'round': history.round,
        }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'GroupBaseSerializer',
    'GroupListSerializer',
    'GroupDetailSerializer',
    'GroupCreateSerializer',
    'GroupUpdateSerializer',
    'GroupMemberBaseSerializer',
    'GroupMemberListSerializer',
    'GroupMemberDetailSerializer',
    'GroupMemberCreateSerializer',
    'GroupMemberUpdateSerializer',
    'GroupInvitationBaseSerializer',
    'GroupInvitationListSerializer',
    'GroupInvitationCreateSerializer',
    'GroupInvitationAcceptSerializer',
    'GroupInvitationRejectSerializer',
    'GroupSettingSerializer',
    'GroupSettingCreateUpdateSerializer',
    'GroupActivitySerializer',
    'GroupWinnerHistorySerializer',
    'GroupWinnerHistoryCreateSerializer',
    'GroupStatsSerializer',
    'MemberStatsSerializer',
    'GroupJoinSerializer',
    'GroupLeaveSerializer',
    'GroupSelectWinnerSerializer',
]