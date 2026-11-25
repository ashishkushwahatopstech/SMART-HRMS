from datetime import date
from django.db import models
from django.utils import timezone
from companies.models import Company


class Holiday(models.Model):
    """
    Corporate Holiday Model.
    Supports Gazetted/Mandatory holidays, Optional/Restricted holidays,
    and Company-specific events.
    Enforces per-company multi-tenancy and unique dates.
    """
    class HolidayType(models.TextChoices):
        MANDATORY = 'mandatory', 'Mandatory / Gazetted Holiday'
        OPTIONAL = 'optional', 'Optional / Restricted Holiday'
        COMPANY_EVENT = 'company_event', 'Company Observance'

    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='holidays',
        help_text="Company this holiday calendar applies to"
    )
    name = models.CharField(max_length=150, help_text="e.g. Republic Day, Diwali, Christmas")
    date = models.DateField(help_text="Calendar date of observance")
    holiday_type = models.CharField(
        max_length=25,
        choices=HolidayType.choices,
        default=HolidayType.MANDATORY
    )
    is_optional = models.BooleanField(
        default=False,
        help_text="Check if employees can optionally choose to take this holiday"
    )
    description = models.TextField(blank=True, help_text="Brief historical or corporate context")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Holiday'
        verbose_name_plural = 'Holidays'
        ordering = ['company', 'date']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'date'],
                name='unique_holiday_per_company_per_date'
            )
        ]

    def __str__(self):
        return f"{self.name} &mdash; {self.date.strftime('%d %b %Y')} ({self.company.code})"

    def clean(self):
        # Keep is_optional synchronized with holiday_type
        if self.holiday_type == self.HolidayType.OPTIONAL:
            self.is_optional = True

    def save(self, *args, **kwargs):
        if self.holiday_type == self.HolidayType.OPTIONAL:
            self.is_optional = True
        super().save(*args, **kwargs)

    @property
    def is_past(self):
        return self.date < timezone.now().date()

    @property
    def day_of_week(self):
        return self.date.strftime('%A')

    def get_badge_class(self):
        mapping = {
            self.HolidayType.MANDATORY: 'bg-danger',
            self.HolidayType.OPTIONAL: 'bg-info text-dark',
            self.HolidayType.COMPANY_EVENT: 'bg-primary',
        }
        return mapping.get(self.holiday_type, 'bg-secondary')

    @classmethod
    def is_working_day(cls, company, target_date):
        """
        Calculates whether target_date is a regular working day for the given company,
        taking into account company weekly holiday policy and mandatory holidays.
        """
        weekday = target_date.weekday()  # Monday=0 ... Sunday=6
        # 1. Weekly holiday policy check
        if company.weekly_holiday_policy == Company.WeeklyHolidayPolicy.SATURDAY_SUNDAY:
            if weekday in [5, 6]:
                return False  # Weekend
        elif company.weekly_holiday_policy == Company.WeeklyHolidayPolicy.SUNDAY_ONLY:
            if weekday == 6:
                return False  # Sunday off

        # 2. Mandatory public holiday check
        if cls.objects.filter(company=company, date=target_date, is_optional=False).exists():
            return False

        return True

    @classmethod
    def get_working_days_in_month(cls, company, year, month):
        """
        Returns count of actual working days for a company in a specified calendar month.
        Essential for payroll actual working day rate computation.
        """
        import calendar
        _, num_days = calendar.monthrange(year, month)
        working_days = 0
        for day in range(1, num_days + 1):
            d = date(year, month, day)
            if cls.is_working_day(company, d):
                working_days += 1
        return working_days
