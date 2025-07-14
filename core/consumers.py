import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils.text import slugify
from django.contrib.auth.models import User
from .models import UserProfile, ChatMessage, Room, Message


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if self.scope["user"].is_authenticated:
            await self.set_user_online(self.scope["user"])

        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        safe_room_name = slugify(self.room_name)
        self.room_group_name = f'chat_{safe_room_name}'

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': f'{self.scope["user"].first_name} joined the chat.',
                'username': 'System',
                'name': 'System'
            }
        )

    async def disconnect(self, close_code):
        if self.scope["user"].is_authenticated:
            await self.set_user_offline(self.scope["user"])

        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': f'{self.scope["user"].first_name} left the chat.',
                'username': 'System',
                'name': 'System'
            }
        )

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get('type', 'chat')

        if msg_type == 'typing':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'show_typing',
                    'username': data['username'],
                    'name': data['name'],
                    # 'message': data['message']
                }
            )
            return

        elif msg_type == 'stop_typing':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'hide_typing',
                    'username': data['username']
                }
            )
            return

        message = data.get('message')
        username = data.get('username')
        name = data.get('name', '')

        if not message or not message.strip():
            return

        await self.save_message(username, self.room_name, message)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message,
                'username': username,
                'name': data['name']
            }
        )

    async def show_typing(self, event):
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'username': event['username'],
            'name': event['name']
        }))

    async def hide_typing(self, event):
        await self.send(text_data=json.dumps({
            'type': 'stop_typing',
            'username': event['username']
        }))

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'message': event['message'],
            'username': event['username'],
            'name': event['name']
        }))

    @database_sync_to_async
    def set_user_online(self, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.is_online = True
        profile.save()

    @database_sync_to_async
    def set_user_offline(self, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.is_online = False
        profile.save()

    @database_sync_to_async
    def save_message(self, username, room_slug, message):
        user = User.objects.get(username=username)
        room = Room.objects.get(slug=room_slug)
        Message.objects.create(user=user, room=room, content=message)

class PrivateChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_slug = self.scope['url_route']['kwargs']['room_slug']
        self.room_group_name = f"private_chat_{self.room_slug}"

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get('type', 'chat')

        if msg_type == 'typing':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'show_typing',
                    'username': data['username'],
                    'name': data['name']
                }
            )
            return

        elif msg_type == 'stop_typing':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'hide_typing',
                    'username': data['username']
                }
            )
            return

        message = data.get('message')
        username = data.get('username')
        name = data.get('name', '')
        if not message or not message.strip():
            return

        sender = self.scope["user"]

        await self.save_message(sender.username, self.room_slug, message)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "message": message,
                "username": sender.username,
                "name": sender.first_name or sender.username,
            }
        )

    async def show_typing(self, event):
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'username': event['username'],
            'name': event['name']
        }))

    async def hide_typing(self, event):
        await self.send(text_data=json.dumps({
            'type': 'stop_typing',
            'username': event['username']
        }))

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            "message": event["message"],
            "username": event["username"],
            "name": event["name"],
        }))

    async def send_system_message(self, message):
        await self.send(text_data=json.dumps({
            "message": message,
            "username": "System",
            "name": "System",
        }))

    @database_sync_to_async
    def save_message(self, sender_username, room_slug, message):
        from django.contrib.auth import get_user_model
        from .models import PrivateChatMessage, PrivateRoom

        User = get_user_model()
        try:
            sender = User.objects.get(username=sender_username)
            room = PrivateRoom.objects.get(room_slug=room_slug)
            PrivateChatMessage.objects.create(sender=sender, room=room, content=message)
        except Exception as e:
            print("Error saving private message:", e)