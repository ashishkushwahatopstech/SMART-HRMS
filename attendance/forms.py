from django import forms
from django.db.models import Q
from django.utils import timezone
from companies.models import Company
from employees.models import Employee, Department
from shifts.models import Shift
from .models import Attendance, AttendanceAuditLog, ManualPunchRequest


class AttendanceManualEntryForm(forms.ModelForm):
    """
    Form for HR / Super Admin to manually add or adjust an employee's attendance record.
    Includes a mandatory adjustment reason for audit logging.
    """
    adjustment_reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Mandatory explanation for manual entry or status adjustment (e.g. Employee forgot to punch, Biometric scanner glitch)...'
        }),
        required=True,
        help_text="Required compliance audit note explaining why this record is being manually recorded or modified."
    )

    class Meta:
        model = Attendance
        fields = [
            'employee',
            'date',
            'shift',
            'check_in_time',
            'check_out_time',
            'status',
            'verification_method',
            'notes',
        ]
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'shift': forms.Select(attrs={'class': 'form-select'}),
            'check_in_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'check_out_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'verification_method': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional internal notes...'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            self.fields['date'].initial = timezone.now().date()
            self.fields['verification_method'].initial = Attendance.VerificationMethod.ADMIN_ADJUSTMENT

        # Restrict employees and shifts to the user's company (and subordinates if Manager)
        if user and not user.is_superuser:
            if hasattr(user, 'employee_profile') and user.employee_profile:
                user_company = user.employee_profile.company
                emp_qs = Employee.objects.filter(
                    company=user_company, employment_status='active'
                )
                if user.role == 'manager' and not user.is_hr_admin:
                    manager_emp = user.employee_profile
                    emp_qs = emp_qs.filter(
                        Q(manager=manager_emp) | Q(department=manager_emp.department)
                    )
                self.fields['employee'].queryset = emp_qs.order_by('first_name')
                self.fields['shift'].queryset = Shift.objects.filter(
                    company=user_company, is_active=True
                ).order_by('name')


class AttendanceFilterForm(forms.Form):
    """
    Filter form for Attendance Log table.
    """
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Search employee name, ID...'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        empty_label="All Departments",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    shift = forms.ModelChoiceField(
        queryset=Shift.objects.none(),
        required=False,
        empty_label="All Shifts",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + list(Attendance.AttendanceStatus.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user and not user.is_superuser:
            if hasattr(user, 'employee_profile') and user.employee_profile:
                comp = user.employee_profile.company
                self.fields['department'].queryset = Department.objects.filter(company=comp)
                self.fields['shift'].queryset = Shift.objects.filter(company=comp)
        else:
            self.fields['department'].queryset = Department.objects.all()
            self.fields['shift'].queryset = Shift.objects.all()


class SelfCheckInForm(forms.Form):
    """
    Lightweight form for logged in managers / admins to punch check-in / check-out.
    """
    notes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional check-in remark / work mode...'})
    )


class ManualPunchRequestForm(forms.ModelForm):
    """
    Form for employees to request manual attendance regularization for missed/forgotten previous days.
    """
    class Meta:
        model = ManualPunchRequest
        fields = [
            'date',
            'punch_type',
            'check_in_time',
            'check_out_time',
            'reason',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'punch_type': forms.Select(attrs={'class': 'form-select'}),
            'check_in_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'check_out_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Provide a detailed explanation for missing the biometric camera punch (e.g. Technical glitch, forgot device, client visit, forgot to punch out)...'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.employee = kwargs.pop('employee', None)
        super().__init__(*args, **kwargs)
        # Default date to yesterday
        self.fields['date'].initial = timezone.now().date() - timezone.timedelta(days=1)
        self.fields['check_in_time'].initial = '09:00'
        self.fields['check_out_time'].initial = '17:00'

    def clean_date(self):
        req_date = self.cleaned_data.get('date')
        if req_date:
            today = timezone.now().date()
            if req_date > today:
                raise forms.ValidationError("You cannot request attendance regularization for a future date.")
            if self.employee and ManualPunchRequest.objects.filter(employee=self.employee, date=req_date).exists():
                raise forms.ValidationError(f"A manual punch request already exists for {req_date}. Please check your request history.")
        return req_date

    def clean(self):
        cleaned_data = super().clean()
        punch_type = cleaned_data.get('punch_type')
        check_in = cleaned_data.get('check_in_time')
        check_out = cleaned_data.get('check_out_time')

        if punch_type in [ManualPunchRequest.PunchType.BOTH, ManualPunchRequest.PunchType.CHECK_IN] and not check_in:
            self.add_error('check_in_time', 'Check-In time is required.')

        if punch_type in [ManualPunchRequest.PunchType.BOTH, ManualPunchRequest.PunchType.CHECK_OUT] and not check_out:
            self.add_error('check_out_time', 'Check-Out time is required.')

        return cleaned_data


class ManualPunchReviewForm(forms.Form):
    """
    Form for Managers / HR Admins to approve or reject a manual punch request.
    """
    action = forms.ChoiceField(
        choices=[('approve', 'Approve'), ('reject', 'Reject')],
        widget=forms.HiddenInput()
    )
    review_remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Optional review feedback or justification...'
        })
    )

