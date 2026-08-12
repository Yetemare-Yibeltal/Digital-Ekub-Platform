import os
import sys
from pathlib import Path
from datetime import timedelta
from decouple import config, Csv

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Security
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,0.0.0.0', cast=Csv())
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='http://localhost:8000,http://localhost:5173', cast=Csv())

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_filters',
    'django_celery_beat',
    'django_celery_results',
    'drf_spectacular',
    'django_ratelimit',
    'auditlog',
    'storages',
    'django_cleanup.apps.CleanupConfig',
    # Local
    'apps.users',
    'apps.groups',
    'apps.contributions',
    'apps.payments',
    'apps.notifications',
    'apps.audit',
    'apps.admin_panel',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.audit.middleware.AuditLogMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': config('DB_ENGINE', default='django.db.backends.postgresql'),
        'NAME': config('DB_NAME', default='ekub_db'),
        'USER': config('DB_USER', default='ekub_user'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
        'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=600, cast=int),
        'OPTIONS': {'connect_timeout': 10},
        'ATOMIC_REQUESTS': True,
    }
}

# Authentication
AUTH_USER_MODEL = 'users.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = config('CELERY_TIMEZONE', default='Africa/Addis_Ababa')
USE_I18N = True
USE_L10N = True
USE_TZ = True
LANGUAGES = [('en', 'English'), ('am', 'Amharic')]
LOCALE_PATHS = [BASE_DIR / 'locale']

# Static & Media
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
FILE_UPLOAD_MAX_MEMORY_SIZE = config('MAX_UPLOAD_SIZE', default=5242880, cast=int)
DATA_UPLOAD_MAX_MEMORY_SIZE = FILE_UPLOAD_MAX_MEMORY_SIZE
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
ALLOWED_IMAGE_EXTENSIONS = config('ALLOWED_IMAGE_TYPES', default='jpg,jpeg,png,gif', cast=Csv())

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS
CORS_ALLOWED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='http://localhost:5173,http://localhost:8000', cast=Csv())
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = ['DELETE', 'GET', 'OPTIONS', 'PATCH', 'POST', 'PUT']
CORS_ALLOW_HEADERS = ['accept', 'accept-encoding', 'authorization', 'content-type', 'dnt', 'origin', 'user-agent', 'x-csrftoken', 'x-requested-with']
CORS_EXPOSE_HEADERS = ['content-disposition']

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('rest_framework_simplejwt.authentication.JWTAuthentication',),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticatedOrReadOnly',),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': ('django_filters.rest_framework.DjangoFilterBackend', 'rest_framework.filters.SearchFilter', 'rest_framework.filters.OrderingFilter'),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.AnonRateThrottle', 'rest_framework.throttling.UserRateThrottle'],
    'DEFAULT_THROTTLE_RATES': {
        'anon': config('RATE_LIMIT_PER_MINUTE', default='60/min'),
        'user': config('RATE_LIMIT_PER_MINUTE', default='100/min'),
    },
    'DEFAULT_RENDERER_CLASSES': ('rest_framework.renderers.JSONRenderer', 'rest_framework.renderers.BrowsableAPIRenderer'),
    'DEFAULT_PARSER_CLASSES': ('rest_framework.parsers.JSONParser', 'rest_framework.parsers.FormParser', 'rest_framework.parsers.MultiPartParser'),
    'EXCEPTION_HANDLER': 'apps.common.exceptions.custom_exception_handler',
}

# JWT
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(seconds=config('JWT_ACCESS_TOKEN_LIFETIME', default=3600, cast=int)),
    'REFRESH_TOKEN_LIFETIME': timedelta(seconds=config('JWT_REFRESH_TOKEN_LIFETIME', default=604800, cast=int)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# Celery
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://redis:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60
CELERY_WORKER_CONCURRENCY = config('CELERY_WORKER_CONCURRENCY', default=4, cast=int)
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_RESULT_EXPIRES = 3600
CELERY_TASK_ALWAYS_EAGER = DEBUG

# Caching (Redis)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': CELERY_BROKER_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'MAX_CONNECTIONS': 1000,
        },
        'KEY_PREFIX': 'ekub',
    }
}
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# Email (Brevo/Sendinblue)
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp-relay.brevo.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='no-reply@ekub-platform.com')
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = '[Ekub] '

# SMS (Africa's Talking)
AFRICASTALKING_USERNAME = config('AFRICASTALKING_USERNAME', default='sandbox')
AFRICASTALKING_API_KEY = config('AFRICASTALKING_API_KEY', default='')
AFRICASTALKING_SENDER_ID = config('AFRICASTALKING_SENDER_ID', default='ekub')
AFRICASTALKING_COUNTRY = config('AFRICASTALKING_COUNTRY', default='ETH')

# Payment Gateways
CHAPA_SECRET_KEY = config('CHAPA_SECRET_KEY', default='')
CHAPA_PUBLIC_KEY = config('CHAPA_PUBLIC_KEY', default='')
CHAPA_WEBHOOK_SECRET = config('CHAPA_WEBHOOK_SECRET', default='')
CHAPA_API_URL = config('CHAPA_API_URL', default='https://api.chapa.co/v1')
CHAPA_TIMEOUT = config('CHAPA_TIMEOUT', default=30, cast=int)

TELEBIRR_API_KEY = config('TELEBIRR_API_KEY', default='')
TELEBIRR_SECRET = config('TELEBIRR_SECRET', default='')
TELEBIRR_API_URL = config('TELEBIRR_API_URL', default='https://api.telebirr.et/v1')
TELEBIRR_MERCHANT_ID = config('TELEBIRR_MERCHANT_ID', default='')

# Platform Fees
PLATFORM_FEE_PERCENTAGE = config('PLATFORM_FEE_PERCENTAGE', default=2.5, cast=float)
PLATFORM_FEE_MINIMUM = config('PLATFORM_FEE_MINIMUM', default=10.00, cast=float)
PLATFORM_FEE_MAXIMUM = config('PLATFORM_FEE_MAXIMUM', default=500.00, cast=float)

# Security & Rate Limiting
OTP_EXPIRY_SECONDS = config('OTP_EXPIRY_SECONDS', default=300, cast=int)
OTP_LENGTH = 6
OTP_MAX_ATTEMPTS = 5
PASSWORD_RESET_TIMEOUT = config('PASSWORD_RESET_TIMEOUT', default=3600, cast=int)
RATE_LIMIT_PER_MINUTE = config('RATE_LIMIT_PER_MINUTE', default=60, cast=int)

# Logging
LOG_LEVEL = config('DJANGO_LOG_LEVEL', default='INFO')
os.makedirs(BASE_DIR / 'logs', exist_ok=True)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}', 'style': '{'},
        'simple': {'format': '{levelname} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'maxBytes': 1024 * 1024 * 10,
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {'handlers': ['console', 'file'], 'level': LOG_LEVEL, 'propagate': True},
        'apps': {'handlers': ['console', 'file'], 'level': LOG_LEVEL, 'propagate': True},
        'celery': {'handlers': ['console', 'file'], 'level': LOG_LEVEL, 'propagate': True},
    },
}

# Sentry (optional)
SENTRY_DSN = config('SENTRY_DSN', default='')
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        environment='production' if not DEBUG else 'development',
    )

# SSL / HTTPS (enforced when DEBUG=False)
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_REDIRECT_EXEMPT = [r'^health/$']

# Security headers
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'

# Frontend URL for email links
FRONTEND_URL = config('FRONTEND_URL', default='http://localhost:5173')

# Default group settings
DEFAULT_CONTRIBUTION_AMOUNT = config('DEFAULT_CONTRIBUTION_AMOUNT', default=100.00, cast=float)
DEFAULT_CYCLE_LENGTH = config('DEFAULT_CYCLE_LENGTH', default=10, cast=int)
DEFAULT_FREQUENCY = config('DEFAULT_FREQUENCY', default='monthly')

# Audit log settings
AUDITLOG_ENABLE = True
AUDITLOG_EXCLUDE_MODELS = ['contenttypes.ContentType', 'sessions.Session']

# Admin site customisation
ADMIN_SITE_HEADER = "Digital Ekub Platform Administration"
ADMIN_SITE_TITLE = "Ekub Admin"
ADMIN_INDEX_TITLE = "Welcome to Ekub Admin Panel"

# Health check
HEALTH_CHECK = {
    'ENDPOINT': '/health/',
    'TIMEOUT': 5,
    'CHECK_DATABASE': True,
    'CHECK_REDIS': True,
    'CHECK_CELERY': True,
}