from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_dashboard, name='dashboard'),
    path('export/attendance/', views.export_attendance_report, name='export_attendance'),
    path('export/payroll/', views.export_payroll_report, name='export_payroll'),
    path('export/leaves/', views.export_leave_report, name='export_leaves'),
    path('export/employees/', views.export_employee_report, name='export_employees'),
]
