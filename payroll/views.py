import csv
from decimal import Decimal
import calendar
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden, HttpResponse
from django.core.exceptions import PermissionDenied
from django.db.models import Sum, Q
from django.utils import timezone
from companies.models import Company
from employees.models import Employee
from .models import PayrollRun, Payslip
from .forms import PayrollRunCreateForm, PayslipPaymentUpdateForm, PayrollFilterForm, BatchDisbursalForm


@login_required
def payroll_dashboard(request):
    """
    Payroll Dashboard for HR Admin and Super Admin:
    Overview of monthly payroll runs, year-to-date disbursements, and status controls.
    """
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        # Redirect employees to their personal payslips
        return redirect('payroll:my_payslips')

    employee = getattr(user, 'employee_profile', None)
    runs = PayrollRun.objects.select_related('company', 'processed_by')

    if not user.is_super_admin:
        if employee:
            runs = runs.filter(company=employee.company)
        else:
            runs = runs.none()

    filter_form = PayrollFilterForm(request.GET)
    if filter_form.is_valid():
        year_val = filter_form.cleaned_data.get('year')
        month_val = filter_form.cleaned_data.get('month')
        status_val = filter_form.cleaned_data.get('status')

        if year_val:
            runs = runs.filter(year=year_val)
        if month_val:
            runs = runs.filter(month=month_val)
        if status_val:
            runs = runs.filter(status=status_val)

    # Metrics
    total_runs_count = runs.count()
    total_disbursed = runs.aggregate(total=Sum('total_net_pay'))['total'] or Decimal('0.00')
    total_gross_paid = runs.aggregate(total=Sum('total_gross'))['total'] or Decimal('0.00')
    total_deductions_made = runs.aggregate(total=Sum('total_deductions'))['total'] or Decimal('0.00')

    context = {
        'runs': runs.order_by('-year', '-month'),
        'filter_form': filter_form,
        'total_runs_count': total_runs_count,
        'total_disbursed': total_disbursed,
        'total_gross_paid': total_gross_paid,
        'total_deductions_made': total_deductions_made,
    }
    return render(request, 'payroll/payroll_dashboard.html', context)


@login_required
def payroll_run_create(request):
    """
    Initiates and processes a new monthly payroll batch.
    """
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    if request.method == 'POST':
        form = PayrollRunCreateForm(request.POST, user=user)
        if form.is_valid():
            company = form.cleaned_data['company']
            month = form.cleaned_data['month']
            year = form.cleaned_data['year']

            # Check if run already exists
            existing_run = PayrollRun.objects.filter(company=company, year=year, month=month).first()
            if existing_run:
                messages.warning(request, f"Payroll for {company.name} - {calendar.month_name[month]} {year} already exists.")
                return redirect('payroll:run_detail', pk=existing_run.id)

            run = form.save(commit=False)
            if not user.is_super_admin and hasattr(user, 'employee_profile') and user.employee_profile:
                run.company = user.employee_profile.company
            run.save()

            # Execute calculation engine
            try:
                run.generate_payslips(user)
                messages.success(request, f"Payroll for {run.month_display_name} processed successfully for {run.total_employees} employees.")
            except Exception as e:
                messages.error(request, f"Error calculating payroll: {str(e)}")

            return redirect('payroll:run_detail', pk=run.id)
    else:
        now = timezone.now()
        initial = {'year': now.year, 'month': now.month}
        form = PayrollRunCreateForm(user=user, initial=initial)

    return render(request, 'payroll/payroll_run_create.html', {'form': form})


@login_required
def payroll_run_detail(request, pk):
    """
    Details of a specific Payroll Run:
    Displays roll-up statistics and the roster of individual payslips.
    """
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    run = PayrollRun.objects.select_related('company', 'processed_by').filter(pk=pk).first()
    if not run:
        messages.error(request, "Payroll run record does not exist or has already been removed.")
        return redirect('payroll:dashboard')

    if not user.is_super_admin:
        employee = getattr(user, 'employee_profile', None)
        if not employee or run.company_id != employee.company_id:
            raise PermissionDenied("You can only access payroll runs for your own company.")

    payslips = run.payslips.select_related('employee', 'employee__designation', 'employee__department').order_by('employee__employee_id')

    # Optional search filter inside the run
    search_q = request.GET.get('q', '').strip()
    if search_q:
        payslips = payslips.filter(
            Q(employee__first_name__icontains=search_q) |
            Q(employee__last_name__icontains=search_q) |
            Q(employee__employee_id__icontains=search_q)
        )

    # Shift & Attendance Aggregates across this run
    all_payslips = run.payslips.all()
    pending_count = all_payslips.filter(payment_status='pending').count()
    paid_count = all_payslips.filter(payment_status='paid').count()
    total_scheduled_hours = all_payslips.aggregate(h=Sum('scheduled_shift_hours'))['h'] or Decimal('0.00')
    total_worked_hours = all_payslips.aggregate(h=Sum('actual_worked_hours'))['h'] or Decimal('0.00')
    total_overtime_hours = all_payslips.aggregate(h=Sum('overtime_hours'))['h'] or Decimal('0.00')
    total_shortfall_hours = all_payslips.aggregate(h=Sum('shortfall_hours'))['h'] or Decimal('0.00')

    batch_form = BatchDisbursalForm(initial={
        'payment_date': timezone.now().date(),
        'payment_reference': f"NEFT-{run.company.code}-{run.year}{run.month:02d}"
    })

    context = {
        'run': run,
        'payslips': payslips,
        'search_q': search_q,
        'pending_count': pending_count,
        'paid_count': paid_count,
        'total_scheduled_hours': total_scheduled_hours,
        'total_worked_hours': total_worked_hours,
        'total_overtime_hours': total_overtime_hours,
        'total_shortfall_hours': total_shortfall_hours,
        'batch_form': batch_form,
    }
    return render(request, 'payroll/payroll_run_detail.html', context)


@login_required
def payroll_run_disburse_batch(request, pk):
    """
    HR action to batch disburse all payslips in a payroll run in one bulk operation.
    Marks all pending payslips as Paid with reference ID and disbursal date.
    """
    if request.method != 'POST':
        return HttpResponseForbidden("Method not allowed")

    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    run = PayrollRun.objects.filter(pk=pk).first()
    if not run:
        messages.error(request, "Payroll run not found.")
        return redirect('payroll:dashboard')

    if not user.is_super_admin:
        employee = getattr(user, 'employee_profile', None)
        if not employee or run.company_id != employee.company_id:
            raise PermissionDenied("You can only access payroll runs for your own company.")

    if run.status == PayrollRun.RunStatus.LOCKED:
        messages.error(request, "This payroll run is locked and cannot be modified.")
        return redirect('payroll:run_detail', pk=pk)

    mode = request.POST.get('payment_mode', 'bank_transfer')
    date_str = request.POST.get('payment_date')
    ref = request.POST.get('payment_reference', '').strip()
    if not ref:
        ref = f"NEFT-{run.company.code}-{run.year}{run.month:02d}-{int(timezone.now().timestamp())}"

    p_date = None
    if date_str:
        try:
            p_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception:
            p_date = timezone.now().date()

    run.disburse_all(payment_mode=mode, payment_date=p_date, payment_reference=ref, user=user)
    messages.success(request, f"Payroll run for {run.month_display_name} has been marked as DISBURSED! (Reference: {ref}).")
    return redirect('payroll:run_detail', pk=pk)


@login_required
def payroll_export_bank_transfer(request, pk):
    """
    Exports upload-ready corporate banking CSV file (NEFT / RTGS / Direct Debit).
    """
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    run = PayrollRun.objects.select_related('company').filter(pk=pk).first()
    if not run:
        messages.error(request, "Payroll run not found.")
        return redirect('payroll:dashboard')

    if not user.is_super_admin:
        employee = getattr(user, 'employee_profile', None)
        if not employee or run.company_id != employee.company_id:
            raise PermissionDenied("Access restricted to your company.")

    payslips = run.payslips.select_related('employee').order_by('employee__employee_id')

    filename = f"Bank_Transfer_{run.company.code}_{run.year}_{run.month:02d}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        'Beneficiary Account Number',
        'Beneficiary Name',
        'IFSC Code',
        'Bank Name',
        'Amount (INR)',
        'Employee ID',
        'Payment Date',
        'Narration'
    ])

    p_date = run.disbursed_at.date().strftime('%d-%m-%Y') if run.disbursed_at else timezone.now().date().strftime('%d-%m-%Y')
    narration = f"Salary {calendar.month_name[run.month]} {run.year}"

    for p in payslips:
        acc_no = p.bank_account_number or p.employee.bank_account_number or 'NOT_PROVIDED'
        ifsc = p.bank_ifsc or p.employee.bank_ifsc_code or 'NOT_PROVIDED'
        bank_name = p.bank_name or p.employee.bank_name or 'Corporate Bank'
        writer.writerow([
            acc_no,
            p.employee.get_full_name(),
            ifsc,
            bank_name,
            str(p.net_pay),
            p.employee.employee_id,
            p_date,
            narration
        ])

    return response


@login_required
def payroll_export_salary_register(request, pk):
    """
    Exports comprehensive salary register CSV for accounting and audit compliance.
    """
    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    run = PayrollRun.objects.select_related('company').filter(pk=pk).first()
    if not run:
        messages.error(request, "Payroll run not found.")
        return redirect('payroll:dashboard')

    if not user.is_super_admin:
        employee = getattr(user, 'employee_profile', None)
        if not employee or run.company_id != employee.company_id:
            raise PermissionDenied("Access restricted to your company.")

    payslips = run.payslips.select_related('employee', 'employee__department', 'employee__designation').order_by('employee__employee_id')

    filename = f"Salary_Register_{run.company.code}_{run.year}_{run.month:02d}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        'Employee ID',
        'Employee Name',
        'Department',
        'Designation',
        'Assigned Shift',
        'Daily Shift Hours',
        'Working Days in Month',
        'Days Present',
        'Paid Leaves',
        'Unpaid LOP Days',
        'Scheduled Shift Hours',
        'Actual Worked Hours',
        'Shortfall Hours',
        'Overtime Hours',
        'Hourly Rate',
        'Basic Salary',
        'HRA',
        'Conveyance',
        'Special Allowance',
        'Shift Allowance',
        'Overtime Pay',
        'Bonus',
        'Gross Earnings',
        'Loss of Pay (LOP)',
        'Provident Fund (EPF)',
        'ESI',
        'Professional Tax (PT)',
        'TDS',
        'Total Deductions',
        'Net Pay',
        'Payment Status',
        'Payment Mode',
        'Payment Reference'
    ])

    for p in payslips:
        writer.writerow([
            p.employee.employee_id,
            p.employee.get_full_name(),
            p.employee.department.name if p.employee.department else '',
            p.employee.designation.title if p.employee.designation else '',
            p.shift_name,
            str(p.shift_daily_hours),
            str(p.working_days),
            str(p.days_present),
            str(p.paid_leaves),
            str(p.unpaid_leaves),
            str(p.scheduled_shift_hours),
            str(p.actual_worked_hours),
            str(p.shortfall_hours),
            str(p.overtime_hours),
            str(p.hourly_rate),
            str(p.basic_salary),
            str(p.hra),
            str(p.conveyance),
            str(p.special_allowance),
            str(p.shift_allowance),
            str(p.overtime_pay),
            str(p.bonus),
            str(p.gross_earnings),
            str(p.loss_of_pay_deduction),
            str(p.provident_fund),
            str(p.esi),
            str(p.professional_tax),
            str(p.tds),
            str(p.total_deductions),
            str(p.net_pay),
            p.get_payment_status_display(),
            p.get_payment_mode_display(),
            p.payment_reference
        ])

    return response


@login_required
def payroll_run_recalculate(request, pk):
    """
    POST action to refresh calculations in a draft/processed payroll run.
    """
    if request.method != 'POST':
        return HttpResponseForbidden("Method not allowed")

    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    run = PayrollRun.objects.filter(pk=pk).first()
    if not run:
        messages.error(request, "Payroll run not found.")
        return redirect('payroll:dashboard')
    if not user.is_super_admin:
        employee = getattr(user, 'employee_profile', None)
        if not employee or run.company_id != employee.company_id:
            raise PermissionDenied("You can only access payroll runs for your own company.")

    if run.status == PayrollRun.RunStatus.LOCKED:
        messages.error(request, "This payroll run is locked and cannot be recalculated.")
        return redirect('payroll:run_detail', pk=pk)

    run.generate_payslips(user)
    messages.success(request, f"Payroll calculations updated successfully for {run.total_employees} employees.")
    return redirect('payroll:run_detail', pk=pk)


@login_required
def payroll_run_lock(request, pk):
    """
    POST action to finalize and lock a payroll run for audit compliance.
    """
    if request.method != 'POST':
        return HttpResponseForbidden("Method not allowed")

    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    run = PayrollRun.objects.filter(pk=pk).first()
    if not run:
        messages.error(request, "Payroll run not found.")
        return redirect('payroll:dashboard')
    if not user.is_super_admin:
        employee = getattr(user, 'employee_profile', None)
        if not employee or run.company_id != employee.company_id:
            raise PermissionDenied("You can only access payroll runs for your own company.")

    run.lock(user)
    messages.success(request, f"Payroll run for {run.month_display_name} has been LOCKED and finalized.")
    return redirect('payroll:run_detail', pk=pk)


@login_required
def payslip_detail(request, pk):
    """
    Printable and downloadable corporate payslip view.
    Accessible to: Super Admin, HR Admin (same company), Manager (subordinate), or applicant employee.
    """
    user = request.user
    payslip = Payslip.objects.select_related(
        'employee', 'employee__designation', 'employee__department', 'company', 'payroll_run'
    ).filter(pk=pk).first()
    if not payslip:
        messages.error(request, "Payslip record does not exist or has already been removed.")
        return redirect('payroll:dashboard')

    can_view = False
    employee = getattr(user, 'employee_profile', None)

    if user.is_super_admin:
        can_view = True
    elif user.is_hr_admin and employee and employee.company_id == payslip.company_id:
        can_view = True
    elif user.is_manager_user and employee and payslip.employee.manager_id == employee.id:
        can_view = True
    elif employee and payslip.employee_id == employee.id:
        can_view = True

    if not can_view:
        raise PermissionDenied("You are not authorized to view this payslip.")

    payment_form = PayslipPaymentUpdateForm(instance=payslip) if (user.is_super_admin or user.is_hr_admin) else None

    context = {
        'payslip': payslip,
        'payment_form': payment_form,
        'can_update_payment': (user.is_super_admin or user.is_hr_admin),
    }
    return render(request, 'payroll/payslip_detail.html', context)


@login_required
def update_payslip_payment(request, pk):
    """
    HR action to mark a payslip as Paid / Disbursed with reference ID.
    """
    if request.method != 'POST':
        return HttpResponseForbidden("Method not allowed")

    user = request.user
    if not (user.is_super_admin or user.is_hr_admin):
        raise PermissionDenied("Access restricted to HR and Super Admins.")

    payslip = Payslip.objects.filter(pk=pk).first()
    if not payslip:
        messages.error(request, "Payslip not found.")
        return redirect('payroll:dashboard')
    form = PayslipPaymentUpdateForm(request.POST, instance=payslip)
    if form.is_valid():
        form.save()
        messages.success(request, f"Payment status updated for {payslip.employee.get_full_name()}.")
    return redirect('payroll:payslip_detail', pk=pk)


@login_required
def my_payslips(request):
    """
    Self-service portal for employees to view and print their personal payslips.
    """
    user = request.user
    employee = getattr(user, 'employee_profile', None)

    if not employee:
        messages.warning(request, "Your login account is not linked to an active Employee profile.")
        return render(request, 'payroll/my_payslips.html', {'payslips': []})

    payslips = Payslip.objects.filter(employee=employee).select_related('company', 'payroll_run').order_by('-year', '-month')

    context = {
        'employee': employee,
        'payslips': payslips,
    }
    return render(request, 'payroll/my_payslips.html', context)
