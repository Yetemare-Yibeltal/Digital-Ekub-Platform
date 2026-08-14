"""
Constants for the Digital Ekub Platform.

This module defines all platform-wide constants including:
- User status, verification, and role choices
- Group status, member roles, and settings
- Contribution and payment statuses
- Notification types and channels
- Platform configuration constants
- Error codes and messages
- Currency and locale settings
- Default values and limits
"""

from typing import List, Tuple, Dict, Any, Optional
from django.utils.translation import gettext_lazy as _


# ============================================================================
# USER CONSTANTS
# ============================================================================

class UserStatus:
    """User account status choices."""
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    SUSPENDED = 'suspended'
    LOCKED = 'locked'
    DELETED = 'deleted'
    PENDING_VERIFICATION = 'pending_verification'

    CHOICES: List[Tuple[str, str]] = [
        (ACTIVE, _('Active')),
        (INACTIVE, _('Inactive')),
        (SUSPENDED, _('Suspended')),
        (LOCKED, _('Locked')),
        (DELETED, _('Deleted')),
        (PENDING_VERIFICATION, _('Pending Verification')),
    ]


class UserVerificationLevel:
    """User verification level choices."""
    UNVERIFIED = 'unverified'
    BASIC = 'basic'
    ADVANCED = 'advanced'
    VERIFIED = 'verified'

    CHOICES: List[Tuple[str, str]] = [
        (UNVERIFIED, _('Unverified')),
        (BASIC, _('Basic')),
        (ADVANCED, _('Advanced')),
        (VERIFIED, _('Verified')),
    ]


class UserRole:
    """User role types."""
    MEMBER = 'member'
    ADMIN = 'admin'
    SUPER_ADMIN = 'super_admin'
    SYSTEM = 'system'

    CHOICES: List[Tuple[str, str]] = [
        (MEMBER, _('Member')),
        (ADMIN, _('Admin')),
        (SUPER_ADMIN, _('Super Admin')),
        (SYSTEM, _('System')),
    ]


class UserGender:
    """User gender choices."""
    MALE = 'M'
    FEMALE = 'F'
    OTHER = 'O'
    PREFER_NOT_TO_SAY = 'N'

    CHOICES: List[Tuple[str, str]] = [
        (MALE, _('Male')),
        (FEMALE, _('Female')),
        (OTHER, _('Other')),
        (PREFER_NOT_TO_SAY, _('Prefer not to say')),
    ]


class UserLanguage:
    """Supported languages."""
    ENGLISH = 'en'
    AMHARIC = 'am'
    OROMO = 'om'
    TIGRINYA = 'ti'
    SOMALI = 'so'

    CHOICES: List[Tuple[str, str]] = [
        (ENGLISH, _('English')),
        (AMHARIC, _('Amharic')),
        (OROMO, _('Oromo')),
        (TIGRINYA, _('Tigrinya')),
        (SOMALI, _('Somali')),
    ]


class UserDeviceType:
    """User device types for push notifications."""
    IOS = 'ios'
    ANDROID = 'android'
    WEB = 'web'
    DESKTOP = 'desktop'

    CHOICES: List[Tuple[str, str]] = [
        (IOS, _('iOS')),
        (ANDROID, _('Android')),
        (WEB, _('Web')),
        (DESKTOP, _('Desktop')),
    ]


# ============================================================================
# GROUP CONSTANTS
# ============================================================================

class GroupStatus:
    """Group status choices."""
    ACTIVE = 'active'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    PAUSED = 'paused'
    PENDING = 'pending'
    EXPIRED = 'expired'

    CHOICES: List[Tuple[str, str]] = [
        (ACTIVE, _('Active')),
        (COMPLETED, _('Completed')),
        (CANCELLED, _('Cancelled')),
        (PAUSED, _('Paused')),
        (PENDING, _('Pending')),
        (EXPIRED, _('Expired')),
    ]


class GroupMemberRole:
    """Group member role choices."""
    OWNER = 'owner'
    ADMIN = 'admin'
    MEMBER = 'member'
    OBSERVER = 'observer'

    CHOICES: List[Tuple[str, str]] = [
        (OWNER, _('Owner')),
        (ADMIN, _('Admin')),
        (MEMBER, _('Member')),
        (OBSERVER, _('Observer')),
    ]


class GroupType:
    """Group type choices."""
    PUBLIC = 'public'
    PRIVATE = 'private'
    INVITE_ONLY = 'invite_only'

    CHOICES: List[Tuple[str, str]] = [
        (PUBLIC, _('Public')),
        (PRIVATE, _('Private')),
        (INVITE_ONLY, _('Invite Only')),
    ]


class GroupFrequency:
    """Group contribution frequency choices."""
    DAILY = 'daily'
    WEEKLY = 'weekly'
    BIWEEKLY = 'biweekly'
    MONTHLY = 'monthly'
    QUARTERLY = 'quarterly'
    YEARLY = 'yearly'

    CHOICES: List[Tuple[str, str]] = [
        (DAILY, _('Daily')),
        (WEEKLY, _('Weekly')),
        (BIWEEKLY, _('Bi-weekly')),
        (MONTHLY, _('Monthly')),
        (QUARTERLY, _('Quarterly')),
        (YEARLY, _('Yearly')),
    ]


class GroupWinnerSelection:
    """Group winner selection method choices."""
    FIXED = 'fixed'
    RANDOM = 'random'
    AUCTION = 'auction'
    BIDDING = 'bidding'

    CHOICES: List[Tuple[str, str]] = [
        (FIXED, _('Fixed Rotation')),
        (RANDOM, _('Random Selection')),
        (AUCTION, _('Auction')),
        (BIDDING, _('Bidding')),
    ]


class GroupInvitationStatus:
    """Group invitation status choices."""
    PENDING = 'pending'
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    EXPIRED = 'expired'
    CANCELLED = 'cancelled'

    CHOICES: List[Tuple[str, str]] = [
        (PENDING, _('Pending')),
        (ACCEPTED, _('Accepted')),
        (REJECTED, _('Rejected')),
        (EXPIRED, _('Expired')),
        (CANCELLED, _('Cancelled')),
    ]


# ============================================================================
# CONTRIBUTION CONSTANTS
# ============================================================================

class ContributionStatus:
    """Contribution status choices."""
    PENDING = 'pending'
    PAID = 'paid'
    OVERDUE = 'overdue'
    CANCELLED = 'cancelled'
    REFUNDED = 'refunded'
    PARTIALLY_PAID = 'partially_paid'
    WAIVED = 'waived'

    CHOICES: List[Tuple[str, str]] = [
        (PENDING, _('Pending')),
        (PAID, _('Paid')),
        (OVERDUE, _('Overdue')),
        (CANCELLED, _('Cancelled')),
        (REFUNDED, _('Refunded')),
        (PARTIALLY_PAID, _('Partially Paid')),
        (WAIVED, _('Waived')),
    ]


class ContributionType:
    """Contribution type choices."""
    REGULAR = 'regular'
    SPECIAL = 'special'
    PENALTY = 'penalty'
    BONUS = 'bonus'
    ADVANCE = 'advance'

    CHOICES: List[Tuple[str, str]] = [
        (REGULAR, _('Regular')),
        (SPECIAL, _('Special')),
        (PENALTY, _('Penalty')),
        (BONUS, _('Bonus')),
        (ADVANCE, _('Advance')),
    ]


# ============================================================================
# PAYMENT CONSTANTS
# ============================================================================

class PaymentStatus:
    """Payment status choices."""
    INITIATED = 'initiated'
    PENDING = 'pending'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    REFUNDED = 'refunded'
    REVERSED = 'reversed'
    EXPIRED = 'expired'

    CHOICES: List[Tuple[str, str]] = [
        (INITIATED, _('Initiated')),
        (PENDING, _('Pending')),
        (PROCESSING, _('Processing')),
        (COMPLETED, _('Completed')),
        (FAILED, _('Failed')),
        (CANCELLED, _('Cancelled')),
        (REFUNDED, _('Refunded')),
        (REVERSED, _('Reversed')),
        (EXPIRED, _('Expired')),
    ]


class PaymentMethod:
    """Payment method choices."""
    TELEBIRR = 'telebirr'
    CHAPA = 'chapa'
    BANK_TRANSFER = 'bank_transfer'
    CASH = 'cash'
    MOBILE_MONEY = 'mobile_money'
    CARD = 'card'

    CHOICES: List[Tuple[str, str]] = [
        (TELEBIRR, _('Telebirr')),
        (CHAPA, _('Chapa')),
        (BANK_TRANSFER, _('Bank Transfer')),
        (CASH, _('Cash')),
        (MOBILE_MONEY, _('Mobile Money')),
        (CARD, _('Card')),
    ]


class PayoutStatus:
    """Payout status choices."""
    PENDING = 'pending'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    PARTIALLY_PAID = 'partially_paid'
    ON_HOLD = 'on_hold'

    CHOICES: List[Tuple[str, str]] = [
        (PENDING, _('Pending')),
        (PROCESSING, _('Processing')),
        (COMPLETED, _('Completed')),
        (FAILED, _('Failed')),
        (CANCELLED, _('Cancelled')),
        (PARTIALLY_PAID, _('Partially Paid')),
        (ON_HOLD, _('On Hold')),
    ]


# ============================================================================
# NOTIFICATION CONSTANTS
# ============================================================================

class NotificationType:
    """Notification type choices."""
    INFO = 'info'
    SUCCESS = 'success'
    WARNING = 'warning'
    ERROR = 'error'
    REMINDER = 'reminder'
    ALERT = 'alert'
    PROMOTION = 'promotion'
    SYSTEM = 'system'
    TRANSACTION = 'transaction'
    GROUP = 'group'
    CONTRIBUTION = 'contribution'
    PAYMENT = 'payment'
    PAYOUT = 'payout'
    VERIFICATION = 'verification'
    SECURITY = 'security'

    CHOICES: List[Tuple[str, str]] = [
        (INFO, _('Info')),
        (SUCCESS, _('Success')),
        (WARNING, _('Warning')),
        (ERROR, _('Error')),
        (REMINDER, _('Reminder')),
        (ALERT, _('Alert')),
        (PROMOTION, _('Promotion')),
        (SYSTEM, _('System')),
        (TRANSACTION, _('Transaction')),
        (GROUP, _('Group')),
        (CONTRIBUTION, _('Contribution')),
        (PAYMENT, _('Payment')),
        (PAYOUT, _('Payout')),
        (VERIFICATION, _('Verification')),
        (SECURITY, _('Security')),
    ]


class NotificationChannel:
    """Notification channel choices."""
    EMAIL = 'email'
    SMS = 'sms'
    PUSH = 'push'
    IN_APP = 'in_app'
    WEBHOOK = 'webhook'

    CHOICES: List[Tuple[str, str]] = [
        (EMAIL, _('Email')),
        (SMS, _('SMS')),
        (PUSH, _('Push Notification')),
        (IN_APP, _('In-App')),
        (WEBHOOK, _('Webhook')),
    ]


class NotificationPriority:
    """Notification priority levels."""
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    URGENT = 'urgent'

    CHOICES: List[Tuple[str, str]] = [
        (LOW, _('Low')),
        (MEDIUM, _('Medium')),
        (HIGH, _('High')),
        (URGENT, _('Urgent')),
    ]


# ============================================================================
# AUDIT CONSTANTS
# ============================================================================

class AuditAction:
    """Audit log action types."""
    CREATE = 'create'
    UPDATE = 'update'
    DELETE = 'delete'
    VIEW = 'view'
    LOGIN = 'login'
    LOGOUT = 'logout'
    REGISTER = 'register'
    VERIFY = 'verify'
    APPROVE = 'approve'
    REJECT = 'reject'
    CANCEL = 'cancel'
    SUSPEND = 'suspend'
    UNSUSPEND = 'unsuspend'
    LOCK = 'lock'
    UNLOCK = 'unlock'
    PAYMENT = 'payment'
    TRANSFER = 'transfer'
    EXPORT = 'export'
    IMPORT = 'import'

    CHOICES: List[Tuple[str, str]] = [
        (CREATE, _('Create')),
        (UPDATE, _('Update')),
        (DELETE, _('Delete')),
        (VIEW, _('View')),
        (LOGIN, _('Login')),
        (LOGOUT, _('Logout')),
        (REGISTER, _('Register')),
        (VERIFY, _('Verify')),
        (APPROVE, _('Approve')),
        (REJECT, _('Reject')),
        (CANCEL, _('Cancel')),
        (SUSPEND, _('Suspend')),
        (UNSUSPEND, _('Unsuspend')),
        (LOCK, _('Lock')),
        (UNLOCK, _('Unlock')),
        (PAYMENT, _('Payment')),
        (TRANSFER, _('Transfer')),
        (EXPORT, _('Export')),
        (IMPORT, _('Import')),
    ]


# ============================================================================
# ERROR CODE CONSTANTS
# ============================================================================

class ErrorCode:
    """Standardized error codes."""
    # Authentication errors (1000-1099)
    INVALID_CREDENTIALS = 'AUTH-1001'
    ACCOUNT_INACTIVE = 'AUTH-1002'
    ACCOUNT_SUSPENDED = 'AUTH-1003'
    ACCOUNT_LOCKED = 'AUTH-1004'
    ACCOUNT_DELETED = 'AUTH-1005'
    TOKEN_EXPIRED = 'AUTH-1006'
    TOKEN_INVALID = 'AUTH-1007'
    TOKEN_MISSING = 'AUTH-1008'
    PERMISSION_DENIED = 'AUTH-1009'

    # Validation errors (2000-2099)
    INVALID_INPUT = 'VAL-2001'
    MISSING_FIELD = 'VAL-2002'
    INVALID_EMAIL = 'VAL-2003'
    INVALID_PHONE = 'VAL-2004'
    INVALID_PASSWORD = 'VAL-2005'
    DUPLICATE_ENTRY = 'VAL-2006'
    INVALID_DATE = 'VAL-2007'
    INVALID_AMOUNT = 'VAL-2008'

    # Resource errors (3000-3099)
    NOT_FOUND = 'RES-3001'
    ALREADY_EXISTS = 'RES-3002'
    CONFLICT = 'RES-3003'
    RESOURCE_LOCKED = 'RES-3004'
    RESOURCE_EXPIRED = 'RES-3005'
    RESOURCE_NOT_AVAILABLE = 'RES-3006'

    # Group errors (4000-4099)
    GROUP_NOT_FOUND = 'GRP-4001'
    GROUP_FULL = 'GRP-4002'
    GROUP_NOT_ACTIVE = 'GRP-4003'
    GROUP_COMPLETED = 'GRP-4004'
    GROUP_CANCELLED = 'GRP-4005'
    NOT_GROUP_MEMBER = 'GRP-4006'
    NOT_GROUP_ADMIN = 'GRP-4007'
    NOT_GROUP_OWNER = 'GRP-4008'

    # Contribution errors (5000-5099)
    CONTRIBUTION_NOT_FOUND = 'CON-5001'
    CONTRIBUTION_ALREADY_PAID = 'CON-5002'
    CONTRIBUTION_OVERDUE = 'CON-5003'
    CONTRIBUTION_NOT_DUE = 'CON-5004'
    CONTRIBUTION_AMOUNT_INVALID = 'CON-5005'

    # Payment errors (6000-6099)
    PAYMENT_NOT_FOUND = 'PAY-6001'
    PAYMENT_FAILED = 'PAY-6002'
    PAYMENT_TIMEOUT = 'PAY-6003'
    PAYMENT_GATEWAY_ERROR = 'PAY-6004'
    PAYMENT_ALREADY_PROCESSED = 'PAY-6005'
    INSUFFICIENT_BALANCE = 'PAY-6006'

    # Server errors (9000-9099)
    INTERNAL_ERROR = 'SVR-9001'
    SERVICE_UNAVAILABLE = 'SVR-9002'
    DATABASE_ERROR = 'SVR-9003'
    THIRD_PARTY_ERROR = 'SVR-9004'

    # OTP errors (7000-7099)
    OTP_EXPIRED = 'OTP-7001'
    OTP_INVALID = 'OTP-7002'
    OTP_TOO_MANY_ATTEMPTS = 'OTP-7003'
    OTP_NOT_VERIFIED = 'OTP-7004'

    # Referral errors (8000-8099)
    REFERRAL_CODE_INVALID = 'REF-8001'
    REFERRAL_CODE_EXPIRED = 'REF-8002'


# ============================================================================
# PLATFORM CONSTANTS
# ============================================================================

class PlatformConfig:
    """Platform-wide configuration constants."""
    # OTP settings
    OTP_LENGTH = 6
    OTP_EXPIRY_SECONDS = 300
    OTP_MAX_ATTEMPTS = 5

    # Password settings
    PASSWORD_MIN_LENGTH = 8
    PASSWORD_MAX_LENGTH = 128

    # Reputation settings
    MIN_REPUTATION = 0
    MAX_REPUTATION = 100
    REPUTATION_INITIAL = 50

    # Group limits
    MIN_GROUP_MEMBERS = 2
    MAX_GROUP_MEMBERS = 100
    DEFAULT_CYCLE_LENGTH = 10

    # Contribution limits
    MIN_CONTRIBUTION_AMOUNT = 10.00
    MAX_CONTRIBUTION_AMOUNT = 1000000.00
    DEFAULT_CONTRIBUTION_AMOUNT = 100.00

    # Fee settings (percentage)
    PLATFORM_FEE_PERCENTAGE = 2.5
    PLATFORM_FEE_MINIMUM = 5.00
    PLATFORM_FEE_MAXIMUM = 500.00

    # Pagination limits
    PAGINATION_DEFAULT_LIMIT = 20
    PAGINATION_MAX_LIMIT = 100

    # File upload limits
    MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
    ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']
    MAX_PROFILE_PICTURE_SIZE = 2 * 1024 * 1024  # 2 MB

    # Cache timeouts (seconds)
    CACHE_DEFAULT_TIMEOUT = 3600  # 1 hour
    CACHE_SHORT_TIMEOUT = 300  # 5 minutes
    CACHE_LONG_TIMEOUT = 86400  # 24 hours
    CACHE_VERY_LONG_TIMEOUT = 604800  # 7 days

    # Session settings
    SESSION_TIMEOUT = 3600  # 1 hour
    SESSION_REMEMBER_TIMEOUT = 604800  # 7 days

    # Lock settings
    ACCOUNT_LOCK_ATTEMPTS = 5
    ACCOUNT_LOCK_DURATION = 30  # minutes
    ACCOUNT_LOCK_INFINITE = False

    # Suspension settings
    INACTIVITY_SUSPENSION_DAYS = 90
    INACTIVITY_DELETION_DAYS = 365

    # Referral settings
    REFERRAL_BONUS_REPUTATION = 10
    REFERRAL_BONUS_AMOUNT = 0.00  # Can be set later

    # Timezone
    DEFAULT_TIMEZONE = 'Africa/Addis_Ababa'
    DEFAULT_CURRENCY = 'ETB'

    # Supported currencies
    SUPPORTED_CURRENCIES = ['ETB', 'USD', 'EUR', 'GBP']

    # Supported languages (same as UserLanguage)
    SUPPORTED_LANGUAGES = ['en', 'am', 'om', 'ti', 'so']


# ============================================================================
# MESSAGE CONSTANTS
# ============================================================================

class Messages:
    """Common success and error messages."""
    # Success messages
    OPERATION_SUCCESS = _('Operation completed successfully.')
    CREATED = _('Resource created successfully.')
    UPDATED = _('Resource updated successfully.')
    DELETED = _('Resource deleted successfully.')
    VERIFIED = _('Verification successful.')
    LOGIN_SUCCESS = _('Login successful.')
    LOGOUT_SUCCESS = _('Logout successful.')
    REGISTRATION_SUCCESS = _('Registration successful.')
    PASSWORD_RESET_SUCCESS = _('Password reset successful.')
    PAYMENT_SUCCESS = _('Payment processed successfully.')
    CONTRIBUTION_SUCCESS = _('Contribution recorded successfully.')

    # Error messages
    OPERATION_FAILED = _('Operation failed. Please try again.')
    NOT_FOUND = _('Resource not found.')
    PERMISSION_DENIED = _('You do not have permission to perform this action.')
    UNAUTHORIZED = _('Authentication required.')
    INVALID_INPUT = _('Invalid input. Please check your data.')
    SERVER_ERROR = _('An internal server error occurred.')

    # User-specific
    USER_NOT_FOUND = _('User not found.')
    USER_ALREADY_EXISTS = _('User already exists.')
    USER_INACTIVE = _('User account is inactive.')
    USER_SUSPENDED = _('User account is suspended.')
    USER_LOCKED = _('User account is locked.')

    # Group-specific
    GROUP_NOT_FOUND = _('Group not found.')
    GROUP_FULL = _('Group is full.')
    GROUP_ALREADY_JOINED = _('Already a member.')
    GROUP_ALREADY_JOINED_ERROR = _('You are already a member of this group.')
    GROUP_NOT_ACTIVE = _('Group is not active.')
    GROUP_NOT_MEMBER = _('You are not a member of this group.')
    GROUP_NOT_ADMIN = _('You are not an admin of this group.')
    GROUP_NOT_OWNER = _('You are not the owner of this group.')

    # Contribution-specific
    CONTRIBUTION_NOT_FOUND = _('Contribution not found.')
    CONTRIBUTION_ALREADY_PAID = _('Contribution already paid.')
    CONTRIBUTION_OVERDUE = _('Contribution is overdue.')
    CONTRIBUTION_NOT_DUE = _('Contribution is not due yet.')

    # Payment-specific
    PAYMENT_NOT_FOUND = _('Payment not found.')
    PAYMENT_FAILED = _('Payment failed. Please try again.')
    PAYMENT_TIMEOUT = _('Payment gateway timeout.')
    PAYMENT_GATEWAY_ERROR = _('Payment gateway error.')

    # OTP-specific
    OTP_EXPIRED = _('OTP has expired. Please request a new one.')
    OTP_INVALID = _('Invalid OTP. Please try again.')
    OTP_TOO_MANY_ATTEMPTS = _('Too many failed attempts. Please request a new OTP.')
    OTP_NOT_VERIFIED = _('OTP not verified.')


# ============================================================================
# REGULAR EXPRESSION CONSTANTS
# ============================================================================

class RegexPatterns:
    """Common regular expression patterns."""
    PHONE_INTERNATIONAL = r'^\+?[1-9]\d{9,14}$'
    PHONE_ETHIOPIA = r'^\+251[1-9]\d{8}$'
    EMAIL_SIMPLE = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    EMAIL_STRICT = r'^[a-zA-Z0-9!#$%&\'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&\'*+/=?^_`{|}~-]+)*@(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$'
    PASSWORD_STRONG = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$'
    CURRENCY = r'^[A-Z]{3}$'
    PERCENTAGE = r'^[0-9]{1,3}(\.[0-9]{1,2})?$'
    REFERRAL_CODE = r'^[A-Z0-9]{6,12}$'
    UUID = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    SLUG = r'^[a-z0-9]+(?:-[a-z0-9]+)*$'
    ALPHANUMERIC = r'^[a-zA-Z0-9]+$'
    ALPHANUMERIC_UNDERSCORE = r'^[a-zA-Z0-9_]+$'
    URL = r'^https?://[^\s/$.?#].[^\s]*$'


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'UserStatus',
    'UserVerificationLevel',
    'UserRole',
    'UserGender',
    'UserLanguage',
    'UserDeviceType',
    'GroupStatus',
    'GroupMemberRole',
    'GroupType',
    'GroupFrequency',
    'GroupWinnerSelection',
    'GroupInvitationStatus',
    'ContributionStatus',
    'ContributionType',
    'PaymentStatus',
    'PaymentMethod',
    'PayoutStatus',
    'NotificationType',
    'NotificationChannel',
    'NotificationPriority',
    'AuditAction',
    'ErrorCode',
    'PlatformConfig',
    'Messages',
    'RegexPatterns',
]