from decimal import Decimal
from datetime import timedelta
import sys
import socket
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Q
from accounts.models import User
from companies.models import Company
from employees.models import Employee
from attendance.models import Attendance
from holidays.models import Holiday
from leaves.models import LeaveApplication
from payroll.models import PayrollRun
import django


def get_local_ip():
    """Returns local LAN IP address for mobile camera / network debugging."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


@login_required
def index(request):
    """
    Main HRMS Dashboard view.
    Adapts metric cards and navigation widgets according to user role.
    """
    user = request.user

    # Aggregate user counts by role
    total_users = User.objects.count()
    super_admins_count = User.objects.filter(role=User.Role.SUPER_ADMIN).count()
    hr_admins_count = User.objects.filter(role=User.Role.HR_ADMIN).count()
    managers_count = User.objects.filter(role=User.Role.MANAGER).count()
    employees_count = User.objects.filter(role=User.Role.EMPLOYEE).count()
    active_users_count = User.objects.filter(is_active=True).count()

    # Corporate & Employee metrics
    total_companies = Company.objects.count()
    total_employees_roster = Employee.objects.count()
    active_employees_roster = Employee.objects.filter(employment_status='active').count()

    # Live Attendance Metrics for Today
    today = timezone.now().date()
    attendance_qs = Attendance.objects.filter(date=today)
    if not user.is_superuser and hasattr(user, 'employee_profile') and user.employee_profile:
        attendance_qs = attendance_qs.filter(company=user.employee_profile.company)

    today_present_count = attendance_qs.filter(status=Attendance.AttendanceStatus.PRESENT).count()
    today_late_count = attendance_qs.filter(is_late=True).count()
    today_half_day_count = attendance_qs.filter(status=Attendance.AttendanceStatus.HALF_DAY).count()
    today_absent_count = attendance_qs.filter(status=Attendance.AttendanceStatus.ABSENT).count()
    today_clocked_in = attendance_qs.filter(check_in_time__isnull=False, check_out_time__isnull=True).count()

    # Employee personal punch record today
    employee_today_attendance = None
    if hasattr(user, 'employee_profile') and user.employee_profile:
        employee_today_attendance = Attendance.objects.filter(
            employee=user.employee_profile, date=today
        ).first()

    # Recent users for the activity table
    recent_users = User.objects.order_by('-date_joined')[:6]

    # Role breakdown data formatted for Chart.js
    role_chart_labels = ['Super Admin', 'HR Admin', 'Manager', 'Employee']
    role_chart_data = [super_admins_count, hr_admins_count, managers_count, employees_count]

    # Dynamic Weekly Attendance Trends (Past 6 Days)
    attendance_trends_labels = []
    attendance_trends_present = []
    attendance_trends_absent = []
    attendance_trends_late = []

    trends_qs = Attendance.objects.all()
    if not user.is_superuser and hasattr(user, 'employee_profile') and user.employee_profile:
        trends_qs = trends_qs.filter(company=user.employee_profile.company)

    for i in range(5, -1, -1):
        target_date = today - timedelta(days=i)
        attendance_trends_labels.append(target_date.strftime('%a %d'))
        day_records = trends_qs.filter(date=target_date)
        attendance_trends_present.append(day_records.filter(status=Attendance.AttendanceStatus.PRESENT).count())
        attendance_trends_absent.append(day_records.filter(status=Attendance.AttendanceStatus.ABSENT).count())
        attendance_trends_late.append(day_records.filter(is_late=True).count())

    # Upcoming holidays for dashboard overview
    upcoming_holidays_qs = Holiday.objects.filter(date__gte=today).order_by('date')
    if not user.is_superuser and hasattr(user, 'employee_profile') and user.employee_profile:
        upcoming_holidays_qs = upcoming_holidays_qs.filter(company=user.employee_profile.company)
    upcoming_holidays = upcoming_holidays_qs[:4]

    # Pending leaves count
    pending_leaves_count = 0
    if user.is_super_admin:
        pending_leaves_count = LeaveApplication.objects.filter(status='pending').count()
    elif user.is_hr_admin and hasattr(user, 'employee_profile') and user.employee_profile:
        pending_leaves_count = LeaveApplication.objects.filter(company=user.employee_profile.company, status='pending').count()
    elif user.is_manager_user and hasattr(user, 'employee_profile') and user.employee_profile:
        pending_leaves_count = LeaveApplication.objects.filter(employee__manager=user.employee_profile, status='pending').count()

    # Latest Payroll Run
    latest_payroll_run = PayrollRun.objects.order_by('-year', '-month').first()
    if not user.is_superuser and hasattr(user, 'employee_profile') and user.employee_profile:
        latest_payroll_run = PayrollRun.objects.filter(company=user.employee_profile.company).order_by('-year', '-month').first()

    # Environment information
    env_info = {
        'python_version': sys.version.split()[0],
        'django_version': django.get_version(),
        'server_time': timezone.now(),
        'local_ip': get_local_ip(),
    }

    context = {
        'total_users': total_users,
        'super_admins_count': super_admins_count,
        'hr_admins_count': hr_admins_count,
        'managers_count': managers_count,
        'employees_count': employees_count,
        'active_users_count': active_users_count,
        'total_companies': total_companies,
        'total_employees_roster': total_employees_roster,
        'active_employees_roster': active_employees_roster,
        'recent_users': recent_users,
        'role_chart_labels': role_chart_labels,
        'role_chart_data': role_chart_data,
        'attendance_trends_labels': attendance_trends_labels,
        'attendance_trends_present': attendance_trends_present,
        'attendance_trends_absent': attendance_trends_absent,
        'attendance_trends_late': attendance_trends_late,
        'today_present_count': today_present_count,
        'today_late_count': today_late_count,
        'today_half_day_count': today_half_day_count,
        'today_absent_count': today_absent_count,
        'today_clocked_in': today_clocked_in,
        'employee_today_attendance': employee_today_attendance,
        'upcoming_holidays': upcoming_holidays,
        'pending_leaves_count': pending_leaves_count,
        'latest_payroll_run': latest_payroll_run,
        'env_info': env_info,
        'is_hr_or_admin': user.is_hr_admin,
        'is_manager': user.is_manager_user,
        'is_employee': user.is_employee_user,
    }

    return render(request, 'dashboard/index.html', context)
