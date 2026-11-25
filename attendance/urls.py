from django.urls import path
from . import views

app_name = 'attendance'

urlpatterns = [
    path('', views.attendance_list, name='list'),
    path('my/', views.my_attendance, name='my_attendance'),
    path('check-in-out/', views.self_check_in_out, name='self_check_in_out'),
    path('create/', views.attendance_manual_entry, name='create'),
    path('<int:pk>/', views.attendance_detail, name='detail'),
    path('<int:pk>/edit/', views.attendance_manual_edit, name='edit'),
    path('<int:pk>/delete/', views.attendance_delete, name='delete'),
    path('ledger/', views.campus_audit_ledger, name='audit_ledger'),

    # Attendance Regularization: Manual Punch Requests
    path('requests/', views.attendance_requests_list, name='requests_list'),
    path('requests/apply/', views.attendance_request_create, name='request_create'),
    path('requests/my/', views.my_punch_requests, name='my_requests'),
    path('requests/<int:pk>/approve/', views.attendance_request_approve, name='request_approve'),
    path('requests/<int:pk>/reject/', views.attendance_request_reject, name='request_reject'),

    # Biometric Face Attendance & Enrollment (Phase 5 & 6)
    path('face-cam/', views.face_kiosk, name='face_kiosk'),
    path('kiosk/<str:company_code>/', views.face_kiosk, name='company_face_kiosk'),
    path('employees/<int:employee_id>/enroll-face/', views.enroll_face, name='enroll_face'),
    path('api/save-sample/<int:employee_id>/', views.api_save_face_sample, name='api_save_face_sample'),
    path('api/reset-face/<int:employee_id>/', views.api_reset_face_data, name='api_reset_face_data'),
    path('api/recognize-face/', views.api_recognize_face, name='api_recognize_face'),
]
