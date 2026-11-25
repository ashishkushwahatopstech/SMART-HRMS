from django.contrib import admin
from .models import PayrollRun, Payslip


class PayslipInline(admin.TabularInline):
    model = Payslip
    extra = 0
    fields = ('employee', 'gross_earnings', 'total_deductions', 'net_pay', 'payment_status')
    readonly_fields = ('employee', 'gross_earnings', 'total_deductions', 'net_pay')


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ('company', 'month', 'year', 'status', 'total_employees', 'total_gross', 'total_net_pay', 'created_at')
    list_filter = ('company', 'year', 'month', 'status')
    search_fields = ('company__name', 'company__code')
    inlines = [PayslipInline]


@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = ('employee', 'company', 'month', 'year', 'gross_earnings', 'loss_of_pay_deduction', 'total_deductions', 'net_pay', 'payment_status')
    list_filter = ('company', 'year', 'month', 'payment_status')
    search_fields = ('employee__employee_id', 'employee__first_name', 'employee__last_name', 'payment_reference')
