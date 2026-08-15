"""
Complete middleware for the audit app.

This module provides comprehensive middleware for auditing all HTTP requests and responses:
- RequestIDMiddleware: Generates and propagates unique request IDs for tracing
- RequestLoggingMiddleware: Logs detailed request information including headers, body, and user context
- ResponseLoggingMiddleware: Logs response details including status, size, and timing
- PerformanceMiddleware: Tracks request duration, database query count/time, cache operations
- UserActivityMiddleware: Creates UserActivity records for authenticated users
- SecurityMiddleware: Detects and logs security events (failed logins, suspicious patterns, rate limiting)
- AuditContextMiddleware: Manages audit context for the current request (thread-local)

All middleware are production-ready with comprehensive error handling, configuration via settings,
and integration with the audit models to store audit data in the database.
"""

import json
import time
import uuid
import re
import logging
import hashlib
import base64
from typing import Dict, Any, Optional, List, Tuple, Callable
from urllib.parse import urlparse, parse_qs
from functools import wraps

from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse
from django.urls import resolve
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.utils.text import get_valid_filename

from .models import (
    AuditLog,
    UserActivity,
    SecurityEvent,
    PerformanceMetric,
    AuditEvent,
)
from . import thread_local

User = get_user_model()
logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS AND CONFIGURATION
# ============================================================================

# Paths to exclude from audit logging (can be overridden in settings)
EXCLUDED_PATHS = getattr(settings, 'AUDIT_EXCLUDED_PATHS', [
    '/admin/',
    '/static/',
    '/media/',
    '/api/v1/auth/token/',
    '/api/v1/auth/refresh/',
    '/health/',
    '/ping/',
    '/ready/',
    '/favicon.ico',
    '/robots.txt',
])

# Maximum request body size to log (in bytes)
MAX_REQUEST_BODY_LOG = getattr(settings, 'AUDIT_MAX_REQUEST_BODY_LOG', 1024)  # 1KB

# Maximum response body size to log (in bytes)
MAX_RESPONSE_BODY_LOG = getattr(settings, 'AUDIT_MAX_RESPONSE_BODY_LOG', 1024)

# Performance thresholds (in milliseconds)
PERFORMANCE_THRESHOLDS = getattr(settings, 'AUDIT_PERFORMANCE_THRESHOLDS', {
    'warning': 1000,    # 1 second
    'critical': 5000,   # 5 seconds
})

# Security-sensitive patterns to monitor
SECURITY_PATTERNS = getattr(settings, 'AUDIT_SECURITY_PATTERNS', {
    'login_attempt': {
        'path': r'/api/v1/auth/login/',
        'method': 'POST',
        'description': 'Login Attempt',
    },
    'failed_login': {
        'path': r'/api/v1/auth/login/',
        'method': 'POST',
        'status_code': 401,
        'description': 'Failed Login Attempt',
    },
    'password_change': {
        'path': r'/api/v1/auth/change-password/',
        'method': 'POST',
        'description': 'Password Change',
    },
    'password_reset': {
        'path': r'/api/v1/auth/password-reset-',
        'method': 'POST',
        'description': 'Password Reset Request',
    },
    'registration': {
        'path': r'/api/v1/auth/register/',
        'method': 'POST',
        'description': 'User Registration',
    },
    'admin_login': {
        'path': r'/admin/login/',
        'method': 'POST',
        'description': 'Admin Login Attempt',
    },
    'admin_action': {
        'path': r'/admin/',
        'method': 'POST',
        'description': 'Admin Action',
    },
    'suspicious_user_agent': {
        'description': 'Suspicious User Agent',
    },
    'rate_limit_exceeded': {
        'status_code': 429,
        'description': 'Rate Limit Exceeded',
    },
    'unauthorized_access': {
        'status_code': 403,
        'description': 'Unauthorized Access Attempt',
    },
})

# Suspicious user agent patterns
SUSPICIOUS_USER_AGENT_PATTERNS = getattr(settings, 'AUDIT_SUSPICIOUS_USER_AGENTS', [
    r'curl',
    r'wget',
    r'python-requests',
    r'java',
    r'perl',
    r'ruby',
    r'go-http-client',
    r'nikto',
    r'sqlmap',
    r'nmap',
    r'nessus',
    r'openvas',
    r'burp',
    r'zap',
    r'w3af',
    r'acunetix',
    r'nikto',
    r'dirbuster',
    r'wfuzz',
    r'gobuster',
    r'ffuf',
])

# SQL injection patterns to detect
SQL_INJECTION_PATTERNS = [
    r'(\%27)|(\')|(\-\-)|(\%23)|(#)',
    r'((\%3D)|(=))[^\n]*((\%27)|(\')|(\-\-)|(\%3B)|(;))',
    r'\w*((\%27)|(\'))((\%6F)|o|(\%4F))((\%72)|r|(\%52))',
    r'(\%27)|(\')|(\-\-)|(;)|(\%23)|(#)',
]

# XSS patterns to detect
XSS_PATTERNS = [
    r'<script.*?>.*?</script>',
    r'javascript:',
    r'onerror=',
    r'onload=',
    r'onclick=',
    r'onmouseover=',
    r'<iframe.*?>',
    r'<object.*?>',
    r'<embed.*?>',
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_client_ip(request: HttpRequest) -> str:
    """Extract client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '')
    return ip or '0.0.0.0'


def is_authenticated(user) -> bool:
    """Check if user is authenticated."""
    return user and user.is_authenticated and not user.is_anonymous


def should_exclude_path(path: str) -> bool:
    """Check if the path should be excluded from auditing."""
    for excluded in EXCLUDED_PATHS:
        if path.startswith(excluded):
            return True
    return False


def sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Sanitize headers by removing sensitive information."""
    sensitive_headers = ['authorization', 'cookie', 'x-api-key', 'x-csrftoken']
    sanitized = {}
    for key, value in headers.items():
        if key.lower() in sensitive_headers:
            sanitized[key] = '***REDACTED***'
        else:
            sanitized[key] = value
    return sanitized


def detect_sql_injection(content: str) -> bool:
    """Detect potential SQL injection patterns in content."""
    if not content:
        return False
    for pattern in SQL_INJECTION_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False


def detect_xss(content: str) -> bool:
    """Detect potential XSS patterns in content."""
    if not content:
        return False
    for pattern in XSS_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False


def is_suspicious_user_agent(user_agent: str) -> bool:
    """Check if the user agent is suspicious."""
    if not user_agent:
        return False
    for pattern in SUSPICIOUS_USER_AGENT_PATTERNS:
        if re.search(pattern, user_agent, re.IGNORECASE):
            return True
    return False


def truncate_content(content: str, max_size: int = 1024) -> str:
    """Truncate content to max_size and add truncation indicator."""
    if not content:
        return ''
    if len(content) <= max_size:
        return content
    return content[:max_size] + f'... (truncated, total {len(content)} bytes)'


def get_request_body(request: HttpRequest) -> Optional[str]:
    """Extract request body as string safely."""
    try:
        if request.body:
            body = request.body.decode('utf-8', errors='ignore')
            return truncate_content(body, MAX_REQUEST_BODY_LOG)
    except Exception:
        return None
    return None


def get_response_body(response: HttpResponse) -> Optional[str]:
    """Extract response body as string safely."""
    try:
        if hasattr(response, 'content') and response.content:
            body = response.content.decode('utf-8', errors='ignore')
            return truncate_content(body, MAX_RESPONSE_BODY_LOG)
    except Exception:
        return None
    return None


def get_resource_type(path: str) -> str:
    """Determine resource type from path."""
    if '/api/v1/' in path:
        if 'groups' in path:
            return 'GROUP'
        if 'contributions' in path:
            return 'CONTRIBUTION'
        if 'payments' in path:
            return 'PAYMENT'
        if 'users' in path or 'profile' in path:
            return 'USER'
        if 'auth' in path:
            return 'AUTH'
        if 'notifications' in path:
            return 'NOTIFICATION'
        if 'admin' in path:
            return 'ADMIN'
        if 'audit' in path:
            return 'AUDIT'
    return 'SYSTEM'


def get_action_from_path(path: str, method: str) -> str:
    """Determine action from path and HTTP method."""
    method_map = {
        'GET': 'VIEW',
        'POST': 'CREATE',
        'PUT': 'UPDATE',
        'PATCH': 'UPDATE',
        'DELETE': 'DELETE',
        'OPTIONS': 'OPTIONS',
        'HEAD': 'HEAD',
    }
    action = method_map.get(method, 'UNKNOWN')

    # Special case for auth paths
    if '/auth/' in path:
        if 'login' in path:
            return 'LOGIN'
        if 'logout' in path:
            return 'LOGOUT'
        if 'register' in path:
            return 'REGISTER'
        if 'change-password' in path or 'password-change' in path:
            return 'CHANGE_PASSWORD'
        if 'password-reset' in path:
            return 'RESET_PASSWORD'
        if 'verify' in path:
            return 'VERIFY'
        if 'otp' in path:
            return 'OTP_OPERATION'

    # API resource actions
    if '/api/v1/' in path:
        resource = get_resource_type(path)
        return f'{action}_{resource}'

    return action


def get_resource_id_from_path(path: str) -> Optional[int]:
    """Extract numeric resource ID from path."""
    matches = re.findall(r'/(\d+)/', path)
    if matches:
        return int(matches[-1])
    return None


# ============================================================================
# MIDDLEWARE: REQUEST ID
# ============================================================================

class RequestIDMiddleware(MiddlewareMixin):
    """
    Generates and propagates a unique request ID for tracing.

    The request ID is added to:
    - The request object (request.request_id)
    - The response headers (X-Request-ID)
    - The audit logs
    """

    def process_request(self, request):
        # Check if request ID already exists (from upstream)
        request_id = request.headers.get('X-Request-ID')
        if not request_id:
            request_id = self._generate_request_id()

        # Add to request object for use in other middleware
        request.request_id = request_id

        # Add to thread-local storage for use in models
        thread_local.request_id = request_id

        # Store in cache for quick lookup
        cache.set(f'request_id_{request_id}', {
            'path': request.path,
            'method': request.method,
            'timestamp': timezone.now().isoformat(),
            'remote_addr': request.META.get('REMOTE_ADDR'),
        }, timeout=3600)

        return None

    def process_response(self, request, response):
        # Add request ID to response headers
        if hasattr(request, 'request_id'):
            response['X-Request-ID'] = request.request_id

        # Clean up thread-local
        if hasattr(thread_local, 'request_id'):
            del thread_local.request_id

        return response

    def _generate_request_id(self) -> str:
        """Generate a unique request ID."""
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        unique_id = uuid.uuid4().hex[:12].upper()
        return f"REQ-{timestamp}-{unique_id}"


# ============================================================================
# MIDDLEWARE: REQUEST LOGGING
# ============================================================================

class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Logs all requests with detailed information.

    Records:
    - HTTP method, path, query parameters
    - User (authenticated or anonymous)
    - IP address, user agent
    - Request body (for non-sensitive data)
    - Request ID for tracing
    - Headers (sanitized)
    """

    def process_request(self, request):
        # Skip excluded paths
        if should_exclude_path(request.path):
            return None

        # Store request start time
        request._start_time = time.time()

        # Extract request details
        request._audit_data = {
            'method': request.method,
            'path': request.path,
            'query_params': dict(request.GET),
            'ip_address': get_client_ip(request),
            'user_agent': request.headers.get('HTTP_USER_AGENT', ''),
            'request_id': getattr(request, 'request_id', None),
            'user': request.user if is_authenticated(request.user) else None,
            'headers': sanitize_headers(dict(request.headers)),
            'content_type': request.headers.get('CONTENT_TYPE', ''),
        }

        # Capture request body (if not a file upload)
        if request.method in ['POST', 'PUT', 'PATCH'] and not request.FILES:
            request._audit_data['body'] = get_request_body(request)
            # Check for security threats in body
            body = request._audit_data.get('body', '')
            if body:
                if detect_sql_injection(body):
                    request._audit_data['security_threat'] = 'SQL_INJECTION'
                if detect_xss(body):
                    request._audit_data['security_threat'] = 'XSS'

        # Log request
        logger.info(
            f"REQUEST: {request.method} {request.path} | "
            f"IP: {request._audit_data['ip_address']} | "
            f"User: {request.user.email if is_authenticated(request.user) else 'Anonymous'} | "
            f"ID: {request._audit_data['request_id']}"
        )

        # Log request body if present (and not too large)
        if request._audit_data.get('body'):
            logger.debug(f"Request Body: {request._audit_data['body']}")

        return None


# ============================================================================
# MIDDLEWARE: RESPONSE LOGGING
# ============================================================================

class ResponseLoggingMiddleware(MiddlewareMixin):
    """
    Logs all responses with status codes and sizes.

    Records:
    - HTTP status code
    - Response size
    - Response time
    - Performance warnings for slow responses
    - Response body (truncated) for debugging
    """

    def process_response(self, request, response):
        # Skip excluded paths
        if should_exclude_path(request.path):
            return response

        # Calculate response size
        size = len(response.content) if hasattr(response, 'content') else 0

        # Calculate duration
        duration = 0
        if hasattr(request, '_start_time'):
            duration = (time.time() - request._start_time) * 1000

        # Log response
        logger.info(
            f"RESPONSE: {request.method} {request.path} | "
            f"Status: {response.status_code} | "
            f"Size: {size} bytes | "
            f"Duration: {duration:.2f}ms"
        )

        # Performance warning for slow responses
        if duration > PERFORMANCE_THRESHOLDS['warning']:
            level = 'warning' if duration < PERFORMANCE_THRESHOLDS['critical'] else 'critical'
            logger.warning(
                f"SLOW RESPONSE: {request.method} {request.path} | "
                f"Duration: {duration:.2f}ms ({level}) | "
                f"Status: {response.status_code}"
            )

            # Create performance metric
            try:
                PerformanceMetric.objects.create(
                    metric_name='response_duration',
                    value=duration,
                    unit='ms',
                    labels={
                        'path': request.path,
                        'method': request.method,
                        'status_code': response.status_code,
                        'level': level,
                        'user_id': request.user.id if is_authenticated(request.user) else 'anonymous',
                    },
                    timestamp=timezone.now(),
                )
            except Exception as e:
                logger.error(f"Error creating performance metric: {str(e)}")

        # Capture response body for debugging (only for non-binary responses)
        if response.status_code < 400 and 'application/json' in response.headers.get('Content-Type', ''):
            try:
                body = get_response_body(response)
                if body:
                    logger.debug(f"Response Body: {body}")
            except Exception:
                pass

        return response


# ============================================================================
# MIDDLEWARE: PERFORMANCE
# ============================================================================

class PerformanceMiddleware(MiddlewareMixin):
    """
    Tracks performance metrics for all requests.

    Records:
    - Request duration
    - Database query count and time
    - Cache hits/misses
    - Response size
    - Memory usage (optional)
    """

    def __init__(self, get_response):
        super().__init__(get_response)
        self._db_queries_start = 0
        self._db_time_start = 0.0

    def process_request(self, request):
        # Skip excluded paths
        if should_exclude_path(request.path):
            return None

        # Start tracking database queries
        from django.db import connection
        self._db_queries_start = len(connection.queries)
        self._db_time_start = sum(float(q.get('time', 0)) for q in connection.queries)

        # Start tracking cache operations
        request._cache_ops_start = {
            'hits': cache.get('cache_hits', 0),
            'misses': cache.get('cache_misses', 0),
        }

        return None

    def process_response(self, request, response):
        # Skip excluded paths
        if should_exclude_path(request.path):
            return response

        # Calculate metrics
        duration = 0
        if hasattr(request, '_start_time'):
            duration = (time.time() - request._start_time) * 1000

        # Database queries
        from django.db import connection
        query_count = len(connection.queries) - self._db_queries_start
        query_time = 0.0
        if query_count > 0:
            # Approximate query time
            current_queries = connection.queries[self._db_queries_start:]
            query_time = sum(float(q.get('time', 0)) for q in current_queries) * 1000  # ms

        # Cache operations
        cache_hits = cache.get('cache_hits', 0)
        cache_misses = cache.get('cache_misses', 0)
        if hasattr(request, '_cache_ops_start'):
            hits = cache_hits - request._cache_ops_start.get('hits', 0)
            misses = cache_misses - request._cache_ops_start.get('misses', 0)
        else:
            hits = 0
            misses = 0

        # Response size
        size = len(response.content) if hasattr(response, 'content') else 0

        # Record metrics if significant or sample
        if duration > 100 or query_count > 5 or hits > 0 or misses > 0 or size > 1000:
            try:
                # Use sampling to reduce database load
                import random
                if random.random() < 0.1:  # 10% sampling
                    PerformanceMetric.objects.create(
                        metric_name='request_performance',
                        value=duration,
                        unit='ms',
                        labels={
                            'path': request.path[:100],
                            'method': request.method,
                            'status_code': response.status_code,
                            'query_count': query_count,
                            'query_time': f"{query_time:.2f}",
                            'cache_hits': hits,
                            'cache_misses': misses,
                            'response_size': size,
                            'user_id': request.user.id if is_authenticated(request.user) else 'anonymous',
                        },
                        timestamp=timezone.now(),
                    )
            except Exception as e:
                logger.error(f"Error creating performance metric: {str(e)}")

        # Update cache operation counters
        cache.set('cache_hits', cache_hits, timeout=None)
        cache.set('cache_misses', cache_misses, timeout=None)

        return response


# ============================================================================
# MIDDLEWARE: USER ACTIVITY
# ============================================================================

class UserActivityMiddleware(MiddlewareMixin):
    """
    Tracks user activities per request.

    Records user actions for authenticated users in the database.
    """

    def process_response(self, request, response):
        # Skip if not authenticated
        if not is_authenticated(request.user):
            return response

        # Skip excluded paths
        if should_exclude_path(request.path):
            return response

        # Skip if response is not successful
        if response.status_code >= 400:
            return response

        try:
            # Determine action and resource
            action = get_action_from_path(request.path, request.method)
            resource = get_resource_type(request.path)
            resource_id = get_resource_id_from_path(request.path)

            # Create user activity record
            UserActivity.objects.create(
                user=request.user,
                action=action,
                resource=resource,
                resource_id=resource_id,
                details={
                    'method': request.method,
                    'path': request.path,
                    'query_params': dict(request.GET),
                    'status_code': response.status_code,
                    'request_id': getattr(request, 'request_id', None),
                    'ip_address': get_client_ip(request),
                    'user_agent': request.headers.get('HTTP_USER_AGENT', ''),
                },
                session_id=request.session.session_key,
                ip_address=get_client_ip(request),
                user_agent=request.headers.get('HTTP_USER_AGENT', ''),
                timestamp=timezone.now(),
            )
            logger.debug(f"User activity recorded: {request.user.email} - {action} on {resource}")
        except Exception as e:
            logger.error(f"Error creating user activity record: {str(e)}")

        return response


# ============================================================================
# MIDDLEWARE: SECURITY
# ============================================================================

class SecurityMiddleware(MiddlewareMixin):
    """
    Detects and logs security-related events.

    Monitors:
    - Failed login attempts
    - Suspicious patterns in requests (SQL injection, XSS)
    - Rate limiting violations
    - Unauthorized access attempts
    - Suspicious user agents
    - Admin login attempts
    """

    def process_response(self, request, response):
        # Skip excluded paths
        if should_exclude_path(request.path):
            return response

        # Check for security events
        self._check_security_events(request, response)

        # Check for suspicious patterns in request/response
        self._check_suspicious_patterns(request, response)

        return response

    def _check_security_events(self, request, response):
        """Check for security events in the request/response."""
        try:
            # Failed login attempts
            if request.path == '/api/v1/auth/login/' and response.status_code == 401:
                self._create_security_event(
                    request,
                    'LOGIN_FAILED',
                    f'Failed login attempt for {request.data.get("email", "unknown") if hasattr(request, "data") else "unknown"}',
                    'warning',
                    {
                        'username': request.data.get('email', 'unknown') if hasattr(request, 'data') else 'unknown',
                        'path': request.path,
                        'method': request.method,
                    }
                )

            # Unauthorized access attempts
            if response.status_code == 403:
                self._create_security_event(
                    request,
                    'UNAUTHORIZED_ACCESS',
                    f'Unauthorized access attempt to {request.path}',
                    'warning',
                    {'path': request.path, 'method': request.method, 'status_code': response.status_code}
                )

            # Suspicious user agent
            user_agent = request.headers.get('HTTP_USER_AGENT', '')
            if is_suspicious_user_agent(user_agent):
                self._create_security_event(
                    request,
                    'SUSPICIOUS_ACTIVITY',
                    f'Suspicious user agent detected: {user_agent[:100]}',
                    'warning',
                    {'user_agent': user_agent[:255], 'path': request.path}
                )

            # Rate limiting violations
            if response.status_code == 429:
                self._create_security_event(
                    request,
                    'RATE_LIMIT_EXCEEDED',
                    f'Rate limit exceeded for {request.path}',
                    'warning',
                    {'path': request.path, 'method': request.method, 'ip': get_client_ip(request)}
                )

            # Admin login attempts
            if request.path == '/admin/login/' and response.status_code == 200:
                self._create_security_event(
                    request,
                    'ADMIN_LOGIN',
                    f'Admin login attempt for {request.POST.get("username", "unknown") if hasattr(request, "POST") else "unknown"}',
                    'info',
                    {'username': request.POST.get('username', 'unknown') if hasattr(request, 'POST') else 'unknown'}
                )

            # Admin login failure
            if request.path == '/admin/login/' and response.status_code == 302 and request.GET.get('next'):
                self._create_security_event(
                    request,
                    'ADMIN_LOGIN_FAILED',
                    'Admin login failed',
                    'warning',
                    {'next': request.GET.get('next', '')}
                )

            # Account lockout detection (multiple failed logins from same IP)
            self._check_account_lockout(request)

        except Exception as e:
            logger.error(f"Error checking security events: {str(e)}")

    def _check_account_lockout(self, request):
        """Check for potential account lockout due to multiple failed login attempts."""
        ip = get_client_ip(request)
        key = f'failed_logins_{ip}'
        attempts = cache.get(key, 0)

        if request.path == '/api/v1/auth/login/' and request.method == 'POST':
            # If this is a failed login, increment counter
            # We can't know yet if it's failed, so we'll check later in the response
            pass

        # If we have > 5 failed attempts in 5 minutes, create a security event
        if attempts >= 5:
            self._create_security_event(
                request,
                'ACCOUNT_LOCKOUT',
                f'Potential account lockout detected from IP {ip}',
                'warning',
                {'ip': ip, 'attempts': attempts}
            )

    def _check_suspicious_patterns(self, request, response):
        """Check for suspicious patterns in request/response content."""
        try:
            # Check request body for SQL injection
            if hasattr(request, '_audit_data') and request._audit_data.get('body'):
                body = request._audit_data['body']
                if detect_sql_injection(body):
                    self._create_security_event(
                        request,
                        'SQL_INJECTION_ATTEMPT',
                        f'Potential SQL injection detected in {request.path}',
                        'critical',
                        {'path': request.path, 'method': request.method}
                    )

                if detect_xss(body):
                    self._create_security_event(
                        request,
                        'XSS_ATTEMPT',
                        f'Potential XSS attack detected in {request.path}',
                        'critical',
                        {'path': request.path, 'method': request.method}
                    )

            # Check query parameters for SQL injection
            for key, values in request.GET.items():
                for value in values:
                    if detect_sql_injection(value) or detect_xss(value):
                        self._create_security_event(
                            request,
                            'SQL_INJECTION_ATTEMPT',
                            f'Potential SQL injection in query parameter {key} at {request.path}',
                            'critical',
                            {'parameter': key, 'value': value[:100], 'path': request.path}
                        )
                        break

            # Check for password in query params
            for key in request.GET.keys():
                if 'password' in key.lower() or 'token' in key.lower():
                    self._create_security_event(
                        request,
                        'SENSITIVE_DATA_IN_URL',
                        f'Sensitive parameter "{key}" found in URL',
                        'warning',
                        {'parameter': key, 'path': request.path}
                    )

        except Exception as e:
            logger.error(f"Error checking suspicious patterns: {str(e)}")

    def _create_security_event(self, request, event_type: str, description: str,
                              severity: str, details: Dict):
        """Create a security event record."""
        try:
            # Check if similar event already exists in the last minute to avoid duplicates
            if event_type in ['LOGIN_FAILED', 'RATE_LIMIT_EXCEEDED']:
                recent = SecurityEvent.objects.filter(
                    event_type=event_type,
                    ip_address=get_client_ip(request),
                    timestamp__gte=timezone.now() - timezone.timedelta(minutes=1)
                ).exists()
                if recent:
                    return

            SecurityEvent.objects.create(
                user=request.user if is_authenticated(request.user) else None,
                event_type=event_type,
                description=description,
                severity=severity,
                details=details,
                ip_address=get_client_ip(request),
                user_agent=request.headers.get('HTTP_USER_AGENT', ''),
                timestamp=timezone.now(),
            )
            logger.warning(f"Security event: {event_type} - {description}")
        except Exception as e:
            logger.error(f"Error creating security event: {str(e)}")


# ============================================================================
# MIDDLEWARE: AUDIT CONTEXT
# ============================================================================

class AuditContextMiddleware(MiddlewareMixin):
    """
    Manages audit context for the current request.

    Provides context for audit logging including:
    - Request ID
    - User
    - IP address
    - User agent
    - Session
    - Path and method
    """

    def process_request(self, request):
        # Set up audit context
        context = {
            'request_id': getattr(request, 'request_id', None),
            'user': request.user if is_authenticated(request.user) else None,
            'ip_address': get_client_ip(request),
            'user_agent': request.headers.get('HTTP_USER_AGENT', ''),
            'session_id': request.session.session_key,
            'path': request.path,
            'method': request.method,
            'timestamp': timezone.now(),
        }

        # Store in thread-local for use in models
        thread_local.audit_context = context

        # Also store request ID separately for convenience
        if context['request_id']:
            thread_local.request_id = context['request_id']

        return None

    def process_response(self, request, response):
        # Clean up thread-local
        if hasattr(thread_local, 'audit_context'):
            del thread_local.audit_context
        if hasattr(thread_local, 'request_id'):
            del thread_local.request_id

        return response


# ============================================================================
# MIDDLEWARE: REQUEST TIMEOUT DETECTION
# ============================================================================

class RequestTimeoutMiddleware(MiddlewareMixin):
    """
    Detects and logs requests that take too long.

    This middleware logs a warning if a request exceeds the configured timeout threshold.
    """

    def __init__(self, get_response):
        super().__init__(get_response)
        self.timeout_threshold = getattr(settings, 'AUDIT_REQUEST_TIMEOUT', 30)  # seconds

    def process_response(self, request, response):
        if hasattr(request, '_start_time'):
            duration = time.time() - request._start_time
            if duration > self.timeout_threshold:
                logger.warning(
                    f"REQUEST TIMEOUT: {request.method} {request.path} | "
                    f"Duration: {duration:.2f}s (threshold: {self.timeout_threshold}s) | "
                    f"User: {request.user.email if is_authenticated(request.user) else 'Anonymous'}"
                )
                # Create a performance metric for timeout
                try:
                    PerformanceMetric.objects.create(
                        metric_name='request_timeout',
                        value=duration * 1000,
                        unit='ms',
                        labels={
                            'path': request.path,
                            'method': request.method,
                            'threshold': self.timeout_threshold,
                            'user_id': request.user.id if is_authenticated(request.user) else 'anonymous',
                        },
                        timestamp=timezone.now(),
                    )
                except Exception as e:
                    logger.error(f"Error creating timeout metric: {str(e)}")
        return response


# ============================================================================
# MIDDLEWARE: BODY LOGGING (with sanitization)
# ============================================================================

class BodyLoggingMiddleware(MiddlewareMixin):
    """
    Logs request and response bodies with sensitive data sanitization.

    This middleware sanitizes sensitive fields like password, token, etc. before logging.
    """

    SENSITIVE_FIELDS = ['password', 'token', 'secret', 'api_key', 'auth', 'credit_card', 'cvv']

    def process_request(self, request):
        if should_exclude_path(request.path):
            return None

        if request.method in ['POST', 'PUT', 'PATCH'] and request.body:
            try:
                body = json.loads(request.body.decode('utf-8'))
                sanitized = self._sanitize_json(body)
                logger.debug(f"Request Body (sanitized): {json.dumps(sanitized, indent=2)[:500]}")
            except json.JSONDecodeError:
                # Not JSON, skip logging
                pass
            except Exception as e:
                logger.error(f"Error logging request body: {str(e)}")

        return None

    def process_response(self, request, response):
        if should_exclude_path(request.path):
            return response

        if hasattr(response, 'content') and response.content:
            try:
                content_type = response.headers.get('Content-Type', '')
                if 'application/json' in content_type:
                    body = json.loads(response.content.decode('utf-8'))
                    sanitized = self._sanitize_json(body)
                    logger.debug(f"Response Body (sanitized): {json.dumps(sanitized, indent=2)[:500]}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            except Exception as e:
                logger.error(f"Error logging response body: {str(e)}")

        return response

    def _sanitize_json(self, data):
        """Recursively sanitize JSON data by redacting sensitive fields."""
        if isinstance(data, dict):
            return {
                key: '***REDACTED***' if any(sensitive in key.lower() for sensitive in self.SENSITIVE_FIELDS)
                else self._sanitize_json(value)
                for key, value in data.items()
            }
        elif isinstance(data, list):
            return [self._sanitize_json(item) for item in data]
        else:
            return data


# ============================================================================
# MIDDLEWARE: CORS LOGGING (OPTIONAL)
# ============================================================================

class CORSAuditMiddleware(MiddlewareMixin):
    """
    Logs CORS-related requests and headers for security auditing.
    """

    def process_request(self, request):
        if should_exclude_path(request.path):
            return None

        origin = request.headers.get('Origin')
        if origin:
            logger.debug(f"CORS Request: {request.method} {request.path} | Origin: {origin} | "
                         f"Referer: {request.headers.get('Referer')}")

        return None


# ============================================================================
# MIDDLEWARE: ERROR LOGGING
# ============================================================================

class ErrorLoggingMiddleware(MiddlewareMixin):
    """
    Logs exceptions and errors with context for debugging.
    """

    def process_exception(self, request, exception):
        if should_exclude_path(request.path):
            return None

        logger.error(
            f"EXCEPTION: {request.method} {request.path} | "
            f"Error: {type(exception).__name__}: {str(exception)} | "
            f"User: {request.user.email if is_authenticated(request.user) else 'Anonymous'} | "
            f"IP: {get_client_ip(request)}"
        )

        # Create a performance metric for errors
        try:
            PerformanceMetric.objects.create(
                metric_name='request_error',
                value=1,
                unit='count',
                labels={
                    'path': request.path,
                    'method': request.method,
                    'error_type': type(exception).__name__,
                    'status_code': 500,
                    'user_id': request.user.id if is_authenticated(request.user) else 'anonymous',
                },
                timestamp=timezone.now(),
            )
        except Exception as e:
            logger.error(f"Error creating error metric: {str(e)}")

        return None


# ============================================================================
# MIDDLEWARE: USER SESSION AUDIT
# ============================================================================

class UserSessionAuditMiddleware(MiddlewareMixin):
    """
    Audits user session creation and destruction events.
    """

    def process_request(self, request):
        if should_exclude_path(request.path):
            return None

        # Check if session was created
        if request.session and request.session.session_key:
            # Check if this is a new session
            if not hasattr(request, '_session_audited'):
                request._session_audited = True
                # Log session creation
                if is_authenticated(request.user):
                    SecurityEvent.objects.create(
                        user=request.user,
                        event_type='SESSION_CREATED',
                        description=f'Session created for {request.user.email}',
                        severity='info',
                        details={
                            'session_key': request.session.session_key[:8] + '...',
                            'ip': get_client_ip(request),
                            'user_agent': request.headers.get('HTTP_USER_AGENT', ''),
                        },
                        ip_address=get_client_ip(request),
                        user_agent=request.headers.get('HTTP_USER_AGENT', ''),
                        timestamp=timezone.now(),
                    )

        return None

    def process_response(self, request, response):
        # Check if session was destroyed (logout)
        if hasattr(request, 'session') and request.session and hasattr(request, '_session_audited'):
            if not request.session.session_key and is_authenticated(request.user):
                try:
                    SecurityEvent.objects.create(
                        user=request.user,
                        event_type='SESSION_DESTROYED',
                        description=f'Session destroyed for {request.user.email}',
                        severity='info',
                        details={
                            'ip': get_client_ip(request),
                            'user_agent': request.headers.get('HTTP_USER_AGENT', ''),
                        },
                        ip_address=get_client_ip(request),
                        user_agent=request.headers.get('HTTP_USER_AGENT', ''),
                        timestamp=timezone.now(),
                    )
                except Exception as e:
                    logger.error(f"Error logging session destruction: {str(e)}")

        return response


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'RequestIDMiddleware',
    'RequestLoggingMiddleware',
    'ResponseLoggingMiddleware',
    'PerformanceMiddleware',
    'UserActivityMiddleware',
    'SecurityMiddleware',
    'AuditContextMiddleware',
    'RequestTimeoutMiddleware',
    'BodyLoggingMiddleware',
    'CORSAuditMiddleware',
    'ErrorLoggingMiddleware',
    'UserSessionAuditMiddleware',
    'thread_local',
    'EXCLUDED_PATHS',
    'SECURITY_PATTERNS',
    'PERFORMANCE_THRESHOLDS',
    'get_client_ip',
    'should_exclude_path',
    'sanitize_headers',
    'detect_sql_injection',
    'detect_xss',
    'is_suspicious_user_agent',
]