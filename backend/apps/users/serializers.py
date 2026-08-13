import re
import random
from datetime import timedelta
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.validators import EmailValidator, RegexValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from .models import User


# ============================================================================
# PHONE NUMBER VALIDATOR
# ============================================================================

phone_regex = RegexValidator(
    regex=r'^\+?[1-9]\d{9,14}$',
    message=_("Phone number must be in international format: '+2519XXXXXXXX'")
)


# ============================================================================
# BASE USER SERIALIZER
# ============================================================================

class UserBaseSerializer(serializers.ModelSerializer):
    """Base serializer with common fields for User model."""
    class Meta:
        model = User
        fields = (
            'id', 'email', 'phone', 'first_name', 'last_name',
            'middle_name', 'full_name', 'profile_picture', 'language',
            'is_phone_verified', 'is_email_verified', 'is_identity_verified',
            'date_joined', 'last_activity', 'reputation_score'
        )
        read_only_fields = (
            'id', 'full_name', 'is_phone_verified', 'is_email_verified',
            'is_identity_verified', 'date_joined', 'last_activity',
            'reputation_score'
        )

    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        return obj.full_name


# ============================================================================
# REGISTRATION SERIALIZER
# ============================================================================

class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration. Validates email, phone, password,
    and creates a new user with OTP.
    """
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password2 = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        label=_('Confirm Password')
    )
    email = serializers.EmailField(
        required=True,
        validators=[
            UniqueValidator(
                queryset=User.objects.all(),
                message=_('A user with this email already exists.')
            ),
            EmailValidator(message=_('Enter a valid email address.'))
        ]
    )
    phone = serializers.CharField(
        required=True,
        validators=[
            phone_regex,
            UniqueValidator(
                queryset=User.objects.all(),
                message=_('A user with this phone number already exists.')
            )
        ]
    )
    first_name = serializers.CharField(required=True, max_length=150)
    last_name = serializers.CharField(required=True, max_length=150)
    middle_name = serializers.CharField(required=False, max_length=150, allow_blank=True)
    language = serializers.ChoiceField(
        choices=['en', 'am', 'om', 'ti', 'so'],
        default='en',
        required=False
    )

    class Meta:
        model = User
        fields = (
            'email', 'phone', 'first_name', 'last_name', 'middle_name',
            'password', 'password2', 'language', 'referral_code'
        )
        extra_kwargs = {
            'referral_code': {'required': False, 'allow_blank': True}
        }

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError(
                {'password2': _('Password fields did not match.')}
            )
        return attrs

    def validate_referral_code(self, value):
        if value:
            if not User.objects.filter(referral_code=value).exists():
                raise serializers.ValidationError(_('Invalid referral code.'))
        return value

    def create(self, validated_data):
        validated_data.pop('password2')
        referral_code = validated_data.pop('referral_code', None)
        user = User(
            email=validated_data['email'],
            phone=validated_data['phone'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            middle_name=validated_data.get('middle_name', ''),
            language=validated_data.get('language', 'en')
        )
        user.set_password(validated_data['password'])
        user.is_active = True

        # Handle referral
        if referral_code:
            referrer = User.objects.get(referral_code=referral_code)
            user.referred_by = referrer
            referrer.referral_count += 1
            referrer.save(update_fields=['referral_count'])

        user.save()
        return user


# ============================================================================
# LOGIN SERIALIZER
# ============================================================================

class UserLoginSerializer(serializers.Serializer):
    """
    Serializer for user login. Returns user data with access and refresh tokens.
    """
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})
    remember_me = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if email and password:
            user = authenticate(email=email, password=password)
            if not user:
                raise serializers.ValidationError(
                    _('Invalid email or password. Please try again.')
                )
            if not user.is_active:
                raise serializers.ValidationError(
                    _('This account is inactive. Please contact support.')
                )
            if user.is_suspended:
                raise serializers.ValidationError(
                    _('This account has been suspended. Please contact support.')
                )
            if user.is_account_locked():
                raise serializers.ValidationError(
                    _('This account is temporarily locked due to too many failed attempts. Please try again later.')
                )
            if user.is_deleted():
                raise serializers.ValidationError(
                    _('This account has been deleted. Please contact support.')
                )
        else:
            raise serializers.ValidationError(
                _('Email and password are required.')
            )

        # Update login tracking
        user.last_login = timezone.now()
        user.login_count += 1
        user.failed_login_attempts = 0
        user.save(update_fields=['last_login', 'login_count', 'failed_login_attempts'])

        # Generate tokens
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        # Set token lifetime based on remember_me
        if attrs.get('remember_me'):
            refresh.set_exp(lifetime=timedelta(days=30))
            access.set_exp(lifetime=timedelta(days=7))

        attrs['user'] = user
        attrs['refresh'] = str(refresh)
        attrs['access'] = str(access)

        return attrs


# ============================================================================
# PROFILE SERIALIZER (READ ONLY)
# ============================================================================

class UserProfileSerializer(UserBaseSerializer):
    """
    Read-only serializer for user profile details with full fields.
    """
    class Meta(UserBaseSerializer.Meta):
        fields = UserBaseSerializer.Meta.fields + (
            'cover_photo', 'date_of_birth', 'gender', 'address', 'city',
            'country', 'timezone', 'currency', 'is_verified', 'is_online',
            'total_groups_joined', 'total_groups_created', 'total_contributed',
            'total_received', 'total_earned', 'defaulted_count', 'on_time_payments',
            'verification_level', 'account_age_days', 'referral_code', 'referral_count'
        )
        read_only_fields = UserBaseSerializer.Meta.read_only_fields + (
            'cover_photo', 'date_of_birth', 'gender', 'address', 'city',
            'country', 'timezone', 'currency', 'is_verified', 'is_online',
            'total_groups_joined', 'total_groups_created', 'total_contributed',
            'total_received', 'total_earned', 'defaulted_count', 'on_time_payments',
            'verification_level', 'account_age_days', 'referral_code', 'referral_count'
        )

    verification_level = serializers.SerializerMethodField()
    is_online = serializers.SerializerMethodField()
    account_age_days = serializers.SerializerMethodField()

    def get_verification_level(self, obj):
        return obj.verification_level

    def get_is_online(self, obj):
        return obj.is_online

    def get_account_age_days(self, obj):
        return obj.account_age_days


# ============================================================================
# PROFILE UPDATE SERIALIZER
# ============================================================================

class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating user profile fields.
    """
    phone = serializers.CharField(
        required=False,
        validators=[phone_regex]
    )

    class Meta:
        model = User
        fields = (
            'first_name', 'last_name', 'middle_name', 'phone',
            'profile_picture', 'cover_photo', 'date_of_birth', 'gender',
            'address', 'city', 'country', 'language', 'timezone', 'currency'
        )

    def validate_phone(self, value):
        if User.objects.filter(phone=value).exclude(id=self.instance.id).exists():
            raise serializers.ValidationError(
                _('This phone number is already in use.')
            )
        return value


# ============================================================================
# CHANGE PASSWORD SERIALIZER
# ============================================================================

class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing user password."""
    old_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'},
        validators=[validate_password]
    )
    confirm_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError(
                {'confirm_password': _('Passwords do not match.')}
            )
        return attrs


# ============================================================================
# OTP SEND SERIALIZER
# ============================================================================

class OTPSendSerializer(serializers.Serializer):
    """
    Serializer for sending OTP via email or phone.
    """
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(required=False, validators=[phone_regex])
    purpose = serializers.ChoiceField(
        choices=['registration', 'login', 'password_reset', 'phone_verification', 'email_verification', 'transaction'],
        default='login'
    )

    def validate(self, attrs):
        email = attrs.get('email')
        phone = attrs.get('phone')
        purpose = attrs.get('purpose')

        if not email and not phone:
            raise serializers.ValidationError(
                _('Either email or phone is required.')
            )

        user = None
        if email:
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                raise serializers.ValidationError(
                    {'email': _('No user found with this email.')}
                )
        elif phone:
            try:
                user = User.objects.get(phone=phone)
            except User.DoesNotExist:
                raise serializers.ValidationError(
                    {'phone': _('No user found with this phone number.')}
                )

        if user and not user.is_active:
            raise serializers.ValidationError(
                _('This account is inactive. Please contact support.')
            )

        attrs['user'] = user
        return attrs


# ============================================================================
# OTP VERIFY SERIALIZER
# ============================================================================

class OTPVerifySerializer(serializers.Serializer):
    """
    Serializer for verifying OTP and marking verification.
    """
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(required=False, validators=[phone_regex])
    otp = serializers.CharField(required=True, max_length=6)

    def validate(self, attrs):
        email = attrs.get('email')
        phone = attrs.get('phone')
        otp = attrs.get('otp')

        if not email and not phone:
            raise serializers.ValidationError(
                _('Either email or phone is required.')
            )

        user = None
        if email:
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                raise serializers.ValidationError(
                    {'email': _('No user found with this email.')}
                )
        elif phone:
            try:
                user = User.objects.get(phone=phone)
            except User.DoesNotExist:
                raise serializers.ValidationError(
                    {'phone': _('No user found with this phone number.')}
                )

        if not user.otp:
            raise serializers.ValidationError(
                _('No OTP found. Please request a new OTP.')
            )

        if user.otp != otp:
            user.otp_attempts += 1
            user.save(update_fields=['otp_attempts'])
            raise serializers.ValidationError(
                _('Invalid OTP. You have {} attempts remaining.').format(5 - user.otp_attempts)
            )

        if user.otp_attempts >= 5:
            raise serializers.ValidationError(
                _('Too many failed OTP attempts. Please request a new OTP.')
            )

        if (timezone.now() - user.otp_created_at).total_seconds() > 300:
            raise serializers.ValidationError(
                _('OTP has expired. Please request a new OTP.')
            )

        # Mark OTP as verified
        user.otp_verified = True
        user.otp = None
        user.otp_created_at = None
        user.otp_attempts = 0
        user.save(update_fields=['otp_verified', 'otp', 'otp_created_at', 'otp_attempts'])

        attrs['user'] = user
        return attrs


# ============================================================================
# PASSWORD RESET SERIALIZERS
# ============================================================================

class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for password reset request."""
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                _('No user found with this email.')
            )
        return value


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for confirming password reset with OTP."""
    email = serializers.EmailField(required=True)
    otp = serializers.CharField(required=True, max_length=6)
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        validators=[validate_password]
    )
    confirm_password = serializers.CharField(
        required=True,
        write_only=True
    )

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError(
                {'confirm_password': _('Passwords do not match.')}
            )

        try:
            user = User.objects.get(email=attrs['email'])
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {'email': _('No user found with this email.')}
            )

        # Verify OTP
        if not user.otp_verified:
            raise serializers.ValidationError(
                _('OTP not verified. Please verify your OTP first.')
            )

        # OTP is already verified, we can proceed
        attrs['user'] = user
        return attrs


# ============================================================================
# LOGOUT SERIALIZER
# ============================================================================

class LogoutSerializer(serializers.Serializer):
    """Serializer for user logout (blacklist refresh token)."""
    refresh = serializers.CharField(required=True)

    def validate_refresh(self, value):
        try:
            token = RefreshToken(value)
            token.blacklist()
        except Exception as e:
            raise serializers.ValidationError(
                _('Invalid refresh token.') + str(e)
            )
        return value


# ============================================================================
# REFRESH TOKEN SERIALIZER
# ============================================================================

class RefreshTokenSerializer(serializers.Serializer):
    """Serializer for refreshing access token."""
    refresh = serializers.CharField(required=True)

    def validate_refresh(self, value):
        try:
            token = RefreshToken(value)
            # Optionally check if token is blacklisted
            attrs = {
                'access': str(token.access_token),
                'refresh': str(token)
            }
            return attrs
        except Exception as e:
            raise serializers.ValidationError(
                _('Invalid refresh token.') + str(e)
            )


# ============================================================================
# USER LIST SERIALIZER (FOR ADMIN)
# ============================================================================

class UserListSerializer(UserBaseSerializer):
    """Serializer for listing users with admin-specific fields."""
    class Meta(UserBaseSerializer.Meta):
        fields = UserBaseSerializer.Meta.fields + (
            'is_active', 'is_suspended', 'is_locked', 'is_verified',
            'total_groups_joined', 'defaulted_count', 'on_time_payments'
        )
        read_only_fields = UserBaseSerializer.Meta.read_only_fields + (
            'is_active', 'is_suspended', 'is_locked', 'is_verified',
            'total_groups_joined', 'defaulted_count', 'on_time_payments'
        )


# ============================================================================
# USER DETAIL SERIALIZER (FOR ADMIN)
# ============================================================================

class UserDetailSerializer(serializers.ModelSerializer):
    """
    Detailed user serializer for admin view with all fields.
    """
    full_name = serializers.SerializerMethodField()
    verification_level = serializers.SerializerMethodField()
    account_age_days = serializers.SerializerMethodField()
    is_online = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = '__all__'
        read_only_fields = (
            'id', 'date_joined', 'updated_at', 'last_login', 'otp',
            'otp_created_at', 'otp_attempts', 'login_count', 'referral_code'
        )

    def get_full_name(self, obj):
        return obj.full_name

    def get_verification_level(self, obj):
        return obj.verification_level

    def get_account_age_days(self, obj):
        return obj.account_age_days

    def get_is_online(self, obj):
        return obj.is_online


# ============================================================================
# ADMIN UPDATE SERIALIZER
# ============================================================================

class AdminUserUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for admin to update user fields including sensitive ones.
    """
    phone = serializers.CharField(validators=[phone_regex], required=False)

    class Meta:
        model = User
        fields = (
            'email', 'phone', 'first_name', 'last_name', 'middle_name',
            'is_active', 'is_suspended', 'is_locked', 'is_phone_verified',
            'is_email_verified', 'is_identity_verified', 'is_verified',
            'language', 'gender', 'country', 'timezone', 'currency'
        )

    def validate_email(self, value):
        if User.objects.filter(email=value).exclude(id=self.instance.id).exists():
            raise serializers.ValidationError(
                _('This email is already in use.')
            )
        return value

    def validate_phone(self, value):
        if User.objects.filter(phone=value).exclude(id=self.instance.id).exists():
            raise serializers.ValidationError(
                _('This phone number is already in use.')
            )
        return value


# ============================================================================
# TOKEN OBTAIN SERIALIZER (JWT)
# ============================================================================

class TokenObtainSerializer(serializers.Serializer):
    """
    Serializer to obtain JWT tokens with user data.
    """
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        user = authenticate(email=attrs['email'], password=attrs['password'])
        if not user:
            raise serializers.ValidationError(
                _('Invalid credentials. Please try again.')
            )
        if not user.is_active:
            raise serializers.ValidationError(
                _('Account is inactive. Please contact support.')
            )
        if user.is_suspended:
            raise serializers.ValidationError(
                _('Account is suspended. Please contact support.')
            )
        if user.is_account_locked():
            raise serializers.ValidationError(
                _('Account is temporarily locked. Please try again later.')
            )

        refresh = RefreshToken.for_user(user)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserProfileSerializer(user).data
        }


# ============================================================================
# EMAIL VERIFICATION SERIALIZER
# ============================================================================

class EmailVerificationSerializer(serializers.Serializer):
    """Serializer for email verification."""
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                _('No user found with this email.')
            )
        return value


# ============================================================================
# REFERRAL STATS SERIALIZER
# ============================================================================

class ReferralStatsSerializer(serializers.Serializer):
    """Serializer for referral statistics."""
    referral_code = serializers.CharField(read_only=True)
    referral_count = serializers.IntegerField(read_only=True)
    referred_users = serializers.ListField(read_only=True)

    def to_representation(self, instance):
        referred_users = User.objects.filter(referred_by=instance)
        return {
            'referral_code': instance.referral_code,
            'referral_count': instance.referral_count,
            'referred_users': UserListSerializer(referred_users, many=True).data
        }