"""
Base payment gateway abstraction for the Digital Ekub Platform.

This module defines the abstract base class that all payment gateways
must implement. It provides a consistent interface for:
- Processing payments (initiate, confirm, complete)
- Processing refunds
- Checking transaction status
- Handling webhook callbacks with signature verification
- Mapping gateway-specific status codes to internal statuses
- Formatting amounts and generating request IDs

All concrete gateways (Chapa, Telebirr, Bank Transfer) inherit from
this base class and implement the abstract methods.

The module also includes:
- GatewayResponse: Standardized response object
- GatewayError and subclasses: Exceptions for gateway operations
- PaymentStatus: Internal status enumeration
- Utility methods for common gateway operations
"""

import abc
import json
import logging
import time
import hmac
import hashlib
import uuid
from decimal import Decimal
from typing import Dict, Any, Optional, Union, Tuple, List, Callable
from enum import Enum
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMERATIONS AND DATA CLASSES
# ============================================================================

class PaymentStatus(str, Enum):
    """
    Internal payment status enumeration.
    These statuses are used consistently across all gateways.
    """
    PENDING = 'pending'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    REFUNDED = 'refunded'
    REVERSED = 'reversed'
    EXPIRED = 'expired'
    UNKNOWN = 'unknown'

    @classmethod
    def from_gateway_status(cls, gateway_status: str, gateway_name: str) -> 'PaymentStatus':
        """
        Map a gateway-specific status to internal PaymentStatus.

        Args:
            gateway_status: The raw status from the gateway
            gateway_name: The name of the gateway (for mapping)

        Returns:
            PaymentStatus: The mapped internal status
        """
        # Default mapping; subclasses should override if needed
        mapping = {
            'chapa': {
                'pending': cls.PENDING,
                'processing': cls.PROCESSING,
                'completed': cls.COMPLETED,
                'failed': cls.FAILED,
                'cancelled': cls.CANCELLED,
                'refunded': cls.REFUNDED,
                'reversed': cls.REVERSED,
                'expired': cls.EXPIRED,
            },
            'telebirr': {
                'pending': cls.PENDING,
                'processing': cls.PROCESSING,
                'completed': cls.COMPLETED,
                'failed': cls.FAILED,
                'cancelled': cls.CANCELLED,
                'refunded': cls.REFUNDED,
                'reversed': cls.REVERSED,
                'expired': cls.EXPIRED,
            },
            'bank_transfer': {
                'pending': cls.PENDING,
                'processing': cls.PROCESSING,
                'completed': cls.COMPLETED,
                'failed': cls.FAILED,
                'cancelled': cls.CANCELLED,
                'refunded': cls.REFUNDED,
                'reversed': cls.REVERSED,
                'expired': cls.EXPIRED,
            },
        }
        gateway_mapping = mapping.get(gateway_name.lower(), {})
        return gateway_mapping.get(gateway_status, cls.UNKNOWN)


@dataclass
class GatewayResponse:
    """
    Standardized response object from a gateway operation.
    """
    success: bool
    transaction_id: Optional[str] = None
    status: PaymentStatus = PaymentStatus.UNKNOWN
    message: str = ''
    raw_data: Dict[str, Any] = field(default_factory=dict)
    reference: Optional[str] = None
    amount: Optional[Decimal] = None
    paid_at: Optional[str] = None  # ISO format timestamp

    def __post_init__(self):
        if isinstance(self.status, str):
            self.status = PaymentStatus(self.status)

    def is_successful(self) -> bool:
        """Return True if the operation was successful and status is completed or pending."""
        return self.success and self.status in (PaymentStatus.COMPLETED, PaymentStatus.PENDING, PaymentStatus.PROCESSING)

    def is_completed(self) -> bool:
        """Return True if the payment is completed."""
        return self.status == PaymentStatus.COMPLETED

    def is_pending(self) -> bool:
        """Return True if the payment is pending."""
        return self.status == PaymentStatus.PENDING


# ============================================================================
# EXCEPTION CLASSES
# ============================================================================

class GatewayError(Exception):
    """Base exception for gateway-related errors."""
    def __init__(self, message: str, code: Optional[str] = None, raw_response: Optional[Dict] = None):
        self.message = message
        self.code = code
        self.raw_response = raw_response
        super().__init__(message)

    def __str__(self):
        if self.code:
            return f"[{self.code}] {self.message}"
        return self.message


class GatewayAuthError(GatewayError):
    """Raised when authentication with the gateway fails."""
    pass


class GatewayTimeoutError(GatewayError):
    """Raised when the gateway request times out."""
    pass


class GatewayConnectionError(GatewayError):
    """Raised when the gateway cannot be reached."""
    pass


class GatewayValidationError(GatewayError):
    """Raised when the gateway returns a validation error."""
    pass


class GatewayProcessingError(GatewayError):
    """Raised when the gateway fails to process the request."""
    pass


class GatewayWebhookError(GatewayError):
    """Raised when webhook verification or processing fails."""
    pass


class GatewayConfigError(GatewayError):
    """Raised when the gateway configuration is invalid."""
    pass


# ============================================================================
# BASE GATEWAY CLASS
# ============================================================================

class BaseGateway(abc.ABC):
    """
    Abstract base class for payment gateways.

    All concrete gateways must implement the abstract methods:
    - process_payment()
    - refund_payment()
    - check_status()
    - handle_webhook()
    - validate_webhook_signature()

    They may also override helper methods for mapping statuses,
    formatting amounts, and generating request IDs.

    The class provides a robust HTTP client with retry logic,
    logging, and error handling.
    """

    # --------------------------------------------------------------------------
    # Class-level constants
    # --------------------------------------------------------------------------

    GATEWAY_NAME: str = 'base'  # Override in subclass
    SUPPORTED_CURRENCIES: Tuple[str, ...] = ('ETB',)
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_FACTOR: float = 0.5
    TIMEOUT: int = 30

    # --------------------------------------------------------------------------
    # Initialization
    # --------------------------------------------------------------------------

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the gateway with configuration.

        Args:
            config: Dictionary with gateway-specific settings (API keys, URLs, etc.)
        """
        self.config = config or {}
        self._session = None
        self._setup_http_session()

        # Validate configuration
        self._validate_config()

        logger.info(f'Initialized {self.GATEWAY_NAME} gateway')

    def _setup_http_session(self) -> None:
        """Set up a requests session with retry logic."""
        session = requests.Session()

        # Retry strategy
        retry_strategy = Retry(
            total=self.MAX_RETRIES,
            backoff_factor=self.RETRY_BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        # Default headers
        session.headers.update({
            'User-Agent': f'EkubPlatform/{self.GATEWAY_NAME}/1.0',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })

        self._session = session

    def _validate_config(self) -> None:
        """
        Validate that required configuration is present.
        Override in subclasses to add specific validations.
        """
        # Subclasses should implement their own validation
        pass

    # --------------------------------------------------------------------------
    # Abstract methods (must be implemented by subclasses)
    # --------------------------------------------------------------------------

    @abc.abstractmethod
    def process_payment(self, amount: Decimal, currency: str, reference: str,
                        description: str, customer_email: str, customer_phone: Optional[str] = None,
                        callback_url: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> GatewayResponse:
        """
        Process a payment.

        Args:
            amount: Amount to charge
            currency: Currency code (e.g., 'ETB')
            reference: Unique reference for this payment
            description: Description of the payment
            customer_email: Email of the customer
            customer_phone: Optional phone number
            callback_url: Optional URL for asynchronous notification
            metadata: Additional metadata to pass to the gateway

        Returns:
            GatewayResponse: Standardized response
        """
        pass

    @abc.abstractmethod
    def refund_payment(self, transaction_id: str, amount: Optional[Decimal] = None,
                       reason: Optional[str] = None) -> GatewayResponse:
        """
        Refund a previously completed payment.

        Args:
            transaction_id: The gateway transaction ID
            amount: Amount to refund (if partial; defaults to full)
            reason: Reason for refund

        Returns:
            GatewayResponse: Standardized response
        """
        pass

    @abc.abstractmethod
    def check_status(self, transaction_id: str) -> GatewayResponse:
        """
        Check the status of a transaction.

        Args:
            transaction_id: The gateway transaction ID

        Returns:
            GatewayResponse: Standardized response with current status
        """
        pass

    @abc.abstractmethod
    def handle_webhook(self, payload: bytes, headers: Dict[str, str]) -> GatewayResponse:
        """
        Handle an incoming webhook from the gateway.

        Args:
            payload: Raw request body
            headers: Request headers

        Returns:
            GatewayResponse: Standardized response indicating the webhook event
        """
        pass

    @abc.abstractmethod
    def validate_webhook_signature(self, payload: bytes, signature: str, secret: Optional[str] = None) -> bool:
        """
        Validate the webhook signature.

        Args:
            payload: Raw request body
            signature: The signature from the request header
            secret: Optional secret override; defaults to configured secret

        Returns:
            bool: True if signature is valid
        """
        pass

    # --------------------------------------------------------------------------
    # Concrete helper methods (may be overridden)
    # --------------------------------------------------------------------------

    def get_headers(self) -> Dict[str, str]:
        """
        Return the HTTP headers to include in requests to the gateway.

        Returns:
            dict: Headers dictionary
        """
        return {
            'Authorization': f'Bearer {self.config.get("api_key", "")}',
        }

    def format_amount(self, amount: Decimal) -> str:
        """
        Format the amount according to the gateway's requirements.

        Args:
            amount: Decimal amount

        Returns:
            str: Formatted amount string
        """
        # Default: return amount as string with 2 decimal places
        return f"{amount:.2f}"

    def generate_request_id(self) -> str:
        """
        Generate a unique request ID for tracking.

        Returns:
            str: Unique ID
        """
        return f"{self.GATEWAY_NAME}_{uuid.uuid4().hex[:16]}_{int(time.time())}"

    def map_status(self, gateway_status: str) -> PaymentStatus:
        """
        Map gateway-specific status to internal PaymentStatus.

        Args:
            gateway_status: Raw status from gateway

        Returns:
            PaymentStatus: Internal status
        """
        return PaymentStatus.from_gateway_status(gateway_status, self.GATEWAY_NAME)

    def parse_datetime(self, datetime_str: str) -> Optional[str]:
        """
        Parse gateway datetime string to ISO format.

        Args:
            datetime_str: Datetime string from gateway

        Returns:
            Optional[str]: ISO format datetime string, or None
        """
        if not datetime_str:
            return None
        try:
            # Attempt to parse; subclasses may override for specific formats
            from dateutil.parser import parse
            dt = parse(datetime_str)
            return dt.isoformat()
        except Exception:
            return datetime_str

    def build_callback_url(self, base_url: Optional[str] = None) -> str:
        """
        Build the callback URL for webhook notifications.

        Args:
            base_url: Optional base URL; defaults to site URL from settings

        Returns:
            str: Full callback URL
        """
        base = base_url or getattr(settings, 'SITE_URL', '')
        if not base:
            raise GatewayConfigError('SITE_URL is not configured for callbacks')
        return urljoin(base, f'/api/v1/webhooks/{self.GATEWAY_NAME}/')

    def log_request(self, method: str, url: str, data: Optional[Dict] = None, headers: Optional[Dict] = None) -> None:
        """
        Log the outgoing request (for debugging).

        Args:
            method: HTTP method
            url: Request URL
            data: Request body
            headers: Request headers
        """
        log_data = {
            'gateway': self.GATEWAY_NAME,
            'method': method,
            'url': url,
            'headers': {k: v for k, v in headers.items() if 'key' not in k.lower()} if headers else {},
            'data': data,
        }
        logger.debug(f'Gateway request: {log_data}')

    def log_response(self, response: requests.Response) -> None:
        """
        Log the incoming response (for debugging).

        Args:
            response: requests.Response object
        """
        log_data = {
            'gateway': self.GATEWAY_NAME,
            'status_code': response.status_code,
            'headers': {k: v for k, v in response.headers.items() if 'key' not in k.lower()},
            'body': response.text[:1000] if response.text else '',
        }
        logger.debug(f'Gateway response: {log_data}')

    # --------------------------------------------------------------------------
    # HTTP request methods with error handling
    # --------------------------------------------------------------------------

    def _request(self, method: str, url: str, data: Optional[Dict] = None,
                 params: Optional[Dict] = None, headers: Optional[Dict] = None,
                 timeout: Optional[int] = None) -> requests.Response:
        """
        Make an HTTP request to the gateway with retry and error handling.

        Args:
            method: HTTP method
            url: Full URL
            data: Request body (JSON serialized)
            params: Query parameters
            headers: Additional headers
            timeout: Request timeout in seconds

        Returns:
            requests.Response: The response object

        Raises:
            GatewayTimeoutError: If request times out
            GatewayConnectionError: If connection fails
            GatewayAuthError: If authentication fails
            GatewayError: For other errors
        """
        timeout = timeout or self.TIMEOUT
        headers = {**self.get_headers(), **(headers or {})}

        self.log_request(method, url, data, headers)

        try:
            response = self._session.request(
                method=method,
                url=url,
                json=data if data else None,
                params=params,
                headers=headers,
                timeout=timeout,
            )
            self.log_response(response)

            # Check for HTTP errors
            if response.status_code >= 500:
                raise GatewayError(f'Gateway server error: {response.status_code}', code='server_error', raw_response=response.text)
            elif response.status_code == 401 or response.status_code == 403:
                raise GatewayAuthError(f'Authentication failed: {response.status_code}', code='auth_error', raw_response=response.text)
            elif response.status_code == 400:
                raise GatewayValidationError(f'Validation error: {response.text}', code='validation_error', raw_response=response.text)
            elif response.status_code >= 400:
                raise GatewayError(f'Request error: {response.status_code}', code='request_error', raw_response=response.text)

            return response

        except requests.exceptions.Timeout:
            raise GatewayTimeoutError('Request timed out', code='timeout')
        except requests.exceptions.ConnectionError as e:
            raise GatewayConnectionError(f'Connection error: {str(e)}', code='connection_error')
        except requests.exceptions.RequestException as e:
            raise GatewayError(f'Request error: {str(e)}', code='request_failed')

    def _post(self, url: str, data: Dict, headers: Optional[Dict] = None, timeout: Optional[int] = None) -> requests.Response:
        """Convenience method for POST requests."""
        return self._request('POST', url, data=data, headers=headers, timeout=timeout)

    def _get(self, url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None, timeout: Optional[int] = None) -> requests.Response:
        """Convenience method for GET requests."""
        return self._request('GET', url, params=params, headers=headers, timeout=timeout)

    def _put(self, url: str, data: Dict, headers: Optional[Dict] = None, timeout: Optional[int] = None) -> requests.Response:
        """Convenience method for PUT requests."""
        return self._request('PUT', url, data=data, headers=headers, timeout=timeout)

    def _patch(self, url: str, data: Dict, headers: Optional[Dict] = None, timeout: Optional[int] = None) -> requests.Response:
        """Convenience method for PATCH requests."""
        return self._request('PATCH', url, data=data, headers=headers, timeout=timeout)

    def _delete(self, url: str, headers: Optional[Dict] = None, timeout: Optional[int] = None) -> requests.Response:
        """Convenience method for DELETE requests."""
        return self._request('DELETE', url, headers=headers, timeout=timeout)

    # --------------------------------------------------------------------------
    # Utility methods for webhook handling
    # --------------------------------------------------------------------------

    def verify_hmac_signature(self, payload: bytes, signature: str, secret: str, algorithm: str = 'sha256') -> bool:
        """
        Verify an HMAC signature.

        Args:
            payload: Raw request body bytes
            signature: Provided signature
            secret: Secret key
            algorithm: Hash algorithm (default: sha256)

        Returns:
            bool: True if valid
        """
        if not signature or not secret:
            return False
        expected = hmac.new(
            secret.encode('utf-8'),
            payload,
            getattr(hashlib, algorithm)
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook_payload(self, payload: bytes) -> Dict[str, Any]:
        """
        Parse webhook payload from bytes to dict.

        Args:
            payload: Raw request body bytes

        Returns:
            dict: Parsed JSON payload

        Raises:
            GatewayWebhookError: If payload is invalid JSON
        """
        try:
            return json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise GatewayWebhookError(f'Invalid JSON payload: {str(e)}')

    # --------------------------------------------------------------------------
    # Class methods for availability and configuration
    # --------------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """
        Check if the gateway is configured and available.

        Returns:
            bool: True if the gateway can be used
        """
        # Subclasses should override to check for required settings
        return True

    @classmethod
    def get_required_config_keys(cls) -> List[str]:
        """
        Return the list of required configuration keys.

        Returns:
            List[str]: Required keys
        """
        return []

    # --------------------------------------------------------------------------
    # String representation
    # --------------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} gateway='{self.GATEWAY_NAME}'>"

    def __str__(self) -> str:
        return f"{self.GATEWAY_NAME} gateway"