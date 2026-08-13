import logging
from django.db.models.signals import post_save, pre_save, pre_delete, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.core.cache import cache
from .models import User
from .tasks import update_user_statistics, send_welcome_email

logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def user_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle post-save events for User model.
    - Generate referral code for new users
    - Send welcome email
    - Update user statistics
    - Clear cached user data
    """
    if created:
        if not instance.referral_code:
            instance.referral_code = instance.generate_referral_code()
            instance.save(update_fields=['referral_code'])
            logger.info(f"Generated referral code for new user: {instance.email}")

        send_welcome_email.delay(instance.id)
        logger.info(f"Queued welcome email for: {instance.email}")

        if instance.referred_by:
            from .tasks import process_referral_bonus
            process_referral_bonus.delay(instance.referred_by.id, instance.id)
            logger.info(f"Queued referral bonus for: {instance.referred_by.email}")

    update_user_statistics.delay(instance.id)

    # Clear cache
    cache.delete(f'user_{instance.id}')
    cache.delete(f'user_profile_{instance.id}')
    logger.debug(f"Cleared cache for user: {instance.id}")


@receiver(pre_save, sender=User)
def user_pre_save_handler(sender, instance, **kwargs):
    """
    Handle pre-save events for User model.
    - Reset verification if email or phone changes
    - Log changes for audit
    - Prevent deactivation of superuser
    - Set default values
    """
    if instance.pk:
        try:
            old = User.objects.get(pk=instance.pk)

            if old.email != instance.email:
                instance.is_email_verified = False
                logger.info(f"Email changed for user {instance.id}, reset email verification")

            if old.phone != instance.phone:
                instance.is_phone_verified = False
                logger.info(f"Phone changed for user {instance.id}, reset phone verification")

            if old.is_superuser and not instance.is_superuser:
                logger.warning(f"Attempted to remove superuser status from user {instance.id}")
                raise ValueError("Cannot remove superuser status")

            if old.is_active and not instance.is_active and not instance.deleted_at:
                logger.info(f"User {instance.id} deactivated without soft delete")

        except User.DoesNotExist:
            pass

    if not instance.referral_code:
        instance.referral_code = instance.generate_referral_code()

    if not instance.language:
        instance.language = 'en'

    if not instance.timezone:
        instance.timezone = 'Africa/Addis_Ababa'

    if not instance.currency:
        instance.currency = 'ETB'


@receiver(pre_delete, sender=User)
def user_pre_delete_handler(sender, instance, **kwargs):
    """
    Prevent hard delete of User model.
    Enforce soft delete instead.
    """
    if not instance.is_deleted():
        instance.soft_delete(reason="Deleted via admin")
        logger.warning(f"User {instance.id} was hard deleted! Using soft delete instead.")
        raise Exception("Use soft_delete() instead of delete() for User model")


@receiver(post_delete, sender=User)
def user_post_delete_handler(sender, instance, **kwargs):
    """
    Clean up after user is deleted.
    - Clear cache
    - Remove related data
    """
    cache.delete(f'user_{instance.id}')
    cache.delete(f'user_profile_{instance.id}')
    cache.delete(f'user_stats_{instance.id}')
    logger.info(f"Cleaned up cache for deleted user: {instance.id}")


@receiver(post_save, sender=User)
def user_verification_complete_handler(sender, instance, created, **kwargs):
    """
    Handle verification complete event.
    - Update reputation score
    - Log verification completion
    """
    if not created:
        if instance.is_phone_verified and instance.is_email_verified:
            if not instance.is_verified:
                instance.is_verified = True
                instance.save(update_fields=['is_verified'])
                logger.info(f"User {instance.id} fully verified")

        if instance.is_identity_verified and not instance.identity_verification_date:
            instance.identity_verification_date = timezone.now()
            instance.is_verified = True
            instance.reputation_score = min(100, instance.reputation_score + 15)
            instance.save(update_fields=['identity_verification_date', 'is_verified', 'reputation_score'])
            logger.info(f"User {instance.id} identity verified")


@receiver(post_save, sender=User)
def user_account_status_handler(sender, instance, created, **kwargs):
    """
    Handle account status changes.
    - Send notifications on suspension/unsuspension
    - Log account status changes
    """
    if not created:
        try:
            old = User.objects.get(pk=instance.pk)

            if old.is_suspended != instance.is_suspended:
                if instance.is_suspended:
                    logger.warning(f"User {instance.id} suspended at {instance.suspended_at}")
                else:
                    logger.info(f"User {instance.id} unsuspended")

            if old.is_locked != instance.is_locked:
                if instance.is_locked:
                    logger.warning(f"User {instance.id} locked until {instance.locked_until}")
                else:
                    logger.info(f"User {instance.id} unlocked")

            if old.is_active != instance.is_active and not instance.is_suspended:
                logger.info(f"User {instance.id} active status changed to {instance.is_active}")

        except User.DoesNotExist:
            pass


@receiver(post_save, sender=User)
def user_reputation_update_handler(sender, instance, created, **kwargs):
    """
    Handle reputation score changes.
    - Cache reputation score
    - Log significant reputation changes
    """
    if not created:
        try:
            old = User.objects.get(pk=instance.pk)
            if old.reputation_score != instance.reputation_score:
                diff = instance.reputation_score - old.reputation_score
                if abs(diff) >= 10:
                    logger.info(f"User {instance.id} reputation changed by {diff} points")
                cache.set(f'user_reputation_{instance.id}', instance.reputation_score, timeout=3600)
        except User.DoesNotExist:
            pass


@receiver(post_save, sender=User)
def user_activity_handler(sender, instance, created, **kwargs):
    """
    Track user activity and update related statistics.
    """
    if not created:
        try:
            old = User.objects.get(pk=instance.pk)
            if old.last_activity != instance.last_activity:
                cache.set(f'user_last_active_{instance.id}', instance.last_activity, timeout=300)
                logger.debug(f"User {instance.id} activity updated to {instance.last_activity}")
        except User.DoesNotExist:
            pass