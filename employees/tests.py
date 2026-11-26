from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.db import IntegrityError
from accounts.models import User
from companies.models import Company
from employees.models import Department, Designation, Employee


class EmployeeModuleTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Companies
        self.company_a = Company.objects.create(name='Company Alpha', code='ALPHA')
        self.company_b = Company.objects.create(name='Company Beta', code='BETA')

        # Departments
        self.dept_it = Department.objects.create(company=self.company_a, name='IT', code='IT')
        self.dept_hr = Department.objects.create(company=self.company_a, name='HR', code='HR')

        # Designations
        self.desig_dev = Designation.objects.create(company=self.company_a, department=self.dept_it, title='Developer')

        # Users
        self.superadmin = User.objects.create_superuser(
            username='adminuser', password='Password@123', email='admin@test.com'
        )

        self.hr_user = User.objects.create_user(
            username='hr_alpha', password='Password@123', email='hr@alpha.com', role=User.Role.HR_ADMIN
        )
        self.emp_user1 = User.objects.create_user(
            username='emp1_alpha', password='Password@123', email='emp1@alpha.com', role=User.Role.EMPLOYEE
        )
        self.emp_user2 = User.objects.create_user(
            username='emp2_alpha', password='Password@123', email='emp2@alpha.com', role=User.Role.EMPLOYEE
        )

        # Employees in Company A
        self.hr_emp = Employee.objects.create(
            user=self.hr_user,
            employee_id='ALPHA-EMP0001',
            company=self.company_a,
            first_name='Harish',
            last_name='Rawat',
            email='hr@alpha.com',
            phone='+91 99000 11111',
            monthly_salary=Decimal('60000.00')
        )

        self.employee1 = Employee.objects.create(
            user=self.emp_user1,
            employee_id='ALPHA-EMP0002',
            company=self.company_a,
            first_name='Alok',
            last_name='Kumar',
            email='emp1@alpha.com',
            phone='+91 99000 22222',
            department=self.dept_it,
            designation=self.desig_dev,
            monthly_salary=Decimal('9000.00'),
            working_hours_per_day=Decimal('8.00')
        )

        self.employee2 = Employee.objects.create(
            user=self.emp_user2,
            employee_id='ALPHA-EMP0003',
            company=self.company_a,
            first_name='Bhavna',
            last_name='Patel',
            email='emp2@alpha.com',
            phone='+91 99000 33333',
            monthly_salary=Decimal('50000.00')
        )

        # Employee in Company B
        self.employee_beta = Employee.objects.create(
            employee_id='BETA-EMP0001',
            company=self.company_b,
            first_name='Suresh',
            last_name='Raina',
            email='suresh@beta.com',
            phone='+91 99000 44444',
            monthly_salary=Decimal('40000.00')
        )

    def test_unique_department_per_company_constraint(self):
        """Duplicate department names in same company should raise IntegrityError."""
        with self.assertRaises(IntegrityError):
            Department.objects.create(company=self.company_a, name='IT', code='IT2')

    def test_salary_calculation_realistic_values(self):
        """Tests section 12 prompt example: ₹9,000 / 26 days = ₹346.15; ₹346.15 / 8h = ₹43.27."""
        daily_rate = self.employee1.calculate_daily_rate(working_days=26)
        hourly_rate = self.employee1.calculate_hourly_rate(working_days=26)
        self.assertEqual(daily_rate, Decimal('346.15'))
        self.assertEqual(hourly_rate, Decimal('43.27'))

    def test_auto_generate_next_employee_id(self):
        next_id = Employee.generate_next_employee_id(self.company_a)
        self.assertEqual(next_id, 'ALPHA-EMP0004')

    def test_multi_company_data_isolation(self):
        """HR Admin of Company A must not see Company B's employees."""
        self.client.login(username='hr_alpha', password='Password@123')
        response = self.client.get(reverse('employees:list'))
        self.assertEqual(response.status_code, 200)

        # Company A employees should be visible
        self.assertContains(response, 'Alok Kumar')
        self.assertContains(response, 'Bhavna Patel')

        # Company B employee MUST NOT be visible!
        self.assertNotContains(response, 'Suresh Raina')

    def test_employee_privacy_safeguard(self):
        """Employee 1 must NOT be allowed to view confidential records of Employee 2."""
        self.client.login(username='emp1_alpha', password='Password@123')

        # Can view own profile
        res_own = self.client.get(reverse('employees:detail', args=[self.employee1.pk]))
        self.assertEqual(res_own.status_code, 200)
        self.assertContains(res_own, 'Alok Kumar')

        # BLOCKED from viewing Employee 2's profile
        res_other = self.client.get(reverse('employees:detail', args=[self.employee2.pk]))
        self.assertEqual(res_other.status_code, 302)  # Redirected with access denied
        self.assertEqual(res_other.url, reverse('dashboard:index'))

    def test_create_employee_with_automatic_user_provisioning(self):
        """HR Admin can create an employee and simultaneously provision a login account."""
        self.client.login(username='hr_alpha', password='Password@123')
        post_data = {
            'company': self.company_a.pk,
            'employee_id': 'ALPHA-EMP0099',
            'first_name': 'Rohit',
            'last_name': 'Sharma',
            'email': 'rohit@alpha.com',
            'phone': '+91 98888 77777',
            'department': self.dept_it.pk,
            'designation': self.desig_dev.pk,
            'joining_date': '2026-01-01',
            'employment_status': 'active',
            'salary_type': 'monthly',
            'monthly_salary': '70000.00',
            'working_hours_per_day': '8.00',
            'assigned_shift_name': 'General Shift (09:00 - 17:00)',
            'create_user_account': True,
            'user_role': 'employee',
            'initial_password': 'Employee@123',
        }
        response = self.client.post(reverse('employees:create'), post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify employee was created
        rohit = Employee.objects.get(employee_id='ALPHA-EMP0099')
        self.assertEqual(rohit.first_name, 'Rohit')
        self.assertIsNotNone(rohit.user)
        self.assertEqual(rohit.user.email, 'rohit@alpha.com')
        self.assertEqual(rohit.user.role, User.Role.EMPLOYEE)

    def test_designation_creation_and_department_sync(self):
        """HR Admin can create a new designation for a department with company auto-sync."""
        self.client.login(username='hr_alpha', password='Password@123')

        post_data = {
            'department': self.dept_it.pk,
            'title': 'Senior DevOps Engineer',
            'description': 'CI/CD pipeline and cloud infrastructure',
            'return_to': 'departments',
        }
        response = self.client.post(reverse('employees:designations'), post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify designation was created and belongs to company_a
        desig = Designation.objects.filter(title='Senior DevOps Engineer', department=self.dept_it).first()
        self.assertIsNotNone(desig)
        self.assertEqual(desig.company, self.company_a)

    def test_designation_deletion_safeguards(self):
        """Cannot delete designation with active employees; can delete when unassigned."""
        self.client.login(username='hr_alpha', password='Password@123')

        # desig_dev is assigned to self.employee1 -> deletion must be blocked
        del_url = reverse('employees:designation_delete', args=[self.desig_dev.pk])
        resp_blocked = self.client.post(del_url, follow=True)
        self.assertEqual(resp_blocked.status_code, 200)
        self.assertTrue(Designation.objects.filter(pk=self.desig_dev.pk).exists())

        # Create unassigned designation
        unassigned_desig = Designation.objects.create(
            company=self.company_a, department=self.dept_hr, title='HR Intern'
        )
        del_unassigned = reverse('employees:designation_delete', args=[unassigned_desig.pk])
        resp_ok = self.client.post(del_unassigned, follow=True)
        self.assertEqual(resp_ok.status_code, 200)
        self.assertFalse(Designation.objects.filter(pk=unassigned_desig.pk).exists())

    def test_reporting_manager_dropdown_strictly_restricted_to_managers(self):
        """Reporting Manager field must ONLY show managers; regular employees and HR are excluded."""
        # Create an authorized manager employee
        mgr_user = User.objects.create_user(
            username='mgr_alpha', password='Password@123', email='mgr@alpha.com', role=User.Role.MANAGER
        )
        desig_mgr = Designation.objects.create(company=self.company_a, department=self.dept_it, title='Engineering Manager')
        mgr_emp = Employee.objects.create(
            user=mgr_user,
            employee_id='ALPHA-MGR001',
            company=self.company_a,
            first_name='Vikram',
            last_name='Malhotra',
            email='mgr@alpha.com',
            phone='+91 99000 88888',
            department=self.dept_it,
            designation=desig_mgr,
            monthly_salary=Decimal('100000.00')
        )

        from employees.forms import EmployeeForm
        form = EmployeeForm(user=self.hr_user)
        manager_queryset = form.fields['manager'].queryset

        # Manager MUST be in the queryset
        self.assertIn(mgr_emp, manager_queryset)

        # Regular employee (self.employee1) MUST NOT be in the manager queryset
        self.assertNotIn(self.employee1, manager_queryset)

        # HR Admin (self.hr_emp) MUST NOT be in the manager queryset
        self.assertNotIn(self.hr_emp, manager_queryset)

        # Also verify the company-options API endpoint
        self.client.login(username='hr_alpha', password='Password@123')
        resp = self.client.get(reverse('employees:api_company_options', args=[self.company_a.pk]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        mgr_ids = [m['id'] for m in data['managers']]
        self.assertIn(mgr_emp.pk, mgr_ids)
        self.assertNotIn(self.employee1.pk, mgr_ids)
        self.assertNotIn(self.hr_emp.pk, mgr_ids)

    def test_employee_lunch_schedule_inheritance_and_override(self):
        from shifts.models import Shift
        from datetime import time
        shift = Shift.objects.create(
            company=self.company_a,
            name='Regular Shift',
            start_time=time(9, 0),
            end_time=time(18, 0),
            lunch_start_time=time(13, 0),
            lunch_end_time=time(14, 0),
        )
        # 1. Inherits default lunch from shift
        emp1 = Employee.objects.create(
            employee_id='ALPHA-EMP9991',
            company=self.company_a,
            first_name='Auto',
            last_name='Lunch',
            email='autolunch@test.com',
            phone='1234567890',
            assigned_shift=shift,
        )
        self.assertEqual(emp1.lunch_start_time, time(13, 0))
        self.assertEqual(emp1.lunch_end_time, time(14, 0))

        # 2. Custom modified lunch time per employee
        emp2 = Employee.objects.create(
            employee_id='ALPHA-EMP9992',
            company=self.company_a,
            first_name='Custom',
            last_name='Lunch',
            email='customlunch@test.com',
            phone='1234567891',
            assigned_shift=shift,
            lunch_start_time=time(12, 30),
            lunch_end_time=time(13, 15),
        )
        self.assertEqual(emp2.lunch_start_time, time(12, 30))
        self.assertEqual(emp2.lunch_end_time, time(13, 15))

