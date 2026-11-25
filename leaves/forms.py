from decimal import Decimal
from datetime import date, timedelta
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from companies.models import Company
from holidays.models import Holiday
from .models import LeaveType, LeaveBalance, LeaveApplication, LeaveApprovalLog


class LeaveTypeForm(forms.ModelForm):
    """
    Form for HR / Super Admin to manage Leave Types per company.
    """
    class Meta:
        model = LeaveType
        fields = [
            'company', 'name', 'code', 'annual_quota', 'is_paid',
            'allow_half_day', 'requires_attachment', 'is_carry_forward',
            'max_carry_forward_days', 'is_active', 'description'
        ]
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Paid Leave'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. PL'}),
            'annual_quota': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5'}),
            'is_paid': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_half_day': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'requires_attachment': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_carry_forward': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'max_carry_forward_days': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional policy details'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.is_super_admin:
            # HR Admin can only manage their own company
            if hasattr(user, 'employee_profile') and user.employee_profile:
                self.fields['company'].queryset = Company.objects.filter(id=user.employee_profile.company_id)
                self.fields['company'].initial = user.employee_profile.company
                self.fields['company'].widget = forms.HiddenInput()
            else:
                self.fields['company'].queryset = Company.objects.none()


class LeaveApplicationForm(forms.ModelForm):
    """
    Employee Leave Application Form with real-time working day checks,
    half-day session selector, and leave balance verification.
    """
    class Meta:
        model = LeaveApplication
        fields = [
            'leave_type', 'start_date', 'end_date', 'is_half_day',
            'half_day_session', 'reason', 'attachment'
        ]
        widgets = {
            'leave_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_leave_type'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'id': 'id_start_date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'id': 'id_end_date'}),
            'is_half_day': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_is_half_day'}),
            'half_day_session': forms.Select(attrs={'class': 'form-select', 'id': 'id_half_day_session'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Specify genuine business or personal reason'}),
            'attachment': forms.FileInput(attrs={'class': 'form-control', 'id': 'id_attachment'}),
        }

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        if employee:
            self.fields['leave_type'].queryset = LeaveType.objects.filter(
                company=employee.company,
                is_active=True
            ).order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        leave_type = cleaned_data.get('leave_type')
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        is_half_day = cleaned_data.get('is_half_day')
        half_day_session = cleaned_data.get('half_day_session')
        attachment = cleaned_data.get('attachment')

        if not leave_type or not start_date:
            return cleaned_data

        # If half-day, end_date must match start_date
        if is_half_day:
            if not leave_type.allow_half_day:
                raise ValidationError({
                    'is_half_day': f"Half-day leaves are not permitted for {leave_type.name}."
                })
            if not half_day_session:
                raise ValidationError({
                    'half_day_session': "Please specify whether this is for the First Half or Second Half."
                })
            cleaned_data['end_date'] = start_date
            end_date = start_date
        else:
            if not end_date:
                cleaned_data['end_date'] = start_date
                end_date = start_date
            elif start_date > end_date:
                raise ValidationError({
                    'end_date': "End date cannot be earlier than start date."
                })

        # Calculate net working days
        company = self.employee.company if self.employee else leave_type.company
        if is_half_day:
            net_days = Decimal('0.50')
            # Check if start_date is a non-working day
            if not Holiday.is_working_day(company, start_date):
                raise ValidationError({
                    'start_date': f"{start_date.strftime('%d %b %Y')} is a weekly off or company holiday."
                })
        else:
            cur = start_date
            working_days_count = 0
            while cur <= end_date:
                if Holiday.is_working_day(company, cur):
                    working_days_count += 1
                cur += timedelta(days=1)

            if working_days_count == 0:
                raise ValidationError(
                    "The selected date range does not contain any regular working days (all selected dates are weekly offs or public holidays)."
                )
            net_days = Decimal(str(working_days_count))

        cleaned_data['calculated_net_days'] = net_days

        # Mandatory attachment verification
        if leave_type.requires_attachment:
            if not attachment and (not self.instance or not self.instance.attachment):
                raise ValidationError({
                    'attachment': f"A supporting document/attachment is mandatory when applying for {leave_type.name}."
                })

        # Check Leave Balance availability (if paid leave)
        if self.employee and leave_type.is_paid:
            balance = LeaveBalance.objects.filter(
                employee=self.employee,
                leave_type=leave_type,
                year=start_date.year
            ).first()

            available = balance.available_days if balance else Decimal('0.00')
            if available < net_days:
                raise ValidationError(
                    f"Insufficient leave balance for {leave_type.name}. You have {available} available days for {start_date.year}, but requested {net_days} working days."
                )

        return cleaned_data


class LeaveDecisionForm(forms.Form):
    """
    Form for Managers / HR Admins to approve or reject leave requests.
    """
    rejection_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Provide justification if rejecting this application...'
        })
    )


class LeaveFilterForm(forms.Form):
    """
    Filter form for applications roster.
    """
    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + list(LeaveApplication.ApplicationStatus.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    leave_type = forms.ModelChoiceField(
        queryset=LeaveType.objects.none(),
        required=False,
        empty_label='All Leave Types',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    year = forms.IntegerField(
        required=False,
        initial=timezone.now().year,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Year'})
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Search employee name or ID...'})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and user.is_authenticated:
            if user.is_super_admin:
                self.fields['leave_type'].queryset = LeaveType.objects.filter(is_active=True).order_by('name')
            elif hasattr(user, 'employee_profile') and user.employee_profile:
                self.fields['leave_type'].queryset = LeaveType.objects.filter(
                    company=user.employee_profile.company,
                    is_active=True
                ).order_by('name')


class LeaveBalanceAdjustmentForm(forms.ModelForm):
    """
    Form for HR Admin to adjust or assign leave balances.
    """
    class Meta:
        model = LeaveBalance
        fields = ['allocated_days', 'carried_forward_days', 'accrued_days']
        widgets = {
            'allocated_days': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5'}),
            'carried_forward_days': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5'}),
            'accrued_days': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5'}),
        }
