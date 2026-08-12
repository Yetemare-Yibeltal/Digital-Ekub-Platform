"""
Config package for Digital Ekub Platform.
"""

import os
import sys
from pathlib import Path
from typing import List, Optional

from .celery import app as celery_app

__version__ = '1.0.0'
__all__ = [
    'celery_app',
    '__version__',
    'get_project_root',
    'validate_environment',
]


def get_project_root() -> Path:
    """Get absolute path to project root directory."""
    current_path = Path(__file__).resolve().parent.parent
    for parent in [current_path, current_path.parent]:
        if (parent / 'manage.py').exists():
            return parent
    return current_path.parent


def validate_environment(required_vars: Optional[List[str]] = None) -> bool:
    """Validate that required environment variables are set."""
    if required_vars is None:
        required_vars = [
            'SECRET_KEY',
            'DB_NAME',
            'DB_USER',
            'DB_PASSWORD',
            'DB_HOST',
            'DB_PORT',
        ]
    
    missing = []
    for var in required_vars:
        if not os.environ.get(var):
            missing.append(var)
    
    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        return False
    return True


def setup_environment() -> None:
    """Setup environment before Django starts."""
    project_root = get_project_root()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    
    if not validate_environment():
        print("WARNING: Some environment variables are missing.")
    
    if not os.environ.get('TZ'):
        os.environ['TZ'] = 'Africa/Addis_Ababa'
    
    if not os.environ.get('DJANGO_SETTINGS_MODULE'):
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


setup_environment()