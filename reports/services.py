import calendar
import io
from datetime import date, timedelta
from decimal import Decimal
import pandas as pd
from django.http import HttpResponse
from companies.models import Company
from employees.models import Employee
from attendance.models import Attendance
from holidays.models import Holiday
from leaves.models import LeaveBalance, LeaveType
from payroll.models import PayrollRun, Payslip


def export_dataframe_response(df, filename_base, format='excel'):
    """
    Utility function to convert a pandas DataFrame into a downloadable
    Excel (.xlsx) or CSV (.csv) HTTP response.
    """
    if format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename_base}.csv"'
        df.to_csv(path_or_buf=response, index=False)
        return response
    else:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Report')
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename_base}.xlsx"'
        return response


def generate_attendance_muster(company, year, month, format='excel'):
    """
    Generates a monthly attendance muster sheet matrix (Days 1 to N)
    with punctuality status codes, summary attendance counts, and overtime.
    """
    _, num_days = calendar.monthrange(year, month)
    employees = Employee.objects.filter(
        company=company,
        employment_status=Employee.EmploymentStatus.ACTIVE
    ).select_related('department', 'designation').order_by('employee_id')

    # Status codes mapping
    status_code_map = {
        Attendance.AttendanceStatus.PRESENT: 'P',
        Attendance.AttendanceStatus.LATE: 'L',
        Attendance.AttendanceStatus.HALF_DAY: 'HD',
        Attendance.AttendanceStatus.ABSENT: 'A',
        Attendance.AttendanceStatus.ON_LEAVE: 'OL',
        Attendance.AttendanceStatus.WEEKLY_OFF: 'WO',
        Attendance.AttendanceStatus.HOLIDAY: 'H',
    }

    records = []
    for emp in employees:
        row = {
            'Employee ID': emp.employee_id,
            'Name': emp.get_full_name(),
            'Department': emp.department.name if emp.department else '',
            'Designation': emp.designation.title if emp.designation else '',
        }

        # Query all attendances for this employee in month
        att_qs = Attendance.objects.filter(
            employee=emp,
            date__year=year,
            date__month=month
        )
        att_by_day = {a.date.day: a for a in att_qs}

        present_cnt = 0
        late_cnt = 0
        half_cnt = 0
        leave_cnt = 0
        absent_cnt = 0
        total_ot = Decimal('0.00')

        for d in range(1, num_days + 1):
            cur_date = date(year, month, d)
            col_name = str(d)

            if d in att_by_day:
                att = att_by_day[d]
                code = status_code_map.get(att.status, 'P')
                if att.status in [Attendance.AttendanceStatus.PRESENT, Attendance.AttendanceStatus.LATE]:
                    present_cnt += 1
                if att.status == Attendance.AttendanceStatus.LATE:
                    late_cnt += 1
                elif att.status == Attendance.AttendanceStatus.HALF_DAY:
                    half_cnt += 1
                elif att.status == Attendance.AttendanceStatus.ON_LEAVE:
                    leave_cnt += 1
                elif att.status == Attendance.AttendanceStatus.ABSENT:
                    absent_cnt += 1

                total_ot += att.overtime_hours or Decimal('0.00')
                row[col_name] = code
            else:
                # Auto-determine if non-working day or absent
                if not Holiday.is_working_day(company, cur_date):
                    if Holiday.objects.filter(company=company, date=cur_date, is_optional=False).exists():
                        row[col_name] = 'H'
                    else:
                        row[col_name] = 'WO'
                else:
                    row[col_name] = '-'

        row['Total Present'] = present_cnt
        row['Late Arrivals'] = late_cnt
        row['Half Days'] = half_cnt
        row['Approved Leaves'] = leave_cnt
        row['Absences'] = absent_cnt
        row['Total Overtime (Hrs)'] = float(total_ot)

        records.append(row)

    df = pd.DataFrame(records)
    filename = f"Attendance_Muster_{company.code}_{calendar.month_name[month]}_{year}"
    return export_dataframe_response(df, filename, format=format)


def generate_payroll_ledger(company, year, month, format='excel'):
    """
    Generates a full monthly compensation, tax, deduction, and disbursal register.
    """
    run = PayrollRun.objects.filter(company=company, year=year, month=month).first()
    if not run:
        # Return empty template
        df = pd.DataFrame(columns=[
            'Employee ID', 'Name', 'Department', 'Designation', 'Working Days',
            'Days Present', 'Paid Leaves', 'Unpaid LOP Days', 'Overtime Hours',
            'Basic Salary', 'HRA', 'Conveyance', 'Special Allowance', 'Overtime Pay',
            'Gross Earnings', 'LOP Deduction', 'PF', 'ESI', 'Professional Tax',
            'TDS', 'Total Deductions', 'Net Salary', 'Payment Status', 'Payment Reference'
        ])
        filename = f"Payroll_Ledger_{company.code}_{calendar.month_name[month]}_{year}_EMPTY"
        return export_dataframe_response(df, filename, format=format)

    payslips = run.payslips.select_related('employee', 'employee__department', 'employee__designation').order_by('employee__employee_id')

    records = []
    for p in payslips:
        records.append({
            'Employee ID': p.employee.employee_id,
            'Name': p.employee.get_full_name(),
            'Department': p.employee.department.name if p.employee.department else '',
            'Designation': p.employee.designation.title if p.employee.designation else '',
            'Working Days': float(p.working_days),
            'Days Present': float(p.days_present),
            'Paid Leaves': float(p.paid_leaves),
            'Unpaid LOP Days': float(p.unpaid_leaves),
            'Overtime Hours': float(p.overtime_hours),
            'Basic Salary': float(p.basic_salary),
            'HRA': float(p.hra),
            'Conveyance': float(p.conveyance),
            'Special Allowance': float(p.special_allowance),
            'Overtime Pay': float(p.overtime_pay),
            'Gross Earnings': float(p.gross_earnings),
            'LOP Deduction': float(p.loss_of_pay_deduction),
            'PF (12%)': float(p.provident_fund),
            'ESI': float(p.esi),
            'Professional Tax': float(p.professional_tax),
            'TDS': float(p.tds),
            'Total Deductions': float(p.total_deductions),
            'Net Salary': float(p.net_pay),
            'Net Pay in Words': p.net_pay_in_words,
            'Payment Status': p.get_payment_status_display(),
            'Payment Reference': p.payment_reference or 'N/A',
        })

    df = pd.DataFrame(records)
    filename = f"Payroll_Ledger_{company.code}_{calendar.month_name[month]}_{year}"
    return export_dataframe_response(df, filename, format=format)


def generate_leave_summary(company, year, format='excel'):
    """
    Generates annual leave entitlement, utilization, and available balance summary.
    """
    balances = LeaveBalance.objects.filter(
        leave_type__company=company,
        year=year
    ).select_related('employee', 'leave_type', 'employee__department').order_by('employee__employee_id', 'leave_type__name')

    records = []
    for b in balances:
        records.append({
            'Employee ID': b.employee.employee_id,
            'Name': b.employee.get_full_name(),
            'Department': b.employee.department.name if b.employee.department else '',
            'Leave Type': b.leave_type.name,
            'Leave Code': b.leave_type.code,
            'Is Paid': 'Yes' if b.leave_type.is_paid else 'No',
            'Year': b.year,
            'Base Quota': float(b.allocated_days),
            'Carried Forward': float(b.carried_forward_days),
            'Accrued Days': float(b.accrued_days),
            'Total Entitled': float(b.total_entitled),
            'Used Days': float(b.used_days),
            'Pending Requests': float(b.pending_days),
            'Available Balance': float(b.available_days),
        })

    df = pd.DataFrame(records)
    filename = f"Leave_Balances_Summary_{company.code}_{year}"
    return export_dataframe_response(df, filename, format=format)


def generate_employee_directory(company, format='excel'):
    """
    Exports full master employee roster for compliance and HR administration.
    """
    employees = Employee.objects.filter(company=company).select_related('department', 'designation', 'manager', 'assigned_shift').order_by('employee_id')

    records = []
    for emp in employees:
        records.append({
            'Employee ID': emp.employee_id,
            'First Name': emp.first_name,
            'Last Name': emp.last_name,
            'Email': emp.email,
            'Phone': emp.phone,
            'Department': emp.department.name if emp.department else '',
            'Designation': emp.designation.title if emp.designation else '',
            'Reporting Manager': emp.manager.get_full_name() if emp.manager else 'None',
            'Joining Date': emp.joining_date.strftime('%Y-%m-%d') if emp.joining_date else '',
            'Status': emp.get_employment_status_display(),
            'Salary Type': emp.get_salary_type_display(),
            'Monthly Salary': float(emp.monthly_salary),
            'Assigned Shift': emp.assigned_shift_name,
            'Face Biometric Registered': 'Yes' if emp.face_registration_status else 'No',
        })

    df = pd.DataFrame(records)
    filename = f"Employee_Directory_{company.code}"
    return export_dataframe_response(df, filename, format=format)
