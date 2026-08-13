from django.contrib.auth import authenticate, logout
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q, Count, Sum, Avg
from django.core.cache import cache
from rest_framework import status, generics, permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from .models import User
from .serializers import (
    UserRegistrationSerializer, UserLoginSerializer, UserProfileSerializer,
    UserProfileUpdateSerializer, ChangePasswordSerializer, OTPSendSerializer,
    OTPVerifySerializer, PasswordResetRequestSerializer, PasswordResetConfirmSerializer,
    LogoutSerializer, RefreshTokenSerializer, UserListSerializer, UserDetailSerializer,
    AdminUserUpdateSerializer, TokenObtainSerializer, ReferralStatsSerializer,
    EmailVerificationSerializer, UserBaseSerializer
)
from apps.common.permissions import IsSuperAdmin, IsAdminOrReadOnly
from apps.common.pagination import CustomPagination
from apps.common.utils import send_otp_email, send_otp_sms, generate_otp


# ============================================================================
# AUTHENTICATION VIEWS
# ============================================================================

class UserRegistrationView(APIView):
    """
    User registration endpoint.
    Creates a new user account and sends OTP for verification.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=UserRegistrationSerializer,
        responses={201: UserProfileSerializer, 400: 'Bad Request'}
    )
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            with transaction.atomic():
                user = serializer.save()
                # Generate and send OTP
                otp = user.generate_otp(purpose='registration')
                # Send OTP via email and SMS
                if user.email:
                    send_otp_email(user.email, otp)
                if user.phone:
                    send_otp_sms(user.phone, otp)
                # Generate tokens
                refresh = RefreshToken.for_user(user)
                return Response({
                    'user': UserProfileSerializer(user).data,
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                    'message': 'Registration successful. OTP sent for verification.'
                }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserLoginView(APIView):
    """
    User login endpoint.
    Authenticates user and returns JWT tokens with user data.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=UserLoginSerializer,
        responses={200: TokenObtainSerializer, 401: 'Unauthorized'}
    )
    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            # Update last login IP
            ip_address = request.META.get('HTTP_X_FORWARDED_FOR')
            if ip_address:
                ip_address = ip_address.split(',')[0]
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            user.last_login_ip = ip_address
            user.save(update_fields=['last_login_ip'])
            return Response({
                'user': UserProfileSerializer(user).data,
                'access': serializer.validated_data['access'],
                'refresh': serializer.validated_data['refresh'],
                'message': 'Login successful.'
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_401_UNAUTHORIZED)


class LogoutView(APIView):
    """
    User logout endpoint.
    Blacklists the refresh token to prevent reuse.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=LogoutSerializer,
        responses={200: 'Logout successful', 400: 'Bad Request'}
    )
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        if serializer.is_valid():
            return Response({
                'message': 'Logout successful.'
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RefreshTokenView(APIView):
    """
    Refresh access token endpoint.
    Returns a new access token using a valid refresh token.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=RefreshTokenSerializer,
        responses={200: RefreshTokenSerializer, 400: 'Bad Request'}
    )
    def post(self, request):
        serializer = RefreshTokenSerializer(data=request.data)
        if serializer.is_valid():
            return Response({
                'access': serializer.validated_data['access'],
                'refresh': serializer.validated_data['refresh']
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Custom token obtain view that returns user data along with tokens.
    """
    serializer_class = TokenObtainSerializer


# ============================================================================
# PROFILE VIEWS
# ============================================================================

class MeView(APIView):
    """
    Get current authenticated user details.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses={200: UserProfileSerializer}
    )
    def get(self, request):
        user = request.user
        user.update_last_activity()
        return Response(UserProfileSerializer(user).data, status=status.HTTP_200_OK)


class UserProfileView(APIView):
    """
    Get and update user profile.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses={200: UserProfileSerializer}
    )
    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=UserProfileUpdateSerializer,
        responses={200: UserProfileSerializer, 400: 'Bad Request'}
    )
    def put(self, request):
        serializer = UserProfileUpdateSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(UserProfileSerializer(request.user).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PublicUserProfileView(APIView):
    """
    Get public user profile by ID or email.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='id', description='User ID', type=int),
            OpenApiParameter(name='email', description='User email', type=str)
        ],
        responses={200: UserBaseSerializer, 404: 'Not Found'}
    )
    def get(self, request):
        user_id = request.query_params.get('id')
        email = request.query_params.get('email')
        if user_id:
            user = get_object_or_404(User, id=user_id)
        elif email:
            user = get_object_or_404(User, email=email)
        else:
            return Response({'error': 'Either id or email parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(UserBaseSerializer(user).data, status=status.HTTP_200_OK)


# ============================================================================
# CHANGE PASSWORD VIEW
# ============================================================================

class ChangePasswordView(APIView):
    """
    Change user password endpoint.
    Requires old password and new password.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=ChangePasswordSerializer,
        responses={200: 'Password changed', 400: 'Bad Request'}
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            if not user.check_password(serializer.validated_data['old_password']):
                return Response({
                    'old_password': ['Incorrect old password.']
                }, status=status.HTTP_400_BAD_REQUEST)
            user.set_password(serializer.validated_data['new_password'])
            user.save()
            return Response({
                'message': 'Password changed successfully.'
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# OTP VIEWS
# ============================================================================

class OTPSendView(APIView):
    """
    Send OTP to user's email or phone.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=OTPSendSerializer,
        responses={200: 'OTP sent', 400: 'Bad Request'}
    )
    def post(self, request):
        serializer = OTPSendSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            purpose = serializer.validated_data.get('purpose', 'login')
            otp = user.generate_otp(purpose=purpose)

            # Send via email if available
            if user.email:
                send_otp_email(user.email, otp)
            # Send via SMS if available
            if user.phone:
                send_otp_sms(user.phone, otp)

            return Response({
                'message': 'OTP sent successfully.',
                'purpose': purpose,
                'expires_in': 300
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OTPVerifyView(APIView):
    """
    Verify OTP sent to user's email or phone.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=OTPVerifySerializer,
        responses={200: 'OTP verified', 400: 'Bad Request'}
    )
    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            return Response({
                'message': 'OTP verified successfully.',
                'user': UserProfileSerializer(user).data
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OTPResendView(APIView):
    """
    Resend OTP to user's email or phone.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=OTPSendSerializer,
        responses={200: 'OTP resent', 400: 'Bad Request'}
    )
    def post(self, request):
        serializer = OTPSendSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            purpose = serializer.validated_data.get('purpose', 'login')
            # Check rate limiting using cache
            cache_key = f'otp_resend_{user.id}_{purpose}'
            if cache.get(cache_key):
                return Response({
                    'error': 'Please wait 60 seconds before requesting a new OTP.'
                }, status=status.HTTP_429_TOO_MANY_REQUESTS)

            otp = user.generate_otp(purpose=purpose)

            if user.email:
                send_otp_email(user.email, otp)
            if user.phone:
                send_otp_sms(user.phone, otp)

            # Set rate limit cache
            cache.set(cache_key, True, 60)

            return Response({
                'message': 'OTP resent successfully.',
                'purpose': purpose,
                'expires_in': 300
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# PASSWORD RESET VIEWS
# ============================================================================

class PasswordResetRequestView(APIView):
    """
    Request password reset.
    Sends OTP to user's email.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=PasswordResetRequestSerializer,
        responses={200: 'OTP sent', 400: 'Bad Request'}
    )
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            user = User.objects.get(email=email)
            otp = user.generate_otp(purpose='password_reset')
            send_otp_email(email, otp)
            return Response({
                'message': 'Password reset OTP sent to your email.',
                'expires_in': 300
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetConfirmView(APIView):
    """
    Confirm password reset with OTP and set new password.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=PasswordResetConfirmSerializer,
        responses={200: 'Password reset', 400: 'Bad Request'}
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            user.set_password(serializer.validated_data['new_password'])
            user.otp_verified = False
            user.otp = None
            user.otp_created_at = None
            user.save()
            return Response({
                'message': 'Password reset successfully.'
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# EMAIL VERIFICATION VIEW
# ============================================================================

class EmailVerificationView(APIView):
    """
    Verify user's email address.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=EmailVerificationSerializer,
        responses={200: 'Email verified', 400: 'Bad Request'}
    )
    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            if user.email != serializer.validated_data['email']:
                return Response({
                    'email': ['Email does not match your account.']
                }, status=status.HTTP_400_BAD_REQUEST)
            user.is_email_verified = True
            user.save(update_fields=['is_email_verified'])
            return Response({
                'message': 'Email verified successfully.'
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PhoneVerificationView(APIView):
    """
    Verify user's phone number.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=OTPVerifySerializer,
        responses={200: 'Phone verified', 400: 'Bad Request'}
    )
    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            if user.phone != serializer.validated_data['phone']:
                return Response({
                    'phone': ['Phone number does not match your account.']
                }, status=status.HTTP_400_BAD_REQUEST)
            user.is_phone_verified = True
            user.save(update_fields=['is_phone_verified'])
            return Response({
                'message': 'Phone number verified successfully.'
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# REFERRAL VIEWS
# ============================================================================

class ReferralStatsView(APIView):
    """
    Get user's referral statistics.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses={200: ReferralStatsSerializer}
    )
    def get(self, request):
        serializer = ReferralStatsSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ReferralListView(APIView):
    """
    Get list of users referred by the current user.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses={200: UserListSerializer(many=True)}
    )
    def get(self, request):
        referred_users = User.objects.filter(referred_by=request.user)
        serializer = UserListSerializer(referred_users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# ADMIN USER VIEWSET
# ============================================================================

class AdminUserViewSet(viewsets.ModelViewSet):
    """
    Admin viewset for managing users.
    Full CRUD operations with additional actions.
    """
    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        queryset = User.objects.all()
        search = self.request.query_params.get('search', '')
        status_filter = self.request.query_params.get('status', '')
        verification_filter = self.request.query_params.get('verification', '')
        date_from = self.request.query_params.get('date_from', '')
        date_to = self.request.query_params.get('date_to', '')

        if search:
            queryset = queryset.filter(
                Q(email__icontains=search) |
                Q(phone__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(middle_name__icontains=search) |
                Q(referral_code__icontains=search)
            )

        if status_filter:
            if status_filter == 'active':
                queryset = queryset.filter(is_active=True, is_suspended=False)
            elif status_filter == 'inactive':
                queryset = queryset.filter(is_active=False)
            elif status_filter == 'suspended':
                queryset = queryset.filter(is_suspended=True)
            elif status_filter == 'locked':
                queryset = queryset.filter(is_locked=True)
            elif status_filter == 'deleted':
                queryset = queryset.filter(deleted_at__isnull=False)
            elif status_filter == 'verified':
                queryset = queryset.filter(is_verified=True)

        if verification_filter:
            if verification_filter == 'phone_verified':
                queryset = queryset.filter(is_phone_verified=True)
            elif verification_filter == 'email_verified':
                queryset = queryset.filter(is_email_verified=True)
            elif verification_filter == 'identity_verified':
                queryset = queryset.filter(is_identity_verified=True)
            elif verification_filter == 'unverified':
                queryset = queryset.filter(
                    is_phone_verified=False,
                    is_email_verified=False
                )

        if date_from:
            queryset = queryset.filter(date_joined__gte=date_from)
        if date_to:
            queryset = queryset.filter(date_joined__lte=date_to)

        return queryset.select_related('referred_by').order_by('-date_joined')

    def get_serializer_class(self):
        if self.action == 'list':
            return UserListSerializer
        elif self.action == 'retrieve':
            return UserDetailSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return AdminUserUpdateSerializer
        return UserListSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(name='search', description='Search by email, phone, or name', type=str),
            OpenApiParameter(name='status', description='Filter by status (active, inactive, suspended, locked, deleted, verified)', type=str),
            OpenApiParameter(name='verification', description='Filter by verification (phone_verified, email_verified, identity_verified, unverified)', type=str),
            OpenApiParameter(name='date_from', description='Filter from date (YYYY-MM-DD)', type=str),
            OpenApiParameter(name='date_to', description='Filter to date (YYYY-MM-DD)', type=str)
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def suspend(self, request, id=None):
        user = self.get_object()
        if user.is_suspended:
            return Response({'error': 'User is already suspended.'}, status=status.HTTP_400_BAD_REQUEST)
        user.is_suspended = True
        user.is_active = False
        user.suspended_at = timezone.now()
        user.suspension_reason = request.data.get('reason', 'No reason provided')
        user.save(update_fields=['is_suspended', 'is_active', 'suspended_at', 'suspension_reason'])
        return Response({
            'message': f'User {user.email} has been suspended.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def unsuspend(self, request, id=None):
        user = self.get_object()
        if not user.is_suspended:
            return Response({'error': 'User is not suspended.'}, status=status.HTTP_400_BAD_REQUEST)
        user.is_suspended = False
        user.is_active = True
        user.suspended_at = None
        user.suspension_reason = None
        user.save(update_fields=['is_suspended', 'is_active', 'suspended_at', 'suspension_reason'])
        return Response({
            'message': f'User {user.email} has been unsuspended.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def lock(self, request, id=None):
        duration = request.data.get('duration_minutes', 30)
        user = self.get_object()
        if user.is_locked:
            return Response({'error': 'User is already locked.'}, status=status.HTTP_400_BAD_REQUEST)
        user.lock_account(duration_minutes=duration)
        return Response({
            'message': f'User {user.email} locked for {duration} minutes.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def unlock(self, request, id=None):
        user = self.get_object()
        if not user.is_locked:
            return Response({'error': 'User is not locked.'}, status=status.HTTP_400_BAD_REQUEST)
        user.unlock_account()
        return Response({
            'message': f'User {user.email} has been unlocked.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def verify_phone(self, request, id=None):
        user = self.get_object()
        if user.is_phone_verified:
            return Response({'error': 'Phone is already verified.'}, status=status.HTTP_400_BAD_REQUEST)
        user.is_phone_verified = True
        user.save(update_fields=['is_phone_verified'])
        return Response({
            'message': f'Phone verified for {user.email}.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def verify_email(self, request, id=None):
        user = self.get_object()
        if user.is_email_verified:
            return Response({'error': 'Email is already verified.'}, status=status.HTTP_400_BAD_REQUEST)
        user.is_email_verified = True
        user.save(update_fields=['is_email_verified'])
        return Response({
            'message': f'Email verified for {user.email}.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def verify_identity(self, request, id=None):
        user = self.get_object()
        if user.is_identity_verified:
            return Response({'error': 'Identity is already verified.'}, status=status.HTTP_400_BAD_REQUEST)
        user.is_identity_verified = True
        user.is_verified = True
        user.identity_verification_date = timezone.now()
        user.save(update_fields=['is_identity_verified', 'is_verified', 'identity_verification_date'])
        return Response({
            'message': f'Identity verified for {user.email}.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def soft_delete(self, request, id=None):
        user = self.get_object()
        if user.is_deleted():
            return Response({'error': 'User is already deleted.'}, status=status.HTTP_400_BAD_REQUEST)
        reason = request.data.get('reason', 'Deleted by admin')
        user.soft_delete(reason=reason)
        return Response({
            'message': f'User {user.email} has been soft deleted.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def restore(self, request, id=None):
        user = self.get_object()
        if not user.is_deleted():
            return Response({'error': 'User is not deleted.'}, status=status.HTTP_400_BAD_REQUEST)
        user.restore()
        return Response({
            'message': f'User {user.email} has been restored.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def stats(self, request, id=None):
        user = self.get_object()
        return Response({
            'email': user.email,
            'phone': user.phone,
            'full_name': user.full_name,
            'date_joined': user.date_joined,
            'last_login': user.last_login,
            'login_count': user.login_count,
            'is_active': user.is_active,
            'is_suspended': user.is_suspended,
            'is_locked': user.is_locked,
            'is_phone_verified': user.is_phone_verified,
            'is_email_verified': user.is_email_verified,
            'is_identity_verified': user.is_identity_verified,
            'verification_level': user.verification_level,
            'total_groups_joined': user.total_groups_joined,
            'total_groups_created': user.total_groups_created,
            'total_contributed': float(user.total_contributed),
            'total_received': float(user.total_received),
            'total_earned': float(user.total_earned),
            'reputation_score': user.reputation_score,
            'defaulted_count': user.defaulted_count,
            'on_time_payments': user.on_time_payments,
            'referral_count': user.referral_count,
            'account_age_days': user.account_age_days
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        total_users = User.objects.count()
        active_users = User.objects.filter(is_active=True).count()
        suspended_users = User.objects.filter(is_suspended=True).count()
        locked_users = User.objects.filter(is_locked=True).count()
        verified_users = User.objects.filter(is_verified=True).count()
        phone_verified = User.objects.filter(is_phone_verified=True).count()
        email_verified = User.objects.filter(is_email_verified=True).count()
        identity_verified = User.objects.filter(is_identity_verified=True).count()
        deleted_users = User.objects.filter(deleted_at__isnull=False).count()

        today = timezone.now().date()
        new_users_today = User.objects.filter(date_joined__date=today).count()
        this_week = today - timezone.timedelta(days=7)
        new_users_week = User.objects.filter(date_joined__date__gte=this_week).count()
        this_month = today - timezone.timedelta(days=30)
        new_users_month = User.objects.filter(date_joined__date__gte=this_month).count()

        avg_reputation = User.objects.aggregate(avg=Avg('reputation_score'))['avg'] or 0

        return Response({
            'total_users': total_users,
            'active_users': active_users,
            'suspended_users': suspended_users,
            'locked_users': locked_users,
            'verified_users': verified_users,
            'phone_verified': phone_verified,
            'email_verified': email_verified,
            'identity_verified': identity_verified,
            'deleted_users': deleted_users,
            'new_users_today': new_users_today,
            'new_users_this_week': new_users_week,
            'new_users_this_month': new_users_month,
            'avg_reputation_score': round(avg_reputation, 2)
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def bulk_verify(self, request):
        user_ids = request.data.get('user_ids', [])
        verification_type = request.data.get('type', 'phone')
        if not user_ids:
            return Response({'error': 'user_ids list is required.'}, status=status.HTTP_400_BAD_REQUEST)

        users = User.objects.filter(id__in=user_ids)
        count = users.count()
        if verification_type == 'phone':
            users.update(is_phone_verified=True)
        elif verification_type == 'email':
            users.update(is_email_verified=True)
        elif verification_type == 'identity':
            users.update(is_identity_verified=True, is_verified=True, identity_verification_date=timezone.now())
        else:
            return Response({'error': 'Invalid verification type.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'message': f'Updated {count} users.',
            'type': verification_type
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def bulk_suspend(self, request):
        user_ids = request.data.get('user_ids', [])
        reason = request.data.get('reason', 'Bulk suspension by admin')
        if not user_ids:
            return Response({'error': 'user_ids list is required.'}, status=status.HTTP_400_BAD_REQUEST)
        users = User.objects.filter(id__in=user_ids)
        count = users.count()
        users.update(
            is_suspended=True,
            is_active=False,
            suspended_at=timezone.now(),
            suspension_reason=reason
        )
        return Response({
            'message': f'Suspended {count} users.',
            'reason': reason
        }, status=status.HTTP_200_OK)


# ============================================================================
# ACTIVITY TRACKING VIEW
# ============================================================================

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def update_activity(request):
    """
    Update user's last activity timestamp.
    """
    user = request.user
    user.update_last_activity()
    return Response({
        'message': 'Activity updated.',
        'last_activity': user.last_activity
    }, status=status.HTTP_200_OK)


# ============================================================================
# DEVICE MANAGEMENT VIEW
# ============================================================================

class DeviceRegistrationView(APIView):
    """
    Register device for push notifications.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request={
            'type': 'object',
            'properties': {
                'fcm_token': {'type': 'string'},
                'device_type': {'type': 'string', 'enum': ['ios', 'android', 'web', 'desktop']},
                'device_id': {'type': 'string'}
            }
        },
        responses={200: 'Device registered'}
    )
    def post(self, request):
        user = request.user
        fcm_token = request.data.get('fcm_token')
        device_type = request.data.get('device_type')
        device_id = request.data.get('device_id')

        if not fcm_token:
            return Response({'error': 'fcm_token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        user.fcm_token = fcm_token
        user.device_type = device_type
        user.device_id = device_id
        user.save(update_fields=['fcm_token', 'device_type', 'device_id'])

        return Response({
            'message': 'Device registered successfully.'
        }, status=status.HTTP_200_OK)

    @extend_schema(
        responses={200: 'Device unregistered'}
    )
    def delete(self, request):
        user = request.user
        user.fcm_token = None
        user.device_type = None
        user.device_id = None
        user.save(update_fields=['fcm_token', 'device_type', 'device_id'])
        return Response({
            'message': 'Device unregistered successfully.'
        }, status=status.HTTP_200_OK)