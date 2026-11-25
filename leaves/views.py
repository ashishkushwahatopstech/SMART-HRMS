from decimal import Decimal
from datetime import date, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum
from django.utils import timezone
from companies.models import Company
from employees.models import Employee
from holidays.models import Holiday
from .models import LeaveType, LeaveBalance, LeaveApplication, LeaveApprovalLog
from services.email_service import (
    send_leave_application_notification,
    send_leave_status_email,
)
from .forms import (
    LeaveTypeForm,
    LeaveApplicationForm,
    LeaveDecisionForm,
    LeaveFilterForm,
    LeaveBalanceAdjustmentForm
)


@login_required
def leave_dashboard(request):
    """
    Employee Leave Portal Dashboard:
    - Current Year Leave Balances (PL, CL, SL, etc.)
    - Summary Metrics (Total Entitled, Used, Pending, Available)
    - Personal Recent Applications
    - If Manager/HR/Admin: Pending approvals section
    """
    user = request.user
    today = timezone.now().date()
    current_year = today.year

    employee = getattr(user, 'employee_profile', None)

    # 1. Employee personal leave balances
    balances = []
    if employee:
        balances = LeaveBalance.objects.filter(
            employee=employee,
            year=current_year,
            leave_type__is_active=True
        ).select_related('leave_type')

    # Summary totals for employee
    total_entitled = sum(b.total_entitled for b in balances) if balances else Decimal('0.00')
    total_used = sum(b.used_days for b in balances) if balances else Decimal('0.00')
    total_pending = sum(b.pending_days for b in balances) if balances else Decimal('0.00')
    total_available = sum(b.available_days for b in balances) if balances else Decimal('0.00')

    # Employee personal recent requests
    my_applications = []
    if employee:
        my_applications = LeaveApplication.objects.filter(
            employee=employee
        ).select_related('leave_type').order_by('-created_at')[:10]

    # 2. Pending team approvals for Manager / HR / Super Admin
    pending_approvals = []
    if user.is_super_admin:
        pending_approvals = LeaveApplication.objects.filter(
            status=LeaveApplication.ApplicationStatus.PENDING
        ).select_related('employee', 'leave_type', 'company').order_by('-created_at')[:10]
    elif user.is_hr_admin and employee:
        pending_approvals = LeaveApplication.objects.filter(
            company=employee.company,
            status=LeaveApplication.ApplicationStatus.PENDING
        ).select_related('employee', 'leave_type', 'company').order_by('-created_at')[:10]
    elif user.is_manager_user and employee:
        # Direct subordinates' requests
        pending_approvals = LeaveApplication.objects.filter(
            employee__manager=employee,
            status=LeaveApplication.ApplicationStatus.PENDING
        ).select_related('employee', 'leave_type', 'company').order_by('-created_at')[:10]

    context = {
        'employee': employee,
        'current_year': current_year,
        'balances': balances,
        'total_entitled': total_entitled,
        'total_used': total_used,
        'total_pending': total_pending,
        'total_available': total_available,
        'my_applications': my_applications,
        'pending_approvals': pending_approvals,
    }
    return render(request, 'leaves/leave_dashboard.html', context)


@login_required
def leave_apply(request):
    """
    Self-Service Leave Application Submission.
    Validates company working days, locks pending days on balance,
    and logs the action in LeaveApprovalLog.
    """
    user = request.user
    employee = getattr(user, 'employee_profile', None)

    if not employee:
        messages.error(request, "Your login account is not linked to an active Employee profile. Contact HR.")
        return redirect('leaves:dashboard')

    if request.method == 'POST':
        form = LeaveApplicationForm(request.POST, request.FILES, employee=employee)
        if form.is_valid():
            application = form.save(commit=False)
            application.employee = employee
            application.company = employee.company
            application.total_days = form.cleaned_data['calculated_net_days']
            application.save()

            # Lock pending days in balance
            bal, _ = LeaveBalance.objects.get_or_create(
                employee=employee,
                leave_type=application.leave_type,
                year=application.start_date.year,
                defaults={'allocated_days': application.leave_type.annual_quota}
            )
            bal.pending_days += application.total_days
            bal.save()

            # Record initial log
            LeaveApprovalLog.objects.create(
                application=application,
                action='Applied',
                acted_by=user,
                remarks='Leave application submitted'
            )

            # Dispatch notification email to Manager and HR Admin
            send_leave_application_notification(application, request=request)

            messages.success(
                request,
                f"Leave request for {application.total_days} day(s) from {application.start_date} to {application.end_date} submitted successfully."
            )
            return redirect('leaves:dashboard')
        else:
            messages.error(request, "Please resolve the errors highlighted below.")
    else:
        initial = {'start_date': timezone.now().date(), 'end_date': timezone.now().date()}
        form = LeaveApplicationForm(employee=employee, initial=initial)

    # Fetch employee's current balances for reference widget
    balances = LeaveBalance.objects.filter(
        employee=employee,
        year=timezone.now().year,
        leave_type__is_active=True
    ).select_related('leave_type')

    context = {
        'form': form,
        'employee': employee,
        'balances': balances,
    }
    return render(request, 'leaves/leave_apply.html', context)


@login_required
def leave_list(request):
    """
    Comprehensive applications roster with status filters and strict role scoping:
    - Super Admin: sees all companies.
    - HR Admin: sees their company employees.
    - Manager: sees direct subordinates + own applications.
    - Employee: sees own applications.
    """
    user = request.user
    employee = getattr(user, 'employee_profile', None)

    queryset = LeaveApplication.objects.select_related('employee', 'leave_type', 'company', 'approved_by')

    # 1. Enforce Multi-Company & Role Scoping
    if user.is_super_admin:
        pass  # Global access
    elif user.is_hr_admin:
        if employee:
            queryset = queryset.filter(company=employee.company)
        else:
            queryset = queryset.none()
    elif user.is_manager_user:
        if employee:
            # Subordinates OR own requests
            queryset = queryset.filter(Q(employee__manager=employee) | Q(employee=employee))
        else:
            queryset = queryset.none()
    else:
        # Standard employee: only own requests
        if employee:
            queryset = queryset.filter(employee=employee)
        else:
            queryset = queryset.none()

    # 2. Filter Form processing
    filter_form = LeaveFilterForm(request.GET, user=user)
    if filter_form.is_valid():
        status_val = filter_form.cleaned_data.get('status')
        leave_type_val = filter_form.cleaned_data.get('leave_type')
        year_val = filter_form.cleaned_data.get('year')
        search_val = filter_form.cleaned_data.get('search')

        if status_val:
            queryset = queryset.filter(status=status_val)
        if leave_type_val:
            queryset = queryset.filter(leave_type=leave_type_val)
        if year_val:
            queryset = queryset.filter(start_date__year=year_val)
        if search_val:
            queryset = queryset.filter(
                Q(employee__first_name__icontains=search_val) |
                Q(employee__last_name__icontains=search_val) |
                Q(employee__employee_id__icontains=search_val)
            )

    queryset = queryset.order_by('-created_at')

    context = {
        'applications': queryset,
        'filter_form': filter_form,
    }
    return render(request, 'leaves/leave_list.html', context)


@login_required
def leave_detail(request, pk):
    """
    Detailed view of a Leave Application:
    Shows date breakdown, status history timeline, and action buttons.
    """
    user = request.user
    application = LeaveApplication.objects.select_related(
        'employee', 'leave_type', 'company', 'approved_by'
    ).filter(pk=pk).first()

    if not application:
        messages.error(request, "Leave application record does not exist or has been removed.")
        return redirect('leaves:list')

    # Permission check: superuser, HR of same company, Manager of applicant, or applicant themselves
    can_view = False
    is_approver = False
    employee = getattr(user, 'employee_profile', None)

    if user.is_super_admin:
        can_view = True
        is_approver = True
    elif user.is_hr_admin and employee and employee.company_id == application.company_id:
        can_view = True
        is_approver = True
    elif user.is_manager_user and employee and application.employee.manager_id == employee.id:
        can_view = True
        is_approver = True
    elif employee and application.employee_id == employee.id:
        can_view = True
        is_approver = False

    if not can_view:
        raise PermissionDenied("You are not authorized to view this leave application.")

    logs = application.approval_logs.select_related('acted_by').order_by('created_at')
    decision_form = LeaveDecisionForm()

    context = {
        'application': application,
        'logs': logs,
        'is_approver': is_approver,
        'can_cancel': (application.status == LeaveApplication.ApplicationStatus.PENDING and employee and application.employee_id == employee.id),
        'decision_form': decision_form,
    }
    return render(request, 'leaves/leave_detail.html', context)


@login_required
def leave_approve(request, pk):
    """
    Approve Leave Request (POST only).
    """
    if request.method != 'POST':
        return HttpResponseForbidden("Method not allowed")

    user = request.user
    application = LeaveApplication.objects.filter(pk=pk).first()
    if not application:
        messages.error(request, "Leave application not found.")
        return redirect('leaves:list')
    employee = getattr(user, 'employee_profile', None)

    # Authorization verification
    authorized = False
    if user.is_super_admin:
        authorized = True
    elif user.is_hr_admin and employee and employee.company_id == application.company_id:
        authorized = True
    elif user.is_manager_user and employee and application.employee.manager_id == employee.id:
        authorized = True

    if not authorized:
        raise PermissionDenied("You do not have authority to approve this leave request.")

    if application.status != LeaveApplication.ApplicationStatus.PENDING:
        messages.warning(request, f"This request is already marked as {application.get_status_display()}.")
        return redirect('leaves:detail', pk=pk)

    application.approve(user)
    # Dispatch approval notification email to employee
    send_leave_status_email(application, status='approved', request=request)

    messages.success(request, f"Leave application for {application.employee.get_full_name()} has been APPROVED.")
    return redirect('leaves:detail', pk=pk)


@login_required
def leave_reject(request, pk):
    """
    Reject Leave Request (POST only).
    """
    if request.method != 'POST':
        return HttpResponseForbidden("Method not allowed")

    user = request.user
    application = LeaveApplication.objects.filter(pk=pk).first()
    if not application:
        messages.error(request, "Leave application not found.")
        return redirect('leaves:list')
    employee = getattr(user, 'employee_profile', None)

    authorized = False
    if user.is_super_admin:
        authorized = True
    elif user.is_hr_admin and employee and employee.company_id == application.company_id:
        authorized = True
    elif user.is_manager_user and employee and application.employee.manager_id == employee.id:
        authorized = True

    if not authorized:
        raise PermissionDenied("You do not have authority to reject this leave request.")

    if application.status != LeaveApplication.ApplicationStatus.PENDING:
        messages.warning(request, f"This request is already marked as {application.get_status_display()}.")
        return redirect('leaves:detail', pk=pk)

    form = LeaveDecisionForm(request.POST)
    reason = "Application rejected by manager/HR"
    if form.is_valid():
        reason = form.cleaned_data.get('rejection_reason') or reason

    application.reject(user, reason)
    # Dispatch rejection notification email to employee
    send_leave_status_email(application, status='rejected', remarks=reason, request=request)

    messages.warning(request, f"Leave application for {application.employee.get_full_name()} has been REJECTED.")
    return redirect('leaves:detail', pk=pk)


@login_required
def leave_cancel(request, pk):
    """
    Applicant cancels their own pending leave request.
    """
    if request.method != 'POST':
        return HttpResponseForbidden("Method not allowed")

    user = request.user
    employee = getattr(user, 'employee_profile', None)
    application = LeaveApplication.objects.filter(pk=pk).first()
    if not application:
        messages.error(request, "Leave application not found or has already been cancelled.")
        return redirect('leaves:list')

    if not employee or application.employee_id != employee.id:
        raise PermissionDenied("You can only cancel your own leave requests.")

    if application.status != LeaveApplication.ApplicationStatus.PENDING:
        messages.warning(request, "Only pending leave requests can be cancelled.")
        return redirect('leaves:detail', pk=pk)

    application.cancel(user)
    messages.info(request, "Your leave application has been cancelled.")
    return redirect('leaves:detail', pk=pk)


@login_required
def leave_types_list(request):
    """
    Manage Leave Types (HR Admin & Super Admin).
    """
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    employee = getattr(user, 'employee_profile', None)
    if user.is_super_admin:
        types = LeaveType.objects.all().select_related('company').order_by('company', 'name')
    elif employee:
        types = LeaveType.objects.filter(company=employee.company).select_related('company').order_by('name')
    else:
        types = LeaveType.objects.none()

    return render(request, 'leaves/leave_types_list.html', {'types': types})


@login_required
def leave_type_create(request):
    """
    Create Leave Type (HR / Super Admin).
    """
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    if request.method == 'POST':
        form = LeaveTypeForm(request.POST, user=user)
        if form.is_valid():
            leave_type = form.save(commit=False)
            if not user.is_super_admin and hasattr(user, 'employee_profile') and user.employee_profile:
                leave_type.company = user.employee_profile.company
            leave_type.save()
            messages.success(request, f"Leave type '{leave_type.name}' created successfully.")
            return redirect('leaves:types_list')
    else:
        form = LeaveTypeForm(user=user)

    return render(request, 'leaves/leave_type_form.html', {'form': form, 'title': 'Create Leave Type'})


@login_required
def leave_type_edit(request, pk):
    """
    Edit Leave Type (HR / Super Admin).
    """
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    leave_type = LeaveType.objects.filter(pk=pk).first()
    if not leave_type:
        messages.error(request, "Leave type does not exist or has already been removed.")
        return redirect('leaves:types_list')
    if not user.is_super_admin:
        employee = getattr(user, 'employee_profile', None)
        if not employee or leave_type.company_id != employee.company_id:
            raise PermissionDenied("You can only edit leave types for your own company.")

    if request.method == 'POST':
        form = LeaveTypeForm(request.POST, instance=leave_type, user=user)
        if form.is_valid():
            form.save()
            messages.success(request, f"Leave type '{leave_type.name}' updated successfully.")
            return redirect('leaves:types_list')
    else:
        form = LeaveTypeForm(instance=leave_type, user=user)

    return render(request, 'leaves/leave_type_form.html', {'form': form, 'title': f'Edit {leave_type.name}'})


@login_required
def leave_balances_manage(request):
    """
    View and manage employee leave balances per year (HR / Super Admin).
    """
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    employee = getattr(user, 'employee_profile', None)
    year = int(request.GET.get('year', timezone.now().year))

    balances = LeaveBalance.objects.filter(year=year).select_related('employee', 'leave_type', 'employee__company')
    if not user.is_super_admin and employee:
        balances = balances.filter(employee__company=employee.company)

    context = {
        'balances': balances.order_by('employee__first_name', 'leave_type__name'),
        'year': year,
    }
    return render(request, 'leaves/leave_balances_manage.html', context)


@login_required
def api_calculate_days(request):
    """
    API endpoint for front-end dynamic net working day and balance calculator.
    Query params: start_date, end_date, is_half_day, leave_type_id
    """
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    is_half_day = request.GET.get('is_half_day') == 'true'
    leave_type_id = request.GET.get('leave_type_id')

    user = request.user
    employee = getattr(user, 'employee_profile', None)

    if not start_str or not employee:
        return JsonResponse({'success': False, 'error': 'Missing parameters or unlinked profile'})

    try:
        start_date = date.fromisoformat(start_str)
        end_date = date.fromisoformat(end_str) if end_str and not is_half_day else start_date
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid date format'})

    company = employee.company

    if is_half_day:
        net_days = Decimal('0.50')
        is_working = Holiday.is_working_day(company, start_date)
        if not is_working:
            return JsonResponse({
                'success': True,
                'net_days': 0.0,
                'warning': 'Selected date is a weekly off or mandatory holiday.'
            })
    else:
        if start_date > end_date:
            return JsonResponse({'success': False, 'error': 'Start date after end date'})

        cur = start_date
        count = 0
        while cur <= end_date:
            if Holiday.is_working_day(company, cur):
                count += 1
            cur += timedelta(days=1)
        net_days = Decimal(str(count))

    # Available balance lookup
    available_days = 0.0
    if leave_type_id:
        bal = LeaveBalance.objects.filter(
            employee=employee,
            leave_type_id=leave_type_id,
            year=start_date.year
        ).first()
        if bal:
            available_days = float(bal.available_days)

    return JsonResponse({
        'success': True,
        'net_days': float(net_days),
        'available_days': available_days,
        'has_sufficient_balance': (available_days >= float(net_days))
    })
