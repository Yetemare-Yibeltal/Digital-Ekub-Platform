"""ASGI entrypoint with WebSocket routing for real-time features."""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from django.urls import path
from apps.notifications.consumers import NotificationConsumer
from apps.groups.consumers import GroupConsumer
from apps.contributions.consumers import ContributionConsumer

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_asgi_app = get_asgi_application()

websocket_urlpatterns = [
    path('ws/notifications/', NotificationConsumer.as_asgi()),
    path('ws/groups/<int:group_id>/', GroupConsumer.as_asgi()),
    path('ws/contributions/<int:user_id>/', ContributionConsumer.as_asgi()),
]

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})