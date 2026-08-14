"""
Custom pagination classes for the Digital Ekub Platform.

This module provides flexible pagination classes with standardized response formats,
support for cursor-based pagination, page-based pagination with metadata,
and utility functions for building paginated responses.
"""

from rest_framework import pagination
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination, CursorPagination, LimitOffsetPagination
from django.core.paginator import InvalidPage
from django.utils.translation import gettext_lazy as _
from collections import OrderedDict
import math
from typing import Dict, Any, Optional, List, Callable, Type
from functools import wraps
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# STANDARD PAGE PAGINATION
# ============================================================================

class StandardPagination(PageNumberPagination):
    """
    Standard page-based pagination with comprehensive metadata.

    Query parameters:
    - page: Page number (default: 1)
    - page_size: Number of items per page (default: 20, max: 100)

    Response format:
    {
        "count": 100,
        "total_pages": 5,
        "current_page": 1,
        "page_size": 20,
        "has_next": true,
        "has_previous": false,
        "next": "http://api.example.com/endpoint/?page=2",
        "previous": null,
        "results": [...]
    }
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'

    def get_paginated_response(self, data):
        """
        Return paginated response with detailed metadata.
        """
        total_pages = math.ceil(self.page.paginator.count / self.page_size)

        return Response(OrderedDict([
            ('count', self.page.paginator.count),
            ('total_pages', total_pages),
            ('current_page', self.page.number),
            ('page_size', self.page_size),
            ('has_next', self.page.has_next()),
            ('has_previous', self.page.has_previous()),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ]))

    def get_paginated_response_schema(self, schema):
        """
        Return schema for OpenAPI documentation.
        """
        return {
            'type': 'object',
            'properties': {
                'count': {'type': 'integer', 'example': 100},
                'total_pages': {'type': 'integer', 'example': 5},
                'current_page': {'type': 'integer', 'example': 1},
                'page_size': {'type': 'integer', 'example': 20},
                'has_next': {'type': 'boolean', 'example': True},
                'has_previous': {'type': 'boolean', 'example': False},
                'next': {'type': 'string', 'nullable': True, 'example': 'http://api.example.com/endpoint/?page=2'},
                'previous': {'type': 'string', 'nullable': True, 'example': None},
                'results': schema,
            }
        }


# ============================================================================
# LARGE PAGINATION (FOR LARGE DATASETS)
# ============================================================================

class LargePagination(StandardPagination):
    """
    Pagination for large datasets with larger page size and max limit.

    Query parameters:
    - page: Page number (default: 1)
    - page_size: Number of items per page (default: 50, max: 500)

    Response format: Same as StandardPagination but with larger limits.
    """
    page_size = 50
    max_page_size = 500
    page_size_query_param = 'page_size'


# ============================================================================
# SMALL PAGINATION (FOR SMALL DATASETS)
# ============================================================================

class SmallPagination(StandardPagination):
    """
    Pagination for small datasets with smaller page size.

    Query parameters:
    - page: Page number (default: 1)
    - page_size: Number of items per page (default: 5, max: 20)

    Response format: Same as StandardPagination but with smaller limits.
    """
    page_size = 5
    max_page_size = 20
    page_size_query_param = 'page_size'


# ============================================================================
# ADMIN PAGINATION (FOR ADMIN PANEL)
# ============================================================================

class AdminPagination(StandardPagination):
    """
    Pagination for admin panel with larger limits and additional metadata.

    Query parameters:
    - page: Page number (default: 1)
    - page_size: Number of items per page (default: 50, max: 200)

    Response format: Same as StandardPagination with additional admin metadata.
    """
    page_size = 50
    max_page_size = 200
    page_size_query_param = 'page_size'

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        # Add admin-specific metadata
        response.data['start_index'] = (self.page.number - 1) * self.page_size + 1
        response.data['end_index'] = min(self.page.number * self.page_size, self.page.paginator.count)
        response.data['count_display'] = f"{response.data['start_index']} - {response.data['end_index']} of {self.page.paginator.count}"
        return response


# ============================================================================
# MOBILE PAGINATION (FOR MOBILE APPS)
# ============================================================================

class MobilePagination(StandardPagination):
    """
    Pagination optimized for mobile applications with smaller page sizes.

    Query parameters:
    - page: Page number (default: 1)
    - page_size: Number of items per page (default: 10, max: 30)

    Response format: Same as StandardPagination but optimized for mobile.
    """
    page_size = 10
    max_page_size = 30
    page_size_query_param = 'page_size'


# ============================================================================
# CURSOR PAGINATION (FOR INFINITE SCROLLING)
# ============================================================================

class CursorBasedPagination(CursorPagination):
    """
    Cursor-based pagination for infinite scrolling and real-time feeds.

    Query parameters:
    - cursor: Encoded cursor for pagination (default: None)

    Response format:
    {
        "next": "http://api.example.com/endpoint/?cursor=abc123",
        "previous": "http://api.example.com/endpoint/?cursor=def456",
        "results": [...]
    }
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    cursor_query_param = 'cursor'
    ordering = '-created_at'  # Default ordering

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('page_size', self.page_size),
            ('results', data)
        ]))


class CustomCursorPagination(CursorBasedPagination):
    """
    Customizable cursor pagination with dynamic ordering.

    Supports ordering by fields and provides additional metadata.
    """
    def __init__(self, ordering: Optional[str] = None, page_size: int = 20):
        self.ordering = ordering or '-created_at'
        self.page_size = page_size
        super().__init__()


# ============================================================================
# LIMIT-OFFSET PAGINATION (LEGACY SUPPORT)
# ============================================================================

class LegacyPagination(LimitOffsetPagination):
    """
    Limit-offset pagination for legacy API compatibility.

    Query parameters:
    - limit: Number of items to return (default: 20, max: 100)
    - offset: Number of items to skip (default: 0)

    Response format:
    {
        "count": 100,
        "limit": 20,
        "offset": 0,
        "next": "http://api.example.com/endpoint/?limit=20&offset=20",
        "previous": null,
        "results": [...]
    }
    """
    default_limit = 20
    max_limit = 100
    limit_query_param = 'limit'
    offset_query_param = 'offset'

    def get_paginated_response(self, data):
        return Response(OrderedDict([
            ('count', self.count),
            ('limit', self.limit),
            ('offset', self.offset),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ]))


# ============================================================================
# CUSTOM PAGINATION (ADAPTABLE)
# ============================================================================

class CustomPagination(StandardPagination):
    """
    Fully customizable pagination with dynamic page size and additional metadata.

    Query parameters:
    - page: Page number (default: 1)
    - page_size: Number of items per page (default: 20, min: 1, max: 150)

    Response format: Includes count, total_pages, current_page, page_size,
    has_next, has_previous, next, previous, results, start_index, end_index.
    """
    page_size = 20
    min_page_size = 1
    max_page_size = 150
    page_size_query_param = 'page_size'
    page_query_param = 'page'

    def get_page_size(self, request):
        """
        Get page size from request with validation.
        """
        try:
            page_size = int(request.query_params.get(self.page_size_query_param, self.page_size))
        except ValueError:
            page_size = self.page_size

        # Validate page size
        page_size = max(self.min_page_size, min(page_size, self.max_page_size))
        return page_size

    def paginate_queryset(self, queryset, request, view=None):
        """
        Override to handle invalid page numbers gracefully.
        """
        try:
            return super().paginate_queryset(queryset, request, view)
        except InvalidPage as e:
            raise NotFound(_('Invalid page. The page number is out of range.'))

    def get_paginated_response(self, data):
        """
        Return paginated response with comprehensive metadata.
        """
        total_pages = math.ceil(self.page.paginator.count / self.page_size)
        start_index = (self.page.number - 1) * self.page_size + 1
        end_index = min(self.page.number * self.page_size, self.page.paginator.count)

        return Response(OrderedDict([
            ('count', self.page.paginator.count),
            ('total_pages', total_pages),
            ('current_page', self.page.number),
            ('page_size', self.page_size),
            ('has_next', self.page.has_next()),
            ('has_previous', self.page.has_previous()),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('start_index', start_index),
            ('end_index', end_index),
            ('results', data)
        ]))

    def get_paginated_response_schema(self, schema):
        """
        Return schema for OpenAPI documentation.
        """
        return {
            'type': 'object',
            'properties': {
                'count': {'type': 'integer', 'example': 100},
                'total_pages': {'type': 'integer', 'example': 5},
                'current_page': {'type': 'integer', 'example': 1},
                'page_size': {'type': 'integer', 'example': 20},
                'has_next': {'type': 'boolean', 'example': True},
                'has_previous': {'type': 'boolean', 'example': False},
                'next': {'type': 'string', 'nullable': True, 'example': 'http://api.example.com/endpoint/?page=2'},
                'previous': {'type': 'string', 'nullable': True, 'example': None},
                'start_index': {'type': 'integer', 'example': 1},
                'end_index': {'type': 'integer', 'example': 20},
                'results': schema,
            }
        }


# ============================================================================
# PAGINATION UTILITY FUNCTIONS
# ============================================================================

def build_paginated_response(
    data: List[Any],
    total_count: int,
    page: int,
    page_size: int,
    base_url: str,
    query_params: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Build a paginated response dictionary manually.

    Args:
        data: List of items for current page
        total_count: Total number of items
        page: Current page number
        page_size: Number of items per page
        base_url: Base URL for generating links
        query_params: Additional query parameters to include in links

    Returns:
        Dict containing paginated response metadata and data
    """
    total_pages = math.ceil(total_count / page_size) if page_size > 0 else 0
    has_next = page < total_pages
    has_previous = page > 1
    start_index = (page - 1) * page_size + 1 if total_count > 0 else 0
    end_index = min(page * page_size, total_count)

    # Build base query string
    qs = query_params.copy() if query_params else {}
    qs.pop('page', None)
    qs.pop('page_size', None)

    def build_url(page_num):
        params = qs.copy()
        params['page'] = str(page_num)
        params['page_size'] = str(page_size)
        param_str = '&'.join([f"{k}={v}" for k, v in params.items()])
        return f"{base_url}?{param_str}" if param_str else base_url

    return {
        'count': total_count,
        'total_pages': total_pages,
        'current_page': page,
        'page_size': page_size,
        'has_next': has_next,
        'has_previous': has_previous,
        'next': build_url(page + 1) if has_next else None,
        'previous': build_url(page - 1) if has_previous else None,
        'start_index': start_index,
        'end_index': end_index,
        'results': data
    }


def get_page_from_request(request, default: int = 1) -> int:
    """
    Extract and validate page number from request.

    Args:
        request: HTTP request object
        default: Default page number if not provided

    Returns:
        Validated page number
    """
    try:
        page = int(request.query_params.get('page', default))
        if page < 1:
            return default
        return page
    except ValueError:
        return default


def get_page_size_from_request(request, default: int = 20, max_size: int = 100) -> int:
    """
    Extract and validate page size from request.

    Args:
        request: HTTP request object
        default: Default page size if not provided
        max_size: Maximum allowed page size

    Returns:
        Validated page size
    """
    try:
        page_size = int(request.query_params.get('page_size', default))
        if page_size < 1:
            return default
        if page_size > max_size:
            return max_size
        return page_size
    except ValueError:
        return default


def get_offset_from_request(request, default: int = 0) -> int:
    """
    Extract and validate offset from request.

    Args:
        request: HTTP request object
        default: Default offset if not provided

    Returns:
        Validated offset
    """
    try:
        offset = int(request.query_params.get('offset', default))
        if offset < 0:
            return default
        return offset
    except ValueError:
        return default


def get_cursor_from_request(request) -> Optional[str]:
    """
    Extract cursor from request.

    Args:
        request: HTTP request object

    Returns:
        Cursor string or None
    """
    return request.query_params.get('cursor')


# ============================================================================
# PAGINATION DECORATORS
# ============================================================================

def auto_paginate(pagination_class: Type[PageNumberPagination] = StandardPagination):
    """
    Decorator to automatically apply pagination to view responses.

    Args:
        pagination_class: Pagination class to use (default: StandardPagination)

    Returns:
        Decorated view function
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            # Create pagination instance
            paginator = pagination_class()

            # Check if view returns paginated queryset
            response = view_func(request, *args, **kwargs)
            if hasattr(response, 'data') and isinstance(response.data, dict):
                # Assume it's already paginated
                return response

            # If response is a queryset or list, paginate it
            if hasattr(response, '__iter__'):
                page = paginator.paginate_queryset(response, request)
                if page is not None:
                    return paginator.get_paginated_response(page)
            return response
        return wrapped_view
    return decorator


def paginate_queryset(
    queryset,
    page: int,
    page_size: int,
    serializer_class: Optional[Type] = None,
    context: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Paginate a queryset and return serialized data with metadata.

    Args:
        queryset: Django queryset to paginate
        page: Page number (1-indexed)
        page_size: Number of items per page
        serializer_class: Optional serializer class for serialization
        context: Optional context for serializer

    Returns:
        Dict with paginated data and metadata
    """
    from django.core.paginator import Paginator

    paginator = Paginator(queryset, page_size)
    total_count = paginator.count
    total_pages = paginator.num_pages

    # Validate page
    if page < 1:
        page = 1
    if page > total_pages and total_pages > 0:
        page = total_pages

    page_obj = paginator.page(page)

    # Serialize if serializer provided
    if serializer_class:
        context = context or {}
        data = serializer_class(page_obj.object_list, many=True, context=context).data
    else:
        data = list(page_obj.object_list)

    return {
        'count': total_count,
        'total_pages': total_pages,
        'current_page': page,
        'page_size': page_size,
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
        'start_index': (page - 1) * page_size + 1 if total_count > 0 else 0,
        'end_index': min(page * page_size, total_count),
        'results': data
    }


# ============================================================================
# PAGINATION HELPER FOR VIEWSETS
# ============================================================================

class PaginatedViewSetMixin:
    """
    Mixin to add pagination to viewset list methods.

    Usage:
        class MyViewSet(PaginatedViewSetMixin, ModelViewSet):
            pagination_class = CustomPagination
    """
    pagination_class = StandardPagination

    def list(self, request, *args, **kwargs):
        """
        Override list to apply custom pagination.
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def paginate_queryset(self, queryset):
        """
        Paginate the queryset if pagination is configured.
        """
        if self.pagination_class is None:
            return None
        paginator = self.pagination_class()
        return paginator.paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data):
        """
        Return paginated response using the configured pagination class.
        """
        if self.pagination_class is None:
            return Response(data)
        paginator = self.pagination_class()
        return paginator.get_paginated_response(data)


# ============================================================================
# PAGINATION CONSTANTS
# ============================================================================

PAGINATION_DEFAULT_LIMIT = 20
PAGINATION_MAX_LIMIT = 100
PAGINATION_ADMIN_LIMIT = 50
PAGINATION_MOBILE_LIMIT = 10
PAGINATION_LARGE_LIMIT = 500

# ============================================================================
# PAGINATION CHAINING
# ============================================================================

class PaginationChain:
    """
    Class for chaining multiple paginated queries.
    Useful for aggregating results from multiple data sources.
    """
    def __init__(self, *querysets, page=1, page_size=20):
        self.querysets = querysets
        self.page = page
        self.page_size = page_size

    def get_results(self):
        """
        Get combined paginated results from all querysets.
        """
        from itertools import chain

        # Combine all querysets
        combined = list(chain(*[list(qs) for qs in self.querysets]))
        total_count = len(combined)

        # Calculate pagination
        total_pages = math.ceil(total_count / self.page_size) if self.page_size > 0 else 0
        page = max(1, min(self.page, total_pages)) if total_pages > 0 else 1
        start = (page - 1) * self.page_size
        end = start + self.page_size

        # Slice results
        results = combined[start:end]

        return {
            'count': total_count,
            'total_pages': total_pages,
            'current_page': page,
            'page_size': self.page_size,
            'has_next': page < total_pages,
            'has_previous': page > 1,
            'start_index': start + 1 if total_count > 0 else 0,
            'end_index': min(end, total_count),
            'results': results
        }

    def get_serialized_results(self, serializer_class, context=None):
        """
        Get paginated results serialized with the given serializer.
        """
        data = self.get_results()
        data['results'] = serializer_class(data['results'], many=True, context=context).data
        return data


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'StandardPagination',
    'LargePagination',
    'SmallPagination',
    'AdminPagination',
    'MobilePagination',
    'CursorBasedPagination',
    'CustomCursorPagination',
    'LegacyPagination',
    'CustomPagination',
    'build_paginated_response',
    'get_page_from_request',
    'get_page_size_from_request',
    'get_offset_from_request',
    'get_cursor_from_request',
    'auto_paginate',
    'paginate_queryset',
    'PaginatedViewSetMixin',
    'PaginationChain',
    'PAGINATION_DEFAULT_LIMIT',
    'PAGINATION_MAX_LIMIT',
    'PAGINATION_ADMIN_LIMIT',
    'PAGINATION_MOBILE_LIMIT',
    'PAGINATION_LARGE_LIMIT',
]