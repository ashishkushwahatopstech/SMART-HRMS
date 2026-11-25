from django.contrib import admin
from .models import Attendance, AttendanceAuditLog


class AttendanceAuditLogInline(admin.TabularInline):
    model = AttendanceAuditLog
    extra = 0
    readonly_fields = ['action', 'changed_by', 'field_name', 'old_value', 'new_value', 'reason', 'created_at']
    can_delete = False


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = [
        'employee', 'company', 'date', 'shift', 'status',
        'check_in_time', 'check_out_time', 'total_working_hours',
        'overtime_hours', 'is_late', 'verification_method'
    ]
    list_filter = ['company', 'status', 'is_late', 'verification_method', 'date']
    search_fields = ['employee__first_name', 'employee__last_name', 'employee__employee_id']
    date_hierarchy = 'date'
    inlines = [AttendanceAuditLogInline]


@admin.register(AttendanceAuditLog)
class AttendanceAuditLogAdmin(admin.ModelAdmin):
    list_display = ['attendance', 'action', 'changed_by', 'field_name', 'old_value', 'new_value', 'created_at']
    list_filter = ['action', 'created_at']
    search_fields = ['attendance__employee__employee_id', 'reason', 'changed_by__username']
