from decimal import Decimal
from django import forms
from django.db.models import Q
from django.contrib.auth import get_user_model
from companies.models import Company
from shifts.models import Shift
from .models import Employee, Department, Designation

User = get_user_model()


class EmployeeForm(forms.ModelForm):
    create_user_account = forms.BooleanField(
        required=False,
        initial=True,
        label="Provision login user account",
        help_text="Automatically creates a web login account for this employee"
    )
    user_role = forms.ChoiceField(
        choices=[
            ('employee', 'Employee (Self-Service)'),
            ('manager', 'Manager (Team Oversight)'),
            ('hr_admin', 'HR Administrator'),
        ],
        initial='employee',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    initial_password = forms.CharField(
        required=False,
        initial='Employee@123',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Default: Employee@123'}),
        help_text="Initial temporary password for login"
    )

    class Meta:
        model = Employee
        fields = [
            'company',
            'employee_id',
            'first_name',
            'last_name',
            'email',
            'phone',
            'profile_picture',
            'department',
            'designation',
            'manager',
            'joining_date',
            'exit_date',
            'employment_status',
            'salary_type',
            'monthly_salary',
            'daily_salary',
            'hourly_salary',
            'working_hours_per_day',
            'assigned_shift',
            'assigned_shift_name',
            'lunch_start_time',
            'lunch_end_time',
            'address',
            'emergency_contact_name',
            'emergency_contact_phone',
        ]
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select', 'id': 'id_company'}),
            'employee_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. TC-EMP0001'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'employee@company.com'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 98765 43210'}),
            'profile_picture': forms.FileInput(attrs={'class': 'form-control'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'designation': forms.Select(attrs={'class': 'form-select'}),
            'manager': forms.Select(attrs={'class': 'form-select'}),
            'joining_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'exit_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'employment_status': forms.Select(attrs={'class': 'form-select'}),
            'salary_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_salary_type'}),
            'monthly_salary': forms.NumberInput(attrs={'class': 'form-control', 'step': '100', 'min': '0'}),
            'daily_salary': forms.NumberInput(attrs={'class': 'form-control', 'step': '10', 'min': '0'}),
            'hourly_salary': forms.NumberInput(attrs={'class': 'form-control', 'step': '1', 'min': '0'}),
            'working_hours_per_day': forms.NumberInput(attrs={'class': 'form-control', 'id': 'id_working_hours_per_day', 'step': '0.25', 'min': '1', 'max': '24'}),
            'assigned_shift': forms.Select(attrs={'class': 'form-select', 'id': 'id_assigned_shift'}),
            'assigned_shift_name': forms.HiddenInput(attrs={'id': 'id_assigned_shift_name'}),
            'lunch_start_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time', 'id': 'id_lunch_start_time'}),
            'lunch_end_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time', 'id': 'id_lunch_end_time'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Residential address...'}),
            'emergency_contact_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Emergency Contact Person'}),
            'emergency_contact_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Emergency Contact Number'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        user_company = None
        if user and not user.is_superuser:
            if hasattr(user, 'employee_profile') and user.employee_profile:
                user_company = user.employee_profile.company
        elif self.instance and self.instance.pk and self.instance.company:
            user_company = self.instance.company
        elif self.initial.get('company'):
            c_val = self.initial.get('company')
            user_company = c_val if isinstance(c_val, Company) else Company.objects.filter(pk=c_val).first()

        # Company isolation for non-superusers
        if user_company:
            self.fields['company'].queryset = Company.objects.filter(id=user_company.id)
            self.fields['company'].initial = user_company
            self.fields['department'].queryset = Department.objects.filter(company=user_company).order_by('name')
            self.fields['designation'].queryset = Designation.objects.filter(company=user_company).order_by('title')
            self.fields['assigned_shift'].queryset = Shift.objects.filter(company=user_company, is_active=True)
        else:
            self.fields['assigned_shift'].queryset = Shift.objects.filter(is_active=True)

        # Enhance shift selection choices with clock timings & expected hours
        shift_qs = self.fields['assigned_shift'].queryset
        self.fields['assigned_shift'].choices = [('', '-- Select Shift Schedule (Clock) --')] + [
            (
                s.id,
                f"{s.name} ({s.start_time.strftime('%I:%M %p')} - {s.end_time.strftime('%I:%M %p')} • {s.total_expected_hours or 8.00} hrs)"
            )
            for s in shift_qs
        ]
        self.fields['assigned_shift_name'].required = False

        # Auto-populate next incremental Employee ID for new employee registration
        if not self.instance.pk and not self.initial.get('employee_id'):
            target_comp = user_company or Company.objects.filter(is_active=True).first()
            if target_comp:
                self.fields['employee_id'].initial = Employee.generate_next_employee_id(target_comp)
        self.fields['employee_id'].required = False

        # Manager Eligibility Criteria:
        # Include users with MANAGER role or designations indicating leadership (Manager, Director, Head, Lead).
        manager_criteria = (
            Q(user__role=User.Role.MANAGER) |
            Q(designation__title__icontains='Manager') |
            Q(designation__title__icontains='Director') |
            Q(designation__title__icontains='Head') |
            Q(designation__title__icontains='Lead') |
            Q(subordinates__isnull=False)
        )

        managers_qs = Employee.objects.filter(
            employment_status=Employee.EmploymentStatus.ACTIVE
        ).filter(manager_criteria)

        if user_company:
            managers_qs = managers_qs.filter(company=user_company)

        # Exclude self when editing an existing employee
        if self.instance and self.instance.pk:
            managers_qs = managers_qs.exclude(pk=self.instance.pk)

        managers_qs = managers_qs.select_related('designation', 'company', 'user').distinct().order_by('first_name', 'last_name')

        self.fields['manager'].queryset = managers_qs
        self.fields['manager'].empty_label = "-- Select Reporting Manager (Optional) --"
        self.fields['manager'].label_from_instance = lambda obj: (
            f"{obj.get_full_name()} ({obj.designation.title if obj.designation else ('HR Admin' if obj.user and obj.user.is_hr_admin else 'Manager')} - {obj.employee_id})"
        )

        # If editing an existing employee who already has a user account
        if self.instance and self.instance.pk and self.instance.user:
            self.fields['create_user_account'].initial = True
            self.fields['create_user_account'].widget.attrs['disabled'] = True
            self.fields['user_role'].initial = self.instance.user.role
            self.fields['initial_password'].widget.attrs['disabled'] = True

    def clean(self):
        cleaned_data = super().clean()
        manager = cleaned_data.get('manager')
        company = cleaned_data.get('company')

        if manager:
            if self.instance and self.instance.pk and manager.pk == self.instance.pk:
                self.add_error('manager', "An employee cannot be their own reporting manager.")
            if company and manager.company != company:
                self.add_error('manager', "Reporting manager must belong to the same company.")

        # Auto-synchronize assigned shift name, hours, and default lunch schedule
        assigned_shift = cleaned_data.get('assigned_shift')
        if assigned_shift:
            if not cleaned_data.get('assigned_shift_name'):
                cleaned_data['assigned_shift_name'] = f"{assigned_shift.name} ({assigned_shift.start_time.strftime('%I:%M %p')} - {assigned_shift.end_time.strftime('%I:%M %p')})"
            if not cleaned_data.get('working_hours_per_day') or cleaned_data.get('working_hours_per_day') == Decimal('0.00'):
                cleaned_data['working_hours_per_day'] = assigned_shift.total_expected_hours or Decimal('8.00')
            if not cleaned_data.get('lunch_start_time') and assigned_shift.lunch_start_time:
                cleaned_data['lunch_start_time'] = assigned_shift.lunch_start_time
            if not cleaned_data.get('lunch_end_time') and assigned_shift.lunch_end_time:
                cleaned_data['lunch_end_time'] = assigned_shift.lunch_end_time

        # Auto-assign next incremental Employee ID if empty
        if not cleaned_data.get('employee_id'):
            comp = cleaned_data.get('company')
            if comp:
                cleaned_data['employee_id'] = Employee.generate_next_employee_id(comp)

        return cleaned_data


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['company', 'name', 'code', 'description']
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Engineering'}),
            'code': forms.TextInput(attrs={'class': 'form-control text-uppercase', 'placeholder': 'e.g. ENG'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Department purpose...'}),
        }

    def __init__(self, *args, user=None, user_company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.is_superuser:
            if hasattr(user, 'employee_profile') and user.employee_profile:
                user_company = user.employee_profile.company

        if user_company:
            self.fields['company'].queryset = Company.objects.filter(id=user_company.id)
            self.fields['company'].initial = user_company


class DesignationForm(forms.ModelForm):
    class Meta:
        model = Designation
        fields = ['company', 'department', 'title', 'description']
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select', 'id': 'id_desig_company'}),
            'department': forms.Select(attrs={'class': 'form-select', 'id': 'id_desig_department'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Senior Software Engineer'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Key responsibilities...'}),
        }

    def __init__(self, *args, user=None, user_company=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Allow company to be auto-derived from department
        self.fields['company'].required = False

        if user and not user.is_superuser:
            if hasattr(user, 'employee_profile') and user.employee_profile:
                user_company = user.employee_profile.company

        if user_company:
            self.fields['company'].queryset = Company.objects.filter(id=user_company.id)
            self.fields['company'].initial = user_company
            self.fields['department'].queryset = Department.objects.filter(company=user_company).order_by('name')
        else:
            self.fields['department'].queryset = Department.objects.select_related('company').order_by('company__name', 'name')

    def clean(self):
        cleaned_data = super().clean()
        department = cleaned_data.get('department')
        company = cleaned_data.get('company')

        # Automatically ensure designation's company matches department's company
        if department:
            cleaned_data['company'] = department.company
        elif not company:
            self.add_error('department', 'Please select a department for this designation.')

        return cleaned_data
