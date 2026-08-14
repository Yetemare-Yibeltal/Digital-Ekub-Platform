"""
Test payment gateway for development and testing.

This gateway simulates payment processing without making real API calls.
It is designed for use in development, staging, and testing environments.

Features:
- Configurable success/failure rates (by default 100% success)
- Simulated processing delays (configurable)
- Predefined responses for different scenarios
- Method to force specific outcomes (success, failure, timeout, etc.)
- Comprehensive logging of all operations
- Support for testing webhook handling
- Support for testing refunds

This gateway should NOT be used in production environments.
"""

import logging
import time
import json
import random
import uuid
from decimal import Decimal
from typing import Dict, Any, Optional, Union, List, Tuple, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field

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
# TEST GATEWAY IMPLEMENTATION
# ============================================================================

class TestGateway(BaseGateway):
    """
    Test payment gateway for development and testing.

    This gateway simulates payment processing with configurable behaviors.
    It is useful for testing payment flows without using real money.

    Configuration keys (in settings or passed to constructor):
    - default_success: Whether payments succeed by default (default: True)
    - success_rate: Percentage of success (0-100, default: 100)
    - processing_delay: Simulated processing delay in seconds (default: 1)
    - response_mode: 'immediate', 'delayed', 'async' (default: 'immediate')
    - webhook_support: Whether to simulate webhooks (default: True)
    - enable_logging: Whether to log detailed operation (default: True)
    - mock_responses: Dictionary of mock responses for specific references
    """

    GATEWAY_NAME = 'test'
    SUPPORTED_CURRENCIES = ('ETB', 'USD', 'EUR', 'GBP')
    MAX_RETRIES = 3

    # Internal state for tracking transactions
    _transactions: Dict[str, Dict[str, Any]] = {}
    _webhook_queue: List[Dict[str, Any]] = []

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the test gateway with configuration.

        Args:
            config: Dictionary with test gateway settings
        """
        super().__init__(config)

        # Default configuration
        self.default_success = self.config.get('default_success', True)
        self.success_rate = self.config.get('success_rate', 100)
        self.processing_delay = self.config.get('processing_delay', 1)
        self.response_mode = self.config.get('response_mode', 'immediate')
        self.webhook_support = self.config.get('webhook_support', True)
        self.enable_logging = self.config.get('enable_logging', True)
        self.mock_responses = self.config.get('mock_responses', {})

        # Validate configuration
        self._validate_config()

        # Reset state
        self._transactions = {}
        self._webhook_queue = []

        logger.info(f'Test gateway initialized (success_rate={self.success_rate}%, delay={self.processing_delay}s)')

    def _validate_config(self) -> None:
        """Validate configuration values."""
        if not 0 <= self.success_rate <= 100:
            raise GatewayConfigError('success_rate must be between 0 and 100')

        if self.processing_delay < 0:
            raise GatewayConfigError('processing_delay must be non-negative')

        if self.response_mode not in ['immediate', 'delayed', 'async']:
            raise GatewayConfigError(f'Invalid response_mode: {self.response_mode}')

    # --------------------------------------------------------------------------
    # CORE PAYMENT METHODS
    # --------------------------------------------------------------------------

    def process_payment(self, amount: Decimal, currency: str, reference: str,
                        description: str, customer_email: str, customer_phone: Optional[str] = None,
                        callback_url: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> GatewayResponse:
        """
        Simulate processing a payment.

        Args:
            amount: Amount to charge
            currency: Currency code
            reference: Unique reference
            description: Payment description
            customer_email: Customer email
            customer_phone: Optional customer phone
            callback_url: Optional callback URL
            metadata: Additional metadata

        Returns:
            GatewayResponse: Simulated response
        """
        if currency not in self.SUPPORTED_CURRENCIES:
            raise GatewayValidationError(f'Unsupported currency: {currency}')

        if amount <= 0:
            raise GatewayValidationError('Amount must be greater than zero')

        # Generate a simulated transaction ID
        transaction_id = f"test_txn_{uuid.uuid4().hex[:8]}"

        # Check if there is a mock response for this reference
        if reference in self.mock_responses:
            mock = self.mock_responses[reference]
            if self.enable_logging:
                logger.info(f'Test gateway using mock response for reference {reference}')
            return self._create_response_from_mock(mock, reference, transaction_id, amount)

        # Determine if the payment should succeed
        should_succeed = self._should_succeed()

        # Simulate processing delay
        if self.response_mode in ['delayed', 'async'] and self.processing_delay > 0:
            if self.enable_logging:
                logger.info(f'Test gateway simulating delay of {self.processing_delay}s')
            time.sleep(self.processing_delay)

        # Store transaction
        self._store_transaction(transaction_id, {
            'reference': reference,
            'amount': float(amount),
            'currency': currency,
            'description': description,
            'customer_email': customer_email,
            'customer_phone': customer_phone,
            'status': 'completed' if should_succeed else 'failed',
            'created_at': timezone.now().isoformat(),
            'metadata': metadata or {},
        })

        # Prepare response
        if should_succeed:
            status = PaymentStatus.COMPLETED
            message = 'Payment processed successfully (test mode)'
            success = True
        else:
            status = PaymentStatus.FAILED
            message = 'Payment failed (test mode)'
            success = False

        # Simulate webhook if enabled
        if self.webhook_support:
            self._queue_webhook(transaction_id, reference, status, amount)

        if self.enable_logging:
            logger.info(f'Test gateway payment: {reference} -> {status.value}')

        return GatewayResponse(
            success=success,
            transaction_id=transaction_id,
            status=status,
            message=message,
            raw_data={
                'simulated': True,
                'test_mode': 'test_gateway',
                'transaction_id': transaction_id,
                'reference': reference,
                'amount': float(amount),
                'currency': currency,
                'delay_applied': self.processing_delay if self.response_mode in ['delayed', 'async'] else 0,
                'webhook_queued': self.webhook_support,
            },
            reference=reference,
            amount=amount,
            paid_at=timezone.now().isoformat() if should_succeed else None,
        )

    def check_status(self, transaction_id: str) -> GatewayResponse:
        """
        Check the status of a transaction.

        Args:
            transaction_id: The transaction ID

        Returns:
            GatewayResponse: Status response
        """
        if not transaction_id:
            raise GatewayValidationError('Transaction ID is required')

        # Look up transaction
        txn = self._get_transaction(transaction_id)

        if txn is None:
            # If not found, return unknown status
            return GatewayResponse(
                success=False,
                transaction_id=transaction_id,
                status=PaymentStatus.UNKNOWN,
                message=f'Transaction {transaction_id} not found',
                raw_data={'error': 'not_found'},
                reference=transaction_id,
            )

        # Determine status from stored data
        status_str = txn.get('status', 'pending')
        status = self.map_status(status_str)
        amount = Decimal(str(txn.get('amount', 0)))

        return GatewayResponse(
            success=True,
            transaction_id=transaction_id,
            status=status,
            message=f'Transaction status: {status_str}',
            raw_data=txn,
            reference=txn.get('reference'),
            amount=amount,
            paid_at=txn.get('paid_at'),
        )

    def refund_payment(self, transaction_id: str, amount: Optional[Decimal] = None,
                       reason: Optional[str] = None) -> GatewayResponse:
        """
        Simulate a refund.

        Args:
            transaction_id: Transaction ID
            amount: Amount to refund (full if None)
            reason: Refund reason

        Returns:
            GatewayResponse: Refund response
        """
        if not transaction_id:
            raise GatewayValidationError('Transaction ID is required')

        txn = self._get_transaction(transaction_id)

        if txn is None:
            return GatewayResponse(
                success=False,
                transaction_id=transaction_id,
                status=PaymentStatus.UNKNOWN,
                message=f'Transaction {transaction_id} not found',
                raw_data={'error': 'not_found'},
            )

        # Determine refund amount
        full_amount = Decimal(str(txn.get('amount', 0)))
        refund_amount = amount if amount is not None else full_amount

        if refund_amount > full_amount:
            raise GatewayValidationError('Refund amount cannot exceed transaction amount')

        if refund_amount <= 0:
            raise GatewayValidationError('Refund amount must be greater than zero')

        # Update transaction status
        txn['status'] = 'refunded'
        txn['refunded_at'] = timezone.now().isoformat()
        txn['refund_amount'] = float(refund_amount)
        txn['refund_reason'] = reason or 'Refund requested'
        self._store_transaction(transaction_id, txn)

        if self.enable_logging:
            logger.info(f'Test gateway refund: {transaction_id} -> {refund_amount}')

        return GatewayResponse(
            success=True,
            transaction_id=transaction_id,
            status=PaymentStatus.REFUNDED,
            message=f'Refund of {refund_amount} processed (test mode)',
            raw_data={
                'simulated': True,
                'refund_amount': float(refund_amount),
                'refund_reason': reason,
                'refunded_at': txn['refunded_at'],
            },
            reference=txn.get('reference'),
            amount=refund_amount,
        )

    def handle_webhook(self, payload: bytes, headers: Dict[str, str]) -> GatewayResponse:
        """
        Handle an incoming webhook.

        Args:
            payload: Raw request body
            headers: Request headers

        Returns:
            GatewayResponse: Webhook response
        """
        try:
            data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise GatewayWebhookError(f'Invalid JSON payload: {str(e)}')

        # Extract event type
        event = data.get('event', 'unknown')
        transaction_id = data.get('transaction_id')
        reference = data.get('reference')
        status_str = data.get('status', 'pending')
        status = self.map_status(status_str)

        # Validate signature if present
        signature = headers.get('X-Test-Signature', '')
        if signature:
            # For test, accept any non-empty signature
            if not self.validate_webhook_signature(payload, signature):
                raise GatewayWebhookError('Invalid signature')

        if self.enable_logging:
            logger.info(f'Test gateway webhook: event={event}, transaction={transaction_id}')

        return GatewayResponse(
            success=True,
            transaction_id=transaction_id,
            status=status,
            message=f'Webhook processed: {event}',
            raw_data=data,
            reference=reference,
            amount=Decimal(str(data.get('amount', 0))) if data.get('amount') else None,
            paid_at=data.get('paid_at'),
        )

    def validate_webhook_signature(self, payload: bytes, signature: str, secret: Optional[str] = None) -> bool:
        """
        Validate webhook signature.

        For test gateway, we accept any non-empty signature.

        Args:
            payload: Raw request body
            signature: The signature
            secret: Optional secret

        Returns:
            bool: True if signature is non-empty
        """
        if not signature:
            return False
        return True

    # --------------------------------------------------------------------------
    # ADMIN AND TESTING METHODS
    # --------------------------------------------------------------------------

    def set_response_mode(self, mode: str) -> None:
        """
        Set the response mode.

        Args:
            mode: 'immediate', 'delayed', 'async'
        """
        if mode not in ['immediate', 'delayed', 'async']:
            raise ValueError(f'Invalid mode: {mode}')
        self.response_mode = mode
        logger.info(f'Test gateway response mode set to {mode}')

    def set_success_rate(self, rate: int) -> None:
        """
        Set the success rate.

        Args:
            rate: Percentage (0-100)
        """
        if not 0 <= rate <= 100:
            raise ValueError('Rate must be between 0 and 100')
        self.success_rate = rate
        logger.info(f'Test gateway success rate set to {rate}%')

    def set_processing_delay(self, seconds: float) -> None:
        """
        Set the simulated processing delay.

        Args:
            seconds: Delay in seconds
        """
        if seconds < 0:
            raise ValueError('Delay must be non-negative')
        self.processing_delay = seconds
        logger.info(f'Test gateway processing delay set to {seconds}s')

    def set_mock_response(self, reference: str, response: Dict[str, Any]) -> None:
        """
        Set a mock response for a specific reference.

        Args:
            reference: Payment reference
            response: Mock response dict with 'status', 'message', etc.
        """
        self.mock_responses[reference] = response
        logger.info(f'Test gateway mock response set for {reference}')

    def clear_mock_responses(self) -> None:
        """Clear all mock responses."""
        self.mock_responses = {}
        logger.info('Test gateway mock responses cleared')

    def get_transaction(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """
        Get transaction details.

        Args:
            transaction_id: Transaction ID

        Returns:
            dict or None: Transaction details
        """
        return self._get_transaction(transaction_id)

    def get_all_transactions(self) -> List[Dict[str, Any]]:
        """
        Get all transactions.

        Returns:
            List[dict]: All stored transactions
        """
        return list(self._transactions.values())

    def get_pending_webhooks(self) -> List[Dict[str, Any]]:
        """
        Get pending webhook events.

        Returns:
            List[dict]: Queue of pending webhook events
        """
        return self._webhook_queue.copy()

    def clear_transactions(self) -> None:
        """Clear all stored transactions."""
        self._transactions = {}
        logger.info('Test gateway transactions cleared')

    def clear_webhooks(self) -> None:
        """Clear webhook queue."""
        self._webhook_queue = []
        logger.info('Test gateway webhook queue cleared')

    def reset_state(self) -> None:
        """Reset all state (transactions, webhooks, mock responses)."""
        self._transactions = {}
        self._webhook_queue = []
        self.mock_responses = {}
        logger.info('Test gateway state reset')

    def process_single_payment(self, amount: Decimal, currency: str = 'ETB',
                              description: str = 'Test payment') -> GatewayResponse:
        """
        Convenience method to process a single payment with auto-generated reference.

        Args:
            amount: Payment amount
            currency: Currency (default: ETB)
            description: Payment description

        Returns:
            GatewayResponse: Payment response
        """
        reference = f"test_{uuid.uuid4().hex[:8]}"
        return self.process_payment(
            amount=amount,
            currency=currency,
            reference=reference,
            description=description,
            customer_email='test@example.com',
        )

    # --------------------------------------------------------------------------
    # INTERNAL HELPER METHODS
    # --------------------------------------------------------------------------

    def _should_succeed(self) -> bool:
        """
        Determine if a payment should succeed.

        Returns:
            bool: True if should succeed
        """
        if not self.default_success:
            return False
        return random.randint(0, 100) < self.success_rate

    def _store_transaction(self, transaction_id: str, data: Dict[str, Any]) -> None:
        """Store a transaction."""
        self._transactions[transaction_id] = data

    def _get_transaction(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """Get a stored transaction."""
        return self._transactions.get(transaction_id)

    def _queue_webhook(self, transaction_id: str, reference: str,
                       status: PaymentStatus, amount: Decimal) -> None:
        """Queue a webhook event."""
        if not self.webhook_support:
            return
        self._webhook_queue.append({
            'event': f'payment.{status.value}',
            'transaction_id': transaction_id,
            'reference': reference,
            'status': status.value,
            'amount': float(amount),
            'timestamp': timezone.now().isoformat(),
        })

    def _create_response_from_mock(self, mock: Dict[str, Any],
                                   reference: str, transaction_id: str,
                                   amount: Decimal) -> GatewayResponse:
        """
        Create a GatewayResponse from a mock definition.

        Args:
            mock: Mock response dict
            reference: Payment reference
            transaction_id: Transaction ID
            amount: Payment amount

        Returns:
            GatewayResponse: Response from mock
        """
        status_str = mock.get('status', 'completed')
        status = self.map_status(status_str)
        success = mock.get('success', True if status_str == 'completed' else False)
        message = mock.get('message', f'Mock response for {reference}')
        raw_data = mock.get('raw_data', {})

        return GatewayResponse(
            success=success,
            transaction_id=mock.get('transaction_id', transaction_id),
            status=status,
            message=message,
            raw_data=raw_data,
            reference=reference,
            amount=amount,
            paid_at=mock.get('paid_at'),
        )

    # --------------------------------------------------------------------------
    # STATUS MAPPING
    # --------------------------------------------------------------------------

    def map_status(self, gateway_status: str) -> PaymentStatus:
        """
        Map test status to internal PaymentStatus.

        Args:
            gateway_status: Status string

        Returns:
            PaymentStatus: Internal status
        """
        mapping = {
            'pending': PaymentStatus.PENDING,
            'processing': PaymentStatus.PROCESSING,
            'completed': PaymentStatus.COMPLETED,
            'success': PaymentStatus.COMPLETED,
            'failed': PaymentStatus.FAILED,
            'cancelled': PaymentStatus.CANCELLED,
            'refunded': PaymentStatus.REFUNDED,
            'expired': PaymentStatus.EXPIRED,
            'reversed': PaymentStatus.REVERSED,
        }
        return mapping.get(gateway_status.lower(), PaymentStatus.UNKNOWN)

    # --------------------------------------------------------------------------
    # FORMAT HELPERS
    # --------------------------------------------------------------------------

    def format_amount(self, amount: Decimal) -> str:
        """Format amount for display."""
        return f"{amount:.2f}"

    # --------------------------------------------------------------------------
    # AVAILABILITY CHECK
    # --------------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """
        Test gateway is always available.

        Returns:
            bool: True
        """
        return True

    @classmethod
    def get_required_config_keys(cls) -> List[str]:
        """Return required configuration keys (none for test gateway)."""
        return []

    # --------------------------------------------------------------------------
    # TESTING HELPERS
    # --------------------------------------------------------------------------

    @staticmethod
    def generate_test_reference(prefix: str = 'TEST') -> str:
        """
        Generate a test reference.

        Args:
            prefix: Prefix for the reference

        Returns:
            str: Unique test reference
        """
        import uuid
        return f"{prefix}_{uuid.uuid4().hex[:8].upper()}"

    @staticmethod
    def get_test_scenarios() -> Dict[str, Dict[str, Any]]:
        """
        Get predefined test scenarios.

        Returns:
            dict: Test scenarios with names and configurations
        """
        return {
            'success': {
                'default_success': True,
                'success_rate': 100,
                'response_mode': 'immediate',
                'description': 'All payments succeed immediately'
            },
            'failure': {
                'default_success': False,
                'success_rate': 0,
                'response_mode': 'immediate',
                'description': 'All payments fail immediately'
            },
            'random': {
                'default_success': True,
                'success_rate': 50,
                'response_mode': 'immediate',
                'description': 'Random success/failure'
            },
            'delayed_success': {
                'default_success': True,
                'success_rate': 100,
                'response_mode': 'delayed',
                'processing_delay': 3,
                'description': 'All payments succeed after delay'
            },
            'delayed_failure': {
                'default_success': False,
                'success_rate': 0,
                'response_mode': 'delayed',
                'processing_delay': 3,
                'description': 'All payments fail after delay'
            },
            'async': {
                'default_success': True,
                'success_rate': 100,
                'response_mode': 'async',
                'processing_delay': 1,
                'description': 'Async processing with webhook'
            },
        }

    def apply_scenario(self, scenario_name: str) -> None:
        """
        Apply a predefined test scenario.

        Args:
            scenario_name: Name of the scenario (see get_test_scenarios)
        """
        scenarios = self.get_test_scenarios()
        if scenario_name not in scenarios:
            raise ValueError(f'Unknown scenario: {scenario_name}')

        scenario = scenarios[scenario_name]
        for key, value in scenario.items():
            if hasattr(self, key):
                setattr(self, key, value)

        logger.info(f'Applied test scenario: {scenario_name} ({scenario["description"]})')

    # --------------------------------------------------------------------------
    # WEBHOOK REGISTRATION (Not applicable)
    # --------------------------------------------------------------------------

    def register_webhook(self, webhook_url: str, events: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Register a webhook (test mode).

        Args:
            webhook_url: Webhook URL
            events: Events to subscribe to

        Returns:
            dict: Registration response
        """
        if self.enable_logging:
            logger.info(f'Test gateway webhook registered: {webhook_url}')
        return {
            'status': 'registered',
            'webhook_url': webhook_url,
            'events': events or ['*'],
            'registered_at': timezone.now().isoformat(),
        }

    # --------------------------------------------------------------------------
    # STRING REPRESENTATION
    # --------------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<TestGateway success_rate={self.success_rate}% mode={self.response_mode}>"

    def __str__(self) -> str:
        return f"Test gateway ({self.success_rate}% success, {self.response_mode})"