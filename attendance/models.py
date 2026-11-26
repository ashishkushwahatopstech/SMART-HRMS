import hashlib
import json
from decimal import Decimal
from datetime import datetime, date, time, timedelta
from django.db import models
from django.conf import settings
from django.utils import timezone


class Attendance(models.Model):
    """
    Daily Attendance Record for an Employee.
    Tracks check-in, check-out, automated working duration, punctuality (late/early departure),
    overtime calculation, and verification method.
    """
    class AttendanceStatus(models.TextChoices):
        PRESENT = 'present', 'Present'
        ABSENT = 'absent', 'Absent'
        HALF_DAY = 'half_day', 'Half Day'
        LATE = 'late', 'Late Arrival'
        ON_LEAVE = 'on_leave', 'On Leave'
        WEEKLY_OFF = 'weekly_off', 'Weekly Off'
        HOLIDAY = 'holiday', 'Holiday'

    class VerificationMethod(models.TextChoices):
        FACE_RECOGNITION = 'face_recognition', 'Face Biometrics'
        MANUAL_WEB = 'manual_web', 'Web Self Check-In'
        ADMIN_ADJUSTMENT = 'admin_adjustment', 'Admin Manual Adjustment'
        BIOMETRIC_DEVICE = 'biometric_device', 'Biometric Device'

    employee = models.ForeignKey(
        'employees.Employee',
        on_delete=models.CASCADE,
        related_name='attendances',
        help_text="Employee this attendance record belongs to"
    )
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='attendances',
        help_text="Company contracted with the employee"
    )
    date = models.DateField(
        default=timezone.now,
        help_text="Work calendar date (or shift-start calendar date for overnight shifts)"
    )
    shift = models.ForeignKey(
        'shifts.Shift',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attendances',
        help_text="Assigned shift schedule for this date"
    )

    # Time Punches
    check_in_time = models.DateTimeField(null=True, blank=True, help_text="Timestamp of employee check-in")
    check_out_time = models.DateTimeField(null=True, blank=True, help_text="Timestamp of employee check-out")

    # Lunch Break Punches
    lunch_start_time = models.DateTimeField(null=True, blank=True, help_text="Timestamp of employee departing for lunch (Lunch Out)")
    lunch_end_time = models.DateTimeField(null=True, blank=True, help_text="Timestamp of employee returning from lunch (Lunch In)")
    total_lunch_duration_minutes = models.PositiveSmallIntegerField(default=0, help_text="Actual lunch break taken in minutes")

    # Status & Method
    status = models.CharField(
        max_length=20,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.PRESENT
    )
    verification_method = models.CharField(
        max_length=25,
        choices=VerificationMethod.choices,
        default=VerificationMethod.MANUAL_WEB
    )

    # Hours & Punctuality
    total_working_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total calculated work duration in hours"
    )
    overtime_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Hours worked in excess of assigned shift"
    )

    is_late = models.BooleanField(default=False, help_text="True if checked in after grace period")
    late_minutes = models.PositiveSmallIntegerField(default=0, help_text="Minutes late past shift start")
    is_early_departure = models.BooleanField(default=False, help_text="True if checked out before shift end")
    early_departure_minutes = models.PositiveSmallIntegerField(default=0, help_text="Minutes left prior to shift end")

    # Audit & Tracking
    notes = models.TextField(blank=True, help_text="Remarks, adjustment reason, or location info")
    ip_address = models.GenericIPAddressField(null=True, blank=True, help_text="IP address used during check-in")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Attendance'
        verbose_name_plural = 'Attendance Records'
        ordering = ['-date', 'employee__first_name']
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'date'],
                name='unique_attendance_per_employee_per_day'
            )
        ]

    def __str__(self):
        return f"{self.employee.get_full_name()} &mdash; {self.date} ({self.get_status_display()})"

    def calculate_hours(self):
        """Calculates gross working hours, lunch break deduction, and overtime hours against assigned shift."""
        # Calculate actual recorded lunch duration if lunch punches exist
        lunch_deduction_seconds = 0.0
        if self.lunch_start_time and self.lunch_end_time and self.lunch_end_time > self.lunch_start_time:
            lunch_deduction_seconds = (self.lunch_end_time - self.lunch_start_time).total_seconds()
            self.total_lunch_duration_minutes = int(round(lunch_deduction_seconds / 60.0))
        elif self.total_lunch_duration_minutes > 0:
            lunch_deduction_seconds = float(self.total_lunch_duration_minutes * 60)

        if self.check_in_time and self.check_out_time:
            gross_seconds = max(0.0, (self.check_out_time - self.check_in_time).total_seconds())
            net_seconds = max(0.0, gross_seconds - lunch_deduction_seconds)
            hours = max(0.0, net_seconds / 3600.0)
            self.total_working_hours = Decimal(str(round(hours, 2)))

            expected = Decimal('8.00')
            if self.shift and self.shift.total_expected_hours:
                expected = self.shift.total_expected_hours

            if self.shift and self.shift.overtime_eligibility and self.total_working_hours > expected:
                self.overtime_hours = (self.total_working_hours - expected).quantize(Decimal('0.01'))
            else:
                self.overtime_hours = Decimal('0.00')
        else:
            self.total_working_hours = Decimal('0.00')
            self.overtime_hours = Decimal('0.00')

    def evaluate_punctuality(self):
        """Checks late arrival with grace period and early departure against shift timings."""
        if not self.shift:
            return

        # 1. Late arrival check
        if self.check_in_time:
            # Shift start on this attendance date
            start_dt, _ = self.shift.get_shift_window(self.date)
            # Make naive or tz-aware matching check_in_time
            if timezone.is_aware(self.check_in_time):
                start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())

            grace_window = start_dt + timedelta(minutes=self.shift.grace_period_minutes)
            if self.check_in_time > grace_window:
                self.is_late = True
                diff_minutes = (self.check_in_time - start_dt).total_seconds() / 60.0
                self.late_minutes = max(0, int(round(diff_minutes)))
            else:
                self.is_late = False
                self.late_minutes = 0

        # 2. Early departure check
        if self.check_out_time:
            _, end_dt = self.shift.get_shift_window(self.date)
            if timezone.is_aware(self.check_out_time):
                end_dt = timezone.make_aware(end_dt, timezone.get_current_timezone())

            if self.check_out_time < end_dt:
                self.is_early_departure = True
                diff_minutes = (end_dt - self.check_out_time).total_seconds() / 60.0
                self.early_departure_minutes = max(0, int(round(diff_minutes)))
            else:
                self.is_early_departure = False
                self.early_departure_minutes = 0

    def evaluate_status(self):
        """Auto-evaluates status if not manual leave/holiday."""
        manual_statuses = [
            self.AttendanceStatus.ON_LEAVE,
            self.AttendanceStatus.HOLIDAY,
            self.AttendanceStatus.WEEKLY_OFF
        ]
        if self.status in manual_statuses:
            return

        if self.check_in_time and self.check_out_time:
            expected = Decimal('8.00')
            if self.shift and self.shift.total_expected_hours:
                expected = self.shift.total_expected_hours

            half_day_threshold = expected / Decimal('2.0')
            if self.total_working_hours < half_day_threshold:
                self.status = self.AttendanceStatus.HALF_DAY
            elif self.is_late:
                self.status = self.AttendanceStatus.LATE
            else:
                self.status = self.AttendanceStatus.PRESENT
        elif self.check_in_time and not self.check_out_time:
            if self.is_late:
                self.status = self.AttendanceStatus.LATE
            else:
                self.status = self.AttendanceStatus.PRESENT

    def save(self, *args, **kwargs):
        # Auto-fill company from employee
        if not self.company_id and self.employee_id:
            self.company = self.employee.company

        # Auto-fill shift from employee assigned_shift if blank
        if not self.shift_id and self.employee_id and self.employee.assigned_shift:
            self.shift = self.employee.assigned_shift

        self.calculate_hours()
        self.evaluate_punctuality()
        self.evaluate_status()

        super().save(*args, **kwargs)

    def get_status_badge_class(self):
        mapping = {
            self.AttendanceStatus.PRESENT: 'bg-success',
            self.AttendanceStatus.LATE: 'bg-warning text-dark',
            self.AttendanceStatus.HALF_DAY: 'bg-info text-dark',
            self.AttendanceStatus.ABSENT: 'bg-danger',
            self.AttendanceStatus.ON_LEAVE: 'bg-secondary',
            self.AttendanceStatus.HOLIDAY: 'bg-primary',
            self.AttendanceStatus.WEEKLY_OFF: 'bg-light text-dark border',
        }
        return mapping.get(self.status, 'bg-secondary')

    def to_snapshot(self):
        """Converts attendance state into serializable dictionary snapshot for immutable audit trail."""
        return {
            'attendance_id': self.id,
            'employee_id': self.employee.employee_id,
            'employee_name': self.employee.get_full_name(),
            'department': self.employee.department.name if self.employee.department else 'Unassigned',
            'company_code': self.company.code,
            'date': self.date.isoformat() if self.date else None,
            'status': self.status,
            'status_label': self.get_status_display(),
            'shift': self.shift.name if self.shift else None,
            'check_in_time': self.check_in_time.strftime('%Y-%m-%d %H:%M:%S') if self.check_in_time else None,
            'lunch_start_time': self.lunch_start_time.strftime('%Y-%m-%d %H:%M:%S') if self.lunch_start_time else None,
            'lunch_end_time': self.lunch_end_time.strftime('%Y-%m-%d %H:%M:%S') if self.lunch_end_time else None,
            'total_lunch_duration_minutes': self.total_lunch_duration_minutes,
            'check_out_time': self.check_out_time.strftime('%Y-%m-%d %H:%M:%S') if self.check_out_time else None,
            'total_working_hours': str(self.total_working_hours),
            'overtime_hours': str(self.overtime_hours),
            'verification_method': self.get_verification_method_display(),
            'is_late': self.is_late,
            'late_minutes': self.late_minutes,
            'is_early_departure': self.is_early_departure,
            'early_departure_minutes': self.early_departure_minutes,
            'notes': self.notes,
            'ip_address': self.ip_address,
        }


class AttendanceAuditLog(models.Model):
    """
    Cryptographic immutable blockchain audit trail recording all attendance actions
    (Creations, Adjustments, Regularization Approvals, and Deletions).
    Publicly transparent and verifiable across the entire campus.
    """
    attendance = models.ForeignKey(
        Attendance,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='attendance_audit_logs',
        null=True,
        blank=True
    )
    employee_name = models.CharField(max_length=200, blank=True)
    employee_id_code = models.CharField(max_length=50, blank=True)
    attendance_date = models.DateField(null=True, blank=True)
    action = models.CharField(max_length=60, help_text="e.g. Attendance Created, Manual Edit, Attendance Record Deleted")
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    field_name = models.CharField(max_length=50, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    reason = models.TextField(help_text="Mandatory business reason for attendance action")
    snapshot = models.JSONField(default=dict, blank=True, help_text="Cryptographic snapshot of affected record state")
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    # Blockchain Cryptographic Ledger Verification
    block_index = models.PositiveIntegerField(default=1)
    previous_hash = models.CharField(max_length=64, blank=True, default='0'*64)
    block_hash = models.CharField(max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Attendance Audit Log'
        verbose_name_plural = 'Attendance Audit Logs'
        ordering = ['-block_index', '-created_at']

    def __str__(self):
        user_str = self.changed_by.username if self.changed_by else "System"
        emp_id = self.employee_id_code or (self.attendance.employee.employee_id if self.attendance else "N/A")
        return f"Block #{self.block_index} [{emp_id}] - {self.action} by {user_str} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"

    @property
    def snapshot_json(self):
        """Returns snapshot pretty-printed as valid JSON string."""
        import json
        if not self.snapshot:
            return "{}"
        if isinstance(self.snapshot, (dict, list)):
            try:
                return json.dumps(self.snapshot, indent=2, default=str)
            except Exception:
                return str(self.snapshot)
        return str(self.snapshot)

    def compute_hash(self):
        """
        Computes SHA-256 cryptographic hash chaining this log entry to the previous block.
        """
        payload = f"{self.block_index}|{self.previous_hash}|{self.company_id}|{self.employee_id_code}|{self.action}|{self.reason}|{self.new_value}|{self.created_at or timezone.now()}"
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        if self.attendance:
            if not self.company_id:
                self.company = self.attendance.company
            if not self.employee_name:
                self.employee_name = self.attendance.employee.get_full_name()
            if not self.employee_id_code:
                self.employee_id_code = self.attendance.employee.employee_id
            if not self.attendance_date:
                self.attendance_date = self.attendance.date
            if not self.snapshot:
                self.snapshot = self.attendance.to_snapshot()

        if not self.block_hash:
            # Blockchain chaining: find previous block for this company
            latest = AttendanceAuditLog.objects.filter(company=self.company).exclude(pk=self.pk).order_by('-block_index', '-id').first()
            if latest:
                self.block_index = latest.block_index + 1
                self.previous_hash = latest.block_hash or ('0' * 64)
            else:
                self.block_index = 1
                self.previous_hash = '0' * 64

            self.block_hash = self.compute_hash()

        super().save(*args, **kwargs)


class ManualPunchRequest(models.Model):
    """
    Attendance Regularization / Missed Punch Request.
    Submitted by an employee when they miss a punch on a previous day.
    Reviewed and approved/rejected by a Manager, HR Admin, or Super Admin.
    """
    class RequestStatus(models.TextChoices):
        PENDING = 'pending', 'Pending Approval'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    class PunchType(models.TextChoices):
        BOTH = 'both', 'Both Check-In & Check-Out'
        CHECK_IN = 'check_in', 'Check-In Only'
        CHECK_OUT = 'check_out', 'Check-Out Only'

    employee = models.ForeignKey(
        'employees.Employee',
        on_delete=models.CASCADE,
        related_name='manual_punch_requests',
        help_text="Employee requesting manual attendance punch"
    )
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        related_name='manual_punch_requests'
    )
    date = models.DateField(
        help_text="The date of the missed attendance punch"
    )
    punch_type = models.CharField(
        max_length=20,
        choices=PunchType.choices,
        default=PunchType.BOTH
    )
    check_in_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Claimed Check-In time"
    )
    check_out_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Claimed Check-Out time"
    )
    reason = models.TextField(
        help_text="Mandatory explanation for missing the camera punch on this day"
    )
    status = models.CharField(
        max_length=20,
        choices=RequestStatus.choices,
        default=RequestStatus.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_punch_requests'
    )
    review_remarks = models.TextField(
        blank=True,
        help_text="Feedback or reason for approval/rejection from Manager/HR"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Manual Punch Request'
        verbose_name_plural = 'Manual Punch Requests'
        ordering = ['-date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'date'],
                name='unique_punch_request_per_employee_per_day'
            )
        ]

    def __str__(self):
        return f"{self.employee.get_full_name()} - {self.date} ({self.get_status_display()})"

    def get_status_badge_class(self):
        mapping = {
            self.RequestStatus.PENDING: 'bg-warning text-dark',
            self.RequestStatus.APPROVED: 'bg-success',
            self.RequestStatus.REJECTED: 'bg-danger',
        }
        return mapping.get(self.status, 'bg-secondary')

