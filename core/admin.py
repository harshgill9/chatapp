from django.contrib import admin
from django.contrib.auth.models import User
from .models import Room, Message, PrivateRoom, PrivateChatMessage, Profile

# Profile model ke liye proper admin class
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'status_privacy', 'photo_privacy', 'group_privacy')
    filter_horizontal = ('blocked_users',)  # Ye zaroori hai for proper UI

admin.site.unregister(User)

# CustomUserAdmin agar chahiye to basic hi rakh lo
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'first_name', 'is_staff')

admin.site.register(User, CustomUserAdmin)
admin.site.register(Profile, ProfileAdmin)

admin.site.register(Room)
admin.site.register(Message)
admin.site.register(PrivateRoom)
admin.site.register(PrivateChatMessage)
# admin.site.register(UserProfile)
