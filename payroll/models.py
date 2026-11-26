from decimal import Decimal
import calendar
from datetime import date
from django.db import models
from django.conf import settings
from django.utils import timezone
from companies.models import Company
from employees.models import Employee
from .engine import compute_monthly_payroll


class PayrollRun(models.Model):
    """
    Monthly batch payroll execution per company.
    Calculates and stores payslips for all eligible employees,
    enforces multi-company isolation, and supports locking for audit compliance.
    """
    class RunStatus(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PROCESSED = 'processed', 'Processed'
        DISBURSED = 'disbursed', 'Disbursed / Paid'
        LOCKED = 'locked', 'Locked & Finalized'

    MONTH_CHOICES = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]

    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='payroll_runs'
    )
    year = models.PositiveSmallIntegerField(default=timezone.now().year)
    month = models.PositiveSmallIntegerField(choices=MONTH_CHOICES, default=timezone.now().month)

    status = models.CharField(
        max_length=20,
        choices=RunStatus.choices,
        default=RunStatus.DRAFT
    )

    total_gross = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_deductions = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_net_pay = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_employees = models.PositiveIntegerField(default=0)

    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_payroll_runs'
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursal_reference = models.CharField(max_length=100, blank=True, help_text="Batch NEFT/UTR payment reference")
    payment_mode = models.CharField(max_length=30, blank=True, default='bank_transfer', help_text="Primary batch payment method")
    locked_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Payroll Run'
        verbose_name_plural = 'Payroll Runs'
        ordering = ['-year', '-month', 'company']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'year', 'month'],
                name='unique_payroll_run_per_company_month'
            )
        ]

    def __str__(self):
        return f"{self.company.code} - {self.get_month_display()} {self.year} ({self.get_status_display()})"

    @property
    def month_display_name(self):
        return f"{calendar.month_name[self.month]} {self.year}"

    def generate_payslips(self, user=None):
        """
        Executes payroll calculation for all active employees of this company.
        Generates or refreshes individual Payslip records and updates run totals.
        """
        if self.status == self.RunStatus.LOCKED:
            raise ValueError("Cannot regenerate payslips for a locked payroll run.")

        employees = Employee.objects.filter(
            company=self.company,
            employment_status=Employee.EmploymentStatus.ACTIVE
        )

        gross_acc = Decimal('0.00')
        deductions_acc = Decimal('0.00')
        net_acc = Decimal('0.00')
        count = 0

        for emp in employees:
            calc = compute_monthly_payroll(emp, self.year, self.month)

            payslip, _ = Payslip.objects.update_or_create(
                payroll_run=self,
                employee=emp,
                defaults={
                    'company': self.company,
                    'year': self.year,
                    'month': self.month,
                    'calendar_days': calc['calendar_days'],
                    'working_days': calc['working_days'],
                    'per_day_rate': calc['per_day_rate'],
                    'hourly_rate': calc['hourly_rate'],
                    'days_present': calc['days_present'],
                    'paid_leaves': calc['paid_leaves'],
                    'unpaid_leaves': calc['unpaid_leaves'],
                    'overtime_hours': calc['overtime_hours'],
                    # Shift & Hourly Compensation Metrics
                    'shift_name': calc.get('shift_name', emp.assigned_shift_name),
                    'shift_daily_hours': calc.get('shift_daily_hours', Decimal('8.00')),
                    'scheduled_shift_hours': calc.get('scheduled_shift_hours', Decimal('0.00')),
                    'actual_worked_hours': calc.get('actual_worked_hours', Decimal('0.00')),
                    'shortfall_hours': calc.get('shortfall_hours', Decimal('0.00')),
                    'shift_allowance': calc.get('shift_allowance', Decimal('0.00')),
                    # Snapshot Banking Details
                    'bank_name': emp.bank_name,
                    'bank_account_number': emp.bank_account_number,
                    'bank_ifsc': emp.bank_ifsc_code,
                    'pan_number': emp.pan_number,
                    # Earnings Breakdown
                    'basic_salary': calc['basic_salary'],
                    'hra': calc['hra'],
                    'conveyance': calc['conveyance'],
                    'medical_allowance': calc['medical_allowance'],
                    'special_allowance': calc['special_allowance'],
                    'overtime_pay': calc['overtime_pay'],
                    'bonus': calc['bonus'],
                    'gross_earnings': calc['gross_earnings'],
                    'loss_of_pay_deduction': calc['loss_of_pay_deduction'],
                    'provident_fund': calc['provident_fund'],
                    'esi': calc['esi'],
                    'professional_tax': calc['professional_tax'],
                    'tds': calc['tds'],
                    'other_deductions': calc['other_deductions'],
                    'total_deductions': calc['total_deductions'],
                    'net_pay': calc['net_pay'],
                    'net_pay_in_words': calc['net_pay_in_words'],
                }
            )

            gross_acc += calc['gross_earnings']
            deductions_acc += calc['total_deductions']
            net_acc += calc['net_pay']
            count += 1

        self.total_gross = gross_acc
        self.total_deductions = deductions_acc
        self.total_net_pay = net_acc
        self.total_employees = count
        self.status = self.RunStatus.PROCESSED
        self.processed_by = user
        self.processed_at = timezone.now()
        self.save()

    def disburse_all(self, payment_mode='bank_transfer', payment_date=None, payment_reference='', user=None):
        """
        Batch disburses all payslips in this payroll run with corporate reference ID,
        sets disbursal timestamp, and updates status to DISBURSED.
        """
        if self.status == self.RunStatus.LOCKED:
            raise ValueError("Cannot modify a locked payroll run.")
        p_date = payment_date or timezone.now().date()
        self.payslips.filter(payment_status=Payslip.PaymentStatus.PENDING).update(
            payment_status=Payslip.PaymentStatus.PAID,
            payment_date=p_date,
            payment_reference=payment_reference,
            payment_mode=payment_mode
        )
        self.status = self.RunStatus.DISBURSED
        self.disbursed_at = timezone.now()
        self.disbursal_reference = payment_reference
        self.payment_mode = payment_mode
        self.save()

    def lock(self, user=None):
        """
        Locks payroll run preventing further modifications for audit compliance.
        """
        self.status = self.RunStatus.LOCKED
        self.locked_at = timezone.now()
        self.save()


class Payslip(models.Model):
    """
    Individual Monthly Employee Payslip.
    Records comprehensive compensation breakdown, working days,
    LOP deductions, overtime hours and pay, statutory deductions,
    and net earnings in words.
    """
    class PaymentStatus(models.TextChoices):
        PENDING = 'pending', 'Pending Disbursal'
        PAID = 'paid', 'Disbursed / Paid'

    class PaymentMode(models.TextChoices):
        BANK_TRANSFER = 'bank_transfer', 'Bank Transfer (NEFT/RTGS)'
        UPI = 'upi', 'UPI / IMPS'
        CHEQUE = 'cheque', 'Cheque'
        CASH = 'cash', 'Cash'

    payroll_run = models.ForeignKey(
        PayrollRun,
        on_delete=models.CASCADE,
        related_name='payslips'
    )
    employee = models.ForeignKey(
        'employees.Employee',
        on_delete=models.CASCADE,
        related_name='payslips'
    )
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='payslips'
    )
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()

    # Days & Rates
    calendar_days = models.PositiveSmallIntegerField(default=30)
    working_days = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    per_day_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Shift & Working Hours Metrics (Corporate Shift-Hour Standard)
    shift_name = models.CharField(max_length=120, blank=True, default='Standard Shift')
    shift_daily_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('8.00'), help_text="Configured shift daily duration")
    scheduled_shift_hours = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal('0.00'), help_text="Total scheduled shift hours for the month")
    actual_worked_hours = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal('0.00'), help_text="Actual biometric verified working hours")
    shortfall_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'), help_text="Unworked shift shortfall deducted as LOP")
    shift_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Night/rotational shift allowance")

    # Attendance & Leave Metrics
    days_present = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    paid_leaves = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    unpaid_leaves = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))

    # Banking & Tax Details Snapshot
    bank_name = models.CharField(max_length=100, blank=True, default='')
    bank_account_number = models.CharField(max_length=50, blank=True, default='')
    bank_ifsc = models.CharField(max_length=25, blank=True, default='')
    pan_number = models.CharField(max_length=20, blank=True, default='')

    # Earnings
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    hra = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    conveyance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    medical_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    special_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    overtime_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    bonus = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    gross_earnings = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Deductions
    loss_of_pay_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    provident_fund = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    esi = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    professional_tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tds = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Net Pay
    net_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    net_pay_in_words = models.CharField(max_length=255, blank=True)

    # Disbursal Tracking
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING
    )
    payment_mode = models.CharField(
        max_length=25,
        choices=PaymentMode.choices,
        default=PaymentMode.BANK_TRANSFER
    )
    payment_date = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Payslip'
        verbose_name_plural = 'Payslips'
        ordering = ['-year', '-month', 'employee']
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'year', 'month'],
                name='unique_payslip_per_employee_month'
            )
        ]

    def __str__(self):
        return f"{self.employee.employee_id} - {calendar.month_name[self.month]} {self.year}: Net ₹{self.net_pay}"

    @property
    def month_name(self):
        return f"{calendar.month_name[self.month]} {self.year}"
