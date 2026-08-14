"""
Payment gateway integrations for the Digital Ekub Platform.

This package provides integrations with various payment gateways:
- Chapa (Ethiopian payment gateway)
- Telebirr (Ethiopian mobile money)
- Bank Transfer (manual, with reconciliation)
- Future gateways can be added easily by extending the BaseGateway class.

All gateways implement a common interface defined in BaseGateway,
allowing for consistent payment processing, refunds, webhook handling,
and status checking across different providers.

The gateway factory (get_gateway) returns the appropriate gateway instance
based on the gateway name configured in the payment record.
"""

import logging
from typing import Optional, Dict, Any, Type
from decimal import Decimal
from django.conf import settings

from .base import BaseGateway, GatewayResponse, GatewayError, PaymentStatus
from .chapa import ChapaGateway
from .telebirr import TelebirrGateway
from .bank_transfer import BankTransferGateway

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gateway registry
# ---------------------------------------------------------------------------

GATEWAY_REGISTRY: Dict[str, Type[BaseGateway]] = {
    'chapa': ChapaGateway,
    'telebirr': TelebirrGateway,
    'bank_transfer': BankTransferGateway,
}


def get_gateway(gateway_name: str, config: Optional[Dict[str, Any]] = None) -> BaseGateway:
    """
    Factory function to get a payment gateway instance.

    Args:
        gateway_name: Name of the gateway ('chapa', 'telebirr', 'bank_transfer')
        config: Optional configuration overrides; defaults to settings

    Returns:
        BaseGateway: An instance of the requested gateway

    Raises:
        ValueError: If the gateway name is not supported
    """
    gateway_class = GATEWAY_REGISTRY.get(gateway_name.lower())
    if not gateway_class:
        raise ValueError(f'Unsupported gateway: {gateway_name}')

    # Merge config with default settings
    if config is None:
        config = {}

    # Get gateway-specific settings
    if gateway_name == 'chapa':
        default_config = {
            'api_key': getattr(settings, 'CHAPA_SECRET_KEY', ''),
            'public_key': getattr(settings, 'CHAPA_PUBLIC_KEY', ''),
            'webhook_secret': getattr(settings, 'CHAPA_WEBHOOK_SECRET', ''),
            'api_url': getattr(settings, 'CHAPA_API_URL', 'https://api.chapa.co/v1'),
            'timeout': getattr(settings, 'CHAPA_TIMEOUT', 30),
        }
    elif gateway_name == 'telebirr':
        default_config = {
            'api_key': getattr(settings, 'TELEBIRR_API_KEY', ''),
            'secret': getattr(settings, 'TELEBIRR_SECRET', ''),
            'merchant_id': getattr(settings, 'TELEBIRR_MERCHANT_ID', ''),
            'api_url': getattr(settings, 'TELEBIRR_API_URL', 'https://api.telebirr.et/v1'),
        }
    else:
        default_config = {}

    # Merge with provided config
    final_config = {**default_config, **config}
    return gateway_class(config=final_config)


def get_available_gateways() -> Dict[str, bool]:
    """
    Check which gateways are available based on configuration.

    Returns:
        Dict mapping gateway names to availability status.
    """
    available = {}
    for name, cls in GATEWAY_REGISTRY.items():
        available[name] = cls.is_available()
    return available


def get_default_gateway() -> Optional[str]:
    """
    Get the default gateway name from settings.

    Returns:
        str: Default gateway name or None
    """
    return getattr(settings, 'PAYMENT_DEFAULT_GATEWAY', 'chapa')


# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------

__version__ = '1.0.0'
__all__ = [
    # Base classes
    'BaseGateway',
    'GatewayResponse',
    'GatewayError',

    # Gateway implementations
    'ChapaGateway',
    'TelebirrGateway',
    'BankTransferGateway',

    # Registry and factory
    'GATEWAY_REGISTRY',
    'get_gateway',
    'get_available_gateways',
    'get_default_gateway',

    # Constants
    'PaymentStatus',
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger.info(f'Payment gateways package v{__version__} initialized')
logger.debug(f'Available gateways: {get_available_gateways()}')
logger.debug(f'Default gateway: {get_default_gateway()}')