# consumers.py
import json
import asyncio
import re
import unicodedata
from collections import defaultdict
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils.text import slugify
from django.utils import timezone
from django.db.models import Q
from django.db.models import Max
from django.contrib.auth.models import User
from .models import Profile, Room, Message, PrivateRoom, PrivateChatMessage, Block

# 🟢 Track all connected users (username -> set of channels)
connected_users = defaultdict(set)


# =====================================
# ✅ BASE CONSUMER (COMMON FOR ALL)
# =====================================
class BaseConsumer(AsyncWebsocketConsumer):
    async def disconnect(self, close_code):
        user = self.scope["user"]
        if not user.is_authenticated:
            return

        username = user.username
        # group_discard may fail if room_group_name not set — wrap in try
        try:
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        except Exception:
            pass
        try:
            await self.channel_layer.group_discard("online_status_group", self.channel_name)
        except Exception:
            pass

        if self.channel_name in connected_users[username]:
            connected_users[username].discard(self.channel_name)

        await asyncio.sleep(2)

        if connected_users.get(username):
            print(f"[DISCONNECTED 🗹] {username} still active elsewhere")
            return

        # mark offline
        try:
            await self.set_user_offline(user)
            await self.broadcast_status(username, False)
        except Exception:
            pass

        print(f"[DISCONNECTED ❌] {username}")

    @database_sync_to_async
    def set_user_online(self, user):
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_online = True
        profile.last_seen = timezone.now()
        profile.save()
        print(f"[ONLINE ✅] {user.username}")

    @database_sync_to_async
    def set_user_offline(self, user):
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_online = False
        profile.last_seen = timezone.now()
        profile.save()
        print(f"[OFFLINE ❌] {user.username}")

    async def broadcast_status(self, username, is_online):
        await self.channel_layer.group_send(
            "online_status_group",
            {
                "type": "user_status",
                "username": username,
                "is_online": is_online,
            },
        )

    # -------------------------
    # Safe helper to fetch reply message text by id
    # -------------------------
    @database_sync_to_async
    def get_reply_message_text(self, reply_to_id):
        """
        Try to resolve reply_to_id (int-like) to a message content.
        Looks in PrivateChatMessage first, then Message (group). Returns None if not found/invalid.
        """
        if not reply_to_id:
            return None
        try:
            rid = int(reply_to_id)
        except (TypeError, ValueError):
            return None

        # try private messages
        try:
            pm = PrivateChatMessage.objects.filter(id=rid).first()
            if pm:
                return pm.content
        except Exception:
            pass

        # try group messages
        try:
            gm = Message.objects.filter(id=rid).first()
            if gm:
                return gm.content
        except Exception:
            pass

        return None


# =====================================
# ✅ PUBLIC CHAT CONSUMER (GROUP)
# =====================================
class ChatConsumer(BaseConsumer):
    async def connect(self):
        await self.accept()
        self.user = self.scope["user"]
        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        self.room_group_name = f"chat_{slugify(self.room_name)}"

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.channel_layer.group_add("online_status_group", self.channel_name)

        if self.user.is_authenticated:
            username = self.user.username
            connected_users[username].add(self.channel_name)
            await self.set_user_online(self.user)
            await self.broadcast_status(username, True)

        print(f"[CONNECTED ✅] {self.user.username}")

    async def disconnect(self, close_code):
        await super().disconnect(close_code)

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get("type")

        # Typing indicator
        if msg_type in ["typing", "stop_typing"]:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "typing_status",
                    "username": data.get("username"),
                    "name": data.get("name"),
                    "is_typing": msg_type == "typing",
                },
            )
            return

        # Normal chat message
        message = data.get("message")
        username = data.get("username")
        name = data.get("name")
        reply_to = data.get("reply_to", None)
        reply_name = data.get("reply_name", None)

        if not message or not message.strip():
            return

        # save and get saved id
        saved_id = await self.save_message(username, self.room_name, message, reply_to, reply_name)

        # Prepare reply_message text safely (uses BaseConsumer.get_reply_message_text)
        reply_message = None
        if reply_to:
            reply_message = await self.get_reply_message_text(reply_to)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "id": saved_id,
                "message": message,
                "username": username,
                "name": name,
                "reply_to": reply_to if reply_to else None,
                "reply_name": reply_name if reply_name else None,
                "reply_to_id": reply_to if reply_to else None,
                "reply_message": reply_message,
            },
        )

    async def chat_message(self, event):
        await self.send(json.dumps(event))

    async def typing_status(self, event):
        await self.send(json.dumps({
            "type": "typing_status",
            "username": event["username"],
            "name": event.get("name"),
            "is_typing": event["is_typing"],
        }))

    async def user_status(self, event):
        await self.send(json.dumps(event))

    @database_sync_to_async
    def save_message(self, username, room_name, message, reply_to=None, reply_name=None):
        user = User.objects.get(username=username)
        room, _ = Room.objects.get_or_create(
            slug=slugify(room_name),
            defaults={"name": room_name, "created_by": user}
        )

        msg = Message.objects.create(
            user=user,
            room=room,
            content=message,
            reply_to=reply_to,
            reply_name=reply_name
        )
        return msg.id


# =====================================
# ✅ PRIVATE CHAT CONSUMER (1-to-1)
# =====================================
class PrivateChatConsumer(BaseConsumer):
    async def connect(self):
        await self.accept()
        self.user = self.scope["user"]

        raw_room_slug = self.scope["url_route"]["kwargs"]["room_slug"]
        users = sorted(raw_room_slug.split("__"))
        combined_slug = f"{users[0]}__{users[1]}"

        safe_slug = unicodedata.normalize("NFKD", combined_slug).encode("ascii", "ignore").decode("ascii")
        safe_slug = re.sub(r"[^A-Za-z0-9_.-]", "_", safe_slug)[:90] or "default_private_room"

        self.room_slug = safe_slug
        self.room_group_name = f"private_chat_{safe_slug}"

        # BLOCK CHECK (MOST IMPORTANT)
        u = self.room_slug.split("__")
        other_username = u[0] if u[1] == self.user.username else u[1]

        if await self.is_blocked(self.user.username, other_username):
            await self.send(json.dumps({
                "type": "blocked",
                "message": "You cannot chat with this user."
            }))
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        
        # ✅ personal sidebar group
        self.user_group_name = f"user_{self.user.username}"

        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )

        # DO NOT add them into online group if blocked
        await self.channel_layer.group_add("online_status_group", self.channel_name)

        if self.user.is_authenticated:
            username = self.user.username
            connected_users[username].add(self.channel_name)

            # Mark them online
            await self.set_user_online(self.user)
            await self.broadcast_status(username, True)

        print(f"[PRIVATE CONNECT] {self.user.username}")
        # ✅ sirf tab read mark karo jab user same room open kare

        # if self.user.username in self.room_slug:
            # await self.mark_messages_as_read()

    async def disconnect(self, close_code):

        await self.channel_layer.group_discard(
            self.user_group_name,
            self.channel_name
        )

        await super().disconnect(close_code)

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get("type")
    
        # Extract other username
        users = self.room_slug.split("__")
        other_username = users[0] if users[1] == self.user.username else users[1]
    
        # If blocked — stop ANYTHING
        if await self.is_blocked(self.user.username, other_username):
            await self.send(json.dumps({
                "type": "blocked",
                "message": f"You blocked {other_username}."
            }))
            return 
    
        # -------------------------------
        # TYPING INDICATOR
        # -------------------------------
        
        if msg_type == "typing":
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "typing_status",
                    "username": self.user.username,
                    "name": self.user.first_name or self.user.username,
                    "is_typing": True,
                },
            )
            return
        
    
        if msg_type == "stop_typing":
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "typing_status",
                    "username": self.user.username,
                    "name": self.user.first_name or self.user.username,
                    "is_typing": False,
                },
            )
            return
    
        # -------------------------------
        # DELETE MESSAGE
        # -------------------------------
        if msg_type == "delete_message":
            msg_id = data.get("msg_id")
            if await self.delete_message_from_db(msg_id, self.user):
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {"type": "message_deleted", "msg_id": msg_id},
                )
            return
    
        # -------------------------------
        # NORMAL CHAT MESSAGE
        # -------------------------------
        if msg_type in ["chat", "chat_message"]:
            message = data.get("message")
            if not message or not message.strip():
                return
    
            reply_to = data.get("reply_to")
            reply_name = data.get("reply_name")
    
            saved_id = await self.save_message(
                self.user.username,
                self.room_slug,
                message,
                reply_to,
                reply_name
            )
    
            reply_message = await self.get_reply_message_text(reply_to) if reply_to else None
    
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "id": saved_id,
                    "message": message,
                    "username": self.user.username,
                    "receiver": other_username,
                    "name": self.user.first_name or self.user.username,
                    "reply_to": reply_to,
                    "reply_name": reply_name,
                    "reply_message": reply_message,
                    "unread_count": await self.get_unread_count(self.user.username, other_username),
                },
            )

            # ✅ realtime sidebar update sender
            await self.channel_layer.group_send(
                f"user_{self.user.username}",
                {
                    "type": "sidebar_update",
                    "message": message,
                    "username": self.user.username,
                    "receiver": other_username,
                }
            )

            # ✅ realtime sidebar update receiver
            await self.channel_layer.group_send(
                f"user_{other_username}",
                {
                    "type": "sidebar_update",
                    "message": message,
                    "username": self.user.username,
                    "receiver": other_username,
                    # "clear_unread": True,  # tell receiver to clear unread count for this chat
                }
            )
            return
        
        if msg_type == "opened_chat":
        
            opened_chat_user = data.get("opened_chat_user")

            if opened_chat_user:
            
                users = sorted([
                    self.user.username,
                    opened_chat_user
                ])

                room_slug = f"{users[0]}__{users[1]}"

                await self.mark_specific_chat_as_read(
                    room_slug,
                    opened_chat_user
                )

            return   
        
    async def sidebar_update(self, event):

        await self.send(text_data=json.dumps({
            "type": "sidebar_update",
            "message": event["message"],
            "username": event["username"],
            "receiver": event["receiver"],
            "clear_unread": event.get("clear_unread", False),
        }))   
        return

    async def chat_message(self, event):
        users = self.room_slug.split("__")
        other_username = users[0] if users[1] == self.user.username else users[1]

        if await self.is_blocked(self.user.username, other_username):
            return  # ❌ Don't send message

        await self.send(json.dumps(event))

    async def typing_status(self, event):
        users = self.room_slug.split("__")
        other_username = users[0] if users[1] == self.user.username else users[1]

        if await self.is_blocked(self.user.username, other_username):
            return  # ❌ No typing updates

        if event["username"] == self.user.username:
            return

        await self.send(json.dumps(event))


    async def user_status(self, event):
        users = self.room_slug.split("__")
        other_username = users[0] if users[1] == self.user.username else users[1]

        if await self.is_blocked(self.user.username, other_username):
            return  # ❌ No online/offline updates

        await self.send(json.dumps(event))

    @database_sync_to_async
    def save_message(self, sender_username, room_slug, message, reply_to=None, reply_name=None):
        try:
            user = User.objects.get(username=sender_username)
            users = sorted(room_slug.split("__"))
            user1 = User.objects.get(username=users[0])
            user2 = User.objects.get(username=users[1])
            room = PrivateRoom.get_or_create_room(user1, user2)

            receiver = user2 if user == user1 else user1

            msg = PrivateChatMessage.objects.create(
                sender=user,
                room=room,
                content=message,
                reply_to=reply_to,
                reply_name=reply_name,
                is_read=False,
                receiver=receiver
            )
            return msg.id
        except Exception as e:
            print(f"[PRIVATE MESSAGE SAVE ERROR]: {e}")
            return None
        
    @database_sync_to_async
    def get_unread_count(self, sender_username, receiver_username):
    
        return PrivateChatMessage.objects.filter(
            sender__username=sender_username,
            receiver__username=receiver_username,
            is_read=False
        ).count()
    
    @database_sync_to_async
    def mark_messages_as_read_for_user(self, username):

        try:
            user = User.objects.get(username=username)

            PrivateChatMessage.objects.filter(
                room__room_slug=self.room_slug,
                receiver=user,
                is_read=False
            ).update(is_read=True)

        except Exception as e:
            print("READ ERROR:", e)

    @database_sync_to_async
    def mark_specific_chat_as_read(self, room_slug, other_username):
    
        try:
        
            other_user = User.objects.get(
                username=other_username
            )
    
            room = PrivateRoom.objects.filter(
                room_slug=room_slug
            ).first()
    
            if not room:
                return
    
            PrivateChatMessage.objects.filter(
                room=room,
                sender=other_user,
                receiver=self.user,
                is_read=False
            ).update(is_read=True)
    
        except Exception as e:
            print("READ ERROR:", e)        
    

    @database_sync_to_async
    def mark_messages_as_read(self):

        try:

            users = self.room_slug.split("__")

            other_username = (
                users[0]
                if users[1] == self.user.username
                else users[1]
            )

            other_user = User.objects.get(
                username=other_username
            )

            room = PrivateRoom.objects.filter(
                room_slug=self.room_slug
            ).first()

            if not room:
                return

            # ✅ sirf current open chat ke unread remove
            PrivateChatMessage.objects.filter(
                room=room,
                sender=other_user,
                receiver=self.user,
                is_read=False
            ).update(is_read=True)

        except Exception as e:
            print("READ ERROR:", e)
        

    @database_sync_to_async
    def delete_message_from_db(self, msg_id, user):
        try:
            msg = PrivateChatMessage.objects.filter(id=msg_id).first()
            if msg:
                # Mark message as deleted (for that user)
                msg.is_deleted = True
                msg.deleted_by.add(user)
                msg.save()
                print(f"[MESSAGE DELETED ✅] {msg_id} by {user.username}")
                return True
            else:
                print(f"[DELETE FAILED 🚫] Message not found")
                return False
        except Exception as e:
            print(f"[DELETE ERROR ❌] {e}")
            return False
        
    async def message_deleted(self, event):
        """
        Broadcast delete event to all connected users in the room
        so the message disappears instantly from both sides.
        """
        await self.send(text_data=json.dumps({
            "type": "delete_message",
            "msg_id": event["msg_id"],
        }))
    

    @database_sync_to_async
    def is_blocked(self, viewer_username, other_username):
        """
        viewer_username = jis bande ki screen chal rahi hai
        other_username = jis se chat ho rahi hai

        If viewer has blocked "other" → don't show their messages.
        If other has blocked viewer → don't allow viewer to send messages.
        """
        try:
            viewer = User.objects.get(username=viewer_username)
            other = User.objects.get(username=other_username)

            # viewer ne other ko block kiya?
            blocked_by_viewer = Block.objects.filter(blocker=viewer, blocked=other).exists()

            # other ne viewer ko block kiya?
            blocked_by_other = Block.objects.filter(blocker=other, blocked=viewer).exists()

            return blocked_by_viewer or blocked_by_other
        except:
            return False


    @database_sync_to_async
    def forward_message_to_user(self, sender_username, msg_id, target_username):
        """
        Fetch original message text and create a new PrivateChatMessage for the target user.
        """
        try:
            sender = User.objects.get(username=sender_username)
            target = User.objects.get(username=target_username)
    
            # Get the original message
            original = PrivateChatMessage.objects.filter(id=msg_id).first()
            if not original:
                print(f"[FORWARD FAIL ❌] Original message not found")
                return False
    
            # Get or create room between sender and target
            users = sorted([sender.username, target.username])
            room = PrivateRoom.get_or_create_room(
                User.objects.get(username=users[0]),
                User.objects.get(username=users[1])
            )
    
            # Save forwarded message
            new_msg = PrivateChatMessage.objects.create(
                sender=sender,
                room=room,
                content=f"📨 Forwarded: {original.content}"
            )
            print(f"[FORWARD ✅] {sender_username} → {target_username}: {original.content}")
            return True
    
        except Exception as e:
            print(f"[FORWARD ERROR ❌]: {e}")
            return False
    