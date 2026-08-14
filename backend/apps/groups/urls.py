"""
URL configuration for the groups app.

This module defines all URL patterns for group-related endpoints:
- Group management (CRUD, lifecycle, winner selection, statistics)
- Member management (add, remove, promote, demote, transfer ownership)
- Invitation management (send, accept, reject, cancel)
- Settings management (CRUD)
- Activity logs (list, retrieve)
- Winner history (list, retrieve)

All endpoints are versioned under /api/v1/groups/ and include detailed
documentation for each route with HTTP methods, request/response examples,
and permission requirements.

============================================================================
API ENDPOINTS REFERENCE
============================================================================

GROUPS (Base URL: /api/v1/groups/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /groups/                          List groups with filtering
POST    /groups/                          Create a new group
GET     /groups/{id}/                     Retrieve group details
PUT     /groups/{id}/                     Update group (full)
PATCH   /groups/{id}/                     Update group (partial)
DELETE  /groups/{id}/                     Soft delete group
POST    /groups/{id}/join/                Join a group
POST    /groups/{id}/leave/               Leave a group
POST    /groups/{id}/select_winner/       Select winner for current round
POST    /groups/{id}/complete/            Complete the group
POST    /groups/{id}/cancel/              Cancel the group
POST    /groups/{id}/pause/               Pause the group
POST    /groups/{id}/resume/              Resume the group
GET     /groups/{id}/stats/               Get group statistics
GET     /groups/{id}/member_stats/        Get member statistics
GET     /groups/{id}/contribution_summary/Get contribution summary
GET     /groups/{id}/activities/          Get recent activities
GET     /groups/{id}/winners/             Get winner history
GET     /groups/public/                   List public groups
GET     /groups/my_groups/                List groups user is member of
GET     /groups/stats_overview/           Get overview statistics

GROUP MEMBERS (Base URL: /api/v1/groups/{group_id}/members/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /members/                         List members of the group
POST    /members/                         Add a member to the group
GET     /members/{id}/                    Retrieve member details
PUT     /members/{id}/                    Update member (full)
PATCH   /members/{id}/                    Update member (partial)
DELETE  /members/{id}/                    Remove a member
POST    /members/{id}/promote/            Promote member to admin
POST    /members/{id}/demote/             Demote admin to member
POST    /members/{id}/transfer_ownership/ Transfer ownership to member

GROUP INVITATIONS (Base URL: /api/v1/groups/{group_id}/invitations/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /invitations/                     List invitations
POST    /invitations/                     Send an invitation
GET     /invitations/{id}/                Retrieve invitation details
DELETE  /invitations/{id}/                Cancel an invitation
POST    /invitations/{id}/accept/         Accept an invitation
POST    /invitations/{id}/reject/         Reject an invitation
POST    /invitations/{id}/cancel/         Cancel an invitation

GROUP SETTINGS (Base URL: /api/v1/groups/{group_id}/settings/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /settings/                        List settings
POST    /settings/                        Create a setting
GET     /settings/{key}/                  Retrieve a setting
PUT     /settings/{key}/                  Update a setting (full)
PATCH   /settings/{key}/                  Update a setting (partial)
DELETE  /settings/{key}/                  Delete a setting

GROUP ACTIVITIES (Base URL: /api/v1/groups/{group_id}/activities/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /activities/                      List activities
GET     /activities/{id}/                 Retrieve activity details

GROUP WINNER HISTORY (Base URL: /api/v1/groups/{group_id}/winners/)
----------------------------------------------------------------------------
Method  Endpoint                          Description
--------|---------------------------------|-----------------------------------
GET     /winners/                         List winners
GET     /winners/{id}/                    Retrieve winner details

============================================================================
QUERY PARAMETERS
============================================================================

Groups List:
- status: filter by status (active, completed, cancelled, paused, pending, expired)
- type: filter by type (public, private, invite_only)
- search: search by name
- frequency: filter by frequency (daily, weekly, biweekly, monthly, quarterly, yearly)
- min_amount: filter by minimum contribution amount
- max_amount: filter by maximum contribution amount
- date_from: filter by creation date (ISO format)
- date_to: filter by creation date (ISO format)
- ordering: sort field (e.g., -created_at, name)

============================================================================
PERMISSIONS
============================================================================

- Public endpoints (GET /groups/, /groups/public/): AllowAny
- Authenticated endpoints: IsAuthenticated
- Admin endpoints: IsAuthenticated + IsGroupAdmin
- Owner endpoints: IsAuthenticated + IsGroupOwner
- Super admin endpoints: IsAuthenticated + IsSuperAdmin

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

# Create a router for group-related viewsets
router = DefaultRouter()

# Register GroupViewSet with nested routes for members, invitations, settings, activities, winners
router.register(r'groups', views.GroupViewSet, basename='group')

# Note: For nested routes, we need to use custom routing or register separately.
# We'll use explicit paths for nested resources to keep it clear and maintainable.

# ============================================================================
# URL PATTERNS
# ============================================================================

urlpatterns = [
    # ========================================================================
    # GROUP ENDPOINTS (direct)
    # ========================================================================

    # List public groups (no authentication required)
    path('groups/public/', views.GroupViewSet.as_view({'get': 'public'}), name='group-public'),

    # List groups user is a member of (authentication required)
    path('groups/my_groups/', views.GroupViewSet.as_view({'get': 'my_groups'}), name='group-my-groups'),

    # Group stats overview (authentication required)
    path('groups/stats_overview/', views.GroupViewSet.as_view({'get': 'stats_overview'}), name='group-stats-overview'),

    # Full CRUD for groups
    path('groups/', views.GroupViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='group-list'),

    path('groups/<int:id>/', views.GroupViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='group-detail'),

    # Group lifecycle actions
    path('groups/<int:id>/join/', views.GroupViewSet.as_view({'post': 'join'}), name='group-join'),
    path('groups/<int:id>/leave/', views.GroupViewSet.as_view({'post': 'leave'}), name='group-leave'),
    path('groups/<int:id>/select_winner/', views.GroupViewSet.as_view({'post': 'select_winner'}), name='group-select-winner'),
    path('groups/<int:id>/complete/', views.GroupViewSet.as_view({'post': 'complete'}), name='group-complete'),
    path('groups/<int:id>/cancel/', views.GroupViewSet.as_view({'post': 'cancel'}), name='group-cancel'),
    path('groups/<int:id>/pause/', views.GroupViewSet.as_view({'post': 'pause'}), name='group-pause'),
    path('groups/<int:id>/resume/', views.GroupViewSet.as_view({'post': 'resume'}), name='group-resume'),

    # Group statistics
    path('groups/<int:id>/stats/', views.GroupViewSet.as_view({'get': 'stats'}), name='group-stats'),
    path('groups/<int:id>/member_stats/', views.GroupViewSet.as_view({'get': 'member_stats'}), name='group-member-stats'),
    path('groups/<int:id>/contribution_summary/', views.GroupViewSet.as_view({'get': 'contribution_summary'}), name='group-contribution-summary'),

    # Group activities and history
    path('groups/<int:id>/activities/', views.GroupViewSet.as_view({'get': 'activities'}), name='group-activities'),
    path('groups/<int:id>/winners/', views.GroupViewSet.as_view({'get': 'winners'}), name='group-winners'),

    # ========================================================================
    # GROUP MEMBERS (nested under group)
    # ========================================================================

    # List and create members
    path('groups/<int:group_id>/members/', views.GroupMemberViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='group-members-list'),

    # Retrieve, update, delete a member
    path('groups/<int:group_id>/members/<int:id>/', views.GroupMemberViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='group-members-detail'),

    # Member actions: promote, demote, transfer ownership
    path('groups/<int:group_id>/members/<int:id>/promote/', views.GroupMemberViewSet.as_view({'post': 'promote'}), name='group-member-promote'),
    path('groups/<int:group_id>/members/<int:id>/demote/', views.GroupMemberViewSet.as_view({'post': 'demote'}), name='group-member-demote'),
    path('groups/<int:group_id>/members/<int:id>/transfer_ownership/', views.GroupMemberViewSet.as_view({'post': 'transfer_ownership'}), name='group-member-transfer-ownership'),

    # ========================================================================
    # GROUP INVITATIONS (nested under group)
    # ========================================================================

    # List and create invitations
    path('groups/<int:group_id>/invitations/', views.GroupInvitationViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='group-invitations-list'),

    # Retrieve, cancel an invitation
    path('groups/<int:group_id>/invitations/<int:id>/', views.GroupInvitationViewSet.as_view({
        'get': 'retrieve',
        'delete': 'destroy'
    }), name='group-invitations-detail'),

    # Invitation actions: accept, reject, cancel
    path('groups/<int:group_id>/invitations/<int:id>/accept/', views.GroupInvitationViewSet.as_view({'post': 'accept'}), name='group-invitation-accept'),
    path('groups/<int:group_id>/invitations/<int:id>/reject/', views.GroupInvitationViewSet.as_view({'post': 'reject'}), name='group-invitation-reject'),
    path('groups/<int:group_id>/invitations/<int:id>/cancel/', views.GroupInvitationViewSet.as_view({'post': 'cancel'}), name='group-invitation-cancel'),

    # ========================================================================
    # GROUP SETTINGS (nested under group)
    # ========================================================================

    # List and create settings
    path('groups/<int:group_id>/settings/', views.GroupSettingViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='group-settings-list'),

    # Retrieve, update, delete a setting by key
    path('groups/<int:group_id>/settings/<str:key>/', views.GroupSettingViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='group-settings-detail'),

    # ========================================================================
    # GROUP ACTIVITIES (nested under group)
    # ========================================================================

    # List activities
    path('groups/<int:group_id>/activities/', views.GroupActivityViewSet.as_view({
        'get': 'list'
    }), name='group-activities-list'),

    # Retrieve activity details
    path('groups/<int:group_id>/activities/<int:id>/', views.GroupActivityViewSet.as_view({
        'get': 'retrieve'
    }), name='group-activities-detail'),

    # ========================================================================
    # GROUP WINNER HISTORY (nested under group)
    # ========================================================================

    # List winners
    path('groups/<int:group_id>/winners/', views.GroupWinnerHistoryViewSet.as_view({
        'get': 'list'
    }), name='group-winners-list'),

    # Retrieve winner details
    path('groups/<int:group_id>/winners/<int:id>/', views.GroupWinnerHistoryViewSet.as_view({
        'get': 'retrieve'
    }), name='group-winners-detail'),

    # ========================================================================
    # API VERSIONING NOTE
    # ========================================================================

    # All endpoints are versioned under /api/v1/ (the root URL configuration
    # will prefix everything with /api/v1/). Future versions (/api/v2/)
    # should maintain backward compatibility where possible.

    # ========================================================================
    # RATE LIMITING
    # ========================================================================

    # Rate limits are configured in settings.py and applied via DRF throttling.
    # Default: 60 requests per minute for authenticated users.
    # Admin endpoints have higher limits.

    # ========================================================================
    # API DOCUMENTATION
    # ========================================================================

    # Interactive API documentation is available at /api/docs/ (Swagger UI)
    # and /api/redoc/ (ReDoc).

    # ========================================================================
    # ERROR HANDLING
    # ========================================================================

    # All errors are handled by the custom exception handler in
    # apps.common.exceptions.custom_exception_handler.
]

# ============================================================================
# URL PATTERN SUMMARY (for quick reference)
# ============================================================================

"""
SUMMARY OF ALL URL PATTERNS WITH METHODS AND DESCRIPTIONS

------------------------------------------------------------------------------
GROUPS
------------------------------------------------------------------------------
GET    /groups/                                    List groups with filtering
POST   /groups/                                    Create a new group
GET    /groups/{id}/                               Retrieve group details
PUT    /groups/{id}/                               Update group (full)
PATCH  /groups/{id}/                               Update group (partial)
DELETE /groups/{id}/                               Soft delete group
POST   /groups/{id}/join/                          Join the group
POST   /groups/{id}/leave/                         Leave the group
POST   /groups/{id}/select_winner/                 Select winner for current round
POST   /groups/{id}/complete/                      Complete the group
POST   /groups/{id}/cancel/                        Cancel the group
POST   /groups/{id}/pause/                         Pause the group
POST   /groups/{id}/resume/                        Resume the group
GET    /groups/{id}/stats/                         Get group statistics
GET    /groups/{id}/member_stats/                  Get member statistics
GET    /groups/{id}/contribution_summary/          Get contribution summary
GET    /groups/{id}/activities/                    Get recent activities
GET    /groups/{id}/winners/                       Get winner history
GET    /groups/public/                             List public groups (no auth)
GET    /groups/my_groups/                          List groups user belongs to
GET    /groups/stats_overview/                     Get overview statistics

------------------------------------------------------------------------------
GROUP MEMBERS (nested under /groups/{group_id}/members)
------------------------------------------------------------------------------
GET    /members/                                   List members
POST   /members/                                   Add a member
GET    /members/{id}/                              Retrieve member details
PUT    /members/{id}/                              Update member (full)
PATCH  /members/{id}/                              Update member (partial)
DELETE /members/{id}/                              Remove a member
POST   /members/{id}/promote/                      Promote to admin
POST   /members/{id}/demote/                       Demote to member
POST   /members/{id}/transfer_ownership/           Transfer ownership

------------------------------------------------------------------------------
GROUP INVITATIONS (nested under /groups/{group_id}/invitations)
------------------------------------------------------------------------------
GET    /invitations/                               List invitations
POST   /invitations/                               Send an invitation
GET    /invitations/{id}/                          Retrieve invitation details
DELETE /invitations/{id}/                          Cancel an invitation
POST   /invitations/{id}/accept/                   Accept invitation
POST   /invitations/{id}/reject/                   Reject invitation
POST   /invitations/{id}/cancel/                   Cancel invitation

------------------------------------------------------------------------------
GROUP SETTINGS (nested under /groups/{group_id}/settings)
------------------------------------------------------------------------------
GET    /settings/                                  List settings
POST   /settings/                                  Create a setting
GET    /settings/{key}/                            Retrieve a setting
PUT    /settings/{key}/                            Update a setting (full)
PATCH  /settings/{key}/                            Update a setting (partial)
DELETE /settings/{key}/                            Delete a setting

------------------------------------------------------------------------------
GROUP ACTIVITIES (nested under /groups/{group_id}/activities)
------------------------------------------------------------------------------
GET    /activities/                                List activities
GET    /activities/{id}/                           Retrieve activity details

------------------------------------------------------------------------------
GROUP WINNER HISTORY (nested under /groups/{group_id}/winners)
------------------------------------------------------------------------------
GET    /winners/                                   List winners
GET    /winners/{id}/                              Retrieve winner details

============================================================================
PERMISSION MATRIX
============================================================================

Public endpoints: AllowAny
- GET /groups/public/

Authenticated endpoints: IsAuthenticated
- GET /groups/ (list), GET /groups/{id}/
- GET /groups/my_groups/, GET /groups/stats_overview/
- GET /groups/{id}/stats/, /member_stats/, /contribution_summary/
- GET /groups/{id}/activities/, /winners/
- GET /groups/{group_id}/members/
- GET /groups/{group_id}/invitations/
- GET /groups/{group_id}/settings/
- GET /groups/{group_id}/activities/
- GET /groups/{group_id}/winners/

Admin endpoints: IsAuthenticated + IsGroupAdmin
- POST /groups/ (create)
- PUT/PATCH /groups/{id}/, DELETE /groups/{id}/
- POST /groups/{id}/complete/, /cancel/, /pause/, /resume/
- POST /groups/{group_id}/members/ (add member)
- PUT/PATCH/DELETE /groups/{group_id}/members/{id}/
- POST /groups/{group_id}/members/{id}/promote/, /demote/
- POST /groups/{group_id}/invitations/ (send)
- DELETE /groups/{group_id}/invitations/{id}/
- POST /groups/{group_id}/settings/
- PUT/PATCH/DELETE /groups/{group_id}/settings/{key}/

Owner endpoints: IsAuthenticated + IsGroupOwner
- POST /groups/{group_id}/members/{id}/transfer_ownership/

Join/Leave endpoints: IsAuthenticated + ActiveUser
- POST /groups/{id}/join/
- POST /groups/{id}/leave/

Winner selection: IsAuthenticated + ActiveUser
- POST /groups/{id}/select_winner/

Super admin endpoints: IsAuthenticated + IsSuperAdmin
- All actions (bypass all permission checks)

============================================================================
EXAMPLE REQUESTS/RESPONSES
============================================================================

POST /groups/
Request:
{
    "name": "Monthly Savings Group",
    "description": "A group for monthly savings",
    "type": "private",
    "frequency": "monthly",
    "contribution_amount": 1000.00,
    "cycle_length": 12,
    "max_members": 10,
    "winner_selection": "fixed",
    "start_date": "2025-01-01T00:00:00Z"
}
Response:
{
    "success": true,
    "data": {
        "id": 1,
        "name": "Monthly Savings Group",
        ...,
        "members_count": 1,
        "is_active": false,  # Pending until 2 members join
        ...
    },
    "message": "Group created successfully."
}

POST /groups/{id}/select_winner/
Response:
{
    "success": true,
    "data": {
        "winner": 5,
        "winner_name": "John Doe",
        "winner_email": "john@example.com",
        "amount": 10000.00,
        "round": 1
    },
    "message": "Winner selected for round 2."
}

============================================================================
FILTERING AND SEARCHING
============================================================================

GET /groups/?status=active&type=public&search=monthly&frequency=monthly&min_amount=500&max_amount=2000&ordering=-created_at
Returns groups matching the criteria, sorted by creation date descending.

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