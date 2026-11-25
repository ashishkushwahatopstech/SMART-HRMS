from django.urls import path
from . import views

app_name = 'leaves'

urlpatterns = [
    path('', views.leave_dashboard, name='dashboard'),
    path('apply/', views.leave_apply, name='apply'),
    path('applications/', views.leave_list, name='list'),
    path('applications/<int:pk>/', views.leave_detail, name='detail'),
    path('applications/<int:pk>/approve/', views.leave_approve, name='approve'),
    path('applications/<int:pk>/reject/', views.leave_reject, name='reject'),
    path('applications/<int:pk>/cancel/', views.leave_cancel, name='cancel'),
    path('types/', views.leave_types_list, name='types_list'),
    path('types/create/', views.leave_type_create, name='type_create'),
    path('types/<int:pk>/edit/', views.leave_type_edit, name='type_edit'),
    path('balances/', views.leave_balances_manage, name='balances_manage'),
    path('api/calculate-days/', views.api_calculate_days, name='api_calculate_days'),
]
