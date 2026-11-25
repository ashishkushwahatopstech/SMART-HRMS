from django.contrib import admin
from .models import Holiday


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ['name', 'company', 'date', 'day_of_week', 'holiday_type', 'is_optional']
    list_filter = ['company', 'holiday_type', 'is_optional', 'date']
    search_fields = ['name', 'description']
    date_hierarchy = 'date'
