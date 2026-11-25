from django.test import TestCase, Client
from django.urls import reverse
from django.core.management import call_command
from accounts.models import User, EmailOTP
from services.email_service import get_site_url, send_test_email, send_otp_email
from django.utils import timezone
from datetime import timedelta
from accounts.decorators import role_required, super_admin_required, hr_required, manager_required
from django.http import HttpResponse


class UserModelTests(TestCase):
    """Tests for custom User model and role-based helper methods."""

    def test_create_default_employee(self):
        user = User.objects.create_user(
            username='johndoe',
            password='Password@123',
            email='john@example.com',
            first_name='John',
            last_name='Doe'
        )
        self.assertEqual(user.role, User.Role.EMPLOYEE)
        self.assertTrue(user.is_employee_user)
        self.assertFalse(user.is_manager_user)
        self.assertFalse(user.is_hr_admin)
        self.assertFalse(user.is_super_admin)
        self.assertEqual(user.get_display_name(), 'John Doe')
        self.assertEqual(user.get_role_badge_class(), 'bg-success')

    def test_create_super_admin(self):
        superuser = User.objects.create_superuser(
            username='adminuser',
            password='AdminPassword@123',
            email='admin@example.com'
        )
        self.assertTrue(superuser.is_superuser)
        self.assertTrue(superuser.is_staff)
        self.assertEqual(superuser.role, User.Role.SUPER_ADMIN)
        self.assertTrue(superuser.is_super_admin)
        self.assertTrue(superuser.is_hr_admin)
        self.assertEqual(superuser.get_role_badge_class(), 'bg-danger')

    def test_hr_admin_role_properties(self):
        hr_user = User.objects.create_user(
            username='hruser',
            password='HrPassword@123',
            role=User.Role.HR_ADMIN
        )
        self.assertTrue(hr_user.is_hr_admin)
        self.assertTrue(hr_user.is_staff)
        self.assertFalse(hr_user.is_super_admin)
        self.assertEqual(hr_user.get_role_badge_class(), 'bg-primary')

    def test_manager_role_properties(self):
        manager = User.objects.create_user(
            username='manageruser',
            password='ManagerPassword@123',
            role=User.Role.MANAGER
        )
        self.assertTrue(manager.is_manager_user)
        self.assertFalse(manager.is_hr_admin)
        self.assertFalse(manager.is_employee_user)
        self.assertEqual(manager.get_role_badge_class(), 'bg-info text-dark')


class AuthenticationViewTests(TestCase):
    """Tests for login, logout, profile, and dashboard authentication."""

    def setUp(self):
        self.client = Client()
        self.password = 'TestPass@123'
        self.user = User.objects.create_user(
            username='testemp',
            password=self.password,
            email='emp@example.com',
            first_name='Test',
            last_name='Employee',
            role=User.Role.EMPLOYEE
        )

    def test_login_page_renders(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')
        self.assertContains(response, 'Sign In to Your Workspace')

    def test_login_success(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'testemp',
            'password': self.password,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)
        self.assertTemplateUsed(response, 'dashboard/index.html')

    def test_login_invalid_credentials(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'testemp',
            'password': 'WrongPassword!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid username or password')

    def test_logout_redirects_to_login(self):
        self.client.login(username='testemp', password=self.password)
        response = self.client.get(reverse('accounts:logout'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')
        self.assertFalse(response.context['user'].is_authenticated)

    def test_unauthenticated_dashboard_redirects_to_login(self):
        response = self.client.get(reverse('dashboard:index'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_authenticated_dashboard_access(self):
        self.client.login(username='testemp', password=self.password)
        response = self.client.get(reverse('dashboard:index'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboard/index.html')
        self.assertContains(response, 'Test Employee')

    def test_profile_view_update(self):
        self.client.login(username='testemp', password=self.password)
        response = self.client.post(reverse('accounts:profile'), {
            'first_name': 'UpdatedFirst',
            'last_name': 'UpdatedLast',
            'email': 'updated@example.com',
            'phone': '+91 91234 56789',
            'bio': 'Updated professional biography.',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'UpdatedFirst')
        self.assertEqual(self.user.last_name, 'UpdatedLast')
        self.assertEqual(self.user.email, 'updated@example.com')
        self.assertEqual(self.user.phone, '+91 91234 56789')


class RoleAccessDecoratorTests(TestCase):
    """Tests for role-based authorization decorators."""

    def setUp(self):
        self.client = Client()
        self.employee = User.objects.create_user(
            username='emp', password='Pass@123', role=User.Role.EMPLOYEE
        )
        self.hr = User.objects.create_user(
            username='hr', password='Pass@123', role=User.Role.HR_ADMIN
        )
        self.admin = User.objects.create_superuser(
            username='admin', password='Pass@123'
        )

    def test_hr_required_decorator_blocks_employee(self):
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.messages.middleware import MessageMiddleware
        factory = RequestFactory()

        @hr_required
        def dummy_view(request):
            return HttpResponse("Authorized")

        # Employee request
        request = factory.get('/dummy/')
        SessionMiddleware(lambda req: None).process_request(request)
        MessageMiddleware(lambda req: None).process_request(request)
        request.user = self.employee
        response = dummy_view(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard:index'))

        # HR request
        request = factory.get('/dummy/')
        SessionMiddleware(lambda req: None).process_request(request)
        MessageMiddleware(lambda req: None).process_request(request)
        request.user = self.hr
        response = dummy_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "Authorized")

        # Super Admin request
        request = factory.get('/dummy/')
        SessionMiddleware(lambda req: None).process_request(request)
        MessageMiddleware(lambda req: None).process_request(request)
        request.user = self.admin
        response = dummy_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "Authorized")


class ManagementCommandTests(TestCase):
    """Tests that setup_phase1_demo executes and creates required demo entities."""

    def test_setup_phase1_demo_command(self):
        call_command('setup_phase1_demo')
        self.assertTrue(User.objects.filter(username='superadmin').exists())
        self.assertTrue(User.objects.filter(username='hradmin').exists())
        self.assertTrue(User.objects.filter(username='manager1').exists())
        self.assertTrue(User.objects.filter(username='employee1').exists())
        self.assertTrue(User.objects.filter(username='employee2').exists())


class EmailOTPandPasswordResetTests(TestCase):
    """
    Unit tests for 6-digit Email OTP generation, secure password reset,
    and Google SMTP dynamic URL service.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='ashish_test',
            password='OldPassword@123',
            email='ashishkushwaha88643@gmail.com',
            first_name='Ashish',
            last_name='Kushwaha',
            role=User.Role.EMPLOYEE
        )

    def test_email_otp_generation_and_invalidation(self):
        """OTP generation creates 6-digit code and invalidates older unused OTPs."""
        otp1 = EmailOTP.generate_otp(self.user, purpose=EmailOTP.Purpose.PASSWORD_RESET, expiry_minutes=10)
        self.assertEqual(len(otp1.otp_code), 6)
        self.assertTrue(otp1.otp_code.isdigit())
        self.assertTrue(otp1.is_valid)

        # Generating a second OTP must mark the previous one as used
        otp2 = EmailOTP.generate_otp(self.user, purpose=EmailOTP.Purpose.PASSWORD_RESET, expiry_minutes=10)
        otp1.refresh_from_db()
        self.assertTrue(otp1.is_used)
        self.assertFalse(otp1.is_valid)
        self.assertTrue(otp2.is_valid)

    def test_forgot_password_view_dispatches_otp_without_frontend_leak(self):
        """Submitting forgot password dispatches OTP email; code is NEVER sent to frontend."""
        response = self.client.post(
            reverse('accounts:forgot_password'),
            {'identity': 'ashish_test'},
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/verify_otp.html')

        # Verify OTP was saved in DB
        otp = EmailOTP.objects.filter(user=self.user, is_used=False).first()
        self.assertIsNotNone(otp)

        # SECURITY CHECK: OTP code must NOT appear in the response HTML or script
        self.assertNotContains(response, otp.otp_code)
        # Obfuscated email (e.g. a***3@gmail.com) is displayed instead
        self.assertContains(response, 'a***3@gmail.com')

    def test_verify_otp_view_success_and_password_update(self):
        """Entering correct OTP updates user password and authenticates user."""
        otp = EmailOTP.generate_otp(self.user, purpose=EmailOTP.Purpose.PASSWORD_RESET, expiry_minutes=10)

        # Set session as if coming from step 1
        session = self.client.session
        session['reset_user_id'] = self.user.id
        session['reset_masked_email'] = 'a***3@gmail.com'
        session.save()

        new_password = 'BrandNewSecurePass@2026'
        post_data = {
            'otp_code': otp.otp_code,
            'new_password': new_password,
            'confirm_password': new_password,
        }
        response = self.client.post(reverse('accounts:verify_otp'), post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboard/index.html')
        self.assertTrue(response.context['user'].is_authenticated)

        # Verify password actually changed in DB
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))

        # Verify OTP marked as used
        otp.refresh_from_db()
        self.assertTrue(otp.is_used)

    def test_verify_otp_view_rejects_invalid_code(self):
        """Entering incorrect OTP code is rejected without resetting password."""
        otp = EmailOTP.generate_otp(self.user, purpose=EmailOTP.Purpose.PASSWORD_RESET, expiry_minutes=10)

        session = self.client.session
        session['reset_user_id'] = self.user.id
        session.save()

        post_data = {
            'otp_code': '000000',  # Wrong code
            'new_password': 'NewPassword@123',
            'confirm_password': 'NewPassword@123',
        }
        response = self.client.post(reverse('accounts:verify_otp'), post_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid or expired verification code')

        # Password remains unchanged
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('OldPassword@123'))

    def test_verify_otp_view_rejects_expired_code(self):
        """Expired OTP code is rejected."""
        otp = EmailOTP.generate_otp(self.user, purpose=EmailOTP.Purpose.PASSWORD_RESET, expiry_minutes=10)
        # Simulate expiration
        otp.expires_at = timezone.now() - timedelta(minutes=1)
        otp.save()

        session = self.client.session
        session['reset_user_id'] = self.user.id
        session.save()

        post_data = {
            'otp_code': otp.otp_code,
            'new_password': 'NewPassword@123',
            'confirm_password': 'NewPassword@123',
        }
        response = self.client.post(reverse('accounts:verify_otp'), post_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid or expired verification code')

    def test_dynamic_site_url_resolution(self):
        """get_site_url extracts dynamic host and protocol from HTTP request."""
        from django.test import RequestFactory
        factory = RequestFactory()

        # Local development test
        req_local = factory.get('/', HTTP_HOST='10.27.5.77:8000')
        self.assertEqual(get_site_url(req_local), 'http://10.27.5.77:8000')

        # HTTPS production test
        req_prod = factory.get('/', HTTP_HOST='hrms.corporate.com', secure=True)
        self.assertEqual(get_site_url(req_prod), 'https://hrms.corporate.com')

        # Fallback when request is None
        self.assertTrue(len(get_site_url(None)) > 0)

