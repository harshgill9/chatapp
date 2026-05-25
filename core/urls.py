from django.urls import path
from . import views
from .views import get_user_status_api
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # 🔐 Authentication
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),

    # 👤 Profile
    path('profile/', views.profile, name='profile'),
    path('update-profile/', views.update_profile, name='update_profile'),
    path('user/<str:username>/', views.user_profile, name='user_profile'),

    # 🏠 Rooms / 🛠 Admin Dashboard
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('create-room/', views.create_room_ajax, name='create_room_ajax'),
    path("group/<slug:slug>/", views.group_chat, name="group_chat"),
    path('group/<slug:slug>/info/', views.group_info, name='group_info'),
    path('group/<slug:slug>/join/', views.send_join_request, name='send_join_request'),
    path('group/join/accept/<int:request_id>/', views.accept_join_request, name='accept_join_request'),
    # path('check-room-access/<slug:slug>/', views.check_room_access, name='check_room_access'),  
    
    path("group/<slug:slug>/send-message/", views.send_group_message, name="send_group_message"),
    path('group/<slug:slug>/exit/', views.exit_group, name='exit_group'),
    path("group/<int:room_id>/report/", views.report_group, name="report_group"),
    path('get-room-messages/<slug:slug>/', views.get_room_messages, name='get_room_messages'),
    path('room/edit/<slug:slug>/', views.edit_room, name='edit_room'),
    path('delete-room/<int:room_id>/', views.delete_room, name='delete_room'),
    path('group/<slug:slug>/requests/', views.manage_requests, name='manage_requests'),
    path('group/request/<int:request_id>/action/<str:action>/', views.handle_request_action, name='handle_request_action'),

    
    # 🛠️ Admin Chat Moderation (✅ Fixed Prefix)
    path('admin-dashboard/chat/<str:room_name>/', views.chat_room_admin, name='chat_room_admin'),
    path('admin-dashboard/delete-message/<int:msg_id>/', views.delete_message, name='admin_delete_message'),
    path('delete-all-messages/<int:room_id>/', views.delete_all_messages, name='delete_all_messages'),
    path('admin-dashboard/user/delete/<int:user_id>/', views.delete_user, name='delete_user'),

    # 🔎 Search & Info Pages
    path('search-users/', views.search_users, name='search_users'),
    path('about/', views.about, name='about'),
    path('help/', views.help_view, name='help'),

    # ⚙️ Account Settings
    path('delete-account/', views.delete_account, name='delete_account'),
    path('settings/account/', views.account_settings, name='account_settings'),
    path('settings/security/', views.security_settings, name='security_settings'),
    path('change-password/', views.change_password, name='change_password'),
    path('enable-2fa/', views.enable_2fa, name='enable_2fa'),
    path('logout-all-devices/', views.logout_all_devices, name='logout_all_devices'),

    # 📝 Account Info & Deletion Requests
    path('settings/request-info/', views.request_account_info, name='request_account_info'),
    path('settings/request-account-report/', views.generate_account_report, name='generate_account_report'),
    path('settings/request-channel-report/', views.generate_channel_report, name='generate_channel_report'),
    path('settings/delete-account/', views.delete_account_info, name='delete_account_info'),
    path('settings/delete-account/confirm/', views.delete_account_permanently, name='delete_account_permanently'),

    # 🔒 Privacy Settings
    path('settings/privacy/', views.privacy_settings, name='privacy_settings'),
    path('settings/privacy/blocked/', views.blocked_contacts_view, name='blocked_contacts'),
    path('settings/privacy/about/', views.privacy_about, name='about_privacy'),
    path('settings/privacy/status/', views.status_privacy, name='status_privacy'),
    path('settings/profile-photo-privacy/', views.profile_photo_privacy, name='profile_photo_privacy'),
    path('settings/default-message-timer/', views.default_message_timer_setting, name='default_message_timer'),
    path('settings/toggle-read-receipts/', views.toggle_read_receipts, name='toggle_read_receipts'),
    path('settings/last-seen-online/', views.last_seen_online, name='last_seen_online'),
    path('settings/save-last-seen-online/', views.save_last_seen_online, name='save_last_seen_online'),
    path('settings/chat-theme/', views.chat_theme, name='chat_theme'),
    path('update-chat-theme/', views.update_chat_theme, name='update_chat_theme'),
    path('remove-chat-wallpaper/', views.remove_chat_wallpaper, name='remove_chat_wallpaper'),
    path('settings/notifications/', views.notification_settings, name='notification_settings'),
    path('update-notification-settings/', views.update_notification_settings, name='update_notification_settings'),
    
    # 🔐 Privacy actions
    path('privacy/group/', views.group_privacy, name='group_privacy'),
    path('privacy/toggle-read-receipts/', views.toggle_read_receipts, name='privacy_toggle_read_receipts'),
    path('privacy/toggle-block-unknowns/', views.toggle_block_unknowns, name='toggle_block_unknowns'),
    path('privacy/block/<str:username>/', views.block_user, name='block_user'),
    path('privacy/unblock/<str:username>/', views.unblock_user, name='unblock_user'),
    path('privacy/toggle-block/', views.toggle_block_user, name='toggle_block_user'),
    path('toggle-app-lock/', views.toggle_app_lock, name='toggle_app_lock'),
    path('set-app-lock-password/', views.set_app_lock_password, name='set_app_lock_password'),
    path('verify-app-lock/', views.verify_app_lock_password, name='verify_app_lock_password'),
    
    # 💬 Chat (Normal Users)
    path('chat/', views.chat_view, name='chat_view'),
    path("delete_chat/<str:username>/", views.delete_chat, name="delete_chat"),
    path('report/<str:username>/', views.report_user, name='report_user'),
    path('delete-message/<int:msg_id>/', views.delete_message, name='delete_message'),
    path('api/messages/<str:room_name>/', views.load_room_messages, name='load_room_messages'),
    path('load_private_messages/<str:room_slug>/', views.load_private_messages, name='load_private_messages'),
    path('load_room_messages/<slug:room_name>/', views.load_room_messages, name='load_room_messages'),
    path("get_user_rooms/", views.get_user_rooms, name="get_user_rooms"),
    path("forward_message/", views.forward_message, name="forward_message"),
    path('delete_message/<int:message_id>/', views.delete_message, name='delete_message'),
    path("clear-chat/<int:room_id>/", views.clear_chat_for_user, name="clear_chat"),
    path("clear-chat-for-me/<int:room_id>/", views.clear_chat_for_me, name="clear_chat_for_me"),
    path("room/<int:room_id>/", views.room, name="room"),
    path("hide-my-messages/<int:room_id>/", views.clear_chat_for_user, name="hide_my_messages"),


    # 📡 Status APIs
    path('api/users/status/', views.get_all_users_status, name='get_all_users_status'),
    path('api/user-status/', views.get_user_status_api, name='get_user_status_api'),
    path('view/user-status/', views.get_user_status_view, name='get_user_status_view'),

    # sidebar data
    path("sidebar-data/", views.sidebar_data, name="sidebar_data"),
]

# 🖼️ Media files (development mode)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
