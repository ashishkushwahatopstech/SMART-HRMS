from django.contrib import admin
from .models import LeaveType, LeaveBalance, LeaveApplication, LeaveApprovalLog


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'company', 'annual_quota', 'is_paid', 'allow_half_day', 'is_carry_forward', 'is_active')
    list_filter = ('company', 'is_paid', 'is_active', 'is_carry_forward')
    search_fields = ('name', 'code', 'company__name')


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'year', 'allocated_days', 'carried_forward_days', 'accrued_days', 'used_days', 'pending_days', 'available_days_display')
    list_filter = ('year', 'leave_type__company', 'leave_type')
    search_fields = ('employee__employee_id', 'employee__first_name', 'employee__last_name', 'leave_type__name')

    def available_days_display(self, obj):
        return obj.available_days
    available_days_display.short_description = 'Available Days'


class LeaveApprovalLogInline(admin.TabularInline):
    model = LeaveApprovalLog
    extra = 0
    readonly_fields = ('action', 'acted_by', 'remarks', 'created_at')


@admin.register(LeaveApplication)
class LeaveApplicationAdmin(admin.ModelAdmin):
    list_display = ('employee', 'company', 'leave_type', 'start_date', 'end_date', 'total_days', 'is_half_day', 'status', 'created_at')
    list_filter = ('status', 'company', 'leave_type', 'is_half_day')
    search_fields = ('employee__employee_id', 'employee__first_name', 'employee__last_name', 'reason')
    inlines = [LeaveApprovalLogInline]


@admin.register(LeaveApprovalLog)
class LeaveApprovalLogAdmin(admin.ModelAdmin):
    list_display = ('application', 'action', 'acted_by', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('application__employee__employee_id', 'acted_by__username', 'remarks')
