"""
Bank Transfer payment gateway implementation.

This gateway handles manual bank transfer payments where users pay via
bank transfer and then confirm their payment. The system generates
payment instructions, tracks pending payments, and allows admins to
confirm receipt and complete payments.

Features:
- Generate bank transfer instructions with unique reference
- Track pending payments awaiting confirmation
- Manual payment confirmation (admin)
- Partial and full refunds
- Reconciliation support
- Payment expiry handling
- Payment reminder generation

This is a "manual" gateway where no external API calls are made;
instead, the system manages the payment lifecycle through admin actions.
"""

import logging
import uuid
import hashlib
from decimal import Decimal
from typing import Dict, Any, Optional, Union, List, Tuple
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings

from .base import (
    BaseGateway,
    GatewayResponse,
    GatewayError,
    GatewayValidationError,
    GatewayProcessingError,
    GatewayConfigError,
    PaymentStatus,
)

logger = logging.getLogger(__name__)


# ============================================================================
# BANK TRANSFER GATEWAY IMPLEMENTATION
# ============================================================================

class BankTransferGateway(BaseGateway):
    """
    Bank Transfer payment gateway for manual payments.

    This gateway does not make external API calls. It generates payment
    instructions and tracks payment statuses based on admin actions.

    Configuration keys (in settings or passed to constructor):
    - bank_name: Name of the bank (e.g., 'Commercial Bank of Ethiopia')
    - account_name: Account holder name
    - account_number: Account number
    - account_currency: Currency (default: 'ETB')
    - reference_prefix: Prefix for payment references (default: 'BT')
    - expiry_hours: Hours until payment expires (default: 48)
    - instructions_template: Template for payment instructions (optional)
    """

    GATEWAY_NAME = 'bank_transfer'
    SUPPORTED_CURRENCIES = ('ETB',)
    MAX_RETRIES = 1  # No external retries needed

    # Default bank account details (should be overridden in settings)
    DEFAULT_BANK_DETAILS = {
        'bank_name': 'Commercial Bank of Ethiopia',
        'account_name': 'Digital Ekub Platform',
        'account_number': '1000XXXXXXX',
        'branch': 'Head Office',
        'swift_code': 'CBETETAA',
        'account_currency': 'ETB',
    }

    # Status mapping for manual statuses
    BANK_TRANSFER_STATUS_MAP = {
        'pending': PaymentStatus.PENDING,
        'processing': PaymentStatus.PROCESSING,
        'completed': PaymentStatus.COMPLETED,
        'failed': PaymentStatus.FAILED,
        'cancelled': PaymentStatus.CANCELLED,
        'refunded': PaymentStatus.REFUNDED,
        'expired': PaymentStatus.EXPIRED,
        'reversed': PaymentStatus.REVERSED,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Bank Transfer gateway with configuration.

        Args:
            config: Dictionary with bank account details and settings
        """
        super().__init__(config)

        # Extract configuration with defaults
        self.bank_name = self.config.get('bank_name', self.DEFAULT_BANK_DETAILS['bank_name'])
        self.account_name = self.config.get('account_name', self.DEFAULT_BANK_DETAILS['account_name'])
        self.account_number = self.config.get('account_number', self.DEFAULT_BANK_DETAILS['account_number'])
        self.branch = self.config.get('branch', self.DEFAULT_BANK_DETAILS.get('branch', 'Head Office'))
        self.swift_code = self.config.get('swift_code', self.DEFAULT_BANK_DETAILS.get('swift_code', 'CBETETAA'))
        self.account_currency = self.config.get('account_currency', self.DEFAULT_BANK_DETAILS.get('account_currency', 'ETB'))
        self.reference_prefix = self.config.get('reference_prefix', 'BT')
        self.expiry_hours = self.config.get('expiry_hours', 48)
        self.instructions_template = self.config.get('instructions_template', None)
        self.require_confirm = self.config.get('require_confirm', True)

        # Validate configuration
        self._validate_config()

        logger.info(f'Bank Transfer gateway initialized (bank: {self.bank_name})')

    def _validate_config(self) -> None:
        """Validate that required configuration is present."""
        if not self.bank_name:
            raise GatewayConfigError('Bank name is required.')
        if not self.account_name:
            raise GatewayConfigError('Account holder name is required.')
        if not self.account_number:
            raise GatewayConfigError('Account number is required.')
        if self.account_currency not in self.SUPPORTED_CURRENCIES:
            logger.warning(f'Unsupported currency {self.account_currency}. Supported: {self.SUPPORTED_CURRENCIES}')

    # --------------------------------------------------------------------------
    # PAYMENT PROCESSING
    # --------------------------------------------------------------------------

    def process_payment(self, amount: Decimal, currency: str, reference: str,
                        description: str, customer_email: str, customer_phone: Optional[str] = None,
                        callback_url: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> GatewayResponse:
        """
        Initialize a bank transfer payment.

        This generates payment instructions and creates a pending payment
        record. The payment will remain pending until an admin confirms receipt.

        Args:
            amount: Amount to pay
            currency: Currency code (ETB only)
            reference: Unique reference for this payment
            description: Description of the payment
            customer_email: Customer email (for notifications)
            customer_phone: Optional customer phone
            callback_url: Not used for bank transfers
            metadata: Additional data

        Returns:
            GatewayResponse with payment instructions and status
        """
        if currency not in self.SUPPORTED_CURRENCIES:
            raise GatewayValidationError(f'Unsupported currency: {currency}. Bank Transfer only supports ETB.')

        if amount <= 0:
            raise GatewayValidationError('Amount must be greater than zero')

        # Generate payment instructions
        instructions = self.generate_payment_instructions(
            reference=reference,
            amount=amount,
            currency=currency,
            customer_email=customer_email,
            customer_phone=customer_phone,
            description=description
        )

        # Calculate expiry time
        expires_at = timezone.now() + timedelta(hours=self.expiry_hours)

        # Build response
        return GatewayResponse(
            success=True,
            transaction_id=reference,  # Using reference as transaction ID
            status=PaymentStatus.PENDING,
            message='Bank transfer payment initiated. Please follow the instructions.',
            raw_data={
                'instructions': instructions,
                'expires_at': expires_at.isoformat(),
                'require_confirm': self.require_confirm,
            },
            reference=reference,
            amount=amount,
        )

    def generate_payment_instructions(self, reference: str, amount: Decimal,
                                      currency: str, customer_email: str,
                                      customer_phone: Optional[str] = None,
                                      description: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate detailed payment instructions for the customer.

        Args:
            reference: Payment reference
            amount: Amount to pay
            currency: Currency code
            customer_email: Customer email
            customer_phone: Optional customer phone
            description: Payment description

        Returns:
            dict: Payment instructions with bank details and steps
        """
        # Format amount
        formatted_amount = f"{amount:.2f} {currency}"

        # Build instructions
        instructions = {
            'bank_details': {
                'bank_name': self.bank_name,
                'account_name': self.account_name,
                'account_number': self.account_number,
                'branch': self.branch,
                'swift_code': self.swift_code,
                'currency': self.account_currency,
            },
            'payment_reference': reference,
            'amount': formatted_amount,
            'description': description or f'Payment for {reference}',
            'steps': [
                f'Transfer {formatted_amount} to the bank account above.',
                f'Use the reference: {reference}',
                'Keep your transaction receipt for verification.',
                'Click "Confirm Payment" after completing the transfer.',
            ],
            'expires_at': (timezone.now() + timedelta(hours=self.expiry_hours)).isoformat(),
            'contact_info': {
                'email': 'support@ekub-platform.com',
                'phone': '+251-XXXX-XXXX',
            },
        }

        # If custom template provided, merge
        if self.instructions_template:
            instructions.update(self.instructions_template)

        # Add customer-specific info
        instructions['customer'] = {
            'email': customer_email,
            'phone': customer_phone,
        }

        return instructions

    # --------------------------------------------------------------------------
    # PAYMENT VERIFICATION AND STATUS CHECK
    # --------------------------------------------------------------------------

    def check_status(self, transaction_id: str) -> GatewayResponse:
        """
        Check the status of a bank transfer payment.

        Since bank transfers are manual, this method checks the local
        payment record status (which is updated by admin confirmation).

        Args:
            transaction_id: The payment reference

        Returns:
            GatewayResponse with current status
        """
        if not transaction_id:
            raise GatewayValidationError('Transaction ID is required')

        # This method should be used in conjunction with the Payment model
        # Since we don't have direct model access here, we return unknown status
        # with a message suggesting to check the payment record.
        return GatewayResponse(
            success=True,
            transaction_id=transaction_id,
            status=PaymentStatus.UNKNOWN,
            message='Status check must be performed on the payment record.',
            raw_data={'note': 'Bank transfer status is maintained in the local payment record.'},
            reference=transaction_id,
        )

    # --------------------------------------------------------------------------
    # REFUNDS
    # --------------------------------------------------------------------------

    def refund_payment(self, transaction_id: str, amount: Optional[Decimal] = None,
                       reason: Optional[str] = None) -> GatewayResponse:
        """
        Process a refund for a bank transfer payment.

        Bank transfer refunds are manual (processed via bank transfer).
        This method updates the payment status to refunded and provides
        instructions for the refund.

        Args:
            transaction_id: The payment reference
            amount: Amount to refund (if None, full refund)
            reason: Reason for refund

        Returns:
            GatewayResponse with refund status and instructions
        """
        if not transaction_id:
            raise GatewayValidationError('Transaction ID is required')

        if amount is not None and amount <= 0:
            raise GatewayValidationError('Refund amount must be greater than zero')

        refund_amount = amount if amount is not None else 'full amount'
        refund_instructions = {
            'method': 'Bank Transfer',
            'instructions': f'Please process a refund of {refund_amount} to the customer\'s bank account.',
            'reference': f'REF-{transaction_id}',
            'requires_manual_action': True,
        }

        return GatewayResponse(
            success=True,
            transaction_id=transaction_id,
            status=PaymentStatus.REFUNDED,
            message=f'Refund of {refund_amount} initiated for {transaction_id}',
            raw_data={
                'refund_instructions': refund_instructions,
                'amount': float(amount) if amount else None,
                'reason': reason,
            },
            reference=transaction_id,
            amount=amount,
        )

    # --------------------------------------------------------------------------
    # WEBHOOK HANDLING
    # --------------------------------------------------------------------------

    def handle_webhook(self, payload: bytes, headers: Dict[str, str]) -> GatewayResponse:
        """
        Handle webhook (not applicable for bank transfers).

        Bank transfers are manual and do not have webhook callbacks.
        This method raises an error indicating the method is not supported.

        Raises:
            GatewayError: Always raised indicating not supported
        """
        raise GatewayError('Webhooks are not supported for Bank Transfer gateway.')

    def validate_webhook_signature(self, payload: bytes, signature: str, secret: Optional[str] = None) -> bool:
        """
        Validate webhook signature (not applicable for bank transfers).

        Returns:
            bool: Always False (webhooks not supported)
        """
        logger.warning('Webhook signature validation called for Bank Transfer gateway (not applicable)')
        return False

    # --------------------------------------------------------------------------
    # ADMIN METHODS
    # --------------------------------------------------------------------------

    def confirm_payment(self, reference: str, amount_received: Decimal,
                        transaction_reference: Optional[str] = None,
                        notes: Optional[str] = None) -> GatewayResponse:
        """
        Confirm receipt of a bank transfer payment (admin action).

        Args:
            reference: Payment reference
            amount_received: Amount actually received
            transaction_reference: Bank transaction reference from customer
            notes: Additional notes

        Returns:
            GatewayResponse indicating confirmation
        """
        if not reference:
            raise GatewayValidationError('Payment reference is required')

        if amount_received <= 0:
            raise GatewayValidationError('Amount received must be greater than zero')

        return GatewayResponse(
            success=True,
            transaction_id=reference,
            status=PaymentStatus.COMPLETED,
            message=f'Payment {reference} confirmed. Amount: {amount_received:.2f}',
            raw_data={
                'amount_received': float(amount_received),
                'transaction_reference': transaction_reference,
                'notes': notes,
                'confirmed_at': timezone.now().isoformat(),
            },
            reference=reference,
            amount=amount_received,
        )

    def reject_payment(self, reference: str, reason: Optional[str] = None) -> GatewayResponse:
        """
        Reject a pending bank transfer payment (admin action).

        Args:
            reference: Payment reference
            reason: Reason for rejection

        Returns:
            GatewayResponse indicating rejection
        """
        if not reference:
            raise GatewayValidationError('Payment reference is required')

        return GatewayResponse(
            success=True,
            transaction_id=reference,
            status=PaymentStatus.FAILED,
            message=f'Payment {reference} rejected. Reason: {reason or "No reason provided"}',
            raw_data={
                'reason': reason,
                'rejected_at': timezone.now().isoformat(),
            },
            reference=reference,
        )

    def cancel_payment(self, reference: str, reason: Optional[str] = None) -> GatewayResponse:
        """
        Cancel a bank transfer payment (admin or user action).

        Args:
            reference: Payment reference
            reason: Reason for cancellation

        Returns:
            GatewayResponse indicating cancellation
        """
        if not reference:
            raise GatewayValidationError('Payment reference is required')

        return GatewayResponse(
            success=True,
            transaction_id=reference,
            status=PaymentStatus.CANCELLED,
            message=f'Payment {reference} cancelled. Reason: {reason or "Cancelled by user"}',
            raw_data={
                'reason': reason,
                'cancelled_at': timezone.now().isoformat(),
            },
            reference=reference,
        )

    def expire_payment(self, reference: str) -> GatewayResponse:
        """
        Expire a bank transfer payment that has been pending too long.

        Args:
            reference: Payment reference

        Returns:
            GatewayResponse indicating expiration
        """
        if not reference:
            raise GatewayValidationError('Payment reference is required')

        return GatewayResponse(
            success=True,
            transaction_id=reference,
            status=PaymentStatus.EXPIRED,
            message=f'Payment {reference} expired.',
            raw_data={
                'expired_at': timezone.now().isoformat(),
            },
            reference=reference,
        )

    # --------------------------------------------------------------------------
    # RECONCILIATION SUPPORT
    # --------------------------------------------------------------------------

    def generate_reconciliation_report(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """
        Generate a reconciliation report for bank transfers.

        This is a placeholder method that would typically generate a report
        of all bank transfer payments within a date range for reconciliation.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            dict: Reconciliation report data
        """
        return {
            'gateway': self.GATEWAY_NAME,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'message': 'Reconciliation report generation is not implemented in the gateway.',
            'requires_manual': True,
            'bank_details': {
                'bank_name': self.bank_name,
                'account_number': self.account_number,
            },
        }

    # --------------------------------------------------------------------------
    # NOTIFICATION HELPERS
    # --------------------------------------------------------------------------

    def generate_email_instructions(self, reference: str, amount: Decimal,
                                    currency: str, customer_email: str) -> Dict[str, Any]:
        """
        Generate email-friendly payment instructions.

        Args:
            reference: Payment reference
            amount: Payment amount
            currency: Currency code
            customer_email: Customer email

        Returns:
            dict: Email-ready instructions with subject and body
        """
        formatted_amount = f"{amount:.2f} {currency}"
        subject = f'Payment Instructions - {reference}'

        body = f"""
        Dear Customer,

        Thank you for your payment. Please follow the instructions below to complete your payment.

        Payment Reference: {reference}
        Amount: {formatted_amount}
        Currency: {currency}

        Bank Details:
        Bank: {self.bank_name}
        Account Name: {self.account_name}
        Account Number: {self.account_number}
        Branch: {self.branch}
        SWIFT Code: {self.swift_code}

        Please use the reference: {reference}

        After completing the transfer, please click the "Confirm Payment" button in the app.

        This payment will expire in {self.expiry_hours} hours.

        If you have any questions, please contact support at support@ekub-platform.com.

        Thank you for using the Digital Ekub Platform.
        """

        return {
            'subject': subject,
            'body': body,
            'to': customer_email,
        }

    def generate_sms_instructions(self, reference: str, amount: Decimal,
                                  currency: str, customer_phone: str) -> str:
        """
        Generate SMS-friendly payment instructions.

        Args:
            reference: Payment reference
            amount: Payment amount
            currency: Currency code
            customer_phone: Customer phone number

        Returns:
            str: SMS message (max 160 characters)
        """
        formatted_amount = f"{amount:.2f} {currency}"
        message = (
            f"Payment {reference}: Transfer {formatted_amount} to {self.bank_name}, "
            f"Acct {self.account_number}. Ref: {reference}. Expires in {self.expiry_hours}h."
        )
        return message[:160]

    # --------------------------------------------------------------------------
    # STATUS MAPPING
    # --------------------------------------------------------------------------

    def map_status(self, gateway_status: str) -> PaymentStatus:
        """
        Map Bank Transfer status to internal PaymentStatus.

        Args:
            gateway_status: Raw status from Bank Transfer system

        Returns:
            PaymentStatus: Internal status
        """
        return self.BANK_TRANSFER_STATUS_MAP.get(gateway_status.lower(), PaymentStatus.UNKNOWN)

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
        Bank Transfer is always available (no external configuration needed).

        Returns:
            bool: True
        """
        return True

    @classmethod
    def get_required_config_keys(cls) -> List[str]:
        """Return required configuration keys."""
        return ['bank_name', 'account_name', 'account_number']

    # --------------------------------------------------------------------------
    # UTILITY METHODS
    # --------------------------------------------------------------------------

    def generate_reference(self) -> str:
        """
        Generate a unique reference for a bank transfer payment.

        Returns:
            str: Unique reference
        """
        import uuid
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        unique_id = uuid.uuid4().hex[:8].upper()
        return f"{self.reference_prefix}-{timestamp}-{unique_id}"

    def verify_reference(self, reference: str) -> bool:
        """
        Verify that a reference is valid.

        Args:
            reference: Reference to verify

        Returns:
            bool: True if reference matches the expected pattern
        """
        import re
        pattern = rf'^{self.reference_prefix}-[0-9]{{14}}-[A-Z0-9]{{8}}$'
        return bool(re.match(pattern, reference))

    # --------------------------------------------------------------------------
    # ERROR HANDLING OVERRIDES
    # --------------------------------------------------------------------------

    def _handle_error(self, error_message: str, error_code: Optional[str] = None) -> None:
        """
        Handle errors (for consistency with other gateways).

        Args:
            error_message: Error message
            error_code: Optional error code

        Raises:
            GatewayProcessingError: Always raised
        """
        raise GatewayProcessingError(error_message, code=error_code)

    # --------------------------------------------------------------------------
    # TESTING HELPERS
    # --------------------------------------------------------------------------

    @staticmethod
    def generate_test_reference() -> str:
        """
        Generate a test reference for bank transfer payments.

        Returns:
            str: Test reference
        """
        import uuid
        return f"BT-TEST-{uuid.uuid4().hex[:8].upper()}"

    @staticmethod
    def get_test_bank_details() -> Dict[str, str]:
        """
        Get test bank account details for development.

        Returns:
            dict: Test bank account details
        """
        return {
            'bank_name': 'Test Bank',
            'account_name': 'Test Account',
            'account_number': '1000TEST0001',
            'branch': 'Test Branch',
            'swift_code': 'TESTETAA',
        }

    # --------------------------------------------------------------------------
    # WEBHOOK REGISTRATION (Not applicable)
    # --------------------------------------------------------------------------

    def register_webhook(self, webhook_url: str, events: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Register a webhook (not applicable for bank transfers).

        Raises:
            GatewayError: Always raised
        """
        raise GatewayError('Webhook registration is not supported for Bank Transfer gateway.')

    # --------------------------------------------------------------------------
    # STRING REPRESENTATION
    # --------------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<BankTransferGateway bank='{self.bank_name}' account='{self.account_number}'>"

    def __str__(self) -> str:
        return f"Bank Transfer gateway ({self.bank_name})"