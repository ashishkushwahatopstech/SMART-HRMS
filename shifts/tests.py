from decimal import Decimal
from datetime import time, date, datetime
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from companies.models import Company
from employees.models import Employee
from shifts.models import Shift, ShiftAssignment


class ShiftCalculationAndModelTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Shift Test Co', code='STC')

    def test_standard_8_hour_shift_calculation(self):
        shift = Shift.objects.create(
            company=self.company,
            name='Day General',
            start_time=time(9, 0),
            end_time=time(17, 0),
            lunch_duration_minutes=60,
            break_duration_minutes=15,
            grace_period_minutes=15
        )
        self.assertEqual(shift.total_expected_hours, Decimal('8.00'))
        self.assertFalse(shift.is_overnight)
        # Net hours: 8.00 - (75 / 60 = 1.25) = 6.75
        self.assertEqual(shift.calculate_net_working_hours(), Decimal('6.75'))

    def test_12_hour_shift_calculation(self):
        shift = Shift.objects.create(
            company=self.company,
            name='12-Hour Day Rotation',
            start_time=time(8, 0),
            end_time=time(20, 0),
            lunch_duration_minutes=60,
            break_duration_minutes=30
        )
        self.assertEqual(shift.total_expected_hours, Decimal('12.00'))
        self.assertFalse(shift.is_overnight)

    def test_24_hour_shift_calculation(self):
        shift = Shift.objects.create(
            company=self.company,
            name='24-Hour Critical',
            start_time=time(9, 0),
            end_time=time(9, 0),
            is_overnight=True
        )
        self.assertEqual(shift.total_expected_hours, Decimal('24.00'))
        self.assertTrue(shift.is_overnight)

    def test_overnight_night_shift_and_window(self):
        """Cross-midnight shift (10 PM to 6 AM) must not split dates incorrectly."""
        shift = Shift.objects.create(
            company=self.company,
            name='Night Shift',
            start_time=time(22, 0),
            end_time=time(6, 0),
            lunch_duration_minutes=45,
            break_duration_minutes=15
        )
        # Auto-detected as overnight because end_time < start_time
        self.assertTrue(shift.is_overnight)
        self.assertEqual(shift.total_expected_hours, Decimal('8.00'))

        # Check shift window spanning into next calendar day
        test_date = date(2026, 11, 24)
        start_dt, end_dt = shift.get_shift_window(test_date)
        self.assertEqual(start_dt, datetime(2026, 11, 24, 22, 0))
        self.assertEqual(end_dt, datetime(2026, 11, 25, 6, 0))

    def test_late_arrival_grace_period_calculation(self):
        shift = Shift.objects.create(
            company=self.company,
            name='Grace Test Shift',
            start_time=time(9, 0),
            end_time=time(17, 0),
            grace_period_minutes=15
        )
        # On time
        self.assertFalse(shift.is_check_in_late(time(8, 55)))
        self.assertFalse(shift.is_check_in_late(time(9, 0)))
        self.assertFalse(shift.is_check_in_late(time(9, 15)))  # Within 15 min grace

        # Late (after 09:15)
        self.assertTrue(shift.is_check_in_late(time(9, 16)))
        self.assertTrue(shift.is_check_in_late(time(9, 45)))


class ShiftViewsAndAssignmentTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.company_a = Company.objects.create(name='Company Alpha', code='ALPHA')
        self.company_b = Company.objects.create(name='Company Beta', code='BETA')

        self.hr_user = User.objects.create_user(
            username='hr_alpha', password='Password@123', email='hr@alpha.com', role=User.Role.HR_ADMIN
        )

        self.shift_a = Shift.objects.create(
            company=self.company_a,
            name='Alpha General Shift',
            start_time=time(9, 0),
            end_time=time(17, 0)
        )
        self.shift_b = Shift.objects.create(
            company=self.company_b,
            name='Beta Factory Shift',
            start_time=time(7, 0),
            end_time=time(15, 0)
        )

        self.employee = Employee.objects.create(
            user=self.hr_user,
            employee_id='ALPHA-EMP101',
            company=self.company_a,
            first_name='Anil',
            last_name='Kumble',
            email='anil@alpha.com',
            phone='+91 99111 22333',
            monthly_salary=Decimal('45000.00'),
            assigned_shift=self.shift_a
        )

    def test_shift_deletion_safeguard(self):
        """Cannot delete shift while employees are assigned to it."""
        self.assertFalse(self.shift_a.can_be_deleted())

        # Unassign employee
        self.employee.assigned_shift = None
        self.employee.save()
        self.assertTrue(self.shift_a.can_be_deleted())

    def test_shift_multi_company_isolation(self):
        """HR of Company Alpha must only see Alpha shifts."""
        self.client.login(username='hr_alpha', password='Password@123')
        response = self.client.get(reverse('shifts:list'))
        self.assertEqual(response.status_code, 200)

        # Alpha shift visible
        self.assertContains(response, 'Alpha General Shift')
        # Beta shift NOT visible
        self.assertNotContains(response, 'Beta Factory Shift')

    def test_assign_shift_creates_history_record(self):
        """Assigning shift updates employee and creates ShiftAssignment history record."""
        self.client.login(username='hr_alpha', password='Password@123')

        new_shift = Shift.objects.create(
            company=self.company_a,
            name='Alpha Afternoon Shift',
            start_time=time(13, 0),
            end_time=time(21, 0)
        )

        post_data = {
            'employees': [self.employee.pk],
            'start_date': '2026-11-25',
            'remarks': 'Transferred to afternoon shift rotation',
        }
        response = self.client.post(reverse('shifts:assign', args=[new_shift.pk]), post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        self.employee.refresh_from_db()
        self.assertEqual(self.employee.assigned_shift, new_shift)

        # Verify ShiftAssignment history record exists
        history = ShiftAssignment.objects.filter(employee=self.employee, shift=new_shift).first()
        self.assertIsNotNone(history)
        self.assertTrue(history.is_active)
        self.assertEqual(history.remarks, 'Transferred to afternoon shift rotation')
