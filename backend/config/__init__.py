"""
Digital Ekub Platform – Configuration Package.

This package holds all settings, URLs, WSGI/ASGI entry points,
and Celery configuration for the Django backend.
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------
__version__ = '1.0.0'
__author__ = 'Digital Ekub Team'
__description__ = 'Django configuration for the Digital Ekub Platform'

# ---------------------------------------------------------------------------
# Import Celery app so it is loaded when Django starts
# ---------------------------------------------------------------------------
from .celery import app as celery_app

# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
__all__ = [
    'celery_app',
    '__version__',
    '__author__',
    '__description__',
    'get_project_root',
    'load_env_file',
    'validate_environment',
    'setup_logging',
    'get_project_settings',
]

# ---------------------------------------------------------------------------
# Project root discovery
# ---------------------------------------------------------------------------
def get_project_root() -> Path:
    """
    Return the absolute path to the project root.

    The root is determined by walking up from this file's location
    until a directory containing 'manage.py' is found. If not found,
    the parent of the 'backend' folder is returned as a fallback.
    """
    current = Path(__file__).resolve().parent  # backend/config/
    # Go up to backend/ then to project root
    backend_dir = current.parent                 # backend/
    # Check if manage.py exists in backend_dir or its parent
    for candidate in [backend_dir, backend_dir.parent]:
        if (candidate / 'manage.py').exists():
            return candidate
    # Fallback: assume project root is one level above backend
    return backend_dir.parent

# ---------------------------------------------------------------------------
# Environment file loader
# ---------------------------------------------------------------------------
def load_env_file(env_file: Optional[Path] = None) -> None:
    """
    Load environment variables from a .env file.

    If no path is given, it looks for '.env' in the project root.
    This is used as a fallback when python‑decouple is not used,
    but we keep it for scenarios where we need explicit loading.
    """
    if env_file is None:
        env_file = get_project_root() / '.env'
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                key, _, value = line.partition('=')
                if key and not os.environ.get(key):
                    os.environ[key] = value.strip()

# ---------------------------------------------------------------------------
# Environment validation
# ---------------------------------------------------------------------------
def validate_environment(required_vars: Optional[List[str]] = None) -> bool:
    """
    Check that all required environment variables are present.

    If not provided, a default list of critical variables is used.
    Returns True if all are set, False otherwise.
    """
    if required_vars is None:
        required_vars = [
            'SECRET_KEY',
            'DB_NAME',
            'DB_USER',
            'DB_PASSWORD',
            'DB_HOST',
            'DB_PORT',
            'CELERY_BROKER_URL',
        ]
    missing = [var for var in required_vars if not os.environ.get(var)]
    if missing:
        print(f"CRITICAL: Missing environment variables: {', '.join(missing)}")
        return False
    return True

# ---------------------------------------------------------------------------
# Early logging setup (before Django's logging is configured)
# ---------------------------------------------------------------------------
def setup_logging(level: str = 'INFO') -> None:
    """
    Configure a basic console logger for early‑stage messages.

    This is used before Django's full logging system is available.
    It logs to stderr with a simple format.
    """
    logger = logging.getLogger('ekub.config')
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger

# ---------------------------------------------------------------------------
# Access settings module (convenience)
# ---------------------------------------------------------------------------
def get_project_settings():
    """
    Return the Django settings module.

    This is useful for scripts that need to access settings
    without importing the module directly.
    """
    from django.conf import settings
    return settings

# ---------------------------------------------------------------------------
# Initialisation when this package is imported
# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so all apps can be imported
project_root = get_project_root()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Try to load .env file as a fallback (decouple will also load it)
try:
    load_env_file()
except Exception:
    pass  # ignore any errors; decouple will handle it

# Validate critical environment variables
if not validate_environment():
    # We log a warning but do not crash – the application may still work
    # if some variables are only needed for optional features.
    logger = setup_logging()
    logger.warning('Some required environment variables are missing.')

# Set default timezone if not already set
if not os.environ.get('TZ'):
    os.environ['TZ'] = 'Africa/Addis_Ababa'

# Ensure Django settings module is defined
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Log startup
logger = setup_logging()
logger.info(f'Config package v{__version__} initialised.')
logger.info(f'Project root: {project_root}')