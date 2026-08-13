from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = (
        'email',
        'phone',
        'first_name',
        'last_name',
        'is_active',
        'is_phone_verified',
        'is_email_verified',
        'is_identity_verified',
        'date_joined',
        'reputation_score'
    )

    list_filter = (
        'is_active',
        'is_suspended',
        'is_locked',
        'is_phone_verified',
        'is_email_verified',
        'is_identity_verified',
        'language',
        'gender',
        'date_joined',
        'country'
    )

    search_fields = (
        'email',
        'phone',
        'first_name',
        'last_name',
        'middle_name',
        'referral_code'
    )

    ordering = ('-date_joined',)

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
        'referral_count'
    )

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
                'referral_count'
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
    )

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

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('referred_by')

    def save_model(self, request, obj, form, change):
        if not obj.referral_code:
            obj.referral_code = obj.generate_referral_code()
        super().save_model(request, obj, form, change)