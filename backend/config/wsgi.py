"""
WSGI config for the Digital Ekub Platform project.

This module contains the WSGI application used by Django's development server
and any production WSGI deployments (Gunicorn, uWSGI, Apache mod_wsgi).

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see:
https://docs.djangoproject.com/en/5.0/howto/deployment/wsgi/
"""

import os
import sys
from django.core.wsgi import get_wsgi_application

# Set default settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Add the project root to Python path (for production compatibility)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# Initialize WSGI application
application = get_wsgi_application()

# Optional: Health check middleware wrapper for monitoring
# This can be used by load balancers to check application health
def health_check_wrapper(environ, start_response):
    """
    Simple health check wrapper that bypasses Django for /health/ endpoints.
    This is useful for load balancers and monitoring tools.
    """
    if environ.get('PATH_INFO', '').startswith('/health/'):
        status = '200 OK'
        headers = [('Content-Type', 'application/json')]
        start_response(status, headers)
        return [b'{"status": "healthy", "service": "ekub-backend"}']
    return application(environ, start_response)

# Uncomment to enable health check wrapper in production
# application = health_check_wrapper