from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('create_room_ajax/', views.create_room_ajax, name='create_room_ajax'),
    path('delete-room/<int:room_id>/', views.delete_room, name='delete_room'),
    path('delete-account/', views.delete_account, name='delete_account'),
    path('profile/', views.profile, name='profile'),
    path('update-profile-pic/', views.update_profile_pic, name='update_profile_pic'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    # path('create_room_ajax/', views.create_room_ajax, name='create_room_ajax'),
    path('search/', views.search_users, name='search_users'),
    path('about/', views.about, name='about'),
]

