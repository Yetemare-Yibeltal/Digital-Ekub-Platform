"""
URL configuration for the notifications app.

This module defines all URL patterns for notification-related endpoints:
- Notification management (CRUD, mark read/unread, clear all, stats)
- Notification templates (CRUD, admin only)
- Notification preferences (CRUD, user-specific)
- Notification channels (CRUD, admin only)
- Notification delivery tracking (list, retrieve)
- Notification events (CRUD, process, retry)
- Notification schedules (CRUD, execute, cancel, reschedule)
- Notification digests (list, retrieve, send)
- Notification audit logs (list, retrieve)
- Notification statistics (admin only)
- Bulk notification sending (admin only)

All endpoints are versioned under /api/v1/notifications/ and include detailed
documentation for each route with HTTP methods, request/response examples,
and permission requirements.

============================================================================
API ENDPOINTS REFERENCE
============================================================================

NOTIFICATIONS (Base URL: /api/v1/notifications/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /notifications/                   List notifications with filtering
POST    /notifications/                   Create a new notification
GET     /notifications/{id}/              Retrieve notification details
PUT     /notifications/{id}/              Update notification (full)
PATCH   /notifications/{id}/              Update notification (partial)
DELETE  /notifications/{id}/              Soft delete notification
POST    /notifications/{id}/mark_read/    Mark notification as read
POST    /notifications/{id}/mark_unread/  Mark notification as unread
POST    /notifications/mark_all_read/     Mark all notifications as read
POST    /notifications/clear_all/         Clear all notifications
GET     /notifications/stats/             Get notification statistics
GET     /notifications/{id}/deliveries/   Get delivery records for notification
GET     /notifications/unread/            Get unread notifications
GET     /notifications/unread_count/      Get unread count
POST    /notifications/send/              Send a notification (admin)

NOTIFICATION TEMPLATES (Base URL: /api/v1/notifications/templates/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /templates/                       List templates (admin)
POST    /templates/                       Create a template (admin)
GET     /templates/{id}/                  Retrieve template details (admin)
PUT     /templates/{id}/                  Update template (admin)
PATCH   /templates/{id}/                  Update template (admin)
DELETE  /templates/{id}/                  Delete template (admin)

NOTIFICATION PREFERENCES (Base URL: /api/v1/notifications/preferences/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /preferences/                     List preferences
POST    /preferences/                     Create a preference
GET     /preferences/{id}/                Retrieve preference details
PUT     /preferences/{id}/                Update preference
PATCH   /preferences/{id}/                Update preference
DELETE  /preferences/{id}/                Delete preference
GET     /preferences/me/                  Get current user's preferences
PUT     /preferences/update_me/           Update current user's preferences

NOTIFICATION CHANNELS (Base URL: /api/v1/notifications/channels/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /channels/                        List channels (admin)
POST    /channels/                        Create a channel (admin)
GET     /channels/{id}/                   Retrieve channel details (admin)
PUT     /channels/{id}/                   Update channel (admin)
PATCH   /channels/{id}/                   Update channel (admin)
DELETE  /channels/{id}/                   Delete channel (admin)

NOTIFICATION DELIVERIES (Base URL: /api/v1/notifications/deliveries/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /deliveries/                      List deliveries
GET     /deliveries/{id}/                 Retrieve delivery details

NOTIFICATION EVENTS (Base URL: /api/v1/notifications/events/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /events/                          List events
POST    /events/                          Create an event
GET     /events/{id}/                     Retrieve event details
PUT     /events/{id}/                     Update event
PATCH   /events/{id}/                     Update event
DELETE  /events/{id}/                     Delete event
POST    /events/{id}/process/             Process an event
POST    /events/{id}/retry/               Retry processing a failed event

NOTIFICATION SCHEDULES (Base URL: /api/v1/notifications/schedules/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /schedules/                       List schedules
POST    /schedules/                       Create a schedule
GET     /schedules/{id}/                  Retrieve schedule details
PUT     /schedules/{id}/                  Update schedule
PATCH   /schedules/{id}/                  Update schedule
DELETE  /schedules/{id}/                  Delete schedule
POST    /schedules/{id}/execute/          Execute a scheduled notification
POST    /schedules/{id}/cancel/           Cancel a scheduled notification
POST    /schedules/{id}/reschedule/       Reschedule a scheduled notification

NOTIFICATION DIGESTS (Base URL: /api/v1/notifications/digests/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /digests/                         List digests
GET     /digests/{id}/                    Retrieve digest details
POST    /digests/{id}/send/               Send a digest

NOTIFICATION AUDITS (Base URL: /api/v1/notifications/audits/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /audits/                          List audit logs
GET     /audits/{id}/                     Retrieve audit details

STATISTICS (Base URL: /api/v1/notifications/stats/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /stats/                           Get notification statistics (admin)

BULK NOTIFICATIONS (Base URL: /api/v1/notifications/bulk/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
POST    /bulk/send/                       Send bulk notifications (admin)

============================================================================
QUERY PARAMETERS
============================================================================

Notifications List:
- type: filter by notification type (info, success, warning, error, reminder, etc.)
- priority: filter by priority (low, medium, high, urgent)
- is_read: filter by read status (true/false)
- date_from: filter by created_at (ISO format)
- date_to: filter by created_at (ISO format)
- search: search in title and message
- object_type: filter by object type
- group_id: filter by group ID
- ordering: sort field (e.g., -created_at, priority)

Templates List:
- is_active: filter by active status (true/false)
- notification_type: filter by notification type
- search: search in name and description
- ordering: sort field (e.g., name, -created_at)

Deliveries List:
- notification_id: filter by notification ID
- status: filter by status (pending, sent, delivered, failed, bounced, blocked)
- channel: filter by channel (email, sms, push, in_app, webhook)
- ordering: sort field (e.g., -created_at)

Events List:
- event_type: filter by event type
- processed: filter by processed status (true/false)
- ordering: sort field (e.g., -created_at)

Schedules List:
- status: filter by status (pending, sent, failed, cancelled)
- ordering: sort field (e.g., scheduled_at)

Digests List:
- digest_type: filter by digest type (daily, weekly)
- ordering: sort field (e.g., -created_at)

Audits List:
- notification_id: filter by notification ID
- action: filter by action
- ordering: sort field (e.g., -timestamp)

============================================================================
PERMISSIONS
============================================================================

Public endpoints: None (all require authentication)
Authenticated endpoints: IsAuthenticated
User-specific: Users see only their own notifications
Admin endpoints: IsSuperAdminUser

Notification Actions:
- create: CanCreateNotification (authenticated)
- update/delete: CanUpdateNotification / CanDeleteNotification (owner or admin)
- mark_read/mark_unread: IsNotificationOwner
- mark_all_read/clear_all: IsAuthenticated (current user only)

Template Actions:
- All: IsSuperAdminUser

Preference Actions:
- me/update_me: IsAuthenticated (current user only)
- list/retrieve: IsAuthenticated (user-specific)
- update/delete: IsAuthenticated (owner or admin)

Channel Actions: IsSuperAdminUser

Delivery: IsAuthenticated (user-specific)

Event Actions:
- list/retrieve: IsAuthenticated (user-specific)
- create: IsAuthenticated
- update/delete: IsSuperAdminUser
- process/retry: IsAuthenticated

Schedule Actions:
- list/retrieve: IsAuthenticated (user-specific)
- create: CanSendNotification
- update/delete: IsSuperAdminUser
- execute/cancel/reschedule: IsAuthenticated

Digest: IsAuthenticated (user-specific)

Audit: IsAuthenticated (user-specific)

Statistics: IsSuperAdminUser

Bulk: IsSuperAdminUser

============================================================================
EXAMPLE REQUESTS/RESPONSES
============================================================================

POST /api/v1/notifications/
Request:
{
    "user": 5,
    "notification_type": "info",
    "title": "Payment Received",
    "message": "Your payment of 1000 ETB has been received.",
    "priority": "high",
    "send_email": true,
    "send_sms": false,
    "send_push": true,
    "send_in_app": true
}
Response:
{
    "success": true,
    "data": {
        "id": 1,
        "message": "Your payment of 1000 ETB has been received.",
        "notification_type": "info",
        ...
    },
    "message": "Notification sent successfully."
}

POST /api/v1/notifications/mark_all_read/
Response:
{
    "message": "Marked 5 notifications as read.",
    "count": 5
}

============================================================================
ERROR RESPONSES
============================================================================

All endpoints return standardized error responses:
{
    "success": false,
    "status_code": 400,
    "code": "validation_error",
    "message": "Human readable error message",
    "errors": {"field": ["Error detail"]},
    "extra_data": {}
}

============================================================================
SUCCESS RESPONSES
============================================================================

All endpoints return standardized success responses:
{
    "success": true,
    "data": {...},        # Optional
    "message": "Human readable success message",  # Optional
    "pagination": {...}   # For list endpoints
}
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

# ============================================================================
# ROUTER SETUP
# ============================================================================

router = DefaultRouter()
router.register(r'notifications', views.NotificationViewSet, basename='notification')
router.register(r'templates', views.NotificationTemplateViewSet, basename='template')
router.register(r'preferences', views.NotificationPreferenceViewSet, basename='preference')
router.register(r'channels', views.NotificationChannelViewSet, basename='channel')
router.register(r'deliveries', views.NotificationDeliveryViewSet, basename='delivery')
router.register(r'events', views.NotificationEventViewSet, basename='event')
router.register(r'schedules', views.NotificationScheduleViewSet, basename='schedule')
router.register(r'digests', views.NotificationDigestViewSet, basename='digest')
router.register(r'audits', views.NotificationAuditViewSet, basename='audit')

# ============================================================================
# URL PATTERNS
# ============================================================================

urlpatterns = [
    # Router URLs
    path('', include(router.urls)),

    # Statistics endpoint (admin only)
    path('stats/', views.NotificationStatsView.as_view(), name='notification-stats'),

    # Bulk notification endpoint (admin only)
    path('bulk/send/', views.BulkNotificationSendView.as_view(), name='bulk-notification-send'),
]

# ============================================================================
# URL PATTERN SUMMARY (for quick reference)
# ============================================================================

"""
SUMMARY OF ALL URL PATTERNS WITH METHODS AND DESCRIPTIONS

------------------------------------------------------------------------------
NOTIFICATIONS
------------------------------------------------------------------------------
GET    /notifications/                                     List notifications with filtering
POST   /notifications/                                     Create a new notification
GET    /notifications/{id}/                                Retrieve notification details
PUT    /notifications/{id}/                                Update notification (full)
PATCH  /notifications/{id}/                                Update notification (partial)
DELETE /notifications/{id}/                                Soft delete notification
POST   /notifications/{id}/mark_read/                      Mark notification as read
POST   /notifications/{id}/mark_unread/                    Mark notification as unread
POST   /notifications/mark_all_read/                       Mark all notifications as read
POST   /notifications/clear_all/                           Clear all notifications
GET    /notifications/stats/                               Get notification statistics
GET    /notifications/{id}/deliveries/                     Get delivery records for notification
GET    /notifications/unread/                              Get unread notifications
GET    /notifications/unread_count/                        Get unread count
POST   /notifications/send/                                Send a notification (admin)

------------------------------------------------------------------------------
NOTIFICATION TEMPLATES
------------------------------------------------------------------------------
GET    /templates/                                         List templates (admin)
POST   /templates/                                         Create a template (admin)
GET    /templates/{id}/                                    Retrieve template details (admin)
PUT    /templates/{id}/                                    Update template (admin)
PATCH  /templates/{id}/                                    Update template (admin)
DELETE /templates/{id}/                                    Delete template (admin)

------------------------------------------------------------------------------
NOTIFICATION PREFERENCES
------------------------------------------------------------------------------
GET    /preferences/                                       List preferences
POST   /preferences/                                       Create a preference
GET    /preferences/{id}/                                  Retrieve preference details
PUT    /preferences/{id}/                                  Update preference
PATCH  /preferences/{id}/                                  Update preference
DELETE /preferences/{id}/                                  Delete preference
GET    /preferences/me/                                    Get current user's preferences
PUT    /preferences/update_me/                             Update current user's preferences

------------------------------------------------------------------------------
NOTIFICATION CHANNELS
------------------------------------------------------------------------------
GET    /channels/                                          List channels (admin)
POST   /channels/                                          Create a channel (admin)
GET    /channels/{id}/                                     Retrieve channel details (admin)
PUT    /channels/{id}/                                     Update channel (admin)
PATCH  /channels/{id}/                                     Update channel (admin)
DELETE /channels/{id}/                                     Delete channel (admin)

------------------------------------------------------------------------------
NOTIFICATION DELIVERIES
------------------------------------------------------------------------------
GET    /deliveries/                                        List deliveries
GET    /deliveries/{id}/                                   Retrieve delivery details

------------------------------------------------------------------------------
NOTIFICATION EVENTS
------------------------------------------------------------------------------
GET    /events/                                            List events
POST   /events/                                            Create an event
GET    /events/{id}/                                       Retrieve event details
PUT    /events/{id}/                                       Update event
PATCH  /events/{id}/                                       Update event
DELETE /events/{id}/                                       Delete event
POST   /events/{id}/process/                               Process an event
POST   /events/{id}/retry/                                 Retry processing a failed event

------------------------------------------------------------------------------
NOTIFICATION SCHEDULES
------------------------------------------------------------------------------
GET    /schedules/                                         List schedules
POST   /schedules/                                         Create a schedule
GET    /schedules/{id}/                                    Retrieve schedule details
PUT    /schedules/{id}/                                    Update schedule
PATCH  /schedules/{id}/                                    Update schedule
DELETE /schedules/{id}/                                    Delete schedule
POST   /schedules/{id}/execute/                            Execute a scheduled notification
POST   /schedules/{id}/cancel/                             Cancel a scheduled notification
POST   /schedules/{id}/reschedule/                         Reschedule a scheduled notification

------------------------------------------------------------------------------
NOTIFICATION DIGESTS
------------------------------------------------------------------------------
GET    /digests/                                           List digests
GET    /digests/{id}/                                      Retrieve digest details
POST   /digests/{id}/send/                                 Send a digest

------------------------------------------------------------------------------
NOTIFICATION AUDITS
------------------------------------------------------------------------------
GET    /audits/                                            List audit logs
GET    /audits/{id}/                                       Retrieve audit details

------------------------------------------------------------------------------
STATISTICS
------------------------------------------------------------------------------
GET    /stats/                                             Get notification statistics (admin)

------------------------------------------------------------------------------
BULK NOTIFICATIONS
------------------------------------------------------------------------------
POST   /bulk/send/                                         Send bulk notifications (admin)

============================================================================
PERMISSION MATRIX
============================================================================

Authenticated endpoints: IsAuthenticated
- GET /notifications/, GET /notifications/{id}/
- GET /notifications/unread/, GET /notifications/unread_count/
- GET /notifications/{id}/deliveries/
- GET /preferences/me/, PUT /preferences/update_me/
- GET /preferences/, GET /preferences/{id}/
- GET /deliveries/, GET /deliveries/{id}/
- GET /events/, GET /events/{id}/
- GET /schedules/, GET /schedules/{id}/
- GET /digests/, GET /digests/{id}/
- GET /audits/, GET /audits/{id}/

User-specific actions: IsAuthenticated + IsNotificationOwner
- POST /notifications/{id}/mark_read/, /mark_unread/

Admin endpoints: IsAuthenticated + IsSuperAdminUser
- POST /notifications/send/
- GET /notifications/stats/
- GET /stats/
- POST /bulk/send/
- All /templates/ endpoints
- All /channels/ endpoints
- PUT/PATCH/DELETE /preferences/{id}/
- PUT/PATCH/DELETE /events/{id}/
- PUT/PATCH/DELETE /schedules/{id}/
- POST /schedules/{id}/execute/, /cancel/, /reschedule/

============================================================================
FILTERING AND SEARCHING
============================================================================

GET /notifications/?type=info&priority=high&is_read=false&ordering=-created_at
Returns unread high-priority info notifications, sorted by creation date descending.

GET /deliveries/?notification_id=5&status=delivered
Returns delivered deliveries for notification 5.

GET /templates/?is_active=true&notification_type=payment
Returns active templates for payment notifications.

============================================================================
PAGINATION
============================================================================

All list endpoints support pagination using query parameters:
- page: Page number (default: 1)
- page_size: Number of items per page (default: 20, max: 100)

Response includes pagination metadata:
{
    "count": 100,
    "total_pages": 5,
    "current_page": 1,
    "page_size": 20,
    "has_next": true,
    "has_previous": false,
    "next": "http://.../?page=2",
    "previous": null,
    "results": [...]
}
"""

# ============================================================================
# DEBUG TOOLBAR
# ============================================================================

# If debug toolbar is installed, add its URLs (only in DEBUG mode)
if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls)),
    ]