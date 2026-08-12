from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView


@csrf_exempt
def health_check(request):
    """Health check endpoint for load balancers and monitoring."""
    return JsonResponse({
        'status': 'ok',
        'service': 'ekub-backend',
        'version': '1.0.0',
        'environment': 'development' if settings.DEBUG else 'production'
    })


def ready_check(request):
    """Readiness probe for Kubernetes and orchestration tools."""
    return HttpResponse('ready', status=200)


def ping(request):
    """Simple ping endpoint for network connectivity testing."""
    return HttpResponse('pong', status=200)


urlpatterns = [
    # Django admin interface
    path('admin/', admin.site.urls),

    # Health and monitoring endpoints
    path('health/', health_check, name='health_check'),
    path('ready/', ready_check, name='ready_check'),
    path('ping/', ping, name='ping'),

    # API documentation - OpenAPI schema, Swagger UI, ReDoc
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # API v1 endpoints
    path('api/v1/auth/', include('apps.users.urls')),
    path('api/v1/groups/', include('apps.groups.urls')),
    path('api/v1/contributions/', include('apps.contributions.urls')),
    path('api/v1/payments/', include('apps.payments.urls')),
    path('api/v1/notifications/', include('apps.notifications.urls')),
    path('api/v1/audit/', include('apps.audit.urls')),
    path('api/v1/admin/', include('apps.admin_panel.urls')),
]

# Serve static and media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)