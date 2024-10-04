from django.urls import path
from .views import login_view, logout_view, register_view, profile_page, add_holiday_request


urlpatterns = [
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('register/', register_view, name='register'),
    path('profile/', profile_page, name='profile_page'),
    path('add_holiday_request', add_holiday_request, name='add_holiday_request')
    # Other URL patterns
]
