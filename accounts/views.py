from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from .models import User, EmailOTP
from .forms import (
    LoginForm,
    UserProfileForm,
    CustomPasswordChangeForm,
    ForgotPasswordForm,
    VerifyOTPForm,
    SendTestEmailForm,
)
from services.email_service import send_otp_email, send_test_email


def mask_email(email):
    """Safely masks an email address for privacy and security (e.g. j***e@domain.com)."""
    if not email or '@' not in email:
        return 'your registered email'
    try:
        name, domain = email.split('@')
        if len(name) <= 2:
            masked = name[0] + '***'
        else:
            masked = name[0] + '***' + name[-1]
        return f"{masked}@{domain}"
    except Exception:
        return 'your registered email'



def login_view(request):
    """
    Handles user login with custom role detection and friendly feedback.
    """
    if request.user.is_authenticated:
        return redirect('dashboard:index')

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)

            # Handle "Remember Me"
            if not form.cleaned_data.get('remember_me'):
                request.session.set_expiry(0)  # Browser close terminates session
            else:
                request.session.set_expiry(1209600)  # 2 weeks

            messages.success(
                request,
                f"Welcome back, {user.get_display_name()}! You are logged in as {user.get_role_display()}."
            )
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect('dashboard:index')
        else:
            messages.error(request, "Invalid username or password. Please try again.")
    else:
        form = LoginForm(request)

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    """
    Logs out the current user and redirects to login page.
    """
    if request.user.is_authenticated:
        username = request.user.get_display_name()
        logout(request)
        messages.info(request, f"Goodbye {username}. You have been securely logged out.")
    return redirect('accounts:login')


@login_required
def profile_view(request):
    """
    Allows the logged-in user to view and update their personal profile.
    """
    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile has been updated successfully.")
            return redirect('accounts:profile')
        else:
            messages.error(request, "Please correct the errors in the form below.")
    else:
        form = UserProfileForm(instance=request.user)

    return render(request, 'accounts/profile.html', {
        'form': form,
        'user': request.user
    })


@login_required
def change_password_view(request):
    """
    Allows the logged-in user to securely change their password.
    """
    if request.method == 'POST':
        form = CustomPasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            # Maintain user session so they don't get logged out
            update_session_auth_hash(request, user)
            messages.success(request, "Your password was successfully updated!")
            return redirect('accounts:profile')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CustomPasswordChangeForm(user=request.user)

    return render(request, 'accounts/change_password.html', {'form': form})


def forgot_password_view(request):
    """
    Step 1 of Password Reset:
    Accepts username or email, generates a cryptographically secure 6-digit OTP,
    and dispatches it via Google SMTP. The OTP code is NEVER sent to frontend.
    """
    if request.user.is_authenticated:
        return redirect('dashboard:index')

    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            identity = form.cleaned_data['identity'].strip()
            user = User.objects.filter(
                Q(username__iexact=identity) | Q(email__iexact=identity)
            ).first()

            if user and user.email:
                otp = EmailOTP.generate_otp(user, purpose=EmailOTP.Purpose.PASSWORD_RESET, expiry_minutes=10)
                # Dispatch OTP via Google SMTP
                send_otp_email(user, otp.otp_code, purpose="Password Reset", request=request)

                request.session['reset_user_id'] = user.id
                request.session['reset_masked_email'] = mask_email(user.email)

                messages.success(
                    request,
                    f"A 6-digit verification code has been dispatched to {mask_email(user.email)}. Please check your inbox."
                )
                return redirect('accounts:verify_otp')
            else:
                # Do not leak user existence, or guide them if account has no email
                if user and not user.email:
                    messages.error(
                        request,
                        "Your account has no registered email address on file. Please contact your HR administrator to update your profile."
                    )
                else:
                    # Generic response to prevent user enumeration
                    messages.info(
                        request,
                        "If an account matching that username or email exists in our system, a verification code has been sent. Please check your inbox."
                    )
    else:
        form = ForgotPasswordForm()

    return render(request, 'accounts/forgot_password.html', {'form': form})


def verify_otp_view(request):
    """
    Step 2 of Password Reset:
    Verifies the 6-digit code entered by user against the unexpired database token.
    On success, updates password, marks OTP as used, and logs the user in.
    """
    if request.user.is_authenticated:
        return redirect('dashboard:index')

    user_id = request.session.get('reset_user_id')
    masked_email = request.session.get('reset_masked_email', 'your email')

    if not user_id:
        messages.warning(request, "Please enter your username or email address first.")
        return redirect('accounts:forgot_password')

    user = get_object_or_404(User, pk=user_id)

    if request.method == 'POST':
        form = VerifyOTPForm(request.POST)
        if form.is_valid():
            entered_otp = form.cleaned_data['otp_code'].strip()
            new_password = form.cleaned_data['new_password']

            # Locate active unexpired OTP
            otp = EmailOTP.objects.filter(
                user=user,
                otp_code=entered_otp,
                purpose=EmailOTP.Purpose.PASSWORD_RESET,
                is_used=False,
                expires_at__gte=timezone.now()
            ).first()

            if otp:
                # Valid OTP! Update password securely
                user.set_password(new_password)
                user.save()

                # Mark OTP used
                otp.is_used = True
                otp.save()

                # Clear reset session
                request.session.pop('reset_user_id', None)
                request.session.pop('reset_masked_email', None)

                # Log user in directly
                login(request, user)
                messages.success(
                    request,
                    f"Your password has been successfully reset! Welcome back, {user.get_display_name()}."
                )
                return redirect('dashboard:index')
            else:
                form.add_error(
                    'otp_code',
                    "Invalid or expired verification code. Please check your inbox or request a new code."
                )
    else:
        form = VerifyOTPForm()

    return render(request, 'accounts/verify_otp.html', {
        'form': form,
        'masked_email': masked_email,
        'user': user,
    })


def resend_otp_view(request):
    """
    Resends a fresh 6-digit OTP code to the user's email during password reset.
    """
    user_id = request.session.get('reset_user_id')
    if not user_id:
        messages.warning(request, "Session expired. Please enter your username again.")
        return redirect('accounts:forgot_password')

    user = get_object_or_404(User, pk=user_id)
    if user.email:
        otp = EmailOTP.generate_otp(user, purpose=EmailOTP.Purpose.PASSWORD_RESET, expiry_minutes=10)
        send_otp_email(user, otp.otp_code, purpose="Password Reset", request=request)
        messages.success(request, f"A fresh verification code has been dispatched to {mask_email(user.email)}.")
    else:
        messages.error(request, "No email address found for this account.")

    return redirect('accounts:verify_otp')


@login_required
def send_test_email_view(request):
    """
    Allows authenticated users (especially HR and Admin) to test Google SMTP delivery live.
    """
    if request.method == 'POST':
        form = SendTestEmailForm(request.POST)
        if form.is_valid():
            recipient = form.cleaned_data['recipient_email']
            success = send_test_email(recipient, request=request)
            if success:
                messages.success(request, f"Test email dispatched successfully to {recipient}! Please check your inbox and spam folder.")
            else:
                messages.error(request, f"Failed to send test email to {recipient}. Please check system logs and SMTP credentials.")
        else:
            messages.error(request, "Please enter a valid recipient email address.")
    return redirect('accounts:profile')

