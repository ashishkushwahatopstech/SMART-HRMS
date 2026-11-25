from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils import timezone
from accounts.decorators import hr_required, role_required
from companies.models import Company
from employees.models import Employee
from .models import Shift, ShiftAssignment
from .forms import ShiftForm, ShiftAssignForm


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager'])
def shift_list(request):
    """
    Rosters shifts with multi-company isolation, search, and filtering.
    """
    shifts = Shift.objects.select_related('company').annotate(
        assigned_count=Count('employees')
    ).order_by('company', 'start_time')

    # Data Isolation: Non-superusers only see their company's shifts
    user_company = None
    if not request.user.is_superuser:
        if hasattr(request.user, 'employee_profile') and request.user.employee_profile:
            user_company = request.user.employee_profile.company
            shifts = shifts.filter(company=user_company)
        else:
            shifts = shifts.none()

    # Search query
    query = request.GET.get('q', '').strip()
    if query:
        shifts = shifts.filter(
            Q(name__icontains=query) |
            Q(shift_code__icontains=query) |
            Q(description__icontains=query)
        )

    # Filter by Company
    company_id = request.GET.get('company')
    if company_id and request.user.is_superuser:
        shifts = shifts.filter(company_id=company_id)

    # Filter by Overnight status
    overnight_filter = request.GET.get('overnight')
    if overnight_filter == 'yes':
        shifts = shifts.filter(is_overnight=True)
    elif overnight_filter == 'no':
        shifts = shifts.filter(is_overnight=False)

    # Filter by Active status
    status_filter = request.GET.get('status')
    if status_filter == 'active':
        shifts = shifts.filter(is_active=True)
    elif status_filter == 'inactive':
        shifts = shifts.filter(is_active=False)

    companies_list = Company.objects.filter(is_active=True) if request.user.is_superuser else ([user_company] if user_company else [])

    paginator = Paginator(shifts, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'shifts/shift_list.html', {
        'page_obj': page_obj,
        'query': query,
        'companies_list': companies_list,
        'selected_company': company_id,
        'selected_overnight': overnight_filter,
        'selected_status': status_filter,
        'total_count': shifts.count(),
    })


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager', 'employee'])
def shift_detail(request, pk):
    """
    Shows full shift configuration, break breakdowns, net working hours,
    and assigned employee roster.
    """
    shift = Shift.objects.select_related('company').filter(pk=pk).first()
    if not shift:
        messages.error(request, "Shift record does not exist or has already been removed.")
        return redirect('shifts:list')

    # Company Isolation
    if not request.user.is_superuser:
        if hasattr(request.user, 'employee_profile') and request.user.employee_profile:
            if request.user.employee_profile.company_id != shift.company_id:
                messages.error(request, "Access denied. Shift belongs to another company.")
                return redirect('shifts:list')
        else:
            messages.error(request, "Access denied. No employee profile found.")
            return redirect('shifts:list')

    assigned_employees = shift.employees.select_related('department', 'designation').order_by('first_name')

    return render(request, 'shifts/shift_detail.html', {
        'shift': shift,
        'assigned_employees': assigned_employees,
        'net_working_hours': shift.calculate_net_working_hours(),
    })


@hr_required
def shift_create(request):
    """
    Creates a new shift. Auto-calculates duration and sets overnight flag if applicable.
    """
    if request.method == 'POST':
        form = ShiftForm(request.POST, user=request.user)
        if form.is_valid():
            shift = form.save()
            messages.success(request, f"Shift '{shift.name}' was created successfully.")
            return redirect('shifts:detail', pk=shift.pk)
        else:
            messages.error(request, "Please fix the errors in the shift form.")
    else:
        form = ShiftForm(user=request.user)

    return render(request, 'shifts/shift_form.html', {
        'form': form,
        'title': 'Create New Shift',
        'is_edit': False,
    })


@hr_required
def shift_edit(request, pk):
    """
    Edits existing shift configuration.
    """
    shift = Shift.objects.filter(pk=pk).first()
    if not shift:
        messages.error(request, "Shift record does not exist or has already been removed.")
        return redirect('shifts:list')

    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != shift.company_id:
            messages.error(request, "Access denied.")
            return redirect('shifts:list')

    if request.method == 'POST':
        form = ShiftForm(request.POST, instance=shift, user=request.user)
        if form.is_valid():
            shift = form.save()
            # Also keep assigned_shift_name on employee profiles synced
            shift.employees.update(assigned_shift_name=f"{shift.name} ({shift.start_time.strftime('%H:%M')} - {shift.end_time.strftime('%H:%M')})")
            messages.success(request, f"Shift '{shift.name}' updated successfully.")
            return redirect('shifts:detail', pk=shift.pk)
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = ShiftForm(instance=shift, user=request.user)

    return render(request, 'shifts/shift_form.html', {
        'form': form,
        'shift': shift,
        'title': f'Edit Shift: {shift.name}',
        'is_edit': True,
    })


@hr_required
def shift_delete(request, pk):
    """
    Deletes shift with safeguard: prevents deletion if employees are currently assigned.
    Supports dynamic return redirection and prevents 404 on duplicate calls.
    """
    next_url = request.GET.get('next') or request.POST.get('next') or reverse('shifts:list')

    shift = Shift.objects.filter(pk=pk).first()
    if not shift:
        messages.info(request, "Shift record does not exist or has already been removed.")
        return redirect(next_url)

    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != shift.company_id:
            messages.error(request, "Access denied.")
            return redirect('shifts:list')

    if not shift.can_be_deleted():
        messages.error(
            request,
            f"Cannot delete shift '{shift.name}'. There are {shift.assigned_employee_count} employees currently assigned to this shift. Reassign them first."
        )
        return redirect('shifts:detail', pk=shift.pk)

    if request.method == 'POST':
        name = shift.name
        shift.delete()
        messages.success(request, f"Shift '{name}' was deleted.")
        return redirect(next_url)

    return render(request, 'shifts/shift_confirm_delete.html', {
        'shift': shift,
        'next_url': next_url,
    })


@hr_required
def shift_assign(request, pk):
    """
    Assigns this shift to one or multiple employees in the same company.
    Creates ShiftAssignment audit record and updates employee.assigned_shift.
    """
    shift = get_object_or_404(Shift, pk=pk)

    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != shift.company_id:
            messages.error(request, "Access denied.")
            return redirect('shifts:list')

    if request.method == 'POST':
        form = ShiftAssignForm(request.POST, shift=shift)
        if form.is_valid():
            selected_employees = form.cleaned_data['employees']
            start_date = form.cleaned_data['start_date']
            remarks = form.cleaned_data['remarks']

            shift_label = f"{shift.name} ({shift.start_time.strftime('%H:%M')} - {shift.end_time.strftime('%H:%M')})"
            for emp in selected_employees:
                # Update employee active shift
                emp.assigned_shift = shift
                emp.assigned_shift_name = shift_label
                emp.working_hours_per_day = shift.total_expected_hours
                emp.save()

                # Close any previous active assignment record
                ShiftAssignment.objects.filter(employee=emp, is_active=True).update(
                    is_active=False, end_date=start_date
                )

                # Create historical assignment record
                ShiftAssignment.objects.create(
                    employee=emp,
                    shift=shift,
                    start_date=start_date,
                    is_active=True,
                    remarks=remarks,
                    assigned_by=request.user
                )

            messages.success(request, f"Successfully assigned shift '{shift.name}' to {len(selected_employees)} employee(s).")
            return redirect('shifts:detail', pk=shift.pk)
        else:
            messages.error(request, "Please correct the assignment form errors.")
    else:
        initial = {'start_date': timezone.now().date()}
        form = ShiftAssignForm(shift=shift, initial=initial)

    return render(request, 'shifts/shift_assign.html', {
        'shift': shift,
        'form': form,
    })
