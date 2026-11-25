from django.urls import path
from . import views

app_name = 'shifts'

urlpatterns = [
    path('', views.shift_list, name='list'),
    path('create/', views.shift_create, name='create'),
    path('<int:pk>/', views.shift_detail, name='detail'),
    path('<int:pk>/edit/', views.shift_edit, name='edit'),
    path('<int:pk>/delete/', views.shift_delete, name='delete'),
    path('<int:pk>/assign/', views.shift_assign, name='assign'),
]
