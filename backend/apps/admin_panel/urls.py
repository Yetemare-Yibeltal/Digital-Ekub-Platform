"""
URL configuration for the admin panel app.

This module defines all URL patterns for administrative endpoints:
- Dashboard statistics and system health
- User management (suspend, activate, verify, delete, restore)
- Group management (approve, complete, cancel, pause, resume)
- Payment management (manual process, refund, mark failed)
- Contribution management (mark paid, refund, waive)
- Notification broadcasting to users and groups
- Report generation and management (daily, weekly, monthly, quarterly, custom)
- Audit log viewing with filtering
- System settings management (CRUD, bulk update)
- Admin preferences (get, update)
- Maintenance operations (clear cache, run maintenance, backup, sync)
- ViewSets for AdminAction, AdminLog, SystemSetting, Report, ReportSchedule, AuditTrail, DashboardWidget
- Bulk actions on users, groups, payments, contributions

All endpoints are versioned under /api/v1/admin/ and include detailed
documentation for each route with HTTP methods, request/response examples,
and permission requirements.

============================================================================
API ENDPOINTS REFERENCE
============================================================================

DASHBOARD (Base URL: /api/v1/admin/dashboard/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /dashboard/                       Get dashboard statistics and health
GET     /dashboard/stats/                 Get dashboard statistics only
GET     /dashboard/health/                Get system health check

USER MANAGEMENT (Base URL: /api/v1/admin/users/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
POST    /users/{user_id}/{action}/        Perform action on user (suspend, activate, verify, delete, restore)

GROUP MANAGEMENT (Base URL: /api/v1/admin/groups/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
POST    /groups/{group_id}/{action}/      Perform action on group (approve, complete, cancel, pause, resume)

PAYMENT MANAGEMENT (Base URL: /api/v1/admin/payments/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
POST    /payments/                        Perform payment actions (manual_payment, refund, mark_failed)

CONTRIBUTION MANAGEMENT (Base URL: /api/v1/admin/contributions/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
POST    /contributions/                   Perform contribution actions (mark_paid, refund, waive)

NOTIFICATION BROADCAST (Base URL: /api/v1/admin/broadcast/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
POST    /broadcast/                       Broadcast notification to users or group

REPORT GENERATION (Base URL: /api/v1/admin/reports/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
POST    /reports/generate/                Generate a report

AUDIT LOG (Base URL: /api/v1/admin/audit/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /audit/logs/                      Get audit logs with filtering

SYSTEM SETTINGS (Base URL: /api/v1/admin/settings/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /settings/                        List system settings
POST    /settings/                        Create a system setting
GET     /settings/{key}/                  Retrieve a system setting
PUT     /settings/{key}/                  Update a system setting
DELETE  /settings/{key}/                  Delete a system setting

ADMIN PREFERENCES (Base URL: /api/v1/admin/preferences/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /preferences/                     Get current admin's preferences
PUT     /preferences/                     Update current admin's preferences

MAINTENANCE (Base URL: /api/v1/admin/maintenance/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
POST    /maintenance/                     Perform maintenance tasks (clear_cache, run_maintenance, backup, sync_settings)

ADMIN ACTIONS (Base URL: /api/v1/admin/actions/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /actions/                         List admin actions
GET     /actions/{id}/                    Retrieve admin action details

ADMIN LOGS (Base URL: /api/v1/admin/logs/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /logs/                            List admin logs
GET     /logs/{id}/                       Retrieve admin log details

REPORTS (Base URL: /api/v1/admin/reports/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /reports/                         List reports
POST    /reports/                         Create a report
GET     /reports/{id}/                    Retrieve report details
PUT     /reports/{id}/                    Update report
PATCH   /reports/{id}/                    Update report
DELETE  /reports/{id}/                    Delete report
POST    /reports/{id}/download/           Download report

REPORT SCHEDULES (Base URL: /api/v1/admin/report_schedules/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /report_schedules/                List report schedules
POST    /report_schedules/                Create a report schedule
GET     /report_schedules/{id}/           Retrieve report schedule details
PUT     /report_schedules/{id}/           Update report schedule
PATCH   /report_schedules/{id}/           Update report schedule
DELETE  /report_schedules/{id}/           Delete report schedule
POST    /report_schedules/{id}/run_now/   Run schedule immediately

AUDIT TRAILS (Base URL: /api/v1/admin/audit_trails/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /audit_trails/                    List audit trails
GET     /audit_trails/{id}/               Retrieve audit trail details

DASHBOARD WIDGETS (Base URL: /api/v1/admin/widgets/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /widgets/                         List dashboard widgets
POST    /widgets/                         Create a dashboard widget
GET     /widgets/{id}/                    Retrieve dashboard widget details
PUT     /widgets/{id}/                    Update dashboard widget
PATCH   /widgets/{id}/                    Update dashboard widget
DELETE  /widgets/{id}/                    Delete dashboard widget

BULK ACTIONS (Base URL: /api/v1/admin/bulk/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
POST    /bulk/                            Perform bulk actions on resources

============================================================================
QUERY PARAMETERS
============================================================================

Admin Actions List:
- admin_id: filter by admin ID
- user_id: filter by user ID
- action: filter by action type
- date_from: filter by timestamp (ISO format)
- date_to: filter by timestamp (ISO format)
- ordering: sort field (e.g., -timestamp)

Admin Logs List:
- admin_id: filter by admin ID
- level: filter by log level (info, warning, error, critical)
- module: filter by module name (contains)
- date_from: filter by timestamp (ISO format)
- date_to: filter by timestamp (ISO format)
- ordering: sort field (e.g., -timestamp)

System Settings List:
- category: filter by category
- ordering: sort field (e.g., key)

Reports List:
- report_type: filter by report type (daily, weekly, monthly, quarterly, custom)
- generated_by: filter by admin ID
- date_from: filter by generated_at (ISO format)
- date_to: filter by generated_at (ISO format)
- ordering: sort field (e.g., -generated_at)

Report Schedules List:
- is_active: filter by active status (true/false)
- frequency: filter by frequency (daily, weekly, monthly)
- ordering: sort field (e.g., next_run)

Audit Trails List:
- user_id: filter by user ID
- action: filter by action (create, update, delete, view, login, logout, export, import)
- content_type: filter by content type model name
- object_id: filter by object ID
- date_from: filter by timestamp (ISO format)
- date_to: filter by timestamp (ISO format)
- ordering: sort field (e.g., -timestamp)

Dashboard Widgets List:
- is_active: filter by active status (true/false)
- widget_type: filter by widget type (stats, chart, table, list, custom, alert, progress)
- ordering: sort field (e.g., order)

============================================================================
PERMISSIONS
============================================================================

All admin endpoints require authentication.
- IsAdminUser: user must be staff
- IsSuperAdmin: user must be superuser
- CanManageUsers: manage users permission
- CanManageGroups: manage groups permission
- CanManagePayments: manage payments permission
- CanManageContributions: manage contributions permission
- CanBroadcastNotifications: broadcast notifications permission
- CanViewReports: view reports permission
- CanGenerateReports: generate reports permission
- CanViewAuditLogs: view audit logs permission
- CanManageSettings: manage system settings permission
- CanManageSystem: manage system permission
- CanPerformBulkActions: perform bulk actions permission
- CanViewDashboard: view dashboard permission

============================================================================
EXAMPLE REQUESTS/RESPONSES
============================================================================

POST /api/v1/admin/users/5/suspend/
Request:
{
    "reason": "Violation of terms"
}
Response:
{
    "message": "User suspended successfully.",
    "user": {
        "id": 5,
        "email": "user@example.com",
        "full_name": "John Doe",
        "is_active": false,
        "is_suspended": true
    }
}

POST /api/v1/admin/payments/
Request:
{
    "action": "manual_payment",
    "user_id": 5,
    "group_id": 3,
    "amount": 1000.00
}
Response:
{
    "message": "Manual payment processed successfully.",
    "data": {
        "payment_id": 10,
        "amount": 1000.0,
        "status": "completed"
    }
}

POST /api/v1/admin/broadcast/
Request:
{
    "target_type": "users",
    "user_ids": [1, 2, 3],
    "message": "System maintenance tonight.",
    "title": "Maintenance Alert",
    "notification_type": "alert"
}
Response:
{
    "message": "Notification broadcasted to 3 users.",
    "count": 3
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
router.register(r'actions', views.AdminActionViewSet, basename='admin-action')
router.register(r'logs', views.AdminLogViewSet, basename='admin-log')
router.register(r'settings', views.SystemSettingViewSet, basename='system-setting')
router.register(r'reports', views.ReportViewSet, basename='report')
router.register(r'report_schedules', views.ReportScheduleViewSet, basename='report-schedule')
router.register(r'audit_trails', views.AuditTrailViewSet, basename='audit-trail')
router.register(r'widgets', views.DashboardWidgetViewSet, basename='dashboard-widget')

# ============================================================================
# URL PATTERNS
# ============================================================================

urlpatterns = [
    # Dashboard endpoints
    path('dashboard/', views.AdminDashboardView.as_view(), name='admin-dashboard'),
    path('dashboard/stats/', views.DashboardStatsView.as_view(), name='admin-dashboard-stats'),
    path('dashboard/health/', views.SystemHealthView.as_view(), name='admin-system-health'),

    # User management
    path('users/<int:user_id>/<str:action>/', views.UserManagementView.as_view(), name='admin-user-action'),

    # Group management
    path('groups/<int:group_id>/<str:action>/', views.GroupManagementView.as_view(), name='admin-group-action'),

    # Payment management
    path('payments/', views.PaymentManagementView.as_view(), name='admin-payment-action'),

    # Contribution management
    path('contributions/', views.ContributionManagementView.as_view(), name='admin-contribution-action'),

    # Notification broadcast
    path('broadcast/', views.NotificationBroadcastView.as_view(), name='admin-broadcast'),

    # Report generation (separate from router for custom action)
    path('reports/generate/', views.ReportGenerationView.as_view(), name='admin-report-generate'),

    # Audit log (separate from router for custom filtering)
    path('audit/logs/', views.AuditLogView.as_view(), name='admin-audit-logs'),

    # System settings (separate from router for key-based operations)
    path('settings/', views.SystemSettingsView.as_view(), name='admin-settings'),
    path('settings/<str:key>/', views.SystemSettingsView.as_view(), name='admin-settings-detail'),

    # Admin preferences
    path('preferences/', views.AdminPreferenceView.as_view(), name='admin-preferences'),

    # Maintenance
    path('maintenance/', views.MaintenanceView.as_view(), name='admin-maintenance'),

    # Bulk actions
    path('bulk/', views.AdminBulkActionView.as_view(), name='admin-bulk'),

    # Router URLs (includes all ViewSet endpoints)
    path('', include(router.urls)),
]

# ============================================================================
# URL PATTERN SUMMARY (for quick reference)
# ============================================================================

"""
SUMMARY OF ALL URL PATTERNS WITH METHODS AND DESCRIPTIONS

------------------------------------------------------------------------------
DASHBOARD
------------------------------------------------------------------------------
GET    /dashboard/                            Get dashboard statistics and health
GET    /dashboard/stats/                      Get dashboard statistics only
GET    /dashboard/health/                     Get system health check

------------------------------------------------------------------------------
USER MANAGEMENT
------------------------------------------------------------------------------
POST   /users/{user_id}/suspend/              Suspend a user
POST   /users/{user_id}/activate/             Activate a user
POST   /users/{user_id}/verify/               Verify a user's identity
POST   /users/{user_id}/delete/               Soft delete a user
POST   /users/{user_id}/restore/              Restore a soft-deleted user

------------------------------------------------------------------------------
GROUP MANAGEMENT
------------------------------------------------------------------------------
POST   /groups/{group_id}/approve/            Approve a pending group
POST   /groups/{group_id}/complete/           Complete a group
POST   /groups/{group_id}/cancel/             Cancel a group
POST   /groups/{group_id}/pause/              Pause a group
POST   /groups/{group_id}/resume/             Resume a paused group

------------------------------------------------------------------------------
PAYMENT MANAGEMENT
------------------------------------------------------------------------------
POST   /payments/                             Process manual payment, refund, or mark failed
Body: { "action": "manual_payment", "user_id": ..., "group_id": ..., "amount": ... }
      { "action": "refund", "payment_id": ..., "reason": ... }
      { "action": "mark_failed", "payment_id": ..., "reason": ... }

------------------------------------------------------------------------------
CONTRIBUTION MANAGEMENT
------------------------------------------------------------------------------
POST   /contributions/                        Mark paid, refund, or waive contribution
Body: { "action": "mark_paid", "contribution_id": ... }
      { "action": "refund", "contribution_id": ..., "reason": ... }
      { "action": "waive", "contribution_id": ..., "amount": ..., "reason": ... }

------------------------------------------------------------------------------
NOTIFICATION BROADCAST
------------------------------------------------------------------------------
POST   /broadcast/                            Broadcast notification
Body: { "target_type": "users", "user_ids": [...], "message": "...", "title": "...", "notification_type": "..." }
      { "target_type": "group", "group_id": ..., "message": "...", "title": "...", "notification_type": "...", "exclude_user_id": ... }

------------------------------------------------------------------------------
REPORTS
------------------------------------------------------------------------------
POST   /reports/generate/                     Generate a report
Body: { "report_type": "daily|weekly|monthly|quarterly|custom", "date_range_start": "2025-01-01", "date_range_end": "2025-01-31", "title": "...", "format": "json|csv|pdf|excel" }

------------------------------------------------------------------------------
AUDIT LOG
------------------------------------------------------------------------------
GET    /audit/logs/                           Get audit logs with filtering (user_id, action, content_type, limit)

------------------------------------------------------------------------------
SYSTEM SETTINGS
------------------------------------------------------------------------------
GET    /settings/                             List system settings
POST   /settings/                             Create a system setting
GET    /settings/{key}/                       Retrieve a system setting
PUT    /settings/{key}/                       Update a system setting
DELETE /settings/{key}/                       Delete a system setting

------------------------------------------------------------------------------
ADMIN PREFERENCES
------------------------------------------------------------------------------
GET    /preferences/                          Get current admin's preferences
PUT    /preferences/                          Update current admin's preferences

------------------------------------------------------------------------------
MAINTENANCE
------------------------------------------------------------------------------
POST   /maintenance/                          Perform maintenance (clear_cache, run_maintenance, backup, sync_settings)

------------------------------------------------------------------------------
ADMIN ACTIONS (ViewSet)
------------------------------------------------------------------------------
GET    /actions/                              List admin actions
GET    /actions/{id}/                         Retrieve admin action details

------------------------------------------------------------------------------
ADMIN LOGS (ViewSet)
------------------------------------------------------------------------------
GET    /logs/                                 List admin logs
GET    /logs/{id}/                            Retrieve admin log details

------------------------------------------------------------------------------
REPORTS (ViewSet)
------------------------------------------------------------------------------
GET    /reports/                              List reports
POST   /reports/                              Create a report
GET    /reports/{id}/                         Retrieve report details
PUT    /reports/{id}/                         Update report
PATCH  /reports/{id}/                         Update report
DELETE /reports/{id}/                         Delete report
POST   /reports/{id}/download/                Download report

------------------------------------------------------------------------------
REPORT SCHEDULES (ViewSet)
------------------------------------------------------------------------------
GET    /report_schedules/                     List report schedules
POST   /report_schedules/                     Create a report schedule
GET    /report_schedules/{id}/                Retrieve report schedule details
PUT    /report_schedules/{id}/                Update report schedule
PATCH  /report_schedules/{id}/                Update report schedule
DELETE /report_schedules/{id}/                Delete report schedule
POST   /report_schedules/{id}/run_now/        Run schedule immediately

------------------------------------------------------------------------------
AUDIT TRAILS (ViewSet)
------------------------------------------------------------------------------
GET    /audit_trails/                         List audit trails
GET    /audit_trails/{id}/                    Retrieve audit trail details

------------------------------------------------------------------------------
DASHBOARD WIDGETS (ViewSet)
------------------------------------------------------------------------------
GET    /widgets/                              List dashboard widgets
POST   /widgets/                              Create a dashboard widget
GET    /widgets/{id}/                         Retrieve dashboard widget details
PUT    /widgets/{id}/                         Update dashboard widget
PATCH  /widgets/{id}/                         Update dashboard widget
DELETE /widgets/{id}/                         Delete dashboard widget

------------------------------------------------------------------------------
BULK ACTIONS
------------------------------------------------------------------------------
POST   /bulk/                                 Perform bulk actions
Body: { "action": "suspend", "resource_type": "user", "ids": [1,2,3], "details": {"reason": "..."} }

============================================================================
PERMISSION MATRIX
============================================================================

Authenticated + AdminUser + CanViewDashboard:
- GET /dashboard/, /dashboard/stats/

Authenticated + AdminUser + CanManageSystem:
- GET /dashboard/health/
- POST /maintenance/

Authenticated + AdminUser + CanManageUsers:
- POST /users/{user_id}/{action}/

Authenticated + AdminUser + CanManageGroups:
- POST /groups/{group_id}/{action}/

Authenticated + AdminUser + CanManagePayments:
- POST /payments/

Authenticated + AdminUser + CanManageContributions:
- POST /contributions/

Authenticated + AdminUser + CanBroadcastNotifications:
- POST /broadcast/

Authenticated + AdminUser + CanGenerateReports:
- POST /reports/generate/
- All /reports/ endpoints (create, update, delete)

Authenticated + AdminUser + CanViewReports:
- GET /reports/ (list, retrieve)

Authenticated + AdminUser + CanViewAuditLogs:
- GET /audit/logs/
- GET /actions/, /logs/, /audit_trails/

Authenticated + AdminUser + CanManageSettings:
- GET /settings/, POST /settings/, PUT /settings/{key}/, DELETE /settings/{key}/
- PUT /preferences/
- All /widgets/ endpoints (create, update, delete)

Authenticated + AdminUser + CanViewDashboard:
- GET /widgets/ (list, retrieve)

Authenticated + SuperAdmin + CanPerformBulkActions:
- POST /bulk/

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