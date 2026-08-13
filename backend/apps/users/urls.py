from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'admin/users', views.AdminUserViewSet, basename='admin-user')

urlpatterns = [
    path('register/', views.UserRegistrationView.as_view(), name='register'),
    path('login/', views.UserLoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('refresh/', views.RefreshTokenView.as_view(), name='refresh'),
    path('token/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),

    path('me/', views.MeView.as_view(), name='me'),
    path('profile/', views.UserProfileView.as_view(), name='profile'),
    path('public-profile/', views.PublicUserProfileView.as_view(), name='public-profile'),

    path('change-password/', views.ChangePasswordView.as_view(), name='change-password'),
    path('password-reset-request/', views.PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('password-reset-confirm/', views.PasswordResetConfirmView.as_view(), name='password-reset-confirm'),

    path('otp-send/', views.OTPSendView.as_view(), name='otp-send'),
    path('otp-verify/', views.OTPVerifyView.as_view(), name='otp-verify'),
    path('otp-resend/', views.OTPResendView.as_view(), name='otp-resend'),

    path('verify-email/', views.EmailVerificationView.as_view(), name='verify-email'),
    path('verify-phone/', views.PhoneVerificationView.as_view(), name='verify-phone'),

    path('referral-stats/', views.ReferralStatsView.as_view(), name='referral-stats'),
    path('referrals/', views.ReferralListView.as_view(), name='referrals'),

    path('update-activity/', views.update_activity, name='update-activity'),

    path('device/', views.DeviceRegistrationView.as_view(), name='device'),

    path('', include(router.urls)),
]