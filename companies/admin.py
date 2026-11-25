from django.contrib import admin
from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'email', 'phone', 'working_days_per_week', 'is_active', 'created_at')
    list_filter = ('is_active', 'weekly_holiday_policy', 'salary_calculation_policy')
    search_fields = ('name', 'code', 'email', 'phone')
    ordering = ('name',)
