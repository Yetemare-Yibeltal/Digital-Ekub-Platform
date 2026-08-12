"""WSGI configuration for production deployment with Gunicorn."""

import os
import sys
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

application = get_wsgi_application()

def health_check_wrapper(environ, start_response):
    if environ.get('PATH_INFO', '').startswith('/health/'):
        status = '200 OK'
        headers = [('Content-Type', 'application/json')]
        start_response(status, headers)
        return [b'{"status": "healthy", "service": "ekub-backend"}']
    return application(environ, start_response)

# Uncomment to enable health check bypass in production
# application = health_check_wrapper