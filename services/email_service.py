import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_site_url(request=None):
    """
    Returns the fully qualified base URL dynamically without hard-coding.
    If an HTTP request is provided, extracts scheme and host from request headers.
    Otherwise falls back to the configured settings.SITE_URL.
    """
    if request:
        try:
            return f"{request.scheme}://{request.get_host()}".rstrip('/')
        except Exception:
            pass
    return getattr(settings, 'SITE_URL', 'https://10.27.5.77:8000').rstrip('/')


def send_templated_email(subject, template_name, context, recipient_list, request=None, fail_silently=False):
    """
    Core email delivery utility rendering responsive big-tech grade HTML emails
    with clean plain-text alternatives, dynamic absolute links, and robust error handling.
    """
    if not recipient_list:
        logger.warning(f"Email attempt with empty recipient list for subject: {subject}")
        return False

    # Filter out empty or None recipient emails
    clean_recipients = [email.strip() for email in recipient_list if email and email.strip()]
    if not clean_recipients:
        return False

    site_url = get_site_url(request)
    base_context = {
        'site_url': site_url,
        'login_url': f"{site_url}/accounts/login/",
        'current_year': timezone.now().year,
        'company_brand': 'Smart HRMS',
        'support_email': getattr(settings, 'EMAIL_HOST_USER', 'ashishkushwaha88643@gmail.com'),
    }
    # Merge caller context
    full_context = {**base_context, **context}

    try:
        html_content = render_to_string(template_name, full_context)
        text_content = strip_tags(html_content)

        formatted_subject = f"[Smart HRMS] {subject}"
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Smart HRMS <ashishkushwaha88643@gmail.com>')

        msg = EmailMultiAlternatives(
            subject=formatted_subject,
            body=text_content,
            from_email=from_email,
            to=clean_recipients
        )
        msg.attach_alternative(html_content, "text/html")
        sent_count = msg.send(fail_silently=fail_silently)
        logger.info(f"Email '{subject}' sent successfully to {clean_recipients}")
        return sent_count > 0

    except Exception as e:
        logger.error(f"Failed to send email '{subject}' to {clean_recipients}: {str(e)}")
        if not fail_silently and settings.DEBUG:
            print(f"[EmailService Error] {str(e)}")
        return False


def send_otp_email(user, otp_code, purpose="Security Verification", request=None):
    """
    Sends a cryptographically secure 6-digit OTP verification code.
    OTP is never displayed to the frontend.
    """
    subject = f"Your Verification Code: {otp_code}"
    template_name = 'emails/otp_verification.html'
    context = {
        'user': user,
        'user_display_name': user.get_display_name(),
        'otp_code': otp_code,
        'purpose': purpose,
        'expiry_minutes': 10,
    }
    return send_templated_email(subject, template_name, context, [user.email], request=request, fail_silently=True)


def send_leave_application_notification(leave_application, request=None):
    """
    Notifies manager and HR administrator when an employee submits a new leave request.
    """
    recipients = []
    # 1. Direct Manager
    if leave_application.employee.manager and leave_application.employee.manager.email:
        recipients.append(leave_application.employee.manager.email)
    
    # 2. Company HR Admin users
    from accounts.models import User
    hr_users = User.objects.filter(
        role__in=[User.Role.HR_ADMIN, User.Role.SUPER_ADMIN],
        is_active=True
    ).exclude(email='').values_list('email', flat=True)
    recipients.extend(list(hr_users))

    # Remove duplicates
    recipients = list(set(recipients))
    if not recipients:
        return False

    site_url = get_site_url(request)
    review_url = f"{site_url}/leaves/{leave_application.pk}/"

    subject = f"New Leave Request: {leave_application.employee.get_full_name()} ({leave_application.leave_type.code})"
    template_name = 'emails/leave_request_notification.html'
    context = {
        'application': leave_application,
        'employee': leave_application.employee,
        'review_url': review_url,
    }
    return send_templated_email(subject, template_name, context, recipients, request=request, fail_silently=True)


def send_leave_status_email(leave_application, status, remarks='', request=None):
    """
    Notifies the employee when their leave request is approved or rejected.
    """
    employee = leave_application.employee
    to_email = employee.email or (employee.user.email if employee.user else None)
    if not to_email:
        return False

    site_url = get_site_url(request)
    detail_url = f"{site_url}/leaves/{leave_application.pk}/"

    status_display = status.upper()
    subject = f"Leave Request {status_display}: {leave_application.start_date.strftime('%d %b')} - {leave_application.end_date.strftime('%d %b %Y')}"
    template_name = 'emails/leave_status_notification.html'
    context = {
        'application': leave_application,
        'employee': employee,
        'status': status,
        'status_display': status_display,
        'remarks': remarks,
        'detail_url': detail_url,
    }
    return send_templated_email(subject, template_name, context, [to_email], request=request, fail_silently=True)


def send_punch_regularization_notification(punch_request, request=None):
    """
    Notifies manager and HR admin when an employee requests missed punch regularization.
    """
    recipients = []
    if punch_request.employee.manager and punch_request.employee.manager.email:
        recipients.append(punch_request.employee.manager.email)

    from accounts.models import User
    hr_users = User.objects.filter(
        role__in=[User.Role.HR_ADMIN, User.Role.SUPER_ADMIN],
        is_active=True
    ).exclude(email='').values_list('email', flat=True)
    recipients.extend(list(hr_users))

    recipients = list(set(recipients))
    if not recipients:
        return False

    site_url = get_site_url(request)
    review_url = f"{site_url}/attendance/requests/"

    subject = f"Missed Punch Regularization Requested: {punch_request.employee.get_full_name()} ({punch_request.date.strftime('%d %b %Y')})"
    template_name = 'emails/punch_request_notification.html'
    context = {
        'punch_request': punch_request,
        'employee': punch_request.employee,
        'review_url': review_url,
    }
    return send_templated_email(subject, template_name, context, recipients, request=request, fail_silently=True)


def send_punch_regularization_status_email(punch_request, status, remarks='', request=None):
    """
    Notifies the employee when their missed punch regularization request is approved or rejected.
    """
    employee = punch_request.employee
    to_email = employee.email or (employee.user.email if employee.user else None)
    if not to_email:
        return False

    site_url = get_site_url(request)
    detail_url = f"{site_url}/attendance/my/"

    status_display = status.upper()
    subject = f"Missed Punch Regularization {status_display}: {punch_request.date.strftime('%d %b %Y')}"
    template_name = 'emails/punch_status_notification.html'
    context = {
        'punch_request': punch_request,
        'employee': employee,
        'status': status,
        'status_display': status_display,
        'remarks': remarks,
        'detail_url': detail_url,
    }
    return send_templated_email(subject, template_name, context, [to_email], request=request, fail_silently=True)


def send_welcome_email(user, temp_password=None, request=None):
    """
    Sends an onboarding welcome email to a newly created user / employee with setup instructions.
    """
    if not user.email:
        return False

    site_url = get_site_url(request)
    login_url = f"{site_url}/accounts/login/"

    subject = "Welcome to Smart HRMS - Your Account Details"
    template_name = 'emails/welcome_account.html'
    context = {
        'user': user,
        'temp_password': temp_password,
        'login_url': login_url,
    }
    return send_templated_email(subject, template_name, context, [user.email], request=request, fail_silently=True)


def send_corporate_announcement_email(subject, title, message, recipient_list, request=None):
    """
    Broadcasts a corporate announcement, holiday event, or meeting invite to staff.
    """
    template_name = 'emails/corporate_announcement.html'
    context = {
        'title': title,
        'message': message,
    }
    return send_templated_email(subject, template_name, context, recipient_list, request=request, fail_silently=True)


def send_test_email(to_email, request=None):
    """
    Sends a test verification email to confirm live SMTP delivery.
    """
    subject = "Google SMTP Integration Verified - Test Notification"
    template_name = 'emails/test_email.html'
    context = {
        'timestamp': timezone.now().strftime('%d %b %Y, %I:%M %p %Z'),
        'sender': getattr(settings, 'EMAIL_HOST_USER', 'ashishkushwaha88643@gmail.com'),
    }
    return send_templated_email(subject, template_name, context, [to_email], request=request, fail_silently=False)
