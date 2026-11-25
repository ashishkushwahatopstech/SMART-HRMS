"""
URL configuration for Smart HRMS project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('companies/', include('companies.urls', namespace='companies')),
    path('employees/', include('employees.urls', namespace='employees')),
    path('shifts/', include('shifts.urls', namespace='shifts')),
    path('attendance/', include('attendance.urls', namespace='attendance')),
    path('holidays/', include('holidays.urls', namespace='holidays')),
    path('leaves/', include('leaves.urls', namespace='leaves')),
    path('payroll/', include('payroll.urls', namespace='payroll')),
    path('reports/', include('reports.urls', namespace='reports')),
    path('', include('dashboard.urls', namespace='dashboard')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
