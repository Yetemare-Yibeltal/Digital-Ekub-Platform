from django.contrib.auth import authenticate, logout
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q, Count, Sum
from rest_framework import status, generics, permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from drf_spectacular.utils import extend_schema, OpenApiParameter
from .models import User
from .serializers import (
    UserRegistrationSerializer, UserLoginSerializer, UserProfileSerializer,
    UserProfileUpdateSerializer, ChangePasswordSerializer, OTPSendSerializer,
    OTPVerifySerializer, PasswordResetRequestSerializer, PasswordResetConfirmSerializer,
    LogoutSerializer, RefreshTokenSerializer, UserListSerializer, UserDetailSerializer,
    AdminUserUpdateSerializer, TokenObtainSerializer, ReferralStatsSerializer,
    EmailVerificationSerializer
)
from apps.common.permissions import IsSuperAdmin, IsAdminOrReadOnly
from apps.common.pagination import CustomPagination
from apps.common.utils import send_otp_email, send_otp_sms, generate_otp


# ============================================================================
# REGISTRATION VIEW
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


# ============================================================================
# LOGIN VIEW
# ============================================================================

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


# ============================================================================
# LOGOUT VIEW
# ============================================================================

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


# ============================================================================
# REFRESH TOKEN VIEW
# ============================================================================

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


# ============================================================================
# PROFILE VIEWS
# ============================================================================

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
                'expires_in': 300  # 5 minutes
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


# ============================================================================
# REFERRAL STATS VIEW
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


# ============================================================================
# ADMIN USER VIEWSET
# ============================================================================

class AdminUserViewSet(viewsets.ModelViewSet):
    """
    Admin viewset for managing users.
    """
    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]
    pagination_class = CustomPagination
    lookup_field = 'id'

    def get_queryset(self):
        queryset = User.objects.all()
        search = self.request.query_params.get('search', '')
        status_filter = self.request.query_params.get('status', '')

        if search:
            queryset = queryset.filter(
                Q(email__icontains=search) |
                Q(phone__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )

        if status_filter:
            if status_filter == 'active':
                queryset = queryset.filter(is_active=True)
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

        return queryset.order_by('-date_joined')

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
            OpenApiParameter(name='status', description='Filter by status (active, inactive, suspended, locked, deleted, verified)', type=str)
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def suspend(self, request, id=None):
        user = self.get_object()
        user.is_suspended = True
        user.is_active = False
        user.suspended_at = timezone.now()
        user.suspension_reason = request.data.get('reason', 'No reason provided')
        user.save()
        return Response({
            'message': f'User {user.email} suspended.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def unsuspend(self, request, id=None):
        user = self.get_object()
        user.is_suspended = False
        user.is_active = True
        user.suspended_at = None
        user.suspension_reason = None
        user.save()
        return Response({
            'message': f'User {user.email} unsuspended.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def lock(self, request, id=None):
        duration = request.data.get('duration_minutes', 30)
        user = self.get_object()
        user.lock_account(duration_minutes=duration)
        return Response({
            'message': f'User {user.email} locked for {duration} minutes.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def unlock(self, request, id=None):
        user = self.get_object()
        user.unlock_account()
        return Response({
            'message': f'User {user.email} unlocked.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def verify_phone(self, request, id=None):
        user = self.get_object()
        user.is_phone_verified = True
        user.save(update_fields=['is_phone_verified'])
        return Response({
            'message': f'Phone verified for {user.email}.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def verify_email(self, request, id=None):
        user = self.get_object()
        user.is_email_verified = True
        user.save(update_fields=['is_email_verified'])
        return Response({
            'message': f'Email verified for {user.email}.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def verify_identity(self, request, id=None):
        user = self.get_object()
        user.is_identity_verified = True
        user.is_verified = True
        user.identity_verification_date = timezone.now()
        user.save(update_fields=['is_identity_verified', 'is_verified', 'identity_verification_date'])
        return Response({
            'message': f'Identity verified for {user.email}.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['delete'])
    def soft_delete(self, request, id=None):
        user = self.get_object()
        reason = request.data.get('reason', 'Deleted by admin')
        user.soft_delete(reason=reason)
        return Response({
            'message': f'User {user.email} soft deleted.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def restore(self, request, id=None):
        user = self.get_object()
        user.restore()
        return Response({
            'message': f'User {user.email} restored.',
            'user': UserListSerializer(user).data
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        total_users = User.objects.count()
        active_users = User.objects.filter(is_active=True).count()
        suspended_users = User.objects.filter(is_suspended=True).count()
        locked_users = User.objects.filter(is_locked=True).count()
        verified_users = User.objects.filter(is_verified=True).count()
        phone_verified = User.objects.filter(is_phone_verified=True).count()
        email_verified = User.objects.filter(is_email_verified=True).count()
        identity_verified = User.objects.filter(is_identity_verified=True).count()

        return Response({
            'total_users': total_users,
            'active_users': active_users,
            'suspended_users': suspended_users,
            'locked_users': locked_users,
            'verified_users': verified_users,
            'phone_verified': phone_verified,
            'email_verified': email_verified,
            'identity_verified': identity_verified
        }, status=status.HTTP_200_OK)


# ============================================================================
# TOKEN OBTAIN PAIR VIEW (CUSTOM)
# ============================================================================

class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Custom token obtain view that returns user data along with tokens.
    """
    serializer_class = TokenObtainSerializer


# ============================================================================
# ME VIEW (CURRENT USER)
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