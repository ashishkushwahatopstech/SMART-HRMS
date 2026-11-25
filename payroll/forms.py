from django import forms
from django.utils import timezone
from companies.models import Company
from .models import PayrollRun, Payslip


class PayrollRunCreateForm(forms.ModelForm):
    """
    Form to initiate a monthly payroll batch execution.
    """
    class Meta:
        model = PayrollRun
        fields = ['company', 'month', 'year', 'notes']
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'month': forms.Select(attrs={'class': 'form-select'}),
            'year': forms.NumberInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional internal remarks'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.is_super_admin:
            if hasattr(user, 'employee_profile') and user.employee_profile:
                self.fields['company'].queryset = Company.objects.filter(id=user.employee_profile.company_id)
                self.fields['company'].initial = user.employee_profile.company
                self.fields['company'].widget = forms.HiddenInput()
            else:
                self.fields['company'].queryset = Company.objects.none()


class PayslipPaymentUpdateForm(forms.ModelForm):
    """
    Form for HR to record disbursal payment details.
    """
    class Meta:
        model = Payslip
        fields = ['payment_status', 'payment_date', 'payment_reference']
        widgets = {
            'payment_status': forms.Select(attrs={'class': 'form-select'}),
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_reference': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'NEFT / UTR / Cheque Ref'}),
        }


class PayrollFilterForm(forms.Form):
    """
    Filter form for Payroll Runs and Payslips.
    """
    year = forms.IntegerField(
        required=False,
        initial=timezone.now().year,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Year'})
    )
    month = forms.ChoiceField(
        choices=[('', 'All Months')] + PayrollRun.MONTH_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + list(PayrollRun.RunStatus.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
