from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.http import HttpResponse
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from django.utils.html import format_html
import csv
from io import StringIO
from .models import User


class UserCreationFormWithPhone(UserCreationForm):
    """Custom user creation form with phone field."""
    class Meta:
        model = User
        fields = ('email', 'phone', 'first_name', 'last_name')


class UserChangeFormWithPhone(UserChangeForm):
    """Custom user change form with phone field."""
    class Meta:
        model = User
        fields = '__all__'


class GroupInline(admin.TabularInline):
    """Inline for groups the user is a member of."""
    from apps.groups.models import GroupMember
    model = GroupMember
    extra = 0
    fields = ('group', 'role', 'is_active', 'joined_at')
    readonly_fields = ('joined_at',)
    can_delete = False
    verbose_name = _('Group Membership')
    verbose_name_plural = _('Group Memberships')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('group')


class ContributionInline(admin.TabularInline):
    """Inline for user contributions."""
    from apps.contributions.models import Contribution
    model = Contribution
    extra = 0
    fields = ('group', 'amount', 'status', 'due_date', 'paid_date')
    readonly_fields = ('created_at', 'updated_at')
    can_delete = False
    verbose_name = _('Contribution')
    verbose_name_plural = _('Contributions')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('group')


class PayoutInline(admin.TabularInline):
    """Inline for user payouts."""
    from apps.payments.models import Payout
    model = Payout
    extra = 0
    fields = ('group', 'amount', 'status', 'created_at')
    readonly_fields = ('created_at',)
    can_delete = False
    verbose_name = _('Payout')
    verbose_name_plural = _('Payouts')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('group')


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Complete admin configuration for User model."""

    # Forms
    form = UserChangeFormWithPhone
    add_form = UserCreationFormWithPhone

    # List display
    list_display = (
        'email',
        'phone',
        'full_name_display',
        'verification_badge',
        'status_badge',
        'is_phone_verified',
        'is_email_verified',
        'reputation_score',
        'date_joined_display',
        'admin_actions'
    )

    # List filters
    list_filter = (
        'is_active',
        'is_suspended',
        'is_locked',
        'is_phone_verified',
        'is_email_verified',
        'is_identity_verified',
        'is_verified',
        'language',
        'gender',
        'country',
        'date_joined',
        ('deleted_at', admin.EmptyFieldListFilter),
    )

    # Search fields
    search_fields = (
        'email',
        'phone',
        'first_name',
        'last_name',
        'middle_name',
        'referral_code',
        'id',
    )

    # Ordering
    ordering = ('-date_joined',)

    # Readonly fields
    readonly_fields = (
        'date_joined',
        'updated_at',
        'last_login',
        'last_login_ip',
        'login_count',
        'otp',
        'otp_created_at',
        'otp_attempts',
        'total_groups_joined',
        'total_groups_created',
        'total_contributed',
        'total_received',
        'reputation_score',
        'referral_code',
        'referral_count',
        'get_referral_link',
        'get_full_profile_link',
    )

    # Fieldsets
    fieldsets = (
        (None, {'fields': ('email', 'password')}),

        (_('Personal Information'), {
            'fields': (
                'first_name',
                'last_name',
                'middle_name',
                'phone',
                'profile_picture',
                'cover_photo',
                'date_of_birth',
                'gender',
                'address',
                'city',
                'country'
            )
        }),

        (_('Preferences'), {
            'fields': (
                'language',
                'timezone',
                'currency',
                'notification_preferences'
            ),
            'classes': ('collapse',)
        }),

        (_('Verification'), {
            'fields': (
                'is_phone_verified',
                'is_email_verified',
                'is_identity_verified',
                'identity_verification_date',
                'is_verified'
            )
        }),

        (_('Security & OTP'), {
            'fields': (
                'otp',
                'otp_created_at',
                'otp_attempts',
                'otp_verified',
                'otp_purpose',
                'last_login_ip',
                'last_login_device',
                'last_login_location',
                'login_count',
                'failed_login_attempts',
                'locked_until',
                'is_locked'
            ),
            'classes': ('collapse',)
        }),

        (_('Account Status'), {
            'fields': (
                'is_active',
                'is_suspended',
                'suspension_reason',
                'suspended_at',
                'reactivation_date',
                'deleted_at',
                'deleted_reason'
            )
        }),

        (_('Statistics'), {
            'fields': (
                'total_groups_joined',
                'total_groups_created',
                'total_contributed',
                'total_received',
                'total_earned',
                'reputation_score',
                'defaulted_count',
                'on_time_payments'
            ),
            'classes': ('collapse',)
        }),

        (_('Referral'), {
            'fields': (
                'referral_code',
                'referred_by',
                'referral_count',
                'get_referral_link'
            ),
            'classes': ('collapse',)
        }),

        (_('Device'), {
            'fields': (
                'fcm_token',
                'device_type',
                'device_id'
            ),
            'classes': ('collapse',)
        }),

        (_('Important Dates'), {
            'fields': (
                'date_joined',
                'updated_at',
                'last_login',
                'last_activity'
            )
        }),

        (_('Admin Links'), {
            'fields': ('get_full_profile_link',),
            'classes': ('collapse',)
        }),
    )

    # Add fieldsets for creating new user
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email',
                'phone',
                'first_name',
                'last_name',
                'password1',
                'password2'
            ),
        }),
    )

    # Inlines
    inlines = [
        GroupInline,
        ContributionInline,
        PayoutInline,
    ]

    # Actions
    actions = [
        'activate_users',
        'suspend_users',
        'verify_phone',
        'verify_email',
        'verify_identity',
        'lock_users',
        'unlock_users',
        'export_as_csv',
        'delete_selected_permanently',
    ]

    # List per page
    list_per_page = 50

    # List max show all
    list_max_show_all = 200

    # ============================================================================
    # CUSTOM METHODS FOR LIST DISPLAY
    # ============================================================================

    def full_name_display(self, obj):
        """Display full name with link."""
        return format_html(
            '<a href="{}" style="font-weight: bold;">{}</a>',
            reverse('admin:users_user_change', args=[obj.id]),
            obj.full_name
        )
    full_name_display.short_description = _('Full Name')
    full_name_display.admin_order_field = 'first_name'

    def verification_badge(self, obj):
        """Display verification badge."""
        if obj.is_identity_verified:
            return format_html('<span style="color: green; font-weight: bold;">✓ Verified</span>')
        elif obj.is_phone_verified and obj.is_email_verified:
            return format_html('<span style="color: blue; font-weight: bold;">◉ Advanced</span>')
        elif obj.is_phone_verified or obj.is_email_verified:
            return format_html('<span style="color: orange; font-weight: bold;">◉ Basic</span>')
        return format_html('<span style="color: red; font-weight: bold;">✗ Unverified</span>')
    verification_badge.short_description = _('Verification')

    def status_badge(self, obj):
        """Display status badge."""
        if obj.is_deleted():
            return format_html('<span style="color: gray; font-weight: bold;">Deleted</span>')
        elif obj.is_suspended:
            return format_html('<span style="color: red; font-weight: bold;">Suspended</span>')
        elif obj.is_account_locked():
            return format_html('<span style="color: orange; font-weight: bold;">Locked</span>')
        elif not obj.is_active:
            return format_html('<span style="color: gray; font-weight: bold;">Inactive</span>')
        return format_html('<span style="color: green; font-weight: bold;">Active</span>')
    status_badge.short_description = _('Status')

    def date_joined_display(self, obj):
        """Display date joined in a readable format."""
        return obj.date_joined.strftime('%Y-%m-%d %H:%M')
    date_joined_display.short_description = _('Joined')
    date_joined_display.admin_order_field = 'date_joined'

    def admin_actions(self, obj):
        """Display admin action buttons."""
        actions = []
        if not obj.is_deleted():
            if obj.is_suspended:
                actions.append(
                    format_html(
                        '<button onclick="location.href=\'{}\'" style="background: #28a745; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer;">Unsuspend</button>',
                        reverse('admin_unsuspend_user', args=[obj.id])
                    )
                )
            else:
                actions.append(
                    format_html(
                        '<button onclick="location.href=\'{}\'" style="background: #dc3545; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer;">Suspend</button>',
                        reverse('admin_suspend_user', args=[obj.id])
                    )
                )
            actions.append(
                format_html(
                    '<button onclick="location.href=\'{}\'" style="background: #007bff; color: white; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer;">View</button>',
                    reverse('admin:users_user_change', args=[obj.id])
                )
            )
        return format_html('&nbsp;&nbsp;'.join(actions))
    admin_actions.short_description = _('Actions')
    admin_actions.allow_tags = True

    def get_referral_link(self, obj):
        """Generate referral link for the user."""
        if obj.referral_code:
            return format_html(
                '<a href="{}?ref={}" target="_blank">{}/register?ref={}</a>',
                'https://ekub-platform.com',
                obj.referral_code,
                'https://ekub-platform.com',
                obj.referral_code
            )
        return _('No referral code')
    get_referral_link.short_description = _('Referral Link')

    def get_full_profile_link(self, obj):
        """Generate admin link to view full profile."""
        return format_html(
            '<a href="{}" target="_blank">View Full Profile</a>',
            reverse('admin:users_user_change', args=[obj.id])
        )
    get_full_profile_link.short_description = _('Profile Link')

    # ============================================================================
    # CUSTOM ACTIONS
    # ============================================================================

    def activate_users(self, request, queryset):
        """Activate selected users."""
        count = queryset.update(is_active=True, is_suspended=False, deleted_at=None)
        self.message_user(request, f'Activated {count} user(s).')
    activate_users.short_description = _('Activate selected users')

    def suspend_users(self, request, queryset):
        """Suspend selected users."""
        count = queryset.update(is_active=False, is_suspended=True, suspended_at=timezone.now())
        self.message_user(request, f'Suspended {count} user(s).')
    suspend_users.short_description = _('Suspend selected users')

    def verify_phone(self, request, queryset):
        """Verify phone for selected users."""
        count = queryset.update(is_phone_verified=True)
        self.message_user(request, f'Verified phone for {count} user(s).')
    verify_phone.short_description = _('Verify phone numbers')

    def verify_email(self, request, queryset):
        """Verify email for selected users."""
        count = queryset.update(is_email_verified=True)
        self.message_user(request, f'Verified email for {count} user(s).')
    verify_email.short_description = _('Verify email addresses')

    def verify_identity(self, request, queryset):
        """Verify identity for selected users."""
        count = queryset.update(
            is_identity_verified=True,
            identity_verification_date=timezone.now()
        )
        self.message_user(request, f'Verified identity for {count} user(s).')
    verify_identity.short_description = _('Verify identity')

    def lock_users(self, request, queryset):
        """Lock selected user accounts."""
        count = queryset.update(is_locked=True, locked_until=timezone.now() + timezone.timedelta(minutes=30))
        self.message_user(request, f'Locked {count} user account(s).')
    lock_users.short_description = _('Lock selected accounts')

    def unlock_users(self, request, queryset):
        """Unlock selected user accounts."""
        count = queryset.update(is_locked=False, locked_until=None, failed_login_attempts=0)
        self.message_user(request, f'Unlocked {count} user account(s).')
    unlock_users.short_description = _('Unlock selected accounts')

    def export_as_csv(self, request, queryset):
        """Export selected users as CSV."""
        meta = self.model._meta
        field_names = [
            'id', 'email', 'phone', 'first_name', 'last_name',
            'is_active', 'is_phone_verified', 'is_email_verified',
            'is_identity_verified', 'date_joined', 'reputation_score'
        ]

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename={meta.verbose_name_plural}.csv'
        writer = csv.writer(response)
        writer.writerow(field_names)

        for obj in queryset:
            row = [getattr(obj, field) for field in field_names]
            writer.writerow(row)

        self.message_user(request, f'Exported {queryset.count()} user(s).')
        return response
    export_as_csv.short_description = _('Export selected as CSV')

    def delete_selected_permanently(self, request, queryset):
        """Permanently delete selected users."""
        count = queryset.count()
        for user in queryset:
            user.delete()
        self.message_user(request, f'Permanently deleted {count} user(s).')
    delete_selected_permanently.short_description = _('Permanently delete selected users')
    delete_selected_permanently.allowed_permissions = ('delete',)

    # ============================================================================
    # OVERRIDEN METHODS
    # ============================================================================

    def get_queryset(self, request):
        """Optimize queryset by selecting related fields."""
        return super().get_queryset(request).select_related('referred_by')

    def save_model(self, request, obj, form, change):
        """Save model with automatic referral code generation."""
        if not obj.referral_code:
            obj.referral_code = obj.generate_referral_code()
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        """Soft delete instead of hard delete."""
        obj.soft_delete(request.user.email)
        self.message_user(request, f'User {obj.email} has been soft deleted.')

    def delete_queryset(self, request, queryset):
        """Soft delete multiple users."""
        count = 0
        for obj in queryset:
            obj.soft_delete(request.user.email)
            count += 1
        self.message_user(request, f'{count} user(s) have been soft deleted.')

    # ============================================================================
    # CUSTOM ADMIN VIEWS (URLS)
    # ============================================================================

    def get_urls(self):
        """Add custom admin URLs."""
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                'suspend/<int:user_id>/',
                self.admin_site.admin_view(self.suspend_user),
                name='suspend_user'
            ),
            path(
                'unsuspend/<int:user_id>/',
                self.admin_site.admin_view(self.unsuspend_user),
                name='unsuspend_user'
            ),
        ]
        return custom_urls + urls

    def suspend_user(self, request, user_id):
        """Custom admin view to suspend a user."""
        user = User.objects.get(id=user_id)
        user.is_suspended = True
        user.is_active = False
        user.suspended_at = timezone.now()
        user.save()
        self.message_user(request, f'User {user.email} has been suspended.')
        return redirect(reverse('admin:users_user_changelist'))

    def unsuspend_user(self, request, user_id):
        """Custom admin view to unsuspend a user."""
        user = User.objects.get(id=user_id)
        user.is_suspended = False
        user.is_active = True
        user.suspended_at = None
        user.save()
        self.message_user(request, f'User {user.email} has been unsuspended.')
        return redirect(reverse('admin:users_user_changelist'))