"""
Telebirr payment gateway implementation.

Telebirr is Ethiopia's leading mobile money service by Ethio Telecom.
This module provides integration with the Telebirr Merchant API.

Features:
- Payment initialization with QR code generation
- Payment status checking
- Full and partial refunds
- Webhook handling with signature verification
- Deep link generation for mobile apps
- QR code generation for in-store payments

Documentation: Telebirr Merchant API documentation (available to registered merchants)
"""

import json
import logging
import hashlib
import hmac
import uuid
import base64
from decimal import Decimal
from typing import Dict, Any, Optional, Union, List, Tuple
from urllib.parse import urljoin, urlencode
from datetime import datetime
import requests

from django.conf import settings
from django.utils import timezone

from .base import (
    BaseGateway,
    GatewayResponse,
    GatewayError,
    GatewayAuthError,
    GatewayTimeoutError,
    GatewayConnectionError,
    GatewayValidationError,
    GatewayProcessingError,
    GatewayWebhookError,
    GatewayConfigError,
    PaymentStatus,
)

logger = logging.getLogger(__name__)


# ============================================================================
# TELEBIRR GATEWAY IMPLEMENTATION
# ============================================================================

class TelebirrGateway(BaseGateway):
    """
    Telebirr payment gateway implementation.

    Supports:
    - Payment initialization with QR code and deep link
    - Payment verification (status check)
    - Full and partial refunds
    - Webhook handling with HMAC signature verification
    - QR code generation for in-store payments
    - Deep link generation for mobile app integration

    Configuration keys (in settings or passed to constructor):
    - api_key: Your Telebirr API key (client ID)
    - secret: Your Telebirr secret key
    - merchant_id: Your merchant ID
    - api_url: Base API URL (default: https://api.telebirr.et/v1)
    - timeout: Request timeout in seconds (default: 30)

    For sandbox testing, set api_url to the sandbox endpoint.
    """

    GATEWAY_NAME = 'telebirr'
    SUPPORTED_CURRENCIES = ('ETB',)
    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 0.5
    TIMEOUT = 30

    # Telebirr API endpoints
    API_ENDPOINTS = {
        'payment': 'payment/initiate',
        'status': 'payment/status/{reference}',
        'refund': 'payment/refund',
        'qr': 'payment/qr',
        'webhook': 'webhook/register',
        'balance': 'merchant/balance',
        'transaction': 'merchant/transaction/{transaction_id}',
    }

    # Telebirr status mapping
    TELEBIRR_STATUS_MAP = {
        'INITIATED': PaymentStatus.PENDING,
        'PENDING': PaymentStatus.PENDING,
        'PROCESSING': PaymentStatus.PROCESSING,
        'PAID': PaymentStatus.COMPLETED,
        'SUCCESS': PaymentStatus.COMPLETED,
        'COMPLETED': PaymentStatus.COMPLETED,
        'FAILED': PaymentStatus.FAILED,
        'CANCELLED': PaymentStatus.CANCELLED,
        'EXPIRED': PaymentStatus.EXPIRED,
        'REFUNDED': PaymentStatus.REFUNDED,
        'REVERSED': PaymentStatus.REVERSED,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Telebirr gateway with configuration.

        Args:
            config: Dictionary with 'api_key', 'secret', 'merchant_id', etc.
        """
        super().__init__(config)

        # Extract configuration
        self.api_key = self.config.get('api_key', '')
        self.secret = self.config.get('secret', '')
        self.merchant_id = self.config.get('merchant_id', '')
        self.api_url = self.config.get('api_url', 'https://api.telebirr.et/v1')
        self.timeout = self.config.get('timeout', 30)
        self.sandbox = self.config.get('sandbox', False)

        # Sanitize API URL
        self.api_url = self.api_url.rstrip('/')

        # Validate required config
        self._validate_config()

        logger.info(f'Telebirr gateway initialized (sandbox={self.sandbox})')

    def _validate_config(self) -> None:
        """Validate that required configuration is present."""
        if not self.api_key:
            raise GatewayConfigError('Telebirr API key is required. Set TELEBIRR_API_KEY in settings.')

        if not self.secret:
            raise GatewayConfigError('Telebirr secret key is required. Set TELEBIRR_SECRET in settings.')

        if not self.merchant_id:
            raise GatewayConfigError('Telebirr merchant ID is required. Set TELEBIRR_MERCHANT_ID in settings.')

        if self.sandbox:
            logger.info('Telebirr sandbox mode enabled.')

    def get_headers(self) -> Dict[str, str]:
        """
        Return headers for Telebirr API requests.

        Telebirr uses custom authentication with:
        - X-API-Key: API key (client ID)
        - X-Signature: HMAC-SHA256 signature of the request body
        - X-Timestamp: Request timestamp
        - X-Nonce: Unique nonce for each request
        """
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-API-Key': self.api_key,
            'X-Merchant-ID': self.merchant_id,
            'X-Timestamp': self._generate_timestamp(),
            'X-Nonce': self._generate_nonce(),
            'User-Agent': f'EkubPlatform/{self.GATEWAY_NAME}/1.0',
        }

        # Signature will be added in _sign_request method
        return headers

    def _generate_timestamp(self) -> str:
        """Generate ISO-8601 timestamp for request."""
        return datetime.utcnow().isoformat() + 'Z'

    def _generate_nonce(self) -> str:
        """Generate a unique nonce for each request."""
        return uuid.uuid4().hex[:16]

    def _sign_request(self, method: str, path: str, body: Optional[Dict] = None,
                     timestamp: Optional[str] = None, nonce: Optional[str] = None) -> str:
        """
        Generate HMAC-SHA256 signature for a request.

        Telebirr expects: HMAC-SHA256(method + path + timestamp + nonce + body_json)

        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            path: API path (e.g., '/payment/initiate')
            body: Request body (dict or None)
            timestamp: Request timestamp (optional, auto-generated)
            nonce: Nonce (optional, auto-generated)

        Returns:
            str: Hex-encoded HMAC signature
        """
        if timestamp is None:
            timestamp = self._generate_timestamp()
        if nonce is None:
            nonce = self._generate_nonce()

        # Build the string to sign
        sign_string = f"{method}{path}{timestamp}{nonce}"

        # Add body if present
        if body:
            body_json = json.dumps(body, separators=(',', ':'), sort_keys=True)
            sign_string += body_json

        # Generate HMAC-SHA256
        signature = hmac.new(
            self.secret.encode('utf-8'),
            sign_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return signature

    def _get_signed_headers(self, method: str, path: str, body: Optional[Dict] = None) -> Dict[str, str]:
        """
        Get headers with signature for a request.

        Args:
            method: HTTP method
            path: API path
            body: Request body

        Returns:
            Dict with headers including signature
        """
        timestamp = self._generate_timestamp()
        nonce = self._generate_nonce()
        signature = self._sign_request(method, path, body, timestamp, nonce)

        headers = self.get_headers()
        headers['X-Timestamp'] = timestamp
        headers['X-Nonce'] = nonce
        headers['X-Signature'] = signature

        return headers

    def _request(self, method: str, url: str, data: Optional[Dict] = None,
                 params: Optional[Dict] = None, headers: Optional[Dict] = None,
                 timeout: Optional[int] = None) -> requests.Response:
        """
        Make an HTTP request to Telebirr with signature authentication.

        Args:
            method: HTTP method
            url: Full URL
            data: Request body
            params: Query parameters
            headers: Additional headers
            timeout: Request timeout

        Returns:
            requests.Response: The response object

        Raises:
            GatewayError: With appropriate error details
        """
        # Extract path from URL
        path = url.replace(self.api_url, '')
        if not path.startswith('/'):
            path = '/' + path

        # Get signed headers
        signed_headers = self._get_signed_headers(method, path, data)
        if headers:
            signed_headers.update(headers)

        self.log_request(method, url, data, signed_headers)

        try:
            timeout = timeout or self.TIMEOUT
            response = self._session.request(
                method=method,
                url=url,
                json=data if data else None,
                params=params,
                headers=signed_headers,
                timeout=timeout,
            )
            self.log_response(response)

            # Check response status
            if response.status_code >= 500:
                raise GatewayError(f'Telebirr server error: {response.status_code}', code='server_error')
            elif response.status_code == 401 or response.status_code == 403:
                raise GatewayAuthError(f'Authentication failed: {response.status_code}', code='auth_error')
            elif response.status_code == 400:
                raise GatewayValidationError(f'Validation error: {response.text}', code='validation_error')
            elif response.status_code == 404:
                raise GatewayValidationError('Resource not found', code='not_found')
            elif response.status_code >= 400:
                raise GatewayError(f'Request error: {response.status_code}', code='request_error')

            return response

        except requests.exceptions.Timeout:
            raise GatewayTimeoutError('Request timed out', code='timeout')
        except requests.exceptions.ConnectionError as e:
            raise GatewayConnectionError(f'Connection error: {str(e)}', code='connection_error')
        except requests.exceptions.RequestException as e:
            raise GatewayError(f'Request error: {str(e)}', code='request_failed')

    # --------------------------------------------------------------------------
    # PAYMENT PROCESSING
    # --------------------------------------------------------------------------

    def process_payment(self, amount: Decimal, currency: str, reference: str,
                        description: str, customer_email: str, customer_phone: Optional[str] = None,
                        callback_url: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> GatewayResponse:
        """
        Initialize a payment with Telebirr.

        Args:
            amount: Amount to charge (in ETB)
            currency: Currency code (ETB only)
            reference: Unique reference for this payment
            description: Description of the payment
            customer_email: Customer email (optional for Telebirr)
            customer_phone: Customer phone number (required for Telebirr)
            callback_url: Optional URL for notification
            metadata: Additional data to pass

        Returns:
            GatewayResponse with transaction_id, QR code, deep link, etc.
        """
        if currency not in self.SUPPORTED_CURRENCIES:
            raise GatewayValidationError(f'Unsupported currency: {currency}. Telebirr only supports ETB.')

        if amount <= 0:
            raise GatewayValidationError('Amount must be greater than zero')

        if not customer_phone:
            raise GatewayValidationError('Customer phone number is required for Telebirr payments')

        # Build request payload
        payload = {
            'amount': self.format_amount(amount),
            'currency': currency,
            'reference': reference,
            'description': description[:200],
            'phone_number': customer_phone,
            'email': customer_email or '',
            'callback_url': callback_url or self.build_callback_url(),
            'meta': metadata or {},
        }

        # If sandbox, add sandbox flag
        if self.sandbox:
            payload['sandbox'] = True

        url = urljoin(self.api_url, self.API_ENDPOINTS['payment'])

        try:
            response = self._post(url, payload)
            data = response.json()

            # Parse Telebirr response
            if data.get('status') == 'success':
                result_data = data.get('data', {})
                return GatewayResponse(
                    success=True,
                    transaction_id=result_data.get('transaction_id') or result_data.get('reference'),
                    status=self.map_status(result_data.get('status', 'pending')),
                    message='Payment initialized successfully',
                    raw_data=data,
                    reference=reference,
                    amount=amount,
                )
            else:
                error_message = data.get('message', 'Unknown error')
                error_code = data.get('code')
                raise GatewayProcessingError(f'Telebirr payment initiation failed: {error_message}',
                                             code=error_code, raw_response=data)

        except GatewayError:
            raise
        except Exception as e:
            logger.error(f'Telebirr payment initialization error: {str(e)}')
            raise GatewayProcessingError(f'Payment initialization failed: {str(e)}')

    def generate_qr(self, reference: str, amount: Decimal, description: str,
                   customer_phone: str, expiry_minutes: int = 30) -> Dict[str, Any]:
        """
        Generate a QR code for in-store Telebirr payments.

        Args:
            reference: Unique reference for this payment
            amount: Payment amount
            description: Payment description
            customer_phone: Customer phone number
            expiry_minutes: QR code expiry in minutes

        Returns:
            dict: QR code data (base64 image, expiry, etc.)

        Raises:
            GatewayProcessingError: If QR generation fails
        """
        payload = {
            'reference': reference,
            'amount': self.format_amount(amount),
            'description': description[:200],
            'phone_number': customer_phone,
            'expiry_minutes': expiry_minutes,
        }

        url = urljoin(self.api_url, self.API_ENDPOINTS['qr'])

        try:
            response = self._post(url, payload)
            data = response.json()

            if data.get('status') == 'success':
                result_data = data.get('data', {})
                return {
                    'qr_code': result_data.get('qr_code'),
                    'qr_image': result_data.get('qr_image'),  # base64 encoded
                    'expires_at': result_data.get('expires_at'),
                    'reference': reference,
                    'amount': amount,
                }
            else:
                raise GatewayProcessingError(f'QR generation failed: {data.get("message", "Unknown error")}')

        except GatewayError:
            raise
        except Exception as e:
            logger.error(f'Telebirr QR generation error: {str(e)}')
            raise GatewayProcessingError(f'QR generation failed: {str(e)}')

    def generate_deep_link(self, reference: str, amount: Decimal, description: str) -> str:
        """
        Generate a deep link for Telebirr mobile app.

        Format: telebirr://pay?amount={amount}&reference={reference}&description={description}

        Args:
            reference: Payment reference
            amount: Payment amount
            description: Payment description

        Returns:
            str: Deep link URL for Telebirr mobile app
        """
        params = {
            'amount': self.format_amount(amount),
            'reference': reference,
            'description': description[:200],
        }
        return f"telebirr://pay?{urlencode(params)}"

    # --------------------------------------------------------------------------
    # PAYMENT VERIFICATION AND STATUS CHECK
    # --------------------------------------------------------------------------

    def check_status(self, transaction_id: str) -> GatewayResponse:
        """
        Check the status of a transaction with Telebirr.

        Args:
            transaction_id: The Telebirr transaction ID or reference

        Returns:
            GatewayResponse with current status
        """
        if not transaction_id:
            raise GatewayValidationError('Transaction ID is required')

        url = urljoin(self.api_url, self.API_ENDPOINTS['status'].format(reference=transaction_id))

        try:
            response = self._get(url)
            data = response.json()

            if data.get('status') == 'success':
                result_data = data.get('data', {})
                status_str = result_data.get('status', 'pending')
                return GatewayResponse(
                    success=True,
                    transaction_id=result_data.get('transaction_id') or result_data.get('reference'),
                    status=self.map_status(status_str),
                    message=f'Transaction status: {status_str}',
                    raw_data=data,
                    reference=result_data.get('reference'),
                    amount=Decimal(str(result_data.get('amount', 0))) if result_data.get('amount') else None,
                    paid_at=self.parse_datetime(result_data.get('paid_at')),
                )
            else:
                error_message = data.get('message', 'Unknown error')
                return GatewayResponse(
                    success=False,
                    status=PaymentStatus.UNKNOWN,
                    message=f'Status check failed: {error_message}',
                    raw_data=data,
                )

        except GatewayError:
            raise
        except Exception as e:
            logger.error(f'Telebirr status check error: {str(e)}')
            raise GatewayProcessingError(f'Status check failed: {str(e)}')

    # --------------------------------------------------------------------------
    # REFUNDS
    # --------------------------------------------------------------------------

    def refund_payment(self, transaction_id: str, amount: Optional[Decimal] = None,
                       reason: Optional[str] = None) -> GatewayResponse:
        """
        Refund a previously completed payment.

        Args:
            transaction_id: The Telebirr transaction ID
            amount: Amount to refund (if None, full refund)
            reason: Reason for refund

        Returns:
            GatewayResponse with refund status
        """
        if not transaction_id:
            raise GatewayValidationError('Transaction ID is required')

        payload = {
            'transaction_id': transaction_id,
            'reason': reason or 'Refund requested',
        }
        if amount is not None:
            if amount <= 0:
                raise GatewayValidationError('Refund amount must be greater than zero')
            payload['amount'] = self.format_amount(amount)

        url = urljoin(self.api_url, self.API_ENDPOINTS['refund'])

        try:
            response = self._post(url, payload)
            data = response.json()

            if data.get('status') == 'success':
                result_data = data.get('data', {})
                refund_status = result_data.get('status', 'pending')
                return GatewayResponse(
                    success=True,
                    transaction_id=result_data.get('refund_id') or result_data.get('transaction_id'),
                    status=self.map_status(refund_status),
                    message='Refund initiated successfully',
                    raw_data=data,
                    amount=amount,
                )
            else:
                error_message = data.get('message', 'Unknown error')
                raise GatewayProcessingError(f'Refund failed: {error_message}', raw_response=data)

        except GatewayError:
            raise
        except Exception as e:
            logger.error(f'Telebirr refund error: {str(e)}')
            raise GatewayProcessingError(f'Refund failed: {str(e)}')

    # --------------------------------------------------------------------------
    # WEBHOOK HANDLING
    # --------------------------------------------------------------------------

    def handle_webhook(self, payload: bytes, headers: Dict[str, str]) -> GatewayResponse:
        """
        Handle an incoming webhook from Telebirr.

        Args:
            payload: Raw request body
            headers: Request headers

        Returns:
            GatewayResponse indicating the webhook event
        """
        try:
            data = self.parse_webhook_payload(payload)
        except GatewayWebhookError as e:
            raise GatewayWebhookError(f'Invalid webhook payload: {str(e)}')

        # Extract event type
        event = data.get('event')
        if not event:
            event = data.get('type', 'unknown')

        # Map event to internal status
        event_status_map = {
            'payment.successful': PaymentStatus.COMPLETED,
            'payment.completed': PaymentStatus.COMPLETED,
            'payment.paid': PaymentStatus.COMPLETED,
            'payment.failed': PaymentStatus.FAILED,
            'payment.cancelled': PaymentStatus.CANCELLED,
            'payment.refunded': PaymentStatus.REFUNDED,
            'payment.expired': PaymentStatus.EXPIRED,
            'payment.reversed': PaymentStatus.REVERSED,
        }
        status = event_status_map.get(event, PaymentStatus.UNKNOWN)

        # Extract transaction data
        transaction_data = data.get('data', {})
        transaction_id = transaction_data.get('transaction_id') or transaction_data.get('reference')
        reference = transaction_data.get('reference')
        amount = Decimal(str(transaction_data.get('amount', 0))) if transaction_data.get('amount') else None

        return GatewayResponse(
            success=True,
            transaction_id=transaction_id,
            status=status,
            message=f'Webhook event: {event}',
            raw_data=data,
            reference=reference,
            amount=amount,
            paid_at=self.parse_datetime(transaction_data.get('paid_at')),
        )

    def validate_webhook_signature(self, payload: bytes, signature: str, secret: Optional[str] = None) -> bool:
        """
        Validate the webhook signature using HMAC-SHA256.

        Telebirr signs webhooks with a secret key.
        The signature is provided in the 'X-Telebirr-Signature' header.

        Args:
            payload: Raw request body
            signature: The signature from the request header
            secret: Optional secret override; defaults to configured secret

        Returns:
            bool: True if signature is valid
        """
        if not signature:
            logger.warning('Missing webhook signature')
            return False

        secret_key = secret or self.secret
        if not secret_key:
            logger.warning('Webhook secret not configured. Cannot validate signatures.')
            return False

        # Telebirr uses HMAC-SHA256
        expected = hmac.new(
            secret_key.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    # --------------------------------------------------------------------------
    # ADDITIONAL UTILITY METHODS
    # --------------------------------------------------------------------------

    def get_merchant_balance(self) -> Dict[str, Any]:
        """
        Get merchant account balance from Telebirr.

        Returns:
            dict: Balance information (available, pending, currency)

        Raises:
            GatewayProcessingError: If the request fails
        """
        url = urljoin(self.api_url, self.API_ENDPOINTS['balance'])

        try:
            response = self._get(url)
            data = response.json()

            if data.get('status') == 'success':
                result_data = data.get('data', {})
                return {
                    'available': Decimal(str(result_data.get('available', 0))),
                    'pending': Decimal(str(result_data.get('pending', 0))),
                    'currency': result_data.get('currency', 'ETB'),
                }
            else:
                raise GatewayProcessingError(f'Balance check failed: {data.get("message", "Unknown error")}')

        except GatewayError:
            raise
        except Exception as e:
            logger.error(f'Telebirr balance check error: {str(e)}')
            raise GatewayProcessingError(f'Balance check failed: {str(e)}')

    def get_transaction_details(self, transaction_id: str) -> Dict[str, Any]:
        """
        Get detailed transaction information from Telebirr.

        Args:
            transaction_id: Telebirr transaction ID

        Returns:
            dict: Detailed transaction data

        Raises:
            GatewayProcessingError: If the request fails
        """
        url = urljoin(self.api_url, self.API_ENDPOINTS['transaction'].format(transaction_id=transaction_id))

        try:
            response = self._get(url)
            data = response.json()

            if data.get('status') == 'success':
                return data.get('data', {})
            else:
                raise GatewayProcessingError(f'Failed to get transaction details: {data.get("message", "Unknown error")}')

        except GatewayError:
            raise
        except Exception as e:
            logger.error(f'Telebirr transaction details error: {str(e)}')
            raise GatewayProcessingError(f'Transaction details failed: {str(e)}')

    # --------------------------------------------------------------------------
    # STATUS MAPPING
    # --------------------------------------------------------------------------

    def map_status(self, gateway_status: str) -> PaymentStatus:
        """
        Map Telebirr-specific status to internal PaymentStatus.

        Args:
            gateway_status: Raw status from Telebirr

        Returns:
            PaymentStatus: Internal status
        """
        return self.TELEBIRR_STATUS_MAP.get(gateway_status.upper(), PaymentStatus.UNKNOWN)

    # --------------------------------------------------------------------------
    # FORMAT HELPERS
    # --------------------------------------------------------------------------

    def format_amount(self, amount: Decimal) -> str:
        """
        Telebirr expects amount as a string with exactly 2 decimal places.

        Args:
            amount: Decimal amount

        Returns:
            str: Formatted amount string
        """
        return f"{amount:.2f}"

    # --------------------------------------------------------------------------
    # AVAILABILITY CHECK
    # --------------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """
        Check if Telebirr is configured and available.

        Returns:
            bool: True if TELEBIRR_API_KEY is set
        """
        return bool(getattr(settings, 'TELEBIRR_API_KEY', ''))

    @classmethod
    def get_required_config_keys(cls) -> List[str]:
        """Return required configuration keys."""
        return ['api_key', 'secret', 'merchant_id']

    # --------------------------------------------------------------------------
    # TESTING HELPERS
    # --------------------------------------------------------------------------

    @staticmethod
    def generate_test_reference() -> str:
        """
        Generate a unique test reference for sandbox payments.

        Returns:
            str: Unique reference starting with 'test_'
        """
        return f"tlb_test_{uuid.uuid4().hex[:12]}_{int(timezone.now().timestamp())}"

    @staticmethod
    def get_sandbox_settings() -> Dict[str, str]:
        """
        Get sandbox test settings for development.

        Returns:
            dict: Sandbox API keys and settings
        """
        return {
            'api_key': 'sandbox_xxxxxxxxxxxxxxxxxxxxxxxx',
            'secret': 'sandbox_secret_xxxxxxxxxxxxxxxxxxxxxxxx',
            'merchant_id': 'sandbox_merchant_001',
            'api_url': 'https://sandbox-api.telebirr.et/v1',
        }

    # --------------------------------------------------------------------------
    # ERROR HANDLING OVERRIDES
    # --------------------------------------------------------------------------

    def _handle_api_error(self, response: requests.Response) -> None:
        """
        Handle Telebirr-specific API errors.

        Args:
            response: requests.Response object

        Raises:
            GatewayError: With appropriate error type
        """
        try:
            data = response.json()
            message = data.get('message', 'Unknown error')
            code = data.get('code')
        except Exception:
            message = response.text
            code = None

        if response.status_code == 401 or response.status_code == 403:
            raise GatewayAuthError(f'Authentication error: {message}', code=code)
        elif response.status_code == 404:
            raise GatewayValidationError(f'Resource not found: {message}', code=code)
        elif response.status_code == 429:
            raise GatewayError(f'Rate limit exceeded: {message}', code='rate_limit')
        elif 400 <= response.status_code < 500:
            raise GatewayValidationError(f'Validation error: {message}', code=code)
        else:
            raise GatewayError(f'Telebirr API error: {message}', code=code or f'http_{response.status_code}')

    def _request(self, method: str, url: str, data: Optional[Dict] = None,
                 params: Optional[Dict] = None, headers: Optional[Dict] = None,
                 timeout: Optional[int] = None) -> requests.Response:
        """Override to add Telebirr-specific error handling."""
        try:
            response = super()._request(method, url, data, params, headers, timeout)
            if response.status_code >= 400:
                self._handle_api_error(response)
            return response
        except (GatewayTimeoutError, GatewayConnectionError):
            raise
        except GatewayAuthError:
            raise
        except GatewayValidationError:
            raise
        except GatewayError:
            raise
        except Exception as e:
            logger.error(f'Unexpected error in Telebirr request: {str(e)}')
            raise GatewayError(f'Unexpected error: {str(e)}')