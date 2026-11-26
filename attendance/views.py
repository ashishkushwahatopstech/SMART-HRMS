from decimal import Decimal
from datetime import datetime, date, time, timedelta
from pathlib import Path
import json
import shutil
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count, Sum
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from accounts.decorators import hr_required, role_required
from companies.models import Company
from employees.models import Employee, Department
from shifts.models import Shift
from .models import Attendance, AttendanceAuditLog, ManualPunchRequest
from .forms import (
    AttendanceManualEntryForm,
    AttendanceFilterForm,
    SelfCheckInForm,
    ManualPunchRequestForm,
    ManualPunchReviewForm,
)
from services.email_service import (
    send_punch_regularization_notification,
    send_punch_regularization_status_email,
)
from .biometrics import (
    decode_base64_image,
    detect_faces,
    save_face_sample,
    train_company_recognizer,
    recognize_face_in_frame,
    get_biometric_dir,
)


def get_client_ip(request):
    """Utility to obtain user IP address."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager'])
def attendance_list(request):
    """
    Attendance records roster with multi-company isolation, search, date range,
    department, shift, and status filters.
    """
    attendances = Attendance.objects.select_related(
        'employee', 'company', 'shift', 'employee__department', 'employee__designation'
    ).order_by('-date', 'employee__first_name')

    # Data Isolation
    user_company = None
    if not request.user.is_superuser:
        if hasattr(request.user, 'employee_profile') and request.user.employee_profile:
            user_company = request.user.employee_profile.company
            attendances = attendances.filter(company=user_company)

            # If Manager (not HR admin), optionally restrict to team or department
            if request.user.role == 'manager' and not request.user.is_hr_admin:
                manager_emp = request.user.employee_profile
                # Managers see subordinates or same department
                attendances = attendances.filter(
                    Q(employee__manager=manager_emp) | Q(employee__department=manager_emp.department)
                )
        else:
            attendances = attendances.none()

    # Query Search
    query = request.GET.get('q', '').strip()
    if query:
        attendances = attendances.filter(
            Q(employee__first_name__icontains=query) |
            Q(employee__last_name__icontains=query) |
            Q(employee__employee_id__icontains=query)
        )

    # Date Range Filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        attendances = attendances.filter(date__gte=date_from)
    if date_to:
        attendances = attendances.filter(date__lte=date_to)

    # Department Filter
    dept_id = request.GET.get('department')
    if dept_id:
        attendances = attendances.filter(employee__department_id=dept_id)

    # Shift Filter
    shift_id = request.GET.get('shift')
    if shift_id:
        attendances = attendances.filter(shift_id=shift_id)

    # Status Filter
    status_filter = request.GET.get('status')
    if status_filter:
        attendances = attendances.filter(status=status_filter)

    # Summary Statistics for filtered records
    stats = attendances.aggregate(
        total=Count('id'),
        present_count=Count('id', filter=Q(status=Attendance.AttendanceStatus.PRESENT)),
        late_count=Count('id', filter=Q(is_late=True)),
        half_day_count=Count('id', filter=Q(status=Attendance.AttendanceStatus.HALF_DAY)),
        absent_count=Count('id', filter=Q(status=Attendance.AttendanceStatus.ABSENT)),
        total_overtime=Sum('overtime_hours'),
    )

    filter_form = AttendanceFilterForm(request.GET, user=request.user)
    dept_qs_company = user_company or Company.objects.filter(is_active=True).first()
    departments = Department.objects.filter(company=dept_qs_company) if dept_qs_company else Department.objects.all()

    # View Mode: 'log' (default list), 'by_date' (date-centric), 'by_employee' (employee-centric)
    view_mode = request.GET.get('view', 'log').strip().lower()
    if view_mode not in ['log', 'by_date', 'by_employee']:
        view_mode = 'log'

    # URL query string helpers so view switching and pagination preserve filters
    query_params = request.GET.copy()
    query_params.pop('page', None)
    base_qs = query_params.urlencode()

    query_params_no_view = query_params.copy()
    query_params_no_view.pop('view', None)
    filter_qs = query_params_no_view.urlencode()

    page_number = request.GET.get('page')
    date_groups = []
    employee_groups = []

    if view_mode == 'by_date':
        # Group attendance records by distinct dates
        distinct_dates = attendances.order_by('-date').values_list('date', flat=True).distinct()
        date_paginator = Paginator(distinct_dates, 7)
        page_obj = date_paginator.get_page(page_number)
        current_dates = list(page_obj)

        if current_dates:
            date_attendances = attendances.filter(date__in=current_dates).select_related(
                'employee', 'company', 'shift', 'employee__department', 'employee__designation'
            ).order_by('-date', 'employee__first_name', 'employee__last_name')

            from collections import defaultdict
            records_by_date = defaultdict(list)
            for att in date_attendances:
                records_by_date[att.date].append(att)

            for dt in current_dates:
                records = records_by_date[dt]
                p_cnt = sum(1 for r in records if r.status == Attendance.AttendanceStatus.PRESENT)
                l_cnt = sum(1 for r in records if r.is_late)
                h_cnt = sum(1 for r in records if r.status == Attendance.AttendanceStatus.HALF_DAY)
                a_cnt = sum(1 for r in records if r.status == Attendance.AttendanceStatus.ABSENT)
                lunch_active_cnt = sum(1 for r in records if r.lunch_start_time and not r.lunch_end_time)
                tot_hours = sum((r.total_working_hours for r in records if r.total_working_hours), Decimal('0.00'))
                tot_ot = sum((r.overtime_hours for r in records if r.overtime_hours), Decimal('0.00'))

                date_groups.append({
                    'date': dt,
                    'records': records,
                    'total': len(records),
                    'present_count': p_cnt,
                    'late_count': l_cnt,
                    'half_day_count': h_cnt,
                    'absent_count': a_cnt,
                    'lunch_active_count': lunch_active_cnt,
                    'total_hours': tot_hours,
                    'total_ot': tot_ot,
                })

    elif view_mode == 'by_employee':
        # Group attendance records by employee
        emp_qs = Employee.objects.select_related('department', 'designation', 'assigned_shift', 'company')
        if user_company:
            emp_qs = emp_qs.filter(company=user_company)
        if request.user.role == 'manager' and not request.user.is_hr_admin:
            manager_emp = getattr(request.user, 'employee_profile', None)
            if manager_emp:
                emp_qs = emp_qs.filter(Q(manager=manager_emp) | Q(department=manager_emp.department))
            else:
                emp_qs = emp_qs.none()
        if query:
            emp_qs = emp_qs.filter(
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(employee_id__icontains=query)
            )
        if dept_id:
            emp_qs = emp_qs.filter(department_id=dept_id)
        if shift_id:
            emp_qs = emp_qs.filter(assigned_shift_id=shift_id)

        emp_qs = emp_qs.exclude(employment_status__in=['terminated', 'resigned']).order_by('first_name', 'last_name')
        emp_paginator = Paginator(emp_qs, 12)
        page_obj = emp_paginator.get_page(page_number)
        current_employees = list(page_obj)

        if current_employees:
            emp_attendances = attendances.filter(employee__in=current_employees).order_by('-date', '-check_in_time')
            from collections import defaultdict
            att_by_emp = defaultdict(list)
            for att in emp_attendances:
                att_by_emp[att.employee_id].append(att)

            today_val = timezone.localdate()
            for emp in current_employees:
                records = att_by_emp[emp.id]
                tot_days = len(records)
                p_cnt = sum(1 for r in records if r.status in [Attendance.AttendanceStatus.PRESENT, Attendance.AttendanceStatus.HALF_DAY])
                l_cnt = sum(1 for r in records if r.is_late)
                a_cnt = sum(1 for r in records if r.status == Attendance.AttendanceStatus.ABSENT)
                tot_hours = sum((r.total_working_hours for r in records if r.total_working_hours), Decimal('0.00'))
                tot_ot = sum((r.overtime_hours for r in records if r.overtime_hours), Decimal('0.00'))
                today_record = next((r for r in records if r.date == today_val), None)

                employee_groups.append({
                    'employee': emp,
                    'records': records[:25],
                    'total_records_count': tot_days,
                    'present_count': p_cnt,
                    'late_count': l_cnt,
                    'absent_count': a_cnt,
                    'total_hours': tot_hours,
                    'total_ot': tot_ot,
                    'today_record': today_record,
                })

    else:
        # Default: log view
        paginator = Paginator(attendances, 15)
        page_obj = paginator.get_page(page_number)

    return render(request, 'attendance/attendance_list.html', {
        'page_obj': page_obj,
        'filter_form': filter_form,
        'query': query,
        'stats': stats,
        'date_from': date_from,
        'date_to': date_to,
        'departments': departments,
        'selected_department': request.GET.get('department', ''),
        'view_mode': view_mode,
        'date_groups': date_groups,
        'employee_groups': employee_groups,
        'base_qs': base_qs,
        'filter_qs': filter_qs,
    })


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager', 'employee'])
def attendance_detail(request, pk):
    """
    Shows full breakdown of an attendance record, punch times, calculated durations,
    and compliance audit trail history.
    """
    att = Attendance.objects.select_related(
        'employee', 'company', 'shift', 'employee__department', 'employee__designation'
    ).filter(pk=pk).first()

    if not att:
        messages.error(request, "Attendance record does not exist or has already been removed.")
        return redirect('attendance:list')

    # Data Isolation & Privacy Safeguard
    if not request.user.is_superuser:
        if not hasattr(request.user, 'employee_profile') or not request.user.employee_profile:
            messages.error(request, "Access denied.")
            return redirect('dashboard:index')

        user_emp = request.user.employee_profile
        # Company isolation
        if user_emp.company_id != att.company_id:
            messages.error(request, "Access denied. Record belongs to another company.")
            return redirect('attendance:list')

        # Employee privacy safeguard: regular employee can only view own record
        if request.user.role == 'employee' and att.employee_id != user_emp.id:
            messages.error(request, "Access denied. You can only view your own attendance records.")
            return redirect('attendance:my_attendance')

    audit_logs = att.audit_logs.select_related('changed_by').order_by('-created_at')

    return render(request, 'attendance/attendance_detail.html', {
        'attendance': att,
        'audit_logs': audit_logs,
    })


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager', 'employee'])
def my_attendance(request):
    """
    Self-service portal for logged-in employee to review personal attendance records,
    monthly stats, and perform web check-in / check-out.
    """
    if not hasattr(request.user, 'employee_profile') or not request.user.employee_profile:
        messages.warning(request, "No employee profile linked to your user account. Self check-in is unavailable.")
        return redirect('dashboard:index')

    employee = request.user.employee_profile
    today = timezone.localdate()

    # Fetch today's record
    today_attendance = Attendance.objects.filter(employee=employee, date=today).first()

    # Personal attendance history
    history = Attendance.objects.filter(employee=employee).order_by('-date')

    # Month filter (defaults to current month)
    selected_month = request.GET.get('month', today.strftime('%Y-%m'))
    try:
        y, m = map(int, selected_month.split('-'))
        history = history.filter(date__year=y, date__month=m)
    except (ValueError, TypeError):
        selected_month = today.strftime('%Y-%m')

    # Stats for the selected month
    monthly_stats = history.aggregate(
        total_days=Count('id'),
        present_days=Count('id', filter=Q(status=Attendance.AttendanceStatus.PRESENT)),
        late_days=Count('id', filter=Q(is_late=True)),
        half_days=Count('id', filter=Q(status=Attendance.AttendanceStatus.HALF_DAY)),
        absent_days=Count('id', filter=Q(status=Attendance.AttendanceStatus.ABSENT)),
        overtime_hours=Sum('overtime_hours'),
        working_hours=Sum('total_working_hours'),
    )

    paginator = Paginator(history, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    check_in_form = SelfCheckInForm()

    # Manual punch requests submitted by this employee
    recent_requests = ManualPunchRequest.objects.filter(employee=employee).order_by('-date', '-created_at')[:8]
    can_manual_punch = request.user.role in ['super_admin', 'hr_admin', 'manager']
    has_face_enrolled = bool(employee.face_registration_status and employee.face_samples_count >= 1)

    return render(request, 'attendance/my_attendance.html', {
        'employee': employee,
        'today_attendance': today_attendance,
        'today': today,
        'page_obj': page_obj,
        'selected_month': selected_month,
        'stats': monthly_stats,
        'check_in_form': check_in_form,
        'recent_requests': recent_requests,
        'can_manual_punch': can_manual_punch,
        'has_face_enrolled': has_face_enrolled,
    })


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager', 'employee'])
def self_check_in_out(request):
    """
    Handles one-click check-in or check-out button for Managers and HR/Super Admins.
    Regular employees must punch in/out using the Face Recognition Camera.
    """
    if request.method != 'POST':
        return redirect('attendance:my_attendance')

    # Security check: Restrict manual web punch to Manager, HR Admin, or Super Admin
    if request.user.role == 'employee':
        messages.error(
            request,
            "Direct manual web punch is disabled for employees. You must mark your attendance via the Face Recognition Camera. For previous missed punches, please submit a Manual Punch Request."
        )
        return redirect('attendance:my_attendance')

    if not hasattr(request.user, 'employee_profile') or not request.user.employee_profile:
        messages.error(request, "No employee record found for your user account.")
        return redirect('dashboard:index')

    employee = request.user.employee_profile
    now = timezone.now()
    local_now = timezone.localtime(now)
    today = local_now.date()
    ip_addr = get_client_ip(request)
    form = SelfCheckInForm(request.POST)
    notes = form.cleaned_data['notes'] if form.is_valid() else ''

    # Check if record for today already exists
    att = Attendance.objects.filter(employee=employee, date=today).first()

    if not att:
        # Check-in action
        att = Attendance.objects.create(
            employee=employee,
            company=employee.company,
            date=today,
            shift=employee.assigned_shift,
            check_in_time=now,
            verification_method=Attendance.VerificationMethod.MANUAL_WEB,
            notes=notes,
            ip_address=ip_addr,
        )
        messages.success(request, f"Check-In recorded at {local_now.strftime('%I:%M %p')}. Have a productive day!")
    elif not att.check_out_time:
        # Check-out action
        att.check_out_time = now
        if notes:
            att.notes = f"{att.notes} | Out Note: {notes}".strip(' |')
        att.save()
        messages.success(
            request,
            f"Check-Out recorded at {local_now.strftime('%I:%M %p')}. Total Hours: {att.total_working_hours} hrs."
        )
    else:
        messages.info(request, "You have already completed check-in and check-out for today.")

    return redirect('attendance:my_attendance')


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager'])
def attendance_manual_entry(request):
    """
    Manager / HR / Super Admin manual creation of an employee's attendance record with audit logging.
    """
    if request.method == 'POST':
        form = AttendanceManualEntryForm(request.POST, user=request.user)
        if form.is_valid():
            att = form.save(commit=False)
            reason = form.cleaned_data['adjustment_reason']

            # Enforce user company if not superuser
            if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
                att.company = request.user.employee_profile.company

            # Manager team boundary check
            if request.user.role == 'manager' and not request.user.is_hr_admin:
                manager_emp = request.user.employee_profile
                if att.employee.manager_id != manager_emp.id and att.employee.department_id != manager_emp.department_id:
                    messages.error(request, "Access denied. You can only enter attendance for your assigned team members.")
                    return redirect('attendance:list')

            # Check if record already exists for this employee on this date
            if Attendance.objects.filter(employee=att.employee, date=att.date).exists():
                form.add_error('date', 'An attendance record already exists for this employee on the selected date.')
            else:
                att.save()

                # Record mandatory audit entry
                AttendanceAuditLog.objects.create(
                    attendance=att,
                    action='Manual Attendance Created',
                    changed_by=request.user,
                    field_name='all',
                    old_value='None',
                    new_value=f"Status: {att.status}, In: {att.check_in_time}, Out: {att.check_out_time}",
                    reason=reason
                )

                messages.success(request, f"Attendance record for {att.employee.get_full_name()} created successfully.")
                return redirect('attendance:detail', pk=att.pk)
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = AttendanceManualEntryForm(user=request.user)

    return render(request, 'attendance/attendance_form.html', {
        'form': form,
        'title': 'Manual Attendance Entry',
        'is_edit': False,
    })


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager'])
def attendance_manual_edit(request, pk):
    """
    Manager / HR / Super Admin manual adjustment of an existing attendance record.
    Compares modified fields and logs an audit log entry for compliance.
    """
    att = Attendance.objects.filter(pk=pk).first()
    if not att:
        messages.error(request, "Attendance record does not exist or has already been removed.")
        return redirect('attendance:list')

    # Company Isolation & Manager Boundary
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != att.company_id:
            messages.error(request, "Access denied.")
            return redirect('attendance:list')

        if request.user.role == 'manager' and not request.user.is_hr_admin:
            manager_emp = request.user.employee_profile
            if att.employee.manager_id != manager_emp.id and att.employee.department_id != manager_emp.department_id:
                messages.error(request, "Access denied. Employee is not in your assigned team or department.")
                return redirect('attendance:list')

    if request.method == 'POST':
        # Capture old values
        old_status = att.status
        old_in = att.check_in_time
        old_out = att.check_out_time
        old_method = att.verification_method

        form = AttendanceManualEntryForm(request.POST, instance=att, user=request.user)
        if form.is_valid():
            reason = form.cleaned_data['adjustment_reason']
            updated_att = form.save(commit=False)
            updated_att.verification_method = Attendance.VerificationMethod.ADMIN_ADJUSTMENT
            updated_att.save()

            # Audit log changed fields
            changes = []
            if old_status != updated_att.status:
                changes.append(f"Status changed from '{old_status}' to '{updated_att.status}'")
            if old_in != updated_att.check_in_time:
                changes.append(f"Check-In changed from '{old_in}' to '{updated_att.check_in_time}'")
            if old_out != updated_att.check_out_time:
                changes.append(f"Check-Out changed from '{old_out}' to '{updated_att.check_out_time}'")

            log_desc = "; ".join(changes) if changes else "Record details adjusted"
            AttendanceAuditLog.objects.create(
                attendance=updated_att,
                action='Manual Attendance Adjusted',
                changed_by=request.user,
                field_name='status/punches',
                old_value=f"Status: {old_status}, In: {old_in}, Out: {old_out}",
                new_value=f"Status: {updated_att.status}, In: {updated_att.check_in_time}, Out: {updated_att.check_out_time}",
                reason=reason
            )

            messages.success(request, f"Attendance record for {updated_att.employee.get_full_name()} updated with audit trail.")
            return redirect('attendance:detail', pk=updated_att.pk)
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = AttendanceManualEntryForm(instance=att, user=request.user)

    return render(request, 'attendance/attendance_form.html', {
        'form': form,
        'attendance': att,
        'title': f'Adjust Attendance: {att.employee.get_full_name()} ({att.date})',
        'is_edit': True,
    })


@role_required(allowed_roles=['super_admin', 'hr_admin'])
def attendance_delete(request, pk):
    """
    Allows HR Admin or Super Admin to delete an attendance record with mandatory business justification.
    In accordance with blockchain governance, the record snapshot is permanently minted into
    the immutable Campus Audit Ledger before removal from active records.
    """
    att = Attendance.objects.select_related('employee', 'company', 'shift').filter(pk=pk).first()
    if not att:
        messages.error(request, "Attendance record not found or already deleted.")
        return redirect('attendance:list')

    # Data Isolation Check
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != att.company_id:
            messages.error(request, "Access denied. Record belongs to another company.")
            return redirect('attendance:list')

    next_url = request.GET.get('next') or request.POST.get('next') or reverse('attendance:list')

    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, "A mandatory business reason is required to delete an attendance record.")
            return render(request, 'attendance/attendance_confirm_delete.html', {
                'attendance': att,
                'next_url': next_url,
            })

        # Capture complete serialized snapshot of the attendance record before deletion
        snapshot = att.to_snapshot()
        emp_name = att.employee.get_full_name()
        emp_code = att.employee.employee_id
        att_date = att.date
        comp = att.company

        # Mint permanent immutable blockchain audit block
        audit_entry = AttendanceAuditLog(
            attendance=None,  # Decouple so active record deletion leaves this permanent block intact
            company=comp,
            employee_name=emp_name,
            employee_id_code=emp_code,
            attendance_date=att_date,
            action='Attendance Record Deleted',
            changed_by=request.user,
            field_name='all',
            old_value=f"Status: {att.status}, In: {att.check_in_time}, Out: {att.check_out_time}, Hours: {att.total_working_hours}",
            new_value='DELETED_FROM_ACTIVE_ROSTER',
            reason=reason,
            snapshot=snapshot,
            ip_address=get_client_ip(request)
        )
        audit_entry.save()

        # Delete active record
        att.delete()

        messages.success(
            request,
            f"Attendance record for {emp_name} ({att_date}) has been deleted. Action permanently minted as Block #{audit_entry.block_index} in the Campus Blockchain Ledger."
        )
        return redirect(next_url)

    return render(request, 'attendance/attendance_confirm_delete.html', {
        'attendance': att,
        'next_url': next_url,
    })


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager', 'employee'])
def campus_audit_ledger(request):
    """
    Publicly transparent Campus Attendance Audit Ledger & Blockchain Trail.
    Accessible to all authenticated campus employees, staff, and administrators.
    Provides verifiable, cryptographic proof of all attendance actions, edits, and deletions.
    """
    company = None
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        company = request.user.employee_profile.company
        logs = AttendanceAuditLog.objects.filter(company=company)
    else:
        # Superuser: option to filter by company
        comp_id = request.GET.get('company')
        if comp_id:
            company = Company.objects.filter(id=comp_id).first()
            logs = AttendanceAuditLog.objects.filter(company=company)
        else:
            logs = AttendanceAuditLog.objects.all()

    companies = Company.objects.filter(is_active=True) if request.user.is_superuser else []

    # Search & Filters
    q = request.GET.get('q', '').strip()
    if q:
        logs = logs.filter(
            Q(employee_name__icontains=q) |
            Q(employee_id_code__icontains=q) |
            Q(reason__icontains=q) |
            Q(action__icontains=q) |
            Q(block_hash__icontains=q)
        )

    action_filter = request.GET.get('action')
    if action_filter:
        logs = logs.filter(action=action_filter)

    date_from = request.GET.get('date_from')
    if date_from:
        logs = logs.filter(created_at__date__gte=date_from)

    date_to = request.GET.get('date_to')
    if date_to:
        logs = logs.filter(created_at__date__lte=date_to)

    # Aggregate Metrics
    total_blocks = logs.count()
    deleted_blocks_count = logs.filter(action__icontains='Deleted').count()
    adjustments_count = logs.filter(action__icontains='Adjusted').count()
    creations_count = logs.filter(action__icontains='Created').count()
    regularizations_count = logs.filter(action__icontains='Approved').count()

    # Distinct action choices for filter dropdown
    distinct_actions = AttendanceAuditLog.objects.values_list('action', flat=True).distinct()

    # Pagination: 20 blocks per page
    paginator = Paginator(logs.select_related('changed_by'), 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'attendance/campus_audit_ledger.html', {
        'page_obj': page_obj,
        'company': company,
        'companies': companies,
        'q': q,
        'action_filter': action_filter,
        'distinct_actions': distinct_actions,
        'date_from': date_from,
        'date_to': date_to,
        'total_blocks': total_blocks,
        'deleted_blocks_count': deleted_blocks_count,
        'adjustments_count': adjustments_count,
        'creations_count': creations_count,
        'regularizations_count': regularizations_count,
    })


# ==============================================================================
# ATTENDANCE REGULARIZATION: MANUAL PUNCH REQUESTS & APPROVALS
# ==============================================================================

@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager', 'employee'])
def attendance_request_create(request):
    """
    Form for employees to request manual attendance punch for missed/forgotten previous days.
    """
    if not hasattr(request.user, 'employee_profile') or not request.user.employee_profile:
        messages.error(request, "No employee profile linked to your user account.")
        return redirect('dashboard:index')

    employee = request.user.employee_profile

    if request.method == 'POST':
        form = ManualPunchRequestForm(request.POST, employee=employee)
        if form.is_valid():
            req = form.save(commit=False)
            req.employee = employee
            req.company = employee.company
            req.save()

            # Dispatch notification email to Manager and HR Admin
            send_punch_regularization_notification(req, request=request)

            messages.success(
                request,
                f"Manual punch request for {req.date.strftime('%d %b %Y')} submitted successfully. Awaiting Manager / HR approval."
            )
            return redirect('attendance:my_attendance')
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = ManualPunchRequestForm(employee=employee)

    return render(request, 'attendance/punch_request_form.html', {
        'form': form,
        'employee': employee,
    })


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager'])
def attendance_requests_list(request):
    """
    Management roster of employee manual punch requests.
    Managers see subordinates / department; HR Admin & Super Admin see company requests.
    """
    requests_qs = ManualPunchRequest.objects.select_related(
        'employee', 'company', 'employee__department', 'reviewed_by'
    ).order_by('-created_at')

    # Data Isolation & Manager Boundary
    user_company = None
    if not request.user.is_superuser:
        if hasattr(request.user, 'employee_profile') and request.user.employee_profile:
            user_company = request.user.employee_profile.company
            requests_qs = requests_qs.filter(company=user_company)

            if request.user.role == 'manager' and not request.user.is_hr_admin:
                manager_emp = request.user.employee_profile
                requests_qs = requests_qs.filter(
                    Q(employee__manager=manager_emp) | Q(employee__department=manager_emp.department)
                )
        else:
            requests_qs = requests_qs.none()

    # Base queryset for counts
    base_qs = requests_qs

    # Status tab filter (defaults to 'all')
    status_tab = request.GET.get('status', 'all')
    if status_tab in ['pending', 'approved', 'rejected']:
        requests_qs = requests_qs.filter(status=status_tab)

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        requests_qs = requests_qs.filter(
            Q(employee__first_name__icontains=q) |
            Q(employee__last_name__icontains=q) |
            Q(employee__employee_id__icontains=q) |
            Q(reason__icontains=q)
        )

    counts = {
        'all': base_qs.count(),
        'pending': base_qs.filter(status=ManualPunchRequest.RequestStatus.PENDING).count(),
        'approved': base_qs.filter(status=ManualPunchRequest.RequestStatus.APPROVED).count(),
        'rejected': base_qs.filter(status=ManualPunchRequest.RequestStatus.REJECTED).count(),
    }

    paginator = Paginator(requests_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    review_form = ManualPunchReviewForm()

    return render(request, 'attendance/punch_requests_list.html', {
        'page_obj': page_obj,
        'status_tab': status_tab,
        'query': q,
        'counts': counts,
        'review_form': review_form,
    })


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager'])
def attendance_request_approve(request, pk):
    """
    Approves an employee's manual punch request and automatically creates/updates
    the corresponding Attendance record with punctuality/overtime recalculations and audit log.
    """
    if request.method != 'POST':
        return redirect('attendance:requests_list')

    punch_req = get_object_or_404(ManualPunchRequest, pk=pk)

    # Permission & Isolation Check
    if not request.user.is_superuser:
        if not hasattr(request.user, 'employee_profile') or not request.user.employee_profile:
            messages.error(request, "Access denied.")
            return redirect('attendance:requests_list')

        if request.user.employee_profile.company_id != punch_req.company_id:
            messages.error(request, "Access denied. Request belongs to another company.")
            return redirect('attendance:requests_list')

        if request.user.role == 'manager' and not request.user.is_hr_admin:
            manager_emp = request.user.employee_profile
            is_subordinate = (
                punch_req.employee.manager_id == manager_emp.id or
                punch_req.employee.department_id == manager_emp.department_id
            )
            if not is_subordinate:
                messages.error(request, "Access denied. Employee is not in your assigned team.")
                return redirect('attendance:requests_list')

    review_remarks = request.POST.get('review_remarks', '').strip()

    # Get or create Attendance record for that employee & date
    att = Attendance.objects.filter(employee=punch_req.employee, date=punch_req.date).first()
    is_new = False
    if not att:
        is_new = True
        att = Attendance(
            employee=punch_req.employee,
            company=punch_req.company,
            date=punch_req.date,
            shift=punch_req.employee.assigned_shift,
        )

    # Build timezone aware timestamps
    tz = timezone.get_current_timezone()
    if punch_req.check_in_time:
        att.check_in_time = timezone.make_aware(
            datetime.combine(punch_req.date, punch_req.check_in_time), tz
        )

    if punch_req.check_out_time:
        out_date = punch_req.date
        if punch_req.check_in_time and punch_req.check_out_time < punch_req.check_in_time:
            out_date = punch_req.date + timedelta(days=1)
        att.check_out_time = timezone.make_aware(
            datetime.combine(out_date, punch_req.check_out_time), tz
        )

    att.verification_method = Attendance.VerificationMethod.ADMIN_ADJUSTMENT
    reg_note = f"Manual punch request approved by {request.user.get_display_name()}. Reason: {punch_req.reason}"
    if review_remarks:
        reg_note += f" | Remarks: {review_remarks}"
    att.notes = f"{att.notes} | {reg_note}".strip(' |')
    att.save()

    # Record mandatory compliance audit trail
    AttendanceAuditLog.objects.create(
        attendance=att,
        action='Manual Punch Request Approved',
        changed_by=request.user,
        field_name='all',
        old_value='Created' if is_new else 'Updated',
        new_value=f"Status: {att.status}, In: {att.check_in_time}, Out: {att.check_out_time}",
        reason=f"Approved manual punch request #{punch_req.id}: {punch_req.reason}"
    )

    punch_req.status = ManualPunchRequest.RequestStatus.APPROVED
    punch_req.reviewed_by = request.user
    punch_req.reviewed_at = timezone.now()
    punch_req.review_remarks = review_remarks
    punch_req.save()

    # Dispatch approval notification email to employee
    send_punch_regularization_status_email(punch_req, status='approved', remarks=review_remarks, request=request)

    messages.success(
        request,
        f"Approved manual punch request for {punch_req.employee.get_full_name()} ({punch_req.date}). Attendance record updated ({att.get_status_display()})."
    )
    return redirect('attendance:requests_list')


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager'])
def attendance_request_reject(request, pk):
    """
    Rejects an employee's manual punch request with reviewer remarks.
    """
    if request.method != 'POST':
        return redirect('attendance:requests_list')

    punch_req = get_object_or_404(ManualPunchRequest, pk=pk)

    # Permission & Isolation Check
    if not request.user.is_superuser:
        if not hasattr(request.user, 'employee_profile') or not request.user.employee_profile:
            messages.error(request, "Access denied.")
            return redirect('attendance:requests_list')

        if request.user.employee_profile.company_id != punch_req.company_id:
            messages.error(request, "Access denied.")
            return redirect('attendance:requests_list')

        if request.user.role == 'manager' and not request.user.is_hr_admin:
            manager_emp = request.user.employee_profile
            is_subordinate = (
                punch_req.employee.manager_id == manager_emp.id or
                punch_req.employee.department_id == manager_emp.department_id
            )
            if not is_subordinate:
                messages.error(request, "Access denied. Employee is not in your assigned team.")
                return redirect('attendance:requests_list')

    review_remarks = request.POST.get('review_remarks', '').strip()
    punch_req.status = ManualPunchRequest.RequestStatus.REJECTED
    punch_req.reviewed_by = request.user
    punch_req.reviewed_at = timezone.now()
    punch_req.review_remarks = review_remarks
    punch_req.save()

    # Dispatch rejection notification email to employee
    send_punch_regularization_status_email(punch_req, status='rejected', remarks=review_remarks, request=request)

    messages.info(
        request,
        f"Manual punch request for {punch_req.employee.get_full_name()} ({punch_req.date}) has been rejected."
    )
    return redirect('attendance:requests_list')


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager', 'employee'])
def my_punch_requests(request):
    """
    Personal history ledger of manual punch requests for logged in employee.
    """
    if not hasattr(request.user, 'employee_profile') or not request.user.employee_profile:
        messages.error(request, "No employee record found for your user account.")
        return redirect('dashboard:index')

    employee = request.user.employee_profile
    requests_qs = ManualPunchRequest.objects.filter(employee=employee).order_by('-date', '-created_at')

    paginator = Paginator(requests_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'attendance/my_punch_requests.html', {
        'page_obj': page_obj,
        'employee': employee,
    })



# ==============================================================================
# PHASE 5 & 6: BIOMETRIC FACE ENROLLMENT & LIVE ATTENDANCE KIOSK
# ==============================================================================

@hr_required
def enroll_face(request, employee_id):
    """
    Biometric face enrollment interface for an employee.
    Captures live webcam / mobile camera frames and trains the company's recognizer.
    """
    employee = get_object_or_404(Employee.objects.select_related('company', 'department'), pk=employee_id)

    # Data Isolation
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != employee.company_id:
            messages.error(request, "Access denied. Employee belongs to another company.")
            return redirect('employees:list')

    # Existing captured samples
    emp_dir = get_biometric_dir(employee.company.code, employee.employee_id)
    sample_files = sorted([f.name for f in emp_dir.glob("sample_*.jpg")])

    return render(request, 'attendance/face_enrollment.html', {
        'employee': employee,
        'sample_files': sample_files,
        'samples_count': len(sample_files),
        'biometric_engine': getattr(settings, 'BIOMETRIC_ENGINE', 'onnx').upper(),
    })


@csrf_exempt
@hr_required
def api_save_face_sample(request, employee_id):
    """
    AJAX endpoint to receive a live video frame from the enrollment camera,
    detect face, crop normalized sample, and save to disk.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)

    employee = get_object_or_404(Employee, pk=employee_id)

    # Data Isolation
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != employee.company_id:
            return JsonResponse({'status': 'error', 'message': 'Unauthorized company'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
        image_base64 = data.get('image', '')
        sample_idx = int(data.get('sample_index', 1))

        if not image_base64:
            return JsonResponse({'status': 'error', 'message': 'No image data provided'}, status=400)

        image_bgr = decode_base64_image(image_base64)
        if image_bgr is None:
            return JsonResponse({'status': 'error', 'message': 'Invalid image format'}, status=400)

        success, msg, box = save_face_sample(employee, image_bgr, sample_index=sample_idx)

        if success:
            return JsonResponse({
                'status': 'success',
                'message': msg,
                'sample_index': sample_idx,
                'total_samples': employee.face_samples_count,
                'is_enrolled': employee.face_registration_status,
                'box': box,
            })
        else:
            return JsonResponse({'status': 'warning', 'message': msg})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@hr_required
def api_reset_face_data(request, employee_id):
    """
    Resets an employee's face enrollment data and deletes stored samples.
    """
    employee = get_object_or_404(Employee, pk=employee_id)

    # Data Isolation
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != employee.company_id:
            messages.error(request, "Access denied.")
            return redirect('employees:list')

    emp_dir = get_biometric_dir(employee.company.code, employee.employee_id)
    if emp_dir.exists():
        shutil.rmtree(emp_dir, ignore_errors=True)

    employee.face_registration_status = False
    employee.face_samples_count = 0
    employee.save(update_fields=['face_registration_status', 'face_samples_count'])

    # Retrain company model
    train_company_recognizer(employee.company)

    messages.success(request, f"Biometric data for {employee.get_full_name()} has been reset.")
    return redirect('attendance:enroll_face', employee_id=employee.pk)


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager'])
def face_kiosk(request, company_code=None):
    """
    Universal Contactless Face Recognition Terminal:
    - Dedicated Universal Kiosk: `/attendance/kiosk/<company_code>/`
    - In-App Universal Terminal: `/attendance/face-cam/`
    Universal access allows any employee of that company to walk up to the camera,
    show their face, and record instant verified attendance without needing prior login.
    """
    company = None
    if company_code:
        company = Company.objects.filter(code__iexact=company_code, is_active=True).first()

    if not company:
        # Check query string
        comp_id = request.GET.get('company')
        comp_code_param = request.GET.get('company_code')
        if comp_code_param:
            company = Company.objects.filter(code__iexact=comp_code_param, is_active=True).first()
        elif comp_id:
            company = Company.objects.filter(id=comp_id, is_active=True).first()

    if not company:
        if request.user.is_authenticated and not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
            company = request.user.employee_profile.company
        else:
            company = Company.objects.filter(is_active=True).first()

    is_super = request.user.is_authenticated and request.user.is_superuser
    companies = Company.objects.filter(is_active=True) if is_super else ([company] if company else [])

    # Today's attendance events for the company
    today = timezone.localdate()
    today_punches = Attendance.objects.filter(
        company=company,
        date=today,
    ).select_related('employee', 'employee__department').order_by('-updated_at')

    departments = Department.objects.filter(company=company) if company else Department.objects.none()
    active_in_count = today_punches.filter(check_in_time__isnull=False, check_out_time__isnull=True).count()
    completed_out_count = today_punches.filter(check_in_time__isnull=False, check_out_time__isnull=False).count()

    # Enrolled employees count
    enrolled_count = Employee.objects.filter(company=company, face_registration_status=True).count()
    total_staff = Employee.objects.filter(company=company, employment_status='active').count()

    universal_kiosk_url = request.build_absolute_uri(
        reverse('attendance:company_face_kiosk', kwargs={'company_code': company.code})
    ) if company else request.build_absolute_uri(reverse('attendance:face_kiosk'))

    return render(request, 'attendance/face_kiosk.html', {
        'company': company,
        'companies': companies,
        'today_punches': today_punches,
        'recent_punches': today_punches,  # backward compatibility
        'departments': departments,
        'active_in_count': active_in_count,
        'completed_out_count': completed_out_count,
        'enrolled_count': enrolled_count,
        'total_staff': total_staff,
        'today': today,
        'universal_kiosk_url': universal_kiosk_url,
        'biometric_engine': getattr(settings, 'BIOMETRIC_ENGINE', 'onnx').upper(),
    })


@csrf_exempt
def api_recognize_face(request):
    """
    Live recognition API called continuously by the Kiosk stream.
    Detects face, recognizes employee, applies anti-flood cooldown,
    and automatically registers attendance check-in or check-out.
    Restricted to authenticated HR / Manager / Admin kiosk sessions.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({'matched': False, 'message': 'Access denied: Authentication required.'}, status=401)

    is_terminal_operator = request.user.role in ['super_admin', 'hr_admin', 'manager']
    logged_in_emp = getattr(request.user, 'employee_profile', None)

    # For regular employees performing camera self-punch, verify linked profile and enrollment
    if not is_terminal_operator:
        if not logged_in_emp:
            return JsonResponse({'matched': False, 'message': 'No employee profile linked to your user account.'}, status=403)
        if not logged_in_emp.face_registration_status or logged_in_emp.face_samples_count < 1:
            return JsonResponse({
                'matched': False,
                'security_status': 'NOT_ENROLLED',
                'message': 'Face biometric profile not yet registered. Please contact HR to enroll your face.'
            })

    try:
        data = json.loads(request.body.decode('utf-8'))
        image_base64 = data.get('image', '')
        company_id = data.get('company_id')

        if not image_base64:
            return JsonResponse({'matched': False, 'message': 'No image data'})

        if company_id:
            try:
                company = Company.objects.filter(id=int(company_id)).first()
            except (ValueError, TypeError):
                company = None

        if not company:
            if request.user.is_authenticated and not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
                company = request.user.employee_profile.company
            else:
                company = Company.objects.filter(is_active=True).first()

        if not company:
            return JsonResponse({'matched': False, 'message': 'No active company configured'})

        image_bgr = decode_base64_image(image_base64)
        if image_bgr is None:
            return JsonResponse({'matched': False, 'message': 'Invalid image format'})

        punch_mode = data.get('punch_mode', 'auto')

        # Two-Tier Fast Punch Pipeline: Compute Remaining (Tier 1) vs Already-Done (Tier 2) candidate pools
        now = timezone.now()
        local_now = timezone.localtime(now)
        today = local_now.date()
        tz = timezone.get_current_timezone()

        def format_dt(dt, with_seconds=False):
            if not dt:
                return ""
            ldt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
            return ldt.strftime('%I:%M:%S %p' if with_seconds else '%I:%M %p')

        remaining_ids = None
        already_done_ids = None
        if company:
            today_atts = Attendance.objects.filter(company=company, date=today)
            enrolled_emp_ids = set(
                Employee.objects.filter(
                    company=company,
                    face_registration_status=True
                ).exclude(
                    employment_status__in=['terminated', 'suspended', 'resigned']
                ).values_list('id', flat=True)
            )

            if punch_mode == 'check_in':
                already_done_ids = set(today_atts.filter(check_in_time__isnull=False).values_list('employee_id', flat=True))
                remaining_ids = enrolled_emp_ids - already_done_ids
            elif punch_mode == 'lunch_out':
                already_done_ids = set(today_atts.filter(lunch_start_time__isnull=False).values_list('employee_id', flat=True))
                remaining_ids = set(
                    today_atts.filter(
                        check_in_time__isnull=False,
                        lunch_start_time__isnull=True,
                        check_out_time__isnull=True
                    ).values_list('employee_id', flat=True)
                )
            elif punch_mode == 'lunch_in':
                already_done_ids = set(today_atts.filter(lunch_end_time__isnull=False).values_list('employee_id', flat=True))
                remaining_ids = set(
                    today_atts.filter(
                        lunch_start_time__isnull=False,
                        lunch_end_time__isnull=True,
                        check_out_time__isnull=True
                    ).values_list('employee_id', flat=True)
                )
            elif punch_mode == 'check_out':
                already_done_ids = set(today_atts.filter(check_out_time__isnull=False).values_list('employee_id', flat=True))
                remaining_ids = set(
                    today_atts.filter(
                        check_in_time__isnull=False,
                        check_out_time__isnull=True
                    ).values_list('employee_id', flat=True)
                )
            elif punch_mode == 'auto':
                # In auto mode, skip employees who have completed all attendance for today
                already_done_ids = set(today_atts.filter(check_out_time__isnull=False).values_list('employee_id', flat=True))
                remaining_ids = enrolled_emp_ids - already_done_ids

        # Execute two-tier facial recognition:
        # Tier 1: Check ONLY remaining un-punched employees (fast matching)
        # Tier 2: Check already-punched employees ONLY if Tier 1 found no match
        match_result = recognize_face_in_frame(
            company,
            image_bgr,
            remaining_employee_ids=remaining_ids,
            already_done_employee_ids=already_done_ids,
            punch_mode=punch_mode
        )
        frame_dims = [image_bgr.shape[1], image_bgr.shape[0]]
        match_result['frame_dims'] = frame_dims

        # Universal fallback across active companies for terminal operator (HR / Admin / Manager)
        if not match_result.get('matched') and is_terminal_operator:
            for other_comp in Company.objects.filter(is_active=True).exclude(id=company.id):
                other_res = recognize_face_in_frame(
                    other_comp,
                    image_bgr,
                    remaining_employee_ids=None,
                    already_done_employee_ids=None,
                    punch_mode=punch_mode
                )
                if other_res.get('matched'):
                    match_result = other_res
                    match_result['frame_dims'] = frame_dims
                    company = other_comp
                    break

        if not match_result.get('matched'):
            return JsonResponse(match_result)

        # Fast Punch Pipeline: Employee matched in Tier 2 (Already completed for this action)
        if match_result.get('already_punched'):
            emp = match_result.get('employee')
            att_rec = Attendance.objects.filter(employee=emp, date=today).first() if emp else None
            punch_detail = ""
            if att_rec:
                if punch_mode == 'check_in' and att_rec.check_in_time:
                    punch_detail = f"Check-In verified at {format_dt(att_rec.check_in_time)}"
                elif punch_mode == 'lunch_out' and att_rec.lunch_start_time:
                    punch_detail = f"Lunch Out started at {format_dt(att_rec.lunch_start_time)}"
                elif punch_mode == 'lunch_in' and att_rec.lunch_end_time:
                    punch_detail = f"Lunch In ended at {format_dt(att_rec.lunch_end_time)}"
                elif punch_mode == 'check_out' and att_rec.check_out_time:
                    punch_detail = f"Check-Out verified at {format_dt(att_rec.check_out_time)}"
                elif att_rec.check_in_time:
                    punch_detail = f"Check-In verified at {format_dt(att_rec.check_in_time)}"

            # Resolve employee photo url
            photo_url = None
            if emp:
                if emp.profile_picture:
                    try:
                        photo_url = emp.profile_picture.url
                    except Exception:
                        photo_url = None
                if not photo_url:
                    company_code = emp.company.code.upper() if emp.company else 'DEFAULT'
                    sample_file = Path(settings.MEDIA_ROOT) / 'faces' / company_code / str(emp.employee_id) / 'sample_01.jpg'
                    if sample_file.exists():
                        photo_url = f"/media/faces/{company_code}/{emp.employee_id}/sample_01.jpg"

            action_label = punch_mode.replace('_', ' ').title()
            msg = f"{emp.get_full_name()} has already completed {action_label}."
            if punch_detail:
                msg += f" ({punch_detail})"

            return JsonResponse({
                'matched': True,
                'access_granted': False,
                'already_punched': True,
                'skip_to_next': True,
                'security_status': 'ALREADY_COMPLETED',
                'employee_name': emp.get_full_name() if emp else 'Employee',
                'employee_id': emp.employee_id if emp else '',
                'department': emp.department.name if (emp and emp.department) else 'General',
                'confidence': match_result.get('confidence', 0),
                'photo_url': photo_url,
                'box': match_result.get('box'),
                'all_faces': match_result.get('all_faces', []),
                'frame_dims': frame_dims,
                'punch_detail': punch_detail,
                'message': msg
            })

        # Check for Security Alert (e.g. Terminated / Suspended / Resigned employee attempting access)
        if match_result.get('access_granted') is False:
            emp = match_result.get('employee')
            return JsonResponse({
                'matched': False,
                'access_granted': False,
                'security_alert': True,
                'security_status': match_result.get('security_status', 'BLOCKED'),
                'employee_name': emp.get_full_name() if emp else 'Unknown',
                'employee_id': emp.employee_id if emp else '',
                'confidence': match_result.get('confidence', 0),
                'box': match_result.get('box'),
                'all_faces': match_result.get('all_faces', []),
                'frame_dims': frame_dims,
                'message': match_result.get('message', 'ACCESS DENIED: Account privilege revoked.')
            })

        employee = match_result['employee']
        confidence = match_result['confidence']
        box = match_result.get('box')

        # Proxy Punch Security Guard:
        # If a regular employee is performing camera self-punch, verify the face matches their own profile
        if not is_terminal_operator and logged_in_emp:
            if employee.id != logged_in_emp.id:
                return JsonResponse({
                    'matched': False,
                    'security_alert': True,
                    'security_status': 'PROXY_ATTEMPT_BLOCKED',
                    'message': f"PROXY PUNCH BLOCKED: Face detected ({employee.get_full_name()}) does not match your employee profile ({logged_in_emp.get_full_name()}).",
                    'box': box,
                    'frame_dims': frame_dims,
                    'confidence': confidence,
                })
        now = timezone.now()
        local_now = timezone.localtime(now)
        today = local_now.date()
        tz = timezone.get_current_timezone()
        time_display = local_now.strftime('%I:%M %p')
        time_exact_display = local_now.strftime('%I:%M:%S %p')

        def format_dt(dt, with_seconds=False):
            if not dt:
                return ""
            ldt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
            return ldt.strftime('%I:%M:%S %p' if with_seconds else '%I:%M %p')

        # Resolve employee photo URL (live or enrolled biometric sample)
        photo_url = None
        if employee.profile_picture:
            try:
                photo_url = employee.profile_picture.url
            except Exception:
                photo_url = None
        if not photo_url:
            company_code = employee.company.code.upper() if employee.company else 'DEFAULT'
            sample_file = Path(settings.MEDIA_ROOT) / 'faces' / company_code / str(employee.employee_id) / 'sample_01.jpg'
            if sample_file.exists():
                photo_url = f"/media/faces/{company_code}/{employee.employee_id}/sample_01.jpg"

        # Shift Timing Rules:
        # Rule 1: Employees can punch in anytime starting 15 minutes before shift start time.
        # Rule 2: Automatic punch-out occurs at/after shift checkout time, including after 1 hour (overtime).
        # During the shift (before checkout time), employee status remains ON DUTY unless Early Exit is chosen.
        shift = employee.assigned_shift
        shift_name = shift.name if shift else "Standard"
        earliest_in_dt = None
        shift_start_dt = None
        shift_end_dt = None
        checkout_1h_after_dt = None

        if shift:
            shift_start_dt, shift_end_dt = shift.get_shift_window(today)
            if timezone.is_aware(now):
                shift_start_dt = timezone.make_aware(shift_start_dt, timezone.get_current_timezone())
                shift_end_dt = timezone.make_aware(shift_end_dt, timezone.get_current_timezone())

            # Earliest punch-in allowed: 15 minutes prior to shift start
            earliest_in_dt = shift_start_dt - timedelta(minutes=15)
            # Reference for 1 hour after checkout time
            checkout_1h_after_dt = shift_end_dt + timedelta(hours=1)

        # Check existing attendance record for today
        att = Attendance.objects.filter(employee=employee, date=today).first()
        punch_mode = data.get('punch_mode', 'auto')

        # ----------------------------------------------------
        # SCENARIO A: Employee has NOT punched in yet today
        # ----------------------------------------------------
        if not att:
            # If explicit punch out or lunch was requested but employee has not checked in:
            if punch_mode in ['check_out', 'early_out', 'force_out', 'lunch_out', 'lunch_in']:
                action_name = "check out" if 'out' in punch_mode else "record lunch"
                return JsonResponse({
                    'matched': True,
                    'access_granted': True,
                    'security_status': 'NOT_CHECKED_IN',
                    'punch_logged': False,
                    'punch_type': 'not_checked_in',
                    'employee_id': employee.employee_id,
                    'employee_name': employee.get_full_name(),
                    'department': employee.department.name if employee.department else 'General',
                    'designation': employee.designation.title if employee.designation else '',
                    'time': time_display,
                    'time_exact': time_exact_display,
                    'photo_url': photo_url,
                    'message': f"CANNOT PROCEED: {employee.get_full_name()} has not punched in yet today. Please punch in first.",
                    'box': box,
                    'frame_dims': frame_dims,
                    'confidence': confidence,
                })

            # Check 15-minute early arrival window
            if shift and earliest_in_dt and now < earliest_in_dt and punch_mode != 'force_in':
                remaining_mins = max(1, int((earliest_in_dt - now).total_seconds() / 60))
                return JsonResponse({
                    'matched': True,
                    'access_granted': True,
                    'security_status': 'EARLY_RESTRICTION',
                    'punch_logged': False,
                    'punch_type': 'early_restriction',
                    'employee_id': employee.employee_id,
                    'employee_name': employee.get_full_name(),
                    'department': employee.department.name if employee.department else 'General',
                    'designation': employee.designation.title if employee.designation else '',
                    'time': time_display,
                    'time_exact': time_exact_display,
                    'photo_url': photo_url,
                    'message': f"EARLY ARRIVAL: Punch-in opens 15 mins before shift start ({format_dt(earliest_in_dt)}). Available in {remaining_mins} min(s).",
                    'box': box,
                    'frame_dims': frame_dims,
                    'confidence': confidence,
                    'shift_name': shift_name,
                    'shift_start': shift.start_time.strftime('%I:%M %p'),
                    'shift_end': shift.end_time.strftime('%I:%M %p'),
                })

            # Check-In action
            att = Attendance.objects.create(
                employee=employee,
                company=employee.company,
                date=today,
                shift=shift,
                check_in_time=now,
                verification_method=Attendance.VerificationMethod.FACE_RECOGNITION,
                notes=f"Automated face recognition punch (Match Confidence: {confidence}%)",
                ip_address=get_client_ip(request)
            )
            punch_type = 'check_in'
            msg = f"PUNCH IN VERIFIED: Welcome, {employee.get_full_name()}! Check-in recorded at {time_display}."

        # ----------------------------------------------------
        # SCENARIO B: Employee is checked in, NOT checked out
        # ----------------------------------------------------
        elif not att.check_out_time:
            # 1. Explicit Lunch Out
            if punch_mode == 'lunch_out':
                if att.lunch_start_time and not att.lunch_end_time:
                    return JsonResponse({
                        'matched': True,
                        'access_granted': True,
                        'security_status': 'AUTHORIZED',
                        'in_cooldown': True,
                        'punch_logged': False,
                        'punch_type': 'already_on_lunch',
                        'employee_id': employee.employee_id,
                        'employee_name': employee.get_full_name(),
                        'department': employee.department.name if employee.department else 'General',
                        'designation': employee.designation.title if employee.designation else '',
                        'time': format_dt(att.lunch_start_time),
                        'time_exact': format_dt(att.lunch_start_time, with_seconds=True),
                        'photo_url': photo_url,
                        'message': f"ALREADY ON LUNCH: {employee.get_full_name()} departed for lunch at {format_dt(att.lunch_start_time)}. Switch to Lunch In when returning.",
                        'box': box,
                        'frame_dims': frame_dims,
                        'confidence': confidence,
                    })
                elif att.lunch_start_time and att.lunch_end_time:
                    return JsonResponse({
                        'matched': True,
                        'access_granted': True,
                        'security_status': 'AUTHORIZED',
                        'in_cooldown': True,
                        'punch_logged': False,
                        'punch_type': 'lunch_completed',
                        'employee_id': employee.employee_id,
                        'employee_name': employee.get_full_name(),
                        'department': employee.department.name if employee.department else 'General',
                        'designation': employee.designation.title if employee.designation else '',
                        'time': format_dt(att.lunch_end_time),
                        'time_exact': format_dt(att.lunch_end_time, with_seconds=True),
                        'photo_url': photo_url,
                        'message': f"LUNCH ALREADY COMPLETED: Break completed today ({att.total_lunch_duration_minutes} mins). Resumed at {format_dt(att.lunch_end_time)}.",
                        'box': box,
                        'frame_dims': frame_dims,
                        'confidence': confidence,
                    })

                # Record Lunch Out
                att.lunch_start_time = now
                att.verification_method = Attendance.VerificationMethod.FACE_RECOGNITION
                att.save()
                punch_type = 'lunch_out'
                msg = f"LUNCH BREAK STARTED: Enjoy your meal, {employee.get_full_name()}! Lunch Out recorded at {time_display}."

            # 2. Explicit Lunch In
            elif punch_mode == 'lunch_in':
                if not att.lunch_start_time:
                    return JsonResponse({
                        'matched': True,
                        'access_granted': True,
                        'security_status': 'AUTHORIZED',
                        'punch_logged': False,
                        'punch_type': 'no_lunch_out',
                        'employee_id': employee.employee_id,
                        'employee_name': employee.get_full_name(),
                        'department': employee.department.name if employee.department else 'General',
                        'designation': employee.designation.title if employee.designation else '',
                        'time': time_display,
                        'time_exact': time_exact_display,
                        'photo_url': photo_url,
                        'message': f"CANNOT PUNCH LUNCH IN: No Lunch Out record found today for {employee.get_full_name()}. Please punch Lunch Out first.",
                        'box': box,
                        'frame_dims': frame_dims,
                        'confidence': confidence,
                    })
                elif att.lunch_end_time:
                    return JsonResponse({
                        'matched': True,
                        'access_granted': True,
                        'security_status': 'AUTHORIZED',
                        'in_cooldown': True,
                        'punch_logged': False,
                        'punch_type': 'lunch_completed',
                        'employee_id': employee.employee_id,
                        'employee_name': employee.get_full_name(),
                        'department': employee.department.name if employee.department else 'General',
                        'designation': employee.designation.title if employee.designation else '',
                        'time': format_dt(att.lunch_end_time),
                        'time_exact': format_dt(att.lunch_end_time, with_seconds=True),
                        'photo_url': photo_url,
                        'message': f"ALREADY RETURNED FROM LUNCH: Returned at {format_dt(att.lunch_end_time)} ({att.total_lunch_duration_minutes} mins).",
                        'box': box,
                        'frame_dims': frame_dims,
                        'confidence': confidence,
                    })

                # Record Lunch In
                att.lunch_end_time = now
                att.verification_method = Attendance.VerificationMethod.FACE_RECOGNITION
                att.save()
                punch_type = 'lunch_in'
                msg = f"LUNCH BREAK ENDED: Welcome back, {employee.get_full_name()}! Lunch In recorded at {time_display} ({att.total_lunch_duration_minutes} mins break)."

            # 3. Explicit Check In when already checked in
            elif punch_mode == 'check_in':
                if att.lunch_start_time and not att.lunch_end_time:
                    # On lunch: Checking in auto-completes lunch break
                    att.lunch_end_time = now
                    att.verification_method = Attendance.VerificationMethod.FACE_RECOGNITION
                    att.save()
                    punch_type = 'lunch_in'
                    msg = f"LUNCH BREAK ENDED: Welcome back, {employee.get_full_name()}! Lunch In recorded at {time_display} ({att.total_lunch_duration_minutes} mins break)."
                else:
                    return JsonResponse({
                        'matched': True,
                        'access_granted': True,
                        'security_status': 'AUTHORIZED',
                        'in_cooldown': True,
                        'punch_logged': False,
                        'punch_type': 'already_in',
                        'employee_id': employee.employee_id,
                        'employee_name': employee.get_full_name(),
                        'department': employee.department.name if employee.department else 'General',
                        'designation': employee.designation.title if employee.designation else '',
                        'time': format_dt(att.check_in_time),
                        'time_exact': format_dt(att.check_in_time, with_seconds=True),
                        'photo_url': photo_url,
                        'message': f"ALREADY CHECKED IN: {employee.get_full_name()} is already checked in at {format_dt(att.check_in_time)}.",
                        'box': box,
                        'frame_dims': frame_dims,
                        'confidence': confidence,
                        'working_hours': str(att.total_working_hours),
                    })

            # 4. Check Out or Auto Detect
            else:
                time_since_in = (now - att.check_in_time).total_seconds()
                min_anti_bounce = 3 if punch_mode in ['check_out', 'early_out', 'force_out'] else 15
                if time_since_in < min_anti_bounce:
                    return JsonResponse({
                        'matched': True,
                        'access_granted': True,
                        'security_status': 'AUTHORIZED',
                        'in_cooldown': True,
                        'punch_logged': False,
                        'punch_type': 'already_in',
                        'employee_id': employee.employee_id,
                        'employee_name': employee.get_full_name(),
                        'department': employee.department.name if employee.department else 'General',
                        'designation': employee.designation.title if employee.designation else '',
                        'time': format_dt(att.check_in_time),
                        'time_exact': format_dt(att.check_in_time, with_seconds=True),
                        'photo_url': photo_url,
                        'message': f"COOLDOWN: Just checked in. Please wait a moment before checking out.",
                        'box': box,
                        'frame_dims': frame_dims,
                        'confidence': confidence,
                        'working_hours': '0.00',
                    })

                # Auto Mode Subcase A: Currently on lunch break -> Auto marks LUNCH IN!
                if punch_mode == 'auto' and att.lunch_start_time and not att.lunch_end_time:
                    time_since_lunch_out = (now - att.lunch_start_time).total_seconds()
                    if time_since_lunch_out < 10:
                        return JsonResponse({
                            'matched': True,
                            'access_granted': True,
                            'security_status': 'AUTHORIZED',
                            'in_cooldown': True,
                            'punch_logged': False,
                            'punch_type': 'already_on_lunch',
                            'employee_id': employee.employee_id,
                            'employee_name': employee.get_full_name(),
                            'department': employee.department.name if employee.department else 'General',
                            'designation': employee.designation.title if employee.designation else '',
                            'time': format_dt(att.lunch_start_time),
                            'time_exact': format_dt(att.lunch_start_time, with_seconds=True),
                            'photo_url': photo_url,
                            'message': f"COOLDOWN: Just departed for lunch. Enjoy your meal!",
                            'box': box,
                            'frame_dims': frame_dims,
                            'confidence': confidence,
                        })
                    att.lunch_end_time = now
                    att.verification_method = Attendance.VerificationMethod.FACE_RECOGNITION
                    att.save()
                    punch_type = 'lunch_in'
                    msg = f"LUNCH BREAK ENDED: Welcome back, {employee.get_full_name()}! Lunch In recorded at {time_display} ({att.total_lunch_duration_minutes} mins break)."

                # Auto Mode Subcase B: Has not taken lunch today -> Check if in lunch window
                elif punch_mode == 'auto' and not att.lunch_start_time:
                    emp_lunch_start = employee.lunch_start_time or (shift.lunch_start_time if shift else None) or time(13, 0)
                    emp_lunch_end = employee.lunch_end_time or (shift.lunch_end_time if shift else None) or time(14, 0)

                    lunch_start_dt = timezone.make_aware(datetime.combine(today, emp_lunch_start), tz) if tz else datetime.combine(today, emp_lunch_start)
                    lunch_end_dt = timezone.make_aware(datetime.combine(today, emp_lunch_end), tz) if tz else datetime.combine(today, emp_lunch_end)

                    in_lunch_window = (now >= (lunch_start_dt - timedelta(minutes=15))) and (now <= (lunch_end_dt + timedelta(minutes=30)))
                    is_near_shift_end = shift_end_dt and (now >= (shift_end_dt - timedelta(minutes=15)))

                    if in_lunch_window and not is_near_shift_end:
                        att.lunch_start_time = now
                        att.verification_method = Attendance.VerificationMethod.FACE_RECOGNITION
                        att.save()
                        punch_type = 'lunch_out'
                        msg = f"LUNCH BREAK STARTED: Enjoy your meal, {employee.get_full_name()}! Lunch Out recorded at {time_display}."
                    else:
                        is_checkout_time = False
                        if shift and shift_end_dt:
                            if now >= (shift_end_dt - timedelta(minutes=10)):
                                is_checkout_time = True
                        else:
                            is_checkout_time = True

                        if is_checkout_time:
                            att.check_out_time = now
                            att.verification_method = Attendance.VerificationMethod.FACE_RECOGNITION
                            att.save()
                            punch_type = 'check_out'
                            ot_note = f" (Overtime: {att.overtime_hours} hrs)" if att.overtime_hours > Decimal('0.00') else ""
                            msg = f"PUNCH OUT VERIFIED: Goodbye, {employee.get_full_name()}! Check-Out recorded at {time_display} ({att.total_working_hours} hrs worked){ot_note}."
                        else:
                            lunch_info = f" Lunch: {emp_lunch_start.strftime('%I:%M %p')}." if emp_lunch_start else ""
                            return JsonResponse({
                                'matched': True,
                                'access_granted': True,
                                'security_status': 'AUTHORIZED',
                                'in_cooldown': True,
                                'punch_logged': False,
                                'punch_type': 'on_duty',
                                'employee_id': employee.employee_id,
                                'employee_name': employee.get_full_name(),
                                'department': employee.department.name if employee.department else 'General',
                                'designation': employee.designation.title if employee.designation else '',
                                'time': format_dt(att.check_in_time),
                                'time_exact': format_dt(att.check_in_time, with_seconds=True),
                                'photo_url': photo_url,
                                'message': f"CURRENTLY ON DUTY: Checked in at {format_dt(att.check_in_time)}.{lunch_info} Shift checkout: {shift.end_time.strftime('%I:%M %p') if shift else 'Open'}.",
                                'box': box,
                                'frame_dims': frame_dims,
                                'confidence': confidence,
                                'working_hours': str(att.total_working_hours),
                                'shift_name': shift_name,
                                'shift_end': shift.end_time.strftime('%I:%M %p') if shift else '',
                            })

                # Explicit Check Out or Auto mode after lunch completed
                else:
                    is_checkout_time = False
                    if punch_mode in ['check_out', 'early_out', 'force_out']:
                        is_checkout_time = True
                    elif shift and shift_end_dt:
                        if now >= (shift_end_dt - timedelta(minutes=10)):
                            is_checkout_time = True
                    else:
                        is_checkout_time = True

                    if is_checkout_time:
                        if att.lunch_start_time and not att.lunch_end_time:
                            att.lunch_end_time = now
                        att.check_out_time = now
                        att.verification_method = Attendance.VerificationMethod.FACE_RECOGNITION
                        att.save()
                        punch_type = 'check_out'
                        ot_note = f" (Overtime: {att.overtime_hours} hrs)" if att.overtime_hours > Decimal('0.00') else ""
                        msg = f"PUNCH OUT VERIFIED: Goodbye, {employee.get_full_name()}! Check-Out recorded at {time_display} ({att.total_working_hours} hrs worked){ot_note}."
                    else:
                        return JsonResponse({
                            'matched': True,
                            'access_granted': True,
                            'security_status': 'AUTHORIZED',
                            'in_cooldown': True,
                            'punch_logged': False,
                            'punch_type': 'on_duty',
                            'employee_id': employee.employee_id,
                            'employee_name': employee.get_full_name(),
                            'department': employee.department.name if employee.department else 'General',
                            'designation': employee.designation.title if employee.designation else '',
                            'time': format_dt(att.check_in_time),
                            'time_exact': format_dt(att.check_in_time, with_seconds=True),
                            'photo_url': photo_url,
                            'message': f"CURRENTLY ON DUTY: Checked in at {format_dt(att.check_in_time)}. Shift checkout: {shift.end_time.strftime('%I:%M %p') if shift else 'Open'}.",
                            'box': box,
                            'frame_dims': frame_dims,
                            'confidence': confidence,
                            'working_hours': str(att.total_working_hours),
                            'shift_name': shift_name,
                            'shift_end': shift.end_time.strftime('%I:%M %p') if shift else '',
                        })

        # ----------------------------------------------------
        # SCENARIO C: Employee ALREADY checked out today
        # ----------------------------------------------------
        else:
            if punch_mode in ['lunch_out', 'lunch_in']:
                return JsonResponse({
                    'matched': True,
                    'access_granted': True,
                    'security_status': 'AUTHORIZED',
                    'in_cooldown': True,
                    'punch_logged': False,
                    'punch_type': 'already_out',
                    'employee_id': employee.employee_id,
                    'employee_name': employee.get_full_name(),
                    'department': employee.department.name if employee.department else 'General',
                    'designation': employee.designation.title if employee.designation else '',
                    'time': format_dt(att.check_out_time),
                    'time_exact': format_dt(att.check_out_time, with_seconds=True),
                    'photo_url': photo_url,
                    'message': f"ALREADY CHECKED OUT: Cannot record lunch punch after shift departure ({format_dt(att.check_out_time)}).",
                    'box': box,
                    'frame_dims': frame_dims,
                    'confidence': confidence,
                    'working_hours': str(att.total_working_hours),
                })

            time_since_out = (now - att.check_out_time).total_seconds()
            if time_since_out < 15:
                return JsonResponse({
                    'matched': True,
                    'access_granted': True,
                    'security_status': 'AUTHORIZED',
                    'in_cooldown': True,
                    'punch_logged': False,
                    'punch_type': 'already_out',
                    'employee_id': employee.employee_id,
                    'employee_name': employee.get_full_name(),
                    'department': employee.department.name if employee.department else 'General',
                    'designation': employee.designation.title if employee.designation else '',
                    'time': format_dt(att.check_out_time),
                    'time_exact': format_dt(att.check_out_time, with_seconds=True),
                    'photo_url': photo_url,
                    'message': f"ALREADY PUNCHED OUT: Checked Out at {format_dt(att.check_out_time)} ({att.total_working_hours} hrs).",
                    'box': box,
                    'frame_dims': frame_dims,
                    'confidence': confidence,
                    'working_hours': str(att.total_working_hours),
                })

            # Re-punch after checkout time: updates latest departure time (overtime exit)
            att.check_out_time = now
            att.verification_method = Attendance.VerificationMethod.FACE_RECOGNITION
            att.save()
            punch_type = 'check_out'
            ot_note = f" (Overtime: {att.overtime_hours} hrs)" if att.overtime_hours > Decimal('0.00') else ""
            msg = f"PUNCH OUT UPDATED: Exit time updated to {time_display} ({att.total_working_hours} hrs worked){ot_note}."

        return JsonResponse({
            'matched': True,
            'access_granted': True,
            'security_status': 'AUTHORIZED',
            'punch_logged': True,
            'punch_type': punch_type,
            'employee_id': employee.employee_id,
            'employee_name': employee.get_full_name(),
            'photo_url': photo_url,
            'department': employee.department.name if employee.department else 'General',
            'department_id': employee.department.id if employee.department else 0,
            'designation': employee.designation.title if employee.designation else '',
            'time': time_display,
            'time_exact': time_exact_display,
            'check_in_time': format_dt(att.check_in_time) if att.check_in_time else time_display,
            'lunch_start_time': format_dt(att.lunch_start_time) if att.lunch_start_time else None,
            'lunch_end_time': format_dt(att.lunch_end_time) if att.lunch_end_time else None,
            'total_lunch_duration_minutes': att.total_lunch_duration_minutes,
            'check_out_time': format_dt(att.check_out_time) if att.check_out_time else None,
            'date': local_now.strftime('%d %b %Y'),
            'confidence': confidence,
            'box': box,
            'frame_dims': frame_dims,
            'message': msg,
            'status': att.get_status_display(),
            'status_badge': att.get_status_badge_class(),
            'working_hours': str(att.total_working_hours),
        })

    except Exception as e:
        return JsonResponse({'matched': False, 'message': f"Recognition error: {str(e)}"}, status=500)

