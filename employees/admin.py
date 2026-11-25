from django.contrib import admin
from .models import Employee, Department, Designation


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'company', 'created_at')
    list_filter = ('company',)
    search_fields = ('name', 'code')


@admin.register(Designation)
class DesignationAdmin(admin.ModelAdmin):
    list_display = ('title', 'department', 'company', 'created_at')
    list_filter = ('company', 'department')
    search_fields = ('title',)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        'employee_id',
        'first_name',
        'last_name',
        'company',
        'department',
        'designation',
        'employment_status',
        'salary_type',
        'monthly_salary',
        'face_registration_status',
        'joining_date',
    )
    list_filter = ('company', 'department', 'employment_status', 'salary_type', 'face_registration_status')
    search_fields = ('employee_id', 'first_name', 'last_name', 'email', 'phone')
    ordering = ('company', 'employee_id')
