# core/routing.py

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Public room chat WebSocket
    re_path(r'ws/chat/(?P<room_name>[\w\-]+)/$', consumers.ChatConsumer.as_asgi()),

    # Private chat WebSocket
    re_path(r'ws/private/(?P<room_slug>[\w\-@\.]+)/$', consumers.PrivateChatConsumer.as_asgi()),
]
