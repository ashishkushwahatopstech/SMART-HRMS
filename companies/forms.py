from django import forms
from .models import Company


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            'name',
            'code',
            'email',
            'phone',
            'address',
            'logo',
            'working_days_per_week',
            'weekly_holiday_policy',
            'default_working_hours',
            'monthly_paid_leave_allowance',
            'allow_leave_carry_forward',
            'max_carry_forward_days',
            'salary_calculation_policy',
            'timezone',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Acme Technologies Pvt Ltd'}),
            'code': forms.TextInput(attrs={'class': 'form-control text-uppercase', 'placeholder': 'e.g. ACMETEC'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'hr@company.com'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 80 1234 5678'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Registered office address...'}),
            'logo': forms.FileInput(attrs={'class': 'form-control'}),
            'working_days_per_week': forms.NumberInput(attrs={'class': 'form-control', 'min': 4, 'max': 7}),
            'weekly_holiday_policy': forms.Select(attrs={'class': 'form-select'}),
            'default_working_hours': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': 1, 'max': 24}),
            'monthly_paid_leave_allowance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': 0, 'max': 10}),
            'allow_leave_carry_forward': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'allow_carry_forward'}),
            'max_carry_forward_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 60}),
            'salary_calculation_policy': forms.Select(attrs={'class': 'form-select'}),
            'timezone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Asia/Kolkata'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'is_active'}),
        }
