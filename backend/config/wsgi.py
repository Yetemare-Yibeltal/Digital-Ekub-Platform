"""
WSGI entrypoint for the Digital Ekub Platform.

This module provides the WSGI application for production deployment
using Gunicorn or uWSGI servers. It includes a health check wrapper
for load balancer monitoring and proper Python path setup.
"""

import os
import sys
import logging
from django.core.wsgi import get_wsgi_application

# Set default settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Add the project root to the Python path for production compatibility
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# Create the WSGI application
application = get_wsgi_application()

# Configure a simple logger for startup messages
logger = logging.getLogger('ekub.wsgi')
logger.info('WSGI application initialized successfully.')

def health_check_wrapper(environ, start_response):
    """
    Wraps the WSGI application to handle /health/ requests directly.
    This bypasses Django for health checks, reducing overhead and
    ensuring quick responses for load balancers and monitoring tools.
    """
    path = environ.get('PATH_INFO', '')
    if path.startswith('/health'):
        status = '200 OK'
        headers = [('Content-Type', 'application/json')]
        start_response(status, headers)
        return [b'{"status": "ok", "service": "ekub-backend", "version": "1.0.0"}']
    # Delegate to the main WSGI application for all other requests
    return application(environ, start_response)

application = health_check_wrapper