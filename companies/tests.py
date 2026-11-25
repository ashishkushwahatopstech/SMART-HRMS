from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from companies.models import Company
from employees.models import Employee


class CompanyModelAndSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.superadmin = User.objects.create_superuser(
            username='adminuser',
            password='Password@123',
            email='admin@example.com'
        )
        self.employee_user = User.objects.create_user(
            username='empuser',
            password='Password@123',
            email='emp@example.com',
            role=User.Role.EMPLOYEE
        )
        self.company = Company.objects.create(
            name='Test Corp Pvt Ltd',
            code='TESTCORP',
            working_days_per_week=5,
            default_working_hours=Decimal('8.00'),
            monthly_paid_leave_allowance=Decimal('1.00')
        )

    def test_company_creation_and_cleaning(self):
        c = Company.objects.create(name='Beta Labs', code='  beta  ')
        self.assertEqual(c.code, 'BETA')
        self.assertEqual(str(c), 'Beta Labs (BETA)')

    def test_company_deletion_safeguard(self):
        # Company without employees can be deleted
        self.assertTrue(self.company.can_be_deleted())

        # Adding an employee blocks deletion
        Employee.objects.create(
            employee_id='TEST-EMP001',
            company=self.company,
            first_name='John',
            last_name='Doe',
            email='john@testcorp.com',
            phone='+91 99999 88888',
            monthly_salary=Decimal('50000.00')
        )
        self.assertFalse(self.company.can_be_deleted())

    def test_super_admin_can_access_company_views(self):
        self.client.login(username='adminuser', password='Password@123')
        response = self.client.get(reverse('companies:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Corp Pvt Ltd')

        detail_res = self.client.get(reverse('companies:detail', args=[self.company.pk]))
        self.assertEqual(detail_res.status_code, 200)

    def test_employee_cannot_access_company_management(self):
        self.client.login(username='empuser', password='Password@123')
        response = self.client.get(reverse('companies:list'))
        self.assertEqual(response.status_code, 302)  # Redirected with access denied
