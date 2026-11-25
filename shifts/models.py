from decimal import Decimal
from datetime import datetime, date, time, timedelta
from django.db import models
from django.conf import settings
from django.utils import timezone


class Shift(models.Model):
    """
    Configurable Work Shift model.
    Supports 8-hour, 12-hour, 24-hour, and custom shifts.
    Properly models overnight cross-midnight shifts and grace periods.
    """
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='shifts',
        help_text="Company this shift belongs to"
    )
    name = models.CharField(max_length=100, help_text="e.g. General Shift, Night Shift, 12-Hour Shift")
    shift_code = models.CharField(max_length=30, blank=True, help_text="e.g. GEN-0917, NGT-2206")

    # Time Schedule
    start_time = models.TimeField(help_text="Shift start time (e.g. 09:00:00)")
    end_time = models.TimeField(help_text="Shift end time (e.g. 17:00:00)")

    # Breaks & Lunch
    lunch_duration_minutes = models.PositiveSmallIntegerField(
        default=60,
        help_text="Allocated lunch break in minutes (e.g. 60 or 45)"
    )
    break_duration_minutes = models.PositiveSmallIntegerField(
        default=15,
        help_text="Allocated tea/personal break in minutes"
    )

    # Working Hours & Overtime
    total_expected_hours = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
        help_text="Gross expected working duration in hours (e.g. 8.00, 12.00, 24.00)"
    )
    grace_period_minutes = models.PositiveSmallIntegerField(
        default=15,
        help_text="Grace window in minutes before check-in is flagged as Late Arrival"
    )
    overtime_eligibility = models.BooleanField(
        default=True,
        help_text="Whether hours worked beyond shift end time qualify for overtime"
    )

    # Overnight / Cross-Midnight Flag
    is_overnight = models.BooleanField(
        default=False,
        help_text="Check if this shift spans across midnight into the next calendar day"
    )

    is_active = models.BooleanField(default=True, help_text="Active shifts can be assigned to staff")
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Shift'
        verbose_name_plural = 'Shifts'
        ordering = ['company', 'start_time']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_shift_name_per_company')
        ]

    def __str__(self):
        overnight_tag = " (Overnight)" if self.is_overnight else ""
        return f"{self.name} [{self.start_time.strftime('%I:%M %p')} - {self.end_time.strftime('%I:%M %p')}]{overnight_tag} ({self.company.code})"

    def clean(self):
        # Auto-detect overnight if end_time <= start_time
        if self.end_time <= self.start_time:
            self.is_overnight = True

    def save(self, *args, **kwargs):
        if self.end_time <= self.start_time:
            self.is_overnight = True
        # Recalculate expected hours if not manually modified
        calculated = self.calculate_gross_hours()
        if not self.total_expected_hours or self.total_expected_hours == Decimal('0.00'):
            self.total_expected_hours = calculated
        super().save(*args, **kwargs)

    def calculate_gross_hours(self):
        """Calculates total gross shift duration in decimal hours."""
        dummy_date = date(2026, 1, 1)
        start_dt = datetime.combine(dummy_date, self.start_time)
        if self.is_overnight or self.end_time <= self.start_time:
            end_dt = datetime.combine(dummy_date + timedelta(days=1), self.end_time)
        else:
            end_dt = datetime.combine(dummy_date, self.end_time)

        duration_seconds = (end_dt - start_dt).total_seconds()
        hours = duration_seconds / 3600.0
        # If start == end and overnight, it represents a 24-hour shift
        if hours == 0 and self.is_overnight:
            hours = 24.0
        return Decimal(str(round(hours, 2)))

    def calculate_net_working_hours(self):
        """Gross expected hours minus unpaid lunch and break duration."""
        unpaid_minutes = self.lunch_duration_minutes + self.break_duration_minutes
        unpaid_hours = Decimal(str(unpaid_minutes)) / Decimal('60.0')
        net = self.total_expected_hours - unpaid_hours
        return max(Decimal('0.00'), net.quantize(Decimal('0.01')))

    def get_shift_window(self, shift_date):
        """
        Returns (start_datetime, end_datetime) for a shift on a given calendar date.
        Crucial for night shifts: prevents attendance logs from splitting across dates.
        """
        start_dt = datetime.combine(shift_date, self.start_time)
        if self.is_overnight:
            end_dt = datetime.combine(shift_date + timedelta(days=1), self.end_time)
        else:
            end_dt = datetime.combine(shift_date, self.end_time)
        return start_dt, end_dt

    def is_check_in_late(self, check_in_time):
        """
        Determines if check_in_time exceeds shift start time plus grace period.
        Supports both datetime.time and timezone-aware datetime.datetime objects.
        """
        if hasattr(check_in_time, 'tzinfo') and timezone.is_aware(check_in_time):
            check_in_time = timezone.localtime(check_in_time).time()
        elif hasattr(check_in_time, 'time') and callable(check_in_time.time):
            check_in_time = check_in_time.time()
        start_min = self.start_time.hour * 60 + self.start_time.minute
        check_min = check_in_time.hour * 60 + check_in_time.minute
        allowed_min = start_min + self.grace_period_minutes
        return check_min > allowed_min

    @property
    def assigned_employee_count(self):
        return self.employees.count()

    def can_be_deleted(self):
        return self.employees.count() == 0


class ShiftAssignment(models.Model):
    """
    Historical and active schedule link between Employee and Shift.
    Supports shift rotations and historical shift change tracking.
    """
    employee = models.ForeignKey(
        'employees.Employee',
        on_delete=models.CASCADE,
        related_name='shift_schedule_history'
    )
    shift = models.ForeignKey(
        Shift,
        on_delete=models.CASCADE,
        related_name='assignments'
    )
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    remarks = models.CharField(max_length=255, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Shift Assignment'
        verbose_name_plural = 'Shift Assignments'
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.employee.get_full_name()} &rarr; {self.shift.name} ({self.start_date})"
