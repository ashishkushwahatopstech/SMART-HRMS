from django.db import models
from django.core.exceptions import ValidationError


class Company(models.Model):
    """
    Multi-company management model.
    Encapsulates all corporate policies: working days, weekly holidays,
    leave accumulation, salary calculation method, and timezone.
    All downstream HRMS modules (employees, shifts, attendance, payroll)
    are strictly isolated per company.
    """
    class WeeklyHolidayPolicy(models.TextChoices):
        SUNDAY_ONLY = 'sunday_only', 'Sunday Only (6-Day Working Week)'
        SATURDAY_SUNDAY = 'saturday_sunday', 'Saturday & Sunday (5-Day Working Week)'
        ALTERNATE_SATURDAY = 'alternate_saturday', 'Sunday & Alternate (2nd & 4th) Saturday'

    class SalaryCalculationPolicy(models.TextChoices):
        ACTUAL_WORKING_DAYS = 'actual_working_days', 'Monthly Salary / Actual Working Days in Month'
        FIXED_26_DAYS = 'fixed_26_days', 'Fixed 26 Days (Calculated by Total Working Hours)'
        FIXED_30_DAYS = 'fixed_30_days', 'Fixed 30 Days (Attendance Marks + In-Between Sundays)'
        WORKING_HOURS = 'working_hours', 'Hourly Salary Calculation (Daily / Configured Hours)'

    # Core Identifiers
    name = models.CharField(max_length=200, unique=True, help_text="Full registered company name")
    code = models.CharField(max_length=20, unique=True, help_text="Short unique company code (e.g. TECHCORP, ACME)")
    address = models.TextField(blank=True, help_text="Physical registered office address")
    phone = models.CharField(max_length=25, blank=True, help_text="Corporate contact phone number")
    email = models.EmailField(blank=True, help_text="Official correspondence email")
    logo = models.ImageField(upload_to='company_logos/', blank=True, null=True, help_text="Company branding logo")

    # Working Hours & Days
    working_days_per_week = models.PositiveSmallIntegerField(default=5, help_text="Standard working days per week (5 or 6)")
    weekly_holiday_policy = models.CharField(
        max_length=30,
        choices=WeeklyHolidayPolicy.choices,
        default=WeeklyHolidayPolicy.SATURDAY_SUNDAY,
        help_text="Weekly off policy for working day computation"
    )
    default_working_hours = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=8.00,
        help_text="Default expected working hours per day"
    )

    # Leave & Accumulation Policy
    monthly_paid_leave_allowance = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=1.00,
        help_text="Paid leaves granted per month (e.g. 1.0 or 1.5)"
    )
    allow_leave_carry_forward = models.BooleanField(
        default=True,
        help_text="Whether unutilized leaves carry forward to next month/year"
    )
    max_carry_forward_days = models.PositiveSmallIntegerField(
        default=15,
        help_text="Maximum unused paid leaves that can be accumulated"
    )

    # Payroll Policy
    salary_calculation_policy = models.CharField(
        max_length=30,
        choices=SalaryCalculationPolicy.choices,
        default=SalaryCalculationPolicy.ACTUAL_WORKING_DAYS,
        help_text="Method used by payroll engine to calculate per-day rate"
    )

    # Localization & Status
    timezone = models.CharField(max_length=50, default='Asia/Kolkata', help_text="Timezone for attendance logs")
    is_active = models.BooleanField(default=True, help_text="Inactive companies cannot record attendance or payroll")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Company'
        verbose_name_plural = 'Companies'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"

    def clean(self):
        self.code = self.code.upper().strip()

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    @property
    def employee_count(self):
        return self.employees.count()

    @property
    def active_employee_count(self):
        return self.employees.filter(employment_status='active').count()

    @property
    def department_count(self):
        return self.departments.count()

    def can_be_deleted(self):
        """Safeguard: Company cannot be deleted if active employee records exist."""
        return self.employees.count() == 0
