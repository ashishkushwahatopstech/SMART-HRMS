from decimal import Decimal
from datetime import date
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from companies.models import Company
from employees.models import Department, Designation, Employee
from attendance.models import Attendance
from leaves.models import LeaveType, LeaveBalance
from payroll.models import PayrollRun, Payslip


class ReportsEngineTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name="Alpha Corp", code="ALPHA")
        self.company_b = Company.objects.create(name="Beta Corp", code="BETA")

        self.superadmin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='password123', role=User.Role.SUPER_ADMIN
        )
        self.hr_user_a = User.objects.create_user(
            username='hr_alpha', email='hr@alpha.com', password='password123', role=User.Role.HR_ADMIN
        )
        self.emp_user_a = User.objects.create_user(
            username='emp_alpha', email='emp@alpha.com', password='password123', role=User.Role.EMPLOYEE
        )

        self.dept_a = Department.objects.create(company=self.company_a, name="Tech")
        self.desig_a = Designation.objects.create(company=self.company_a, department=self.dept_a, title="Dev")

        self.emp_hr = Employee.objects.create(
            user=self.hr_user_a,
            employee_id="A-HR01",
            company=self.company_a,
            first_name="HR",
            last_name="Alpha",
            email="hr@alpha.com",
            phone="1111111111",
            department=self.dept_a,
            designation=self.desig_a
        )
        self.emp_a = Employee.objects.create(
            user=self.emp_user_a,
            employee_id="A-EMP01",
            company=self.company_a,
            first_name="John",
            last_name="Doe",
            email="john@alpha.com",
            phone="2222222222",
            department=self.dept_a,
            designation=self.desig_a,
            monthly_salary=Decimal('50000.00')
        )

        # Seed 1 attendance record
        Attendance.objects.create(
            employee=self.emp_a,
            company=self.company_a,
            date=date(2026, 1, 15),
            status=Attendance.AttendanceStatus.PRESENT
        )

        # Seed 1 leave balance
        self.pl_type = LeaveType.objects.create(
            company=self.company_a,
            name="Paid Leave",
            code="PL",
            annual_quota=Decimal('12.00')
        )
        LeaveBalance.objects.create(
            employee=self.emp_a,
            leave_type=self.pl_type,
            year=2026,
            allocated_days=Decimal('12.00')
        )

        # Seed 1 payroll run & payslip
        self.run_a = PayrollRun.objects.create(
            company=self.company_a,
            year=2026,
            month=1
        )
        self.run_a.generate_payslips(self.superadmin)

        self.client = Client()

    def test_attendance_muster_export_excel(self):
        """Tests Excel export of attendance muster."""
        self.client.login(username='hr_alpha', password='password123')
        url = reverse('reports:export_attendance') + '?year=2026&month=1&format=excel'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertIn('attachment; filename="Attendance_Muster_ALPHA_January_2026.xlsx"', response['Content-Disposition'])
        self.assertTrue(len(response.content) > 1000)

    def test_attendance_muster_export_csv(self):
        """Tests CSV export of attendance muster."""
        self.client.login(username='hr_alpha', password='password123')
        url = reverse('reports:export_attendance') + '?year=2026&month=1&format=csv'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('A-EMP01', response.content.decode('utf-8'))
        self.assertIn('John Doe', response.content.decode('utf-8'))

    def test_payroll_ledger_export_excel(self):
        """Tests Excel export of monthly payroll ledger."""
        self.client.login(username='hr_alpha', password='password123')
        url = reverse('reports:export_payroll') + '?year=2026&month=1&format=excel'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertIn('attachment; filename="Payroll_Ledger_ALPHA_January_2026.xlsx"', response['Content-Disposition'])

    def test_leave_summary_export_csv(self):
        """Tests CSV export of annual leave summary."""
        self.client.login(username='hr_alpha', password='password123')
        url = reverse('reports:export_leaves') + '?year=2026&format=csv'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('Paid Leave', response.content.decode('utf-8'))
        self.assertIn('12.0', response.content.decode('utf-8'))

    def test_employee_directory_export_excel(self):
        """Tests Excel export of employee master directory."""
        self.client.login(username='hr_alpha', password='password123')
        url = reverse('reports:export_employees') + '?format=excel'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    def test_regular_employee_forbidden_from_reports(self):
        """Regular employee cannot access reports center."""
        self.client.login(username='emp_alpha', password='password123')
        response = self.client.get(reverse('reports:dashboard'))
        self.assertEqual(response.status_code, 403)
