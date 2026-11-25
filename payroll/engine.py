from decimal import Decimal
import calendar
from datetime import date, timedelta
from django.db.models import Sum, Q
from companies.models import Company
from holidays.models import Holiday
from attendance.models import Attendance
from leaves.models import LeaveApplication


def number_to_words_inr(amount):
    """
    Converts a Decimal or float amount to Indian Currency words.
    e.g. 45200.50 -> "Rupees Forty Five Thousand Two Hundred and Fifty Paise Only"
    """
    try:
        amount = Decimal(str(amount)).quantize(Decimal('0.01'))
    except Exception:
        return "Rupees Zero Only"

    rupees = int(amount)
    paise = int(round((amount - Decimal(rupees)) * 100))

    if rupees == 0 and paise == 0:
        return "Rupees Zero Only"

    ones = [
        "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
        "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
        "Seventeen", "Eighteen", "Nineteen"
    ]
    tens = [
        "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"
    ]

    def two_digits(n):
        if n == 0:
            return ""
        if n < 20:
            return ones[n]
        return tens[n // 10] + (" " + ones[n % 10] if (n % 10 != 0) else "")

    def three_digits(n):
        res = ""
        h = n // 100
        rem = n % 100
        if h > 0:
            res += ones[h] + " Hundred"
            if rem > 0:
                res += " and "
        if rem > 0:
            res += two_digits(rem)
        return res

    words = []
    # Indian grouping: Crores (10,000,000), Lakhs (100,000), Thousands (1,000), Hundreds (100)
    cr = rupees // 10000000
    rupees %= 10000000
    lakh = rupees // 100000
    rupees %= 100000
    th = rupees // 1000
    rem = rupees % 1000

    if cr > 0:
        words.append(two_digits(cr) + " Crore")
    if lakh > 0:
        words.append(two_digits(lakh) + " Lakh")
    if th > 0:
        words.append(two_digits(th) + " Thousand")
    if rem > 0:
        words.append(three_digits(rem))

    result = "Rupees " + " ".join(words).strip()
    if paise > 0:
        result += " and " + two_digits(paise) + " Paise"
    result += " Only"
    return result


def compute_monthly_payroll(employee, year, month):
    """
    Computes exact monthly earnings, deductions, overtime, and LOP
    for an employee based on the company's salary calculation policy,
    holiday calendar, attendance records, and leave applications.

    Policy Rules:
    1. Fixed 30 Days:
       Final salary is based on actual attendance marks (Present, Late, Half Day)
       and includes in-between Sundays (Sundays flanked by punching days).
       Total paid days = attended days + approved paid leaves + in-between Sundays.
       Shortfall below 30 days is deducted as Loss of Pay.
    2. Fixed 26 Days / Working Hours:
       Salary is calculated directly from the employee's total working hours.
       Shortfall below 26 standard working days (26 * expected daily hours) is deducted.
    3. Actual Working Days:
       Calculates rate against month's actual business working days.
    """
    company = employee.company

    # 1. Calendar days & actual working days in month
    _, calendar_days = calendar.monthrange(year, month)
    actual_working_days = Holiday.get_working_days_in_month(company, year, month)
    start_dt = date(year, month, 1)
    end_dt = date(year, month, calendar_days)

    policy = company.salary_calculation_policy
    monthly_salary = employee.monthly_salary or Decimal('0.00')
    expected_daily_hours = employee.working_hours_per_day or company.default_working_hours or Decimal('8.00')

    # 2. Determine per-day rate divisor and base working days
    if policy == Company.SalaryCalculationPolicy.FIXED_30_DAYS:
        divisor = Decimal('30.00')
        policy_working_days = Decimal('30.00')
    elif policy in [Company.SalaryCalculationPolicy.FIXED_26_DAYS, Company.SalaryCalculationPolicy.WORKING_HOURS]:
        divisor = Decimal('26.00')
        policy_working_days = Decimal('26.00')
    else:
        divisor = Decimal(str(max(1, actual_working_days)))
        policy_working_days = Decimal(str(actual_working_days))

    # Daily and Hourly Rates
    if employee.salary_type == employee.SalaryType.DAILY and employee.daily_salary > 0:
        per_day_rate = employee.daily_salary
    else:
        per_day_rate = (monthly_salary / divisor).quantize(Decimal('0.01'))

    if employee.salary_type == employee.SalaryType.HOURLY and employee.hourly_salary > 0:
        hourly_rate = employee.hourly_salary
    else:
        hourly_rate = (per_day_rate / expected_daily_hours).quantize(Decimal('0.01'))

    # 3. Attendance analytics for the month
    attendance_qs = Attendance.objects.filter(
        employee=employee,
        date__year=year,
        date__month=month
    )

    # Full days present (PRESENT or LATE)
    full_days_count = Decimal(str(attendance_qs.filter(
        status__in=[
            Attendance.AttendanceStatus.PRESENT,
            Attendance.AttendanceStatus.LATE,
        ]
    ).count()))

    # Half day attendance counts as 0.5 present
    half_days_count = Decimal(str(attendance_qs.filter(
        status=Attendance.AttendanceStatus.HALF_DAY
    ).count())) * Decimal('0.50')

    attended_days = full_days_count + half_days_count
    unexcused_absent_days = Decimal(str(attendance_qs.filter(status=Attendance.AttendanceStatus.ABSENT).count()))
    total_ot_hours = attendance_qs.aggregate(total_ot=Sum('overtime_hours'))['total_ot'] or Decimal('0.00')

    # Total Worked Hours across all attendance records
    total_worked_hours = Decimal('0.00')
    for att in attendance_qs:
        if att.total_working_hours and att.total_working_hours > 0:
            total_worked_hours += att.total_working_hours
        elif att.check_in_time and att.check_out_time:
            diff_secs = (att.check_out_time - att.check_in_time).total_seconds()
            total_worked_hours += Decimal(str(round(max(0.0, diff_secs / 3600.0), 2)))
        elif att.status in [Attendance.AttendanceStatus.PRESENT, Attendance.AttendanceStatus.LATE]:
            total_worked_hours += expected_daily_hours
        elif att.status == Attendance.AttendanceStatus.HALF_DAY:
            total_worked_hours += (expected_daily_hours / Decimal('2.0'))

    # 4. Leave applications for the month
    leaves_qs = LeaveApplication.objects.filter(
        employee=employee,
        status=LeaveApplication.ApplicationStatus.APPROVED,
        start_date__lte=end_dt,
        end_date__gte=start_dt
    ).select_related('leave_type')

    paid_leave_days = Decimal('0.00')
    unpaid_leave_days = Decimal('0.00')

    for lv in leaves_qs:
        s = max(lv.start_date, start_dt)
        e = min(lv.end_date, end_dt)
        if lv.is_half_day:
            cur_days = Decimal('0.50')
        else:
            cur = s
            cnt = 0
            while cur <= e:
                if Holiday.is_working_day(company, cur):
                    cnt += 1
                cur += timedelta(days=1)
            cur_days = Decimal(str(cnt))

        if lv.leave_type.is_paid:
            paid_leave_days += cur_days
        else:
            unpaid_leave_days += cur_days

    # 5. Policy-Specific Computation (30 Days vs 26 Days / Working Hours vs Actual Working Days)
    sundays_included_count = Decimal('0.00')

    if policy == Company.SalaryCalculationPolicy.FIXED_30_DAYS:
        # PUNCH DATES in this month
        active_punch_dates = set(
            attendance_qs.filter(
                Q(check_in_time__isnull=False) |
                Q(status__in=[
                    Attendance.AttendanceStatus.PRESENT,
                    Attendance.AttendanceStatus.LATE,
                    Attendance.AttendanceStatus.HALF_DAY
                ])
            ).values_list('date', flat=True)
        )
        # Expanded punch dates (+/- 3 days) for smooth month-boundary transitions
        expanded_punch_dates = set(
            Attendance.objects.filter(
                employee=employee,
                date__gte=start_dt - timedelta(days=3),
                date__lte=end_dt + timedelta(days=3),
            ).filter(
                Q(check_in_time__isnull=False) |
                Q(status__in=[
                    Attendance.AttendanceStatus.PRESENT,
                    Attendance.AttendanceStatus.LATE,
                    Attendance.AttendanceStatus.HALF_DAY
                ])
            ).values_list('date', flat=True)
        )

        # In-between Sundays (Sundays falling between active punch days)
        in_between_cnt = 0
        for day_num in range(1, calendar_days + 1):
            cur_d = date(year, month, day_num)
            if cur_d.weekday() == 6:  # Sunday
                if cur_d in active_punch_dates:
                    # Already counted as present work day
                    continue
                has_before = any(p < cur_d for p in expanded_punch_dates)
                has_after = any(p > cur_d for p in expanded_punch_dates)
                if has_before and has_after:
                    in_between_cnt += 1

        sundays_included_count = Decimal(str(in_between_cnt))
        total_paid_days = attended_days + paid_leave_days + sundays_included_count
        total_paid_days = min(Decimal('30.00'), total_paid_days)

        total_lop_days = max(Decimal('0.00'), Decimal('30.00') - total_paid_days)
        lop_deduction = (total_lop_days * per_day_rate).quantize(Decimal('0.01'))
        days_present = attended_days + sundays_included_count

    elif policy in [Company.SalaryCalculationPolicy.FIXED_26_DAYS, Company.SalaryCalculationPolicy.WORKING_HOURS]:
        # Calculate salary directly based on employee's total working hours
        total_expected_hours = (Decimal('26.00') * expected_daily_hours).quantize(Decimal('0.01'))
        paid_leave_hours = (paid_leave_days * expected_daily_hours).quantize(Decimal('0.01'))
        total_credited_hours = total_worked_hours + paid_leave_hours

        shortfall_hours = max(Decimal('0.00'), total_expected_hours - total_credited_hours)
        lop_deduction = (shortfall_hours * hourly_rate).quantize(Decimal('0.01'))

        # Effective days present and LOP days for reporting
        effective_days_present = (total_worked_hours / expected_daily_hours).quantize(Decimal('0.01'))
        effective_lop_days = (shortfall_hours / expected_daily_hours).quantize(Decimal('0.01'))

        days_present = effective_days_present
        total_lop_days = effective_lop_days

    else:
        # ACTUAL_WORKING_DAYS
        total_lop_days = unpaid_leave_days + unexcused_absent_days
        lop_deduction = (total_lop_days * per_day_rate).quantize(Decimal('0.01'))
        days_present = attended_days

    # 6. Earnings Breakdown
    basic_salary = (monthly_salary * Decimal('0.50')).quantize(Decimal('0.01'))
    hra = (monthly_salary * Decimal('0.30')).quantize(Decimal('0.01'))
    conveyance = (monthly_salary * Decimal('0.10')).quantize(Decimal('0.01'))
    special_allowance = (monthly_salary - (basic_salary + hra + conveyance)).quantize(Decimal('0.01'))

    overtime_pay = (total_ot_hours * hourly_rate * Decimal('1.50')).quantize(Decimal('0.01'))
    bonus = Decimal('0.00')
    gross_earnings = (monthly_salary + overtime_pay + bonus).quantize(Decimal('0.01'))

    # 7. Statutory Deductions based on earned compensation
    earned_gross = max(Decimal('0.00'), gross_earnings - lop_deduction)
    earned_basic = max(Decimal('0.00'), basic_salary - (lop_deduction * Decimal('0.50')))

    # Provident Fund = 12% of earned basic
    if basic_salary > 0 and earned_basic > 0:
        pf_deduction = (earned_basic * Decimal('0.12')).quantize(Decimal('0.01'))
    else:
        pf_deduction = Decimal('0.00')

    # ESI = 0.75% of earned gross if earned gross <= ₹21,000
    if earned_gross <= Decimal('21000.00') and earned_gross > Decimal('0.00'):
        esi_deduction = (earned_gross * Decimal('0.0075')).quantize(Decimal('0.01'))
    else:
        esi_deduction = Decimal('0.00')

    # Professional Tax = ₹200 if earned gross > ₹15,000
    if earned_gross > Decimal('15000.00'):
        pt_deduction = Decimal('200.00')
    else:
        pt_deduction = Decimal('0.00')

    tds_deduction = Decimal('0.00')
    other_deductions = Decimal('0.00')

    total_deductions = (
        lop_deduction + pf_deduction + esi_deduction + pt_deduction + tds_deduction + other_deductions
    ).quantize(Decimal('0.01'))

    # 8. Net Pay
    net_pay = max(Decimal('0.00'), (gross_earnings - total_deductions).quantize(Decimal('0.01')))
    net_pay_words = number_to_words_inr(net_pay)

    return {
        'calendar_days': calendar_days,
        'working_days': policy_working_days,
        'per_day_rate': per_day_rate,
        'hourly_rate': hourly_rate,
        'days_present': days_present,
        'paid_leaves': paid_leave_days,
        'unpaid_leaves': total_lop_days,
        'overtime_hours': total_ot_hours,
        'basic_salary': basic_salary,
        'hra': hra,
        'conveyance': conveyance,
        'medical_allowance': Decimal('0.00'),
        'special_allowance': special_allowance,
        'overtime_pay': overtime_pay,
        'bonus': bonus,
        'gross_earnings': gross_earnings,
        'loss_of_pay_deduction': lop_deduction,
        'provident_fund': pf_deduction,
        'esi': esi_deduction,
        'professional_tax': pt_deduction,
        'tds': tds_deduction,
        'other_deductions': other_deductions,
        'total_deductions': total_deductions,
        'net_pay': net_pay,
        'net_pay_in_words': net_pay_words,
        'sundays_included': sundays_included_count,
        'total_worked_hours': total_worked_hours,
    }
