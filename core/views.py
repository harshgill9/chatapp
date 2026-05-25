from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import (authenticate, login, logout, update_session_auth_hash, get_user_model)
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q, Count, F, OuterRef, Subquery
from django.urls import reverse
from django.db.models import Max
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django.http import HttpResponse, JsonResponse
from django.utils.text import slugify
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from django.contrib.auth.forms import PasswordChangeForm
from .forms import SearchForm, ProfilePicForm, ProfileUpdateForm, RoomImageForm
from .models import Profile, Room as Group, Message, PrivateRoom, PrivateChatMessage, ChatMessage, GroupJoinRequest, Room
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from core import models
from django.db.models.functions import Coalesce
from django.db.models import Value, IntegerField, CharField

import re
import unicodedata
import json
import traceback

CustomUser = get_user_model()

def is_admin(user):
    return user.is_staff or user.is_superuser

@login_required
@user_passes_test(is_admin)
def chat_room_admin(request, room_name):
    room = get_object_or_404(Room, slug=room_name)
    messages = Message.objects.filter(room=room, is_deleted=False).order_by('timestamp')
    context = {
        "room": room,
        "messages": messages
    }
    return render(request, "chat_admin.html", context)

@login_required
@user_passes_test(is_admin)
def delete_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    username = user.username
    user.delete()
    messages.success(request, f"User '{username}' deleted successfully.")
    return redirect("admin_dashboard")

@staff_member_required
def admin_dashboard(request):
    users = User.objects.all()
    rooms = Room.objects.all()
    messages_list = Message.objects.order_by('-timestamp')[:50]
    return render(request, 'admin_dashboard.html', {
        'users': users,
        'rooms': rooms,
        'messages': messages_list
    })

def get_room_messages(request, slug):
    try:
        room = Room.objects.get(slug=slug)
        messages = room.messages.order_by('timestamp')  # related_name='messages'
        data = {
            "messages": [
                {
                    "id": msg.id,
                    "user": msg.user.username,
                    "room_name": room.name,
                    "content": msg.content,
                    "timestamp": msg.timestamp.strftime("%b %d, %H:%M"),
                } for msg in messages
            ]
        }
        return JsonResponse(data)
    except Room.DoesNotExist:
        return JsonResponse({"messages": []})
    
@login_required
def create_room_ajax(request):
    if request.method == 'POST':
        room_name = request.POST.get('room_name', '').strip()
        if room_name == '':
            messages.error(request, "Room name cannot be empty.")
            return render(request, 'create_room.html')

        slug = slugify(room_name)

        if Room.objects.filter(slug=slug).exists():
            messages.error(request, 'Room name already exists')
            return render(request, 'create_room.html')

        room = Room.objects.create(
            name=room_name,
            slug=slug,
            created_by=request.user
        )
        room.members.add(request.user)

        return redirect(f"{reverse('home')}?room={slug}")

    return render(request, 'create_room.html')

@login_required
def group_info(request, slug):
    room = get_object_or_404(Room, slug=slug)
    user_request = None
    if request.user.is_authenticated:
        join_requests = GroupJoinRequest.objects.filter(room=room, status='pending')
        user_request = room.join_requests.filter(user=request.user).first()

    return render(request, 'group_info.html', {
        'join_requests': join_requests,
        'room': room,
        'user_request': user_request
    })

@login_required
def exit_group(request, slug):
    group = get_object_or_404(Room, slug=slug)
    if request.user in group.members.all():
        group.members.remove(request.user)
        GroupJoinRequest.objects.filter(room=group, user=request.user).delete()
        messages.success(request, "You have left the group.")
    else:
        messages.error(request, "You are not part of this group.")
    return redirect('home')


@login_required
def report_group(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    messages.success(request, f"Group '{room.name}' has been reported to admin.")
    return redirect("home")

def edit_room(request, slug):
    room = get_object_or_404(Room, slug=slug)

    if room.created_by != request.user and not request.user.is_staff:
        messages.error(request, "You don't have permission to edit this room.")
        return redirect('home')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()  # ✅ Add this line
        image_form = RoomImageForm(request.POST, request.FILES, instance=room)

        if not name:
            messages.error(request, "Room name cannot be empty.")
            return redirect('edit_room', slug=slug)

        new_slug = slugify(name)
        if new_slug != room.slug and Room.objects.filter(slug=new_slug).exists():
            messages.error(request, "Room name already exists.")
            return redirect('edit_room', slug=slug)

        room.name = name
        room.slug = new_slug
        room.description = description  

        if image_form.is_valid():
            image_form.save()

        room.save() 
        messages.success(request, "Room updated successfully.")
        return redirect('group_info', slug=room.slug)

    else:
        image_form = RoomImageForm(instance=room)

    return render(request, 'edit_room.html', {'room': room, 'image_form': image_form})

@login_required
def delete_room(request, room_id):
    next_url = request.GET.get('next') or reverse('home')
    room = get_object_or_404(Room, id=room_id)

    if room.created_by != request.user and not request.user.is_staff:
        messages.error(request, "You don't have permission to delete this room.")
        return redirect(next_url)

    if request.method == 'POST':
        room.delete()
        messages.success(request, 'Room deleted successfully.')
        return redirect(next_url)

    return render(request, 'confirm_delete_room.html', {'room': room, 'next': next_url})

@login_required
def send_join_request(request, slug):
    group = get_object_or_404(Room, slug=slug)

    if request.user in group.members.all():
        messages.info(request, "You are already a member of this group.")
        return redirect(f"/?room={group.slug}")

    GroupJoinRequest.objects.filter(room=group, user=request.user).exclude(status='pending').delete()

    existing = GroupJoinRequest.objects.filter(room=group, user=request.user, status='pending').first()
    if existing:
        messages.info(request, "You’ve already sent a join request.")
    else:
        GroupJoinRequest.objects.create(room=group, user=request.user, status='pending')
        messages.success(request, "Join request sent successfully!")

    return redirect(f"/?room={group.slug}")


@login_required
def accept_join_request(request, request_id):
    join_request = get_object_or_404(GroupJoinRequest, id=request_id)

    if join_request.room.created_by == request.user:
        join_request.room.members.add(join_request.user)
        join_request.status = 'accepted'
        join_request.save()
        messages.success(request, f"{join_request.user.username} has been added to the group.")
    else:
        messages.error(request, "You are not allowed to accept this request.")

    return redirect('group_info', slug=join_request.room.slug)


@login_required
def send_group_message(request, slug):
    group = get_object_or_404(Room, slug=slug)

    if request.user not in group.members.all():
        messages.error(request, "You must be a member to send messages.")
        return redirect("group_chat", slug=slug)

    if request.method == "POST":
        content = request.POST.get("message", "").strip()
        if content:
            Message.objects.create(user=request.user, room=group, content=content)
        else:
            messages.warning(request, "Message cannot be empty.")

    return redirect("group_chat", slug=slug)
@login_required
def manage_requests(request, slug):
    room = get_object_or_404(Room, slug=slug)

    if request.user != room.created_by:
        messages.error(request, "Only the admin can manage join requests.")
        return redirect('group_info', slug=slug)

    requests = room.join_requests.filter(status='pending')
    return render(request, 'manage_requests.html', {'room': room, 'requests': requests})


@login_required
def handle_request_action(request, request_id, action):
    join_request = get_object_or_404(GroupJoinRequest, id=request_id)
    room = join_request.room

    if request.user != room.created_by:
        messages.error(request, "You are not authorized to perform this action.")
        return redirect('group_info', slug=room.slug)

    if action == 'accept':
        join_request.status = 'accepted'
        room.members.add(join_request.user)
        messages.success(request, f"{join_request.user.username} added to group ✅")
    elif action == 'reject':
        join_request.status = 'rejected'
        messages.info(request, f"{join_request.user.username}'s request rejected ❌")

    join_request.save()
    return redirect('manage_requests', slug=room.slug)

@login_required
def profile(request):
    rooms = Room.objects.filter(created_by=request.user)
    messages_list = ChatMessage.objects.filter(sender=request.user).order_by('-timestamp')[:20]
    profile = request.user.profile

    return render(request, 'profile.html', {
        'rooms': rooms, 
        'messages': messages_list,
        'profile': profile
    })

@login_required
def update_profile(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    if request.method == 'POST':
        form = ProfileUpdateForm(request.POST, request.FILES, instance=profile) 
        if form.is_valid():
            profile = form.save(commit=False)
            user.first_name = form.cleaned_data.get('first_name', user.first_name)
            user.save()
            profile.save()
            messages.success(request, "Profile updated successfully.")
            return redirect('profile')
    else:
        form = ProfileUpdateForm(instance=profile, initial={'first_name': user.first_name})

    return render(request, 'update_profile.html', {'form': form, 'profile': profile})

@login_required
def home(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    storage = messages.get_messages(request)
    list(storage)

    rooms = Room.objects.filter(
        Q(members=request.user) | Q(created_by=request.user)
    ).distinct().annotate(

        last_group_msg_time=Subquery(
            Message.objects.filter(
                room=OuterRef('pk')
            ).order_by('-timestamp').values('timestamp')[:1]
        ),

        unread_count=Count(
            'messages',
            filter=Q(
                messages__is_read=False
            ) & ~Q(
                messages__sender=request.user
            )
        )

    ).order_by(
        F("last_group_msg_time").desc(nulls_last=True)
    )

    for room in rooms:
        if room.created_by == request.user:
            room.pending_requests_count = GroupJoinRequest.objects.filter(
                room=room,
                status='pending'
            ).count()
        else:
            room.pending_requests_count = 0

    my_room_qs = PrivateRoom.objects.filter(
        Q(user1=request.user, user2=OuterRef('pk')) |
        Q(user2=request.user, user1=OuterRef('pk'))
    )

    users = User.objects.exclude(id=request.user.id).annotate(

        room_id=Subquery(
            PrivateRoom.objects.filter(
                Q(user1=request.user, user2=OuterRef('pk')) |
                Q(user2=request.user, user1=OuterRef('pk'))
            ).values('id')[:1]
        ),
    
        # ✅ LAST MESSAGE
        last_msg=Coalesce(
            Subquery(
                PrivateChatMessage.objects.filter(
                    (
                        Q(sender=request.user, receiver=OuterRef('pk')) |
                        Q(sender=OuterRef('pk'), receiver=request.user)
                    ),
                    is_deleted=False
                ).exclude(
                    deleted_by=request.user
                ).order_by('-timestamp').values('content')[:1]
            ),
            Value(''),
            output_field=CharField()
        ),
    
        # ✅ LAST MESSAGE SENDER
        last_msg_sender=Subquery(
            PrivateChatMessage.objects.filter(
                (
                    Q(sender=request.user, receiver=OuterRef('pk')) |
                    Q(sender=OuterRef('pk'), receiver=request.user)
                ),
                is_deleted=False
            ).exclude(
                deleted_by=request.user
            ).order_by('-timestamp').values('sender__username')[:1]
        ),
    
        # ✅ LAST MESSAGE TIME
        last_msg_time=Subquery(
            PrivateChatMessage.objects.filter(
                (
                    Q(sender=request.user, receiver=OuterRef('pk')) |
                    Q(sender=OuterRef('pk'), receiver=request.user)
                ),
                is_deleted=False
            ).exclude(
                deleted_by=request.user
            ).order_by('-timestamp').values('timestamp')[:1]
        ),
    
        # ✅ UNREAD COUNT
        unread_count=Count(
            'sent_private_messages',
            filter=Q(
                sent_private_messages__receiver=request.user,
                sent_private_messages__is_read=False
            )
        )
    
    ).order_by(
        F("last_msg_time").desc(nulls_last=True)
    )
    
    for u in users:
        print("USER:", u.username, "| ROOM:", u.room_id, "| UNREAD:", getattr(u, 'unread_count', 0))

    room_slug = request.GET.get("room")
    user_name = request.GET.get("chat")

    selected_room = None
    selected_user = None
    private_room = None
    chat_messages = []
    selected_user_status = "Offline"
    blocked_flag = False
    pending_requests = None
    join_request = None

    if room_slug:
        try:
            selected_room = Room.objects.get(slug=room_slug)
    
            # ✅ USER KI JOIN REQUEST CHECK
            join_request = GroupJoinRequest.objects.filter(
                room=selected_room,
                user=request.user
            ).first()

            Message.objects.filter(
                room=selected_room,
                is_read=False
            ).exclude(
                sender=request.user
            ).update(is_read=True)
    
            chat_messages = ChatMessage.objects.filter(
                room_name=selected_room.slug
            ).order_by('timestamp')[:50]

            

            if selected_room.created_by == request.user:
                pending_requests = GroupJoinRequest.objects.filter(
                    room=selected_room, status='pending'
                )

        except Room.DoesNotExist:
            messages.error(request, 'Selected room does not exist')

    elif user_name:
        try:
            selected_user = User.objects.get(username=user_name)
            profile.refresh_from_db()

            blocked_flag = selected_user in profile.blocked_users.all()

            private_room = get_or_create_private_chat(request.user, selected_user)

            PrivateChatMessage.objects.filter(
                room=private_room,
                sender=selected_user,
                receiver=request.user,
                is_read=False
            ).update(is_read=True)

            chat_messages = PrivateChatMessage.objects.filter(
                room=private_room
            ).order_by('timestamp')

            selected_user_status = get_user_status_string(selected_user.username)

        except User.DoesNotExist:
            messages.error(request, 'Selected user does not exist')

    return render(request, 'home.html', {
        'rooms': rooms,
        'users': users,
        'selected_room': selected_room,
        'selected_user': selected_user,
        'private_room': private_room,
        'messages': chat_messages,
        'selected_user_status': selected_user_status,
        'chat_active': bool(selected_room or private_room or selected_user),
        'is_blocked': blocked_flag,
        'profile': profile,
        'pending_requests': pending_requests,
        'join_request': join_request,
    })


def get_or_create_private_chat(user1, user2):
    user1, user2 = sorted([user1, user2], key=lambda u: u.id)
    private_rooms = PrivateRoom.objects.filter(user1=user1, user2=user2)
    if private_rooms.exists():
        return private_rooms.first()
    return PrivateRoom.objects.create(user1=user1, user2=user2)

@login_required
def delete_account(request):
    if request.method == 'POST':
        user = request.user
        logout(request)  # Logout first
        user.delete()    # Then delete user
        return render(request, 'account_deleted.html')
    return render(request, 'confirm_delete.html')

@login_required
def account_settings(request):
    return render(request, 'account_settings.html')

@login_required
def security_settings(request):
    recent_logins = []  
    return render(request, 'security_settings.html', {
        'recent_logins': recent_logins
    })

@login_required
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  
            return redirect('security_settings') 
    else:
        form = PasswordChangeForm(user=request.user)

    return render(request, 'change_password.html', {'form': form})

@login_required
def enable_2fa(request):
    return HttpResponse("2FA feature coming soon!")

@login_required
def logout_all_devices(request):
    return HttpResponse("Logout from all devices feature coming soon!")

@login_required
def request_account_info(request):
    return render(request, 'request_account_info.html')

def generate_account_report(request):
    if request.method == "POST":
        messages.success(request, "✅ Your account report request has been received.")
    return redirect('request_account_info')

def generate_channel_report(request):
    if request.method == "POST":
        messages.success(request, "✅ Your channel report request has been received.")
    return redirect('request_account_info')

@login_required
def delete_account_info(request):
    return render(request, 'delete_account_info.html')

def delete_account_permanently(request):
    if request.method == 'POST':
        if request.user.is_authenticated:
            request.user.delete()
            messages.success(request, "Your account has been permanently deleted.")
            return redirect('home') 
    return redirect('delete_account_info')

@login_required
def privacy_settings(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return render(request, 'privacy_settings.html', {'profile': profile})

@csrf_exempt
def last_seen_online(request):
    last_seen = request.session.get("last_seen", "")
    online_status = request.session.get("online_status", "")
    
    context = {
        "selected_last_seen": last_seen,
        "selected_online_status": online_status,
    }
    return render(request, "last_seen_online.html", context)

@csrf_exempt
def save_last_seen_online(request):
    if request.method == "POST":
        last_seen = request.POST.get('last_seen')
        online_status = request.POST.get('online_status')

        # Save settings in session
        request.session["last_seen"] = last_seen
        request.session["online_status"] = online_status

        return JsonResponse({"status": "success"})
    return JsonResponse({"status": "error"}, status=400)

@csrf_exempt
def profile_photo_privacy(request):
    user = request.user
    profile, created = Profile.objects.get_or_create(user=user)  

    if request.method == 'POST':
        choice = request.POST.get('photo_privacy')
        profile.photo_privacy = choice
        profile.save()
        return redirect('profile_photo_privacy')

    context = {
        'current_setting': profile.photo_privacy
    }
    return render(request, 'profile_photo_privacy.html', context)

@login_required
def privacy_about(request):
    profile, _  = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        choice = request.POST.get('photo_privacy')
        profile.photo_privacy = choice
        profile.save()
        return JsonResponse({"status": "success"})  
    return render(request, 'about_privacy.html', {'profile': profile})

@login_required
def status_privacy(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        choice = request.POST.get('status_privacy')
        profile.status_privacy = choice
        profile.save()
        messages.success(request, "Status privacy updated successfully.")
        return redirect('status_privacy')  
    return render(request, 'status_privacy.html', {'profile': profile})

@login_required
@require_http_methods(["GET", "POST"])
def default_message_timer_setting(request):
    profile_obj, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        timer_value = int(request.POST.get('default_message_timer', 0))
        profile_obj.default_message_timer = timer_value
        profile_obj.save()
        return redirect('default_message_timer') 
    return render(request, 'default_message_timer.html', {
        'profile': profile_obj
    })

@require_POST
@login_required
def toggle_read_receipts(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    profile.read_receipts_enabled = not profile.read_receipts_enabled
    profile.save()
    return JsonResponse({'status': 'success', 'enabled': profile.read_receipts_enabled})

@require_POST
@login_required
def toggle_block_unknowns(request):
    profile, _ = Profile.objects.get_or_create(user=request.user) 
    profile.block_unknowns = not profile.block_unknowns
    profile.save() 
    return JsonResponse({'status': 'success', 'enabled': profile.block_unknowns})

@login_required
def group_privacy(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        selected = request.POST.get('group_privacy')
        if selected in ['everyone', 'contacts', 'contacts_except']:
            profile.group_privacy = selected
            profile.save()
            return JsonResponse({'status': 'success'})  
    return render(request, 'group_privacy.html', {
        'profile': profile
    })

@login_required
def blocked_contacts_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    blocked_users = profile.blocked_users.all()
    return render(request, 'blocked_contacts.html', {
        'blocked_users': blocked_users
    })

@login_required
def block_user(request):
    if request.method == "POST":
        target_username = request.POST.get('username')
        try:
            target_user = User.objects.get(username=target_username)
            profile, _ = Profile.objects.get_or_create(user=request.user)
            profile.blocked_users.add(target_user)
            return JsonResponse({'status': 'success', 'message': 'User blocked successfully'})
        except User.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'User not found'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'})

@login_required
def unblock_user(request):
    if request.method == 'POST':
        target_username = request.POST.get('username')
        try:
            target_user = User.objects.get(username=target_username)
            profile, _ = Profile.objects.get_or_create(user=request.user)
            profile.blocked_users.remove(target_user)
            return JsonResponse({'status': 'success', 'message': 'User unblocked'})
        except User.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'User not found'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'})

@login_required
@require_POST 
def toggle_block_user(request):
    try:
        data = json.loads(request.body)
        username = data.get('username')
        action = data.get('action') # 'block' ya 'unblock'
    except:
        return JsonResponse({"error": "Invalid data format"}, status=400)
    
    if not username or action not in ['block', 'unblock']:
        return JsonResponse({"error": "Missing username or action"}, status=400)
        
    target_user = get_object_or_404(User, username=username)
    current_profile, _ = Profile.objects.get_or_create(user=request.user)

    if action == 'block':
        current_profile.blocked_users.add(target_user)
        status_message = "blocked"
    
    elif action == 'unblock':
        current_profile.blocked_users.remove(target_user)
        status_message = "unblocked"
    return JsonResponse({"status": status_message, "username": username})

@login_required
def report_user(request, username):
    user_to_report = get_object_or_404(CustomUser, username=username)
    print("Reported user:", user_to_report)
    return redirect('chat_detail', username=username)

@login_required
def chat_view(request):
    users = User.objects.exclude(id=request.user.id)
    selected_user = None
    is_blocked = False

    username = request.GET.get('chat')
    if username:
        try:
            selected_user = User.objects.get(username=username)
            profile, _ = Profile.objects.get_or_create(user=request.user)
            is_blocked = selected_user in profile.blocked_users.all()
        except User.DoesNotExist:
            selected_user = None

    try:
        profile = Profile.objects.get(user=request.user)
        chat_theme = profile.chat_theme
        profile_image_url = profile.image.url if profile.image else None
    except Profile.DoesNotExist:
        chat_theme = 'default'
        profile_image_url = None

    context = {
        'user': users,
        'chat_theme': chat_theme,
        'selected_user': selected_user,
        'is_blocked': is_blocked,
        'profile_image_url': profile_image_url,  # yaha daal diya
    }
    return render(request, 'chat_view.html', context)

@login_required
def delete_chat(request, username):

    if request.method != "POST":
        return JsonResponse(
            {"error": "Invalid request"},
            status=400
        )

    other_user = get_object_or_404(
        User,
        username=username
    )

    room = PrivateRoom.get_or_create_room(
        request.user,
        other_user
    )

    messages = PrivateChatMessage.objects.filter(
        room=room
    )

    for msg in messages:

        msg.deleted_by.add(request.user)

        # ✅ dono users delete kar de
        if msg.deleted_by.count() == 2:

            # ❌ msg.delete()

            # ✅ message ko hide mark karo
            msg.content = "Message deleted"
            msg.save()

    return JsonResponse({"success": True})
@login_required
def user_profile(request, username):
    user_obj = get_object_or_404(User, username=username)
    return render(request, 'chat/user_profile.html', {
        'profile_user': user_obj
    })

def get_user_status_string(username): 
    try:
        user = User.objects.get(username=username)
        profile, _ = Profile.objects.get_or_create(user=user)
        return "Online" if profile.is_online else "Offline"
    except User.DoesNotExist:
        return "Unknown"
    except Exception:
        return "Unknown"

def get_user_status_api(request):
    username = request.GET.get("username")
    if not username:
        return JsonResponse({"error": "Username is required"}, status=400)

    try:
        profile = Profile.objects.get(user__username=username)
        status = "Online" if profile.is_online else "Offline"
        return JsonResponse({"status": status})
    except Profile.DoesNotExist:
        return JsonResponse({"status": "User not found"}, status=404)

def get_user_status_view(request):
    if request.method == "GET":
        username = request.GET.get("username")
        try:
            user = User.objects.get(username=username)
            status = "online" if user.profile.is_online else "offline"
            return JsonResponse({"status": status})
        except User.DoesNotExist:
            return JsonResponse({"error": "User not found"}, status=404)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=400)
    
def user_logged_in_custom(request, user):
    profile, _ = Profile.objects.get_or_create(user=user) 
    profile.is_online = True
    profile.last_seen = timezone.now()
    profile.save()

@csrf_exempt
@login_required
def toggle_app_lock(request):
    if request.method == "POST":
        profile = request.user.profile

        currently_enabled = profile.app_lock_enabled

        if not currently_enabled:
            if not profile.app_lock_password_hash:
                return JsonResponse({'status': 'need_password'})

            profile.app_lock_enabled = True
            profile.save()
            return JsonResponse({'status': 'success', 'enabled': True})
        
        else:
            profile.app_lock_enabled = False
            profile.save()
            return JsonResponse({'status': 'success', 'enabled': False})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

@csrf_exempt
@login_required
def set_app_lock_password(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        password = data.get('password')

        if not password or len(password) < 4:
            return JsonResponse({'status': 'error', 'message': 'Password too short'}, status=400)

        user_profile = request.user.profile 
        user_profile.app_lock_password_hash = make_password(password)
        user_profile.app_lock_enabled = True
        user_profile.save()

        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)

@csrf_exempt
@login_required
def verify_app_lock_password(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        password = data.get('password')

        profile = request.user.profile
        if profile.app_lock_password == password:
            return JsonResponse({'status': 'success'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Incorrect password'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

@login_required
def chat_theme(request):
    profile = request.user.profile
    return render(request, 'chat_theme.html', {'profile': profile})

@login_required
def update_chat_theme(request):
    if request.method == "POST":
        try:
            user_profile = request.user.profile  
            wallpaper_file = request.FILES.get("chat_wallpaper")
            wallpaper_default = request.POST.get("chat_wallpaper_default")

            if not wallpaper_default or wallpaper_default.strip() == "":
                wallpaper_default = "default_wallpaper"  # apne hisab se default value change kar sakte ho

            upload_quality = request.POST.get("media_upload_quality")
            auto_photos = request.POST.get("auto_download_photos") == "true"
            auto_videos = request.POST.get("auto_download_videos") == "true"
            auto_audio = request.POST.get("auto_download_audio") == "true"
            auto_docs = request.POST.get("auto_download_documents") == "true"

            if wallpaper_file:
                user_profile.chat_wallpaper = wallpaper_file
                user_profile.chat_wallpaper_default = None  # Clear default when custom wallpaper set
            else:
                user_profile.chat_wallpaper = None
                user_profile.chat_wallpaper_default = wallpaper_default

            chat_theme = request.POST.get("chat_color_theme")
            if not chat_theme:
                chat_theme = "default"  # fallback value

            user_profile.chat_theme = chat_theme

            user_profile.media_upload_quality = upload_quality
            user_profile.auto_download_photos = auto_photos
            user_profile.auto_download_videos = auto_videos
            user_profile.auto_download_audio = auto_audio
            user_profile.auto_download_documents = auto_docs

            user_profile.save()
            return JsonResponse({"status": "success"})
        except Exception as e:
            print("Error in update_chat_theme:", e)
            # import traceback
            traceback.print_exc()
            return JsonResponse({"status": "error", "message": str(e)})
    return JsonResponse({"status": "error", "message": "Invalid request method"})

@login_required
def remove_chat_wallpaper(request):
    profile = request.user.profile
    if profile.chat_wallpaper:
        profile.chat_wallpaper.delete(save=False)
        profile.chat_wallpaper = None
        profile.chat_wallpaper_default = 'default'
        profile.save()
        return JsonResponse({"status": "success"})
    return JsonResponse({"status": "no_wallpaper"})

@login_required
def notification_settings(request):
    profile, created = Profile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        mute_notifications = request.POST.get("mute_notifications") == "on"
        email_alerts = request.POST.get("email_alerts") == "on"

        profile.mute_notifications = mute_notifications
        profile.email_alerts = email_alerts
        profile.save()

        messages.success(request, "✅ Notification settings have been updated successfully!")
        return redirect('notification_settings')  # stays on same page

    return render(request, 'notification_settings.html', {'profile': profile})

def update_notification_settings(request):
    if request.method == "POST":
        profile = Profile.objects.get(user=request.user)
        profile.mute_notifications = request.POST.get("mute") == "true"
        profile.save()
        return JsonResponse({"status": "success"})
    return JsonResponse({"error": "Invalid Request"}, status=400)


def signup_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        username = request.POST.get('username', '').strip()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        # Validation
        if not all([name, username, phone, password, confirm_password]):
            messages.error(request, "All fields are required.")
            return render(request, 'signup.html')

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'signup.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return render(request, 'signup.html')

        try:
            # Create user
            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=name
            )

            # Save phone number in profile
            profile = user.profile
            profile.phone_number = phone
            profile.save()

            messages.success(request, "Account created successfully.")
            return redirect('login')

        except Exception as e:
            messages.error(request, f"Error creating account: {str(e)}")

    return render(request, 'signup.html')

def login_view(request):
    next_url = request.GET.get('next', '')
    if request.method == 'POST':
        username = request.POST['username'].strip()
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            profile, _ = Profile.objects.get_or_create(user=user) # Ensure profile exists
            profile.is_online = True
            profile.save()
            return redirect(request.POST.get('next') or 'home')
        else:
            messages.error(request, "Invalid username or password.")
    return render(request, 'login.html', {'next': next_url})

def logout_view(request):
    if request.user.is_authenticated:
        try:
            profile, _ = Profile.objects.get_or_create(user=request.user) # Ensure profile exists
            profile.is_online = False
            profile.save()
        except:
            pass
    logout(request)
    return redirect('login')

@login_required
def get_all_users_status(request):
    users = User.objects.all()
    data = [
        {
            "username": user.username,
            "is_online": getattr(user.profile, "is_online", False)
        }
        for user in users
    ]
    return JsonResponse(data, safe=False)

@login_required
def search_users(request):

    query = request.GET.get("q", "").strip()

    data = []
    group_data = []

    # Agar query empty hai
    if not query:
        return JsonResponse({
            "users": [],
            "groups": []
        })

    # Search Users
    users = User.objects.filter(
        Q(username__icontains=query) |
        Q(profile__phone_number__icontains=query) |
        Q(first_name__icontains=query)
    ).exclude(id=request.user.id)[:10]

    # Search Groups
    rooms = Room.objects.filter(
        name__icontains=query
    )[:10]

    # Users Data
    for user in users:

        data.append({
            "username": user.username,
            "name": user.first_name or user.username,
            "phone": user.profile.phone_number if hasattr(user, 'profile') else "",
            "profile_pic": (
                user.profile.profile_pic.url
                if user.profile.profile_pic
                else ""
            )
        })

    # Groups Data
    for room in rooms:

        group_data.append({
            "name": room.name,
            "slug": room.slug,
            "image": room.image.url if room.image else ""
        })

    return JsonResponse({
        "users": data,
        "groups": group_data
    })

@login_required
def group_chat(request, slug):
    group = get_object_or_404(Group, slug=slug)
    messages = Message.objects.filter(room=group)
    join_request = join_request.objects.filter(group=group, user=request.user).first()

    return render(request, "home.html", {
        "group": group,
        "messages": messages,
        "join_request": join_request,
    })

def is_admin(user):
    return user.is_staff or user.is_superuser

def send_message(
    request):
    if request.method == "POST":
        data = json.loads(request.body)
        room_id = request.session.get("room_id")
        room = Room.objects.get(id=room_id)
        user = request.user

        msg = Message.objects.create(
            room=room,
            user=user,
            content=data.get("message"),
            reply_to=data.get("reply_to"),
            reply_name=data.get("reply_name"),
        )
        return JsonResponse({"status": "ok"})

@csrf_exempt
def delete_message(request, message_id):
    """
    Marks a message as deleted by the current user (for both group & private).
    Message will not appear for that user after reload.
    """
    if request.method != "DELETE":
        return JsonResponse({"success": False, "error": "Invalid request method."})

    try:
        user = request.user
        deleted = False

        # 🟢 Try deleting from Group Chat Messages
        try:
            msg = Message.objects.get(id=message_id)
            msg.is_deleted = True
            msg.deleted_by.add(user)
            msg.save()
            deleted = True
            print(f"🗑️ Group message marked deleted by {user.username} (ID: {message_id})")
        except Message.DoesNotExist:
            pass

        # 🟢 Try deleting from Private Chat Messages
        if not deleted:
            try:
                msg = PrivateChatMessage.objects.get(id=message_id)
                msg.is_deleted = True
                msg.deleted_by.add(user)
                msg.save()
                deleted = True
                print(f"🗑️ Private message marked deleted by {user.username} (ID: {message_id})")
            except PrivateChatMessage.DoesNotExist:
                pass

        if deleted:
            return JsonResponse({"success": True})
        else:
            return JsonResponse({"success": False, "error": "Message not found."})

    except Exception as e:
        print(f"❌ Delete message error: {e}")
        return JsonResponse({"success": False, "error": str(e)})

@csrf_exempt
def delete_all_messages(request, room_id):
    if request.method == "POST":
        try:
            room = Room.objects.get(id=room_id)
            Message.objects.filter(room=room).delete()
            return JsonResponse({"status": "success"})
        except Room.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Room not found"})
    return JsonResponse({"status": "error", "message": "Invalid request"})

@csrf_exempt
@login_required
def clear_chat_for_me(request, room_id):
    return JsonResponse({"status": "success"})

@csrf_exempt
@login_required
def clear_chat_for_user(request, room_id):
    if request.method == "POST":
        try:
            room = Room.objects.get(id=room_id)
            user = request.user

            # Saare messages fetch
            messages = Message.objects.filter(room=room)

            # Hidden_by me add karo
            for msg in messages:
                msg.hidden_by.add(user)

            return JsonResponse({"status": "success"})

        except Room.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Room not found"})
    
    return JsonResponse({"status": "error", "message": "Invalid request"})

@login_required
def room(request, room_id):
    room = Room.objects.get(id=room_id)
    user = request.user

    # Sirf woh messages dikhana jo user ne hide nahi kiye
    messages = Message.objects.filter(room=room).exclude(hidden_by=user)

    return render(request, "room.html", {
        "room": room,
        "messages": messages
    })

# -------------------- Private Chat Messages --------------------
@login_required
def load_private_messages(request, room_slug):
    try:
        users = sorted(room_slug.split("__"))
        user1 = User.objects.get(username=users[0])
        user2 = User.objects.get(username=users[1])
        room = PrivateRoom.get_or_create_room(user1, user2)

        # ✅ FIX: Only show messages not deleted globally AND not deleted by this user
        messages = (
            PrivateChatMessage.objects.filter(room=room, is_deleted=False)
            .exclude(deleted_by=request.user)
            .order_by("timestamp")
        )

        data = []
        for msg in messages:
            reply_message_text = None
            if msg.reply_to:
                try:
                    target = PrivateChatMessage.objects.filter(id=int(msg.reply_to)).first()
                    if target and not target.is_deleted:
                        reply_message_text = target.content
                except:
                    pass

            data.append({
                "id": msg.id,
                "username": msg.sender.username,
                "name": msg.sender.first_name or msg.sender.username,
                "content": msg.content,
                "timestamp": msg.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "reply_to": msg.reply_to if msg.reply_to else None,
                "reply_name": msg.reply_name,
                "reply_message": reply_message_text,
                "is_self": msg.sender == request.user,
            })

        return JsonResponse({"messages": data})

    except Exception as e:
        # import traceback
        print("💥 Private chat load error:", e)
        traceback.print_exc()
        return JsonResponse({"messages": []})


# -------------------- Room Chat Messages --------------------
@login_required
def load_room_messages(request, room_name):
    try:
        room = Room.objects.filter(slug=room_name).first()
        if not room:
            return JsonResponse({"messages": []})

        # ✅ FIX: ignore messages that are marked deleted
        messages = (
            Message.objects.filter(room=room, is_deleted=False)
            .exclude(hidden_by=request.user)
            .order_by("timestamp")
        )

        data = []
        for msg in messages:
            sender_username = msg.sender.username if msg.sender else msg.user.username
            reply_message_text = None

            if msg.reply_to:
                try:
                    target = Message.objects.filter(id=int(msg.reply_to), is_deleted=False).first()
                    if target:
                        reply_message_text = target.content
                except:
                    pass

            data.append({
                "id": msg.id,
                "username": sender_username,
                "name": sender_username,
                "content": msg.content,
                "timestamp": msg.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "reply_to": msg.reply_to,
                "reply_name": msg.reply_name,
                "reply_message": reply_message_text,
                "is_self": sender_username == request.user.username,
            })

        return JsonResponse({"messages": data})

    except Exception as e:
        # import traceback
        print("💥 Error in load_room_messages:", e)
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)

# -------------------- Helper to find replied message ID --------------------
def get_reply_message_id(reply_text, room):
    """Find the original message ID for reply scroll."""
    if not reply_text:
        return None
    try:
        msg = (
            Message.objects.filter(room=room, content=reply_text).first()
            or PrivateChatMessage.objects.filter(room=room, content=reply_text).first()
        )
        return msg.id if msg else None
    except:
        return None
    

@login_required
def get_user_rooms(request):
    user = request.user

    # ✅ Sab users lao except current user
    users = list(
        User.objects.exclude(id=user.id).values("username", "first_name")
    )

    # ✅ Frontend ke liye readable name field add karo
    for u in users:
        u["name"] = u["first_name"] or u["username"]

    # ✅ Sab non-private (group) rooms lao
    groups = Room.objects.filter(is_private=False).values("name", "slug")

    # 🔍 Debug print (sirf check ke liye)
    print("✅ USERS =>", users)
    print("✅ GROUPS =>", list(groups))

    # ✅ JSON response bhej do
    return JsonResponse({
        "users": users,
        "groups": list(groups)
    })

@csrf_exempt
def forward_message(request):
    if request.method == "POST":
        try:
            # ✅ Accept both form-data and JSON
            if request.content_type == "application/json":
                data = json.loads(request.body)
            else:
                data = request.POST

            sender_name = data.get('sender_name')
            message_text = data.get('message_text')
            target_type = data.get('target_type')
            target_name = data.get('target_name')

            if not sender_name or not message_text or not target_type or not target_name:
                return JsonResponse({'success': False, 'error': 'Incomplete data provided.'})

            sender = User.objects.get(username=sender_name)

            redirect_url = None

            # 🟢 Forward to Private Chat
            if target_type == 'user':
                receiver = User.objects.get(username=target_name)
                room = PrivateRoom.get_or_create_room(sender, receiver)

                PrivateChatMessage.objects.create(
                    room=room,
                    sender=sender,
                    content=message_text,
                    is_forwarded=True,
                    original_sender=sender.username
                )

                # ✅ Correct redirect to private chat page
                redirect_url = f"/?chat={room.room_slug}"
                print(f"✅ Forwarded private message to {receiver.username}")

            # 🟢 Forward to Group Chat
            elif target_type == 'group':
                try:
                    print("🔍 Forward request:", target_type, target_name)
                    print("Available rooms:", list(Room.objects.values_list('slug', flat=True)))

                    room = Room.objects.get(slug=target_name)
                except Room.DoesNotExist:
                    print(f"❌ No room found for slug '{target_name}'")
                    return JsonResponse({'success': False, 'error': f'Group \"{target_name}\" not found.'})

                Message.objects.create(
                    room=room,
                    user=sender,
                    content=message_text,
                    is_forwarded=True,
                    original_sender=sender.username
                )

                # ✅ Correct redirect to group chat page
                redirect_url = f"/?chat={room.slug}"
                print(f"✅ Forwarded group message to {room.name}")

            else:
                return JsonResponse({'success': False, 'error': 'Invalid target type.'})

            return JsonResponse({'success': True, 'redirect_url': redirect_url})

        except Exception as e:
            print(f"[FORWARD ERROR ❌] {e}")
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request method.'})

def about(request):
    return render(request, 'about.html')


def help_view(request):
    return render(request, 'help.html')

from django.contrib.auth.models import User

@login_required
def sidebar_data(request):

    users = User.objects.exclude(
        id=request.user.id
    )

    users_data = []

    for user in users:

        # ✅ deleted messages exclude
        last_message = PrivateChatMessage.objects.filter(
            sender__in=[request.user, user],
            receiver__in=[request.user, user]
        ).exclude(
            deleted_by=request.user
        ).order_by('-timestamp').first()

        unread_count = PrivateChatMessage.objects.filter(
            sender=user,
            receiver=request.user,
            is_read=False
        ).exclude(
            deleted_by=request.user
        ).count()

        user.last_msg = None
        user.last_msg_sender = None
        user.last_msg_time = None

        if last_message:

            user.last_msg = last_message.content
            user.last_msg_sender = last_message.sender
            user.last_msg_time = last_message.timestamp

        user.unread_count = unread_count

        users_data.append(user)

    users_data.sort(
        key=lambda x: x.last_msg_time or 0,
        reverse=True
    )

    return render(
        request,
        "partials/sidebar_users.html",
        {
            "users": users_data,
            "request_user": request.user,
            "request": request
        }
    )

def get_unread_counts(user):
    from django.db.models import Count, Q

    return Message.objects.filter(
        receiver=user,
        is_read=False
    ).values('sender').annotate(total=Count('id'))