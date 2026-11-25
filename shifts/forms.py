from django import forms
from companies.models import Company
from employees.models import Employee
from .models import Shift, ShiftAssignment


class ShiftForm(forms.ModelForm):
    class Meta:
        model = Shift
        fields = [
            'company',
            'name',
            'shift_code',
            'start_time',
            'end_time',
            'lunch_duration_minutes',
            'break_duration_minutes',
            'total_expected_hours',
            'grace_period_minutes',
            'overtime_eligibility',
            'is_overnight',
            'is_active',
            'description',
        ]
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. General Shift, Night Shift'}),
            'shift_code': forms.TextInput(attrs={'class': 'form-control text-uppercase', 'placeholder': 'e.g. GEN-0917'}),
            'start_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'lunch_duration_minutes': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 180}),
            'break_duration_minutes': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 120}),
            'total_expected_hours': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.25', 'min': 1, 'max': 24}),
            'grace_period_minutes': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 120}),
            'overtime_eligibility': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'overtime_eligibility'}),
            'is_overnight': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'is_overnight'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'is_active'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Shift notes and applicability...'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['total_expected_hours'].required = False
        self.fields['total_expected_hours'].help_text = "Leave blank to auto-calculate from timings"

        if user and not user.is_superuser:
            if hasattr(user, 'employee_profile') and user.employee_profile:
                user_company = user.employee_profile.company
                self.fields['company'].queryset = Company.objects.filter(id=user_company.id)
                self.fields['company'].initial = user_company


class ShiftAssignForm(forms.ModelForm):
    employees = forms.ModelMultipleChoiceField(
        queryset=Employee.objects.none(),
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '8'}),
        help_text="Hold Ctrl/Cmd to select multiple employees"
    )

    class Meta:
        model = ShiftAssignment
        fields = ['start_date', 'remarks']
        widgets = {
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'remarks': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Reason for schedule change...'}),
        }

    def __init__(self, *args, **kwargs):
        shift = kwargs.pop('shift', None)
        super().__init__(*args, **kwargs)
        if shift:
            self.fields['employees'].queryset = Employee.objects.filter(
                company=shift.company, employment_status='active'
            ).order_by('first_name')
