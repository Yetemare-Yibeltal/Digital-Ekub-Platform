"""
Utility functions for the Digital Ekub Platform.

This module provides reusable helper functions for various tasks:
- OTP generation and delivery
- Email and SMS sending
- Referral code generation
- Phone/email validation
- Currency formatting and platform fee calculation
- IP address and user agent extraction
- String and text utilities
- Date and time helpers
- File validation
- Random generation
- Security utilities
"""

import re
import os
import random
import string
import hashlib
import hmac
import base64
import json
import uuid
import math
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any, List, Union, Tuple, Callable
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse, parse_qs
from functools import wraps
import logging

from django.utils import timezone
from django.utils.text import slugify as django_slugify
from django.core.validators import validate_email, ValidationError
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


# ============================================================================
# OTP GENERATION AND DELIVERY
# ============================================================================

def generate_otp(length: int = 6, numeric_only: bool = True) -> str:
    """
    Generate a one-time password (OTP) of specified length.

    Args:
        length: Length of OTP (default: 6)
        numeric_only: If True, generate numeric OTP; else alphanumeric

    Returns:
        str: Generated OTP
    """
    if numeric_only:
        return ''.join(random.choices(string.digits, k=length))
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def generate_otp_with_expiry(
    user_id: int,
    length: int = 6,
    expiry_seconds: int = 300,
    numeric_only: bool = True
) -> Tuple[str, datetime]:
    """
    Generate OTP and store in cache with expiry.

    Args:
        user_id: User ID for cache key
        length: OTP length
        expiry_seconds: Expiry time in seconds
        numeric_only: Whether OTP is numeric only

    Returns:
        Tuple of (otp, expiry_time)
    """
    otp = generate_otp(length, numeric_only)
    expiry_time = timezone.now() + timedelta(seconds=expiry_seconds)
    cache_key = f'otp_{user_id}_{int(timezone.now().timestamp())}'
    cache.set(cache_key, {'otp': otp, 'expiry': expiry_time.isoformat()}, timeout=expiry_seconds)
    return otp, expiry_time


def verify_otp(user_id: int, otp: str, purpose: str = 'login') -> bool:
    """
    Verify OTP from cache.

    Args:
        user_id: User ID
        otp: OTP to verify
        purpose: Purpose of OTP (for cache key differentiation)

    Returns:
        bool: True if OTP is valid and not expired
    """
    # Try all cache keys for this user (last 5 minutes)
    now = timezone.now()
    for key in cache.keys(f'otp_{user_id}_*'):
        data = cache.get(key)
        if data and data.get('otp') == otp:
            expiry = datetime.fromisoformat(data['expiry'])
            if expiry > now:
                cache.delete(key)
                return True
            cache.delete(key)
    return False


def send_otp_email(email: str, otp: str, purpose: str = 'verification') -> bool:
    """
    Send OTP via email.

    Args:
        email: Recipient email
        otp: OTP to send
        purpose: Purpose of OTP

    Returns:
        bool: True if sent successfully
    """
    try:
        subject = f'Your OTP for {purpose} - Ekub Platform'
        html_message = render_to_string('emails/otp.html', {
            'otp': otp,
            'purpose': purpose,
            'expiry': 5,
            'year': timezone.now().year
        })
        plain_message = f'Your OTP for {purpose} is: {otp}. It expires in 5 minutes.'
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            html_message=html_message,
            fail_silently=False
        )
        logger.info(f'OTP email sent to {email} for {purpose}')
        return True
    except Exception as e:
        logger.error(f'Failed to send OTP email to {email}: {str(e)}')
        return False


def send_otp_sms(phone: str, otp: str, purpose: str = 'verification') -> bool:
    """
    Send OTP via SMS using Africa's Talking.

    Args:
        phone: Recipient phone number
        otp: OTP to send
        purpose: Purpose of OTP

    Returns:
        bool: True if sent successfully
    """
    try:
        from africastalking import SMS
        sms = SMS
        message = f'Your OTP for {purpose} on Ekub Platform is: {otp}. It expires in 5 minutes.'
        response = sms.send(message, [phone], sender_id=settings.AFRICASTALKING_SENDER_ID)
        logger.info(f'OTP SMS sent to {phone} for {purpose}: {response}')
        return True
    except Exception as e:
        logger.error(f'Failed to send OTP SMS to {phone}: {str(e)}')
        return False


# ============================================================================
# REFERRAL CODE GENERATION
# ============================================================================

def generate_referral_code(prefix: str = '', length: int = 8) -> str:
    """
    Generate a unique referral code.

    Args:
        prefix: Optional prefix for the code
        length: Length of code (excluding prefix)

    Returns:
        str: Generated referral code
    """
    chars = string.ascii_uppercase + string.digits
    # Avoid ambiguous characters: 0, O, 1, I
    chars = chars.replace('0', '').replace('O', '').replace('1', '').replace('I', '')
    code = ''.join(random.choices(chars, k=length))
    if prefix:
        code = f"{prefix}{code}"
    return code


# ============================================================================
# PHONE AND EMAIL VALIDATION
# ============================================================================

def validate_phone_number(phone: str) -> bool:
    """
    Validate international phone number format.

    Args:
        phone: Phone number to validate

    Returns:
        bool: True if valid
    """
    # Accept + followed by 9-15 digits
    pattern = r'^\+?[1-9]\d{9,14}$'
    return bool(re.match(pattern, phone))


def validate_email_address(email: str) -> bool:
    """
    Validate email address format.

    Args:
        email: Email to validate

    Returns:
        bool: True if valid
    """
    try:
        validate_email(email)
        return True
    except ValidationError:
        return False


def sanitize_input(text: str, allow_newlines: bool = False) -> str:
    """
    Sanitize input text to prevent XSS and other injections.

    Args:
        text: Text to sanitize
        allow_newlines: Whether to preserve newlines

    Returns:
        str: Sanitized text
    """
    if not text:
        return ''
    # Remove HTML tags
    text = re.sub(r'<[^>]*>', '', text)
    # Escape quotes and special characters
    text = text.replace('"', '&quot;').replace("'", '&#39;')
    if not allow_newlines:
        text = text.replace('\n', ' ').replace('\r', ' ')
    return text.strip()


# ============================================================================
# CURRENCY AND FEE CALCULATION
# ============================================================================

def format_currency(amount: Union[int, float, Decimal], currency: str = 'ETB') -> str:
    """
    Format amount as currency string.

    Args:
        amount: Amount to format
        currency: Currency code (default: ETB)

    Returns:
        str: Formatted currency string
    """
    if isinstance(amount, (int, float)):
        amount = Decimal(str(amount))
    amount = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return f"{currency} {amount:,.2f}"


def calculate_platform_fee(amount: Union[int, float, Decimal]) -> Decimal:
    """
    Calculate platform fee based on configured percentage.

    Args:
        amount: Base amount

    Returns:
        Decimal: Calculated fee
    """
    amount = Decimal(str(amount))
    percentage = Decimal(str(settings.PLATFORM_FEE_PERCENTAGE)) / Decimal('100')
    fee = (amount * percentage).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    # Apply minimum and maximum limits
    min_fee = Decimal(str(settings.PLATFORM_FEE_MINIMUM))
    max_fee = Decimal(str(settings.PLATFORM_FEE_MAXIMUM))
    if fee < min_fee:
        fee = min_fee
    elif fee > max_fee:
        fee = max_fee
    return fee


def calculate_net_amount(amount: Union[int, float, Decimal]) -> Decimal:
    """
    Calculate net amount after platform fee.

    Args:
        amount: Gross amount

    Returns:
        Decimal: Net amount after fee deduction
    """
    amount = Decimal(str(amount))
    fee = calculate_platform_fee(amount)
    return (amount - fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ============================================================================
# IP ADDRESS AND USER AGENT HELPERS
# ============================================================================

def get_client_ip(request) -> str:
    """
    Extract client IP address from request.

    Args:
        request: HTTP request object

    Returns:
        str: Client IP address
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_user_agent(request) -> str:
    """
    Extract user agent from request.

    Args:
        request: HTTP request object

    Returns:
        str: User agent string
    """
    return request.META.get('HTTP_USER_AGENT', '')


def get_user_location(ip: str) -> Optional[Dict[str, Any]]:
    """
    Get approximate location from IP address.
    (Uses external API or GeoIP database)

    Args:
        ip: IP address

    Returns:
        Optional dict with location data
    """
    try:
        # Placeholder: use external service or GeoIP
        # For now, return dummy data
        return {
            'country': 'Unknown',
            'city': 'Unknown',
            'region': 'Unknown',
            'latitude': 0.0,
            'longitude': 0.0
        }
    except Exception:
        return None


# ============================================================================
# STRING AND TEXT UTILITIES
# ============================================================================

def truncate_text(text: str, max_length: int = 100, suffix: str = '...') -> str:
    """
    Truncate text to specified length.

    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to append if truncated

    Returns:
        str: Truncated text
    """
    if len(text) <= max_length:
        return text
    return text[:max_length] + suffix


def slugify(text: str) -> str:
    """
    Convert text to slug.

    Args:
        text: Text to slugify

    Returns:
        str: Slugified text
    """
    return django_slugify(text)


def generate_random_string(length: int = 10, include_special: bool = False) -> str:
    """
    Generate a random string.

    Args:
        length: Length of string
        include_special: Whether to include special characters

    Returns:
        str: Random string
    """
    chars = string.ascii_letters + string.digits
    if include_special:
        chars += string.punctuation
    return ''.join(random.choices(chars, k=length))


def is_valid_uuid(uuid_string: str) -> bool:
    """
    Check if string is a valid UUID.

    Args:
        uuid_string: String to check

    Returns:
        bool: True if valid UUID
    """
    try:
        uuid.UUID(uuid_string)
        return True
    except ValueError:
        return False


# ============================================================================
# DATE AND TIME HELPERS
# ============================================================================

def parse_date_range(date_range: str) -> Optional[Tuple[date, date]]:
    """
    Parse common date range strings.

    Args:
        date_range: 'today', 'yesterday', 'week', 'month', 'year', or 'YYYY-MM-DD:YYYY-MM-DD'

    Returns:
        Tuple of (start_date, end_date) or None if invalid
    """
    today = date.today()
    if date_range == 'today':
        return today, today
    elif date_range == 'yesterday':
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    elif date_range == 'week':
        start = today - timedelta(days=today.weekday())
        return start, today
    elif date_range == 'month':
        start = today.replace(day=1)
        return start, today
    elif date_range == 'year':
        start = today.replace(month=1, day=1)
        return start, today
    elif ':' in date_range:
        parts = date_range.split(':')
        if len(parts) == 2:
            try:
                start = datetime.strptime(parts[0], '%Y-%m-%d').date()
                end = datetime.strptime(parts[1], '%Y-%m-%d').date()
                return start, end
            except ValueError:
                return None
    return None


def get_date_range(days: int = 30) -> Tuple[date, date]:
    """
    Get date range from today minus days to today.

    Args:
        days: Number of days to go back

    Returns:
        Tuple of (start_date, end_date)
    """
    end = date.today()
    start = end - timedelta(days=days)
    return start, end


def format_datetime(dt: Optional[datetime], format: str = '%Y-%m-%d %H:%M:%S') -> str:
    """
    Format datetime to string.

    Args:
        dt: Datetime object
        format: Format string

    Returns:
        str: Formatted datetime string
    """
    if dt is None:
        return ''
    return dt.strftime(format)


def parse_datetime(dt_string: str, format: str = '%Y-%m-%d %H:%M:%S') -> Optional[datetime]:
    """
    Parse datetime from string.

    Args:
        dt_string: Datetime string
        format: Format string

    Returns:
        datetime or None if invalid
    """
    try:
        return datetime.strptime(dt_string, format)
    except ValueError:
        return None


def calculate_percentage(value: Union[int, float], total: Union[int, float]) -> Decimal:
    """
    Calculate percentage.

    Args:
        value: Part value
        total: Total value

    Returns:
        Decimal: Percentage
    """
    if total == 0:
        return Decimal('0')
    return Decimal(str((value / total) * 100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ============================================================================
# FILE VALIDATION
# ============================================================================

def validate_file_size(file, max_size: int = 5242880) -> bool:
    """
    Validate file size.

    Args:
        file: File object
        max_size: Maximum size in bytes (default: 5MB)

    Returns:
        bool: True if file size is within limits
    """
    return file.size <= max_size


def validate_file_extension(file, allowed_extensions: List[str]) -> bool:
    """
    Validate file extension.

    Args:
        file: File object
        allowed_extensions: List of allowed extensions (e.g., ['jpg', 'png'])

    Returns:
        bool: True if extension is allowed
    """
    ext = file.name.split('.')[-1].lower()
    return ext in allowed_extensions


def validate_image_file(file) -> bool:
    """
    Validate image file (size and extension).

    Args:
        file: File object

    Returns:
        bool: True if valid image
    """
    allowed = getattr(settings, 'ALLOWED_IMAGE_EXTENSIONS', ['jpg', 'jpeg', 'png', 'gif'])
    max_size = getattr(settings, 'MAX_IMAGE_SIZE', 5242880)
    return validate_file_size(file, max_size) and validate_file_extension(file, allowed)


# ============================================================================
# URL AND PARAMETER HELPERS
# ============================================================================

def build_absolute_url(path: str, request=None, base_url: str = None) -> str:
    """
    Build absolute URL.

    Args:
        path: Relative path (e.g., '/api/v1/users/')
        request: Optional request object to get scheme/host
        base_url: Optional base URL to use

    Returns:
        str: Absolute URL
    """
    if request:
        return request.build_absolute_uri(path)
    if base_url:
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    return path


def extract_query_params(url: str) -> Dict[str, List[str]]:
    """
    Extract query parameters from URL.

    Args:
        url: URL string

    Returns:
        Dict with parameter names and list of values
    """
    parsed = urlparse(url)
    return parse_qs(parsed.query)


# ============================================================================
# SECURITY UTILITIES
# ============================================================================

def generate_secure_token(length: int = 64) -> str:
    """
    Generate a secure random token.

    Args:
        length: Length of token (in bytes before encoding)

    Returns:
        str: URL-safe base64 encoded token
    """
    token = os.urandom(length)
    return base64.urlsafe_b64encode(token).decode('utf-8').rstrip('=')


def hash_string(value: str, salt: Optional[str] = None) -> str:
    """
    Hash a string using SHA-256.

    Args:
        value: String to hash
        salt: Optional salt

    Returns:
        str: Hex digest
    """
    if salt:
        value = f"{salt}{value}"
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def verify_hmac_signature(data: str, signature: str, secret: str) -> bool:
    """
    Verify HMAC signature.

    Args:
        data: Data to verify
        signature: Provided signature
        secret: Secret key

    Returns:
        bool: True if signature is valid
    """
    expected = hmac.new(secret.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def generate_hmac_signature(data: str, secret: str) -> str:
    """
    Generate HMAC signature.

    Args:
        data: Data to sign
        secret: Secret key

    Returns:
        str: HMAC signature
    """
    return hmac.new(secret.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).hexdigest()


# ============================================================================
# JSON HELPERS
# ============================================================================

def safe_json_loads(json_string: str, default: Any = None) -> Any:
    """
    Safely parse JSON string.

    Args:
        json_string: JSON string to parse
        default: Default value if parsing fails

    Returns:
        Parsed JSON or default
    """
    try:
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(data: Any, default: str = '{}') -> str:
    """
    Safely serialize to JSON string.

    Args:
        data: Data to serialize
        default: Default string if serialization fails

    Returns:
        JSON string or default
    """
    try:
        return json.dumps(data)
    except (TypeError, ValueError):
        return default


# ============================================================================
# CACHE HELPERS
# ============================================================================

def cache_get_or_set(key: str, value_func: Callable, timeout: int = 3600) -> Any:
    """
    Get from cache or set using value function.

    Args:
        key: Cache key
        value_func: Function to compute value if not in cache
        timeout: Cache timeout in seconds

    Returns:
        Cached or computed value
    """
    value = cache.get(key)
    if value is None:
        value = value_func()
        cache.set(key, value, timeout)
    return value


def invalidate_cache_pattern(pattern: str) -> int:
    """
    Invalidate all cache keys matching a pattern.

    Args:
        pattern: Pattern to match (e.g., 'user_*')

    Returns:
        int: Number of keys invalidated
    """
    count = 0
    for key in cache.keys(pattern):
        cache.delete(key)
        count += 1
    return count


# ============================================================================
# LOGGING HELPERS
# ============================================================================

def log_audit_event(
    user_id: Optional[int],
    action: str,
    resource: str,
    resource_id: Optional[str] = None,
    details: Optional[Dict] = None,
    ip: Optional[str] = None
) -> None:
    """
    Log audit event.

    Args:
        user_id: User ID (or None for system)
        action: Action performed (e.g., 'login', 'create', 'update', 'delete')
        resource: Resource type (e.g., 'user', 'group', 'contribution')
        resource_id: Resource identifier
        details: Additional details
        ip: Client IP address
    """
    log_data = {
        'user_id': user_id,
        'action': action,
        'resource': resource,
        'resource_id': resource_id,
        'details': details or {},
        'ip': ip,
        'timestamp': timezone.now().isoformat()
    }
    logger.info(f'AUDIT: {json.dumps(log_data)}')


# ============================================================================
# RETRY DECORATOR
# ============================================================================

def retry_on_failure(
    max_retries: int = 3,
    delay: int = 1,
    backoff: float = 2.0,
    exceptions: Tuple = (Exception,)
):
    """
    Decorator to retry a function on failure.

    Args:
        max_retries: Maximum number of retries
        delay: Initial delay in seconds
        backoff: Multiplier for delay after each retry
        exceptions: Tuple of exceptions to catch

    Returns:
        Decorated function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            _delay = delay
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        raise
                    logger.warning(f'Retry {attempt+1}/{max_retries} for {func.__name__}: {str(e)}')
                    time.sleep(_delay)
                    _delay *= backoff
            return None
        return wrapper
    return decorator


# ============================================================================
# TIMEZONE HELPERS
# ============================================================================

def get_current_time() -> datetime:
    """
    Get current time in project timezone.

    Returns:
        datetime: Current time with timezone
    """
    return timezone.now()


def get_timezone_offset(timezone_str: str) -> int:
    """
    Get offset in hours for given timezone.

    Args:
        timezone_str: Timezone string (e.g., 'Africa/Addis_Ababa')

    Returns:
        int: Offset in hours from UTC
    """
    try:
        import pytz
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
        offset = now.utcoffset()
        if offset:
            return offset.total_seconds() // 3600
        return 0
    except Exception:
        return 0


# ============================================================================
# PAGINATION HELPERS (ADDITIONAL)
# ============================================================================

def get_pagination_params(request) -> Dict[str, int]:
    """
    Extract pagination parameters from request.

    Args:
        request: HTTP request object

    Returns:
        Dict with 'page' and 'page_size'
    """
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', settings.PAGINATION_DEFAULT_LIMIT))
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = settings.PAGINATION_DEFAULT_LIMIT
    if page_size > settings.PAGINATION_MAX_LIMIT:
        page_size = settings.PAGINATION_MAX_LIMIT
    return {'page': page, 'page_size': page_size}


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'generate_otp',
    'generate_otp_with_expiry',
    'verify_otp',
    'send_otp_email',
    'send_otp_sms',
    'generate_referral_code',
    'validate_phone_number',
    'validate_email_address',
    'sanitize_input',
    'format_currency',
    'calculate_platform_fee',
    'calculate_net_amount',
    'get_client_ip',
    'get_user_agent',
    'get_user_location',
    'truncate_text',
    'slugify',
    'generate_random_string',
    'is_valid_uuid',
    'parse_date_range',
    'get_date_range',
    'format_datetime',
    'parse_datetime',
    'calculate_percentage',
    'validate_file_size',
    'validate_file_extension',
    'validate_image_file',
    'build_absolute_url',
    'extract_query_params',
    'generate_secure_token',
    'hash_string',
    'verify_hmac_signature',
    'generate_hmac_signature',
    'safe_json_loads',
    'safe_json_dumps',
    'cache_get_or_set',
    'invalidate_cache_pattern',
    'log_audit_event',
    'retry_on_failure',
    'get_current_time',
    'get_timezone_offset',
    'get_pagination_params',
]