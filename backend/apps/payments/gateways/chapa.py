"""
Chapa payment gateway implementation.

Chapa is a leading Ethiopian payment gateway supporting:
- Telebirr (mobile money)
- Bank transfers
- Card payments
- QR code payments

This module provides a complete integration with the Chapa API,
including payment initialization, status checks, refunds,
webhook handling, and signature verification.

Documentation: https://developer.chapa.co/docs
"""

import json
import logging
import hashlib
import hmac
import uuid
import os
from decimal import Decimal
from typing import Dict, Any, Optional, Union, List, Tuple
from urllib.parse import urljoin
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
# CHAPA GATEWAY IMPLEMENTATION
# ============================================================================

class ChapaGateway(BaseGateway):
    """
    Chapa payment gateway implementation.

    Supports:
    - Payment initialization with redirect or QR code
    - Payment verification (status check)
    - Full and partial refunds
    - Webhook handling with signature verification
    - Sandbox and production modes

    Configuration keys (in settings or passed to constructor):
    - api_key: Your Chapa secret key (from environment variable)
    - public_key: Your Chapa public key (from environment variable)
    - webhook_secret: Secret for webhook signature verification
    - api_url: Base API URL (default: https://api.chapa.co/v1)
    - timeout: Request timeout in seconds (default: 30)

    For sandbox testing, set api_url to the sandbox endpoint.
    """

    GATEWAY_NAME = 'chapa'
    SUPPORTED_CURRENCIES = ('ETB', 'USD')
    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 0.5
    TIMEOUT = 30

    # Chapa API endpoints
    API_ENDPOINTS = {
        'initialize': 'transactions/initialize',
        'verify': 'transactions/verify/{reference}',
        'refund': 'transactions/refund',
        'status': 'transactions/status/{transaction_id}',
        'webhook': 'webhooks',
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Chapa gateway with configuration.

        Args:
            config: Dictionary with 'api_key', 'public_key', 'webhook_secret', etc.
        """
        super().__init__(config)

        # Extract configuration from environment or passed config
        self.api_key = self.config.get('api_key') or os.environ.get('CHAPA_SECRET_KEY', '')
        self.public_key = self.config.get('public_key') or os.environ.get('CHAPA_PUBLIC_KEY', '')
        self.webhook_secret = self.config.get('webhook_secret') or os.environ.get('CHAPA_WEBHOOK_SECRET', '')
        self.api_url = self.config.get('api_url', os.environ.get('CHAPA_API_URL', 'https://api.chapa.co/v1'))
        self.timeout = self.config.get('timeout', 30)
        self.sandbox = self.config.get('sandbox', False)

        # Sanitize API URL
        self.api_url = self.api_url.rstrip('/')

        # Validate required config
        self._validate_config()

        logger.info(f'Chapa gateway initialized (sandbox={self.sandbox})')

    def _validate_config(self) -> None:
        """Validate that required configuration is present."""
        if not self.api_key:
            raise GatewayConfigError(
                'Chapa API key is required. Set CHAPA_SECRET_KEY in environment variables or pass in config.'
            )

        if self.sandbox:
            if self.api_key == 'your-placeholder':
                logger.warning('Using default sandbox API key. This is insecure for production.')
        else:
            if self.api_key.startswith('your-placeholder'):
                logger.warning('Using test API key in production mode. Set CHAPA_SECRET_KEY to a production key.')

    def get_headers(self) -> Dict[str, str]:
        """Return headers for Chapa API requests."""
        headers = super().get_headers()
        headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    # --------------------------------------------------------------------------
    # PAYMENT PROCESSING
    # --------------------------------------------------------------------------

    def process_payment(self, amount: Decimal, currency: str, reference: str,
                        description: str, customer_email: str, customer_phone: Optional[str] = None,
                        callback_url: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> GatewayResponse:
        """
        Initialize a payment with Chapa.

        Args:
            amount: Amount to charge
            currency: Currency code (ETB, USD)
            reference: Unique reference for this payment (must be unique)
            description: Description of the payment
            customer_email: Customer email
            customer_phone: Optional phone number
            callback_url: Optional URL for redirection after payment
            metadata: Additional data to pass to Chapa

        Returns:
            GatewayResponse with transaction_id, checkout_url, status, etc.
        """
        if currency not in self.SUPPORTED_CURRENCIES:
            raise GatewayValidationError(f'Unsupported currency: {currency}. Supported: {self.SUPPORTED_CURRENCIES}')

        if amount <= 0:
            raise GatewayValidationError('Amount must be greater than zero')

        payload = {
            'amount': self.format_amount(amount),
            'currency': currency,
            'tx_ref': reference,
            'email': customer_email,
            'phone_number': customer_phone or '',
            'callback_url': callback_url or self.build_callback_url(),
            'return_url': callback_url or self.build_callback_url(),
            'customization': {
                'title': 'Digital Ekub Platform',
                'description': description[:200],
            },
            'meta': metadata or {},
        }

        if self.sandbox:
            payload['sandbox'] = True

        url = urljoin(self.api_url, self.API_ENDPOINTS['initialize'])

        try:
            response = self._post(url, payload)
            data = response.json()

            if data.get('status') == 'success':
                result_data = data.get('data', {})
                return GatewayResponse(
                    success=True,
                    transaction_id=result_data.get('transaction_id') or result_data.get('tx_ref'),
                    status=self.map_status(result_data.get('status', 'pending')),
                    message='Payment initialized successfully',
                    raw_data=data,
                    reference=result_data.get('tx_ref'),
                    amount=amount,
                )
            else:
                error_message = data.get('message', 'Unknown error')
                raise GatewayProcessingError(f'Chapa initialization failed: {error_message}', raw_response=data)

        except GatewayError:
            raise
        except Exception as e:
            logger.error(f'Chapa payment initialization error: {str(e)}')
            raise GatewayProcessingError(f'Payment initialization failed: {str(e)}')

    # --------------------------------------------------------------------------
    # PAYMENT VERIFICATION AND STATUS CHECK
    # --------------------------------------------------------------------------

    def check_status(self, transaction_id: str) -> GatewayResponse:
        """
        Check the status of a transaction with Chapa.

        Args:
            transaction_id: The Chapa transaction ID (or reference)

        Returns:
            GatewayResponse with current status
        """
        if not transaction_id:
            raise GatewayValidationError('Transaction ID is required')

        url = urljoin(self.api_url, self.API_ENDPOINTS['verify'].format(reference=transaction_id))

        try:
            response = self._get(url)
            data = response.json()

            if data.get('status') == 'success':
                result_data = data.get('data', {})
                status_str = result_data.get('status', 'pending')
                return GatewayResponse(
                    success=True,
                    transaction_id=result_data.get('transaction_id') or result_data.get('tx_ref'),
                    status=self.map_status(status_str),
                    message=f'Transaction status: {status_str}',
                    raw_data=data,
                    reference=result_data.get('tx_ref'),
                    amount=Decimal(str(result_data.get('amount', 0))),
                    paid_at=self.parse_datetime(result_data.get('created_at')),
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
            logger.error(f'Chapa status check error: {str(e)}')
            raise GatewayProcessingError(f'Status check failed: {str(e)}')

    # --------------------------------------------------------------------------
    # REFUNDS
    # --------------------------------------------------------------------------

    def refund_payment(self, transaction_id: str, amount: Optional[Decimal] = None,
                       reason: Optional[str] = None) -> GatewayResponse:
        """
        Refund a previously completed payment.

        Args:
            transaction_id: The Chapa transaction ID
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
                    transaction_id=result_data.get('transaction_id') or result_data.get('refund_id'),
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
            logger.error(f'Chapa refund error: {str(e)}')
            raise GatewayProcessingError(f'Refund failed: {str(e)}')

    # --------------------------------------------------------------------------
    # WEBHOOK HANDLING
    # --------------------------------------------------------------------------

    def handle_webhook(self, payload: bytes, headers: Dict[str, str]) -> GatewayResponse:
        """
        Handle an incoming webhook from Chapa.

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

        event = data.get('event')
        if not event:
            raise GatewayWebhookError('Missing event type in webhook payload')

        event_status_map = {
            'payment.completed': PaymentStatus.COMPLETED,
            'payment.failed': PaymentStatus.FAILED,
            'payment.cancelled': PaymentStatus.CANCELLED,
            'payment.refunded': PaymentStatus.REFUNDED,
            'payment.reversed': PaymentStatus.REVERSED,
            'payment.expired': PaymentStatus.EXPIRED,
        }
        status = event_status_map.get(event, PaymentStatus.UNKNOWN)

        transaction_data = data.get('data', {})
        transaction_id = transaction_data.get('transaction_id') or transaction_data.get('tx_ref')
        reference = transaction_data.get('tx_ref')
        amount = Decimal(str(transaction_data.get('amount', 0))) if transaction_data.get('amount') else None

        return GatewayResponse(
            success=True,
            transaction_id=transaction_id,
            status=status,
            message=f'Webhook event: {event}',
            raw_data=data,
            reference=reference,
            amount=amount,
            paid_at=self.parse_datetime(transaction_data.get('created_at')),
        )

    def validate_webhook_signature(self, payload: bytes, signature: str, secret: Optional[str] = None) -> bool:
        """
        Validate the webhook signature using HMAC-SHA256.

        Chapa signs webhooks with a secret key.
        The signature is provided in the 'x-chapa-signature' header.

        Args:
            payload: Raw request body
            signature: The signature from the request header
            secret: Optional secret override; defaults to configured webhook_secret

        Returns:
            bool: True if signature is valid
        """
        if not signature:
            logger.warning('Missing webhook signature')
            return False

        secret_key = secret or self.webhook_secret
        if not secret_key:
            logger.warning('Webhook secret not configured. Cannot validate signatures.')
            return False

        expected = hmac.new(
            secret_key.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    # --------------------------------------------------------------------------
    # ADDITIONAL UTILITY METHODS
    # --------------------------------------------------------------------------

    def generate_checkout_url(self, reference: str, amount: Decimal, description: str,
                              customer_email: str, customer_phone: Optional[str] = None) -> str:
        """
        Generate a direct checkout URL for Chapa.

        This is a convenience method that combines process_payment and
        returns the checkout URL directly.

        Args:
            reference: Unique payment reference
            amount: Payment amount
            description: Payment description
            customer_email: Customer email
            customer_phone: Optional customer phone

        Returns:
            str: Checkout URL for redirection

        Raises:
            GatewayProcessingError: If payment initialization fails
        """
        response = self.process_payment(
            amount=amount,
            currency='ETB',
            reference=reference,
            description=description,
            customer_email=customer_email,
            customer_phone=customer_phone,
        )
        if response.success and response.raw_data.get('data', {}).get('checkout_url'):
            return response.raw_data['data']['checkout_url']
        else:
            raise GatewayProcessingError('Failed to generate checkout URL')

    def verify_payment(self, reference: str) -> GatewayResponse:
        """
        Verify payment status using the reference.

        This is a wrapper around check_status for convenience.

        Args:
            reference: The payment reference (tx_ref)

        Returns:
            GatewayResponse with status
        """
        return self.check_status(reference)

    def get_transaction_details(self, transaction_id: str) -> Dict[str, Any]:
        """
        Get detailed transaction information from Chapa.

        Args:
            transaction_id: Chapa transaction ID

        Returns:
            dict: Detailed transaction data

        Raises:
            GatewayProcessingError: If the request fails
        """
        response = self.check_status(transaction_id)
        if response.success:
            return response.raw_data.get('data', {})
        else:
            raise GatewayProcessingError(f'Failed to get transaction details: {response.message}')

    # --------------------------------------------------------------------------
    # STATUS MAPPING
    # --------------------------------------------------------------------------

    def map_status(self, gateway_status: str) -> PaymentStatus:
        """
        Map Chapa-specific status to internal PaymentStatus.

        Chapa statuses: 'pending', 'successful', 'failed', 'cancelled', 'refunded'

        Args:
            gateway_status: Raw status from Chapa

        Returns:
            PaymentStatus: Internal status
        """
        mapping = {
            'pending': PaymentStatus.PENDING,
            'processing': PaymentStatus.PROCESSING,
            'successful': PaymentStatus.COMPLETED,
            'completed': PaymentStatus.COMPLETED,
            'failed': PaymentStatus.FAILED,
            'cancelled': PaymentStatus.CANCELLED,
            'refunded': PaymentStatus.REFUNDED,
            'reversed': PaymentStatus.REVERSED,
            'expired': PaymentStatus.EXPIRED,
        }
        return mapping.get(gateway_status.lower(), PaymentStatus.UNKNOWN)

    # --------------------------------------------------------------------------
    # FORMAT HELPERS
    # --------------------------------------------------------------------------

    def format_amount(self, amount: Decimal) -> str:
        """
        Chapa expects amount as a string with exactly 2 decimal places.

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
        Check if Chapa is configured and available.

        Returns:
            bool: True if CHAPA_SECRET_KEY is set in environment
        """
        return bool(os.environ.get('CHAPA_SECRET_KEY', ''))

    @classmethod
    def get_required_config_keys(cls) -> List[str]:
        """Return required configuration keys."""
        return ['api_key']

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
        return f"test_{uuid.uuid4().hex[:12]}_{int(timezone.now().timestamp())}"

    @staticmethod
    def get_sandbox_keys() -> Dict[str, str]:
        """
        Get sandbox test keys for development.

        These are placeholder keys that should be replaced with actual
        sandbox credentials from Chapa dashboard. Do not commit real keys.

        Returns:
            dict: Sandbox API keys (placeholders)
        """
        return {
            'api_key': os.environ.get('CHAPA_SECRET_KEY', 'your-chapa-secret-key-here'),
            'public_key': os.environ.get('CHAPA_PUBLIC_KEY', 'your-chapa-public-key-here'),
            'webhook_secret': os.environ.get('CHAPA_WEBHOOK_SECRET', 'your-chapa-webhook-secret-here'),
        }

    # --------------------------------------------------------------------------
    # WEBHOOK REGISTRATION
    # --------------------------------------------------------------------------

    def register_webhook(self, webhook_url: str, events: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Register a webhook URL with Chapa.

        Note: This feature may not be available in all Chapa plans.
        If not available, webhooks must be configured manually in the dashboard.

        Args:
            webhook_url: URL to receive webhooks
            events: List of events to subscribe to (default: all)

        Returns:
            dict: Registration response

        Raises:
            GatewayError: If registration fails
        """
        if not webhook_url:
            raise GatewayValidationError('Webhook URL is required')

        payload = {
            'url': webhook_url,
            'events': events or ['payment.completed', 'payment.failed', 'payment.refunded'],
        }

        url = urljoin(self.api_url, self.API_ENDPOINTS['webhook'])

        try:
            response = self._post(url, payload)
            data = response.json()
            if data.get('status') == 'success':
                logger.info(f'Webhook registered: {webhook_url}')
                return data.get('data', {})
            else:
                raise GatewayError(f'Webhook registration failed: {data.get("message", "Unknown error")}')
        except GatewayError:
            raise
        except Exception as e:
            logger.error(f'Webhook registration error: {str(e)}')
            raise GatewayError(f'Webhook registration failed: {str(e)}')

    # --------------------------------------------------------------------------
    # ERROR HANDLING OVERRIDES
    # --------------------------------------------------------------------------

    def _handle_api_error(self, response: requests.Response) -> None:
        """
        Handle Chapa-specific API errors.

        Chapa returns error messages in a consistent format:
        { "status": "error", "message": "Error description", "data": {} }

        Args:
            response: requests.Response object

        Raises:
            GatewayError: With appropriate error type
        """
        try:
            data = response.json()
            message = data.get('message', 'Unknown error')
        except Exception:
            message = response.text

        if response.status_code == 401 or response.status_code == 403:
            raise GatewayAuthError(f'Authentication error: {message}')
        elif response.status_code == 404:
            raise GatewayValidationError(f'Resource not found: {message}')
        elif response.status_code == 429:
            raise GatewayError(f'Rate limit exceeded: {message}', code='rate_limit')
        elif 400 <= response.status_code < 500:
            raise GatewayValidationError(f'Validation error: {message}')
        else:
            raise GatewayError(f'Chapa API error: {message}', code=f'http_{response.status_code}')

    def _request(self, method: str, url: str, data: Optional[Dict] = None,
                 params: Optional[Dict] = None, headers: Optional[Dict] = None,
                 timeout: Optional[int] = None) -> requests.Response:
        """Override to add Chapa-specific error handling."""
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
            logger.error(f'Unexpected error in Chapa request: {str(e)}')
            raise GatewayError(f'Unexpected error: {str(e)}')