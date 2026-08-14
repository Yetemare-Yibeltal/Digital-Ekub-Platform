"""
Admin configuration for the groups app.

This module provides comprehensive Django admin interfaces for all group models:
- Group: Main group entity with full CRUD operations
- GroupMember: Membership management with role assignment
- GroupInvitation: Invitation tracking and management
- GroupSetting: Group configuration management
- GroupActivity: Audit log viewing
- GroupWinnerHistory: Winner history viewing and management

All admin classes include custom list displays, filters, search fields,
inline relationships, and custom actions for efficient group management.
"""

from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.urls import reverse
from django.utils.html import format_html
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.contrib import messages
from django.db.models import Count, Sum, Q

import csv
from io import StringIO
from decimal import Decimal

from apps.users.models import User
from apps.common.constants import GroupStatus, GroupMemberRole, GroupType, GroupFrequency, GroupWinnerSelection
from apps.common.utils import format_currency, log_audit_event

from .models import (
    Group, GroupMember, GroupInvitation, GroupSetting,
    GroupActivity, GroupWinnerHistory
)


# ============================================================================
# GROUP ADMIN
# ============================================================================

@admin.register(Group)
class GroupAdmin(ModelAdmin):
    """
    Admin configuration for Group model with comprehensive features.
    """
    # List display
    list_display = (
        'id',
        'name_display',
        'status_badge',
        'type_display',
        'frequency_display',
        'contribution_amount_display',
        'members_count_display',
        'current_round_display',
        'created_by_display',
        'created_at_display',
        'actions_display',
    )

    # List filters
    list_filter = (
        'status',
        'type',
        'frequency',
        'winner_selection',
        'created_at',
        'start_date',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    # Search fields
    search_fields = (
        'name',
        'description',
        'created_by__email',
        'created_by__first_name',
        'created_by__last_name',
        'id',
    )

    # Ordering
    ordering = ('-created_at',)

    # Readonly fields
    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'deleted_at',
        'members_count',
        'total_contributions',
        'total_paid',
        'total_pending',
        'total_overdue',
        'created_by',
        'current_round',
        'completed_at',
        'paused_at',
        'cancelled_at',
        'get_members_link',
        'get_activities_link',
        'get_winners_link',
        'get_statistics_display',
    )

    # Fieldsets
    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'id',
                'name',
                'description',
                'type',
                'status',
                'created_by',
            )
        }),

        (_('Financial Settings'), {
            'fields': (
                'frequency',
                'contribution_amount',
                'cycle_length',
                'max_members',
                'winner_selection',
            )
        }),

        (_('Timeline'), {
            'fields': (
                'start_date',
                'end_date',
                'current_round',
                'completed_at',
                'paused_at',
                'cancelled_at',
            )
        }),

        (_('Statistics (Denormalized)'), {
            'fields': (
                'members_count',
                'total_contributions',
                'total_paid',
                'total_pending',
                'total_overdue',
                'get_statistics_display',
            ),
            'classes': ('collapse',),
        }),

        (_('Admin Links'), {
            'fields': (
                'get_members_link',
                'get_activities_link',
                'get_winners_link',
            ),
            'classes': ('collapse',),
        }),

        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
                'deleted_at',
            ),
            'classes': ('collapse',),
        }),
    )

    # Inlines
    inlines = []

    # Actions
    actions = [
        'activate_groups',
        'pause_groups',
        'resume_groups',
        'complete_groups',
        'cancel_groups',
        'export_as_csv',
        'export_as_json',
        'delete_selected_permanently',
    ]

    # List per page
    list_per_page = 50

    # List max show all
    list_max_show_all = 200

    # Save as
    save_as = True

    # Save as continue
    save_as_continue = True

    # --------------------------------------------------------------------------
    # CUSTOM DISPLAY METHODS
    # --------------------------------------------------------------------------

    def name_display(self, obj):
        """Display group name with link to detail view."""
        url = reverse('admin:groups_group_change', args=[obj.id])
        return format_html(
            '<a href="{}" style="font-weight: bold;">{}</a>',
            url,
            obj.name
        )
    name_display.short_description = _('Name')
    name_display.admin_order_field = 'name'

    def status_badge(self, obj):
        """Display status as a colored badge."""
        colors = {
            GroupStatus.ACTIVE: 'green',
            GroupStatus.PENDING: 'orange',
            GroupStatus.COMPLETED: 'blue',
            GroupStatus.CANCELLED: 'red',
            GroupStatus.PAUSED: 'gray',
            GroupStatus.EXPIRED: 'darkred',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 12px; font-size: 12px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def type_display(self, obj):
        """Display type with badge."""
        colors = {
            GroupType.PUBLIC: 'green',
            GroupType.PRIVATE: 'blue',
            GroupType.INVITE_ONLY: 'orange',
        }
        color = colors.get(obj.type, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 12px; font-size: 12px;">{}</span>',
            color,
            obj.get_type_display()
        )
    type_display.short_description = _('Type')
    type_display.admin_order_field = 'type'

    def frequency_display(self, obj):
        """Display frequency with badge."""
        return format_html(
            '<span style="background: #6c757d; color: white; padding: 2px 8px; '
            'border-radius: 12px; font-size: 12px;">{}</span>',
            obj.get_frequency_display()
        )
    frequency_display.short_description = _('Frequency')
    frequency_display.admin_order_field = 'frequency'

    def contribution_amount_display(self, obj):
        """Display formatted contribution amount."""
        return format_currency(obj.contribution_amount)
    contribution_amount_display.short_description = _('Amount')
    contribution_amount_display.admin_order_field = 'contribution_amount'

    def members_count_display(self, obj):
        """Display members count with link."""
        url = reverse('admin:groups_groupmember_changelist') + f'?group__id__exact={obj.id}'
        return format_html(
            '<a href="{}">{} / {}</a>',
            url,
            obj.members_count,
            obj.max_members
        )
    members_count_display.short_description = _('Members')
    members_count_display.admin_order_field = 'members_count'

    def current_round_display(self, obj):
        """Display current round with progress bar."""
        progress = obj.progress_percentage
        return format_html(
            '{}/{} <span style="background: #e9ecef; padding: 2px 4px; '
            'border-radius: 4px; font-size: 11px;">{}%</span>',
            obj.current_round + 1,
            obj.cycle_length,
            int(progress)
        )
    current_round_display.short_description = _('Round')
    current_round_display.admin_order_field = 'current_round'

    def created_by_display(self, obj):
        """Display created by with link to user admin."""
        if obj.created_by:
            url = reverse('admin:users_user_change', args=[obj.created_by.id])
            return format_html(
                '<a href="{}">{}</a>',
                url,
                obj.created_by.email
            )
        return '-'
    created_by_display.short_description = _('Created By')
    created_by_display.admin_order_field = 'created_by'

    def created_at_display(self, obj):
        """Display formatted created at."""
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def actions_display(self, obj):
        """Display action buttons for quick operations."""
        actions = []

        if obj.status in [GroupStatus.ACTIVE, GroupStatus.PAUSED]:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #28a745; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 2px;">Complete</button>',
                    f'/admin/groups/group/{obj.id}/complete/'
                )
            )

        if obj.status == GroupStatus.ACTIVE:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #ffc107; color: black; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 2px;">Pause</button>',
                    f'/admin/groups/group/{obj.id}/pause/'
                )
            )

        if obj.status == GroupStatus.PAUSED:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #17a2b8; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 2px;">Resume</button>',
                    f'/admin/groups/group/{obj.id}/resume/'
                )
            )

        if obj.status not in [GroupStatus.COMPLETED, GroupStatus.CANCELLED]:
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" '
                    'style="background: #dc3545; color: white; border: none; '
                    'padding: 2px 8px; border-radius: 3px; cursor: pointer; '
                    'margin: 2px;">Cancel</button>',
                    f'/admin/groups/group/{obj.id}/cancel/'
                )
            )

        return format_html('&nbsp;'.join(actions))
    actions_display.short_description = _('Actions')
    actions_display.allow_tags = True

    def get_members_link(self, obj):
        """Link to members list for this group."""
        url = reverse('admin:groups_groupmember_changelist') + f'?group__id__exact={obj.id}'
        return format_html('<a href="{}">View Members ({})</a>', url, obj.members_count)
    get_members_link.short_description = _('Members')

    def get_activities_link(self, obj):
        """Link to activities list for this group."""
        url = reverse('admin:groups_groupactivity_changelist') + f'?group__id__exact={obj.id}'
        return format_html('<a href="{}">View Activities</a>', url)
    get_activities_link.short_description = _('Activities')

    def get_winners_link(self, obj):
        """Link to winners list for this group."""
        url = reverse('admin:groups_groupwinnerhistory_changelist') + f'?group__id__exact={obj.id}'
        return format_html('<a href="{}">View Winners</a>', url)
    get_winners_link.short_description = _('Winners')

    def get_statistics_display(self, obj):
        """Display statistics as a formatted table."""
        stats = obj.get_contribution_summary()
        return format_html(
            '''
            <table style="border-collapse: collapse; width: 100%;">
                <tr><td style="padding: 2px 8px;">Total Contributions:</td>
                <td style="padding: 2px 8px; font-weight: bold;">{}</td></tr>
                <tr><td style="padding: 2px 8px;">Paid:</td>
                <td style="padding: 2px 8px; color: green; font-weight: bold;">{} ({})</td></tr>
                <tr><td style="padding: 2px 8px;">Pending:</td>
                <td style="padding: 2px 8px; color: orange; font-weight: bold;">{} ({})</td></tr>
                <tr><td style="padding: 2px 8px;">Overdue:</td>
                <td style="padding: 2px 8px; color: red; font-weight: bold;">{} ({})</td></tr>
                <tr><td style="padding: 2px 8px;">Completion Rate:</td>
                <td style="padding: 2px 8px; font-weight: bold;">{}%</td></tr>
            </table>
            ''',
            stats['total_contributions'],
            stats['paid_contributions'],
            format_currency(stats['total_paid_amount']),
            stats['pending_contributions'],
            format_currency(stats['pending_amount']),
            stats['overdue_contributions'],
            format_currency(stats['overdue_amount']),
            stats['completion_rate']
        )
    get_statistics_display.short_description = _('Statistics')

    # --------------------------------------------------------------------------
    # CUSTOM ACTIONS
    # --------------------------------------------------------------------------

    def activate_groups(self, request, queryset):
        """Activate selected groups."""
        count = 0
        for group in queryset:
            if group.status == GroupStatus.PENDING:
                group.status = GroupStatus.ACTIVE
                group.save(update_fields=['status'])
                count += 1
        self.message_user(request, f'Activated {count} group(s).')
    activate_groups.short_description = _('Activate selected groups')

    def pause_groups(self, request, queryset):
        """Pause selected groups."""
        count = 0
        for group in queryset:
            if group.status == GroupStatus.ACTIVE:
                group.pause_group()
                count += 1
        self.message_user(request, f'Paused {count} group(s).')
    pause_groups.short_description = _('Pause selected groups')

    def resume_groups(self, request, queryset):
        """Resume selected groups."""
        count = 0
        for group in queryset:
            if group.status == GroupStatus.PAUSED:
                group.resume_group()
                count += 1
        self.message_user(request, f'Resumed {count} group(s).')
    resume_groups.short_description = _('Resume selected groups')

    def complete_groups(self, request, queryset):
        """Complete selected groups."""
        count = 0
        errors = []
        for group in queryset:
            try:
                if group.is_active and not group.is_completed:
                    group.complete_group()
                    count += 1
            except Exception as e:
                errors.append(f'Group {group.id}: {str(e)}')
        msg = f'Completed {count} group(s).'
        if errors:
            msg += f' Errors: {", ".join(errors)}'
        self.message_user(request, msg)
    complete_groups.short_description = _('Complete selected groups')

    def cancel_groups(self, request, queryset):
        """Cancel selected groups."""
        count = 0
        reason = request.POST.get('reason', 'Cancelled by admin')
        for group in queryset:
            if not group.is_cancelled:
                group.cancel_group(reason)
                count += 1
        self.message_user(request, f'Cancelled {count} group(s). Reason: {reason}')
    cancel_groups.short_description = _('Cancel selected groups')

    def export_as_csv(self, request, queryset):
        """Export selected groups as CSV."""
        meta = self.model._meta
        field_names = [
            'id', 'name', 'status', 'type', 'frequency',
            'contribution_amount', 'cycle_length', 'max_members',
            'members_count', 'current_round', 'created_at', 'start_date', 'end_date'
        ]

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename={meta.verbose_name_plural}.csv'
        writer = csv.writer(response)
        writer.writerow(field_names)

        for obj in queryset:
            row = [getattr(obj, field) for field in field_names]
            writer.writerow(row)

        self.message_user(request, f'Exported {queryset.count()} group(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def export_as_json(self, request, queryset):
        """Export selected groups as JSON."""
        import json
        from django.core.serializers.json import DjangoJSONEncoder

        data = list(queryset.values(
            'id', 'name', 'status', 'type', 'frequency',
            'contribution_amount', 'cycle_length', 'max_members',
            'members_count', 'current_round', 'created_at', 'start_date', 'end_date'
        ))

        response = HttpResponse(
            json.dumps(data, cls=DjangoJSONEncoder, indent=2),
            content_type='application/json'
        )
        response['Content-Disposition'] = f'attachment; filename=groups.json'
        self.message_user(request, f'Exported {queryset.count()} group(s).')
        return response
    export_as_json.short_description = _('Export selected as JSON')

    def delete_selected_permanently(self, request, queryset):
        """Permanently delete selected groups."""
        count = queryset.count()
        for group in queryset:
            group.delete()
        self.message_user(request, f'Permanently deleted {count} group(s).')
    delete_selected_permanently.short_description = _('Permanently delete selected groups')

    # --------------------------------------------------------------------------
    # CUSTOM ADMIN VIEWS
    # --------------------------------------------------------------------------

    def get_urls(self):
        """Add custom admin URLs for group actions."""
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:group_id>/complete/',
                self.admin_site.admin_view(self.complete_group),
                name='complete_group'
            ),
            path(
                '<int:group_id>/pause/',
                self.admin_site.admin_view(self.pause_group),
                name='pause_group'
            ),
            path(
                '<int:group_id>/resume/',
                self.admin_site.admin_view(self.resume_group),
                name='resume_group'
            ),
            path(
                '<int:group_id>/cancel/',
                self.admin_site.admin_view(self.cancel_group),
                name='cancel_group'
            ),
        ]
        return custom_urls + urls

    def complete_group(self, request, group_id):
        """Custom admin view to complete a group."""
        group = get_object_or_404(Group, id=group_id)
        if group.is_active:
            group.complete_group()
            self.message_user(request, f'Group "{group.name}" completed.')
        else:
            self.message_user(request, f'Group "{group.name}" cannot be completed.', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:groups_group_changelist'))

    def pause_group(self, request, group_id):
        """Custom admin view to pause a group."""
        group = get_object_or_404(Group, id=group_id)
        if group.is_active:
            group.pause_group()
            self.message_user(request, f'Group "{group.name}" paused.')
        else:
            self.message_user(request, f'Group "{group.name}" cannot be paused.', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:groups_group_changelist'))

    def resume_group(self, request, group_id):
        """Custom admin view to resume a group."""
        group = get_object_or_404(Group, id=group_id)
        if group.is_paused:
            group.resume_group()
            self.message_user(request, f'Group "{group.name}" resumed.')
        else:
            self.message_user(request, f'Group "{group.name}" cannot be resumed.', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:groups_group_changelist'))

    def cancel_group(self, request, group_id):
        """Custom admin view to cancel a group."""
        group = get_object_or_404(Group, id=group_id)
        if not group.is_cancelled:
            reason = request.GET.get('reason', 'Cancelled by admin')
            group.cancel_group(reason)
            self.message_user(request, f'Group "{group.name}" cancelled.')
        else:
            self.message_user(request, f'Group "{group.name}" is already cancelled.', messages.ERROR)
        return HttpResponseRedirect(reverse('admin:groups_group_changelist'))

    # --------------------------------------------------------------------------
    # OVERRIDEN METHODS
    # --------------------------------------------------------------------------

    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related('created_by')

    def save_model(self, request, obj, form, change):
        """Save model with audit logging."""
        if not change:
            if not obj.created_by:
                obj.created_by = request.user
            obj.save()
            log_audit_event(
                user_id=request.user.id,
                action='group_created_via_admin',
                resource='group',
                resource_id=obj.id,
                details={'name': obj.name}
            )
        else:
            obj.save()
            log_audit_event(
                user_id=request.user.id,
                action='group_updated_via_admin',
                resource='group',
                resource_id=obj.id,
                details={'name': obj.name}
            )

    def delete_model(self, request, obj):
        """Soft delete instead of hard delete."""
        obj.soft_delete(reason=f'Deleted by admin {request.user.email}')
        self.message_user(request, f'Group "{obj.name}" has been soft deleted.')

    def delete_queryset(self, request, queryset):
        """Soft delete multiple groups."""
        count = 0
        for obj in queryset:
            obj.soft_delete(reason=f'Bulk deleted by admin {request.user.email}')
            count += 1
        self.message_user(request, f'{count} group(s) have been soft deleted.')


# ============================================================================
# GROUP MEMBER ADMIN
# ============================================================================

@admin.register(GroupMember)
class GroupMemberAdmin(ModelAdmin):
    """Admin configuration for GroupMember model."""

    list_display = (
        'id',
        'user_display',
        'group_display',
        'role_badge',
        'joined_at_display',
        'is_active_display',
    )

    list_filter = (
        'role',
        'is_active',
        'joined_at',
        ('group', admin.RelatedOnlyFieldListFilter),
        ('user', admin.RelatedOnlyFieldListFilter),
    )

    search_fields = (
        'user__email',
        'user__first_name',
        'user__last_name',
        'group__name',
        'group__id',
    )

    ordering = ('-joined_at',)

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'joined_at',
        'left_at',
    )

    fieldsets = (
        (_('Membership'), {
            'fields': (
                'group',
                'user',
                'role',
                'is_active',
            )
        }),
        (_('Timing'), {
            'fields': (
                'joined_at',
                'left_at',
                'reason',
            )
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'activate_members',
        'deactivate_members',
        'promote_to_admin',
        'promote_to_owner',
        'demote_to_member',
        'export_as_csv',
    ]

    list_per_page = 50

    def user_display(self, obj):
        """Display user with link."""
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def group_display(self, obj):
        """Display group with link."""
        url = reverse('admin:groups_group_change', args=[obj.group.id])
        return format_html('<a href="{}">{}</a>', url, obj.group.name)
    group_display.short_description = _('Group')
    group_display.admin_order_field = 'group__name'

    def role_badge(self, obj):
        """Display role with colored badge."""
        colors = {
            GroupMemberRole.OWNER: 'red',
            GroupMemberRole.ADMIN: 'blue',
            GroupMemberRole.MEMBER: 'green',
            GroupMemberRole.OBSERVER: 'gray',
        }
        color = colors.get(obj.role, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 12px; font-size: 12px;">{}</span>',
            color,
            obj.get_role_display()
        )
    role_badge.short_description = _('Role')
    role_badge.admin_order_field = 'role'

    def joined_at_display(self, obj):
        """Display formatted joined at."""
        return obj.joined_at.strftime('%Y-%m-%d %H:%M')
    joined_at_display.short_description = _('Joined')
    joined_at_display.admin_order_field = 'joined_at'

    def is_active_display(self, obj):
        """Display active status with badge."""
        if obj.is_active:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Active</span>'
            )
        return format_html(
            '<span style="color: red; font-weight: bold;">✗ Inactive</span>'
        )
    is_active_display.short_description = _('Active')
    is_active_display.admin_order_field = 'is_active'

    def activate_members(self, request, queryset):
        """Activate selected members."""
        count = queryset.update(is_active=True)
        self.message_user(request, f'Activated {count} member(s).')
    activate_members.short_description = _('Activate selected members')

    def deactivate_members(self, request, queryset):
        """Deactivate selected members."""
        count = 0
        for member in queryset:
            if member.is_active:
                member.is_active = False
                member.left_at = timezone.now()
                member.reason = 'Deactivated by admin'
                member.save(update_fields=['is_active', 'left_at', 'reason'])
                count += 1
        self.message_user(request, f'Deactivated {count} member(s).')
    deactivate_members.short_description = _('Deactivate selected members')

    def promote_to_admin(self, request, queryset):
        """Promote selected members to admin."""
        count = 0
        for member in queryset:
            if member.is_active and member.role != 'owner':
                member.role = 'admin'
                member.save(update_fields=['role'])
                count += 1
        self.message_user(request, f'Promoted {count} member(s) to admin.')
    promote_to_admin.short_description = _('Promote to admin')

    def promote_to_owner(self, request, queryset):
        """Promote selected members to owner."""
        count = 0
        for member in queryset:
            if member.is_active:
                # Demote existing owners first
                GroupMember.objects.filter(group=member.group, role='owner', is_active=True).update(role='admin')
                member.role = 'owner'
                member.save(update_fields=['role'])
                count += 1
        self.message_user(request, f'Promoted {count} member(s) to owner.')
    promote_to_owner.short_description = _('Promote to owner')

    def demote_to_member(self, request, queryset):
        """Demote selected members to member."""
        count = 0
        for member in queryset:
            if member.is_active and member.role != 'owner':
                member.role = 'member'
                member.save(update_fields=['role'])
                count += 1
        self.message_user(request, f'Demoted {count} member(s) to member.')
    demote_to_member.short_description = _('Demote to member')

    def export_as_csv(self, request, queryset):
        """Export selected members as CSV."""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=group_members.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Group', 'User Email', 'Role', 'Joined At', 'Active'])
        for obj in queryset:
            writer.writerow([
                obj.id, obj.group.name, obj.user.email,
                obj.get_role_display(), obj.joined_at, obj.is_active
            ])
        self.message_user(request, f'Exported {queryset.count()} member(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')


# ============================================================================
# GROUP INVITATION ADMIN
# ============================================================================

@admin.register(GroupInvitation)
class GroupInvitationAdmin(ModelAdmin):
    """Admin configuration for GroupInvitation model."""

    list_display = (
        'id',
        'invitee_email_display',
        'inviter_display',
        'group_display',
        'status_badge',
        'expires_at_display',
        'created_at_display',
    )

    list_filter = (
        'status',
        'created_at',
        'expires_at',
        ('group', admin.RelatedOnlyFieldListFilter),
    )

    search_fields = (
        'invitee_email',
        'inviter__email',
        'group__name',
        'token',
    )

    ordering = ('-created_at',)

    readonly_fields = (
        'id',
        'token',
        'created_at',
        'updated_at',
        'accepted_at',
    )

    fieldsets = (
        (_('Invitation'), {
            'fields': (
                'group',
                'inviter',
                'invitee_email',
                'invitee_user',
                'token',
                'status',
                'message',
            )
        }),
        (_('Timing'), {
            'fields': (
                'created_at',
                'updated_at',
                'expires_at',
                'accepted_at',
            )
        }),
    )

    actions = [
        'resend_invitations',
        'expire_invitations',
        'cancel_invitations',
    ]

    def invitee_email_display(self, obj):
        """Display invitee email with link if user exists."""
        if obj.invitee_user:
            url = reverse('admin:users_user_change', args=[obj.invitee_user.id])
            return format_html(
                '<a href="{}">{}</a>',
                url,
                obj.invitee_email
            )
        return obj.invitee_email
    invitee_email_display.short_description = _('Invitee')
    invitee_email_display.admin_order_field = 'invitee_email'

    def inviter_display(self, obj):
        """Display inviter with link."""
        url = reverse('admin:users_user_change', args=[obj.inviter.id])
        return format_html('<a href="{}">{}</a>', url, obj.inviter.email)
    inviter_display.short_description = _('Inviter')
    inviter_display.admin_order_field = 'inviter__email'

    def group_display(self, obj):
        """Display group with link."""
        url = reverse('admin:groups_group_change', args=[obj.group.id])
        return format_html('<a href="{}">{}</a>', url, obj.group.name)
    group_display.short_description = _('Group')
    group_display.admin_order_field = 'group__name'

    def status_badge(self, obj):
        """Display status with colored badge."""
        colors = {
            'pending': 'orange',
            'accepted': 'green',
            'rejected': 'red',
            'expired': 'gray',
            'cancelled': 'darkred',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; '
            'border-radius: 12px; font-size: 12px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def expires_at_display(self, obj):
        """Display formatted expires at."""
        return obj.expires_at.strftime('%Y-%m-%d %H:%M')
    expires_at_display.short_description = _('Expires')
    expires_at_display.admin_order_field = 'expires_at'

    def created_at_display(self, obj):
        """Display formatted created at."""
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'

    def resend_invitations(self, request, queryset):
        """Resend invitations."""
        count = 0
        for invitation in queryset.filter(status='pending'):
            # Resend email logic would go here
            count += 1
        self.message_user(request, f'Resent {count} invitation(s).')
    resend_invitations.short_description = _('Resend selected invitations')

    def expire_invitations(self, request, queryset):
        """Expire selected invitations."""
        count = queryset.filter(status='pending').update(status='expired')
        self.message_user(request, f'Expired {count} invitation(s).')
    expire_invitations.short_description = _('Expire selected invitations')

    def cancel_invitations(self, request, queryset):
        """Cancel selected invitations."""
        count = queryset.filter(status='pending').update(status='cancelled')
        self.message_user(request, f'Cancelled {count} invitation(s).')
    cancel_invitations.short_description = _('Cancel selected invitations')


# ============================================================================
# GROUP SETTING ADMIN
# ============================================================================

@admin.register(GroupSetting)
class GroupSettingAdmin(ModelAdmin):
    """Admin configuration for GroupSetting model."""

    list_display = (
        'id',
        'group_display',
        'key_display',
        'value_display',
        'created_at_display',
    )

    list_filter = (
        ('group', admin.RelatedOnlyFieldListFilter),
        'created_at',
    )

    search_fields = (
        'group__name',
        'key',
        'value',
    )

    ordering = ('-created_at',)

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
    )

    fieldsets = (
        (_('Setting'), {
            'fields': (
                'group',
                'key',
                'value',
                'description',
            )
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    def group_display(self, obj):
        """Display group with link."""
        url = reverse('admin:groups_group_change', args=[obj.group.id])
        return format_html('<a href="{}">{}</a>', url, obj.group.name)
    group_display.short_description = _('Group')
    group_display.admin_order_field = 'group__name'

    def key_display(self, obj):
        """Display key with styling."""
        return format_html(
            '<code style="background: #f8f9fa; padding: 2px 6px; border-radius: 4px;">{}</code>',
            obj.key
        )
    key_display.short_description = _('Key')
    key_display.admin_order_field = 'key'

    def value_display(self, obj):
        """Display value with truncation."""
        value = str(obj.value)
        if len(value) > 50:
            value = value[:50] + '...'
        return value
    value_display.short_description = _('Value')
    value_display.admin_order_field = 'value'

    def created_at_display(self, obj):
        """Display formatted created at."""
        return obj.created_at.strftime('%Y-%m-%d %H:%M')
    created_at_display.short_description = _('Created')
    created_at_display.admin_order_field = 'created_at'


# ============================================================================
# GROUP ACTIVITY ADMIN
# ============================================================================

@admin.register(GroupActivity)
class GroupActivityAdmin(ModelAdmin):
    """Admin configuration for GroupActivity model."""

    list_display = (
        'id',
        'group_display',
        'action_display',
        'user_display',
        'timestamp_display',
    )

    list_filter = (
        'action',
        ('group', admin.RelatedOnlyFieldListFilter),
        'timestamp',
    )

    search_fields = (
        'group__name',
        'action',
        'user__email',
        'details',
    )

    ordering = ('-timestamp',)

    readonly_fields = (
        'id',
        'group',
        'user',
        'action',
        'details',
        'timestamp',
    )

    list_per_page = 50

    def group_display(self, obj):
        """Display group with link."""
        url = reverse('admin:groups_group_change', args=[obj.group.id])
        return format_html('<a href="{}">{}</a>', url, obj.group.name)
    group_display.short_description = _('Group')
    group_display.admin_order_field = 'group__name'

    def action_display(self, obj):
        """Display action with styling."""
        return format_html(
            '<code style="background: #f8f9fa; padding: 2px 6px; border-radius: 4px;">{}</code>',
            obj.action
        )
    action_display.short_description = _('Action')
    action_display.admin_order_field = 'action'

    def user_display(self, obj):
        """Display user with link if exists."""
        if obj.user:
            url = reverse('admin:users_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.email)
        return 'System'
    user_display.short_description = _('User')
    user_display.admin_order_field = 'user__email'

    def timestamp_display(self, obj):
        """Display formatted timestamp."""
        return obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_display.short_description = _('Timestamp')
    timestamp_display.admin_order_field = 'timestamp'

    def has_add_permission(self, request):
        """Prevent manual addition of activities."""
        return False

    def has_change_permission(self, request, obj=None):
        """Prevent editing of activities."""
        return False


# ============================================================================
# GROUP WINNER HISTORY ADMIN
# ============================================================================

@admin.register(GroupWinnerHistory)
class GroupWinnerHistoryAdmin(ModelAdmin):
    """Admin configuration for GroupWinnerHistory model."""

    list_display = (
        'id',
        'group_display',
        'user_display',
        'round_display',
        'amount_display',
        'paid_out_display',
        'selected_at_display',
    )

    list_filter = (
        'paid_out',
        ('group', admin.RelatedOnlyFieldListFilter),
        'selected_at',
    )

    search_fields = (
        'group__name',
        'user__email',
        'user__first_name',
        'user__last_name',
        'payment_reference',
    )

    ordering = ('-selected_at',)

    readonly_fields = (
        'id',
        'group',
        'user',
        'round',
        'amount',
        'selected_at',
        'paid_out_at',
    )

    fieldsets = (
        (_('Winner'), {
            'fields': (
                'group',
                'user',
                'round',
                'amount',
                'payment_reference',
            )
        }),
        (_('Payment Status'), {
            'fields': (
                'paid_out',
                'paid_out_at',
            )
        }),
        (_('Timing'), {
            'fields': (
                'selected_at',
            )
        }),
    )

    actions = [
        'mark_as_paid',
        'mark_as_unpaid',
        'export_as_csv',
    ]

    def group_display(self, obj):
        """Display group with link."""
        url = reverse('admin:groups_group_change', args=[obj.group.id])
        return format_html('<a href="{}">{}</a>', url, obj.group.name)
    group_display.short_description = _('Group')
    group_display.admin_order_field = 'group__name'

    def user_display(self, obj):
        """Display user with link."""
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_display.short_description = _('Winner')
    user_display.admin_order_field = 'user__email'

    def round_display(self, obj):
        """Display round number."""
        return f"Round {obj.round + 1}"
    round_display.short_description = _('Round')
    round_display.admin_order_field = 'round'

    def amount_display(self, obj):
        """Display formatted amount."""
        return format_currency(obj.amount)
    amount_display.short_description = _('Amount')
    amount_display.admin_order_field = 'amount'

    def paid_out_display(self, obj):
        """Display paid out status with badge."""
        if obj.paid_out:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Paid</span>'
            )
        return format_html(
            '<span style="color: orange; font-weight: bold;">⏳ Pending</span>'
        )
    paid_out_display.short_description = _('Paid Out')
    paid_out_display.admin_order_field = 'paid_out'

    def selected_at_display(self, obj):
        """Display formatted selected at."""
        return obj.selected_at.strftime('%Y-%m-%d %H:%M')
    selected_at_display.short_description = _('Selected')
    selected_at_display.admin_order_field = 'selected_at'

    def mark_as_paid(self, request, queryset):
        """Mark selected winners as paid."""
        count = 0
        for winner in queryset.filter(paid_out=False):
            winner.mark_paid()
            count += 1
        self.message_user(request, f'Marked {count} winner(s) as paid.')
    mark_as_paid.short_description = _('Mark selected as paid')

    def mark_as_unpaid(self, request, queryset):
        """Mark selected winners as unpaid."""
        count = queryset.filter(paid_out=True).update(paid_out=False, paid_out_at=None)
        self.message_user(request, f'Marked {count} winner(s) as unpaid.')
    mark_as_unpaid.short_description = _('Mark selected as unpaid')

    def export_as_csv(self, request, queryset):
        """Export selected winners as CSV."""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=winners.csv'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Group', 'Winner Email', 'Round', 'Amount', 'Paid Out', 'Selected At'])
        for obj in queryset:
            writer.writerow([
                obj.id, obj.group.name, obj.user.email,
                obj.round + 1, float(obj.amount),
                'Yes' if obj.paid_out else 'No',
                obj.selected_at
            ])
        self.message_user(request, f'Exported {queryset.count()} winner(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def has_add_permission(self, request):
        """Prevent manual addition of winner history."""
        return False