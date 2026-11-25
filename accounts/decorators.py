from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


def role_required(allowed_roles=None):
    """
    Decorator to restrict view access to specific user roles.
    allowed_roles: list or tuple of role strings, e.g. ['super_admin', 'hr_admin']
    """
    if allowed_roles is None:
        allowed_roles = []

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.warning(request, "Please log in to access this page.")
                return redirect(f"{reverse('accounts:login')}?next={request.path}")

            # Superusers always have full access
            if request.user.is_superuser or request.user.role == 'super_admin':
                return view_func(request, *args, **kwargs)

            if request.user.role in allowed_roles:
                return view_func(request, *args, **kwargs)

            messages.error(
                request,
                f"Access denied. Your role ({request.user.get_role_display()}) does not have permission to view this section."
            )
            return redirect('dashboard:index')

        return _wrapped_view
    return decorator


def super_admin_required(view_func):
    """Requires Super Admin role or Django superuser"""
    return role_required(['super_admin'])(view_func)


def hr_required(view_func):
    """Requires Super Admin or HR Admin role"""
    return role_required(['super_admin', 'hr_admin'])(view_func)


def manager_required(view_func):
    """Requires Super Admin, HR Admin, or Manager role"""
    return role_required(['super_admin', 'hr_admin', 'manager'])(view_func)
