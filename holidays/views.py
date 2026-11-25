import calendar
from datetime import date, datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import JsonResponse
from django.utils import timezone
from accounts.decorators import hr_required, role_required
from companies.models import Company
from .models import Holiday
from .forms import HolidayForm, HolidayFilterForm


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager', 'employee'])
def holiday_list(request):
    """
    Roster listing of company holidays with year filtering, multi-company isolation,
    and upcoming vs all-year views.
    """
    now = timezone.now()
    current_year = now.year
    today = now.date()

    # Data Isolation
    user_company = None
    holidays = Holiday.objects.select_related('company').order_by('date')
    if not request.user.is_superuser:
        if hasattr(request.user, 'employee_profile') and request.user.employee_profile:
            user_company = request.user.employee_profile.company
            holidays = holidays.filter(company=user_company)
        else:
            holidays = holidays.none()

    # Search query
    query = request.GET.get('q', '').strip()
    if query:
        holidays = holidays.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )

    # Year Filter (Default current year)
    year_param = request.GET.get('year')
    selected_year = int(year_param) if year_param and year_param.isdigit() else current_year
    holidays = holidays.filter(date__year=selected_year)

    # Type Filter
    holiday_type = request.GET.get('holiday_type')
    if holiday_type:
        holidays = holidays.filter(holiday_type=holiday_type)

    # Company Filter (Superuser only)
    comp_param = request.GET.get('company')
    if comp_param and request.user.is_superuser:
        holidays = holidays.filter(company_id=comp_param)

    # Metrics for selected year
    total_holidays = holidays.count()
    mandatory_count = holidays.filter(is_optional=False).count()
    optional_count = holidays.filter(is_optional=True).count()
    upcoming_count = holidays.filter(date__gte=today).count()

    # View tab (all vs upcoming)
    view_tab = request.GET.get('tab', 'all')
    if view_tab == 'upcoming':
        display_holidays = holidays.filter(date__gte=today)
    else:
        display_holidays = holidays

    paginator = Paginator(display_holidays, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    companies_list = Company.objects.filter(is_active=True) if request.user.is_superuser else ([user_company] if user_company else [])

    return render(request, 'holidays/holiday_list.html', {
        'page_obj': page_obj,
        'selected_year': selected_year,
        'current_year': current_year,
        'query': query,
        'holiday_type': holiday_type,
        'selected_company': comp_param,
        'companies_list': companies_list,
        'total_holidays': total_holidays,
        'mandatory_count': mandatory_count,
        'optional_count': optional_count,
        'upcoming_count': upcoming_count,
        'view_tab': view_tab,
        'today': today,
    })


@role_required(allowed_roles=['super_admin', 'hr_admin', 'manager', 'employee'])
def holiday_calendar(request):
    """
    Visual monthly calendar grid highlighting company public holidays and scheduled weekly offs.
    """
    now = timezone.now()
    year = int(request.GET.get('year', now.year))
    month = int(request.GET.get('month', now.month))

    # Clamp month bounds
    if month < 1:
        month = 12
        year -= 1
    elif month > 12:
        month = 1
        year += 1

    # Resolve company
    company = None
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        company = request.user.employee_profile.company
    else:
        comp_id = request.GET.get('company')
        if comp_id:
            company = Company.objects.filter(id=comp_id).first()
        if not company:
            company = Company.objects.filter(is_active=True).first()

    companies_list = Company.objects.filter(is_active=True) if request.user.is_superuser else ([company] if company else [])

    # Fetch holidays for this company in this month
    month_holidays = {}
    if company:
        holidays_qs = Holiday.objects.filter(company=company, date__year=year, date__month=month)
        for h in holidays_qs:
            month_holidays[h.date] = h

    # Calculate calendar matrix (Weeks x 7 Days starting Monday)
    cal = calendar.Calendar(firstweekday=0)
    month_matrix = cal.monthdatescalendar(year, month)

    calendar_weeks = []
    for week in month_matrix:
        week_days = []
        for d in week:
            is_cur_month = (d.month == month)
            is_today = (d == now.date())
            weekday = d.weekday()  # Monday=0 ... Sunday=6

            # Determine weekly off status according to company policy
            is_weekly_off = False
            if company:
                if company.weekly_holiday_policy == Company.WeeklyHolidayPolicy.SATURDAY_SUNDAY:
                    is_weekly_off = weekday in [5, 6]
                elif company.weekly_holiday_policy == Company.WeeklyHolidayPolicy.SUNDAY_ONLY:
                    is_weekly_off = (weekday == 6)

            holiday_obj = month_holidays.get(d)

            week_days.append({
                'date': d,
                'day': d.day,
                'is_current_month': is_cur_month,
                'is_today': is_today,
                'is_weekly_off': is_weekly_off,
                'holiday': holiday_obj,
            })
        calendar_weeks.append(week_days)

    # Previous and next month navigation
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    month_name = calendar.month_name[month]

    # Month statistics
    working_days_count = Holiday.get_working_days_in_month(company, year, month) if company else 0

    return render(request, 'holidays/holiday_calendar.html', {
        'company': company,
        'companies_list': companies_list,
        'year': year,
        'month': month,
        'month_name': month_name,
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
        'calendar_weeks': calendar_weeks,
        'month_holidays_count': len(month_holidays),
        'working_days_count': working_days_count,
    })


@hr_required
def holiday_create(request):
    """
    Creates a new holiday on the company calendar.
    """
    if request.method == 'POST':
        form = HolidayForm(request.POST, user=request.user)
        if form.is_valid():
            holiday = form.save(commit=False)
            if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
                holiday.company = request.user.employee_profile.company

            # Check unique constraint manually for friendly message
            if Holiday.objects.filter(company=holiday.company, date=holiday.date).exists():
                form.add_error('date', f"A holiday already exists for {holiday.company.code} on {holiday.date}.")
            else:
                holiday.save()
                messages.success(request, f"Holiday '{holiday.name}' was added to the {holiday.company.name} calendar.")
                return redirect('holidays:list')
        else:
            messages.error(request, "Please fix the form errors below.")
    else:
        form = HolidayForm(user=request.user)

    return render(request, 'holidays/holiday_form.html', {
        'form': form,
        'title': 'Add New Holiday',
        'is_edit': False,
    })


@hr_required
def holiday_edit(request, pk):
    """
    Edits an existing holiday.
    """
    holiday = Holiday.objects.filter(pk=pk).first()
    if not holiday:
        messages.error(request, "Holiday record does not exist or has already been removed.")
        return redirect('holidays:list')

    # Data Isolation
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != holiday.company_id:
            messages.error(request, "Access denied. Holiday belongs to another company.")
            return redirect('holidays:list')

    if request.method == 'POST':
        form = HolidayForm(request.POST, instance=holiday, user=request.user)
        if form.is_valid():
            updated = form.save()
            messages.success(request, f"Holiday '{updated.name}' updated successfully.")
            return redirect('holidays:list')
        else:
            messages.error(request, "Please correct the form errors.")
    else:
        form = HolidayForm(instance=holiday, user=request.user)

    return render(request, 'holidays/holiday_form.html', {
        'form': form,
        'holiday': holiday,
        'title': f'Edit Holiday: {holiday.name}',
        'is_edit': True,
    })


@hr_required
def holiday_delete(request, pk):
    """
    Deletes an existing holiday.
    Supports dynamic return redirection and prevents 404 on duplicate calls.
    """
    next_url = request.GET.get('next') or request.POST.get('next') or reverse('holidays:list')

    holiday = Holiday.objects.filter(pk=pk).first()
    if not holiday:
        messages.info(request, "Holiday record does not exist or has already been removed.")
        return redirect(next_url)

    # Data Isolation
    if not request.user.is_superuser and hasattr(request.user, 'employee_profile') and request.user.employee_profile:
        if request.user.employee_profile.company_id != holiday.company_id:
            messages.error(request, "Access denied.")
            return redirect('holidays:list')

    if request.method == 'POST':
        name = holiday.name
        holiday.delete()
        messages.success(request, f"Holiday '{name}' was removed from the calendar.")
        return redirect(next_url)

    return render(request, 'holidays/holiday_confirm_delete.html', {
        'holiday': holiday,
        'next_url': next_url,
    })


def api_holidays(request):
    """
    JSON endpoint providing holidays for dynamic integrations.
    """
    year = request.GET.get('year', timezone.now().year)
    company_id = request.GET.get('company')

    holidays = Holiday.objects.filter(date__year=year)
    if company_id:
        holidays = holidays.filter(company_id=company_id)
    elif request.user.is_authenticated and not request.user.is_superuser and hasattr(request.user, 'employee_profile'):
        holidays = holidays.filter(company=request.user.employee_profile.company)

    data = [
        {
            'id': h.id,
            'title': h.name,
            'date': h.date.strftime('%Y-%m-%d'),
            'type': h.holiday_type,
            'is_optional': h.is_optional,
            'company': h.company.code,
        }
        for h in holidays
    ]
    return JsonResponse({'status': 'success', 'holidays': data})
