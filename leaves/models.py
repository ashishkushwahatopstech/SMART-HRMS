from decimal import Decimal
from datetime import date, timedelta
from django.db import models
from django.conf import settings
from django.utils import timezone
from companies.models import Company
from holidays.models import Holiday


class LeaveType(models.Model):
    """
    Configurable Leave Category per Company.
    Defines annual entitlement quota, paid/unpaid classification,
    carry-forward caps, and documentation rules.
    """
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='leave_types',
        help_text="Company this leave type belongs to"
    )
    name = models.CharField(max_length=100, help_text="e.g. Paid Leave, Sick Leave, Casual Leave")
    code = models.CharField(max_length=20, help_text="e.g. PL, SL, CL, ML, LWP")
    annual_quota = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('12.00'),
        help_text="Annual baseline entitlement in days"
    )
    is_paid = models.BooleanField(
        default=True,
        help_text="If True, regular salary is paid during this leave. If False, treated as LWP."
    )
    allow_half_day = models.BooleanField(
        default=True,
        help_text="Whether employees can take half-day requests of this leave type"
    )
    requires_attachment = models.BooleanField(
        default=False,
        help_text="Whether supporting documentation (e.g. medical certificate) is mandatory"
    )
    is_carry_forward = models.BooleanField(
        default=False,
        help_text="Whether unused balance can roll over into next calendar year"
    )
    max_carry_forward_days = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Maximum days permitted to roll over"
    )
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Leave Type'
        verbose_name_plural = 'Leave Types'
        ordering = ['company', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'code'],
                name='unique_leave_type_code_per_company'
            )
        ]

    def __str__(self):
        paid_label = "Paid" if self.is_paid else "Unpaid"
        return f"{self.name} ({self.code}) &mdash; {paid_label} [{self.company.code}]"


def get_current_year():
    return timezone.now().year


class LeaveBalance(models.Model):
    """
    Yearly balance ledger tracking an individual employee's entitlements,
    carry-forward, monthly accruals, pending requests, and used days.
    """
    employee = models.ForeignKey(
        'employees.Employee',
        on_delete=models.CASCADE,
        related_name='leave_balances'
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name='balances'
    )
    year = models.PositiveSmallIntegerField(default=get_current_year)

    allocated_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="Base annual quota assigned"
    )
    carried_forward_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="Days rolled over from previous year"
    )
    accrued_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="Accrued dynamically during current year"
    )
    used_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="Days approved and utilized"
    )
    pending_days = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="Days currently locked in pending applications"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Leave Balance'
        verbose_name_plural = 'Leave Balances'
        ordering = ['-year', 'employee', 'leave_type']
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'leave_type', 'year'],
                name='unique_leave_balance_per_employee_type_year'
            )
        ]

    def __str__(self):
        return f"{self.employee.get_full_name()} &bull; {self.leave_type.code} ({self.year}): {self.available_days} Available"

    @property
    def total_entitled(self):
        return (self.allocated_days + self.carried_forward_days + self.accrued_days).quantize(Decimal('0.01'))

    @property
    def available_days(self):
        total = self.total_entitled
        committed = self.used_days + self.pending_days
        avail = total - committed
        return max(Decimal('0.00'), avail.quantize(Decimal('0.01')))


class LeaveApplication(models.Model):
    """
    Formal Employee Leave Application.
    Calculates net working days by automatically excluding weekly offs & holidays,
    supports half-day requests, and provides approval workflows.
    """
    class ApplicationStatus(models.TextChoices):
        PENDING = 'pending', 'Pending Approval'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        CANCELLED = 'cancelled', 'Cancelled'

    class HalfDaySession(models.TextChoices):
        FIRST_HALF = 'first_half', 'First Half (Morning)'
        SECOND_HALF = 'second_half', 'Second Half (Afternoon)'

    employee = models.ForeignKey(
        'employees.Employee',
        on_delete=models.CASCADE,
        related_name='leave_applications'
    )
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='leave_applications'
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name='applications'
    )

    start_date = models.DateField(help_text="First date of requested leave")
    end_date = models.DateField(help_text="Last date of requested leave")

    is_half_day = models.BooleanField(
        default=False,
        help_text="Whether this is a 0.5 day leave request"
    )
    half_day_session = models.CharField(
        max_length=20,
        choices=HalfDaySession.choices,
        blank=True,
        help_text="Applicable if half-day is checked"
    )

    total_days = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Net business working days requested"
    )
    reason = models.TextField(help_text="Purpose or justification for leave")
    attachment = models.FileField(
        upload_to='leaves/attachments/',
        blank=True,
        null=True,
        help_text="Supporting document (e.g. medical slip, travel document)"
    )

    status = models.CharField(
        max_length=20,
        choices=ApplicationStatus.choices,
        default=ApplicationStatus.PENDING
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_leave_applications'
    )
    decision_date = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Leave Application'
        verbose_name_plural = 'Leave Applications'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee.get_full_name()} &bull; {self.leave_type.code} [{self.start_date} to {self.end_date}] ({self.get_status_display()})"

    def calculate_net_days(self):
        """
        Calculates net working days between start_date and end_date,
        automatically excluding scheduled weekly offs and mandatory public holidays.
        """
        if self.is_half_day:
            return Decimal('0.50')

        if self.start_date > self.end_date:
            return Decimal('0.00')

        company = self.company or self.employee.company
        cur = self.start_date
        net_days = 0

        while cur <= self.end_date:
            # Check if working day (excludes weekends and mandatory holidays)
            if Holiday.is_working_day(company, cur):
                net_days += 1
            cur += timedelta(days=1)

        return Decimal(str(net_days))

    def save(self, *args, **kwargs):
        if not self.company_id and self.employee_id:
            self.company = self.employee.company

        # If total_days not pre-calculated or needs sync:
        calculated = self.calculate_net_days()
        if not self.total_days or self.total_days <= Decimal('0.00'):
            self.total_days = calculated

        super().save(*args, **kwargs)

    def approve(self, user):
        """
        Approves leave application:
        1. Changes status to APPROVED.
        2. Transfers days from pending_days to used_days on employee's LeaveBalance.
        3. Automatically synchronizes attendance records as 'ON_LEAVE'.
        4. Logs approval in LeaveApprovalLog.
        """
        from attendance.models import Attendance

        self.status = self.ApplicationStatus.APPROVED
        self.approved_by = user
        self.decision_date = timezone.now()
        self.save()

        # Update balance
        bal = LeaveBalance.objects.filter(
            employee=self.employee,
            leave_type=self.leave_type,
            year=self.start_date.year
        ).first()

        if bal:
            # Reduce pending, increase used
            bal.pending_days = max(Decimal('0.00'), bal.pending_days - self.total_days)
            bal.used_days += self.total_days
            bal.save()

        # Mark attendance records for working days during this leave
        cur = self.start_date
        while cur <= self.end_date:
            if Holiday.is_working_day(self.company, cur):
                status_to_set = Attendance.AttendanceStatus.HALF_DAY if self.is_half_day else Attendance.AttendanceStatus.ON_LEAVE
                att, created = Attendance.objects.get_or_create(
                    employee=self.employee,
                    date=cur,
                    defaults={
                        'company': self.company,
                        'shift': self.employee.assigned_shift,
                        'status': status_to_set,
                        'notes': f"Approved {self.leave_type.name} ({self.reason})",
                    }
                )
                if not created:
                    att.status = status_to_set
                    att.notes = f"Approved {self.leave_type.name} ({self.reason})"
                    att.save()
            cur += timedelta(days=1)

        LeaveApprovalLog.objects.create(
            application=self,
            action='Approved',
            acted_by=user,
            remarks='Leave request approved'
        )

    def reject(self, user, reason):
        """
        Rejects leave application:
        1. Changes status to REJECTED with rejection_reason.
        2. Restores pending_days on employee's LeaveBalance.
        3. Logs rejection in LeaveApprovalLog.
        """
        self.status = self.ApplicationStatus.REJECTED
        self.approved_by = user
        self.decision_date = timezone.now()
        self.rejection_reason = reason
        self.save()

        bal = LeaveBalance.objects.filter(
            employee=self.employee,
            leave_type=self.leave_type,
            year=self.start_date.year
        ).first()

        if bal:
            bal.pending_days = max(Decimal('0.00'), bal.pending_days - self.total_days)
            bal.save()

        LeaveApprovalLog.objects.create(
            application=self,
            action='Rejected',
            acted_by=user,
            remarks=reason
        )

    def cancel(self, user=None):
        """
        Cancels leave application if pending, freeing locked pending_days.
        """
        if self.status == self.ApplicationStatus.PENDING:
            self.status = self.ApplicationStatus.CANCELLED
            self.save()

            bal = LeaveBalance.objects.filter(
                employee=self.employee,
                leave_type=self.leave_type,
                year=self.start_date.year
            ).first()

            if bal:
                bal.pending_days = max(Decimal('0.00'), bal.pending_days - self.total_days)
                bal.save()

            LeaveApprovalLog.objects.create(
                application=self,
                action='Cancelled',
                acted_by=user,
                remarks='Cancelled by applicant'
            )

    def get_status_badge_class(self):
        mapping = {
            self.ApplicationStatus.APPROVED: 'bg-success',
            self.ApplicationStatus.PENDING: 'bg-warning text-dark',
            self.ApplicationStatus.REJECTED: 'bg-danger',
            self.ApplicationStatus.CANCELLED: 'bg-secondary',
        }
        return mapping.get(self.status, 'bg-secondary')


class LeaveApprovalLog(models.Model):
    """
    Audit log tracking workflow status changes, manager approvals, and reasons.
    """
    application = models.ForeignKey(
        LeaveApplication,
        on_delete=models.CASCADE,
        related_name='approval_logs'
    )
    action = models.CharField(max_length=50)
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Leave Approval Log'
        verbose_name_plural = 'Leave Approval Logs'
        ordering = ['-created_at']

    def __str__(self):
        user_name = self.acted_by.get_display_name() if self.acted_by else "System"
        return f"{self.application.employee.employee_id} - {self.action} by {user_name} on {self.created_at.strftime('%Y-%m-%d %H:%M')}"
