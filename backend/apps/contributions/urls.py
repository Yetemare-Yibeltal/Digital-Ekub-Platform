"""
URL configuration for the contributions app.

This module defines all URL patterns for contribution-related endpoints:
- Contribution management (CRUD, status updates, payment processing)
- Payment management (list, create, refund, complete, fail)
- Reminder management (list, retrieve, send)
- Audit log viewing (list, retrieve)
- Statistics and reporting (summary, stats, group_summary)
- Bulk operations (bulk_create, bulk_update_status)
- Admin actions (stats_overview)

All endpoints are versioned under /api/v1/contributions/ and include detailed
documentation for each route with HTTP methods, request/response examples,
and permission requirements.

============================================================================
API ENDPOINTS REFERENCE
============================================================================

CONTRIBUTIONS (Base URL: /api/v1/contributions/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /contributions/                   List contributions with filtering
POST    /contributions/                   Create a new contribution
GET     /contributions/{id}/              Retrieve contribution details
PUT     /contributions/{id}/              Update contribution (full)
PATCH   /contributions/{id}/              Update contribution (partial)
DELETE  /contributions/{id}/              Soft delete contribution
POST    /contributions/{id}/mark_paid/    Mark contribution as paid
POST    /contributions/{id}/mark_overdue/ Mark contribution as overdue
POST    /contributions/{id}/cancel/       Cancel contribution
POST    /contributions/{id}/refund/       Refund contribution
POST    /contributions/{id}/waive/        Waive part or all of contribution
POST    /contributions/{id}/send_reminder/Send reminder
GET     /contributions/{id}/reminders/    Get all reminders
GET     /contributions/{id}/audit_trail/  Get audit trail
GET     /contributions/{id}/payment_detail/Get payment details
GET     /contributions/{id}/stats/        Get contribution statistics
GET     /contributions/my_contributions/  Get user's contributions
GET     /contributions/pending/           Get pending contributions
GET     /contributions/overdue/           Get overdue contributions
GET     /contributions/summary/           Get summary statistics
GET     /contributions/group_summary/     Get group contribution summary
POST    /contributions/bulk_create/       Bulk create contributions (admin)
POST    /contributions/bulk_update_status/Bulk update status (admin)
GET     /contributions/stats_overview/    Overview statistics (admin)

CONTRIBUTION PAYMENTS (Base URL: /api/v1/contributions/payments/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /payments/                        List payments
POST    /payments/                        Create a payment
GET     /payments/{id}/                   Retrieve payment details
PUT     /payments/{id}/                   Update payment (full)
PATCH   /payments/{id}/                   Update payment (partial)
DELETE  /payments/{id}/                   Delete payment
POST    /payments/{id}/refund_payment/    Refund payment
POST    /payments/{id}/mark_completed/    Mark payment as completed
POST    /payments/{id}/mark_failed/       Mark payment as failed

CONTRIBUTION REMINDERS (Base URL: /api/v1/contributions/reminders/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /reminders/                       List reminders
GET     /reminders/{id}/                  Retrieve reminder details

CONTRIBUTION AUDITS (Base URL: /api/v1/contributions/audits/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /audits/                          List audit entries
GET     /audits/{id}/                     Retrieve audit details

============================================================================
QUERY PARAMETERS
============================================================================

Contributions List:
- group_id: filter by group ID
- user_id: filter by user ID
- status: filter by status (pending, paid, overdue, cancelled, refunded, waived, partially_paid)
- type: filter by contribution type (regular, special, penalty, bonus, advance)
- date_from: filter by due date (ISO format)
- date_to: filter by due date (ISO format)
- round: filter by round number
- search: search in reference, notes, user email, group name
- ordering: sort field (e.g., -due_date, amount)

Payments List:
- contribution_id: filter by contribution ID
- user_id: filter by user ID
- status: filter by status (pending, completed, failed, refunded)
- ordering: sort field (e.g., -paid_at)

Reminders List:
- contribution_id: filter by contribution ID
- ordering: sort field (e.g., -sent_at)

Audits List:
- contribution_id: filter by contribution ID
- action: filter by action
- ordering: sort field (e.g., -timestamp)

============================================================================
PERMISSIONS
============================================================================

- Public endpoints: None (all require authentication)
- Authenticated endpoints: IsAuthenticated
- User-specific: Users see only their own contributions and group memberships
- Admin endpoints: IsAuthenticated + CanProcessContribution
- Super admin endpoints: IsAuthenticated + IsSuperAdminUser

============================================================================
EXAMPLE REQUESTS/RESPONSES
============================================================================

POST /api/v1/contributions/
Request:
{
    "user": 5,
    "group": 3,
    "amount": 1000.00,
    "round": 2,
    "due_date": "2025-03-15T00:00:00Z"
}
Response:
{
    "success": true,
    "data": {
        "id": 1,
        "amount": 1000.00,
        "status": "pending",
        ...
    },
    "message": "Contribution created successfully."
}

POST /api/v1/contributions/{id}/mark_paid/
Request:
{
    "payment_method": "telebirr",
    "reference": "TXN-123456"
}
Response:
{
    "success": true,
    "message": "Contribution marked as paid successfully.",
    "contribution": {...}
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
router.register(r'contributions', views.ContributionViewSet, basename='contribution')
router.register(r'payments', views.ContributionPaymentViewSet, basename='payment')
router.register(r'reminders', views.ContributionReminderViewSet, basename='reminder')
router.register(r'audits', views.ContributionAuditViewSet, basename='audit')

# ============================================================================
# URL PATTERNS
# ============================================================================

urlpatterns = [
    path('', include(router.urls)),
]

# ============================================================================
# URL PATTERN SUMMARY (for quick reference)
# ============================================================================

"""
SUMMARY OF ALL URL PATTERNS WITH METHODS AND DESCRIPTIONS

------------------------------------------------------------------------------
CONTRIBUTIONS
------------------------------------------------------------------------------
GET    /contributions/                                    List contributions with filtering
POST   /contributions/                                    Create a new contribution
GET    /contributions/{id}/                               Retrieve contribution details
PUT    /contributions/{id}/                               Update contribution (full)
PATCH  /contributions/{id}/                               Update contribution (partial)
DELETE /contributions/{id}/                               Soft delete contribution
POST   /contributions/{id}/mark_paid/                     Mark contribution as paid
POST   /contributions/{id}/mark_overdue/                  Mark contribution as overdue
POST   /contributions/{id}/cancel/                        Cancel contribution
POST   /contributions/{id}/refund/                        Refund contribution
POST   /contributions/{id}/waive/                         Waive part or all of contribution
POST   /contributions/{id}/send_reminder/                 Send reminder
GET    /contributions/{id}/reminders/                     Get all reminders
GET    /contributions/{id}/audit_trail/                   Get audit trail
GET    /contributions/{id}/payment_detail/                Get payment details
GET    /contributions/{id}/stats/                         Get contribution statistics
GET    /contributions/my_contributions/                   Get user's contributions
GET    /contributions/pending/                            Get pending contributions
GET    /contributions/overdue/                            Get overdue contributions
GET    /contributions/summary/                            Get summary statistics
GET    /contributions/group_summary/                      Get group contribution summary
POST   /contributions/bulk_create/                        Bulk create contributions (admin)
POST   /contributions/bulk_update_status/                 Bulk update status (admin)
GET    /contributions/stats_overview/                     Overview statistics (admin)

------------------------------------------------------------------------------
CONTRIBUTION PAYMENTS
------------------------------------------------------------------------------
GET    /payments/                                         List payments
POST   /payments/                                         Create a payment
GET    /payments/{id}/                                    Retrieve payment details
PUT    /payments/{id}/                                    Update payment (full)
PATCH  /payments/{id}/                                    Update payment (partial)
DELETE /payments/{id}/                                    Delete payment
POST   /payments/{id}/refund_payment/                     Refund payment
POST   /payments/{id}/mark_completed/                     Mark payment as completed
POST   /payments/{id}/mark_failed/                        Mark payment as failed

------------------------------------------------------------------------------
CONTRIBUTION REMINDERS
------------------------------------------------------------------------------
GET    /reminders/                                        List reminders
GET    /reminders/{id}/                                   Retrieve reminder details

------------------------------------------------------------------------------
CONTRIBUTION AUDITS
------------------------------------------------------------------------------
GET    /audits/                                           List audit entries
GET    /audits/{id}/                                      Retrieve audit details

============================================================================
PERMISSION MATRIX
============================================================================

Authenticated endpoints: IsAuthenticated
- GET /contributions/, GET /contributions/{id}/
- GET /contributions/my_contributions/
- GET /contributions/pending/, GET /contributions/overdue/
- GET /contributions/summary/, GET /contributions/group_summary/
- GET /contributions/{id}/stats/
- GET /contributions/{id}/reminders/
- GET /contributions/{id}/audit_trail/
- GET /contributions/{id}/payment_detail/
- POST /contributions/{id}/send_reminder/
- GET /payments/, GET /payments/{id}/
- GET /reminders/, GET /reminders/{id}/
- GET /audits/, GET /audits/{id}/

User-specific actions: IsAuthenticated + CanProcessContribution
- POST /contributions/ (create)
- PUT/PATCH /contributions/{id}/, DELETE /contributions/{id}/
- POST /contributions/{id}/mark_paid/
- POST /contributions/{id}/mark_overdue/
- POST /contributions/{id}/cancel/
- POST /contributions/{id}/refund/
- POST /contributions/{id}/waive/
- POST /payments/ (create)
- PUT/PATCH/DELETE /payments/{id}/
- POST /payments/{id}/refund_payment/
- POST /payments/{id}/mark_completed/
- POST /payments/{id}/mark_failed/

Admin endpoints: IsAuthenticated + IsSuperAdminUser
- POST /contributions/bulk_create/
- POST /contributions/bulk_update_status/
- GET /contributions/stats_overview/

============================================================================
FILTERING AND SEARCHING
============================================================================

GET /contributions/?group_id=3&status=pending&date_from=2025-01-01&ordering=-due_date
Returns pending contributions for group 3, sorted by due date descending.

GET /payments/?contribution_id=5&status=completed
Returns completed payments for contribution 5.

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