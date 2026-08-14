"""
URL configuration for the payments app.

This module defines all URL patterns for payment-related endpoints:
- Payment management (CRUD, actions: complete, fail, cancel, refund, retry, expire, reverse)
- Payout management (CRUD, actions: complete, fail, cancel, put_on_hold)
- Payment transactions (list, retrieve)
- Gateway logs (list, retrieve)
- Webhooks (receive and process)
- Reconciliation (CRUD, match)
- Disputes (CRUD, resolve, reject)
- Settlements (CRUD)
- Payment methods (CRUD)
- Audit logs (list, retrieve)
- Statistics (payment stats, payout stats)

All endpoints are versioned under /api/v1/ and include detailed
documentation for each route with HTTP methods, request/response examples,
and permission requirements.

============================================================================
API ENDPOINTS REFERENCE
============================================================================

PAYMENTS (Base URL: /api/v1/payments/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /payments/                        List payments with filtering
POST    /payments/                        Create a new payment
GET     /payments/{id}/                   Retrieve payment details
PUT     /payments/{id}/                   Update payment (full)
PATCH   /payments/{id}/                   Update payment (partial)
DELETE  /payments/{id}/                   Soft delete payment
POST    /payments/{id}/complete/          Complete a pending payment
POST    /payments/{id}/fail/              Mark payment as failed
POST    /payments/{id}/cancel/            Cancel a payment
POST    /payments/{id}/refund/            Refund a completed payment
POST    /payments/{id}/retry/             Retry a failed payment
POST    /payments/{id}/expire/            Expire a pending payment
POST    /payments/{id}/reverse/           Reverse a payment
GET     /payments/{id}/transactions/      Get transactions for payment
GET     /payments/{id}/gateway_logs/      Get gateway logs for payment
GET     /payments/{id}/reconciliations/   Get reconciliations for payment
GET     /payments/{id}/disputes/          Get disputes for payment
GET     /payments/{id}/stats/             Get statistics for payment
GET     /payments/my_payments/            Get current user's payments
GET     /payments/stats_overview/         Overview payment statistics (admin)

PAYOUTS (Base URL: /api/v1/payouts/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /payouts/                         List payouts with filtering
POST    /payouts/                         Create a new payout
GET     /payouts/{id}/                    Retrieve payout details
PUT     /payouts/{id}/                    Update payout (full)
PATCH   /payouts/{id}/                    Update payout (partial)
DELETE  /payouts/{id}/                    Soft delete payout
POST    /payouts/{id}/complete/           Complete a pending payout
POST    /payouts/{id}/fail/               Mark payout as failed
POST    /payouts/{id}/cancel/             Cancel a payout
POST    /payouts/{id}/put_on_hold/        Put payout on hold
GET     /payouts/my_payouts/              Get current user's payouts
GET     /payouts/stats_overview/          Overview payout statistics (admin)

PAYMENT TRANSACTIONS (Base URL: /api/v1/transactions/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /transactions/                    List payment transactions
GET     /transactions/{id}/               Retrieve transaction details

PAYMENT GATEWAY LOGS (Base URL: /api/v1/gateway_logs/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /gateway_logs/                    List gateway logs
GET     /gateway_logs/{id}/               Retrieve gateway log details

WEBHOOKS (Base URL: /api/v1/webhooks/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
POST    /webhooks/{gateway}/              Receive webhook from gateway

PAYMENT RECONCILIATIONS (Base URL: /api/v1/reconciliations/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /reconciliations/                 List reconciliations
POST    /reconciliations/                 Create a reconciliation
GET     /reconciliations/{id}/            Retrieve reconciliation details
PUT     /reconciliations/{id}/            Update reconciliation (full)
PATCH   /reconciliations/{id}/            Update reconciliation (partial)
DELETE  /reconciliations/{id}/            Delete reconciliation
POST    /reconciliations/{id}/match/      Mark reconciliation as matched

PAYMENT DISPUTES (Base URL: /api/v1/disputes/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /disputes/                        List disputes
POST    /disputes/                        Create a dispute
GET     /disputes/{id}/                   Retrieve dispute details
PUT     /disputes/{id}/                   Update dispute (full)
PATCH   /disputes/{id}/                   Update dispute (partial)
DELETE  /disputes/{id}/                   Delete dispute
POST    /disputes/{id}/resolve/           Resolve a dispute
POST    /disputes/{id}/reject/            Reject a dispute

SETTLEMENTS (Base URL: /api/v1/settlements/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /settlements/                     List settlements
POST    /settlements/                     Create a settlement
GET     /settlements/{id}/                Retrieve settlement details
PUT     /settlements/{id}/                Update settlement (full)
PATCH   /settlements/{id}/                Update settlement (partial)
DELETE  /settlements/{id}/                Delete settlement

PAYMENT METHODS (Base URL: /api/v1/payment_methods/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /payment_methods/                 List payment methods
POST    /payment_methods/                 Create a payment method
GET     /payment_methods/{id}/            Retrieve payment method details
PUT     /payment_methods/{id}/            Update payment method (full)
PATCH   /payment_methods/{id}/            Update payment method (partial)
DELETE  /payment_methods/{id}/            Delete payment method

PAYMENT AUDITS (Base URL: /api/v1/payment_audits/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /payment_audits/                  List payment audits
GET     /payment_audits/{id}/             Retrieve audit details

PAYMENT STATISTICS (Base URL: /api/v1/payment_stats/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /payment_stats/                   Get payment statistics (admin)

PAYOUT STATISTICS (Base URL: /api/v1/payout_stats/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /payout_stats/                    Get payout statistics (admin)

============================================================================
QUERY PARAMETERS
============================================================================

Payments List:
- group_id: filter by group ID
- user_id: filter by user ID
- status: filter by status (pending, processing, completed, failed, cancelled, refunded, expired, reversed)
- payment_method: filter by payment method (telebirr, chapa, bank_transfer, cash, mobile_money, card)
- date_from: filter by created_at (ISO format)
- date_to: filter by created_at (ISO format)
- search: search in reference, user email, user name
- ordering: sort field (e.g., -created_at, amount)

Payouts List:
- group_id: filter by group ID
- user_id: filter by user ID
- status: filter by status (pending, processing, completed, failed, cancelled, partially_paid, on_hold)
- search: search in reference, user email
- ordering: sort field (e.g., -created_at)

Transactions List:
- payment_id: filter by payment ID
- ordering: sort field (e.g., -created_at)

Gateway Logs List:
- payment_id: filter by payment ID
- ordering: sort field (e.g., -created_at)

Reconciliations List:
- payment_id: filter by payment ID
- status: filter by status (pending, matched, failed, discrepancy)
- ordering: sort field (e.g., -reconciled_at)

Disputes List:
- payment_id: filter by payment ID
- status: filter by status (pending, investigating, resolved, rejected)
- ordering: sort field (e.g., -created_at)

============================================================================
PERMISSIONS
============================================================================

Public endpoints: None (all require authentication)
Authenticated endpoints: IsAuthenticated
User-specific: Users see only their own payments and groups they are members of
Admin endpoints: IsSuperAdminUser

Payment Actions:
- create: CanCreatePayment (user is member of group)
- update/delete: CanUpdatePayment / CanDeletePayment (owner or group admin)
- complete/fail/cancel/refund/retry/expire/reverse: CanProcessPayment (group admin)

Payout Actions:
- create: CanCreatePayout (group admin or superuser)
- update/delete: CanUpdatePayout / CanDeletePayout (owner or group admin)
- complete/fail/cancel/put_on_hold: CanProcessPayout (group admin)

============================================================================
EXAMPLE REQUESTS/RESPONSES
============================================================================

POST /api/v1/payments/
Request:
{
    "user": 5,
    "group": 3,
    "amount": 1000.00,
    "payment_method": "telebirr",
    "gateway": "chapa",
    "contribution": 10
}
Response:
{
    "success": true,
    "data": {
        "id": 1,
        "reference": "PAY-20250101120000-ABC12345",
        "amount": 1000.00,
        "status": "pending",
        ...
    },
    "message": "Payment created successfully."
}

POST /api/v1/payments/{id}/complete/
Request:
{
    "reference": "TXN-123456"
}
Response:
{
    "success": true,
    "message": "Payment completed.",
    "payment": {...}
}

POST /api/v1/webhooks/chapa/
Request body: raw JSON payload
Response:
{
    "status": "accepted"
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
router.register(r'payments', views.PaymentViewSet, basename='payment')
router.register(r'payouts', views.PayoutViewSet, basename='payout')
router.register(r'transactions', views.PaymentTransactionViewSet, basename='transaction')
router.register(r'gateway_logs', views.PaymentGatewayLogViewSet, basename='gatewaylog')
router.register(r'reconciliations', views.PaymentReconciliationViewSet, basename='reconciliation')
router.register(r'disputes', views.PaymentDisputeViewSet, basename='dispute')
router.register(r'settlements', views.SettlementViewSet, basename='settlement')
router.register(r'payment_methods', views.PaymentMethodViewSet, basename='paymentmethod')
router.register(r'payment_audits', views.PaymentAuditViewSet, basename='paymentaudit')

# ============================================================================
# URL PATTERNS
# ============================================================================

urlpatterns = [
    # Router URLs
    path('', include(router.urls)),

    # Webhook endpoint (no authentication)
    path('webhooks/<str:gateway>/', views.PaymentWebhookView.as_view(), name='webhook'),

    # Statistics endpoints (admin only)
    path('payment_stats/', views.PaymentStatisticsView.as_view(), name='payment-stats'),
    path('payout_stats/', views.PayoutStatisticsView.as_view(), name='payout-stats'),
]

# ============================================================================
# URL PATTERN SUMMARY (for quick reference)
# ============================================================================

"""
SUMMARY OF ALL URL PATTERNS WITH METHODS AND DESCRIPTIONS

------------------------------------------------------------------------------
PAYMENTS
------------------------------------------------------------------------------
GET    /payments/                                     List payments with filtering
POST   /payments/                                     Create a new payment
GET    /payments/{id}/                                Retrieve payment details
PUT    /payments/{id}/                                Update payment (full)
PATCH  /payments/{id}/                                Update payment (partial)
DELETE /payments/{id}/                                Soft delete payment
POST   /payments/{id}/complete/                       Complete a pending payment
POST   /payments/{id}/fail/                           Mark payment as failed
POST   /payments/{id}/cancel/                         Cancel a payment
POST   /payments/{id}/refund/                         Refund a completed payment
POST   /payments/{id}/retry/                          Retry a failed payment
POST   /payments/{id}/expire/                         Expire a pending payment
POST   /payments/{id}/reverse/                        Reverse a payment
GET    /payments/{id}/transactions/                   Get transactions for payment
GET    /payments/{id}/gateway_logs/                   Get gateway logs for payment
GET    /payments/{id}/reconciliations/                Get reconciliations for payment
GET    /payments/{id}/disputes/                       Get disputes for payment
GET    /payments/{id}/stats/                          Get statistics for payment
GET    /payments/my_payments/                         Get current user's payments
GET    /payments/stats_overview/                      Overview payment statistics (admin)

------------------------------------------------------------------------------
PAYOUTS
------------------------------------------------------------------------------
GET    /payouts/                                      List payouts with filtering
POST   /payouts/                                      Create a new payout
GET    /payouts/{id}/                                 Retrieve payout details
PUT    /payouts/{id}/                                 Update payout (full)
PATCH  /payouts/{id}/                                 Update payout (partial)
DELETE /payouts/{id}/                                 Soft delete payout
POST   /payouts/{id}/complete/                        Complete a pending payout
POST   /payouts/{id}/fail/                            Mark payout as failed
POST   /payouts/{id}/cancel/                          Cancel a payout
POST   /payouts/{id}/put_on_hold/                     Put payout on hold
GET    /payouts/my_payouts/                           Get current user's payouts
GET    /payouts/stats_overview/                       Overview payout statistics (admin)

------------------------------------------------------------------------------
PAYMENT TRANSACTIONS
------------------------------------------------------------------------------
GET    /transactions/                                 List payment transactions
GET    /transactions/{id}/                            Retrieve transaction details

------------------------------------------------------------------------------
PAYMENT GATEWAY LOGS
------------------------------------------------------------------------------
GET    /gateway_logs/                                 List gateway logs
GET    /gateway_logs/{id}/                            Retrieve gateway log details

------------------------------------------------------------------------------
WEBHOOKS
------------------------------------------------------------------------------
POST   /webhooks/{gateway}/                           Receive webhook from gateway

------------------------------------------------------------------------------
PAYMENT RECONCILIATIONS
------------------------------------------------------------------------------
GET    /reconciliations/                              List reconciliations
POST   /reconciliations/                              Create a reconciliation
GET    /reconciliations/{id}/                         Retrieve reconciliation details
PUT    /reconciliations/{id}/                         Update reconciliation (full)
PATCH  /reconciliations/{id}/                         Update reconciliation (partial)
DELETE /reconciliations/{id}/                         Delete reconciliation
POST   /reconciliations/{id}/match/                   Mark reconciliation as matched

------------------------------------------------------------------------------
PAYMENT DISPUTES
------------------------------------------------------------------------------
GET    /disputes/                                     List disputes
POST   /disputes/                                     Create a dispute
GET    /disputes/{id}/                                Retrieve dispute details
PUT    /disputes/{id}/                                Update dispute (full)
PATCH  /disputes/{id}/                                Update dispute (partial)
DELETE /disputes/{id}/                                Delete dispute
POST   /disputes/{id}/resolve/                        Resolve a dispute
POST   /disputes/{id}/reject/                         Reject a dispute

------------------------------------------------------------------------------
SETTLEMENTS
------------------------------------------------------------------------------
GET    /settlements/                                  List settlements
POST   /settlements/                                  Create a settlement
GET    /settlements/{id}/                             Retrieve settlement details
PUT    /settlements/{id}/                             Update settlement (full)
PATCH  /settlements/{id}/                             Update settlement (partial)
DELETE /settlements/{id}/                             Delete settlement

------------------------------------------------------------------------------
PAYMENT METHODS
------------------------------------------------------------------------------
GET    /payment_methods/                              List payment methods
POST   /payment_methods/                              Create a payment method
GET    /payment_methods/{id}/                         Retrieve payment method details
PUT    /payment_methods/{id}/                         Update payment method (full)
PATCH  /payment_methods/{id}/                         Update payment method (partial)
DELETE /payment_methods/{id}/                         Delete payment method

------------------------------------------------------------------------------
PAYMENT AUDITS
------------------------------------------------------------------------------
GET    /payment_audits/                               List payment audits
GET    /payment_audits/{id}/                          Retrieve audit details

------------------------------------------------------------------------------
PAYMENT STATISTICS
------------------------------------------------------------------------------
GET    /payment_stats/                                Get payment statistics (admin)

------------------------------------------------------------------------------
PAYOUT STATISTICS
------------------------------------------------------------------------------
GET    /payout_stats/                                 Get payout statistics (admin)

============================================================================
PERMISSION MATRIX
============================================================================

Authenticated endpoints: IsAuthenticated
- GET /payments/, GET /payments/{id}/
- GET /payments/my_payments/
- GET /payments/{id}/transactions/, /gateway_logs/, /reconciliations/, /disputes/
- GET /payments/{id}/stats/
- GET /payouts/, GET /payouts/{id}/
- GET /payouts/my_payouts/
- GET /transactions/, GET /transactions/{id}/
- GET /gateway_logs/, GET /gateway_logs/{id}/
- GET /reconciliations/, GET /reconciliations/{id}/
- GET /disputes/, GET /disputes/{id}/
- GET /payment_methods/, GET /payment_methods/{id}/
- GET /payment_audits/, GET /payment_audits/{id}/

User-specific actions: IsAuthenticated + CanCreatePayment / CanUpdatePayment / CanDeletePayment
- POST /payments/ (create)
- PUT/PATCH /payments/{id}/, DELETE /payments/{id}/

Admin/Group admin actions: IsAuthenticated + CanProcessPayment
- POST /payments/{id}/complete/, /fail/, /cancel/, /refund/, /retry/, /expire/, /reverse/

Payout actions: IsAuthenticated + CanCreatePayout / CanProcessPayout
- POST /payouts/ (create)
- PUT/PATCH /payouts/{id}/, DELETE /payouts/{id}/
- POST /payouts/{id}/complete/, /fail/, /cancel/, /put_on_hold/

Admin endpoints: IsAuthenticated + IsSuperAdminUser
- GET /payments/stats_overview/
- GET /payouts/stats_overview/
- GET /payment_stats/
- GET /payout_stats/
- POST /settlements/, PUT/PATCH /settlements/{id}/, DELETE /settlements/{id}/
- POST /reconciliations/, PUT/PATCH /reconciliations/{id}/, DELETE /reconciliations/{id}/
- POST /disputes/{id}/resolve/, /reject/

Public endpoints: AllowAny
- POST /webhooks/{gateway}/ (no authentication)

============================================================================
FILTERING AND SEARCHING
============================================================================

GET /payments/?group_id=3&status=completed&date_from=2025-01-01&ordering=-amount
Returns completed payments for group 3, sorted by amount descending.

GET /payouts/?user_id=5&status=pending
Returns pending payouts for user 5.

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