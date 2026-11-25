from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from accounts.decorators import hr_required, super_admin_required
from .models import Company
from .forms import CompanyForm


@hr_required
def company_list(request):
    """
    Lists companies. Super Admins see all companies;
    HR Admins see companies they have access to.
    """
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    companies = Company.objects.annotate(
        total_employees=Count('employees', distinct=True),
        total_departments=Count('departments', distinct=True)
    ).order_by('name')

    # Data Isolation: Non-superusers can only view their assigned company
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        companies = companies.filter(id=request.user.employee_profile.company_id)

    if search_query:
        companies = companies.filter(
            Q(name__icontains=search_query) |
            Q(code__icontains=search_query) |
            Q(email__icontains=search_query)
        )

    if status_filter == 'active':
        companies = companies.filter(is_active=True)
    elif status_filter == 'inactive':
        companies = companies.filter(is_active=False)

    paginator = Paginator(companies, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'companies/company_list.html', {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'total_count': companies.count(),
    })


@hr_required
def company_detail(request, pk):
    """
    Displays full company profile, department hierarchy, employee roster, and policies.
    """
    company = Company.objects.filter(pk=pk).first()
    if not company:
        messages.error(request, "Company record does not exist or has already been removed.")
        return redirect('companies:list')

    # Check authorization for data isolation
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != company.id:
            messages.error(request, "Access denied. You can only view your own company.")
            return redirect('companies:list')

    departments = company.departments.annotate(emp_count=Count('employees')).order_by('name')
    recent_employees = company.employees.select_related('department', 'designation').order_by('-joining_date')[:8]

    return render(request, 'companies/company_detail.html', {
        'company': company,
        'departments': departments,
        'recent_employees': recent_employees,
    })


@super_admin_required
def company_create(request):
    """
    Creates a new company (Super Admin privilege).
    """
    if request.method == 'POST':
        form = CompanyForm(request.POST, request.FILES)
        if form.is_valid():
            company = form.save()
            messages.success(request, f"Company '{company.name}' ({company.code}) has been created successfully.")
            return redirect('companies:detail', pk=company.pk)
        else:
            messages.error(request, "Please correct the errors in the form below.")
    else:
        form = CompanyForm()

    return render(request, 'companies/company_form.html', {
        'form': form,
        'title': 'Register New Company',
        'is_edit': False,
    })


@super_admin_required
def company_edit(request, pk):
    """
    Edits existing company details and policies.
    """
    company = Company.objects.filter(pk=pk).first()
    if not company:
        messages.error(request, "Company record does not exist or has already been removed.")
        return redirect('companies:list')

    if request.method == 'POST':
        form = CompanyForm(request.POST, request.FILES, instance=company)
        if form.is_valid():
            company = form.save()
            messages.success(request, f"Company '{company.name}' was successfully updated.")
            return redirect('companies:detail', pk=company.pk)
        else:
            messages.error(request, "Please correct the form errors.")
    else:
        form = CompanyForm(instance=company)

    return render(request, 'companies/company_form.html', {
        'form': form,
        'company': company,
        'title': f'Edit Company: {company.name}',
        'is_edit': True,
    })


@super_admin_required
def company_delete(request, pk):
    """
    Deletes a company with safeguard: blocks deletion if employee records exist.
    Supports dynamic return redirection and prevents 404 on duplicate calls.
    """
    next_url = request.GET.get('next') or request.POST.get('next') or reverse('companies:list')

    company = Company.objects.filter(pk=pk).first()
    if not company:
        messages.info(request, "Company record does not exist or has already been removed.")
        return redirect(next_url)

    if not company.can_be_deleted():
        messages.error(
            request,
            f"Cannot delete company '{company.name}'. It contains {company.employee_count} active/registered employee records. Please reassign or remove employees first."
        )
        return redirect('companies:detail', pk=company.pk)

    if request.method == 'POST':
        name = company.name
        company.delete()
        messages.success(request, f"Company '{name}' has been safely deleted.")
        return redirect(next_url)

    return render(request, 'companies/company_confirm_delete.html', {
        'company': company,
        'next_url': next_url,
    })
