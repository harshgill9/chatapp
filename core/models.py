from django.db import models
from django.contrib.auth.models import User
from django.dispatch import receiver
from django.utils.text import slugify
from django.db.models.signals import post_save
from django.utils.timezone import now
from django.contrib.auth.hashers import make_password, check_password

class Room(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    members = models.ManyToManyField(User, related_name='group_members', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    image = models.ImageField(upload_to='room_images/', blank=True, null=True)
    participants = models.ManyToManyField(User, related_name="chat_rooms", blank=True)
    description = models.TextField(blank=True, null=True)
    is_private = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)


    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Message(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='messages')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    sender = models.ForeignKey(User, related_name='sent_messages', on_delete=models.CASCADE, null=True, blank=True)
    receiver = models.ForeignKey(User, related_name='received_messages', on_delete=models.CASCADE, null=True, blank=True)
    content = models.TextField()
    reply_to = models.TextField(null=True, blank=True)
    reply_name = models.CharField(max_length=255, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_by = models.ManyToManyField(User, blank=True, related_name="deleted_messages")
    is_forwarded = models.BooleanField(default=False)
    original_sender = models.CharField(max_length=255, blank=True, null=True)
    hidden_by = models.ManyToManyField(User, blank=True, related_name="hidden_messages")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # read_by = models.ManyToManyField(User, blank=True, related_name="read_messages")

    def __str__(self):    
        sender_name = self.sender.username if self.sender else self.user.username
        return f'{sender_name} in {self.room.name}: {self.content[:30]}'

class PrivateRoom(models.Model):
    room_slug = models.SlugField(unique=True, blank=True)
    user1 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='private_rooms_1', null=True, blank=True)
    user2 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='private_rooms_2', null=True, blank=True)

    class Meta:
        unique_together = ('user1', 'user2')

    def generate_room_slug(self):
        usernames = sorted([self.user1.username, self.user2.username])
        return f"{usernames[0]}__{usernames[1]}"

    def save(self, *args, **kwargs):
        # Order users by username to maintain consistency
        if self.user1.id > self.user2.id:
            self.user1, self.user2 = self.user2, self.user1

        if not self.room_slug:
            self.room_slug = self.generate_room_slug()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user1.username} - {self.user2.username}"
    
    @classmethod
    def get_or_create_room(cls, user_a, user_b):
        user1, user2 = sorted([user_a, user_b], key=lambda u: u.id)
        room, created = cls.objects.get_or_create(user1=user1, user2=user2)
        return room
    

class PrivateChatMessage(models.Model):
    room = models.ForeignKey(PrivateRoom, related_name='messages', on_delete=models.CASCADE)
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_private_messages', null=True, blank=True)
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_private_messages', null=True, blank=True)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_by = models.ManyToManyField(User, related_name='deleted_private_messages', blank=True)
    reply_to = models.TextField(null=True, blank=True)
    reply_name = models.CharField(max_length=255, null=True, blank=True)
    reply_to_id = models.PositiveIntegerField(null=True, blank=True)
    is_forwarded = models.BooleanField(default=False)
    original_sender = models.CharField(max_length=255, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    # read_by = models.ManyToManyField(User, blank=True, related_name="read_private_messages")

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.sender.username} → {self.room.room_slug}: {self.content[:30]}"

class GroupJoinRequest(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='join_requests')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=10,
        choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('rejected', 'Rejected')],
        default='pending'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('room', 'user')  # Prevent duplicate requests

    def __str__(self):
        return f"{self.user.username} → {self.room.name} ({self.status})"
    
#  Profile with privacy settings
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    profile_pic = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    image = models.ImageField(upload_to='profiles/', blank=True, null=True)
    phone_number = models.CharField(max_length=10, blank=True, null=True)
    about = models.TextField(blank=True, null=True)
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)
    blocked_users = models.ManyToManyField(User, related_name='blocked_by_profile', blank=True)
    app_lock_enabled = models.BooleanField(default=False)
    app_lock_password = models.CharField(max_length=128, blank=True, null=True)
    app_lock_password_hash = models.CharField(max_length=128, blank=True, null=True)
    chat_wallpaper = models.ImageField(upload_to='chat_wallpapers/', null=True, blank=True)
    chat_wallpaper_default = models.CharField(max_length=255, null=True, blank=True)
    mute_notifications = models.BooleanField(default=False)
    
    CHAT_THEME_CHOICES = [
        ('default', 'Default'),
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('gradient', 'Gradient'),
    ]

    chat_theme = models.CharField(
        max_length=20,
        choices=CHAT_THEME_CHOICES,
        default='default'
    )

    # 📸 Media Upload Quality
    MEDIA_QUALITY_CHOICES = [
        ('high', 'High Quality'),
        ('standard', 'Standard Quality'),
    ]
    media_upload_quality = models.CharField(
        max_length=10, choices=MEDIA_QUALITY_CHOICES, default='standard'
    )

    # 📥 Auto Download Options
    auto_download_photos = models.BooleanField(default=True)
    auto_download_videos = models.BooleanField(default=False)
    auto_download_audio = models.BooleanField(default=False)
    auto_download_documents = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username
    
    PHOTO_PRIVACY_CHOICES = [
        ('everyone', 'Everyone'),
        ('my_contacts', 'My Contacts'),
        ('my_contacts_except', 'My Contacts Except'),
        ('nobody', 'Nobody'),
    ]

    photo_privacy = models.CharField(
        max_length=30,
        choices=PHOTO_PRIVACY_CHOICES,
        default='everyone'
    )

    status_privacy = models.CharField(max_length=50, default='everyone')
    read_receipts_enabled = models.BooleanField(default=True)
    default_message_timer = models.IntegerField(default=0)  # in minutes
    block_unknowns = models.BooleanField(default=False)

    group_privacy = models.CharField(
        max_length=30,
        choices=[
            ('everyone', 'Everyone'),
            ('contacts', 'My Contacts'),
            ('contacts_except', 'My Contacts Except')
        ],
        default='everyone'
    )

    TIMER_CHOICES = [
        (0, 'Off'),
        (1, '1 minute'),
        (5, '5 minutes'),
        (10, '10 minutes'),
        (60, '1 hour'),
        (1440, '1 day'),
    ]

    def set_app_lock_password(self, raw_password):
        self.app_lock_password = make_password(raw_password)
        self.save()

    def check_app_lock_password(self, raw_password):
        return check_password(raw_password, self.app_lock_password)
    
    def __str__(self):
        return f"{self.user.username}'s Profile"

def get_profile(self):
    profile, _ = Profile.objects.get_or_create(user=self)
    return profile

User.add_to_class('profile', property(get_profile))

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
    else:
        if hasattr(instance, 'profile'):
            instance.profile.save()

# ChatMessage for generic chat (public/private)
class ChatMessage(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='group_sent_messages', null=True, blank=True)
    room_name = models.CharField(max_length=255)  # can be private or public room slug/name
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.sender.username}: {self.message[:20]}'

class Block(models.Model):
    blocker = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocking')
    blocked = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocked_by')
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('blocker', 'blocked')  # Prevent duplicates

    def __str__(self):
        return f"{self.blocker} blocked {self.blocked}"


