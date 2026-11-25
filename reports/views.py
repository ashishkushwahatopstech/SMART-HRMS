from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from companies.models import Company
from .services import (
    generate_attendance_muster,
    generate_payroll_ledger,
    generate_leave_summary,
    generate_employee_directory
)


@login_required
def reports_dashboard(request):
    """
    Reports & Data Export Center.
    Allows HR Admin and Super Admin to download customizable Excel and CSV reports.
    """
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    employee = getattr(user, 'employee_profile', None)

    if user.is_super_admin:
        companies = Company.objects.filter(is_active=True).order_by('name')
    elif employee:
        companies = Company.objects.filter(id=employee.company_id)
    else:
        companies = Company.objects.none()

    current_year = timezone.now().year
    current_month = timezone.now().month

    context = {
        'companies': companies,
        'current_year': current_year,
        'current_month': current_month,
    }
    return render(request, 'reports/reports_dashboard.html', context)


@login_required
def export_attendance_report(request):
    """Download Attendance Muster Sheet (Excel/CSV)."""
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted.")

    company_id = request.GET.get('company_id')
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    fmt = request.GET.get('format', 'excel')

    company = _get_authorized_company(user, company_id)
    return generate_attendance_muster(company, year, month, format=fmt)


@login_required
def export_payroll_report(request):
    """Download Monthly Payroll Ledger (Excel/CSV)."""
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted.")

    company_id = request.GET.get('company_id')
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    fmt = request.GET.get('format', 'excel')

    company = _get_authorized_company(user, company_id)
    return generate_payroll_ledger(company, year, month, format=fmt)


@login_required
def export_leave_report(request):
    """Download Annual Leave Summary (Excel/CSV)."""
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted.")

    company_id = request.GET.get('company_id')
    year = int(request.GET.get('year', timezone.now().year))
    fmt = request.GET.get('format', 'excel')

    company = _get_authorized_company(user, company_id)
    return generate_leave_summary(company, year, format=fmt)


@login_required
def export_employee_report(request):
    """Download Employee Master Directory (Excel/CSV)."""
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted.")

    company_id = request.GET.get('company_id')
    fmt = request.GET.get('format', 'excel')

    company = _get_authorized_company(user, company_id)
    return generate_employee_directory(company, format=fmt)


def _get_authorized_company(user, company_id):
    """Helper to enforce strict multi-company authorization."""
    if user.is_super_admin and company_id:
        return get_object_or_404(Company, id=company_id)

    employee = getattr(user, 'employee_profile', None)
    if not employee:
        raise PermissionDenied("Your user account has no associated company profile.")

    return employee.company
