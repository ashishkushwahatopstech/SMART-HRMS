from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import secrets


class User(AbstractUser):
    """
    Custom User Model for Smart HRMS.
    Supports role-based authentication and access control:
    1. Super Admin
    2. HR Admin
    3. Manager
    4. Employee
    """
    class Role(models.TextChoices):
        SUPER_ADMIN = 'super_admin', 'Super Admin'
        HR_ADMIN = 'hr_admin', 'HR Admin'
        MANAGER = 'manager', 'Manager'
        EMPLOYEE = 'employee', 'Employee'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.EMPLOYEE,
        help_text='User role for permission and access control'
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text='Contact phone number'
    )
    avatar = models.ImageField(
        upload_to='avatars/',
        blank=True,
        null=True,
        help_text='Profile picture'
    )
    bio = models.TextField(
        blank=True,
        null=True,
        help_text='Short personal or professional bio'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-date_joined']

    def __str__(self):
        full_name = self.get_full_name()
        if full_name:
            return f"{full_name} ({self.username}) - {self.get_role_display()}"
        return f"{self.username} - {self.get_role_display()}"

    @property
    def is_super_admin(self):
        return self.is_superuser or self.role == self.Role.SUPER_ADMIN

    @property
    def is_hr_admin(self):
        return self.is_super_admin or self.role == self.Role.HR_ADMIN

    @property
    def is_manager_user(self):
        return self.role == self.Role.MANAGER

    @property
    def is_employee_user(self):
        return self.role == self.Role.EMPLOYEE

    def get_display_name(self):
        full_name = self.get_full_name()
        return full_name if full_name else self.username

    def get_role_badge_class(self):
        """Returns Bootstrap 5 color class based on role"""
        mapping = {
            self.Role.SUPER_ADMIN: 'bg-danger',
            self.Role.HR_ADMIN: 'bg-primary',
            self.Role.MANAGER: 'bg-info text-dark',
            self.Role.EMPLOYEE: 'bg-success',
        }
        return mapping.get(self.role, 'bg-secondary')

    def save(self, *args, **kwargs):
        # Ensure superuser always has super_admin role and staff permissions
        if self.is_superuser:
            self.role = self.Role.SUPER_ADMIN
            self.is_staff = True
        elif self.role in [self.Role.HR_ADMIN]:
            self.is_staff = True
        super().save(*args, **kwargs)


class EmailOTP(models.Model):
    """
    Cryptographically secure 6-digit Email OTP for user verification,
    password reset, and two-factor authentication.
    """
    class Purpose(models.TextChoices):
        PASSWORD_RESET = 'password_reset', 'Password Reset'
        LOGIN_2FA = 'login_2fa', 'Login Two-Factor Auth'
        EMAIL_VERIFICATION = 'email_verification', 'Email Verification'

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='email_otps'
    )
    otp_code = models.CharField(max_length=6)
    purpose = models.CharField(
        max_length=25,
        choices=Purpose.choices,
        default=Purpose.PASSWORD_RESET
    )
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Email OTP'
        verbose_name_plural = 'Email OTPs'
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP for {self.user.username} ({self.purpose})"

    @property
    def is_valid(self):
        return not self.is_used and timezone.now() <= self.expires_at

    @classmethod
    def generate_otp(cls, user, purpose=Purpose.PASSWORD_RESET, expiry_minutes=10):
        """
        Generates a 6-digit secure random OTP, marks old unused OTPs as used,
        and creates a new EmailOTP instance.
        """
        # Invalidate old unused OTPs for this user and purpose
        cls.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)

        code = ''.join(secrets.choice('0123456789') for _ in range(6))
        expires_at = timezone.now() + timezone.timedelta(minutes=expiry_minutes)
        return cls.objects.create(
            user=user,
            otp_code=code,
            purpose=purpose,
            expires_at=expires_at
        )

