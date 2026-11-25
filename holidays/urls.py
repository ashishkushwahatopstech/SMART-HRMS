from django.urls import path
from . import views

app_name = 'holidays'

urlpatterns = [
    path('', views.holiday_list, name='list'),
    path('calendar/', views.holiday_calendar, name='calendar'),
    path('create/', views.holiday_create, name='create'),
    path('<int:pk>/edit/', views.holiday_edit, name='edit'),
    path('<int:pk>/delete/', views.holiday_delete, name='delete'),
    path('api/', views.api_holidays, name='api'),
]
