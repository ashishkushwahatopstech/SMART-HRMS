from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone


class Department(models.Model):
    """
    Department division within a specific company.
    """
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='departments'
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Department'
        verbose_name_plural = 'Departments'
        ordering = ['company', 'name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_department_per_company')
        ]

    def __str__(self):
        return f"{self.name} ({self.company.code})"

    @property
    def employee_count(self):
        return self.employees.count()


class Designation(models.Model):
    """
    Job designation / role title within a department.
    """
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='designations'
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name='designations'
    )
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Designation'
        verbose_name_plural = 'Designations'
        ordering = ['company', 'title']
        constraints = [
            models.UniqueConstraint(fields=['company', 'department', 'title'], name='unique_designation_per_department')
        ]

    def __str__(self):
        return f"{self.title} - {self.department.name} ({self.company.code})"


class Employee(models.Model):
    """
    Core Employee profile containing employment contracts, corporate links,
    compensation types, reporting manager, and biometric face registration status.
    """
    class EmploymentStatus(models.TextChoices):
        ACTIVE = 'active', 'Active'
        PROBATION = 'probation', 'On Probation'
        ON_LEAVE = 'on_leave', 'On Extended Leave'
        SUSPENDED = 'suspended', 'Suspended'
        TERMINATED = 'terminated', 'Terminated'
        RESIGNED = 'resigned', 'Resigned'

    class SalaryType(models.TextChoices):
        MONTHLY = 'monthly', 'Monthly Fixed Salary'
        DAILY = 'daily', 'Daily Wage'
        HOURLY = 'hourly', 'Hourly Rate'

    # Optional Link to Login Account
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employee_profile',
        help_text="Associated login account (enables self-service portal)"
    )

    # Identifiers
    employee_id = models.CharField(
        max_length=30,
        unique=True,
        help_text="Unique Employee ID (e.g. TC-EMP0001)"
    )
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.PROTECT,
        related_name='employees',
        help_text="Company this employee is contracted with"
    )

    # Personal Information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True, help_text="Official employee email")
    phone = models.CharField(max_length=25, help_text="Contact telephone number")
    profile_picture = models.ImageField(
        upload_to='employees/photos/',
        blank=True,
        null=True,
        help_text="Employee identity photo"
    )
    address = models.TextField(blank=True, help_text="Residential street address")
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=25, blank=True)

    # Corporate Position
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employees'
    )
    designation = models.ForeignKey(
        Designation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employees'
    )
    manager = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subordinates',
        help_text="Reporting manager for approvals"
    )
    joining_date = models.DateField(default=timezone.now)
    exit_date = models.DateField(null=True, blank=True)
    employment_status = models.CharField(
        max_length=25,
        choices=EmploymentStatus.choices,
        default=EmploymentStatus.ACTIVE
    )

    # Compensation & Shift
    salary_type = models.CharField(
        max_length=20,
        choices=SalaryType.choices,
        default=SalaryType.MONTHLY
    )
    monthly_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Monthly gross salary in INR"
    )
    daily_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        blank=True,
        help_text="Calculated or manual daily wage"
    )
    hourly_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        blank=True,
        help_text="Calculated or manual hourly rate"
    )
    working_hours_per_day = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('8.00'),
        help_text="Expected daily hours"
    )
    assigned_shift = models.ForeignKey(
        'shifts.Shift',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employees',
        help_text="Assigned shift schedule"
    )
    assigned_shift_name = models.CharField(
        max_length=100,
        default='General Shift (09:00 - 17:00)',
        help_text="Assigned shift schedule label"
    )

    # Face Biometric Enrollment
    face_registration_status = models.BooleanField(
        default=False,
        help_text="True if biometric face samples have been captured"
    )
    face_samples_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of face training frames registered"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Employee'
        verbose_name_plural = 'Employees'
        ordering = ['company', 'employee_id']

    def __str__(self):
        return f"{self.get_full_name()} ({self.employee_id}) - {self.company.code}"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def calculate_daily_rate(self, working_days=26):
        """Calculates effective daily rate based on salary type and policy."""
        if self.salary_type == self.SalaryType.DAILY and self.daily_salary > 0:
            return self.daily_salary
        if self.monthly_salary > 0 and working_days > 0:
            return (self.monthly_salary / Decimal(str(working_days))).quantize(Decimal('0.01'))
        return Decimal('0.00')

    def calculate_hourly_rate(self, working_days=26):
        """Calculates effective hourly rate based on daily rate and daily working hours."""
        if self.salary_type == self.SalaryType.HOURLY and self.hourly_salary > 0:
            return self.hourly_salary
        daily_rate = self.calculate_daily_rate(working_days=working_days)
        if daily_rate > 0 and self.working_hours_per_day > 0:
            return (daily_rate / self.working_hours_per_day).quantize(Decimal('0.01'))
        return Decimal('0.00')

    def get_status_badge_class(self):
        mapping = {
            self.EmploymentStatus.ACTIVE: 'bg-success',
            self.EmploymentStatus.PROBATION: 'bg-warning text-dark',
            self.EmploymentStatus.ON_LEAVE: 'bg-info text-dark',
            self.EmploymentStatus.SUSPENDED: 'bg-danger',
            self.EmploymentStatus.TERMINATED: 'bg-dark',
            self.EmploymentStatus.RESIGNED: 'bg-secondary',
        }
        return mapping.get(self.employment_status, 'bg-secondary')

    def get_status_ring_class(self):
        mapping = {
            self.EmploymentStatus.ACTIVE: 'ring-active',
            self.EmploymentStatus.PROBATION: 'ring-probation',
            self.EmploymentStatus.ON_LEAVE: 'ring-on-leave',
            self.EmploymentStatus.SUSPENDED: 'ring-suspended',
            self.EmploymentStatus.TERMINATED: 'ring-terminated',
            self.EmploymentStatus.RESIGNED: 'ring-resigned',
        }
        return mapping.get(self.employment_status, 'ring-resigned')

    @classmethod
    def generate_next_employee_id(cls, company):
        """
        Generates an incremental Employee ID, e.g., MEGASCALE-EMP0002, TOPSTECH-EMP0001, etc.
        Scans all existing employee IDs in the company and calculates the next sequential number.
        """
        import re
        prefix = f"{company.code}-EMP"
        existing_ids = list(cls.objects.filter(company=company).values_list('employee_id', flat=True))
        max_num = 0
        for emp_id in existing_ids:
            if not emp_id:
                continue
            matches = re.findall(r'(\d+)', str(emp_id))
            if matches:
                try:
                    num = int(matches[-1])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass

        next_num = max_num + 1
        candidate = f"{prefix}{next_num:04d}"
        # Ensure candidate is globally unique
        while cls.objects.filter(employee_id=candidate).exists():
            next_num += 1
            candidate = f"{prefix}{next_num:04d}"
        return candidate

    def save(self, *args, **kwargs):
        # Auto-compute daily and hourly rates if left at zero and monthly salary is specified
        if self.salary_type == self.SalaryType.MONTHLY and self.monthly_salary > 0:
            if not self.daily_salary or self.daily_salary == Decimal('0.00'):
                self.daily_salary = self.calculate_daily_rate()
            if not self.hourly_salary or self.hourly_salary == Decimal('0.00'):
                self.hourly_salary = self.calculate_hourly_rate()
        super().save(*args, **kwargs)
