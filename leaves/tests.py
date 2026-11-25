from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.db import IntegrityError, transaction
from accounts.models import User
from companies.models import Company
from employees.models import Department, Designation, Employee
from holidays.models import Holiday
from attendance.models import Attendance
from leaves.models import LeaveType, LeaveBalance, LeaveApplication, LeaveApprovalLog
from leaves.forms import LeaveApplicationForm


class LeaveManagementTests(TestCase):
    def setUp(self):
        # 1. Companies
        self.company_a = Company.objects.create(
            name="Alpha Corp",
            code="ALPHA",
            weekly_holiday_policy=Company.WeeklyHolidayPolicy.SATURDAY_SUNDAY,
            working_days_per_week=5
        )
        self.company_b = Company.objects.create(
            name="Beta Corp",
            code="BETA",
            weekly_holiday_policy=Company.WeeklyHolidayPolicy.SATURDAY_SUNDAY,
            working_days_per_week=5
        )

        # 2. Users
        self.superadmin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='password123', role=User.Role.SUPER_ADMIN
        )
        self.hr_user_a = User.objects.create_user(
            username='hr_alpha', email='hr@alpha.com', password='password123', role=User.Role.HR_ADMIN
        )
        self.mgr_user_a = User.objects.create_user(
            username='mgr_alpha', email='mgr@alpha.com', password='password123', role=User.Role.MANAGER
        )
        self.emp_user_a = User.objects.create_user(
            username='emp_alpha', email='emp@alpha.com', password='password123', role=User.Role.EMPLOYEE
        )

        # Company B user
        self.emp_user_b = User.objects.create_user(
            username='emp_beta', email='emp@beta.com', password='password123', role=User.Role.EMPLOYEE
        )

        # 3. Dept & Desig
        self.dept_a = Department.objects.create(company=self.company_a, name="Eng Alpha")
        self.desig_a = Designation.objects.create(company=self.company_a, department=self.dept_a, title="Dev Alpha")

        self.dept_b = Department.objects.create(company=self.company_b, name="Eng Beta")
        self.desig_b = Designation.objects.create(company=self.company_b, department=self.dept_b, title="Dev Beta")

        # 4. Employees
        self.emp_mgr = Employee.objects.create(
            user=self.mgr_user_a,
            employee_id="A-MGR01",
            company=self.company_a,
            first_name="Manager",
            last_name="Alpha",
            email="mgr@alpha.com",
            phone="1111111111",
            department=self.dept_a,
            designation=self.desig_a
        )
        self.emp_a = Employee.objects.create(
            user=self.emp_user_a,
            employee_id="A-EMP01",
            company=self.company_a,
            first_name="John",
            last_name="Alpha",
            email="emp@alpha.com",
            phone="2222222222",
            department=self.dept_a,
            designation=self.desig_a,
            manager=self.emp_mgr
        )
        self.emp_hr = Employee.objects.create(
            user=self.hr_user_a,
            employee_id="A-HR01",
            company=self.company_a,
            first_name="HR",
            last_name="Alpha",
            email="hr@alpha.com",
            phone="3333333333",
            department=self.dept_a,
            designation=self.desig_a
        )
        self.emp_b = Employee.objects.create(
            user=self.emp_user_b,
            employee_id="B-EMP01",
            company=self.company_b,
            first_name="Jane",
            last_name="Beta",
            email="emp@beta.com",
            phone="4444444444",
            department=self.dept_b,
            designation=self.desig_b
        )

        # 5. Leave Types
        self.pl_type = LeaveType.objects.create(
            company=self.company_a,
            name="Paid Leave",
            code="PL",
            annual_quota=Decimal('12.00'),
            is_paid=True,
            allow_half_day=True,
            is_carry_forward=True,
            max_carry_forward_days=Decimal('6.00')
        )
        self.sl_type = LeaveType.objects.create(
            company=self.company_a,
            name="Sick Leave",
            code="SL",
            annual_quota=Decimal('6.00'),
            is_paid=True,
            allow_half_day=True,
            requires_attachment=True
        )

        # 6. Holiday on a Monday (e.g., 2026-01-26 Republic Day)
        Holiday.objects.create(
            company=self.company_a,
            name="Republic Day",
            date=date(2026, 1, 26),
            holiday_type=Holiday.HolidayType.MANDATORY,
            is_optional=False
        )

        # 7. Leave Balance for emp_a
        self.bal_pl = LeaveBalance.objects.create(
            employee=self.emp_a,
            leave_type=self.pl_type,
            year=2026,
            allocated_days=Decimal('12.00'),
            carried_forward_days=Decimal('2.00')
        )

        self.client = Client()

    def test_leave_type_unique_code_per_company(self):
        """Verifies duplicate leave type code in same company raises IntegrityError."""
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                LeaveType.objects.create(
                    company=self.company_a,
                    name="Duplicate PL",
                    code="PL"
                )

    def test_leave_balance_available_days_computation(self):
        """Verifies total_entitled and available_days calculations."""
        # Total entitled = 12 allocated + 2 carried = 14
        self.assertEqual(self.bal_pl.total_entitled, Decimal('14.00'))
        self.assertEqual(self.bal_pl.available_days, Decimal('14.00'))

        # Add 3 used and 2 pending
        self.bal_pl.used_days = Decimal('3.00')
        self.bal_pl.pending_days = Decimal('2.00')
        self.bal_pl.save()

        # Available = 14 - (3 + 2) = 9
        self.assertEqual(self.bal_pl.available_days, Decimal('9.00'))

    def test_working_days_calculation_excludes_weekends_and_holidays(self):
        """
        Friday 2026-01-23 to Tuesday 2026-01-27:
        - 2026-01-23 (Fri): Working day (1)
        - 2026-01-24 (Sat): Weekend off (0)
        - 2026-01-25 (Sun): Weekend off (0)
        - 2026-01-26 (Mon): Mandatory Holiday Republic Day (0)
        - 2026-01-27 (Tue): Working day (1)
        Total net working days must equal exactly 2.00!
        """
        app = LeaveApplication(
            employee=self.emp_a,
            company=self.company_a,
            leave_type=self.pl_type,
            start_date=date(2026, 1, 23),
            end_date=date(2026, 1, 27),
            is_half_day=False,
            reason="Extended holiday trip"
        )
        net_days = app.calculate_net_days()
        self.assertEqual(net_days, Decimal('2.00'))

    def test_half_day_application_duration(self):
        """Half day leave must return exactly 0.50 days."""
        app = LeaveApplication(
            employee=self.emp_a,
            company=self.company_a,
            leave_type=self.pl_type,
            start_date=date(2026, 1, 23),
            end_date=date(2026, 1, 23),
            is_half_day=True,
            half_day_session=LeaveApplication.HalfDaySession.FIRST_HALF,
            reason="Personal work morning"
        )
        self.assertEqual(app.calculate_net_days(), Decimal('0.50'))

    def test_application_approval_workflow_and_attendance_sync(self):
        """
        Approving a leave application:
        - Marks status as APPROVED.
        - Moves pending_days to used_days on LeaveBalance.
        - Synchronizes Attendance record as 'on_leave'.
        - Creates LeaveApprovalLog.
        """
        # Apply for 2 days (2026-01-21 to 2026-01-22: Wed, Thu)
        app = LeaveApplication.objects.create(
            employee=self.emp_a,
            company=self.company_a,
            leave_type=self.pl_type,
            start_date=date(2026, 1, 21),
            end_date=date(2026, 1, 22),
            is_half_day=False,
            reason="Family function",
            status=LeaveApplication.ApplicationStatus.PENDING
        )
        self.bal_pl.pending_days = Decimal('2.00')
        self.bal_pl.save()

        # Approve by Manager
        app.approve(self.mgr_user_a)

        self.assertEqual(app.status, LeaveApplication.ApplicationStatus.APPROVED)
        self.bal_pl.refresh_from_db()
        self.assertEqual(self.bal_pl.pending_days, Decimal('0.00'))
        self.assertEqual(self.bal_pl.used_days, Decimal('2.00'))

        # Verify Attendance records generated as on_leave
        att_wed = Attendance.objects.get(employee=self.emp_a, date=date(2026, 1, 21))
        att_thu = Attendance.objects.get(employee=self.emp_a, date=date(2026, 1, 22))
        self.assertEqual(att_wed.status, Attendance.AttendanceStatus.ON_LEAVE)
        self.assertEqual(att_thu.status, Attendance.AttendanceStatus.ON_LEAVE)

        # Verify Audit Log
        self.assertTrue(app.approval_logs.filter(action='Approved').exists())

    def test_application_rejection_restores_pending_balance(self):
        """Rejection frees pending days back into available balance."""
        app = LeaveApplication.objects.create(
            employee=self.emp_a,
            company=self.company_a,
            leave_type=self.pl_type,
            start_date=date(2026, 1, 21),
            end_date=date(2026, 1, 22),
            is_half_day=False,
            reason="Family function",
            status=LeaveApplication.ApplicationStatus.PENDING
        )
        self.bal_pl.pending_days = Decimal('2.00')
        self.bal_pl.save()

        app.reject(self.mgr_user_a, "Critical project release underway")
        self.assertEqual(app.status, LeaveApplication.ApplicationStatus.REJECTED)
        self.bal_pl.refresh_from_db()
        self.assertEqual(self.bal_pl.pending_days, Decimal('0.00'))
        self.assertEqual(self.bal_pl.available_days, Decimal('14.00'))
        self.assertTrue(app.approval_logs.filter(action='Rejected').exists())

    def test_application_cancellation_by_employee(self):
        """Employee can cancel pending application, restoring balance."""
        app = LeaveApplication.objects.create(
            employee=self.emp_a,
            company=self.company_a,
            leave_type=self.pl_type,
            start_date=date(2026, 1, 21),
            end_date=date(2026, 1, 22),
            is_half_day=False,
            reason="Family function",
            status=LeaveApplication.ApplicationStatus.PENDING
        )
        self.bal_pl.pending_days = Decimal('2.00')
        self.bal_pl.save()

        app.cancel(self.emp_user_a)
        self.assertEqual(app.status, LeaveApplication.ApplicationStatus.CANCELLED)
        self.bal_pl.refresh_from_db()
        self.assertEqual(self.bal_pl.pending_days, Decimal('0.00'))

    def test_leave_form_insufficient_balance_validation(self):
        """Form validation fails if requested days exceed available quota."""
        # Available is 14 days, apply for 15 working days
        form_data = {
            'leave_type': self.pl_type.id,
            'start_date': '2026-02-02', # Monday
            'end_date': '2026-02-20',   # 3 full weeks = 15 working days
            'is_half_day': False,
            'reason': 'Extended leave beyond balance'
        }
        form = LeaveApplicationForm(data=form_data, employee=self.emp_a)
        self.assertFalse(form.is_valid())
        self.assertTrue(any('Insufficient leave balance' in err for err in form.non_field_errors()))

    def test_multi_company_isolation_in_leave_list(self):
        """HR Admin of Company A cannot see applications from Company B."""
        # Create application for Company B
        LeaveApplication.objects.create(
            employee=self.emp_b,
            company=self.company_b,
            leave_type=self.pl_type,  # for test fixture
            start_date=date(2026, 1, 21),
            end_date=date(2026, 1, 21),
            is_half_day=False,
            total_days=Decimal('1.00'),
            reason="Company B leave",
            status=LeaveApplication.ApplicationStatus.PENDING
        )

        # Login as HR Admin Alpha
        self.client.login(username='hr_alpha', password='password123')
        response = self.client.get(reverse('leaves:list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Jane Beta")
        self.assertNotContains(response, "Company B leave")
