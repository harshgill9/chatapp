from django.contrib import admin

# Register your models here.
from .models import Room, Message, PrivateRoom, PrivateChatMessage, UserProfile

admin.site.register(Room)
admin.site.register(Message)
admin.site.register(PrivateRoom)
admin.site.register(PrivateChatMessage)
admin.site.register(UserProfile)