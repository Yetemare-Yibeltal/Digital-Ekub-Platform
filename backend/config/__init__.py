"""
Digital Ekub Platform – Configuration Package.

This package initialises the Django environment, loads .env,
validates Python and database compatibility, and exposes shared
utilities for the entire backend application.
"""

import os
import sys
import logging
import platform
from pathlib import Path
from typing import Optional, List, Dict, Any

# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------
__version__ = '1.0.0'
__author__ = 'Digital Ekub Team'
__app_name__ = 'Ekub Platform Backend'

# ---------------------------------------------------------------------------
# Import Celery app so it is available when Django starts
# ---------------------------------------------------------------------------
from .celery import app as celery_app

# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
__all__ = [
    'celery_app',
    '__version__',
    '__app_name__',
    'get_project_root',
    'load_env_file',
    'validate_environment',
    'setup_early_logging',
    'get_settings_value',
    'check_python_version',
    'get_system_info',
    'get_database_config',
]

# ---------------------------------------------------------------------------
# Project root discovery
# ---------------------------------------------------------------------------
def get_project_root() -> Path:
    """
    Return the absolute path to the project root directory.

    Walks up from the location of this file until it finds manage.py.
    Falls back to the parent of the 'backend' directory.
    """
    current = Path(__file__).resolve().parent  # backend/config/
    backend_dir = current.parent                # backend/
    for candidate in [backend_dir, backend_dir.parent]:
        if (candidate / 'manage.py').exists():
            return candidate
    return backend_dir.parent

# ---------------------------------------------------------------------------
# Environment file loader (with fallback)
# ---------------------------------------------------------------------------
def load_env_file(env_file: Optional[Path] = None) -> bool:
    """
    Load environment variables from a .env file.

    Returns True if file was loaded successfully, False otherwise.
    This is used as a fallback when python-decouple is not used.
    """
    if env_file is None:
        env_file = get_project_root() / '.env'
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    key, _, value = line.partition('=')
                    if key and not os.environ.get(key):
                        os.environ[key] = value.strip()
            return True
        except Exception as e:
            print(f"Warning: Could not load .env file: {e}", file=sys.stderr)
            return False
    return False

# ---------------------------------------------------------------------------
# System validation
# ---------------------------------------------------------------------------
def check_python_version() -> bool:
    """Ensure we are running Python 3.10 or higher."""
    major, minor, _ = sys.version_info[:3]
    if major < 3 or (major == 3 and minor < 10):
        print(f"Error: Python 3.10+ required (current: {major}.{minor})", file=sys.stderr)
        return False
    return True

def get_system_info() -> Dict[str, str]:
    """Return system information for logging."""
    return {
        'python_version': sys.version,
        'platform': platform.platform(),
        'architecture': platform.architecture()[0],
        'hostname': platform.node(),
        'processor': platform.processor(),
    }

# ---------------------------------------------------------------------------
# Environment validation
# ---------------------------------------------------------------------------
def validate_environment(required_vars: Optional[List[str]] = None) -> bool:
    """Check that all required environment variables are present."""
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
        print(f"CRITICAL: Missing environment variables: {', '.join(missing)}", file=sys.stderr)
        return False
    return True

# ---------------------------------------------------------------------------
# Early logging setup (before Django configures logging)
# ---------------------------------------------------------------------------
def setup_early_logging(level: str = 'INFO') -> logging.Logger:
    """
    Configure a minimal console logger for early-stage messages.

    This logger is used before Django's full logging system is available.
    """
    logger = logging.getLogger('ekub.config')
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger

# ---------------------------------------------------------------------------
# Settings helper (allows retrieval with default fallback)
# ---------------------------------------------------------------------------
def get_settings_value(key: str, default: Any = None) -> Any:
    """
    Retrieve a setting from environment with a fallback.

    This is a convenience for scripts that need to access settings
    before Django is fully loaded.
    """
    return os.environ.get(key, default)

# ---------------------------------------------------------------------------
# Database configuration helper
# ---------------------------------------------------------------------------
def get_database_config() -> Dict[str, str]:
    """Return the database connection settings as a dictionary."""
    return {
        'name': os.environ.get('DB_NAME', 'ekub_db'),
        'user': os.environ.get('DB_USER', 'ekub_user'),
        'password': os.environ.get('DB_PASSWORD', ''),
        'host': os.environ.get('DB_HOST', 'localhost'),
        'port': os.environ.get('DB_PORT', '5432'),
        'engine': os.environ.get('DB_ENGINE', 'django.db.backends.postgresql'),
    }

# ---------------------------------------------------------------------------
# Application info
# ---------------------------------------------------------------------------
def get_app_info() -> Dict[str, str]:
    """Return application metadata."""
    return {
        'app_name': __app_name__,
        'version': __version__,
        'author': __author__,
        'project_root': str(get_project_root()),
        'environment': os.environ.get('ENV', 'development'),
    }

# ---------------------------------------------------------------------------
# Initialisation when this package is imported
# ---------------------------------------------------------------------------

# 1. Check Python version
if not check_python_version():
    sys.exit(1)

# 2. Ensure project root is on sys.path
project_root = get_project_root()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 3. Attempt to load .env file (as a fallback, decouple will also load it)
load_env_file()

# 4. Validate critical environment variables
env_ok = validate_environment()

# 5. Set up early logger
logger = setup_early_logging()
if env_ok:
    logger.info('Environment variables validated successfully.')
else:
    logger.warning('Some required environment variables are missing.')

# 6. Log system information
logger.info(f'System: {get_system_info()}')
logger.info(f'App info: {get_app_info()}')

# 7. Set default timezone if not already set
if not os.environ.get('TZ'):
    os.environ['TZ'] = 'Africa/Addis_Ababa'
    logger.info('Timezone set to Africa/Addis_Ababa')

# 8. Ensure Django settings module is defined
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# 9. Log successful initialisation
logger.info('Config package fully initialised.')