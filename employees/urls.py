from django.urls import path
from . import views

app_name = 'employees'

urlpatterns = [
    path('', views.employee_list, name='list'),
    path('create/', views.employee_create, name='create'),
    path('users/', views.user_role_management, name='user_roles'),
    path('<int:pk>/', views.employee_detail, name='detail'),
    path('<int:pk>/edit/', views.employee_edit, name='edit'),
    path('<int:pk>/delete/', views.employee_delete, name='delete'),
    path('<int:pk>/change-role/', views.employee_change_role, name='change_role'),
    path('departments/', views.department_list_create, name='departments'),
    path('designations/', views.designation_list_create, name='designations'),
    path('designations/<int:pk>/delete/', views.designation_delete, name='designation_delete'),
    path('api/company-options/<int:company_id>/', views.api_company_options, name='api_company_options'),
]
