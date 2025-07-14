from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db.models import Q
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils.text import slugify
from .forms import SearchForm, ProfilePicForm
import json

from .models import Room, Message, PrivateRoom, UserProfile, ChatMessage


@staff_member_required
def admin_dashboard(request):
    users = User.objects.all()
    rooms = Room.objects.all()
    messages = Message.objects.order_by('-timestamp')[:50]
    return render(request, 'admin_dashboard.html', {
        'users': users,
        'rooms': rooms,
        'messages': messages
    })


@login_required
def create_room_ajax(request):
    if request.method == 'POST':
        room_name = request.POST.get('room_name')
        if not Room.objects.filter(name=room_name).exists():
            Room.objects.create(name=room_name, created_by=request.user)
            return redirect(f"{reverse('home')}?room={room_name}")
        else:
            messages.error(request, 'Room name already exists')
    return render(request, 'create_room.html')


@login_required
def delete_room(request, room_id):
    next_url = request.GET.get('next') or 'home'
    room = get_object_or_404(Room, id=room_id)
    if request.method == 'POST':
        room.delete()
        messages.success(request, 'Room deleted successfully.')
    return redirect(next_url)


@login_required
def profile(request):
    rooms = Room.objects.filter(created_by=request.user)
    messages = ChatMessage.objects.filter(sender=request.user).order_by('-timestamp')[:20]
    return render(request, 'profile.html', {'rooms': rooms, 'messages': messages})

@login_required
def update_profile_pic(request):
    profile = request.user.userprofile
    if request.method == 'POST':
        form = ProfilePicForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile picture updated successfully.")
            return redirect('profile')  # Or anywhere you want to go after upload
    else:
        form = ProfilePicForm(instance=profile)
    
    return render(request, 'update_profile_pic.html', {'form': form})

@login_required
def home(request):
    storage = messages.get_messages(request)
    list(storage)

    rooms = Room.objects.all()
    users = User.objects.exclude(id=request.user.id)

    selected_room = None
    selected_user = None
    private_room = None
    chat_messages = []

    room_name = request.GET.get("room")
    user_name = request.GET.get("chat")
    selected_user_status = False

    if room_name:
        try:
            selected_room = Room.objects.get(slug=room_name)
            chat_messages = ChatMessage.objects.filter(room_name=selected_room.slug).order_by('timestamp')[:50]
        except Room.DoesNotExist:
            messages.error(request, 'Selected room does not exist')

    elif user_name:
        try:
            selected_user = User.objects.get(username=user_name)
            private_room = get_or_create_private_chat(request.user, selected_user)
            chat_messages = ChatMessage.objects.filter(room_name=private_room.room_slug).order_by('timestamp')[:50]
            selected_user_status = get_user_status(selected_user.username)
        except User.DoesNotExist:
            messages.error(request, 'Selected user does not exist')

    return render(request, 'home.html', {
        'rooms': rooms,
        'users': users,
        'selected_room': selected_room,
        'selected_user': selected_user,
        'private_room': private_room,
        'messages': chat_messages,
        'error_message': messages.get_messages(request),
        'selected_user_status': selected_user_status
    })

def get_or_create_private_chat(user1, user2):
    user1, user2 = sorted([user1, user2], key=lambda u: u.id)
    room, created = PrivateRoom.objects.get_or_create(user1=user1, user2=user2)
    return room
# core/views.py
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout

@login_required
def delete_account(request):
    if request.method == 'POST':
        user = request.user
        logout(request)  # Pehle logout kar do
        user.delete()    # Fir user ko delete kar do
        return render(request, 'account_deleted.html')  # Confirmation page
    return render(request, 'confirm_delete.html')


def signup_view(request):
    if request.method == 'POST':
        name = request.POST['name']
        username = request.POST['username'].strip()
        password = request.POST['password']

        if not username or not password:
            messages.error(request, "Username and password are required.")
        elif ' ' in username:
            messages.error(request, "Username cannot contain spaces.")
        elif not username.isalnum():
            messages.error(request, "Username can only contain letters and numbers.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
        else:
            User.objects.create_user(first_name=name, username=username, password=password)
            messages.success(request, "Account created successfully. Please log in.")
            return redirect('login')
    return render(request, 'signup.html')


def login_view(request):
    next_url = request.GET.get('next', '')
    if request.method == 'POST':
        username = request.POST['username'].strip()
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.is_online = True
            profile.save()
            return redirect(request.POST.get('next') or 'home')
        else:
            messages.error(request, "Invalid username or password.")
    return render(request, 'login.html', {'next': next_url})


def logout_view(request):
    if request.user.is_authenticated:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.is_online = False
        profile.save()
    logout(request)
    return redirect('login')


@csrf_exempt
def create_room_ajax(request):
    if request.method == "POST":
        data = json.loads(request.body)
        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"success": False, "error": "Room name is required"})
        slug = slugify(name)
        if Room.objects.filter(slug=slug).exists():
            return JsonResponse({"success": False, "error": "Room already exists"})
        room = Room.objects.create(name=name, slug=slug, created_by=request.user)
        return JsonResponse({"success": True, "slug": room.slug})
    return JsonResponse({"success": False, "error": "Invalid request"})


def get_user_status(username):
    try:
        profile = UserProfile.objects.get(user__username=username)
        return profile.is_online
    except UserProfile.DoesNotExist:
        return False


def search_users(request):
    query = request.GET.get('q', '')
    users = User.objects.filter(username__icontains=query)
    result = []
    for user in users:
        try:
            profile = UserProfile.objects.get(user=user)
            is_online = profile.is_online
        except UserProfile.DoesNotExist:
            is_online = False
        result.append({
            'username': user.username,
            'online': is_online
        })
    return JsonResponse({'results': result})

def about(request):
    return render(request, 'about.html')

