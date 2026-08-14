"""
Custom exception classes for the Digital Ekub Platform.

This module provides a comprehensive set of exception classes
for standardized error handling across the entire application.
All exceptions include HTTP status codes, error codes, and
human-readable messages for consistent API responses.
"""

from rest_framework import status
from rest_framework.exceptions import APIException
from django.utils.translation import gettext_lazy as _
from typing import Dict, Any, Optional, List, Union


class CustomAPIException(APIException):
    """
    Base custom exception for API errors.

    All custom exceptions inherit from this class to ensure
    consistent error response formatting across the platform.
    """
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = _('An unexpected error occurred.')
    default_code = 'server_error'

    def __init__(
        self,
        detail: Optional[str] = None,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize custom exception with optional details.

        Args:
            detail: Human-readable error message
            code: Error code for programmatic handling
            status_code: HTTP status code override
            extra_data: Additional error context data
        """
        if detail is not None:
            self.detail = detail
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.extra_data = extra_data or {}
        super().__init__(self.detail, self.code)

    def get_full_details(self) -> Dict[str, Any]:
        """
        Return full error details including extra data.

        Returns:
            Dict containing status_code, code, detail, and extra_data
        """
        return {
            'status_code': self.status_code,
            'code': self.code,
            'detail': str(self.detail),
            'extra_data': self.extra_data,
        }


# ============================================================================
# HTTP 4XX CLIENT ERROR EXCEPTIONS
# ============================================================================

class BadRequestError(CustomAPIException):
    """HTTP 400 Bad Request - Invalid request parameters."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = _('Bad request. Please check your input.')
    default_code = 'bad_request'


class ValidationError(CustomAPIException):
    """HTTP 422 Unprocessable Entity - Invalid or missing fields."""
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = _('Validation error. Please check the provided fields.')
    default_code = 'validation_error'

    def __init__(
        self,
        detail: Optional[str] = None,
        code: Optional[str] = None,
        field_errors: Optional[Dict[str, List[str]]] = None,
        **kwargs
    ):
        """
        Initialize validation error with field-specific errors.

        Args:
            detail: Human-readable error message
            code: Error code
            field_errors: Dictionary mapping field names to error messages
        """
        self.field_errors = field_errors or {}
        super().__init__(detail, code, **kwargs)


class NotFoundError(CustomAPIException):
    """HTTP 404 Not Found - Resource does not exist."""
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = _('The requested resource was not found.')
    default_code = 'not_found'


class PermissionDeniedError(CustomAPIException):
    """HTTP 403 Forbidden - Insufficient permissions."""
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = _('You do not have permission to perform this action.')
    default_code = 'permission_denied'


class UnauthorizedError(CustomAPIException):
    """HTTP 401 Unauthorized - Not authenticated."""
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = _('Authentication credentials were not provided or are invalid.')
    default_code = 'unauthorized'


class ConflictError(CustomAPIException):
    """HTTP 409 Conflict - Resource conflict or duplicate."""
    status_code = status.HTTP_409_CONFLICT
    default_detail = _('Resource conflict detected.')
    default_code = 'conflict'


class GoneError(CustomAPIException):
    """HTTP 410 Gone - Resource is no longer available."""
    status_code = status.HTTP_410_GONE
    default_detail = _('The requested resource is no longer available.')
    default_code = 'gone'


class UnsupportedMediaTypeError(CustomAPIException):
    """HTTP 415 Unsupported Media Type."""
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    default_detail = _('Unsupported media type.')
    default_code = 'unsupported_media_type'


class TooManyRequestsError(CustomAPIException):
    """HTTP 429 Too Many Requests - Rate limit exceeded."""
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = _('Too many requests. Please try again later.')
    default_code = 'too_many_requests'


class MethodNotAllowedError(CustomAPIException):
    """HTTP 405 Method Not Allowed."""
    status_code = status.HTTP_405_METHOD_NOT_ALLOWED
    default_detail = _('Method not allowed for this endpoint.')
    default_code = 'method_not_allowed'


# ============================================================================
# HTTP 5XX SERVER ERROR EXCEPTIONS
# ============================================================================

class InternalServerError(CustomAPIException):
    """HTTP 500 Internal Server Error."""
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = _('An internal server error occurred. Please try again later.')
    default_code = 'internal_server_error'


class ServiceUnavailableError(CustomAPIException):
    """HTTP 503 Service Unavailable."""
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = _('Service is temporarily unavailable. Please try again later.')
    default_code = 'service_unavailable'


class GatewayTimeoutError(CustomAPIException):
    """HTTP 504 Gateway Timeout."""
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    default_detail = _('Gateway timeout. Please try again later.')
    default_code = 'gateway_timeout'


# ============================================================================
# DOMAIN-SPECIFIC EXCEPTIONS
# ============================================================================

# --- User Authentication Exceptions ---

class UserNotFoundError(NotFoundError):
    """User does not exist."""
    default_detail = _('User not found.')
    default_code = 'user_not_found'


class UserInactiveError(UnauthorizedError):
    """User account is inactive."""
    default_detail = _('This account is inactive. Please contact support.')
    default_code = 'user_inactive'


class UserSuspendedError(PermissionDeniedError):
    """User account is suspended."""
    default_detail = _('This account has been suspended. Please contact support.')
    default_code = 'user_suspended'


class UserLockedError(PermissionDeniedError):
    """User account is locked."""
    default_detail = _('This account is temporarily locked. Please try again later.')
    default_code = 'user_locked'


class UserDeletedError(PermissionDeniedError):
    """User account is deleted."""
    default_detail = _('This account has been deleted.')
    default_code = 'user_deleted'


class InvalidCredentialsError(UnauthorizedError):
    """Invalid login credentials."""
    default_detail = _('Invalid email or password.')
    default_code = 'invalid_credentials'


class EmailAlreadyExistsError(ConflictError):
    """Email is already registered."""
    default_detail = _('A user with this email already exists.')
    default_code = 'email_already_exists'


class PhoneAlreadyExistsError(ConflictError):
    """Phone number is already registered."""
    default_detail = _('A user with this phone number already exists.')
    default_code = 'phone_already_exists'


# --- OTP Exceptions ---

class OTPExpiredError(BadRequestError):
    """OTP has expired."""
    default_detail = _('OTP has expired. Please request a new one.')
    default_code = 'otp_expired'


class OTPInvalidError(BadRequestError):
    """Invalid OTP provided."""
    default_detail = _('Invalid OTP. Please try again.')
    default_code = 'otp_invalid'


class OTPTooManyAttemptsError(BadRequestError):
    """Too many failed OTP attempts."""
    default_detail = _('Too many failed attempts. Please request a new OTP.')
    default_code = 'otp_too_many_attempts'


class OTPNotVerifiedError(BadRequestError):
    """OTP not verified."""
    default_detail = _('OTP not verified. Please verify your OTP first.')
    default_code = 'otp_not_verified'


# --- Password Exceptions ---

class PasswordMismatchError(BadRequestError):
    """Passwords do not match."""
    default_detail = _('Passwords do not match.')
    default_code = 'password_mismatch'


class PasswordTooWeakError(BadRequestError):
    """Password does not meet complexity requirements."""
    default_detail = _('Password is too weak. Please choose a stronger password.')
    default_code = 'password_too_weak'


class PasswordResetFailedError(InternalServerError):
    """Password reset failed."""
    default_detail = _('Password reset failed. Please try again.')
    default_code = 'password_reset_failed'


# --- Group Exceptions ---

class GroupNotFoundError(NotFoundError):
    """Group does not exist."""
    default_detail = _('Group not found.')
    default_code = 'group_not_found'


class GroupFullError(BadRequestError):
    """Group has reached maximum capacity."""
    default_detail = _('Group is full. Cannot accept new members.')
    default_code = 'group_full'


class GroupAlreadyJoinedError(ConflictError):
    """User is already a member of the group."""
    default_detail = _('You are already a member of this group.')
    default_code = 'group_already_joined'


class GroupNotActiveError(BadRequestError):
    """Group is not active."""
    default_detail = _('Group is not active.')
    default_code = 'group_not_active'


class GroupCompletedError(BadRequestError):
    """Group is already completed."""
    default_detail = _('Group has already been completed.')
    default_code = 'group_completed'


class GroupCancelledError(BadRequestError):
    """Group is cancelled."""
    default_detail = _('Group has been cancelled.')
    default_code = 'group_cancelled'


class GroupNotMemberError(PermissionDeniedError):
    """User is not a member of the group."""
    default_detail = _('You are not a member of this group.')
    default_code = 'group_not_member'


class GroupAlreadyMemberError(ConflictError):
    """User is already a member."""
    default_detail = _('User is already a member of this group.')
    default_code = 'group_already_member'


class GroupMaxMembersExceededError(BadRequestError):
    """Maximum members exceeded."""
    default_detail = _('Maximum members exceeded for this group.')
    default_code = 'group_max_members_exceeded'


class GroupMinMembersRequiredError(BadRequestError):
    """Minimum members required to proceed."""
    default_detail = _('Minimum members required to proceed.')
    default_code = 'group_min_members_required'


class GroupNotOwnerError(PermissionDeniedError):
    """User is not the owner of the group."""
    default_detail = _('You are not the owner of this group.')
    default_code = 'group_not_owner'


class GroupNotAdminError(PermissionDeniedError):
    """User is not an admin of the group."""
    default_detail = _('You are not an admin of this group.')
    default_code = 'group_not_admin'


# --- Contribution Exceptions ---

class ContributionNotFoundError(NotFoundError):
    """Contribution not found."""
    default_detail = _('Contribution not found.')
    default_code = 'contribution_not_found'


class ContributionAlreadyPaidError(ConflictError):
    """Contribution is already paid."""
    default_detail = _('Contribution has already been paid.')
    default_code = 'contribution_already_paid'


class ContributionOverdueError(BadRequestError):
    """Contribution is overdue."""
    default_detail = _('Contribution is overdue. Please pay immediately.')
    default_code = 'contribution_overdue'


class ContributionAmountInvalidError(BadRequestError):
    """Invalid contribution amount."""
    default_detail = _('Invalid contribution amount.')
    default_code = 'contribution_amount_invalid'


class ContributionNotDueError(BadRequestError):
    """Contribution is not due yet."""
    default_detail = _('Contribution is not due yet.')
    default_code = 'contribution_not_due'


class ContributionAlreadyProcessedError(ConflictError):
    """Contribution has already been processed."""
    default_detail = _('Contribution has already been processed.')
    default_code = 'contribution_already_processed'


# --- Payment Exceptions ---

class PaymentNotFoundError(NotFoundError):
    """Payment not found."""
    default_detail = _('Payment not found.')
    default_code = 'payment_not_found'


class PaymentFailedError(InternalServerError):
    """Payment processing failed."""
    default_detail = _('Payment processing failed. Please try again.')
    default_code = 'payment_failed'


class PaymentTimeoutError(ServiceUnavailableError):
    """Payment gateway timeout."""
    default_detail = _('Payment gateway timeout. Please try again.')
    default_code = 'payment_timeout'


class PaymentGatewayError(ServiceUnavailableError):
    """Payment gateway error."""
    default_detail = _('Payment gateway error. Please try again later.')
    default_code = 'payment_gateway_error'


class PaymentAlreadyProcessedError(ConflictError):
    """Payment has already been processed."""
    default_detail = _('Payment has already been processed.')
    default_code = 'payment_already_processed'


class PaymentAmountMismatchError(BadRequestError):
    """Payment amount does not match expected."""
    default_detail = _('Payment amount does not match the expected amount.')
    default_code = 'payment_amount_mismatch'


class PaymentWebhookVerificationError(BadRequestError):
    """Payment webhook verification failed."""
    default_detail = _('Payment webhook verification failed.')
    default_code = 'payment_webhook_verification_failed'


# --- Notification Exceptions ---

class NotificationNotFoundError(NotFoundError):
    """Notification not found."""
    default_detail = _('Notification not found.')
    default_code = 'notification_not_found'


class NotificationSendFailedError(InternalServerError):
    """Failed to send notification."""
    default_detail = _('Failed to send notification. Please try again.')
    default_code = 'notification_send_failed'


class NotificationAlreadyReadError(ConflictError):
    """Notification is already read."""
    default_detail = _('Notification has already been read.')
    default_code = 'notification_already_read'


# --- Referral Exceptions ---

class ReferralCodeInvalidError(BadRequestError):
    """Invalid referral code."""
    default_detail = _('Invalid referral code.')
    default_code = 'referral_code_invalid'


class ReferralCodeExpiredError(BadRequestError):
    """Referral code has expired."""
    default_detail = _('Referral code has expired.')
    default_code = 'referral_code_expired'


# --- Permission Exceptions ---

class InsufficientReputationError(PermissionDeniedError):
    """Insufficient reputation score."""
    default_detail = _('Insufficient reputation score to perform this action.')
    default_code = 'insufficient_reputation'


class FeatureNotAvailableError(BadRequestError):
    """Feature is not available to the user."""
    default_detail = _('This feature is not available to your account type.')
    default_code = 'feature_not_available'


class InsufficientBalanceError(BadRequestError):
    """Insufficient balance."""
    default_detail = _('Insufficient balance to perform this action.')
    default_code = 'insufficient_balance'


# --- File Upload Exceptions ---

class FileTooLargeError(BadRequestError):
    """Uploaded file is too large."""
    default_detail = _('Uploaded file is too large. Maximum size is 5MB.')
    default_code = 'file_too_large'


class InvalidFileTypeError(BadRequestError):
    """Invalid file type."""
    default_detail = _('Invalid file type. Allowed types: JPG, PNG, GIF.')
    default_code = 'invalid_file_type'


class FileUploadFailedError(InternalServerError):
    """File upload failed."""
    default_detail = _('File upload failed. Please try again.')
    default_code = 'file_upload_failed'


# ============================================================================
# EXCEPTION HANDLER FOR DRF
# ============================================================================

def custom_exception_handler(exc, context):
    """
    Custom exception handler for Django REST Framework.

    This handler formats all exceptions in a consistent structure:
    {
        "success": false,
        "status_code": 400,
        "code": "bad_request",
        "message": "Human readable error message",
        "errors": {
            "field_name": ["Error message 1", "Error message 2"]
        },
        "extra_data": {}
    }

    Args:
        exc: The exception instance
        context: The context of the exception

    Returns:
        Response object with formatted error details
    """
    from rest_framework.views import exception_handler
    from rest_framework.response import Response

    response = exception_handler(exc, context)

    if response is None:
        if isinstance(exc, CustomAPIException):
            response = Response(
                {
                    'success': False,
                    'status_code': exc.status_code,
                    'code': exc.default_code,
                    'message': str(exc.detail),
                    'errors': getattr(exc, 'field_errors', {}),
                    'extra_data': getattr(exc, 'extra_data', {}),
                },
                status=exc.status_code
            )
        else:
            response = Response(
                {
                    'success': False,
                    'status_code': status.HTTP_500_INTERNAL_SERVER_ERROR,
                    'code': 'server_error',
                    'message': 'An unexpected error occurred.',
                    'errors': {},
                    'extra_data': {},
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        response.data = {
            'success': False,
            'status_code': response.status_code,
            'code': getattr(exc, 'default_code', 'error'),
            'message': response.data.get('detail', str(response.data)),
            'errors': response.data.get('fields', {}),
            'extra_data': {},
        }

    return response


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def raise_if_not_found(obj, message: Optional[str] = None):
    """
    Helper function to raise NotFoundError if object is None.

    Args:
        obj: The object to check
        message: Optional custom error message

    Raises:
        NotFoundError: If obj is None
    """
    if obj is None:
        raise NotFoundError(detail=message or 'Resource not found.')
    return obj


def raise_if_not_authorized(condition: bool, message: Optional[str] = None):
    """
    Helper function to raise PermissionDeniedError if condition is False.

    Args:
        condition: Boolean condition to check
        message: Optional custom error message

    Raises:
        PermissionDeniedError: If condition is False
    """
    if not condition:
        raise PermissionDeniedError(detail=message or 'Permission denied.')


def raise_if_invalid(condition: bool, message: Optional[str] = None):
    """
    Helper function to raise BadRequestError if condition is False.

    Args:
        condition: Boolean condition to check
        message: Optional custom error message

    Raises:
        BadRequestError: If condition is False
    """
    if not condition:
        raise BadRequestError(detail=message or 'Invalid request.')


def raise_if_conflict(condition: bool, message: Optional[str] = None):
    """
    Helper function to raise ConflictError if condition is True.

    Args:
        condition: Boolean condition to check
        message: Optional custom error message

    Raises:
        ConflictError: If condition is True
    """
    if condition:
        raise ConflictError(detail=message or 'Resource conflict detected.')


def handle_exception_silently(func):
    """
    Decorator to silently handle exceptions and return None.

    Useful for background tasks where logging is sufficient.

    Args:
        func: Function to wrap

    Returns:
        Wrapped function that returns None on exception
    """
    import logging
    logger = logging.getLogger(__name__)

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f'Error in {func.__name__}: {str(e)}', exc_info=True)
            return None

    return wrapper