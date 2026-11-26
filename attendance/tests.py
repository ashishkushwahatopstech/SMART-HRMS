from decimal import Decimal
from datetime import datetime, date, time, timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from companies.models import Company
from employees.models import Employee, Department
from shifts.models import Shift
from attendance.models import Attendance, AttendanceAuditLog, ManualPunchRequest


class AttendanceCalculationAndPunctualityTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Attendance Corp', code='ATC')
        self.shift_8h = Shift.objects.create(
            company=self.company,
            name='Standard Day',
            start_time=time(9, 0),
            end_time=time(17, 0),
            grace_period_minutes=15,
            total_expected_hours=Decimal('8.00'),
            overtime_eligibility=True
        )
        self.shift_night = Shift.objects.create(
            company=self.company,
            name='Overnight Shift',
            start_time=time(22, 0),
            end_time=time(6, 0),
            is_overnight=True,
            grace_period_minutes=15,
            total_expected_hours=Decimal('8.00'),
            overtime_eligibility=True
        )
        self.employee = Employee.objects.create(
            employee_id='ATC-EMP001',
            company=self.company,
            first_name='Rohan',
            last_name='Sharma',
            email='rohan@atc.com',
            phone='+91 98888 11111',
            assigned_shift=self.shift_8h,
            monthly_salary=Decimal('50000.00')
        )

    def test_standard_work_hours_and_present_status(self):
        """Full 8-hour shift on time should yield 8.00 hrs, 0 OT, and PRESENT status."""
        test_date = date(2026, 11, 24)
        check_in = timezone.make_aware(datetime(2026, 11, 24, 9, 0))
        check_out = timezone.make_aware(datetime(2026, 11, 24, 17, 0))

        att = Attendance.objects.create(
            employee=self.employee,
            date=test_date,
            check_in_time=check_in,
            check_out_time=check_out
        )
        self.assertEqual(att.total_working_hours, Decimal('8.00'))
        self.assertEqual(att.overtime_hours, Decimal('0.00'))
        self.assertFalse(att.is_late)
        self.assertFalse(att.is_early_departure)
        self.assertEqual(att.status, Attendance.AttendanceStatus.PRESENT)

    def test_overtime_calculation(self):
        """Working from 09:00 to 19:30 on an 8-hour shift should yield 10.50 hrs & 2.50 hrs OT."""
        test_date = date(2026, 11, 24)
        check_in = timezone.make_aware(datetime(2026, 11, 24, 9, 0))
        check_out = timezone.make_aware(datetime(2026, 11, 24, 19, 30))

        att = Attendance.objects.create(
            employee=self.employee,
            date=test_date,
            check_in_time=check_in,
            check_out_time=check_out
        )
        self.assertEqual(att.total_working_hours, Decimal('10.50'))
        self.assertEqual(att.overtime_hours, Decimal('2.50'))

    def test_attendance_lunch_break_deduction(self):
        """Working from 09:00 to 18:00 with 1 hour lunch (13:00 to 14:00) yields 8.00 net working hours."""
        test_date = date(2026, 11, 24)
        check_in = timezone.make_aware(datetime(2026, 11, 24, 9, 0))
        lunch_out = timezone.make_aware(datetime(2026, 11, 24, 13, 0))
        lunch_in = timezone.make_aware(datetime(2026, 11, 24, 14, 0))
        check_out = timezone.make_aware(datetime(2026, 11, 24, 18, 0))

        att = Attendance.objects.create(
            employee=self.employee,
            date=test_date,
            check_in_time=check_in,
            lunch_start_time=lunch_out,
            lunch_end_time=lunch_in,
            check_out_time=check_out
        )
        self.assertEqual(att.total_lunch_duration_minutes, 60)
        # Gross = 9.00 hrs, Lunch = 1.00 hr, Net = 8.00 hrs
        self.assertEqual(att.total_working_hours, Decimal('8.00'))
        self.assertEqual(att.overtime_hours, Decimal('0.00'))

    def test_half_day_threshold(self):
        """Working 3.5 hours on an 8-hour shift (< 4h threshold) must be flagged as Half Day."""
        test_date = date(2026, 11, 24)
        check_in = timezone.make_aware(datetime(2026, 11, 24, 9, 0))
        check_out = timezone.make_aware(datetime(2026, 11, 24, 12, 30))

        att = Attendance.objects.create(
            employee=self.employee,
            date=test_date,
            check_in_time=check_in,
            check_out_time=check_out
        )
        self.assertEqual(att.total_working_hours, Decimal('3.50'))
        self.assertEqual(att.status, Attendance.AttendanceStatus.HALF_DAY)

    def test_late_arrival_with_grace_period(self):
        """Check-in at 09:12 is within 15m grace (On Time); at 09:35 exceeds grace (Late)."""
        test_date = date(2026, 11, 24)

        # 1. Within grace (09:10)
        att_on_time = Attendance.objects.create(
            employee=self.employee,
            date=test_date,
            check_in_time=timezone.make_aware(datetime(2026, 11, 24, 9, 10)),
            check_out_time=timezone.make_aware(datetime(2026, 11, 24, 17, 10))
        )
        self.assertFalse(att_on_time.is_late)
        self.assertEqual(att_on_time.late_minutes, 0)

        # 2. Past grace (09:35)
        att_on_time.delete()
        att_late = Attendance.objects.create(
            employee=self.employee,
            date=test_date,
            check_in_time=timezone.make_aware(datetime(2026, 11, 24, 9, 35)),
            check_out_time=timezone.make_aware(datetime(2026, 11, 24, 17, 35))
        )
        self.assertTrue(att_late.is_late)
        self.assertEqual(att_late.late_minutes, 35)
        self.assertEqual(att_late.status, Attendance.AttendanceStatus.LATE)

    def test_early_departure(self):
        """Leaving at 16:15 for a 17:00 shift end must flag early departure of 45 mins."""
        test_date = date(2026, 11, 24)
        att = Attendance.objects.create(
            employee=self.employee,
            date=test_date,
            check_in_time=timezone.make_aware(datetime(2026, 11, 24, 9, 0)),
            check_out_time=timezone.make_aware(datetime(2026, 11, 24, 16, 15))
        )
        self.assertTrue(att.is_early_departure)
        self.assertEqual(att.early_departure_minutes, 45)

    def test_cross_midnight_night_shift(self):
        """Check-in at 22:00 on 24th, check-out at 06:00 on 25th must evaluate smoothly."""
        test_date = date(2026, 11, 24)
        check_in = timezone.make_aware(datetime(2026, 11, 24, 22, 0))
        check_out = timezone.make_aware(datetime(2026, 11, 25, 6, 0))

        att = Attendance.objects.create(
            employee=self.employee,
            shift=self.shift_night,
            date=test_date,
            check_in_time=check_in,
            check_out_time=check_out
        )
        self.assertEqual(att.total_working_hours, Decimal('8.00'))
        self.assertFalse(att.is_late)
        self.assertFalse(att.is_early_departure)
        self.assertEqual(att.status, Attendance.AttendanceStatus.PRESENT)


class AttendanceViewsAndSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.comp_a = Company.objects.create(name='Alpha Solutions', code='ALPHA')
        self.comp_b = Company.objects.create(name='Beta Systems', code='BETA')

        self.hr_user = User.objects.create_user(
            username='hr_alpha', password='Password@123', email='hr@alpha.com', role=User.Role.HR_ADMIN
        )
        self.emp_user = User.objects.create_user(
            username='emp_alpha', password='Password@123', email='emp@alpha.com', role=User.Role.EMPLOYEE
        )

        self.emp_a = Employee.objects.create(
            user=self.emp_user,
            employee_id='ALPHA-EMP001',
            company=self.comp_a,
            first_name='Vikram',
            last_name='Nair',
            email='emp@alpha.com',
            phone='+91 99999 11111',
            monthly_salary=Decimal('40000.00')
        )
        self.hr_emp = Employee.objects.create(
            user=self.hr_user,
            employee_id='ALPHA-HR001',
            company=self.comp_a,
            first_name='Sonia',
            last_name='Mehta',
            email='hr@alpha.com',
            phone='+91 99999 22222',
            monthly_salary=Decimal('65000.00')
        )

        self.emp_b = Employee.objects.create(
            employee_id='BETA-EMP001',
            company=self.comp_b,
            first_name='Karan',
            last_name='Johar',
            email='karan@beta.com',
            phone='+91 99999 33333',
            monthly_salary=Decimal('50000.00')
        )

        # Create attendance records
        self.att_a = Attendance.objects.create(
            employee=self.emp_a,
            company=self.comp_a,
            date=date(2026, 11, 24),
            check_in_time=timezone.make_aware(datetime(2026, 11, 24, 9, 0)),
            check_out_time=timezone.make_aware(datetime(2026, 11, 24, 17, 0))
        )
        self.att_b = Attendance.objects.create(
            employee=self.emp_b,
            company=self.comp_b,
            date=date(2026, 11, 24),
            check_in_time=timezone.make_aware(datetime(2026, 11, 24, 9, 0)),
            check_out_time=timezone.make_aware(datetime(2026, 11, 24, 17, 0))
        )

    def test_multi_company_isolation(self):
        """HR of Company Alpha cannot see Company Beta's attendance record."""
        self.client.login(username='hr_alpha', password='Password@123')
        response = self.client.get(reverse('attendance:list'))
        self.assertEqual(response.status_code, 200)

        # Alpha employee record is visible
        self.assertContains(response, 'Vikram Nair')
        # Beta employee record MUST NOT be visible
        self.assertNotContains(response, 'Karan Johar')

    def test_attendance_list_view_modes(self):
        """Attendance list view supports log, by_date, and by_employee modes."""
        self.client.login(username='hr_alpha', password='Password@123')

        # 1. Log view (default)
        res_log = self.client.get(reverse('attendance:list') + '?view=log')
        self.assertEqual(res_log.status_code, 200)
        self.assertContains(res_log, 'Vikram Nair')
        self.assertContains(res_log, 'slide-detail-')

        # 2. By Date view
        res_date = self.client.get(reverse('attendance:list') + '?view=by_date')
        self.assertEqual(res_date.status_code, 200)
        self.assertContains(res_date, 'Vikram Nair')
        self.assertContains(res_date, 'date-roster-')

        # 3. By Employee view
        res_emp = self.client.get(reverse('attendance:list') + '?view=by_employee')
        self.assertEqual(res_emp.status_code, 200)
        self.assertContains(res_emp, 'Vikram Nair')
        self.assertContains(res_emp, 'Attendance History')

    def test_attendance_list_clever_lunch_display(self):
        """Attendance list cleanly displays lunch break without interrupting punch flow."""
        self.client.login(username='hr_alpha', password='Password@123')
        self.att_a.lunch_start_time = timezone.make_aware(datetime(2026, 11, 24, 13, 0))
        self.att_a.lunch_end_time = timezone.make_aware(datetime(2026, 11, 24, 13, 45))
        self.att_a.total_lunch_duration_minutes = 45
        self.att_a.save()

        res = self.client.get(reverse('attendance:list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '45m')
        self.assertContains(res, 'punch-lunch-pill')

    def test_employee_privacy_safeguard(self):
        """Regular employee can view own record, but cannot view peer records."""
        self.client.login(username='emp_alpha', password='Password@123')

        # Can view own detail
        res_own = self.client.get(reverse('attendance:detail', args=[self.att_a.pk]))
        self.assertEqual(res_own.status_code, 200)
        self.assertContains(res_own, 'Vikram Nair')

        # Blocked from viewing Company B's record
        res_other = self.client.get(reverse('attendance:detail', args=[self.att_b.pk]))
        self.assertEqual(res_other.status_code, 302)

    def test_self_check_in_and_check_out_workflow(self):
        """
        Direct manual web punch is disabled for regular employees (they must use camera).
        Managers and HR admins are permitted to perform web check-in.
        """
        self.client.login(username='emp_alpha', password='Password@123')

        # 1. Regular employee is BLOCKED from manual web punch
        res_in = self.client.post(reverse('attendance:self_check_in_out'), {'notes': 'Office desk'}, follow=True)
        self.assertEqual(res_in.status_code, 200)
        self.assertContains(res_in, "Direct manual web punch is disabled for employees")

        # 2. HR Admin / Manager is ALLOWED to punch via web
        self.client.login(username='hr_alpha', password='Password@123')
        # Delete today's attendance for HR employee to test fresh punch
        Attendance.objects.filter(employee=self.hr_emp, date=timezone.now().date()).delete()

        res_hr_in = self.client.post(reverse('attendance:self_check_in_out'), {'notes': 'HR desk'}, follow=True)
        self.assertEqual(res_hr_in.status_code, 200)
        self.assertContains(res_hr_in, "Check-In recorded at")

        hr_att = Attendance.objects.filter(employee=self.hr_emp, date=timezone.now().date()).first()
        self.assertIsNotNone(hr_att)
        self.assertIsNotNone(hr_att.check_in_time)

    def test_manual_punch_request_submission_by_employee(self):
        """Employee can submit a manual punch request for a past missed date."""
        self.client.login(username='emp_alpha', password='Password@123')
        past_date = (timezone.now() - timedelta(days=2)).date()

        post_data = {
            'date': str(past_date),
            'punch_type': ManualPunchRequest.PunchType.BOTH,
            'check_in_time': '09:15',
            'check_out_time': '17:30',
            'reason': 'Technical glitch with mobile camera browser',
        }
        response = self.client.post(reverse('attendance:request_create'), post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'submitted successfully')

        req = ManualPunchRequest.objects.filter(employee=self.emp_a, date=past_date).first()
        self.assertIsNotNone(req)
        self.assertEqual(req.status, ManualPunchRequest.RequestStatus.PENDING)
        self.assertEqual(req.check_in_time, time(9, 15))
        self.assertEqual(req.check_out_time, time(17, 30))

        # Test future date rejection
        future_date = (timezone.now() + timedelta(days=2)).date()
        post_future = {
            'date': str(future_date),
            'punch_type': ManualPunchRequest.PunchType.BOTH,
            'check_in_time': '09:00',
            'check_out_time': '17:00',
            'reason': 'Future date test',
        }
        res_future = self.client.post(reverse('attendance:request_create'), post_future, follow=True)
        self.assertContains(res_future, 'cannot request attendance regularization for a future date')

    def test_manual_punch_request_approval_by_manager_or_hr(self):
        """HR/Manager can approve request, which creates the Attendance record and audit trail."""
        past_date = (timezone.now() - timedelta(days=3)).date()
        punch_req = ManualPunchRequest.objects.create(
            employee=self.emp_a,
            company=self.comp_a,
            date=past_date,
            punch_type=ManualPunchRequest.PunchType.BOTH,
            check_in_time=time(9, 0),
            check_out_time=time(17, 30),
            reason='Forgot to punch on return from client demo'
        )

        self.client.login(username='hr_alpha', password='Password@123')
        res_approve = self.client.post(
            reverse('attendance:request_approve', args=[punch_req.pk]),
            {'review_remarks': 'Verified with team lead'},
            follow=True
        )
        self.assertEqual(res_approve.status_code, 200)
        self.assertContains(res_approve, 'Approved manual punch request')

        punch_req.refresh_from_db()
        self.assertEqual(punch_req.status, ManualPunchRequest.RequestStatus.APPROVED)
        self.assertEqual(punch_req.reviewed_by, self.hr_user)

        # Verify Attendance record was generated
        att = Attendance.objects.filter(employee=self.emp_a, date=past_date).first()
        self.assertIsNotNone(att)
        self.assertEqual(att.verification_method, Attendance.VerificationMethod.ADMIN_ADJUSTMENT)
        self.assertEqual(att.total_working_hours, Decimal('8.50'))

        # Verify audit log exists
        audit_log = AttendanceAuditLog.objects.filter(attendance=att).first()
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.changed_by, self.hr_user)

    def test_manual_punch_request_rejection(self):
        """HR/Manager can reject request with justification remarks."""
        past_date = (timezone.now() - timedelta(days=4)).date()
        punch_req = ManualPunchRequest.objects.create(
            employee=self.emp_a,
            company=self.comp_a,
            date=past_date,
            punch_type=ManualPunchRequest.PunchType.BOTH,
            check_in_time=time(9, 0),
            check_out_time=time(17, 0),
            reason='No valid proof of work'
        )

        self.client.login(username='hr_alpha', password='Password@123')
        res_reject = self.client.post(
            reverse('attendance:request_reject', args=[punch_req.pk]),
            {'review_remarks': 'Unapproved absence on that date'},
            follow=True
        )
        self.assertEqual(res_reject.status_code, 200)

        punch_req.refresh_from_db()
        self.assertEqual(punch_req.status, ManualPunchRequest.RequestStatus.REJECTED)
        self.assertEqual(punch_req.review_remarks, 'Unapproved absence on that date')

        # Attendance record MUST NOT exist
        att = Attendance.objects.filter(employee=self.emp_a, date=past_date).first()
        self.assertIsNone(att)

    def test_manual_attendance_adjustment_audit_log(self):
        """HR manual edit must record an AttendanceAuditLog with reason and user stamp."""
        self.client.login(username='hr_alpha', password='Password@123')

        post_data = {
            'employee': self.emp_a.pk,
            'date': '2026-11-24',
            'status': Attendance.AttendanceStatus.PRESENT,
            'verification_method': Attendance.VerificationMethod.ADMIN_ADJUSTMENT,
            'check_in_time': '2026-11-24T09:00',
            'check_out_time': '2026-11-24T18:00',
            'adjustment_reason': 'Employee verified biometric machine did not register punch card',
        }
        response = self.client.post(reverse('attendance:edit', args=[self.att_a.pk]), post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify audit log was created
        audit_log = AttendanceAuditLog.objects.filter(attendance=self.att_a).first()
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.changed_by, self.hr_user)
        self.assertIn('biometric machine did not register', audit_log.reason)


class BiometricFaceRecognitionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.company_a = Company.objects.create(name='Biometric Alpha', code='BIOA')
        self.company_b = Company.objects.create(name='Biometric Beta', code='BIOB')

        self.hr_user = User.objects.create_user(
            username='bio_hr', password='Password@123', email='biohr@alpha.com', role=User.Role.HR_ADMIN
        )
        self.emp_a = Employee.objects.create(
            user=self.hr_user,
            employee_id='BIOA-EMP001',
            company=self.company_a,
            first_name='Aarav',
            last_name='Deshmukh',
            email='aarav@bioa.com',
            phone='+91 91111 22222',
            monthly_salary=Decimal('50000.00')
        )
        self.emp_b = Employee.objects.create(
            employee_id='BIOB-EMP001',
            company=self.company_b,
            first_name='Kavita',
            last_name='Iyer',
            email='kavita@biob.com',
            phone='+91 92222 33333',
            monthly_salary=Decimal('55000.00')
        )

    def test_face_kiosk_view_renders(self):
        """Kiosk view renders successfully for authenticated user."""
        self.client.login(username='bio_hr', password='Password@123')
        response = self.client.get(reverse('attendance:face_kiosk'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Face Recognition Attendance')
        self.assertContains(response, 'Biometric Alpha')

    def test_enroll_face_page_company_isolation(self):
        """HR of Company A can access Company A employee enrollment, but blocked from Company B."""
        self.client.login(username='bio_hr', password='Password@123')

        # Allowed for Company A employee
        res_a = self.client.get(reverse('attendance:enroll_face', args=[self.emp_a.pk]))
        self.assertEqual(res_a.status_code, 200)
        self.assertContains(res_a, 'Aarav Deshmukh')

        # BLOCKED for Company B employee
        res_b = self.client.get(reverse('attendance:enroll_face', args=[self.emp_b.pk]))
        self.assertEqual(res_b.status_code, 302)
        self.assertEqual(res_b.url, reverse('employees:list'))

    def test_recognize_api_rejects_empty_image(self):
        """Recognition API returns matched: False on empty payload when authenticated as HR."""
        self.client.login(username='bio_hr', password='Password@123')
        response = self.client.post(
            reverse('attendance:api_recognize_face'),
            data='{"image": ""}',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['matched'])

    def test_recognize_api_access_control(self):
        """Recognition API requires authentication and enforces self-punch enrollment rules."""
        # Unauthenticated request rejected
        response_anon = self.client.post(
            reverse('attendance:api_recognize_face'),
            data='{"image": ""}',
            content_type='application/json'
        )
        self.assertEqual(response_anon.status_code, 401)

        # Logged in as regular employee without employee profile -> 403
        emp_user = User.objects.create_user(
            username='bio_emp', password='Password@123', email='emp@alpha.com', role=User.Role.EMPLOYEE
        )
        self.client.login(username='bio_emp', password='Password@123')
        response_emp = self.client.post(
            reverse('attendance:api_recognize_face'),
            data='{"image": ""}',
            content_type='application/json'
        )
        self.assertEqual(response_emp.status_code, 403)

        # Employee with profile but not enrolled -> NOT_ENROLLED notification
        self.emp_b.user = emp_user
        self.emp_b.face_registration_status = False
        self.emp_b.face_samples_count = 0
        self.emp_b.save()

        response_not_enrolled = self.client.post(
            reverse('attendance:api_recognize_face'),
            data='{"image": ""}',
            content_type='application/json'
        )
        self.assertEqual(response_not_enrolled.status_code, 200)
        self.assertEqual(response_not_enrolled.json().get('security_status'), 'NOT_ENROLLED')

    def test_reset_face_data_clears_biometrics(self):
        """Reset action clears samples and resets face_registration_status."""
        self.client.login(username='bio_hr', password='Password@123')

        self.emp_a.face_registration_status = True
        self.emp_a.face_samples_count = 5
        self.emp_a.save()

        response = self.client.get(reverse('attendance:api_reset_face_data', args=[self.emp_a.pk]))
        self.assertEqual(response.status_code, 302)

        self.emp_a.refresh_from_db()
        self.assertFalse(self.emp_a.face_registration_status)
        self.assertEqual(self.emp_a.face_samples_count, 0)

    def test_hr_admin_can_delete_attendance_and_mints_blockchain_block(self):
        """HR Admin can delete attendance; an immutable cryptographic audit block is minted."""
        self.client.login(username='bio_hr', password='Password@123')

        att = Attendance.objects.create(
            employee=self.emp_a,
            company=self.company_a,
            date=date(2026, 11, 22),
            status=Attendance.AttendanceStatus.PRESENT
        )

        # Deleting requires mandatory reason
        del_res = self.client.post(
            reverse('attendance:delete', args=[att.pk]),
            data={'reason': 'Approved duplicate punch removal'}
        )
        self.assertEqual(del_res.status_code, 302)
        self.assertFalse(Attendance.objects.filter(pk=att.pk).exists())

        # Verify cryptographic blockchain ledger entry
        log_entry = AttendanceAuditLog.objects.filter(
            company=self.company_a,
            action='Attendance Record Deleted'
        ).first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.reason, 'Approved duplicate punch removal')
        self.assertTrue(len(log_entry.block_hash) == 64)
        self.assertIn('employee_name', log_entry.snapshot)
        self.assertEqual(log_entry.snapshot['employee_name'], self.emp_a.get_full_name())

    def test_campus_audit_ledger_publicly_visible_to_campus_employees(self):
        """All authenticated campus employees can view the audit ledger; outer public is blocked."""
        # 1. Outer public (unauthenticated) is blocked
        anon_res = self.client.get(reverse('attendance:audit_ledger'))
        self.assertEqual(anon_res.status_code, 302)
        self.assertIn(reverse('accounts:login'), anon_res.url)

        # 2. Campus internal employee can access and view the ledger
        emp_user = User.objects.create_user(
            username='bio_emp', password='Password@123', email='bioemp@alpha.com', role=User.Role.EMPLOYEE
        )
        Employee.objects.create(
            user=emp_user,
            employee_id='BIOA-EMP009',
            company=self.company_a,
            first_name='Campus',
            last_name='Staff',
            email='bioemp@alpha.com',
            phone='+91 94444 55555'
        )
        self.client.login(username='bio_emp', password='Password@123')
        emp_res = self.client.get(reverse('attendance:audit_ledger'))
        self.assertEqual(emp_res.status_code, 200)
        self.assertContains(emp_res, 'Campus Attendance Audit Ledger')

