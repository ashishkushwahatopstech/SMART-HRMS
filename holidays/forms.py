from django import forms
from django.utils import timezone
from companies.models import Company
from .models import Holiday


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = [
            'company',
            'name',
            'date',
            'holiday_type',
            'is_optional',
            'description',
        ]
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Independence Day, Diwali, Christmas'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'holiday_type': forms.Select(attrs={'class': 'form-select'}),
            'is_optional': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'is_optional'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional details about the observance...'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            self.fields['date'].initial = timezone.now().date()

        if user and not user.is_superuser:
            if hasattr(user, 'employee_profile') and user.employee_profile:
                user_comp = user.employee_profile.company
                self.fields['company'].queryset = Company.objects.filter(id=user_comp.id)
                self.fields['company'].initial = user_comp


class HolidayFilterForm(forms.Form):
    year = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': 2020, 'max': 2035})
    )
    holiday_type = forms.ChoiceField(
        choices=[('', 'All Types')] + list(Holiday.HolidayType.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    company = forms.ModelChoiceField(
        queryset=Company.objects.filter(is_active=True),
        required=False,
        empty_label="All Companies",
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
