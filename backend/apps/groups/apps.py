"""
App configuration for the groups app.

This module defines the Django AppConfig for the groups app,
including the ready method for importing signals and custom
initialization tasks when the app is loaded.
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

import logging

logger = logging.getLogger(__name__)


class GroupsConfig(AppConfig):
    """
    Configuration for the groups app.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.groups'
    label = 'groups'
    verbose_name = _('Groups')

    def ready(self):
        """
        Called when the app is ready.

        This method performs initialization tasks:
        - Import signals to connect signal handlers
        - Register custom admin configurations
        - Perform any necessary startup checks
        - Initialize app-specific settings
        """
        # Import signals to ensure they are registered
        try:
            import apps.groups.signals
            logger.info('Groups signals imported successfully')
        except ImportError as e:
            logger.warning(f'Failed to import groups signals: {e}')

        # Import admin to register admin classes
        try:
            import apps.groups.admin
            logger.info('Groups admin registered successfully')
        except ImportError as e:
            logger.warning(f'Failed to import groups admin: {e}')

        # Perform startup checks for the app
        self._perform_startup_checks()

        # Initialize app settings
        self._initialize_settings()

        logger.info(f'Groups app initialized (version {self.get_version()})')

    def _perform_startup_checks(self):
        """
        Perform startup checks to ensure the app is properly configured.
        """
        try:
            # Check required models exist
            from .models import Group, GroupMember, GroupInvitation
            logger.info('Groups models validated successfully')
        except ImportError as e:
            logger.error(f'Required models not found: {e}')

    def _initialize_settings(self):
        """
        Initialize app-specific settings.
        """
        from django.conf import settings

        # Set default values if not defined
        if not hasattr(settings, 'GROUP_MAX_MEMBERS'):
            settings.GROUP_MAX_MEMBERS = 100
            logger.info('GROUP_MAX_MEMBERS set to default: 100')

        if not hasattr(settings, 'GROUP_MIN_MEMBERS'):
            settings.GROUP_MIN_MEMBERS = 2
            logger.info('GROUP_MIN_MEMBERS set to default: 2')

        if not hasattr(settings, 'GROUP_DEFAULT_CYCLE_LENGTH'):
            settings.GROUP_DEFAULT_CYCLE_LENGTH = 10
            logger.info('GROUP_DEFAULT_CYCLE_LENGTH set to default: 10')

        if not hasattr(settings, 'GROUP_AUTO_ACTIVATE_DAYS'):
            settings.GROUP_AUTO_ACTIVATE_DAYS = 7
            logger.info('GROUP_AUTO_ACTIVATE_DAYS set to default: 7')

        if not hasattr(settings, 'GROUP_AUTO_COMPLETE_DAYS'):
            settings.GROUP_AUTO_COMPLETE_DAYS = 14
            logger.info('GROUP_AUTO_COMPLETE_DAYS set to default: 14')

        if not hasattr(settings, 'GROUP_PAUSE_EXPIRY_DAYS'):
            settings.GROUP_PAUSE_EXPIRY_DAYS = 30
            logger.info('GROUP_PAUSE_EXPIRY_DAYS set to default: 30')

        if not hasattr(settings, 'GROUP_INVITATION_EXPIRY_DAYS'):
            settings.GROUP_INVITATION_EXPIRY_DAYS = 7
            logger.info('GROUP_INVITATION_EXPIRY_DAYS set to default: 7')

        logger.info('Groups settings initialized')

    def get_version(self) -> str:
        """
        Return the version of the groups app.
        """
        from . import __version__
        return __version__


# ============================================================================
# APP REGISTRATION
# ============================================================================

# The app is registered via INSTALLED_APPS in settings.py
# This config class is used by Django's app registry

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['GroupsConfig']