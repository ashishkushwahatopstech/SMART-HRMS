from django.contrib import admin
from .models import Shift, ShiftAssignment


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'shift_code',
        'company',
        'start_time',
        'end_time',
        'total_expected_hours',
        'is_overnight',
        'grace_period_minutes',
        'is_active',
    )
    list_filter = ('company', 'is_overnight', 'is_active', 'overtime_eligibility')
    search_fields = ('name', 'shift_code')


@admin.register(ShiftAssignment)
class ShiftAssignmentAdmin(admin.ModelAdmin):
    list_display = ('employee', 'shift', 'start_date', 'end_date', 'is_active', 'created_at')
    list_filter = ('shift__company', 'is_active')
    search_fields = ('employee__first_name', 'employee__last_name', 'employee__employee_id', 'shift__name')
