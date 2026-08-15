"""
URL configuration for the audit app.

This module defines all URL patterns for audit and monitoring endpoints:
- Audit Logs (CRUD, filtering, stats, summary)
- Audit Events (CRUD, process, retry)
- Audit Rules (CRUD, evaluate)
- Audit Alerts (CRUD, acknowledge, resolve, dismiss)
- Audit Reports (CRUD, download, generate)
- Audit Retention Policies (CRUD, enforce)
- Security Events (CRUD, stats)
- User Activities (CRUD, summary)
- System Health (CRUD, overview)
- Performance Metrics (CRUD, aggregate, overview)
- Anomaly Detection (CRUD, resolve, mark_false_positive)
- Audit Statistics (overview)
- Security Statistics (overview)

All endpoints are versioned under /api/v1/audit/ and include detailed
documentation for each route with HTTP methods, request/response examples,
and permission requirements.

============================================================================
API ENDPOINTS REFERENCE
============================================================================

AUDIT LOGS (Base URL: /api/v1/audit/logs/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /logs/                            List audit logs with filtering
POST    /logs/                            Create an audit log entry
GET     /logs/{id}/                       Retrieve audit log details
PUT     /logs/{id}/                       Update audit log (full)
PATCH   /logs/{id}/                       Update audit log (partial)
DELETE  /logs/{id}/                       Delete audit log
GET     /logs/stats/                      Get audit log statistics
GET     /logs/summary/                    Get audit log summary

AUDIT EVENTS (Base URL: /api/v1/audit/events/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /events/                          List audit events
POST    /events/                          Create an audit event
GET     /events/{id}/                     Retrieve audit event details
PUT     /events/{id}/                     Update audit event
PATCH   /events/{id}/                     Update audit event
DELETE  /events/{id}/                     Delete audit event
POST    /events/{id}/process/             Process an event
POST    /events/{id}/retry/               Retry processing a failed event

AUDIT RULES (Base URL: /api/v1/audit/rules/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /rules/                           List audit rules
POST    /rules/                           Create an audit rule
GET     /rules/{id}/                      Retrieve audit rule details
PUT     /rules/{id}/                      Update audit rule
PATCH   /rules/{id}/                      Update audit rule
DELETE  /rules/{id}/                      Delete audit rule
POST    /rules/{id}/evaluate/             Evaluate rule against an audit log

AUDIT ALERTS (Base URL: /api/v1/audit/alerts/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /alerts/                          List audit alerts
POST    /alerts/                          Create an audit alert (auto-generated)
GET     /alerts/{id}/                     Retrieve audit alert details
PUT     /alerts/{id}/                     Update audit alert
PATCH   /alerts/{id}/                     Update audit alert
DELETE  /alerts/{id}/                     Delete audit alert
POST    /alerts/{id}/acknowledge/         Acknowledge an alert
POST    /alerts/{id}/resolve/             Resolve an alert
POST    /alerts/{id}/dismiss/             Dismiss an alert

AUDIT REPORTS (Base URL: /api/v1/audit/reports/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /reports/                         List audit reports
POST    /reports/                         Generate an audit report
GET     /reports/{id}/                    Retrieve audit report details
PUT     /reports/{id}/                    Update audit report
PATCH   /reports/{id}/                    Update audit report
DELETE  /reports/{id}/                    Delete audit report
POST    /reports/{id}/download/           Download an audit report

AUDIT RETENTION POLICIES (Base URL: /api/v1/audit/retention/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /retention/                       List retention policies
POST    /retention/                       Create a retention policy
GET     /retention/{id}/                  Retrieve retention policy details
PUT     /retention/{id}/                  Update retention policy
PATCH   /retention/{id}/                  Update retention policy
DELETE  /retention/{id}/                  Delete retention policy
POST    /retention/{id}/enforce/          Enforce a retention policy

SECURITY EVENTS (Base URL: /api/v1/audit/security/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /security/                        List security events
POST    /security/                        Create a security event
GET     /security/{id}/                   Retrieve security event details
PUT     /security/{id}/                   Update security event
PATCH   /security/{id}/                   Update security event
DELETE  /security/{id}/                   Delete security event
GET     /security/stats/                  Get security event statistics

USER ACTIVITIES (Base URL: /api/v1/audit/activities/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /activities/                      List user activities
POST    /activities/                      Create a user activity record
GET     /activities/{id}/                 Retrieve activity details
PUT     /activities/{id}/                 Update activity
PATCH   /activities/{id}/                 Update activity
DELETE  /activities/{id}/                 Delete activity
GET     /activities/summary/              Get user activity summary

SYSTEM HEALTH (Base URL: /api/v1/audit/health/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /health/                          List system health checks
POST    /health/                          Create a system health check
GET     /health/{id}/                     Retrieve health check details
PUT     /health/{id}/                     Update health check
PATCH   /health/{id}/                     Update health check
DELETE  /health/{id}/                     Delete health check
GET     /health/overview/                 Get system health overview

PERFORMANCE METRICS (Base URL: /api/v1/audit/metrics/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /metrics/                         List performance metrics
POST    /metrics/                         Create a performance metric
GET     /metrics/{id}/                    Retrieve metric details
PUT     /metrics/{id}/                    Update metric
PATCH   /metrics/{id}/                    Update metric
DELETE  /metrics/{id}/                    Delete metric
GET     /metrics/aggregate/               Get aggregate statistics for a metric
GET     /metrics/overview/                Get performance metrics overview

ANOMALY DETECTION (Base URL: /api/v1/audit/anomalies/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /anomalies/                       List anomalies
POST    /anomalies/                       Create an anomaly detection record
GET     /anomalies/{id}/                  Retrieve anomaly details
PUT     /anomalies/{id}/                  Update anomaly
PATCH   /anomalies/{id}/                  Update anomaly
DELETE  /anomalies/{id}/                  Delete anomaly
POST    /anomalies/{id}/resolve/          Resolve an anomaly
POST    /anomalies/{id}/mark_false_positive/ Mark anomaly as false positive

STATISTICS (Base URL: /api/v1/audit/stats/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /stats/audit/                     Get audit statistics
GET     /stats/security/                  Get security statistics

============================================================================
QUERY PARAMETERS
============================================================================

Audit Logs List:
- user_id: filter by user ID
- action: filter by action (CREATE, UPDATE, DELETE, VIEW, LOGIN, LOGOUT, etc.)
- resource: filter by resource type (USER, GROUP, PAYMENT, etc.)
- resource_id: filter by resource ID
- severity: filter by severity (info, warning, error, critical)
- date_from: filter by timestamp (ISO format)
- date_to: filter by timestamp (ISO format)
- search: search in action, resource, details, ip_address
- ordering: sort field (e.g., -timestamp)

Audit Events List:
- event_type: filter by event type
- user_id: filter by user ID
- processed: filter by processed status (true/false)
- date_from: filter by created_at (ISO format)
- date_to: filter by created_at (ISO format)
- ordering: sort field (e.g., -created_at)

Audit Rules List:
- is_active: filter by active status (true/false)
- severity: filter by severity
- action: filter by action (log, alert, notify, block)
- search: search in name and description
- ordering: sort field (e.g., -created_at)

Audit Alerts List:
- rule_id: filter by rule ID
- status: filter by status (new, acknowledged, resolved, dismissed)
- severity: filter by severity
- date_from: filter by timestamp (ISO format)
- date_to: filter by timestamp (ISO format)
- ordering: sort field (e.g., -timestamp)

Audit Reports List:
- report_type: filter by report type (compliance, security, activity, custom)
- generated_by: filter by admin ID
- date_from: filter by generated_at (ISO format)
- date_to: filter by generated_at (ISO format)
- ordering: sort field (e.g., -generated_at)

Security Events List:
- user_id: filter by user ID
- event_type: filter by event type
- severity: filter by severity
- date_from: filter by timestamp (ISO format)
- date_to: filter by timestamp (ISO format)
- ordering: sort field (e.g., -timestamp)

User Activities List:
- user_id: filter by user ID
- action: filter by action
- resource: filter by resource
- date_from: filter by timestamp (ISO format)
- date_to: filter by timestamp (ISO format)
- ordering: sort field (e.g., -timestamp)

System Health List:
- component: filter by component name
- status: filter by status (ok, warning, error, degraded)
- date_from: filter by checked_at (ISO format)
- date_to: filter by checked_at (ISO format)
- ordering: sort field (e.g., -checked_at)

Performance Metrics List:
- metric_name: filter by metric name
- date_from: filter by timestamp (ISO format)
- date_to: filter by timestamp (ISO format)
- ordering: sort field (e.g., -timestamp)

Anomaly Detection List:
- anomaly_type: filter by anomaly type (spike, drop, pattern, outlier, trend, seasonal)
- metric_name: filter by metric name
- status: filter by status (open, investigating, resolved, false_positive)
- severity: filter by severity
- date_from: filter by detected_at (ISO format)
- date_to: filter by detected_at (ISO format)
- ordering: sort field (e.g., -detected_at)

============================================================================
PERMISSIONS
============================================================================

All audit endpoints require authentication.
- IsAdminUser: user must be staff
- IsSuperAdmin: user must be superuser
- CanViewAuditLogs: view audit logs permission
- CanManageAuditRules: manage audit rules permission
- CanManageAuditAlerts: manage audit alerts permission
- CanGenerateAuditReports: generate audit reports permission
- CanViewSecurityEvents: view security events permission
- CanViewSystemHealth: view system health permission
- CanViewPerformanceMetrics: view performance metrics permission
- CanManageAnomalies: manage anomaly detections permission
- IsSystemAdmin: system admin permission (staff + specific flag)

Endpoint Permission Matrix:
- GET /logs/, /logs/{id}/, /logs/stats/, /logs/summary/: IsAdminUser + CanViewAuditLogs
- POST /logs/: IsAuthenticated
- PUT/PATCH/DELETE /logs/{id}/: IsAdminUser + CanViewAuditLogs
- GET /events/: IsAdminUser + CanViewAuditLogs
- POST /events/: IsAuthenticated
- PUT/PATCH/DELETE /events/{id}/: IsAdminUser + CanViewAuditLogs
- POST /events/{id}/process/, /retry/: IsAdminUser + CanViewAuditLogs
- GET /rules/: IsAdminUser + CanManageAuditRules
- POST /rules/: IsAdminUser + CanManageAuditRules
- PUT/PATCH/DELETE /rules/{id}/: IsAdminUser + CanManageAuditRules
- POST /rules/{id}/evaluate/: IsAdminUser + CanManageAuditRules
- GET /alerts/: IsAdminUser + CanManageAuditAlerts
- PUT/PATCH/DELETE /alerts/{id}/: IsAdminUser + CanManageAuditAlerts
- POST /alerts/{id}/acknowledge/, /resolve/, /dismiss/: IsAdminUser + CanManageAuditAlerts
- GET /reports/: IsAdminUser + CanViewAuditLogs
- POST /reports/: IsAdminUser + CanGenerateAuditReports
- PUT/PATCH/DELETE /reports/{id}/: IsAdminUser + CanGenerateAuditReports
- POST /reports/{id}/download/: IsAdminUser + CanViewAuditLogs
- GET /retention/: IsSuperAdmin
- POST /retention/: IsSuperAdmin
- PUT/PATCH/DELETE /retention/{id}/: IsSuperAdmin
- POST /retention/{id}/enforce/: IsSuperAdmin
- GET /security/: IsAdminUser + CanViewSecurityEvents
- POST /security/: IsAuthenticated
- PUT/PATCH/DELETE /security/{id}/: IsAdminUser + CanViewSecurityEvents
- GET /security/stats/: IsAdminUser + CanViewSecurityEvents
- GET /activities/: IsAdminUser + CanViewAuditLogs
- POST /activities/: IsAuthenticated
- PUT/PATCH/DELETE /activities/{id}/: IsAdminUser + CanViewAuditLogs
- GET /activities/summary/: IsAdminUser + CanViewAuditLogs
- GET /health/: IsAdminUser + CanViewSystemHealth
- POST /health/: IsSystemAdmin
- PUT/PATCH/DELETE /health/{id}/: IsSystemAdmin
- GET /health/overview/: IsAdminUser + CanViewSystemHealth
- GET /metrics/: IsAdminUser + CanViewPerformanceMetrics
- POST /metrics/: IsAuthenticated
- PUT/PATCH/DELETE /metrics/{id}/: IsAdminUser + CanViewPerformanceMetrics
- GET /metrics/aggregate/: IsAdminUser + CanViewPerformanceMetrics
- GET /metrics/overview/: IsAdminUser + CanViewPerformanceMetrics
- GET /anomalies/: IsAdminUser + CanManageAnomalies
- POST /anomalies/: IsSystemAdmin
- PUT/PATCH/DELETE /anomalies/{id}/: IsAdminUser + CanManageAnomalies
- POST /anomalies/{id}/resolve/, /mark_false_positive/: IsAdminUser + CanManageAnomalies
- GET /stats/audit/, /stats/security/: IsAdminUser + CanViewAuditLogs

============================================================================
EXAMPLE REQUESTS/RESPONSES
============================================================================

GET /api/v1/audit/logs/?user_id=5&severity=error&ordering=-timestamp
Response:
{
    "count": 10,
    "next": "http://.../?page=2",
    "previous": null,
    "results": [
        {
            "id": 1,
            "user_email": "user@example.com",
            "action": "UPDATE",
            "action_display": "Update",
            "resource": "USER",
            "severity": "error",
            "severity_display": "Error",
            "timestamp": "2025-01-01T12:00:00Z"
        }
    ]
}

POST /api/v1/audit/logs/
Request:
{
    "action": "CREATE",
    "resource": "PAYMENT",
    "resource_id": 123,
    "details": {"amount": 1000.00},
    "severity": "info"
}
Response:
{
    "id": 2,
    "user_email": "admin@example.com",
    "action": "CREATE",
    "resource": "PAYMENT",
    "severity": "info",
    "timestamp": "2025-01-01T12:05:00Z"
}

POST /api/v1/audit/alerts/{id}/acknowledge/
Response:
{
    "message": "Alert acknowledged.",
    "alert": {
        "id": 1,
        "rule_name": "High Severity Audit",
        "status_display": "Acknowledged",
        "timestamp": "2025-01-01T12:00:00Z"
    }
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
router.register(r'logs', views.AuditLogViewSet, basename='audit-log')
router.register(r'events', views.AuditEventViewSet, basename='audit-event')
router.register(r'rules', views.AuditRuleViewSet, basename='audit-rule')
router.register(r'alerts', views.AuditAlertViewSet, basename='audit-alert')
router.register(r'reports', views.AuditReportViewSet, basename='audit-report')
router.register(r'retention', views.AuditRetentionPolicyViewSet, basename='audit-retention')
router.register(r'security', views.SecurityEventViewSet, basename='security-event')
router.register(r'activities', views.UserActivityViewSet, basename='user-activity')
router.register(r'health', views.SystemHealthViewSet, basename='system-health')
router.register(r'metrics', views.PerformanceMetricViewSet, basename='performance-metric')
router.register(r'anomalies', views.AnomalyDetectionViewSet, basename='anomaly-detection')

# ============================================================================
# URL PATTERNS
# ============================================================================

urlpatterns = [
    # Router URLs
    path('', include(router.urls)),

    # Statistics endpoints
    path('stats/audit/', views.AuditStatisticsView.as_view(), name='audit-stats'),
    path('stats/security/', views.SecurityStatisticsView.as_view(), name='security-stats'),

    # Overview endpoints
    path('health/overview/', views.SystemHealthOverviewView.as_view(), name='system-health-overview'),
    path('metrics/overview/', views.PerformanceMetricsOverviewView.as_view(), name='performance-metrics-overview'),

    # Custom action endpoints (already in ViewSets via @action, but we keep them for clarity)
    # All custom actions are already registered through the router.
]

# ============================================================================
# URL PATTERN SUMMARY (for quick reference)
# ============================================================================

"""
SUMMARY OF ALL URL PATTERNS WITH METHODS AND DESCRIPTIONS

------------------------------------------------------------------------------
AUDIT LOGS
------------------------------------------------------------------------------
GET    /logs/                                     List audit logs with filtering
POST   /logs/                                     Create an audit log entry
GET    /logs/{id}/                                Retrieve audit log details
PUT    /logs/{id}/                                Update audit log (full)
PATCH  /logs/{id}/                                Update audit log (partial)
DELETE /logs/{id}/                                Delete audit log
GET    /logs/stats/                               Get audit log statistics
GET    /logs/summary/                             Get audit log summary

------------------------------------------------------------------------------
AUDIT EVENTS
------------------------------------------------------------------------------
GET    /events/                                   List audit events
POST   /events/                                   Create an audit event
GET    /events/{id}/                              Retrieve audit event details
PUT    /events/{id}/                              Update audit event
PATCH  /events/{id}/                              Update audit event
DELETE /events/{id}/                              Delete audit event
POST   /events/{id}/process/                      Process an event
POST   /events/{id}/retry/                        Retry processing a failed event

------------------------------------------------------------------------------
AUDIT RULES
------------------------------------------------------------------------------
GET    /rules/                                    List audit rules
POST   /rules/                                    Create an audit rule
GET    /rules/{id}/                               Retrieve audit rule details
PUT    /rules/{id}/                               Update audit rule
PATCH  /rules/{id}/                               Update audit rule
DELETE /rules/{id}/                               Delete audit rule
POST   /rules/{id}/evaluate/                      Evaluate rule against an audit log

------------------------------------------------------------------------------
AUDIT ALERTS
------------------------------------------------------------------------------
GET    /alerts/                                   List audit alerts
POST   /alerts/                                   Create an audit alert (auto-generated)
GET    /alerts/{id}/                              Retrieve audit alert details
PUT    /alerts/{id}/                              Update audit alert
PATCH  /alerts/{id}/                              Update audit alert
DELETE /alerts/{id}/                              Delete audit alert
POST   /alerts/{id}/acknowledge/                  Acknowledge an alert
POST   /alerts/{id}/resolve/                      Resolve an alert
POST   /alerts/{id}/dismiss/                      Dismiss an alert

------------------------------------------------------------------------------
AUDIT REPORTS
------------------------------------------------------------------------------
GET    /reports/                                  List audit reports
POST   /reports/                                  Generate an audit report
GET    /reports/{id}/                             Retrieve audit report details
PUT    /reports/{id}/                             Update audit report
PATCH  /reports/{id}/                             Update audit report
DELETE /reports/{id}/                             Delete audit report
POST   /reports/{id}/download/                    Download an audit report

------------------------------------------------------------------------------
AUDIT RETENTION POLICIES
------------------------------------------------------------------------------
GET    /retention/                                List retention policies
POST   /retention/                                Create a retention policy
GET    /retention/{id}/                           Retrieve retention policy details
PUT    /retention/{id}/                           Update retention policy
PATCH  /retention/{id}/                           Update retention policy
DELETE /retention/{id}/                           Delete retention policy
POST   /retention/{id}/enforce/                   Enforce a retention policy

------------------------------------------------------------------------------
SECURITY EVENTS
------------------------------------------------------------------------------
GET    /security/                                 List security events
POST   /security/                                 Create a security event
GET    /security/{id}/                            Retrieve security event details
PUT    /security/{id}/                            Update security event
PATCH  /security/{id}/                            Update security event
DELETE /security/{id}/                            Delete security event
GET    /security/stats/                           Get security event statistics

------------------------------------------------------------------------------
USER ACTIVITIES
------------------------------------------------------------------------------
GET    /activities/                               List user activities
POST   /activities/                               Create a user activity record
GET    /activities/{id}/                          Retrieve activity details
PUT    /activities/{id}/                          Update activity
PATCH  /activities/{id}/                          Update activity
DELETE /activities/{id}/                          Delete activity
GET    /activities/summary/                       Get user activity summary

------------------------------------------------------------------------------
SYSTEM HEALTH
------------------------------------------------------------------------------
GET    /health/                                   List system health checks
POST   /health/                                   Create a system health check
GET    /health/{id}/                              Retrieve health check details
PUT    /health/{id}/                              Update health check
PATCH  /health/{id}/                              Update health check
DELETE /health/{id}/                              Delete health check
GET    /health/overview/                          Get system health overview

------------------------------------------------------------------------------
PERFORMANCE METRICS
------------------------------------------------------------------------------
GET    /metrics/                                  List performance metrics
POST   /metrics/                                  Create a performance metric
GET    /metrics/{id}/                             Retrieve metric details
PUT    /metrics/{id}/                             Update metric
PATCH  /metrics/{id}/                             Update metric
DELETE /metrics/{id}/                             Delete metric
GET    /metrics/aggregate/                        Get aggregate statistics for a metric
GET    /metrics/overview/                         Get performance metrics overview

------------------------------------------------------------------------------
ANOMALY DETECTION
------------------------------------------------------------------------------
GET    /anomalies/                                List anomalies
POST   /anomalies/                                Create an anomaly detection record
GET    /anomalies/{id}/                           Retrieve anomaly details
PUT    /anomalies/{id}/                           Update anomaly
PATCH  /anomalies/{id}/                           Update anomaly
DELETE /anomalies/{id}/                           Delete anomaly
POST   /anomalies/{id}/resolve/                   Resolve an anomaly
POST   /anomalies/{id}/mark_false_positive/       Mark anomaly as false positive

------------------------------------------------------------------------------
STATISTICS
------------------------------------------------------------------------------
GET    /stats/audit/                              Get audit statistics
GET    /stats/security/                           Get security statistics

============================================================================
PERMISSION MATRIX (Detailed)
============================================================================

Logs:
- GET /logs/, /logs/{id}/, /logs/stats/, /logs/summary/: IsAdminUser + CanViewAuditLogs
- POST /logs/: IsAuthenticated
- PUT/PATCH/DELETE /logs/{id}/: IsAdminUser + CanViewAuditLogs

Events:
- GET /events/: IsAdminUser + CanViewAuditLogs
- POST /events/: IsAuthenticated
- PUT/PATCH/DELETE /events/{id}/: IsAdminUser + CanViewAuditLogs
- POST /events/{id}/process/, /retry/: IsAdminUser + CanViewAuditLogs

Rules:
- GET /rules/: IsAdminUser + CanManageAuditRules
- POST /rules/: IsAdminUser + CanManageAuditRules
- PUT/PATCH/DELETE /rules/{id}/: IsAdminUser + CanManageAuditRules
- POST /rules/{id}/evaluate/: IsAdminUser + CanManageAuditRules

Alerts:
- GET /alerts/: IsAdminUser + CanManageAuditAlerts
- PUT/PATCH/DELETE /alerts/{id}/: IsAdminUser + CanManageAuditAlerts
- POST /alerts/{id}/acknowledge/, /resolve/, /dismiss/: IsAdminUser + CanManageAuditAlerts

Reports:
- GET /reports/: IsAdminUser + CanViewAuditLogs
- POST /reports/: IsAdminUser + CanGenerateAuditReports
- PUT/PATCH/DELETE /reports/{id}/: IsAdminUser + CanGenerateAuditReports
- POST /reports/{id}/download/: IsAdminUser + CanViewAuditLogs

Retention:
- GET /retention/: IsSuperAdmin
- POST /retention/: IsSuperAdmin
- PUT/PATCH/DELETE /retention/{id}/: IsSuperAdmin
- POST /retention/{id}/enforce/: IsSuperAdmin

Security:
- GET /security/: IsAdminUser + CanViewSecurityEvents
- POST /security/: IsAuthenticated
- PUT/PATCH/DELETE /security/{id}/: IsAdminUser + CanViewSecurityEvents
- GET /security/stats/: IsAdminUser + CanViewSecurityEvents

Activities:
- GET /activities/: IsAdminUser + CanViewAuditLogs
- POST /activities/: IsAuthenticated
- PUT/PATCH/DELETE /activities/{id}/: IsAdminUser + CanViewAuditLogs
- GET /activities/summary/: IsAdminUser + CanViewAuditLogs

Health:
- GET /health/: IsAdminUser + CanViewSystemHealth
- POST /health/: IsSystemAdmin
- PUT/PATCH/DELETE /health/{id}/: IsSystemAdmin
- GET /health/overview/: IsAdminUser + CanViewSystemHealth

Metrics:
- GET /metrics/: IsAdminUser + CanViewPerformanceMetrics
- POST /metrics/: IsAuthenticated
- PUT/PATCH/DELETE /metrics/{id}/: IsAdminUser + CanViewPerformanceMetrics
- GET /metrics/aggregate/: IsAdminUser + CanViewPerformanceMetrics
- GET /metrics/overview/: IsAdminUser + CanViewPerformanceMetrics

Anomalies:
- GET /anomalies/: IsAdminUser + CanManageAnomalies
- POST /anomalies/: IsSystemAdmin
- PUT/PATCH/DELETE /anomalies/{id}/: IsAdminUser + CanManageAnomalies
- POST /anomalies/{id}/resolve/, /mark_false_positive/: IsAdminUser + CanManageAnomalies

Statistics:
- GET /stats/audit/, /stats/security/: IsAdminUser + CanViewAuditLogs

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