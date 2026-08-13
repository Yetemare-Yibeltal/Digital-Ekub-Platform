from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum, Count, Q
from celery import shared_task
from .models import User


@shared_task
def cleanup_expired_otps():
    """
    Delete expired OTPs and reset OTP attempts.
    Runs daily to clean up stale OTP data.
    """
    expiry_time = timezone.now() - timedelta(minutes=5)
    users = User.objects.filter(
        otp_created_at__lt=expiry_time,
        otp__isnull=False
    )
    count = users.count()
    users.update(
        otp=None,
        otp_created_at=None,
        otp_attempts=0,
        otp_verified=False
    )
    return f"Cleaned up {count} expired OTPs"


@shared_task
def update_user_statistics(user_id):
    """
    Update user statistics including groups joined, contributions, and payouts.
    Runs after significant user actions.
    """
    from apps.groups.models import GroupMember
    from apps.contributions.models import Contribution
    from apps.payments.models import Payout

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return f"User {user_id} not found"

    groups_joined = GroupMember.objects.filter(user=user, is_active=True).count()
    groups_created = user.groups_created.count()
    total_contributed = Contribution.objects.filter(
        user=user,
        status='paid'
    ).aggregate(total=Sum('amount'))['total'] or 0
    total_received = Payout.objects.filter(
        user=user,
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or 0
    on_time = Contribution.objects.filter(
        user=user,
        status='paid',
        paid_date__lte=models.F('due_date')
    ).count()
    defaulted = Contribution.objects.filter(
        user=user,
        status='overdue'
    ).count()

    user.total_groups_joined = groups_joined
    user.total_groups_created = groups_created
    user.total_contributed = total_contributed
    user.total_received = total_received
    user.on_time_payments = on_time
    user.defaulted_count = defaulted
    user.save(update_fields=[
        'total_groups_joined', 'total_groups_created',
        'total_contributed', 'total_received',
        'on_time_payments', 'defaulted_count'
    ])
    return f"Updated statistics for user {user.email}"


@shared_task
def process_referral_bonus(referrer_id, referee_id):
    """
    Give referral bonus to referrer when a referred user becomes active.
    """
    try:
        referrer = User.objects.get(id=referrer_id)
        referee = User.objects.get(id=referee_id)
    except User.DoesNotExist:
        return "User not found"

    if referee.is_active and referee.is_phone_verified:
        referrer.referral_count += 1
        referrer.reputation_score += 10
        referrer.save(update_fields=['referral_count', 'reputation_score'])
        return f"Bonus awarded to {referrer.email} for referring {referee.email}"
    return "Referee not yet active or verified"


@shared_task
def unlock_locked_accounts():
    """
    Unlock user accounts that have passed their lock duration.
    Runs every 5 minutes.
    """
    now = timezone.now()
    users = User.objects.filter(
        is_locked=True,
        locked_until__lte=now
    )
    count = users.count()
    for user in users:
        user.unlock_account()
    return f"Unlocked {count} accounts"


@shared_task
def suspend_inactive_users():
    """
    Automatically suspend users inactive for 90 days.
    Runs daily.
    """
    inactive_threshold = timezone.now() - timedelta(days=90)
    users = User.objects.filter(
        is_active=True,
        is_suspended=False,
        last_activity__lt=inactive_threshold
    )
    count = users.count()
    users.update(
        is_suspended=True,
        is_active=False,
        suspended_at=timezone.now(),
        suspension_reason="Automatically suspended due to 90 days of inactivity"
    )
    return f"Suspended {count} inactive users"


@shared_task
def soft_delete_inactive_users():
    """
    Soft delete users inactive for 365 days and already suspended.
    Runs monthly.
    """
    delete_threshold = timezone.now() - timedelta(days=365)
    users = User.objects.filter(
        is_suspended=True,
        is_active=False,
        deleted_at__isnull=True,
        last_activity__lt=delete_threshold
    )
    count = users.count()
    for user in users:
        user.soft_delete(reason="Automatically deleted after 365 days of inactivity")
    return f"Soft deleted {count} long-inactive users"


@shared_task
def update_reputation_scores():
    """
    Recalculate reputation scores for all users based on their activity.
    Runs weekly.
    """
    from apps.groups.models import GroupMember
    from apps.contributions.models import Contribution

    users = User.objects.filter(is_active=True)
    updated = 0
    for user in users:
        on_time = Contribution.objects.filter(
            user=user, status='paid', paid_date__lte=models.F('due_date')
        ).count()
        defaulted = Contribution.objects.filter(user=user, status='overdue').count()
        groups_active = GroupMember.objects.filter(user=user, is_active=True).count()
        score = 50
        score += on_time * 2
        score -= defaulted * 5
        score += groups_active * 1
        if user.is_phone_verified:
            score += 10
        if user.is_email_verified:
            score += 5
        if user.is_identity_verified:
            score += 15
        user.reputation_score = max(0, min(100, score))
        user.save(update_fields=['reputation_score'])
        updated += 1
    return f"Updated reputation scores for {updated} users"


@shared_task
def process_defaulted_users():
    """
    Reduce reputation for users with overdue contributions.
    Runs daily.
    """
    overdue = timezone.now() - timedelta(days=7)
    users = User.objects.filter(
        contributions__status='overdue',
        contributions__due_date__lt=overdue
    ).distinct()
    count = 0
    for user in users:
        user.reputation_score = max(0, user.reputation_score - 2)
        user.save(update_fields=['reputation_score'])
        count += 1
    return f"Reduced reputation for {count} defaulting users"


@shared_task
def send_welcome_email(user_id):
    """
    Send welcome email to new user.
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return "User not found"
    from apps.notifications.services import send_email
    send_email(
        to_email=user.email,
        subject="Welcome to Digital Ekub Platform!",
        template_name="welcome.html",
        context={
            'user': user,
            'referral_code': user.referral_code,
            'support_email': 'support@ekub-platform.com'
        }
    )
    return f"Welcome email sent to {user.email}"