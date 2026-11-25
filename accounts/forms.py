from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    UserCreationForm,
    UserChangeForm,
    PasswordChangeForm,
)
from .models import User


class LoginForm(AuthenticationForm):
    """
    Bootstrap 5 styled login form with remember me option.
    """
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'Enter your username',
                'autocomplete': 'username',
                'id': 'id_username',
            }
        ),
        label='Username'
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'Enter your password',
                'autocomplete': 'current-password',
                'id': 'id_password',
            }
        ),
        label='Password'
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={
                'class': 'form-check-input',
                'id': 'remember_me'
            }
        ),
        label='Remember me on this device'
    )


class UserProfileForm(forms.ModelForm):
    """
    Form for users to edit their personal profile information.
    """
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'bio', 'avatar']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@company.com'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 98765 43210'}),
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'A brief description about yourself...'}),
            'avatar': forms.FileInput(attrs={'class': 'form-control'}),
        }


class CustomPasswordChangeForm(PasswordChangeForm):
    """
    Bootstrap 5 styled password change form.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})


class CustomUserCreationForm(UserCreationForm):
    """
    Form for creating new users in Django admin with custom fields.
    """
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'role', 'phone')


class CustomUserChangeForm(UserChangeForm):
    """
    Form for updating existing users in Django admin with custom fields.
    """
    class Meta(UserChangeForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'role', 'phone', 'avatar', 'bio', 'is_active', 'is_staff')


class ForgotPasswordForm(forms.Form):
    """
    Form to request a secure 6-digit email OTP for password reset.
    """
    identity = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Enter your username or registered email',
            'autocomplete': 'username',
            'autofocus': True,
        }),
        label='Username or Email Address'
    )


class VerifyOTPForm(forms.Form):
    """
    Form to verify the 6-digit email OTP and enter a new secure password.
    """
    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg text-center font-monospace',
            'placeholder': '••••••',
            'style': 'letter-spacing: 10px; font-size: 26px; font-weight: 700;',
            'autocomplete': 'one-time-code',
            'maxlength': '6',
            'autofocus': True,
        }),
        label='6-Digit Verification Code'
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Enter new password (min. 8 characters)',
            'autocomplete': 'new-password',
        }),
        label='New Password'
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Re-enter your new password',
            'autocomplete': 'new-password',
        }),
        label='Confirm New Password'
    )

    def clean(self):
        cleaned_data = super().clean()
        pw1 = cleaned_data.get('new_password')
        pw2 = cleaned_data.get('confirm_password')

        if pw1 and len(pw1) < 8:
            self.add_error('new_password', 'Password must be at least 8 characters long.')

        if pw1 and pw2 and pw1 != pw2:
            self.add_error('confirm_password', 'Passwords do not match. Please verify and re-type.')

        return cleaned_data


class SendTestEmailForm(forms.Form):
    """
    Form to send a test email to verify Google SMTP delivery.
    """
    recipient_email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'recipient@example.com',
        }),
        label='Recipient Email Address'
    )

