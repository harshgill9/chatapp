from django.utils.timezone import now
from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.utils import timezone
from .models import Profile

# Create profile when user is created
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)

# Save profile when user is saved
@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()  # ✅ FIXED: was userprofile

# Set user online on login
@receiver(user_logged_in)
def set_user_online(sender, request, user, **kwargs):
    profile = Profile.objects.get(user=user)
    profile.is_online = True
    profile.last_seen = timezone.now()
    profile.save()
    print(f"[LOGIN ONLINE ✅] {user.username}")

# Set user offline on logout
@receiver(user_logged_out)
def set_user_offline(sender, request, user, **kwargs):
    profile = Profile.objects.get(user=user)
    profile.is_online = False
    profile.last_seen = timezone.now()
    profile.save()
    print(f"[LOGOUT OFFLINE ❌] {user.username}")

@receiver(user_logged_out)
def update_last_seen(sender, request, user, **kwargs):
    if user.is_authenticated:
        profile = Profile.objects.get(user=user)
        profile.last_seen = now()
        profile.save()