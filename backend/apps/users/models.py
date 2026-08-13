from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator, MinLengthValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import random
import string

class User(AbstractUser):
    """
    Custom User model for the Digital Ekub Platform.
    Uses email as the unique identifier instead of username.
    """
    # Remove username field
    username = None

    # Core fields
    email = models.EmailField(
        _('email address'),
        unique=True,
        db_index=True,
        error_messages={'unique': _('A user with this email already exists.')}
    )

    # Phone number with international format validation
    phone_regex = RegexValidator(
        regex=r'^\+?[1-9]\d{9,14}$',
        message=_("Phone number must be in international format: '+2519XXXXXXXX'")
    )
    phone = models.CharField(
        _('phone number'),
        validators=[phone_regex],
        max_length=17,
        unique=True,
        db_index=True,
        error_messages={'unique': _('A user with this phone number already exists.')}
    )

    # Profile information
    first_name = models.CharField(_('first name'), max_length=150, db_index=True)
    last_name = models.CharField(_('last name'), max_length=150, db_index=True)
    middle_name = models.CharField(_('middle name'), max_length=150, blank=True, null=True)
    profile_picture = models.ImageField(
        _('profile picture'),
        upload_to='profiles/%Y/%m/%d/',
        null=True,
        blank=True,
        max_length=255
    )
    cover_photo = models.ImageField(
        _('cover photo'),
        upload_to='covers/%Y/%m/%d/',
        null=True,
        blank=True,
        max_length=255
    )

    # Personal information
    date_of_birth = models.DateField(_('date of birth'), null=True, blank=True)
    gender = models.CharField(
        _('gender'),
        max_length=10,
        choices=[('M', _('Male')), ('F', _('Female')), ('O', _('Other'))],
        blank=True,
        null=True
    )
    address = models.TextField(_('address'), blank=True, null=True)
    city = models.CharField(_('city'), max_length=100, blank=True, null=True)
    country = models.CharField(_('country'), max_length=100, default='Ethiopia')

    # Language and preferences
    LANGUAGE_CHOICES = [
        ('en', _('English')),
        ('am', _('Amharic')),
        ('om', _('Oromo')),
        ('ti', _('Tigrinya')),
        ('so', _('Somali'))
    ]
    language = models.CharField(
        _('language'),
        max_length=5,
        choices=LANGUAGE_CHOICES,
        default='en',
        db_index=True
    )
    timezone = models.CharField(_('timezone'), max_length=50, default='Africa/Addis_Ababa')
    currency = models.CharField(_('currency'), max_length=3, default='ETB')
    notification_preferences = models.JSONField(
        _('notification preferences'),
        default=dict,
        help_text=_('User preferences for email, SMS, and push notifications')
    )

    # Verification status
    is_phone_verified = models.BooleanField(_('phone verified'), default=False, db_index=True)
    is_email_verified = models.BooleanField(_('email verified'), default=False, db_index=True)
    is_identity_verified = models.BooleanField(_('identity verified'), default=False, db_index=True)
    identity_verification_date = models.DateTimeField(_('identity verification date'), null=True, blank=True)

    # OTP and security
    otp = models.CharField(_('OTP'), max_length=6, null=True, blank=True)
    otp_created_at = models.DateTimeField(_('OTP created at'), null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(_('OTP attempts'), default=0)
    otp_verified = models.BooleanField(_('OTP verified'), default=False)
    otp_purpose = models.CharField(
        _('OTP purpose'),
        max_length=20,
        choices=[
            ('registration', _('Registration')),
            ('login', _('Login')),
            ('password_reset', _('Password Reset')),
            ('phone_verification', _('Phone Verification')),
            ('email_verification', _('Email Verification')),
            ('transaction', _('Transaction'))
        ],
        null=True,
        blank=True
    )

    # Security and login tracking
    last_login_ip = models.GenericIPAddressField(_('last login IP'), null=True, blank=True)
    last_login_device = models.CharField(_('last login device'), max_length=255, blank=True, null=True)
    last_login_location = models.CharField(_('last login location'), max_length=255, blank=True, null=True)
    login_count = models.PositiveIntegerField(_('login count'), default=0)
    failed_login_attempts = models.PositiveSmallIntegerField(_('failed login attempts'), default=0)
    locked_until = models.DateTimeField(_('locked until'), null=True, blank=True)
    is_locked = models.BooleanField(_('account locked'), default=False, db_index=True)

    # Account status
    is_active = models.BooleanField(_('active'), default=True, db_index=True)
    is_verified = models.BooleanField(_('verified'), default=False, db_index=True)
    is_suspended = models.BooleanField(_('suspended'), default=False, db_index=True)
    suspension_reason = models.TextField(_('suspension reason'), blank=True, null=True)
    suspended_at = models.DateTimeField(_('suspended at'), null=True, blank=True)
    reactivation_date = models.DateTimeField(_('reactivation date'), null=True, blank=True)

    # User statistics
    total_groups_joined = models.PositiveIntegerField(_('total groups joined'), default=0)
    total_groups_created = models.PositiveIntegerField(_('total groups created'), default=0)
    total_contributed = models.DecimalField(
        _('total contributed'),
        max_digits=15,
        decimal_places=2,
        default=0.00
    )
    total_received = models.DecimalField(
        _('total received'),
        max_digits=15,
        decimal_places=2,
        default=0.00
    )
    total_earned = models.DecimalField(
        _('total earned (fees)'),
        max_digits=15,
        decimal_places=2,
        default=0.00
    )
    reputation_score = models.PositiveIntegerField(_('reputation score'), default=0, db_index=True)
    defaulted_count = models.PositiveIntegerField(_('defaulted payments'), default=0)
    on_time_payments = models.PositiveIntegerField(_('on-time payments'), default=0)

    # Referral and marketing
    referral_code = models.CharField(
        _('referral code'),
        max_length=10,
        unique=True,
        null=True,
        blank=True,
        db_index=True
    )
    referred_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referrals',
        verbose_name=_('referred by')
    )
    referral_count = models.PositiveIntegerField(_('referral count'), default=0)

    # Device and notification tokens
    fcm_token = models.CharField(_('Firebase Cloud Messaging token'), max_length=255, blank=True, null=True)
    device_type = models.CharField(
        _('device type'),
        max_length=20,
        choices=[
            ('ios', _('iOS')),
            ('android', _('Android')),
            ('web', _('Web')),
            ('desktop', _('Desktop'))
        ],
        blank=True,
        null=True
    )
    device_id = models.CharField(_('device ID'), max_length=255, blank=True, null=True)

    # Timestamps
    date_joined = models.DateTimeField(_('date joined'), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True, db_index=True)
    last_activity = models.DateTimeField(_('last activity'), null=True, blank=True, db_index=True)
    deleted_at = models.DateTimeField(_('deleted at'), null=True, blank=True, db_index=True)
    deleted_reason = models.TextField(_('deletion reason'), blank=True, null=True)

    # Meta
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name', 'phone']

    class Meta:
        db_table = 'users'
        ordering = ['-date_joined']
        verbose_name = _('user')
        verbose_name_plural = _('users')
        indexes = [
            models.Index(fields=['email', 'is_active']),
            models.Index(fields=['phone', 'is_active']),
            models.Index(fields=['referral_code']),
            models.Index(fields=['reputation_score']),
            models.Index(fields=['last_activity']),
        ]

    def __str__(self):
        return f"{self.email} ({self.full_name})"

    def save(self, *args, **kwargs):
        # Generate referral code if not set
        if not self.referral_code:
            self.referral_code = self.generate_referral_code()
        super().save(*args, **kwargs)

    # ============================================================================
    # PROPERTIES
    # ============================================================================

    @property
    def full_name(self):
        """Return the user's full name."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def full_name_with_middle(self):
        """Return the user's full name with middle name."""
        if self.middle_name:
            return f"{self.first_name} {self.middle_name} {self.last_name}".strip()
        return self.full_name

    @property
    def display_name(self):
        """Return the display name (prefer full_name, fallback to email)."""
        return self.full_name if self.full_name else self.email

    @property
    def is_online(self):
        """Check if user was active within the last 5 minutes."""
        if not self.last_activity:
            return False
        return (timezone.now() - self.last_activity).total_seconds() < 300

    @property
    def account_age_days(self):
        """Return the number of days since the user joined."""
        return (timezone.now() - self.date_joined).days

    @property
    def verification_level(self):
        """Return the verification level of the user."""
        if self.is_identity_verified:
            return 'verified'
        if self.is_phone_verified and self.is_email_verified:
            return 'advanced'
        if self.is_phone_verified or self.is_email_verified:
            return 'basic'
        return 'unverified'

    # ============================================================================
    # METHODS
    # ============================================================================

    def generate_referral_code(self):
        """Generate a unique referral code."""
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        while User.objects.filter(referral_code=code).exists():
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        return code

    def generate_otp(self, purpose='login'):
        """Generate and store an OTP for the user."""
        otp = ''.join(random.choices(string.digits, k=6))
        self.otp = otp
        self.otp_created_at = timezone.now()
        self.otp_attempts = 0
        self.otp_purpose = purpose
        self.otp_verified = False
        self.save(update_fields=['otp', 'otp_created_at', 'otp_attempts', 'otp_purpose', 'otp_verified'])
        return otp

    def verify_otp(self, otp):
        """Verify the provided OTP."""
        if not self.otp or not self.otp_created_at:
            return False

        # Check if OTP expired (5 minutes expiry)
        if (timezone.now() - self.otp_created_at).total_seconds() > 300:
            return False

        # Check attempts
        if self.otp_attempts >= 5:
            return False

        if self.otp == otp:
            self.otp_verified = True
            self.otp = None
            self.otp_created_at = None
            self.save(update_fields=['otp_verified', 'otp', 'otp_created_at'])
            return True

        self.otp_attempts += 1
        self.save(update_fields=['otp_attempts'])
        return False

    def soft_delete(self, reason=None):
        """Soft delete the user."""
        self.deleted_at = timezone.now()
        self.deleted_reason = reason
        self.is_active = False
        self.save(update_fields=['deleted_at', 'deleted_reason', 'is_active'])

    def restore(self):
        """Restore a soft-deleted user."""
        self.deleted_at = None
        self.deleted_reason = None
        self.is_active = True
        self.save(update_fields=['deleted_at', 'deleted_reason', 'is_active'])

    def is_deleted(self):
        """Check if the user is soft-deleted."""
        return self.deleted_at is not None

    def update_last_activity(self):
        """Update the last activity timestamp."""
        self.last_activity = timezone.now()
        self.save(update_fields=['last_activity'])

    def increment_login_count(self):
        """Increment the login count."""
        self.login_count += 1
        self.save(update_fields=['login_count'])

    def lock_account(self, duration_minutes=30):
        """Lock the user account for a specified duration."""
        self.is_locked = True
        self.locked_until = timezone.now() + timezone.timedelta(minutes=duration_minutes)
        self.save(update_fields=['is_locked', 'locked_until'])

    def unlock_account(self):
        """Unlock the user account."""
        self.is_locked = False
        self.locked_until = None
        self.failed_login_attempts = 0
        self.save(update_fields=['is_locked', 'locked_until', 'failed_login_attempts'])

    def is_account_locked(self):
        """Check if the user account is locked."""
        if not self.is_locked:
            return False
        if self.locked_until and self.locked_until < timezone.now():
            self.unlock_account()
            return False
        return True

    def can_create_group(self):
        """Check if the user can create a new group."""
        if self.is_deleted() or not self.is_active or self.is_suspended or self.is_account_locked():
            return False
        # Check if user is verified enough to create groups
        if not self.is_phone_verified:
            return False
        return True

    def can_join_group(self, group):
        """Check if the user can join a specific group."""
        if self.is_deleted() or not self.is_active or self.is_suspended or self.is_account_locked():
            return False
        if not self.is_phone_verified:
            return False
        # Additional group-specific checks can be added here
        return True

    def can_contribute(self, group):
        """Check if the user can contribute to a group."""
        if self.is_deleted() or not self.is_active or self.is_suspended or self.is_account_locked():
            return False
        if not self.is_phone_verified:
            return False
        # Additional contribution checks can be added here
        return True

    def get_groups(self):
        """Get all groups the user is a member of."""
        from apps.groups.models import GroupMember
        return GroupMember.objects.filter(user=self, is_active=True).select_related('group')

    def get_active_groups(self):
        """Get active groups the user is a member of."""
        from apps.groups.models import GroupMember
        return GroupMember.objects.filter(
            user=self,
            is_active=True,
            group__status='active'
        ).select_related('group')

    def get_pending_contributions(self):
        """Get pending contributions for the user."""
        from apps.contributions.models import Contribution
        return Contribution.objects.filter(
            user=self,
            status='pending'
        ).order_by('due_date')

    def get_overdue_contributions(self):
        """Get overdue contributions for the user."""
        from apps.contributions.models import Contribution
        return Contribution.objects.filter(
            user=self,
            status='pending',
            due_date__lt=timezone.now()
        ).order_by('due_date')

    def update_reputation(self, score_change):
        """Update the user's reputation score."""
        self.reputation_score = max(0, self.reputation_score + score_change)
        self.save(update_fields=['reputation_score'])

    def update_statistics(self, contributed=0, received=0, groups_joined=0, groups_created=0):
        """Update user statistics."""
        if contributed:
            self.total_contributed += contributed
        if received:
            self.total_received += received
        if groups_joined:
            self.total_groups_joined += groups_joined
        if groups_created:
            self.total_groups_created += groups_created
        self.save(update_fields=[
            'total_contributed', 'total_received',
            'total_groups_joined', 'total_groups_created'
        ])

    def to_dict(self):
        """Convert user to dictionary for API responses."""
        return {
            'id': self.id,
            'email': self.email,
            'phone': self.phone,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.full_name,
            'profile_picture': self.profile_picture.url if self.profile_picture else None,
            'language': self.language,
            'is_phone_verified': self.is_phone_verified,
            'is_email_verified': self.is_email_verified,
            'is_identity_verified': self.is_identity_verified,
            'verification_level': self.verification_level,
            'date_joined': self.date_joined.isoformat() if self.date_joined else None,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None,
            'reputation_score': self.reputation_score,
            'total_contributed': float(self.total_contributed),
            'total_received': float(self.total_received),
            'is_online': self.is_online,
        }