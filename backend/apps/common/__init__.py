"""
Common utilities and shared components for the Digital Ekub Platform.

This package provides reusable functionality used across multiple apps:
- Custom exception classes
- Shared permission classes
- Pagination helpers
- Utility functions
- Validators
- Constants

All shared components should be imported from this package for consistency.
"""

__version__ = '1.0.0'

# Expose commonly used utilities
from .exceptions import (
    CustomAPIException,
    ValidationError,
    NotFoundError,
    PermissionDeniedError,
    ConflictError,
    ServiceUnavailableError,
    BadRequestError,
    InternalServerError
)

from .permissions import (
    IsAdminUser,
    IsSuperAdminUser,
    IsActiveUser,
    IsVerifiedUser,
    IsOwnerOrAdmin,
    IsOwnerOrReadOnly,
    IsGroupAdmin,
    IsGroupMember,
    IsGroupOwner,
    IsActiveAndVerified,
    IsPhoneVerifiedUser,
    IsEmailVerifiedUser
)

from .pagination import (
    CustomPagination,
    StandardPagination,
    LargePagination,
    SmallPagination
)

from .utils import (
    generate_otp,
    send_otp_email,
    send_otp_sms,
    send_email,
    send_sms,
    generate_referral_code,
    validate_phone_number,
    validate_email,
    sanitize_input,
    format_currency,
    calculate_platform_fee,
    get_client_ip,
    get_user_agent,
    truncate_text,
    slugify,
    generate_random_string,
    is_valid_uuid,
    parse_date_range,
    get_date_range,
    calculate_percentage,
    format_datetime,
    parse_datetime
)

from .validators import (
    PhoneNumberValidator,
    EmailValidator,
    StrongPasswordValidator,
    NumericValidator,
    DateValidator,
    DateTimeValidator,
    CurrencyValidator,
    PercentageValidator,
    FileSizeValidator,
    FileExtensionValidator,
    ImageValidator
)

from .constants import (
    OTP_LENGTH,
    OTP_EXPIRY_SECONDS,
    MAX_OTP_ATTEMPTS,
    MINIMUM_REPUTATION,
    MAX_REPUTATION,
    PLATFORM_FEE_PERCENTAGE,
    DEFAULT_CONTRIBUTION_AMOUNT,
    DEFAULT_CYCLE_LENGTH,
    MAX_GROUP_MEMBERS,
    MIN_GROUP_MEMBERS,
    DEFAULT_TIMEZONE,
    SUPPORTED_LANGUAGES,
    SUPPORTED_CURRENCIES,
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_SIZE,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    USER_STATUS_CHOICES,
    GROUP_STATUS_CHOICES,
    CONTRIBUTION_STATUS_CHOICES,
    PAYMENT_STATUS_CHOICES,
    NOTIFICATION_TYPES,
    EVENT_TYPES
)

__all__ = [
    # Exceptions
    'CustomAPIException',
    'ValidationError',
    'NotFoundError',
    'PermissionDeniedError',
    'ConflictError',
    'ServiceUnavailableError',
    'BadRequestError',
    'InternalServerError',

    # Permissions
    'IsAdminUser',
    'IsSuperAdminUser',
    'IsActiveUser',
    'IsVerifiedUser',
    'IsOwnerOrAdmin',
    'IsOwnerOrReadOnly',
    'IsGroupAdmin',
    'IsGroupMember',
    'IsGroupOwner',
    'IsActiveAndVerified',
    'IsPhoneVerifiedUser',
    'IsEmailVerifiedUser',

    # Pagination
    'CustomPagination',
    'StandardPagination',
    'LargePagination',
    'SmallPagination',

    # Utilities
    'generate_otp',
    'send_otp_email',
    'send_otp_sms',
    'send_email',
    'send_sms',
    'generate_referral_code',
    'validate_phone_number',
    'validate_email',
    'sanitize_input',
    'format_currency',
    'calculate_platform_fee',
    'get_client_ip',
    'get_user_agent',
    'truncate_text',
    'slugify',
    'generate_random_string',
    'is_valid_uuid',
    'parse_date_range',
    'get_date_range',
    'calculate_percentage',
    'format_datetime',
    'parse_datetime',

    # Validators
    'PhoneNumberValidator',
    'EmailValidator',
    'StrongPasswordValidator',
    'NumericValidator',
    'DateValidator',
    'DateTimeValidator',
    'CurrencyValidator',
    'PercentageValidator',
    'FileSizeValidator',
    'FileExtensionValidator',
    'ImageValidator',

    # Constants
    'OTP_LENGTH',
    'OTP_EXPIRY_SECONDS',
    'MAX_OTP_ATTEMPTS',
    'MINIMUM_REPUTATION',
    'MAX_REPUTATION',
    'PLATFORM_FEE_PERCENTAGE',
    'DEFAULT_CONTRIBUTION_AMOUNT',
    'DEFAULT_CYCLE_LENGTH',
    'MAX_GROUP_MEMBERS',
    'MIN_GROUP_MEMBERS',
    'DEFAULT_TIMEZONE',
    'SUPPORTED_LANGUAGES',
    'SUPPORTED_CURRENCIES',
    'ALLOWED_IMAGE_TYPES',
    'MAX_IMAGE_SIZE',
    'PAGINATION_DEFAULT_LIMIT',
    'PAGINATION_MAX_LIMIT',
    'USER_STATUS_CHOICES',
    'GROUP_STATUS_CHOICES',
    'CONTRIBUTION_STATUS_CHOICES',
    'PAYMENT_STATUS_CHOICES',
    'NOTIFICATION_TYPES',
    'EVENT_TYPES',
]

__docformat__ = 'restructuredtext en'