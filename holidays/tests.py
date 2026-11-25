from datetime import date
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.db import IntegrityError, transaction
from accounts.models import User
from companies.models import Company
from employees.models import Employee
from holidays.models import Holiday


class HolidayModelAndWorkingDayTests(TestCase):
    def setUp(self):
        # Company A: 5-day week (Sat/Sun off)
        self.comp_5day = Company.objects.create(
            name='Five Day Co',
            code='FIVEDAY',
            weekly_holiday_policy=Company.WeeklyHolidayPolicy.SATURDAY_SUNDAY
        )
        # Company B: 6-day week (Sun only off)
        self.comp_6day = Company.objects.create(
            name='Six Day Co',
            code='SIXDAY',
            weekly_holiday_policy=Company.WeeklyHolidayPolicy.SUNDAY_ONLY
        )

        # 2026-01-26 is Monday (Republic Day)
        self.holiday_republic = Holiday.objects.create(
            company=self.comp_5day,
            name='Republic Day',
            date=date(2026, 1, 26),
            holiday_type=Holiday.HolidayType.MANDATORY,
            is_optional=False
        )
        # 2026-02-16 is Monday (Maha Shivratri - Optional)
        self.holiday_shivratri = Holiday.objects.create(
            company=self.comp_5day,
            name='Maha Shivratri',
            date=date(2026, 2, 16),
            holiday_type=Holiday.HolidayType.OPTIONAL,
            is_optional=True
        )

    def test_holiday_properties(self):
        self.assertEqual(self.holiday_republic.day_of_week, 'Monday')
        self.assertEqual(self.holiday_republic.get_badge_class(), 'bg-danger')
        self.assertEqual(self.holiday_shivratri.get_badge_class(), 'bg-info text-dark')

    def test_unique_holiday_per_company_constraint(self):
        """Duplicate holiday on the same date within the same company must fail."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Holiday.objects.create(
                    company=self.comp_5day,
                    name='Duplicate Republic Day',
                    date=date(2026, 1, 26)
                )

        # Allowed for a different company
        h_b = Holiday.objects.create(
            company=self.comp_6day,
            name='Republic Day B',
            date=date(2026, 1, 26)
        )
        self.assertIsNotNone(h_b.pk)

    def test_is_working_day_weekly_off_logic(self):
        # Saturday: 2026-01-24
        sat_date = date(2026, 1, 24)
        # Sunday: 2026-01-25
        sun_date = date(2026, 1, 25)
        # Tuesday: 2026-01-27
        tue_date = date(2026, 1, 27)

        # 5-day week: Sat & Sun are not working days
        self.assertFalse(Holiday.is_working_day(self.comp_5day, sat_date))
        self.assertFalse(Holiday.is_working_day(self.comp_5day, sun_date))
        self.assertTrue(Holiday.is_working_day(self.comp_5day, tue_date))

        # 6-day week: Sat is working, Sun is not working
        self.assertTrue(Holiday.is_working_day(self.comp_6day, sat_date))
        self.assertFalse(Holiday.is_working_day(self.comp_6day, sun_date))

    def test_mandatory_vs_optional_holiday_working_day_evaluation(self):
        # Monday 2026-01-26 has mandatory holiday -> Not working day
        self.assertFalse(Holiday.is_working_day(self.comp_5day, date(2026, 1, 26)))

        # Monday 2026-02-16 has optional holiday -> Regular working day unless floating leave taken
        self.assertTrue(Holiday.is_working_day(self.comp_5day, date(2026, 2, 16)))

    def test_working_days_in_month_calculation(self):
        # January 2026: 31 days
        # 5 Saturdays + 4 Sundays = 9 weekend days
        # 1 mandatory holiday (Jan 26 Republic Day)
        # Expected working days = 31 - 9 - 1 = 21 working days
        working_days = Holiday.get_working_days_in_month(self.comp_5day, 2026, 1)
        self.assertEqual(working_days, 21)


class HolidayViewsAndRBACSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.comp_a = Company.objects.create(name='Holiday Alpha', code='HALPHA')
        self.comp_b = Company.objects.create(name='Holiday Beta', code='HBETA')

        self.hr_user = User.objects.create_user(
            username='hr_holiday', password='Password@123', email='hr@halpha.com', role=User.Role.HR_ADMIN
        )
        self.hr_emp = Employee.objects.create(
            user=self.hr_user,
            employee_id='HA-HR001',
            company=self.comp_a,
            first_name='Kavita',
            last_name='Nair',
            email='kavita@halpha.com',
            phone='+91 91234 56789'
        )

        self.hol_a = Holiday.objects.create(
            company=self.comp_a,
            name='Alpha Founders Day',
            date=date(2026, 5, 10),
            holiday_type=Holiday.HolidayType.COMPANY_EVENT
        )
        self.hol_b = Holiday.objects.create(
            company=self.comp_b,
            name='Beta Innovation Day',
            date=date(2026, 6, 15),
            holiday_type=Holiday.HolidayType.COMPANY_EVENT
        )

    def test_multi_company_isolation_on_holiday_list(self):
        """HR of Company Alpha must only see Alpha's holidays."""
        self.client.login(username='hr_holiday', password='Password@123')
        response = self.client.get(reverse('holidays:list'))
        self.assertEqual(response.status_code, 200)

        # Alpha holiday visible
        self.assertContains(response, 'Alpha Founders Day')
        # Beta holiday NOT visible
        self.assertNotContains(response, 'Beta Innovation Day')

    def test_calendar_grid_view_renders(self):
        """Calendar view renders successfully with company and month context."""
        self.client.login(username='hr_holiday', password='Password@123')
        response = self.client.get(reverse('holidays:calendar') + '?year=2026&month=5')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'May 2026')
        self.assertContains(response, 'Alpha Founders Day')

    def test_holiday_create_and_edit_workflow(self):
        """HR can create and edit a holiday."""
        self.client.login(username='hr_holiday', password='Password@123')

        # 1. Create Holiday
        create_data = {
            'company': self.comp_a.pk,
            'name': 'Corporate Milestone Day',
            'date': '2026-07-20',
            'holiday_type': Holiday.HolidayType.MANDATORY,
            'is_optional': False,
            'description': 'Celebration of 10 years in business',
        }
        res_create = self.client.post(reverse('holidays:create'), create_data, follow=True)
        self.assertEqual(res_create.status_code, 200)
        self.assertTrue(Holiday.objects.filter(name='Corporate Milestone Day').exists())

        new_h = Holiday.objects.get(name='Corporate Milestone Day')

        # 2. Edit Holiday
        edit_data = {
            'company': self.comp_a.pk,
            'name': 'Corporate Milestone Day (Updated)',
            'date': '2026-07-20',
            'holiday_type': Holiday.HolidayType.MANDATORY,
            'is_optional': False,
            'description': 'Updated milestone gala celebration',
        }
        res_edit = self.client.post(reverse('holidays:edit', args=[new_h.pk]), edit_data, follow=True)
        self.assertEqual(res_edit.status_code, 200)
        new_h.refresh_from_db()
        self.assertEqual(new_h.name, 'Corporate Milestone Day (Updated)')

    def test_api_holidays_json_response(self):
        """API endpoint returns JSON array of holidays."""
        self.client.login(username='hr_holiday', password='Password@123')
        response = self.client.get(reverse('holidays:api') + '?year=2026')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertGreaterEqual(len(data['holidays']), 1)
        self.assertEqual(data['holidays'][0]['title'], 'Alpha Founders Day')
