from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from accounts.decorators import hr_required, super_admin_required, role_required, manager_required
from companies.models import Company
from shifts.models import Shift
from .models import Employee, Department, Designation
from .forms import EmployeeForm, DepartmentForm, DesignationForm

User = get_user_model()


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager'])
def employee_list(request):
    """
    Rosters employees with multi-field search, filtering, and company isolation.
    """
    employees = Employee.objects.select_related(
        'company', 'department', 'designation', 'manager', 'user'
    ).order_by('-joining_date')

    # Data Isolation: Non-superusers only see their company's employees
    user_company = None
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        user_company = request.user.employee_profile.company
        employees = employees.filter(company=user_company)

    # Search query
    query = request.GET.get('q', '').strip()
    if query:
        employees = employees.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(employee_id__icontains=query) |
            Q(email__icontains=query) |
            Q(phone__icontains=query)
        )

    # Filter parameters
    company_id = request.GET.get('company')
    if company_id and request.user.is_superuser:
        employees = employees.filter(company_id=company_id)

    dept_id = request.GET.get('department')
    if dept_id:
        employees = employees.filter(department_id=dept_id)

    desig_id = request.GET.get('designation')
    if desig_id:
        employees = employees.filter(designation_id=desig_id)

    status_filter = request.GET.get('status')
    if status_filter:
        employees = employees.filter(employment_status=status_filter)

    salary_type_filter = request.GET.get('salary_type')
    if salary_type_filter:
        employees = employees.filter(salary_type=salary_type_filter)

    # Context filter dropdown options
    companies_list = Company.objects.filter(is_active=True) if request.user.is_superuser else ([user_company] if user_company else [])
    departments_list = Department.objects.all() if request.user.is_superuser else Department.objects.filter(company=user_company)
    designations_list = Designation.objects.all() if request.user.is_superuser else Designation.objects.filter(company=user_company)

    paginator = Paginator(employees, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'employees/employee_list.html', {
        'page_obj': page_obj,
        'query': query,
        'companies_list': companies_list,
        'departments_list': departments_list,
        'designations_list': designations_list,
        'selected_company': company_id,
        'selected_dept': dept_id,
        'selected_desig': desig_id,
        'selected_status': status_filter,
        'selected_salary_type': salary_type_filter,
        'total_count': employees.count(),
        'status_choices': Employee.EmploymentStatus.choices,
        'salary_choices': Employee.SalaryType.choices,
    })


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager', 'employee'])
def employee_detail(request, pk):
    """
    Displays full employee profile with compensation, reporting hierarchy,
    and history tabs (attendance, leave, payroll, biometrics).
    Enforces privacy: Regular employees can only view their own profile.
    """
    employee = Employee.objects.select_related(
        'company', 'department', 'designation', 'manager', 'user'
    ).filter(pk=pk).first()

    if not employee:
        messages.error(request, "Employee record does not exist or has already been removed.")
        return redirect('employees:list')

    # Privacy Protection
    if request.user.role == 'employee':
        if not hasattr(request.user, 'employee_profile') or request.user.employee_profile.pk != employee.pk:
            messages.error(request, "Access denied. Confidential employee records cannot be viewed by other employees.")
            return redirect('dashboard:index')

    # Company Isolation for Managers and HR Admins
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != employee.company_id:
            messages.error(request, "Access denied. Employee belongs to another company.")
            return redirect('employees:list')

    # 1. Attendance Records & Statistics
    attendances = employee.attendances.select_related('shift').order_by('-date', '-check_in_time')[:60]
    total_present = employee.attendances.filter(status__in=['present', 'late', 'half_day']).count()
    total_late = employee.attendances.filter(is_late=True).count()
    total_hours = sum((att.total_working_hours for att in employee.attendances.all() if att.total_working_hours), Decimal('0.00'))

    # 2. Leave Balances & Applications
    leave_balances = employee.leave_balances.select_related('leave_type')
    leave_applications = employee.leave_applications.select_related('leave_type').order_by('-start_date')[:10]

    # 3. Payslip History
    payslips = employee.payslips.select_related('payroll_run').order_by('-year', '-month')[:12]

    return render(request, 'employees/employee_detail.html', {
        'employee': employee,
        'attendances': attendances,
        'total_present': total_present,
        'total_late': total_late,
        'total_hours': total_hours,
        'leave_balances': leave_balances,
        'leave_applications': leave_applications,
        'payslips': payslips,
    })


@hr_required
def employee_create(request):
    """
    Creates a new employee profile and optionally creates a login account.
    """
    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            employee = form.save(commit=False)

            # Auto-generate employee ID if left blank
            if not employee.employee_id:
                employee.employee_id = Employee.generate_next_employee_id(employee.company)

            # Handle user account provisioning
            create_account = form.cleaned_data.get('create_user_account')
            if create_account:
                # Generate unique username from first name + last name or employee_id
                base_username = f"{employee.first_name.lower().replace(' ', '')}.{employee.last_name.lower().replace(' ', '')}"
                username = base_username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1

                password = form.cleaned_data.get('initial_password') or 'Employee@123'
                role = form.cleaned_data.get('user_role') or User.Role.EMPLOYEE

                user = User.objects.create_user(
                    username=username,
                    email=employee.email,
                    password=password,
                    first_name=employee.first_name,
                    last_name=employee.last_name,
                    role=role,
                    phone=employee.phone
                )

                # Attach to corresponding group
                group_name_map = {
                    User.Role.EMPLOYEE: 'Employee',
                    User.Role.MANAGER: 'Manager',
                    User.Role.HR_ADMIN: 'HR Admin',
                }
                group_name = group_name_map.get(role)
                if group_name:
                    group, _ = Group.objects.get_or_create(name=group_name)
                    user.groups.add(group)

                employee.user = user

            employee.save()
            messages.success(
                request,
                f"Employee '{employee.get_full_name()}' ({employee.employee_id}) added successfully!" +
                (f" Login account created with username: '{employee.user.username}'." if employee.user else "")
            )
            return redirect('employees:detail', pk=employee.pk)
        else:
            messages.error(request, "Please fix the errors in the employee form.")
    else:
        # Pre-populate next employee ID if company is pre-selected
        initial_data = {}
        if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
            initial_data['company'] = request.user.employee_profile.company
            initial_data['employee_id'] = Employee.generate_next_employee_id(request.user.employee_profile.company)
        elif Company.objects.exists():
            default_company = Company.objects.first()
            initial_data['company'] = default_company
            initial_data['employee_id'] = Employee.generate_next_employee_id(default_company)

        form = EmployeeForm(initial=initial_data, user=request.user)

    return render(request, 'employees/employee_form.html', {
        'form': form,
        'title': 'Add New Employee',
        'is_edit': False,
    })


@hr_required
def employee_edit(request, pk):
    """
    Updates existing employee profile and keeps linked User details synchronized.
    """
    employee = Employee.objects.filter(pk=pk).first()
    if not employee:
        messages.error(request, "Employee record does not exist or has already been removed.")
        return redirect('employees:list')

    # Company Isolation
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != employee.company_id:
            messages.error(request, "Access denied. Cannot modify employees of another company.")
            return redirect('employees:list')

    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES, instance=employee, user=request.user)
        if form.is_valid():
            employee = form.save()

            # Keep linked user synchronized
            if employee.user:
                employee.user.first_name = employee.first_name
                employee.user.last_name = employee.last_name
                employee.user.email = employee.email
                employee.user.phone = employee.phone
                new_role = form.cleaned_data.get('user_role')
                if new_role and new_role != employee.user.role:
                    employee.user.role = new_role
                    if new_role == User.Role.HR_ADMIN:
                        employee.user.is_staff = True
                    elif not employee.user.is_superuser:
                        employee.user.is_staff = False
                    group_name_map = {
                        User.Role.EMPLOYEE: 'Employee',
                        User.Role.MANAGER: 'Manager',
                        User.Role.HR_ADMIN: 'HR Admin',
                    }
                    employee.user.groups.clear()
                    group_name = group_name_map.get(new_role)
                    if group_name:
                        group, _ = Group.objects.get_or_create(name=group_name)
                        employee.user.groups.add(group)
                employee.user.save()

            messages.success(request, f"Employee '{employee.get_full_name()}' updated successfully.")
            return redirect('employees:detail', pk=employee.pk)
        else:
            messages.error(request, "Please correct the form errors.")
    else:
        form = EmployeeForm(instance=employee, user=request.user)

    return render(request, 'employees/employee_form.html', {
        'form': form,
        'employee': employee,
        'title': f'Edit Employee: {employee.get_full_name()}',
        'is_edit': True,
    })


@hr_required
def employee_delete(request, pk):
    """
    Deletes an employee record with appropriate confirmation.
    Handles duplicate requests, prevents 404 on already-deleted items,
    and supports dynamic return redirection.
    """
    next_url = request.GET.get('next') or request.POST.get('next') or reverse('employees:list')

    employee = Employee.objects.filter(pk=pk).select_related('company', 'user').first()
    if not employee:
        messages.info(request, "Employee record does not exist or has already been removed.")
        return redirect(next_url)

    # Company Isolation
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != employee.company_id:
            messages.error(request, "Access denied.")
            return redirect('employees:list')

    # Prevent self-deletion
    if hasattr(request.user, 'employee_profile') and request.user.employee_profile and request.user.employee_profile.pk == employee.pk:
        messages.error(request, "Operation prohibited: You cannot delete your own employee profile or login account.")
        return redirect('employees:detail', pk=employee.pk)

    if request.method == 'POST':
        name = employee.get_full_name()
        emp_id = employee.employee_id
        # Also clean up user account if tied only to this employee
        if employee.user and not employee.user.is_superuser:
            employee.user.delete()
        employee.delete()
        messages.success(request, f"Employee record '{name}' ({emp_id}) was successfully removed.")
        return redirect(next_url)

    return render(request, 'employees/employee_confirm_delete.html', {
        'employee': employee,
        'next_url': next_url,
    })


# =========================================================================
# Department & Designation Management
# =========================================================================

@manager_required
def department_list_create(request):
    """
    Lists departments, displays existing designations per department,
    and provides inline forms and modals to create new departments and designations.
    """
    user_company = None
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        user_company = request.user.employee_profile.company
        departments = Department.objects.filter(company=user_company)
    else:
        departments = Department.objects.all()

    departments = departments.prefetch_related('designations', 'employees').select_related('company').order_by('name')

    if request.method == 'POST':
        form = DepartmentForm(request.POST, user=request.user, user_company=user_company)
        if form.is_valid():
            dept = form.save()
            messages.success(request, f"Department '{dept.name}' added successfully.")
            return redirect('employees:departments')
        else:
            messages.error(request, "Failed to create department. Please check fields.")
    else:
        initial = {'company': user_company} if user_company else {}
        form = DepartmentForm(initial=initial, user=request.user, user_company=user_company)

    # Pre-built designation form for quick "Add Designation" modal
    desig_form = DesignationForm(user=request.user, user_company=user_company)

    # Designations count for tabs
    total_designations = Designation.objects.filter(company=user_company).count() if user_company else Designation.objects.count()

    return render(request, 'employees/departments.html', {
        'departments': departments,
        'form': form,
        'desig_form': desig_form,
        'total_designations': total_designations,
        'user_company': user_company,
    })


@manager_required
def designation_list_create(request):
    """
    Lists designations with department filtering, and provides forms to create new designations.
    """
    user_company = None
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        user_company = request.user.employee_profile.company
        designations = Designation.objects.filter(company=user_company)
        departments_list = Department.objects.filter(company=user_company).order_by('name')
    else:
        designations = Designation.objects.all()
        departments_list = Department.objects.all().select_related('company').order_by('company__name', 'name')

    selected_dept_id = request.GET.get('department')
    if selected_dept_id:
        designations = designations.filter(department_id=selected_dept_id)

    designations = designations.select_related('company', 'department').prefetch_related('employees').order_by('company__name', 'department__name', 'title')

    if request.method == 'POST':
        form = DesignationForm(request.POST, user=request.user, user_company=user_company)
        if form.is_valid():
            desig = form.save()
            messages.success(request, f"Designation '{desig.title}' added to Department '{desig.department.name}' successfully.")
            if request.POST.get('return_to') == 'departments':
                return redirect('employees:departments')
            return redirect('employees:designations')
        else:
            err_msg = "; ".join([f"{f}: {e[0]}" for f, e in form.errors.items()]) if form.errors else "Please check fields."
            messages.error(request, f"Failed to create designation. {err_msg}")
    else:
        initial = {'company': user_company} if user_company else {}
        if selected_dept_id:
            initial['department'] = selected_dept_id
        form = DesignationForm(initial=initial, user=request.user, user_company=user_company)

    total_departments = departments_list.count()

    return render(request, 'employees/designations.html', {
        'designations': designations,
        'form': form,
        'departments_list': departments_list,
        'selected_dept_id': int(selected_dept_id) if selected_dept_id and selected_dept_id.isdigit() else None,
        'total_departments': total_departments,
        'user_company': user_company,
    })


@manager_required
def designation_delete(request, pk):
    """
    Deletes a designation if it has no assigned employees.
    """
    if request.method != 'POST':
        messages.error(request, "Invalid request method.")
        return redirect('employees:designations')

    desig = get_object_or_404(Designation, pk=pk)

    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if desig.company != request.user.employee_profile.company:
            messages.error(request, "You do not have permission to delete designations from other companies.")
            return redirect('employees:designations')

    if desig.employees.exists():
        messages.error(request, f"Cannot delete designation '{desig.title}' because {desig.employees.count()} employee(s) are assigned to it.")
    else:
        title = desig.title
        dept_name = desig.department.name
        desig.delete()
        messages.success(request, f"Designation '{title}' from Department '{dept_name}' deleted successfully.")

    if request.POST.get('return_to') == 'departments':
        return redirect('employees:departments')
    return redirect('employees:designations')


@manager_required
def api_company_options(request, company_id):
    """
    Returns JSON of departments, designations, managers, and next employee ID for a company.
    Used for instant dynamic dropdown filtering in the employee creation form.
    Only managers are returned in the managers list.
    """
    company = get_object_or_404(Company, pk=company_id)

    # Permission check for company isolation
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != company.id:
            return JsonResponse({'error': 'Unauthorized company'}, status=403)

    departments = list(Department.objects.filter(company=company).order_by('name').values('id', 'name'))
    designations = list(Designation.objects.filter(company=company).order_by('title').values('id', 'title', 'department_id'))

    manager_criteria = (
        Q(user__role=User.Role.MANAGER) |
        Q(designation__title__icontains='Manager') |
        Q(designation__title__icontains='Director') |
        Q(designation__title__icontains='Head') |
        Q(designation__title__icontains='Lead') |
        Q(subordinates__isnull=False)
    )
    managers = Employee.objects.filter(
        company=company,
        employment_status=Employee.EmploymentStatus.ACTIVE
    ).filter(manager_criteria).select_related('designation', 'user').distinct().order_by('first_name', 'last_name')

    managers_data = [
        {
            'id': m.id,
            'name': f"{m.get_full_name()} ({m.designation.title if m.designation else ('HR Admin' if m.user and m.user.is_hr_admin else 'Manager')} - {m.employee_id})"
        }
        for m in managers
    ]

    next_id = Employee.generate_next_employee_id(company)

    shifts = list(Shift.objects.filter(company=company, is_active=True).values('id', 'name', 'start_time', 'end_time', 'total_expected_hours'))
    shifts_data = [
        {
            'id': s['id'],
            'name': s['name'],
            'display_time': f"{s['start_time'].strftime('%I:%M %p')} - {s['end_time'].strftime('%I:%M %p')}" if s['start_time'] and s['end_time'] else '',
            'hours': float(s['total_expected_hours'] or 8.0)
        }
        for s in shifts
    ]

    return JsonResponse({
        'departments': departments,
        'designations': designations,
        'managers': managers_data,
        'shifts': shifts_data,
        'next_employee_id': next_id,
    })


@hr_required
def user_role_management(request):
    """
    Rosters all system users and provides instant role change controls (HR Admin, Manager, Employee).
    Accessible via Sidebar -> Organization & People -> User Roles & Access.
    """
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        new_role = request.POST.get('role')
        target_user = get_object_or_404(User, pk=user_id)

        # Prevent non-superusers from modifying superuser accounts
        if target_user.is_superuser and not request.user.is_superuser:
            messages.error(request, "Permission denied: Only Super Admin can modify superuser privileges.")
            return redirect('employees:user_roles')

        valid_roles = [User.Role.EMPLOYEE, User.Role.MANAGER, User.Role.HR_ADMIN]
        if new_role in valid_roles:
            target_user.role = new_role
            if new_role == User.Role.HR_ADMIN:
                target_user.is_staff = True
            elif not target_user.is_superuser:
                target_user.is_staff = False

            # Update Django group membership
            group_name_map = {
                User.Role.EMPLOYEE: 'Employee',
                User.Role.MANAGER: 'Manager',
                User.Role.HR_ADMIN: 'HR Admin',
            }
            target_user.groups.clear()
            group_name = group_name_map.get(new_role)
            if group_name:
                group, _ = Group.objects.get_or_create(name=group_name)
                target_user.groups.add(group)

            target_user.save()
            messages.success(request, f"User '{target_user.username}' is now assigned as {target_user.get_role_display()}.")
        else:
            messages.error(request, "Invalid role specified.")
        return redirect('employees:user_roles')

    # Query users
    users_qs = User.objects.select_related('employee_profile', 'employee_profile__company').order_by('-date_joined')
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        user_company = request.user.employee_profile.company
        users_qs = users_qs.filter(Q(employee_profile__company=user_company) | Q(is_superuser=True))

    hr_count = users_qs.filter(role=User.Role.HR_ADMIN).count()
    manager_count = users_qs.filter(role=User.Role.MANAGER).count()
    employee_count = users_qs.filter(role=User.Role.EMPLOYEE).count()

    return render(request, 'employees/user_roles.html', {
        'users': users_qs,
        'hr_count': hr_count,
        'manager_count': manager_count,
        'employee_count': employee_count,
    })


@hr_required
def employee_change_role(request, pk):
    """
    Directly updates or creates the system user role for a specific employee profile.
    Called from the Employee Detail page.
    """
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        new_role = request.POST.get('role', User.Role.EMPLOYEE)
        valid_roles = [User.Role.EMPLOYEE, User.Role.MANAGER, User.Role.HR_ADMIN]
        if new_role not in valid_roles:
            messages.error(request, "Invalid role selected.")
            return redirect('employees:detail', pk=pk)

        group_name_map = {
            User.Role.EMPLOYEE: 'Employee',
            User.Role.MANAGER: 'Manager',
            User.Role.HR_ADMIN: 'HR Admin',
        }

        if employee.user:
            u = employee.user
            u.role = new_role
            if new_role == User.Role.HR_ADMIN:
                u.is_staff = True
            elif not u.is_superuser:
                u.is_staff = False
            u.groups.clear()
            g_name = group_name_map.get(new_role)
            if g_name:
                group, _ = Group.objects.get_or_create(name=g_name)
                u.groups.add(group)
            u.save()
            messages.success(request, f"Access role for {employee.get_full_name()} updated to {u.get_role_display()}.")
        else:
            # Create user account for employee
            base_username = f"{employee.first_name.lower().replace(' ', '')}.{employee.last_name.lower().replace(' ', '')}"
            username = request.POST.get('username') or base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            password = request.POST.get('password') or 'Employee@123'
            is_staff_val = (new_role == User.Role.HR_ADMIN)
            u = User.objects.create_user(
                username=username,
                email=employee.email,
                password=password,
                first_name=employee.first_name,
                last_name=employee.last_name,
                role=new_role,
                phone=employee.phone,
                is_staff=is_staff_val
            )
            g_name = group_name_map.get(new_role)
            if g_name:
                group, _ = Group.objects.get_or_create(name=g_name)
                u.groups.add(group)
            employee.user = u
            employee.save()
            messages.success(request, f"Web login created for {employee.get_full_name()} (@{u.username}) with {u.get_role_display()} access.")

    return redirect('employees:detail', pk=pk)
