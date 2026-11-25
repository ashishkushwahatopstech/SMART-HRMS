from django.urls import path
from . import views

app_name = 'payroll'

urlpatterns = [
    path('', views.payroll_dashboard, name='dashboard'),
    path('runs/create/', views.payroll_run_create, name='run_create'),
    path('runs/<int:pk>/', views.payroll_run_detail, name='run_detail'),
    path('runs/<int:pk>/recalculate/', views.payroll_run_recalculate, name='run_recalculate'),
    path('runs/<int:pk>/lock/', views.payroll_run_lock, name='run_lock'),
    path('payslips/<int:pk>/', views.payslip_detail, name='payslip_detail'),
    path('payslips/<int:pk>/payment/', views.update_payslip_payment, name='update_payment'),
    path('my-payslips/', views.my_payslips, name='my_payslips'),
]
