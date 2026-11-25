from decimal import Decimal
from datetime import date
from django.test import TestCase, Client
from django.urls import reverse
from django.db import IntegrityError, transaction
from accounts.models import User
from companies.models import Company
from employees.models import Department, Designation, Employee
from holidays.models import Holiday
from leaves.models import LeaveType, LeaveBalance, LeaveApplication
from attendance.models import Attendance
from payroll.models import PayrollRun, Payslip
from payroll.engine import compute_monthly_payroll, number_to_words_inr


class PayrollEngineTests(TestCase):
    def setUp(self):
        # 1. Company A with Actual Working Days Policy
        self.company_a = Company.objects.create(
            name="Alpha Corp",
            code="ALPHA",
            weekly_holiday_policy=Company.WeeklyHolidayPolicy.SATURDAY_SUNDAY,
            working_days_per_week=5,
            salary_calculation_policy=Company.SalaryCalculationPolicy.ACTUAL_WORKING_DAYS
        )

        # Company B with Fixed 26 Days Policy
        self.company_b = Company.objects.create(
            name="Beta Corp",
            code="BETA",
            weekly_holiday_policy=Company.WeeklyHolidayPolicy.SATURDAY_SUNDAY,
            working_days_per_week=5,
            salary_calculation_policy=Company.SalaryCalculationPolicy.FIXED_26_DAYS
        )

        # 2. Users
        self.superadmin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='password123', role=User.Role.SUPER_ADMIN
        )
        self.hr_user_a = User.objects.create_user(
            username='hr_alpha', email='hr@alpha.com', password='password123', role=User.Role.HR_ADMIN
        )
        self.emp_user_a = User.objects.create_user(
            username='emp_alpha', email='emp@alpha.com', password='password123', role=User.Role.EMPLOYEE
        )
        self.emp_user_b = User.objects.create_user(
            username='emp_beta', email='emp@beta.com', password='password123', role=User.Role.EMPLOYEE
        )

        # 3. Dept & Desig
        self.dept_a = Department.objects.create(company=self.company_a, name="Engineering")
        self.desig_a = Designation.objects.create(company=self.company_a, department=self.dept_a, title="Developer")

        self.dept_b = Department.objects.create(company=self.company_b, name="Operations")
        self.desig_b = Designation.objects.create(company=self.company_b, department=self.dept_b, title="Staff")

        # 4. Employees
        # Trainee Developer with ₹9,000 monthly salary (Section 12 reference)
        self.trainee = Employee.objects.create(
            user=self.emp_user_a,
            employee_id="A-EMP01",
            company=self.company_a,
            first_name="Neha",
            last_name="Rao",
            email="neha@alpha.com",
            phone="1111111111",
            department=self.dept_a,
            designation=self.desig_a,
            salary_type=Employee.SalaryType.MONTHLY,
            monthly_salary=Decimal('9000.00'),
            working_hours_per_day=Decimal('8.00')
        )

        # Senior Engineer with ₹60,000 monthly salary
        self.senior_dev = Employee.objects.create(
            employee_id="A-EMP02",
            company=self.company_a,
            first_name="Arun",
            last_name="Verma",
            email="arun@alpha.com",
            phone="2222222222",
            department=self.dept_a,
            designation=self.desig_a,
            salary_type=Employee.SalaryType.MONTHLY,
            monthly_salary=Decimal('60000.00'),
            working_hours_per_day=Decimal('8.00')
        )

        # Beta employee with ₹9,000 monthly salary under Fixed 26 Days
        self.emp_b = Employee.objects.create(
            user=self.emp_user_b,
            employee_id="B-EMP01",
            company=self.company_b,
            first_name="Jane",
            last_name="Beta",
            email="jane@beta.com",
            phone="3333333333",
            department=self.dept_b,
            designation=self.desig_b,
            salary_type=Employee.SalaryType.MONTHLY,
            monthly_salary=Decimal('9000.00'),
            working_hours_per_day=Decimal('8.00')
        )

        self.emp_hr = Employee.objects.create(
            user=self.hr_user_a,
            employee_id="A-HR01",
            company=self.company_a,
            first_name="HR",
            last_name="Alpha",
            email="hr@alpha.com",
            phone="4444444444",
            department=self.dept_a,
            designation=self.desig_a
        )

        # 5. January 2026 Holiday (Republic Day - Jan 26)
        Holiday.objects.create(
            company=self.company_a,
            name="Republic Day",
            date=date(2026, 1, 26),
            holiday_type=Holiday.HolidayType.MANDATORY,
            is_optional=False
        )

        # 6. Unpaid Leave Type (LWP)
        self.lwp_type = LeaveType.objects.create(
            company=self.company_a,
            name="Leave Without Pay",
            code="LWP",
            annual_quota=Decimal('0.00'),
            is_paid=False
        )

        self.client = Client()

    def test_actual_working_days_policy_rate_computation(self):
        """
        In Jan 2026, Alpha Corp has 5 Saturdays, 4 Sundays, and 1 mandatory holiday (Jan 26).
        Total calendar days = 31.
        Actual working days = 31 - 9 - 1 = 21 days.
        For Trainee with ₹9,000 salary:
        Per-day rate = 9000 / 21 = 428.57.
        """
        payroll = compute_monthly_payroll(self.trainee, 2026, 1)
        self.assertEqual(payroll['working_days'], Decimal('21'))
        self.assertEqual(payroll['per_day_rate'], Decimal('428.57'))

    def test_fixed_26_days_policy_rate_computation(self):
        """
        Under Company B's Fixed 26 Days Policy:
        Per-day rate = 9000 / 26 = 346.15.
        """
        payroll = compute_monthly_payroll(self.emp_b, 2026, 1)
        self.assertEqual(payroll['per_day_rate'], Decimal('346.15'))

    def test_fixed_30_days_policy_attendance_and_in_between_sundays(self):
        """
        When working days is set 30 days:
        Salary is based on attendance marks + in-between Sundays.
        E.g. Employee with ₹30,000 monthly salary (rate = ₹1,000/day).
        Punched on Friday Jan 9 and Monday Jan 12 (2 days).
        Sunday Jan 11 is flanked by punches -> included!
        Total paid days = 2 (attended) + 1 (Sunday) = 3 paid days.
        LOP days = 27 -> LOP deduction = ₹27,000.
        Earned base = ₹3,000.
        """
        company_30 = Company.objects.create(
            name="Gamma 30 Days Corp",
            code="GAMMA30",
            salary_calculation_policy=Company.SalaryCalculationPolicy.FIXED_30_DAYS,
            working_days_per_week=6
        )
        emp_30 = Employee.objects.create(
            employee_id="G-EMP01",
            company=company_30,
            first_name="Raj",
            last_name="Kumar",
            email="raj@gamma.com",
            salary_type=Employee.SalaryType.MONTHLY,
            monthly_salary=Decimal('30000.00'),
            working_hours_per_day=Decimal('8.00')
        )
        # Friday Jan 9, 2026
        Attendance.objects.create(
            employee=emp_30,
            company=company_30,
            date=date(2026, 1, 9),
            status=Attendance.AttendanceStatus.PRESENT
        )
        # Monday Jan 12, 2026
        Attendance.objects.create(
            employee=emp_30,
            company=company_30,
            date=date(2026, 1, 12),
            status=Attendance.AttendanceStatus.PRESENT
        )

        payroll = compute_monthly_payroll(emp_30, 2026, 1)
        self.assertEqual(payroll['working_days'], Decimal('30.00'))
        self.assertEqual(payroll['per_day_rate'], Decimal('1000.00'))
        self.assertEqual(payroll['sundays_included'], Decimal('1.00'))
        self.assertEqual(payroll['days_present'], Decimal('3.00'))
        self.assertEqual(payroll['unpaid_leaves'], Decimal('27.00'))
        self.assertEqual(payroll['loss_of_pay_deduction'], Decimal('27000.00'))

    def test_fixed_30_days_sundays_outside_punches_not_included(self):
        """
        Sundays that do not come in between punching days are NOT included.
        E.g. Punches on Jan 15 and 16 only.
        Sundays on Jan 4, 11 (before) and Jan 18, 25 (after) must NOT be included.
        """
        company_30 = Company.objects.create(
            name="Delta 30 Corp",
            code="DELTA30",
            salary_calculation_policy=Company.SalaryCalculationPolicy.FIXED_30_DAYS,
            working_days_per_week=6
        )
        emp = Employee.objects.create(
            employee_id="D-EMP01",
            company=company_30,
            first_name="Sunil",
            last_name="Sharma",
            email="sunil@delta.com",
            salary_type=Employee.SalaryType.MONTHLY,
            monthly_salary=Decimal('30000.00'),
            working_hours_per_day=Decimal('8.00')
        )
        Attendance.objects.create(
            employee=emp, company=company_30, date=date(2026, 1, 15), status=Attendance.AttendanceStatus.PRESENT
        )
        Attendance.objects.create(
            employee=emp, company=company_30, date=date(2026, 1, 16), status=Attendance.AttendanceStatus.PRESENT
        )

        payroll = compute_monthly_payroll(emp, 2026, 1)
        self.assertEqual(payroll['sundays_included'], Decimal('0.00'))
        self.assertEqual(payroll['days_present'], Decimal('2.00'))
        self.assertEqual(payroll['unpaid_leaves'], Decimal('28.00'))
        self.assertEqual(payroll['loss_of_pay_deduction'], Decimal('28000.00'))

    def test_fixed_26_days_policy_working_hours_calculation(self):
        """
        When working days is set 26 days:
        Salary is calculated from actual working hours.
        E.g. Monthly salary = ₹26,000, 8 hrs/day shift.
        Daily rate = 26000 / 26 = 1000. Hourly rate = 1000 / 8 = 125.
        Total expected hours for 26 days = 208 hours.
        If employee works 16.00 hours total:
        Shortfall = 208 - 16 = 192 hours.
        LOP deduction = 192 * 125 = ₹24,000.
        Earned base = 16 * 125 = ₹2,000.
        """
        att = Attendance.objects.create(
            employee=self.emp_b,
            company=self.company_b,
            date=date(2026, 1, 5),
            status=Attendance.AttendanceStatus.PRESENT
        )
        Attendance.objects.filter(id=att.id).update(total_working_hours=Decimal('16.00'))

        payroll = compute_monthly_payroll(self.emp_b, 2026, 1)
        self.assertEqual(payroll['working_days'], Decimal('26.00'))
        self.assertEqual(payroll['per_day_rate'], Decimal('346.15'))
        self.assertEqual(payroll['hourly_rate'], Decimal('43.27'))
        # Total expected hours = 26 * 8 = 208 hrs
        # Shortfall = 208 - 16 = 192 hrs
        # LOP deduction = 192 * 43.27 = 8307.84
        # Earned base = 9000 - 8307.84 = 692.16 (16 * 43.27)
        self.assertEqual(payroll['loss_of_pay_deduction'], Decimal('8307.84'))

    def test_loss_of_pay_deduction_for_unpaid_leave(self):
        """
        If Trainee takes 2 days of approved LWP in Jan 2026:
        LOP Deduction = 2 * 428.57 = 857.14.
        """
        LeaveApplication.objects.create(
            employee=self.trainee,
            company=self.company_a,
            leave_type=self.lwp_type,
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 16),
            is_half_day=False,
            total_days=Decimal('2.00'),
            reason="Unforeseen personal leave",
            status=LeaveApplication.ApplicationStatus.APPROVED
        )

        payroll = compute_monthly_payroll(self.trainee, 2026, 1)
        self.assertEqual(payroll['unpaid_leaves'], Decimal('2.00'))
        self.assertEqual(payroll['loss_of_pay_deduction'], Decimal('857.14'))

    def test_overtime_pay_calculation(self):
        """
        If Senior Dev (₹60,000 salary, rate/day = 60000/21 = 2857.14, hourly = 2857.14/8 = 357.14)
        works 10 hours overtime:
        Overtime pay = 10 * 357.14 * 1.5 = 5357.10.
        """
        att = Attendance.objects.create(
            employee=self.senior_dev,
            company=self.company_a,
            date=date(2026, 1, 12),
            status=Attendance.AttendanceStatus.PRESENT
        )
        Attendance.objects.filter(id=att.id).update(
            overtime_hours=Decimal('10.00'),
            total_working_hours=Decimal('18.00')
        )

        payroll = compute_monthly_payroll(self.senior_dev, 2026, 1)
        self.assertEqual(payroll['overtime_hours'], Decimal('10.00'))
        self.assertAlmostEqual(float(payroll['overtime_pay']), 5357.10, places=1)

    def test_number_to_words_inr_formatting(self):
        """Tests Indian Rupee words generation."""
        words_9000 = number_to_words_inr(Decimal('9000.00'))
        self.assertEqual(words_9000, "Rupees Nine Thousand Only")

        words_45200 = number_to_words_inr(Decimal('45200.00'))
        self.assertEqual(words_45200, "Rupees Forty Five Thousand Two Hundred Only")

    def test_payroll_run_generate_and_lock_workflow(self):
        """
        Tests PayrollRun batch execution, payslip generation,
        and lock enforcement.
        """
        run = PayrollRun.objects.create(
            company=self.company_a,
            year=2026,
            month=1
        )
        run.generate_payslips(self.superadmin)

        self.assertEqual(run.status, PayrollRun.RunStatus.PROCESSED)
        self.assertEqual(run.total_employees, 3) # trainee, senior_dev, emp_hr
        self.assertEqual(run.payslips.count(), 3)
        self.assertTrue(run.total_net_pay > 0)

        # Lock the run
        run.lock(self.superadmin)
        self.assertEqual(run.status, PayrollRun.RunStatus.LOCKED)
        self.assertIsNotNone(run.locked_at)

        # Attempting regeneration must raise ValueError
        with self.assertRaises(ValueError):
            run.generate_payslips(self.superadmin)

    def test_multi_company_isolation_on_payroll_dashboard(self):
        """HR Admin Alpha cannot see Payroll Runs from Beta Corp."""
        PayrollRun.objects.create(
            company=self.company_b,
            year=2026,
            month=1,
            total_net_pay=Decimal('50000.00')
        )

        self.client.login(username='hr_alpha', password='password123')
        response = self.client.get(reverse('payroll:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Beta Corp")

    def test_employee_can_only_view_own_payslip(self):
        """Employee cannot access another employee's payslip."""
        run = PayrollRun.objects.create(
            company=self.company_a,
            year=2026,
            month=1
        )
        run.generate_payslips(self.superadmin)

        trainee_payslip = run.payslips.get(employee=self.trainee)
        senior_payslip = run.payslips.get(employee=self.senior_dev)

        # Login as Trainee (emp_alpha)
        self.client.login(username='emp_alpha', password='password123')

        # Allowed to view own payslip
        resp_own = self.client.get(reverse('payroll:payslip_detail', args=[trainee_payslip.id]))
        self.assertEqual(resp_own.status_code, 200)
        self.assertContains(resp_own, "Neha Rao")

        # Forbidden from viewing senior dev's payslip
        resp_other = self.client.get(reverse('payroll:payslip_detail', args=[senior_payslip.id]))
        self.assertEqual(resp_other.status_code, 403)
