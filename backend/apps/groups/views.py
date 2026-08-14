"""
Views for the groups app.

This module provides all API views for group management including:
- Group CRUD operations (create, list, retrieve, update, delete)
- Group member management (add, remove, promote, demote, transfer ownership)
- Group invitations (send, accept, reject, cancel)
- Group lifecycle (activate, complete, cancel, pause, resume)
- Winner selection (fixed rotation, random)
- Statistics and reporting
- Admin actions (bulk operations, moderation)

All views use appropriate permissions and include comprehensive logging.
"""

from django.db import transaction
from django.db.models import Q, Count, Sum, Avg, Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets, status, permissions, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound

from apps.users.models import User
from apps.common.pagination import CustomPagination
from apps.common.permissions import (
    IsAuthenticated, IsActiveUser, IsSuperAdminUser,
    IsAdminUser, IsOwnerOrReadOnly, IsOwnerOrAdmin
)
from apps.common.exceptions import (
    BadRequestError, NotFoundError, PermissionDeniedError,
    ConflictError, ValidationError as CustomValidationError
)
from apps.common.utils import log_audit_event, get_client_ip

from .models import (
    Group, GroupMember, GroupInvitation, GroupSetting,
    GroupActivity, GroupWinnerHistory
)
from .serializers import (
    GroupListSerializer, GroupDetailSerializer, GroupCreateSerializer,
    GroupUpdateSerializer, GroupMemberListSerializer, GroupMemberDetailSerializer,
    GroupMemberCreateSerializer, GroupMemberUpdateSerializer,
    GroupInvitationListSerializer, GroupInvitationCreateSerializer,
    GroupInvitationAcceptSerializer, GroupInvitationRejectSerializer,
    GroupSettingSerializer, GroupSettingCreateUpdateSerializer,
    GroupActivitySerializer, GroupWinnerHistorySerializer,
    GroupStatsSerializer, MemberStatsSerializer,
    GroupJoinSerializer, GroupLeaveSerializer, GroupSelectWinnerSerializer,
)
from .permissions import (
    IsGroupMember, IsGroupAdmin, IsGroupOwner, IsGroupActive,
    IsGroupNotFull, IsGroupNotCompleted, CanJoinGroup, CanLeaveGroup,
    CanManageGroup, CanViewGroup,
)
from .tasks import (
    process_expired_groups, auto_select_winner, send_group_reminders,
    process_group_completion, cleanup_inactive_groups, update_group_stats
)

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# GROUP VIEW SET
# ============================================================================

class GroupViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Group model with full CRUD and additional actions.

    Provides endpoints for:
    - Listing groups with filtering
    - Creating new groups
    - Retrieving group details
    - Updating group settings
    - Soft deleting groups
    - Joining and leaving groups
    - Selecting winners
    - Managing group lifecycle (complete, cancel, pause, resume)
    - Retrieving group statistics
    """

    queryset = Group.objects.filter(deleted_at__isnull=True)
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.action == 'list':
            return GroupListSerializer
        elif self.action == 'retrieve':
            return GroupDetailSerializer
        elif self.action == 'create':
            return GroupCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return GroupUpdateSerializer
        elif self.action == 'stats':
            return GroupStatsSerializer
        else:
            return GroupDetailSerializer

    def get_permissions(self):
        if self.action == 'create':
            permission_classes = [IsAuthenticated, IsActiveUser]
        elif self.action in ['update', 'partial_update', 'destroy']:
            permission_classes = [IsAuthenticated, IsGroupAdmin]
        elif self.action in ['retrieve', 'list']:
            permission_classes = [permissions.AllowAny]
        elif self.action in ['join', 'leave', 'select_winner']:
            permission_classes = [IsAuthenticated, IsActiveUser]
        elif self.action in ['complete', 'cancel', 'pause', 'resume']:
            permission_classes = [IsAuthenticated, IsGroupAdmin]
        elif self.action in ['stats', 'member_stats', 'contribution_summary']:
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        # Filter based on user role
        if not user or not user.is_authenticated:
            # Anonymous users see only public groups
            queryset = queryset.filter(type='public', status='active')
        elif not user.is_superuser:
            # Regular users see public groups and groups they are members of
            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)
            queryset = queryset.filter(
                Q(type='public') |
                Q(id__in=member_group_ids)
            )

        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Filter by type
        type_filter = self.request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(type=type_filter)

        # Search by name
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(name__icontains=search)

        # Filter by frequency
        frequency = self.request.query_params.get('frequency')
        if frequency:
            queryset = queryset.filter(frequency=frequency)

        # Filter by contribution amount range
        min_amount = self.request.query_params.get('min_amount')
        max_amount = self.request.query_params.get('max_amount')
        if min_amount:
            queryset = queryset.filter(contribution_amount__gte=min_amount)
        if max_amount:
            queryset = queryset.filter(contribution_amount__lte=max_amount)

        # Filter by date range
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(created_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__lte=date_to)

        # Ordering
        ordering = self.request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)

        return queryset.select_related('created_by').prefetch_related(
            Prefetch('memberships', queryset=GroupMember.objects.filter(is_active=True))
        )

    # ========================================================================
    # OVERRIDDEN METHODS
    # ========================================================================

    def perform_create(self, serializer):
        """Create a group with the current user as creator and owner."""
        with transaction.atomic():
            group = serializer.save(created_by=self.request.user)
            logger.info(f'Group {group.id} created by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='group_create',
                resource='group',
                resource_id=group.id,
                ip=get_client_ip(self.request)
            )

    def perform_update(self, serializer):
        """Update a group and log changes."""
        with transaction.atomic():
            group = serializer.save()
            logger.info(f'Group {group.id} updated by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='group_update',
                resource='group',
                resource_id=group.id,
                ip=get_client_ip(self.request),
                details={'updated_fields': list(serializer.validated_data.keys())}
            )

    def perform_destroy(self, instance):
        """Soft delete a group."""
        with transaction.atomic():
            instance.soft_delete(reason='Deleted by admin')
            logger.info(f'Group {instance.id} soft deleted by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='group_delete',
                resource='group',
                resource_id=instance.id,
                ip=get_client_ip(self.request)
            )

    # ========================================================================
    # CUSTOM ACTIONS
    # ========================================================================

    @action(detail=True, methods=['post'])
    def join(self, request, id=None):
        """Join the group."""
        group = self.get_object()
        user = request.user

        # Check if user can join
        if not group.is_active:
            raise BadRequestError(_('Group is not active.'))
        if group.is_full:
            raise BadRequestError(_('Group is full.'))
        if group.is_completed:
            raise BadRequestError(_('Group is completed.'))
        if group.is_cancelled:
            raise BadRequestError(_('Group is cancelled.'))
        if group.is_member(user):
            raise ConflictError(_('You are already a member.'))

        # Perform join
        with transaction.atomic():
            member = group.add_member(user)
            logger.info(f'User {user.id} joined group {group.id}')
            log_audit_event(
                user_id=user.id,
                action='group_join',
                resource='group',
                resource_id=group.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'joined',
                'member_id': member.id,
                'group': GroupListSerializer(group).data
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def leave(self, request, id=None):
        """Leave the group."""
        group = self.get_object()
        user = request.user

        if not group.is_member(user):
            raise BadRequestError(_('You are not a member of this group.'))

        # Check if user is the only owner
        if group.is_owner(user):
            owners = GroupMember.objects.filter(group=group, role='owner', is_active=True)
            if owners.count() == 1:
                raise BadRequestError(
                    _('You are the only owner. Transfer ownership before leaving.')
                )

        reason = request.data.get('reason')
        with transaction.atomic():
            group.remove_member(user, reason)
            logger.info(f'User {user.id} left group {group.id}')
            log_audit_event(
                user_id=user.id,
                action='group_leave',
                resource='group',
                resource_id=group.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'left',
                'message': 'You have left the group.'
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def select_winner(self, request, id=None):
        """Select a winner for the current round."""
        group = self.get_object()

        if not group.is_active:
            raise BadRequestError(_('Group is not active.'))
        if group.is_completed:
            raise BadRequestError(_('Group is already completed.'))
        if group.members_count < 2:
            raise BadRequestError(_('Group needs at least 2 members.'))

        method = request.data.get('method')

        with transaction.atomic():
            winner = group.select_winner(method)
            if not winner:
                raise BadRequestError(_('No eligible winner found.'))

            # Record winner
            history = GroupWinnerHistory.objects.create(
                group=group,
                user=winner,
                round=group.current_round,
                amount=group.current_pot_amount,
            )

            group.log_activity(
                action='winner_selected',
                user=request.user,
                details={
                    'winner_id': winner.id,
                    'round': group.current_round,
                    'amount': str(group.current_pot_amount),
                }
            )

            # Advance round
            group.advance_round()

            logger.info(f'Winner selected for group {group.id}: user {winner.id}')
            log_audit_event(
                user_id=request.user.id,
                action='group_select_winner',
                resource='group',
                resource_id=group.id,
                ip=get_client_ip(request),
                details={'winner_id': winner.id, 'round': history.round}
            )

            return Response({
                'winner': {
                    'id': winner.id,
                    'name': winner.full_name,
                    'email': winner.email,
                },
                'amount': float(group.current_pot_amount),
                'round': history.round,
                'message': f'Winner selected for round {history.round + 1}.'
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def complete(self, request, id=None):
        """Complete the group."""
        group = self.get_object()

        if group.is_completed:
            return Response({'message': _('Group is already completed.')}, status=status.HTTP_200_OK)

        # Check if any pending/overdue contributions exist
        pending = group.get_pending_contributions()
        if pending.exists():
            raise BadRequestError(_('Cannot complete group with pending contributions.'))

        overdue = group.get_overdue_contributions()
        if overdue.exists():
            raise BadRequestError(_('Cannot complete group with overdue contributions.'))

        with transaction.atomic():
            group.complete_group()
            logger.info(f'Group {group.id} completed by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='group_complete',
                resource='group',
                resource_id=group.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'completed',
                'message': 'Group completed successfully.'
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def cancel(self, request, id=None):
        """Cancel the group."""
        group = self.get_object()

        if group.is_cancelled:
            return Response({'message': _('Group is already cancelled.')}, status=status.HTTP_200_OK)

        reason = request.data.get('reason', 'Cancelled by admin')

        with transaction.atomic():
            group.cancel_group(reason)
            logger.info(f'Group {group.id} cancelled by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='group_cancel',
                resource='group',
                resource_id=group.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'cancelled',
                'message': f'Group cancelled. Reason: {reason}'
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def pause(self, request, id=None):
        """Pause the group."""
        group = self.get_object()

        if group.is_paused:
            return Response({'message': _('Group is already paused.')}, status=status.HTTP_200_OK)

        reason = request.data.get('reason', 'Paused by admin')

        with transaction.atomic():
            group.pause_group(reason)
            logger.info(f'Group {group.id} paused by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='group_pause',
                resource='group',
                resource_id=group.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'paused',
                'message': f'Group paused. Reason: {reason}'
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def resume(self, request, id=None):
        """Resume the group."""
        group = self.get_object()

        if not group.is_paused:
            return Response({'message': _('Group is not paused.')}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            group.resume_group()
            logger.info(f'Group {group.id} resumed by user {request.user.id}')
            log_audit_event(
                user_id=request.user.id,
                action='group_resume',
                resource='group',
                resource_id=group.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'active',
                'message': 'Group resumed successfully.'
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def stats(self, request, id=None):
        """Get statistics for the group."""
        group = self.get_object()
        stats = group.get_contribution_summary()
        return Response({
            'group': GroupListSerializer(group).data,
            'stats': stats
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def member_stats(self, request, id=None):
        """Get member statistics for the group."""
        group = self.get_object()
        members = group.get_members().select_related('user')

        data = []
        for member in members:
            stats = group.get_member_contributions(member.user)
            data.append({
                'user_id': member.user.id,
                'user_name': member.user.full_name,
                'user_email': member.user.email,
                'role': member.role,
                'joined_at': member.joined_at,
                **stats
            })

        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def contribution_summary(self, request, id=None):
        """Get contribution summary for the group."""
        group = self.get_object()
        return Response(group.get_contribution_summary(), status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def activities(self, request, id=None):
        """Get recent activities for the group."""
        group = self.get_object()
        activities = group.activities.all().order_by('-timestamp')[:50]
        from .serializers import GroupActivitySerializer
        serializer = GroupActivitySerializer(activities, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def winners(self, request, id=None):
        """Get winner history for the group."""
        group = self.get_object()
        winners = group.winner_history.all().order_by('-selected_at')
        serializer = GroupWinnerHistorySerializer(winners, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def public(self, request):
        """List all public groups."""
        queryset = Group.objects.filter(
            type='public',
            status='active',
            deleted_at__isnull=True
        ).order_by('-created_at')[:20]
        serializer = GroupListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def my_groups(self, request):
        """List groups the current user is a member of."""
        user = request.user
        if not user.is_authenticated:
            raise PermissionDenied(_('Authentication required.'))

        member_group_ids = GroupMember.objects.filter(
            user=user,
            is_active=True
        ).values_list('group_id', flat=True)

        queryset = Group.objects.filter(
            id__in=member_group_ids,
            deleted_at__isnull=True
        ).order_by('-created_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = GroupListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = GroupListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def stats_overview(self, request):
        """Get overview statistics for all groups."""
        user = request.user

        if not user.is_authenticated:
            raise PermissionDenied(_('Authentication required.'))

        queryset = Group.objects.filter(deleted_at__isnull=True)

        if not user.is_superuser:
            member_group_ids = GroupMember.objects.filter(
                user=user,
                is_active=True
            ).values_list('group_id', flat=True)
            queryset = queryset.filter(id__in=member_group_ids)

        total_groups = queryset.count()
        active_groups = queryset.filter(status='active').count()
        completed_groups = queryset.filter(status='completed').count()
        pending_groups = queryset.filter(status='pending').count()
        cancelled_groups = queryset.filter(status='cancelled').count()
        paused_groups = queryset.filter(status='paused').count()
        expired_groups = queryset.filter(status='expired').count()

        total_members = GroupMember.objects.filter(
            group__in=queryset,
            is_active=True
        ).count()

        total_contributions = queryset.aggregate(
            total=Sum('total_contributions')
        )['total'] or 0

        total_paid = queryset.aggregate(
            total=Sum('total_paid')
        )['total'] or 0

        return Response({
            'total_groups': total_groups,
            'active_groups': active_groups,
            'completed_groups': completed_groups,
            'pending_groups': pending_groups,
            'cancelled_groups': cancelled_groups,
            'paused_groups': paused_groups,
            'expired_groups': expired_groups,
            'total_members': total_members,
            'total_contributions': total_contributions,
            'total_paid': float(total_paid),
        }, status=status.HTTP_200_OK)


# ============================================================================
# GROUP MEMBER VIEW SET
# ============================================================================

class GroupMemberViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing group members.

    Provides endpoints for:
    - Listing members of a group
    - Retrieving member details
    - Adding a member
    - Updating member role
    - Removing a member
    """

    serializer_class = GroupMemberDetailSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        group_id = self.kwargs.get('group_id')
        if group_id:
            return GroupMember.objects.filter(group_id=group_id, is_active=True).select_related('user')
        return GroupMember.objects.filter(is_active=True).select_related('user')

    def get_serializer_class(self):
        if self.action == 'list':
            return GroupMemberListSerializer
        elif self.action == 'create':
            return GroupMemberCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return GroupMemberUpdateSerializer
        return GroupMemberDetailSerializer

    def get_permissions(self):
        if self.action in ['create']:
            permission_classes = [IsAuthenticated, IsActiveUser, IsGroupAdmin]
        elif self.action in ['update', 'partial_update', 'destroy']:
            permission_classes = [IsAuthenticated, IsActiveUser, IsGroupAdmin]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_group(self):
        """Get the group from the URL."""
        group_id = self.kwargs.get('group_id')
        if not group_id:
            raise NotFoundError(_('Group ID is required.'))
        try:
            return Group.objects.get(id=group_id, deleted_at__isnull=True)
        except Group.DoesNotExist:
            raise NotFoundError(_('Group not found.'))

    def perform_create(self, serializer):
        group = self.get_group()
        with transaction.atomic():
            member = serializer.save(group=group)
            logger.info(f'Member {member.user.id} added to group {group.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='group_add_member',
                resource='group_member',
                resource_id=member.id,
                ip=get_client_ip(self.request)
            )

    def perform_update(self, serializer):
        member = self.get_object()
        old_role = member.role
        with transaction.atomic():
            serializer.save()
            logger.info(f'Member {member.user.id} role changed from {old_role} to {member.role}')
            log_audit_event(
                user_id=self.request.user.id,
                action='group_update_member',
                resource='group_member',
                resource_id=member.id,
                ip=get_client_ip(self.request),
                details={'old_role': old_role, 'new_role': member.role}
            )

    def perform_destroy(self, instance):
        group = instance.group
        with transaction.atomic():
            group.remove_member(instance.user, reason='Removed by admin')
            logger.info(f'Member {instance.user.id} removed from group {group.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='group_remove_member',
                resource='group_member',
                resource_id=instance.id,
                ip=get_client_ip(self.request)
            )

    @action(detail=True, methods=['post'])
    def promote(self, request, group_id=None, id=None):
        """Promote a member to admin."""
        member = self.get_object()
        group = self.get_group()

        if not group.is_admin(request.user) and not request.user.is_superuser:
            raise PermissionDenied(_('You do not have permission to promote members.'))

        with transaction.atomic():
            group.promote_to_admin(member.user)
            logger.info(f'Member {member.user.id} promoted to admin in group {group.id}')
            log_audit_event(
                user_id=request.user.id,
                action='group_promote_member',
                resource='group_member',
                resource_id=member.id,
                ip=get_client_ip(request)
            )
            return Response({
                'message': f'User {member.user.full_name} promoted to admin.',
                'member': GroupMemberDetailSerializer(member).data
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def demote(self, request, group_id=None, id=None):
        """Demote an admin to member."""
        member = self.get_object()
        group = self.get_group()

        if not group.is_admin(request.user) and not request.user.is_superuser:
            raise PermissionDenied(_('You do not have permission to demote members.'))

        if member.role == 'owner':
            raise BadRequestError(_('Cannot demote the owner.'))

        with transaction.atomic():
            group.demote_to_member(member.user)
            logger.info(f'Member {member.user.id} demoted to member in group {group.id}')
            log_audit_event(
                user_id=request.user.id,
                action='group_demote_member',
                resource='group_member',
                resource_id=member.id,
                ip=get_client_ip(request)
            )
            return Response({
                'message': f'User {member.user.full_name} demoted to member.',
                'member': GroupMemberDetailSerializer(member).data
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def transfer_ownership(self, request, group_id=None, id=None):
        """Transfer ownership to another member."""
        member = self.get_object()
        group = self.get_group()

        if not group.is_owner(request.user) and not request.user.is_superuser:
            raise PermissionDenied(_('Only the owner can transfer ownership.'))

        if member.role == 'owner':
            raise BadRequestError(_('User is already the owner.'))

        with transaction.atomic():
            group.transfer_ownership(member.user)
            logger.info(f'Ownership transferred to {member.user.id} in group {group.id}')
            log_audit_event(
                user_id=request.user.id,
                action='group_transfer_ownership',
                resource='group_member',
                resource_id=member.id,
                ip=get_client_ip(request)
            )
            return Response({
                'message': f'Ownership transferred to {member.user.full_name}.',
                'member': GroupMemberDetailSerializer(member).data
            }, status=status.HTTP_200_OK)


# ============================================================================
# GROUP INVITATION VIEW SET
# ============================================================================

class GroupInvitationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing group invitations.

    Provides endpoints for:
    - Listing invitations
    - Creating invitations
    - Retrieving invitation details
    - Accepting an invitation
    - Rejecting an invitation
    - Cancelling an invitation
    """

    serializer_class = GroupInvitationListSerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        group_id = self.kwargs.get('group_id')
        if group_id:
            return GroupInvitation.objects.filter(group_id=group_id)
        return GroupInvitation.objects.all()

    def get_serializer_class(self):
        if self.action == 'create':
            return GroupInvitationCreateSerializer
        elif self.action == 'accept':
            return GroupInvitationAcceptSerializer
        elif self.action == 'reject':
            return GroupInvitationRejectSerializer
        return GroupInvitationListSerializer

    def get_permissions(self):
        if self.action in ['create']:
            permission_classes = [IsAuthenticated, IsActiveUser]
        elif self.action in ['destroy']:
            permission_classes = [IsAuthenticated, IsActiveUser, IsGroupAdmin]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_group(self):
        """Get the group from the URL."""
        group_id = self.kwargs.get('group_id')
        if not group_id:
            raise NotFoundError(_('Group ID is required.'))
        try:
            return Group.objects.get(id=group_id, deleted_at__isnull=True)
        except Group.DoesNotExist:
            raise NotFoundError(_('Group not found.'))

    def perform_create(self, serializer):
        group = self.get_group()
        with transaction.atomic():
            invitation = serializer.save(
                group=group,
                inviter=self.request.user
            )
            logger.info(f'Invitation {invitation.id} sent by user {self.request.user.id}')
            log_audit_event(
                user_id=self.request.user.id,
                action='group_invite',
                resource='group_invitation',
                resource_id=invitation.id,
                ip=get_client_ip(self.request)
            )

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance.cancel()
            logger.info(f'Invitation {instance.id} cancelled by user {self.request.user.id}')

    @action(detail=True, methods=['post'])
    def accept(self, request, group_id=None, id=None):
        """Accept an invitation."""
        invitation = self.get_object()
        user = request.user

        # Check if invitation is valid
        if invitation.status != GroupInvitationStatus.PENDING:
            raise BadRequestError(_('Invitation is not pending.'))
        if invitation.is_expired:
            invitation.status = GroupInvitationStatus.EXPIRED
            invitation.save(update_fields=['status'])
            raise BadRequestError(_('Invitation has expired.'))

        # Check if user matches invitee_email
        if user.email != invitation.invitee_email:
            raise PermissionDenied(_('This invitation was sent to a different email.'))

        with transaction.atomic():
            invitation.accept(user)
            logger.info(f'Invitation {invitation.id} accepted by user {user.id}')
            log_audit_event(
                user_id=user.id,
                action='group_accept_invite',
                resource='group_invitation',
                resource_id=invitation.id,
                ip=get_client_ip(request)
            )
            return Response({
                'status': 'accepted',
                'message': 'Invitation accepted successfully.',
                'group': invitation.group.id
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def reject(self, request, group_id=None, id=None):
        """Reject an invitation."""
        invitation = self.get_object()

        if invitation.status != GroupInvitationStatus.PENDING:
            raise BadRequestError(_('Invitation is not pending.'))

        with transaction.atomic():
            invitation.reject()
            logger.info(f'Invitation {invitation.id} rejected by user {request.user.id}')
            return Response({
                'status': 'rejected',
                'message': 'Invitation rejected.'
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def cancel(self, request, group_id=None, id=None):
        """Cancel an invitation."""
        invitation = self.get_object()

        if invitation.status != GroupInvitationStatus.PENDING:
            raise BadRequestError(_('Invitation is not pending.'))

        with transaction.atomic():
            invitation.cancel()
            logger.info(f'Invitation {invitation.id} cancelled by user {request.user.id}')
            return Response({
                'status': 'cancelled',
                'message': 'Invitation cancelled.'
            }, status=status.HTTP_200_OK)


# ============================================================================
# GROUP SETTING VIEW SET
# ============================================================================

class GroupSettingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing group settings.

    Provides endpoints for:
    - Listing settings
    - Creating/updating settings
    - Retrieving a setting
    - Deleting a setting
    """

    serializer_class = GroupSettingSerializer
    pagination_class = CustomPagination
    lookup_field = 'key'

    def get_queryset(self):
        group_id = self.kwargs.get('group_id')
        if group_id:
            return GroupSetting.objects.filter(group_id=group_id)
        return GroupSetting.objects.none()

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return GroupSettingCreateUpdateSerializer
        return GroupSettingSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsAuthenticated, IsGroupAdmin]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_group(self):
        """Get the group from the URL."""
        group_id = self.kwargs.get('group_id')
        if not group_id:
            raise NotFoundError(_('Group ID is required.'))
        try:
            return Group.objects.get(id=group_id, deleted_at__isnull=True)
        except Group.DoesNotExist:
            raise NotFoundError(_('Group not found.'))

    def perform_create(self, serializer):
        group = self.get_group()
        setting = serializer.save(group=group)
        logger.info(f'Setting {setting.key} created for group {group.id}')

    def perform_update(self, serializer):
        setting = serializer.save()
        logger.info(f'Setting {setting.key} updated for group {setting.group.id}')

    def perform_destroy(self, instance):
        logger.info(f'Setting {instance.key} deleted from group {instance.group.id}')
        instance.delete()


# ============================================================================
# GROUP ACTIVITY VIEW SET
# ============================================================================

class GroupActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing group activities.

    Provides endpoints for:
    - Listing activities
    - Retrieving activity details
    """

    serializer_class = GroupActivitySerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        group_id = self.kwargs.get('group_id')
        if group_id:
            return GroupActivity.objects.filter(group_id=group_id).order_by('-timestamp')
        return GroupActivity.objects.none()

    def get_permissions(self):
        return [IsAuthenticated()]


# ============================================================================
# GROUP WINNER HISTORY VIEW SET
# ============================================================================

class GroupWinnerHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing winner history.

    Provides endpoints for:
    - Listing winners
    - Retrieving winner details
    """

    serializer_class = GroupWinnerHistorySerializer
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        group_id = self.kwargs.get('group_id')
        if group_id:
            return GroupWinnerHistory.objects.filter(group_id=group_id).order_by('-selected_at')
        return GroupWinnerHistory.objects.none()

    def get_permissions(self):
        return [IsAuthenticated()]