"""
Custom validators for the Digital Ekub Platform.

This module provides reusable validation classes and functions for:
- Phone number validation (international format)
- Email validation with MX record check
- Password strength validation with multiple rules
- Numeric range validations
- Date and time validations
- File size and extension validations
- Image validation (dimensions, format)
- Domain-specific validations (referral codes, currency, percentage)
- Combined/composite validators
"""

import re
import os
import uuid
import math
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional, List, Tuple, Any, Union, Dict, Callable
from functools import wraps

from django.core.exceptions import ValidationError
from django.core.validators import (
    RegexValidator,
    EmailValidator,
    MinValueValidator,
    MaxValueValidator,
    MinLengthValidator,
    MaxLengthValidator,
    FileExtensionValidator,
    FileSizeValidator,
)
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

# Phone number patterns
PHONE_PATTERN = r'^\+?[1-9]\d{9,14}$'
PHONE_PATTERN_ETHIOPIA = r'^\+251[1-9]\d{8}$'
PHONE_PATTERN_WITHOUT_COUNTRY = r'^[1-9]\d{9,14}$'

# Email patterns
EMAIL_PATTERN_SIMPLE = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
EMAIL_PATTERN_STRICT = r'^[a-zA-Z0-9!#$%&\'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&\'*+/=?^_`{|}~-]+)*@(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$'

# Password patterns
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# Currency patterns
CURRENCY_PATTERN = r'^[A-Z]{3}$'

# Percentage patterns
PERCENTAGE_PATTERN = r'^[0-9]{1,3}(\.[0-9]{1,2})?$'

# Referral code patterns
REFERRAL_CODE_PATTERN = r'^[A-Z0-9]{6,12}$'

# UUID pattern
UUID_PATTERN = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'


# ============================================================================
# PHONE NUMBER VALIDATORS
# ============================================================================

class PhoneNumberValidator(RegexValidator):
    """
    Validate international phone numbers.

    Requires format: +[country_code][number], e.g., +251912345678
    Minimum 10 digits, maximum 15 digits.
    """
    regex = re.compile(PHONE_PATTERN)
    message = _(
        'Phone number must be in international format: +[country_code][number]. '
        'Example: +251912345678'
    )
    code = 'invalid_phone_number'

    def __init__(self, country_code: Optional[str] = None, **kwargs):
        self.country_code = country_code
        super().__init__(**kwargs)

    def __call__(self, value):
        if self.country_code and not value.startswith(f'+{self.country_code}'):
            raise ValidationError(
                _('Phone number must start with country code +{country_code}.').format(
                    country_code=self.country_code
                ),
                code='invalid_country_code'
            )
        super().__call__(value)


class EthiopianPhoneNumberValidator(PhoneNumberValidator):
    """Validate Ethiopian phone numbers starting with +251."""
    regex = re.compile(PHONE_PATTERN_ETHIOPIA)
    message = _('Phone number must be a valid Ethiopian number: +251XXXXXXXXX')
    code = 'invalid_ethiopian_phone_number'

    def __init__(self, **kwargs):
        super().__init__(country_code='251', **kwargs)


class PhoneNumberOptionalValidator(PhoneNumberValidator):
    """Allow empty phone number but validate if provided."""
    def __call__(self, value):
        if not value:
            return
        super().__call__(value)


# ============================================================================
# EMAIL VALIDATORS
# ============================================================================

class EmailValidatorCustom(EmailValidator):
    """
    Enhanced email validator with additional checks.
    """
    message = _('Enter a valid email address.')
    code = 'invalid_email'
    user_regex = re.compile(
        r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$",
        re.IGNORECASE
    )

    def __init__(self, check_mx: bool = False, **kwargs):
        self.check_mx = check_mx
        super().__init__(**kwargs)

    def __call__(self, value):
        super().__call__(value)
        if self.check_mx:
            from django.core.validators import validate_email
            try:
                validate_email(value)
            except ValidationError:
                raise ValidationError(
                    _('Invalid email domain. Please check the email address.'),
                    code='invalid_email_domain'
                )


class EmailOptionalValidator(EmailValidatorCustom):
    """Allow empty email but validate if provided."""
    def __call__(self, value):
        if not value:
            return
        super().__call__(value)


# ============================================================================
# PASSWORD VALIDATORS
# ============================================================================

class StrongPasswordValidator:
    """
    Validate password strength with multiple rules.

    Rules:
    - Minimum length (default: 8)
    - Maximum length (default: 128)
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    - No common passwords
    - No personal information (username, email, etc.)
    """
    message = _('Password is not strong enough.')
    code = 'password_too_weak'

    def __init__(
        self,
        min_length: int = PASSWORD_MIN_LENGTH,
        max_length: int = PASSWORD_MAX_LENGTH,
        require_uppercase: bool = True,
        require_lowercase: bool = True,
        require_digit: bool = True,
        require_special: bool = True,
        forbidden_words: Optional[List[str]] = None,
        check_personal_info: bool = False,
    ):
        self.min_length = min_length
        self.max_length = max_length
        self.require_uppercase = require_uppercase
        self.require_lowercase = require_lowercase
        self.require_digit = require_digit
        self.require_special = require_special
        self.forbidden_words = forbidden_words or []
        self.check_personal_info = check_personal_info

    def __call__(self, value, user=None):
        errors = []

        # Check length
        if len(value) < self.min_length:
            errors.append(_('Password must be at least {min_length} characters.').format(
                min_length=self.min_length
            ))
        if len(value) > self.max_length:
            errors.append(_('Password must not exceed {max_length} characters.').format(
                max_length=self.max_length
            ))

        # Check uppercase
        if self.require_uppercase and not any(c.isupper() for c in value):
            errors.append(_('Password must contain at least one uppercase letter.'))

        # Check lowercase
        if self.require_lowercase and not any(c.islower() for c in value):
            errors.append(_('Password must contain at least one lowercase letter.'))

        # Check digit
        if self.require_digit and not any(c.isdigit() for c in value):
            errors.append(_('Password must contain at least one digit.'))

        # Check special character
        if self.require_special and not any(c in '!@#$%^&*()_+-=[]{};:,.<>?/~' for c in value):
            errors.append(_('Password must contain at least one special character.'))

        # Check forbidden words
        if self.forbidden_words:
            lower_value = value.lower()
            for word in self.forbidden_words:
                if word.lower() in lower_value:
                    errors.append(_('Password contains forbidden word: {word}.').format(
                        word=word
                    ))

        # Check personal information
        if self.check_personal_info and user:
            personal_info = [
                str(user.username),
                str(user.email),
                str(user.first_name),
                str(user.last_name),
                str(user.phone),
            ]
            lower_value = value.lower()
            for info in personal_info:
                if info and info.lower() in lower_value:
                    errors.append(_('Password contains personal information.'))

        if errors:
            raise ValidationError(errors, code=self.code)

    def validate(self, password, user=None):
        self.__call__(password, user)


class PasswordNotCommonValidator:
    """
    Validate that password is not in the list of common passwords.
    """
    message = _('This password is too common. Please choose a stronger password.')
    code = 'password_common'

    # Top 100 most common passwords
    COMMON_PASSWORDS = {
        'password', '123456', '12345678', 'qwerty', 'abc123', 'monkey', '1234567',
        'letmein', 'dragon', '111111', 'baseball', 'iloveyou', 'trustno1', 'sunshine',
        'master', '123123', 'welcome', 'shadow', 'ashley', 'football', 'jesus', 'michael',
        'ninja', 'mustang', 'password1', '123456789', '1234567890', 'qwertyuiop',
        'qwerty123', 'admin', 'admin123', 'root', 'toor', '1234', '12345', '654321',
        '11111111', '222222', '333333', '444444', '555555', '666666', '777777', '888888',
        '999999', '000000', 'abcdef', 'abcd1234', 'passw0rd', 'p@ssw0rd', 'P@ssw0rd',
        'changeme', 'default', 'secret', 'hello', 'world', 'summer', 'winter', 'spring',
        'autumn', 'fall', 'soccer', 'hockey', 'basketball', 'tennis', 'golf', 'swimming',
        'running', 'jogging', 'walking', 'cycling', 'fishing', 'hunting', 'camping',
        'travel', 'vacation', 'holiday', 'birthday', 'anniversary', 'wedding',
        'honeymoon', 'family', 'friend', 'love', 'happy', 'smile', 'laugh', 'cry',
        'sad', 'angry', 'excited', 'tired', 'hungry', 'thirsty', 'sleep', 'dream',
        'music', 'movie', 'book', 'read', 'write', 'code', 'program', 'python',
        'django', 'flask', 'react', 'vue', 'angular', 'javascript', 'typescript',
    }

    def __call__(self, value):
        if value.lower() in self.COMMON_PASSWORDS:
            raise ValidationError(self.message, code=self.code)


class PasswordNotUsernameValidator:
    """
    Validate that password is not same as or similar to username/email.
    """
    message = _('Password is too similar to your username or email.')
    code = 'password_similar_to_username'

    def __init__(self, user_field: str = 'username'):
        self.user_field = user_field

    def __call__(self, value, user=None):
        if user is None:
            return

        username = getattr(user, self.user_field, None)
        email = getattr(user, 'email', None)

        if username and (value.lower() == username.lower() or username.lower() in value.lower()):
            raise ValidationError(self.message, code=self.code)

        if email and (value.lower() == email.lower() or email.lower().split('@')[0] in value.lower()):
            raise ValidationError(self.message, code=self.code)


# ============================================================================
# NUMERIC VALIDATORS
# ============================================================================

class MinValueValidatorCustom(MinValueValidator):
    """Enhanced min value validator with custom message."""
    message = _('Value must be at least {limit_value}.')

    def __init__(self, limit_value: Union[int, float, Decimal], message: Optional[str] = None, **kwargs):
        super().__init__(limit_value, **kwargs)
        if message:
            self.message = message


class MaxValueValidatorCustom(MaxValueValidator):
    """Enhanced max value validator with custom message."""
    message = _('Value must be at most {limit_value}.')

    def __init__(self, limit_value: Union[int, float, Decimal], message: Optional[str] = None, **kwargs):
        super().__init__(limit_value, **kwargs)
        if message:
            self.message = message


class RangeValidator:
    """
    Validate that value is within a range.
    """
    message_min = _('Value must be at least {min_value}.')
    message_max = _('Value must be at most {max_value}.')
    message_range = _('Value must be between {min_value} and {max_value}.')

    def __init__(
        self,
        min_value: Optional[Union[int, float, Decimal]] = None,
        max_value: Optional[Union[int, float, Decimal]] = None,
        min_message: Optional[str] = None,
        max_message: Optional[str] = None,
        range_message: Optional[str] = None,
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.min_message = min_message or self.message_min
        self.max_message = max_message or self.message_max
        self.range_message = range_message or self.message_range

    def __call__(self, value):
        if self.min_value is not None and value < self.min_value:
            raise ValidationError(
                self.min_message.format(min_value=self.min_value),
                code='min_value'
            )
        if self.max_value is not None and value > self.max_value:
            raise ValidationError(
                self.max_message.format(max_value=self.max_value),
                code='max_value'
            )
        if self.min_value is not None and self.max_value is not None:
            if value < self.min_value or value > self.max_value:
                raise ValidationError(
                    self.range_message.format(
                        min_value=self.min_value,
                        max_value=self.max_value
                    ),
                    code='range'
                )


class PositiveNumberValidator:
    """Validate that value is a positive number."""
    message = _('Value must be a positive number.')
    code = 'positive_number'

    def __call__(self, value):
        if value <= 0:
            raise ValidationError(self.message, code=self.code)


class NonNegativeNumberValidator:
    """Validate that value is a non-negative number."""
    message = _('Value must be a non-negative number (zero or greater).')
    code = 'non_negative_number'

    def __call__(self, value):
        if value < 0:
            raise ValidationError(self.message, code=self.code)


# ============================================================================
# DATE AND TIME VALIDATORS
# ============================================================================

class DateValidator:
    """
    Validate date values with optional range constraints.
    """
    message_future = _('Date cannot be in the future.')
    message_past = _('Date cannot be in the past.')
    message_range = _('Date must be between {start_date} and {end_date}.')

    def __init__(
        self,
        allow_future: bool = True,
        allow_past: bool = True,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None,
        future_message: Optional[str] = None,
        past_message: Optional[str] = None,
        range_message: Optional[str] = None,
    ):
        self.allow_future = allow_future
        self.allow_past = allow_past
        self.min_date = min_date
        self.max_date = max_date
        self.future_message = future_message or self.message_future
        self.past_message = past_message or self.message_past
        self.range_message = range_message or self.message_range

    def __call__(self, value):
        if not isinstance(value, (date, datetime)):
            return

        if isinstance(value, datetime):
            value = value.date()

        today = date.today()

        if not self.allow_future and value > today:
            raise ValidationError(self.future_message, code='future_date')

        if not self.allow_past and value < today:
            raise ValidationError(self.past_message, code='past_date')

        if self.min_date and value < self.min_date:
            raise ValidationError(
                self.range_message.format(
                    start_date=self.min_date.isoformat(),
                    end_date=self.max_date.isoformat() if self.max_date else 'indefinite'
                ),
                code='min_date'
            )

        if self.max_date and value > self.max_date:
            raise ValidationError(
                self.range_message.format(
                    start_date=self.min_date.isoformat() if self.min_date else 'indefinite',
                    end_date=self.max_date.isoformat()
                ),
                code='max_date'
            )


class DateTimeValidator(DateValidator):
    """
    Validate datetime values with optional range constraints.
    """
    def __call__(self, value):
        if not isinstance(value, datetime):
            return

        now = timezone.now()

        if not self.allow_future and value > now:
            raise ValidationError(self.future_message, code='future_datetime')

        if not self.allow_past and value < now:
            raise ValidationError(self.past_message, code='past_datetime')

        if self.min_date and value < self.min_date:
            raise ValidationError(
                self.range_message.format(
                    start_date=self.min_date.isoformat(),
                    end_date=self.max_date.isoformat() if self.max_date else 'indefinite'
                ),
                code='min_datetime'
            )

        if self.max_date and value > self.max_date:
            raise ValidationError(
                self.range_message.format(
                    start_date=self.min_date.isoformat() if self.min_date else 'indefinite',
                    end_date=self.max_date.isoformat()
                ),
                code='max_datetime'
            )


class AgeValidator:
    """
    Validate age based on date of birth.
    """
    message_min = _('Age must be at least {min_age} years.')
    message_max = _('Age must be at most {max_age} years.')
    message_range = _('Age must be between {min_age} and {max_age} years.')

    def __init__(
        self,
        min_age: Optional[int] = None,
        max_age: Optional[int] = None,
        min_message: Optional[str] = None,
        max_message: Optional[str] = None,
        range_message: Optional[str] = None,
    ):
        self.min_age = min_age
        self.max_age = max_age
        self.min_message = min_message or self.message_min
        self.max_message = max_message or self.message_max
        self.range_message = range_message or self.message_range

    def __call__(self, value):
        if not isinstance(value, (date, datetime)):
            return

        if isinstance(value, datetime):
            value = value.date()

        today = date.today()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))

        if self.min_age is not None and age < self.min_age:
            raise ValidationError(
                self.min_message.format(min_age=self.min_age),
                code='min_age'
            )

        if self.max_age is not None and age > self.max_age:
            raise ValidationError(
                self.max_message.format(max_age=self.max_age),
                code='max_age'
            )

        if self.min_age is not None and self.max_age is not None:
            if age < self.min_age or age > self.max_age:
                raise ValidationError(
                    self.range_message.format(
                        min_age=self.min_age,
                        max_age=self.max_age
                    ),
                    code='age_range'
                )


# ============================================================================
# FILE VALIDATORS
# ============================================================================

class FileSizeValidatorCustom(FileSizeValidator):
    """
    Enhanced file size validator with custom message.
    """
    message = _('File size exceeds maximum allowed size of {max_size} MB.')
    code = 'file_too_large'

    def __init__(self, max_size: int, message: Optional[str] = None, **kwargs):
        self.max_size = max_size
        self.max_size_mb = max_size / (1024 * 1024)
        super().__init__(max_size, **kwargs)
        if message:
            self.message = message

    def __call__(self, value):
        if value.size > self.max_size:
            raise ValidationError(
                self.message.format(max_size=self.max_size_mb),
                code=self.code
            )


class FileExtensionValidatorCustom(FileExtensionValidator):
    """
    Enhanced file extension validator with custom message.
    """
    message = _('File extension "{extension}" is not allowed. Allowed extensions: {allowed_extensions}.')
    code = 'invalid_file_extension'

    def __init__(self, allowed_extensions: List[str], message: Optional[str] = None, **kwargs):
        self.allowed_extensions = allowed_extensions
        super().__init__(allowed_extensions, **kwargs)
        if message:
            self.message = message

    def __call__(self, value):
        ext = os.path.splitext(value.name)[1][1:].lower()
        if ext not in self.allowed_extensions:
            raise ValidationError(
                self.message.format(
                    extension=ext,
                    allowed_extensions=', '.join(self.allowed_extensions)
                ),
                code=self.code
            )


class ImageValidator:
    """
    Combined validator for image files.
    Checks: size, extension, dimensions, format.
    """
    def __init__(
        self,
        max_size: Optional[int] = None,
        allowed_extensions: Optional[List[str]] = None,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        min_width: Optional[int] = None,
        min_height: Optional[int] = None,
        allowed_formats: Optional[List[str]] = None,
    ):
        self.max_size = max_size or settings.MAX_IMAGE_SIZE
        self.allowed_extensions = allowed_extensions or settings.ALLOWED_IMAGE_EXTENSIONS
        self.max_width = max_width
        self.max_height = max_height
        self.min_width = min_width
        self.min_height = min_height
        self.allowed_formats = allowed_formats or ['JPEG', 'PNG', 'GIF']

    def __call__(self, value):
        from PIL import Image
        import io

        # Check size
        if value.size > self.max_size:
            raise ValidationError(
                _('Image size exceeds maximum allowed size of {max_size} MB.').format(
                    max_size=self.max_size / (1024 * 1024)
                ),
                code='image_too_large'
            )

        # Check extension
        ext = os.path.splitext(value.name)[1][1:].lower()
        if ext not in self.allowed_extensions:
            raise ValidationError(
                _('Image extension "{extension}" is not allowed. Allowed: {allowed}.').format(
                    extension=ext,
                    allowed=', '.join(self.allowed_extensions)
                ),
                code='invalid_image_extension'
            )

        # Check dimensions and format
        try:
            value.seek(0)
            img = Image.open(value)
            width, height = img.size
            img_format = img.format

            # Check format
            if self.allowed_formats and img_format not in self.allowed_formats:
                raise ValidationError(
                    _('Image format "{format}" is not allowed. Allowed: {allowed}.').format(
                        format=img_format,
                        allowed=', '.join(self.allowed_formats)
                    ),
                    code='invalid_image_format'
                )

            # Check dimensions
            if self.max_width and width > self.max_width:
                raise ValidationError(
                    _('Image width exceeds maximum of {max_width}px.').format(
                        max_width=self.max_width
                    ),
                    code='image_width_too_large'
                )

            if self.max_height and height > self.max_height:
                raise ValidationError(
                    _('Image height exceeds maximum of {max_height}px.').format(
                        max_height=self.max_height
                    ),
                    code='image_height_too_large'
                )

            if self.min_width and width < self.min_width:
                raise ValidationError(
                    _('Image width is below minimum of {min_width}px.').format(
                        min_width=self.min_width
                    ),
                    code='image_width_too_small'
                )

            if self.min_height and height < self.min_height:
                raise ValidationError(
                    _('Image height is below minimum of {min_height}px.').format(
                        min_height=self.min_height
                    ),
                    code='image_height_too_small'
                )

        except Exception as e:
            raise ValidationError(
                _('Invalid image file: {error}').format(error=str(e)),
                code='invalid_image'
            )


# ============================================================================
# DOMAIN-SPECIFIC VALIDATORS
# ============================================================================

class CurrencyValidator(RegexValidator):
    """
    Validate currency code (ISO 4217).
    """
    regex = re.compile(CURRENCY_PATTERN)
    message = _('Currency must be a valid ISO 4217 currency code (e.g., ETB, USD).')
    code = 'invalid_currency'


class PercentageValidator(RangeValidator):
    """
    Validate percentage values (0-100).
    """
    def __init__(self, min_value: Optional[Union[int, float]] = None, max_value: Optional[Union[int, float]] = None):
        min_val = min_value if min_value is not None else 0
        max_val = max_value if max_value is not None else 100
        super().__init__(
            min_value=min_val,
            max_value=max_val,
            range_message=_('Percentage must be between {min_value}% and {max_value}%.')
        )


class ReferralCodeValidator(RegexValidator):
    """
    Validate referral code format.
    """
    regex = re.compile(REFERRAL_CODE_PATTERN)
    message = _('Referral code must be 6-12 alphanumeric characters (uppercase).')
    code = 'invalid_referral_code'


class UUIDValidator(RegexValidator):
    """
    Validate UUID format.
    """
    regex = re.compile(UUID_PATTERN, re.IGNORECASE)
    message = _('Invalid UUID format.')
    code = 'invalid_uuid'


class URLValidator:
    """
    Validate URL format with optional protocol and domain checks.
    """
    message = _('Invalid URL format.')
    code = 'invalid_url'

    def __init__(
        self,
        require_https: bool = False,
        allowed_domains: Optional[List[str]] = None,
        require_valid_domain: bool = False,
    ):
        self.require_https = require_https
        self.allowed_domains = allowed_domains
        self.require_valid_domain = require_valid_domain

    def __call__(self, value):
        from urllib.parse import urlparse

        try:
            parsed = urlparse(value)
            if not parsed.scheme or not parsed.netloc:
                raise ValidationError(self.message, code=self.code)

            if self.require_https and parsed.scheme != 'https':
                raise ValidationError(
                    _('URL must use HTTPS protocol.'),
                    code='https_required'
                )

            if self.allowed_domains:
                domain = parsed.netloc.lower()
                allowed = [d.lower() for d in self.allowed_domains]
                if not any(domain == d or domain.endswith(f'.{d}') for d in allowed):
                    raise ValidationError(
                        _('Domain "{domain}" is not allowed. Allowed: {allowed}.').format(
                            domain=domain,
                            allowed=', '.join(self.allowed_domains)
                        ),
                        code='domain_not_allowed'
                    )

        except Exception:
            raise ValidationError(self.message, code=self.code)


# ============================================================================
# COMBINED AND UTILITY VALIDATORS
# ============================================================================

class CompositeValidator:
    """
    Combine multiple validators and run them in sequence.
    """
    def __init__(self, *validators):
        self.validators = validators

    def __call__(self, value):
        errors = []
        for validator in self.validators:
            try:
                validator(value)
            except ValidationError as e:
                if hasattr(e, 'messages'):
                    errors.extend(e.messages)
                else:
                    errors.append(str(e))
        if errors:
            raise ValidationError(errors)


class ConditionalValidator:
    """
    Run validators only if condition is met.
    """
    def __init__(self, condition: Callable, *validators):
        self.condition = condition
        self.validators = validators

    def __call__(self, value, **kwargs):
        if self.condition(value, **kwargs):
            for validator in self.validators:
                validator(value)


def validate_or_none(validator):
    """
    Decorator that allows None/empty values to pass validation.
    """
    def wrapper(value, *args, **kwargs):
        if value is None or value == '':
            return
        return validator(value, *args, **kwargs)
    return wrapper


def validate_many(validators, value):
    """
    Run multiple validators and collect all errors.
    """
    errors = []
    for validator in validators:
        try:
            validator(value)
        except ValidationError as e:
            if hasattr(e, 'messages'):
                errors.extend(e.messages)
            else:
                errors.append(str(e))
    if errors:
        raise ValidationError(errors)


# ============================================================================
# VALIDATOR FACTORIES
# ============================================================================

def create_phone_validator(country_code: Optional[str] = None) -> PhoneNumberValidator:
    """Create a phone number validator for a specific country."""
    return PhoneNumberValidator(country_code=country_code)


def create_password_validator(**kwargs) -> StrongPasswordValidator:
    """Create a password validator with custom rules."""
    return StrongPasswordValidator(**kwargs)


def create_range_validator(min_val: Any = None, max_val: Any = None, **kwargs) -> RangeValidator:
    """Create a range validator with optional min and max values."""
    return RangeValidator(min_value=min_val, max_value=max_val, **kwargs)


def create_image_validator(**kwargs) -> ImageValidator:
    """Create an image validator with custom settings."""
    return ImageValidator(**kwargs)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Phone validators
    'PhoneNumberValidator',
    'EthiopianPhoneNumberValidator',
    'PhoneNumberOptionalValidator',

    # Email validators
    'EmailValidatorCustom',
    'EmailOptionalValidator',

    # Password validators
    'StrongPasswordValidator',
    'PasswordNotCommonValidator',
    'PasswordNotUsernameValidator',

    # Numeric validators
    'MinValueValidatorCustom',
    'MaxValueValidatorCustom',
    'RangeValidator',
    'PositiveNumberValidator',
    'NonNegativeNumberValidator',

    # Date validators
    'DateValidator',
    'DateTimeValidator',
    'AgeValidator',

    # File validators
    'FileSizeValidatorCustom',
    'FileExtensionValidatorCustom',
    'ImageValidator',

    # Domain validators
    'CurrencyValidator',
    'PercentageValidator',
    'ReferralCodeValidator',
    'UUIDValidator',
    'URLValidator',

    # Combined validators
    'CompositeValidator',
    'ConditionalValidator',
    'validate_or_none',
    'validate_many',

    # Factories
    'create_phone_validator',
    'create_password_validator',
    'create_range_validator',
    'create_image_validator',

    # Constants
    'PHONE_PATTERN',
    'PHONE_PATTERN_ETHIOPIA',
    'EMAIL_PATTERN_SIMPLE',
    'EMAIL_PATTERN_STRICT',
    'PASSWORD_MIN_LENGTH',
    'PASSWORD_MAX_LENGTH',
    'CURRENCY_PATTERN',
    'PERCENTAGE_PATTERN',
    'REFERRAL_CODE_PATTERN',
    'UUID_PATTERN',
]