from decimal import Decimal
from datetime import time, datetime, timedelta, date
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from django.utils import timezone
from accounts.models import User
from companies.models import Company
from employees.models import Employee, Department, Designation
from shifts.models import Shift, ShiftAssignment
from attendance.models import Attendance, AttendanceAuditLog
from holidays.models import Holiday
from leaves.models import LeaveType, LeaveBalance, LeaveApplication, LeaveApprovalLog
from payroll.models import PayrollRun, Payslip


class Command(BaseCommand):
    help = 'Seeds initial groups, roles, companies, departments, designations, and demo employees.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Initializing Smart HRMS Demo Data..."))

        # 1. Create standard Django Groups
        groups = {
            'Super Admin': 'Full administrative control over all companies and settings.',
            'HR Admin': 'Personnel, shifts, leaves, attendance, and payroll governance.',
            'Manager': 'Team oversight, attendance audit, and leave authorization.',
            'Employee': 'Self-service attendance check-in, leave requests, and payslips.',
        }

        group_objects = {}
        for group_name in groups.keys():
            group, created = Group.objects.get_or_create(name=group_name)
            group_objects[group_name] = group

        # 2. Create Demo Companies
        # Company A: Acme Technologies (5-day week, actual working days salary policy)
        acme, created = Company.objects.get_or_create(
            code='ACMETEC',
            defaults={
                'name': 'Acme Technologies Pvt Ltd',
                'email': 'contact@acmetec.com',
                'phone': '+91 80 4100 2000',
                'address': 'Level 4, Cyber Park, Electronic City Phase 1, Bangalore, Karnataka - 560100',
                'working_days_per_week': 5,
                'weekly_holiday_policy': Company.WeeklyHolidayPolicy.SATURDAY_SUNDAY,
                'default_working_hours': Decimal('8.00'),
                'monthly_paid_leave_allowance': Decimal('1.00'),
                'allow_leave_carry_forward': True,
                'max_carry_forward_days': 15,
                'salary_calculation_policy': Company.SalaryCalculationPolicy.ACTUAL_WORKING_DAYS,
                'timezone': 'Asia/Kolkata',
                'is_active': True,
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"  [+] Created Company: {acme.name} ({acme.code})"))

        # Company B: Zenith Global Solutions (6-day week, fixed 26-day salary policy)
        zenith, created = Company.objects.get_or_create(
            code='ZENITH',
            defaults={
                'name': 'Zenith Global Solutions Ltd',
                'email': 'hr@zenithglobal.com',
                'phone': '+91 22 2500 8000',
                'address': 'Plot 12, MIDC Industrial Area, Andheri East, Mumbai, Maharashtra - 400093',
                'working_days_per_week': 6,
                'weekly_holiday_policy': Company.WeeklyHolidayPolicy.SUNDAY_ONLY,
                'default_working_hours': Decimal('8.00'),
                'monthly_paid_leave_allowance': Decimal('1.50'),
                'allow_leave_carry_forward': True,
                'max_carry_forward_days': 12,
                'salary_calculation_policy': Company.SalaryCalculationPolicy.FIXED_26_DAYS,
                'timezone': 'Asia/Kolkata',
                'is_active': True,
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"  [+] Created Company: {zenith.name} ({zenith.code})"))

        # 3. Create Departments for Acme Technologies
        dept_data = [
            ('Engineering', 'ENG', 'Product architecture and software engineering'),
            ('Human Resources', 'HR', 'People operations and talent development'),
            ('Sales & Marketing', 'MKT', 'Client acquisition and business development'),
            ('Finance & Accounts', 'FIN', 'Corporate finance, taxation, and payroll audit'),
        ]
        acme_depts = {}
        for name, code, desc in dept_data:
            dept, _ = Department.objects.get_or_create(
                company=acme,
                name=name,
                defaults={'code': code, 'description': desc}
            )
            acme_depts[name] = dept

        # Zenith Department
        zenith_eng, _ = Department.objects.get_or_create(
            company=zenith,
            name='Engineering Operations',
            defaults={'code': 'EOP', 'description': 'Cloud operations'}
        )

        # 4. Create Designations for Acme Technologies
        desig_data = [
            ('Engineering', 'Engineering Manager', 'Leads software delivery teams'),
            ('Engineering', 'Senior Software Engineer', 'Core Python and backend developer'),
            ('Engineering', 'Full Stack Developer', 'Django web applications developer'),
            ('Engineering', 'QA Engineer', 'Quality testing and automation'),
            ('Human Resources', 'HR Operations Lead', 'Manages employee lifecycles and compliance'),
            ('Sales & Marketing', 'Sales Manager', 'Oversees enterprise accounts'),
            ('Sales & Marketing', 'Business Development Rep', 'Client outreach'),
            ('Finance & Accounts', 'Senior Financial Analyst', 'Financial reporting and audit'),
        ]
        acme_desigs = {}
        for dept_name, title, desc in desig_data:
            desig, _ = Designation.objects.get_or_create(
                company=acme,
                department=acme_depts[dept_name],
                title=title,
                defaults={'description': desc}
            )
            acme_desigs[title] = desig

        zenith_lead, _ = Designation.objects.get_or_create(
            company=zenith,
            department=zenith_eng,
            title='Cloud Operations Lead'
        )

        # 5. Create Core Users & Linked Employees
        # 5.1 Super Admin (System Superuser)
        superadmin, _ = User.objects.get_or_create(
            username='superadmin',
            defaults={
                'email': 'admin@smarthrms.local',
                'first_name': 'System',
                'last_name': 'Administrator',
                'role': User.Role.SUPER_ADMIN,
                'is_staff': True,
                'is_superuser': True,
                'phone': '+91 99000 11111',
                'bio': 'System Master Admin with full multi-company authority.',
            }
        )
        superadmin.set_password('Admin@123')
        superadmin.save()
        superadmin.groups.add(group_objects['Super Admin'])

        # 5.2 HR Admin (Sneha Patel - Acme)
        hr_user, _ = User.objects.get_or_create(
            username='hradmin',
            defaults={
                'email': 'hr@smarthrms.local',
                'first_name': 'Sneha',
                'last_name': 'Patel',
                'role': User.Role.HR_ADMIN,
                'is_staff': True,
                'is_superuser': False,
                'phone': '+91 99000 22222',
                'bio': 'Head of People Operations at Acme Technologies.',
            }
        )
        hr_user.set_password('Hradmin@123')
        hr_user.save()
        hr_user.groups.add(group_objects['HR Admin'])

        hr_emp, _ = Employee.objects.get_or_create(
            employee_id='ACME-EMP0001',
            defaults={
                'user': hr_user,
                'company': acme,
                'first_name': 'Sneha',
                'last_name': 'Patel',
                'email': 'hr@smarthrms.local',
                'phone': '+91 99000 22222',
                'department': acme_depts['Human Resources'],
                'designation': acme_desigs['HR Operations Lead'],
                'joining_date': timezone.now().date(),
                'employment_status': Employee.EmploymentStatus.ACTIVE,
                'salary_type': Employee.SalaryType.MONTHLY,
                'monthly_salary': Decimal('75000.00'),
                'working_hours_per_day': Decimal('8.00'),
            }
        )

        # 5.3 Manager 1: Vikram Sharma (Engineering Manager)
        mgr1_user, _ = User.objects.get_or_create(
            username='manager1',
            defaults={
                'email': 'manager1@smarthrms.local',
                'first_name': 'Vikram',
                'last_name': 'Sharma',
                'role': User.Role.MANAGER,
                'is_staff': False,
                'is_superuser': False,
                'phone': '+91 99000 33333',
                'bio': 'Engineering Team Lead at Acme Technologies.',
            }
        )
        mgr1_user.set_password('Manager@123')
        mgr1_user.save()
        mgr1_user.groups.add(group_objects['Manager'])

        mgr1_emp, _ = Employee.objects.get_or_create(
            employee_id='ACME-EMP0002',
            defaults={
                'user': mgr1_user,
                'company': acme,
                'first_name': 'Vikram',
                'last_name': 'Sharma',
                'email': 'manager1@smarthrms.local',
                'phone': '+91 99000 33333',
                'department': acme_depts['Engineering'],
                'designation': acme_desigs['Engineering Manager'],
                'manager': hr_emp,
                'joining_date': timezone.now().date(),
                'employment_status': Employee.EmploymentStatus.ACTIVE,
                'salary_type': Employee.SalaryType.MONTHLY,
                'monthly_salary': Decimal('95000.00'),
                'working_hours_per_day': Decimal('8.00'),
            }
        )

        # 5.4 Manager 2: Ritu Varma (Sales Manager)
        mgr2_user, _ = User.objects.get_or_create(
            username='manager2',
            defaults={
                'email': 'manager2@smarthrms.local',
                'first_name': 'Ritu',
                'last_name': 'Varma',
                'role': User.Role.MANAGER,
                'is_staff': False,
                'is_superuser': False,
                'phone': '+91 99000 33334',
                'bio': 'Sales Team Manager at Acme Technologies.',
            }
        )
        mgr2_user.set_password('Manager@123')
        mgr2_user.save()
        mgr2_user.groups.add(group_objects['Manager'])

        mgr2_emp, _ = Employee.objects.get_or_create(
            employee_id='ACME-EMP0003',
            defaults={
                'user': mgr2_user,
                'company': acme,
                'first_name': 'Ritu',
                'last_name': 'Varma',
                'email': 'manager2@smarthrms.local',
                'phone': '+91 99000 33334',
                'department': acme_depts['Sales & Marketing'],
                'designation': acme_desigs['Sales Manager'],
                'manager': hr_emp,
                'joining_date': timezone.now().date(),
                'employment_status': Employee.EmploymentStatus.ACTIVE,
                'salary_type': Employee.SalaryType.MONTHLY,
                'monthly_salary': Decimal('85000.00'),
                'working_hours_per_day': Decimal('8.00'),
            }
        )

        # 5.5 Ten Employees across Acme Technologies
        employee_records = [
            # 1. Aarav Verma (Senior Software Engineer)
            {
                'username': 'employee1',
                'first': 'Aarav', 'last': 'Verma',
                'email': 'employee1@smarthrms.local', 'phone': '+91 99000 44441',
                'emp_id': 'ACME-EMP0004',
                'dept': 'Engineering', 'desig': 'Senior Software Engineer', 'mgr': mgr1_emp,
                'salary_type': Employee.SalaryType.MONTHLY, 'salary': Decimal('65000.00'),
                'status': Employee.EmploymentStatus.ACTIVE,
            },
            # 2. Priya Singh (Full Stack Developer)
            {
                'username': 'employee2',
                'first': 'Priya', 'last': 'Singh',
                'email': 'employee2@smarthrms.local', 'phone': '+91 99000 44442',
                'emp_id': 'ACME-EMP0005',
                'dept': 'Engineering', 'desig': 'Full Stack Developer', 'mgr': mgr1_emp,
                'salary_type': Employee.SalaryType.MONTHLY, 'salary': Decimal('48000.00'),
                'status': Employee.EmploymentStatus.ACTIVE,
            },
            # 3. Rohan Gupta (QA Engineer)
            {
                'username': 'employee3',
                'first': 'Rohan', 'last': 'Gupta',
                'email': 'employee3@smarthrms.local', 'phone': '+91 99000 44443',
                'emp_id': 'ACME-EMP0006',
                'dept': 'Engineering', 'desig': 'QA Engineer', 'mgr': mgr1_emp,
                'salary_type': Employee.SalaryType.MONTHLY, 'salary': Decimal('35000.00'),
                'status': Employee.EmploymentStatus.ACTIVE,
            },
            # 4. Ananya Joshi (Business Development Rep)
            {
                'username': 'employee4',
                'first': 'Ananya', 'last': 'Joshi',
                'email': 'employee4@smarthrms.local', 'phone': '+91 99000 44444',
                'emp_id': 'ACME-EMP0007',
                'dept': 'Sales & Marketing', 'desig': 'Business Development Rep', 'mgr': mgr2_emp,
                'salary_type': Employee.SalaryType.MONTHLY, 'salary': Decimal('32000.00'),
                'status': Employee.EmploymentStatus.ACTIVE,
            },
            # 5. Karan Mehta (Senior Financial Analyst)
            {
                'username': 'employee5',
                'first': 'Karan', 'last': 'Mehta',
                'email': 'employee5@smarthrms.local', 'phone': '+91 99000 44445',
                'emp_id': 'ACME-EMP0008',
                'dept': 'Finance & Accounts', 'desig': 'Senior Financial Analyst', 'mgr': hr_emp,
                'salary_type': Employee.SalaryType.MONTHLY, 'salary': Decimal('55000.00'),
                'status': Employee.EmploymentStatus.ACTIVE,
            },
            # 6. Neha Rao (Junior Developer - Trainee with ₹9,000 example as requested in Section 12)
            {
                'username': 'employee6',
                'first': 'Neha', 'last': 'Rao',
                'email': 'employee6@smarthrms.local', 'phone': '+91 99000 44446',
                'emp_id': 'ACME-EMP0009',
                'dept': 'Engineering', 'desig': 'Full Stack Developer', 'mgr': mgr1_emp,
                'salary_type': Employee.SalaryType.MONTHLY, 'salary': Decimal('9000.00'),
                'status': Employee.EmploymentStatus.PROBATION,
            },
            # 7. Devendra Kulkarni (Daily Wage Contract Worker)
            {
                'username': 'employee7',
                'first': 'Devendra', 'last': 'Kulkarni',
                'email': 'employee7@smarthrms.local', 'phone': '+91 99000 44447',
                'emp_id': 'ACME-EMP0010',
                'dept': 'Engineering', 'desig': 'QA Engineer', 'mgr': mgr1_emp,
                'salary_type': Employee.SalaryType.DAILY, 'salary': Decimal('15000.00'),
                'status': Employee.EmploymentStatus.ACTIVE,
            },
            # 8. Meera Nair (Business Development)
            {
                'username': 'employee8',
                'first': 'Meera', 'last': 'Nair',
                'email': 'employee8@smarthrms.local', 'phone': '+91 99000 44448',
                'emp_id': 'ACME-EMP0011',
                'dept': 'Sales & Marketing', 'desig': 'Business Development Rep', 'mgr': mgr2_emp,
                'salary_type': Employee.SalaryType.MONTHLY, 'salary': Decimal('30000.00'),
                'status': Employee.EmploymentStatus.ACTIVE,
            },
            # 9. Siddharth Pandey (Backend Developer)
            {
                'username': 'employee9',
                'first': 'Siddharth', 'last': 'Pandey',
                'email': 'employee9@smarthrms.local', 'phone': '+91 99000 44449',
                'emp_id': 'ACME-EMP0012',
                'dept': 'Engineering', 'desig': 'Senior Software Engineer', 'mgr': mgr1_emp,
                'salary_type': Employee.SalaryType.MONTHLY, 'salary': Decimal('60000.00'),
                'status': Employee.EmploymentStatus.ACTIVE,
            },
            # 10. Pooja Deshmukh (UI/UX Developer)
            {
                'username': 'employee10',
                'first': 'Pooja', 'last': 'Deshmukh',
                'email': 'employee10@smarthrms.local', 'phone': '+91 99000 44450',
                'emp_id': 'ACME-EMP0013',
                'dept': 'Engineering', 'desig': 'Full Stack Developer', 'mgr': mgr1_emp,
                'salary_type': Employee.SalaryType.MONTHLY, 'salary': Decimal('42000.00'),
                'status': Employee.EmploymentStatus.ACTIVE,
            },
        ]

        for emp_info in employee_records:
            u, _ = User.objects.get_or_create(
                username=emp_info['username'],
                defaults={
                    'email': emp_info['email'],
                    'first_name': emp_info['first'],
                    'last_name': emp_info['last'],
                    'role': User.Role.EMPLOYEE,
                    'phone': emp_info['phone'],
                }
            )
            u.set_password('Employee@123')
            u.save()
            u.groups.add(group_objects['Employee'])

            emp, created_emp = Employee.objects.get_or_create(
                employee_id=emp_info['emp_id'],
                defaults={
                    'user': u,
                    'company': acme,
                    'first_name': emp_info['first'],
                    'last_name': emp_info['last'],
                    'email': emp_info['email'],
                    'phone': emp_info['phone'],
                    'department': acme_depts[emp_info['dept']],
                    'designation': acme_desigs[emp_info['desig']],
                    'manager': emp_info['mgr'],
                    'joining_date': timezone.now().date(),
                    'employment_status': emp_info['status'],
                    'salary_type': emp_info['salary_type'],
                    'monthly_salary': emp_info['salary'],
                    'working_hours_per_day': Decimal('8.00'),
                }
            )

        # 6. Add 1 Employee to Zenith (to test Multi-Company Data Isolation)
        zenith_emp, _ = Employee.objects.get_or_create(
            employee_id='ZENITH-EMP0001',
            defaults={
                'company': zenith,
                'first_name': 'Sunil',
                'last_name': 'Gavaskar',
                'email': 'sunil@zenithglobal.com',
                'phone': '+91 98888 12345',
                'department': zenith_eng,
                'designation': zenith_lead,
                'joining_date': timezone.now().date(),
                'employment_status': Employee.EmploymentStatus.ACTIVE,
                'salary_type': Employee.SalaryType.MONTHLY,
                'monthly_salary': Decimal('80000.00'),
            }
        )

        # 7. Create Configurable Shifts (Phase 3)
        # Acme Technologies Shifts
        acme_shifts_spec = [
            {
                'name': 'General Shift',
                'code': 'GEN-0917',
                'start': time(9, 0),
                'end': time(17, 0),
                'hours': Decimal('8.00'),
                'lunch': 60,
                'break': 15,
                'grace': 15,
                'overnight': False,
                'desc': 'Standard daytime business schedule',
            },
            {
                'name': 'Morning Shift',
                'code': 'MOR-0614',
                'start': time(6, 0),
                'end': time(14, 0),
                'hours': Decimal('8.00'),
                'lunch': 45,
                'break': 15,
                'grace': 15,
                'overnight': False,
                'desc': 'Early production shift',
            },
            {
                'name': 'Evening Shift',
                'code': 'EVE-1422',
                'start': time(14, 0),
                'end': time(22, 0),
                'hours': Decimal('8.00'),
                'lunch': 45,
                'break': 15,
                'grace': 15,
                'overnight': False,
                'desc': 'Late afternoon to night operation',
            },
            {
                'name': 'Night Shift (Overnight)',
                'code': 'NGT-2206',
                'start': time(22, 0),
                'end': time(6, 0),
                'hours': Decimal('8.00'),
                'lunch': 45,
                'break': 15,
                'grace': 15,
                'overnight': True,
                'desc': 'Overnight cross-midnight shift (10 PM - 6 AM)',
            },
            {
                'name': '12-Hour Day Shift',
                'code': '12H-0820',
                'start': time(8, 0),
                'end': time(20, 0),
                'hours': Decimal('12.00'),
                'lunch': 60,
                'break': 30,
                'grace': 15,
                'overnight': False,
                'desc': '12-hour extended engineering on-call shift',
            },
        ]

        acme_shifts = {}
        for sspec in acme_shifts_spec:
            s_obj, created = Shift.objects.get_or_create(
                company=acme,
                name=sspec['name'],
                defaults={
                    'shift_code': sspec['code'],
                    'start_time': sspec['start'],
                    'end_time': sspec['end'],
                    'total_expected_hours': sspec['hours'],
                    'lunch_duration_minutes': sspec['lunch'],
                    'break_duration_minutes': sspec['break'],
                    'grace_period_minutes': sspec['grace'],
                    'is_overnight': sspec['overnight'],
                    'overtime_eligibility': True,
                    'description': sspec['desc'],
                }
            )
            acme_shifts[sspec['name']] = s_obj

        # Zenith Shifts (including 24-Hour Emergency Shift)
        zenith_general, _ = Shift.objects.get_or_create(
            company=zenith,
            name='Zenith Standard Day Shift',
            defaults={
                'shift_code': 'ZEN-0918',
                'start_time': time(9, 30),
                'end_time': time(18, 30),
                'total_expected_hours': Decimal('9.00'),
                'lunch_duration_minutes': 60,
                'break_duration_minutes': 15,
                'grace_period_minutes': 15,
                'is_overnight': False,
            }
        )

        zenith_24h, _ = Shift.objects.get_or_create(
            company=zenith,
            name='24-Hour Critical Support Shift',
            defaults={
                'shift_code': 'ZEN-24HR',
                'start_time': time(9, 0),
                'end_time': time(9, 0),
                'total_expected_hours': Decimal('24.00'),
                'lunch_duration_minutes': 120,
                'break_duration_minutes': 60,
                'grace_period_minutes': 30,
                'is_overnight': True,
                'description': 'Full 24-hour mission critical rotation',
            }
        )

        # 8. Assign Shifts to Employees
        shift_assignments_map = {
            'ACME-EMP0001': acme_shifts['General Shift'],
            'ACME-EMP0002': acme_shifts['General Shift'],
            'ACME-EMP0003': acme_shifts['General Shift'],
            'ACME-EMP0004': acme_shifts['General Shift'],              # employee1
            'ACME-EMP0005': acme_shifts['Morning Shift'],              # employee2
            'ACME-EMP0006': acme_shifts['Evening Shift'],              # employee3
            'ACME-EMP0007': acme_shifts['Night Shift (Overnight)'],    # employee4
            'ACME-EMP0008': acme_shifts['12-Hour Day Shift'],          # employee5
            'ACME-EMP0009': acme_shifts['General Shift'],              # employee6
            'ACME-EMP0010': acme_shifts['General Shift'],
            'ACME-EMP0011': acme_shifts['General Shift'],
            'ACME-EMP0012': acme_shifts['Morning Shift'],
            'ACME-EMP0013': acme_shifts['General Shift'],
        }

        for emp_id, shift_obj in shift_assignments_map.items():
            emp_rec = Employee.objects.filter(employee_id=emp_id).first()
            if emp_rec:
                emp_rec.assigned_shift = shift_obj
                emp_rec.assigned_shift_name = f"{shift_obj.name} ({shift_obj.start_time.strftime('%H:%M')} - {shift_obj.end_time.strftime('%H:%M')})"
                emp_rec.working_hours_per_day = shift_obj.total_expected_hours
                emp_rec.save()

                ShiftAssignment.objects.get_or_create(
                    employee=emp_rec,
                    shift=shift_obj,
                    is_active=True,
                    defaults={
                        'start_date': timezone.now().date(),
                        'remarks': 'Initial corporate schedule assignment',
                        'assigned_by': superadmin,
                    }
                )

        # Assign Zenith employee
        zenith_emp.assigned_shift = zenith_24h
        zenith_emp.assigned_shift_name = f"{zenith_24h.name} (24 Hours)"
        zenith_emp.working_hours_per_day = Decimal('24.00')
        zenith_emp.save()

        # 9. Seed Demo Attendance Records (Last 5 Days)
        today = timezone.now().date()
        date_range = [today - timedelta(days=i) for i in range(4, -1, -1)]

        demo_active_emps = Employee.objects.filter(employment_status='active', assigned_shift__isnull=False)
        attendance_count = 0

        for cur_date in date_range:
            # Skip Sunday if Sunday-only off, or weekend
            is_sunday = (cur_date.weekday() == 6)
            is_saturday = (cur_date.weekday() == 5)

            for emp in demo_active_emps:
                # Check weekly holiday policy
                if is_sunday or (is_saturday and emp.company.weekly_holiday_policy == Company.WeeklyHolidayPolicy.SATURDAY_SUNDAY):
                    Attendance.objects.get_or_create(
                        employee=emp,
                        date=cur_date,
                        defaults={
                            'company': emp.company,
                            'shift': emp.assigned_shift,
                            'status': Attendance.AttendanceStatus.WEEKLY_OFF,
                            'verification_method': Attendance.VerificationMethod.MANUAL_WEB,
                            'notes': 'Scheduled weekly off day',
                        }
                    )
                    continue

                shift = emp.assigned_shift
                start_h = shift.start_time.hour
                start_m = shift.start_time.minute
                end_h = shift.end_time.hour
                end_m = shift.end_time.minute

                # Variation patterns based on employee id & day
                day_offset = cur_date.day % 4
                emp_seed = emp.id % 5

                if emp_seed == 0 and cur_date == today:
                    # One employee absent today
                    Attendance.objects.get_or_create(
                        employee=emp,
                        date=cur_date,
                        defaults={
                            'company': emp.company,
                            'shift': shift,
                            'status': Attendance.AttendanceStatus.ABSENT,
                            'notes': 'Unplanned absence / sick call',
                        }
                    )
                    attendance_count += 1
                    continue

                # Late arrival variation
                is_emp_late = (emp_seed == 2 and day_offset == 1)
                punch_in_minute = start_m + (25 if is_emp_late else -5)
                actual_in_dt = timezone.make_aware(datetime.combine(cur_date, time(start_h, max(0, min(59, punch_in_minute)))))

                # For today: check-out might be in-progress if afternoon
                is_today = (cur_date == today)
                if is_today and emp_seed in [1, 3]:
                    # Still clocked in (missing checkout)
                    actual_out_dt = None
                else:
                    out_date = cur_date + timedelta(days=1) if shift.is_overnight else cur_date
                    overtime_extra = 90 if (emp_seed == 4) else 0  # 1.5 hr OT
                    actual_out_dt = timezone.make_aware(datetime.combine(out_date, time(end_h, end_m)) + timedelta(minutes=overtime_extra))

                att_rec, created = Attendance.objects.get_or_create(
                    employee=emp,
                    date=cur_date,
                    defaults={
                        'company': emp.company,
                        'shift': shift,
                        'check_in_time': actual_in_dt,
                        'check_out_time': actual_out_dt,
                        'verification_method': Attendance.VerificationMethod.FACE_RECOGNITION if emp.face_registration_status else Attendance.VerificationMethod.MANUAL_WEB,
                        'ip_address': '192.168.1.105',
                    }
                )
                if created:
                    attendance_count += 1

        # Seed one sample manual audit log entry
        sample_att = Attendance.objects.filter(employee__employee_id='ACME-EMP0004').first()
        if sample_att and not sample_att.audit_logs.exists():
            AttendanceAuditLog.objects.create(
                attendance=sample_att,
                action='Manual Clock Correction',
                changed_by=superadmin,
                field_name='check_in_time',
                old_value='09:25:00 AM',
                new_value='08:55:00 AM',
                reason='Biometric camera light reflection delayed facial scan detection by 30 mins'
            )

        # 10. Seed 2026 Corporate Holidays
        holidays_spec = [
            ('New Year\'s Day', date(2026, 1, 1), Holiday.HolidayType.MANDATORY, False, 'First calendar day of the new year'),
            ('Republic Day', date(2026, 1, 26), Holiday.HolidayType.MANDATORY, False, 'Constitution of India celebration'),
            ('Maha Shivratri', date(2026, 2, 16), Holiday.HolidayType.OPTIONAL, True, 'Restricted optional holiday'),
            ('Holi', date(2026, 3, 3), Holiday.HolidayType.MANDATORY, False, 'Festival of Colors national holiday'),
            ('Good Friday', date(2026, 4, 3), Holiday.HolidayType.MANDATORY, False, 'National gazetted holiday'),
            ('Ambedkar Jayanti', date(2026, 4, 14), Holiday.HolidayType.OPTIONAL, True, 'Dr. B.R. Ambedkar commemoration'),
            ('May Day', date(2026, 5, 1), Holiday.HolidayType.MANDATORY, False, 'International Workers\' Day'),
            ('Independence Day', date(2026, 8, 15), Holiday.HolidayType.MANDATORY, False, '79th Indian Independence Day'),
            ('Raksha Bandhan', date(2026, 8, 28), Holiday.HolidayType.OPTIONAL, True, 'Restricted optional holiday'),
            ('Janmashtami', date(2026, 9, 4), Holiday.HolidayType.OPTIONAL, True, 'Lord Krishna birthday observance'),
            ('Gandhi Jayanti', date(2026, 10, 2), Holiday.HolidayType.MANDATORY, False, 'Mahatma Gandhi Birth Anniversary'),
            ('Dussehra (Vijaya Dashami)', date(2026, 10, 20), Holiday.HolidayType.MANDATORY, False, 'National festival holiday'),
            ('Diwali (Deepavali)', date(2026, 11, 8), Holiday.HolidayType.MANDATORY, False, 'Festival of Lights national holiday'),
            ('Govardhan Puja', date(2026, 11, 9), Holiday.HolidayType.OPTIONAL, True, 'Post-Diwali optional holiday'),
            ('Guru Nanak Jayanti', date(2026, 11, 24), Holiday.HolidayType.MANDATORY, False, 'Guru Nanak Gurpurab public holiday'),
            ('Christmas Day', date(2026, 12, 25), Holiday.HolidayType.MANDATORY, False, 'Christmas national holiday'),
        ]

        for comp in [acme, zenith]:
            for hname, hdate, htype, hopt, hdesc in holidays_spec:
                Holiday.objects.get_or_create(
                    company=comp,
                    date=hdate,
                    defaults={
                        'name': hname,
                        'holiday_type': htype,
                        'is_optional': hopt,
                        'description': hdesc,
                    }
                )

        # 11. Seed Leave Categories (LeaveType)
        leave_types_spec = [
            ('Paid Leave', 'PL', Decimal('12.00'), True, True, False, True, Decimal('6.00'), 'Standard annual paid vacation entitlement'),
            ('Casual Leave', 'CL', Decimal('6.00'), True, True, False, False, Decimal('0.00'), 'Short-notice personal leave for unexpected events'),
            ('Sick Leave', 'SL', Decimal('6.00'), True, True, True, False, Decimal('0.00'), 'Health recuperation with supporting medical advice'),
            ('Leave Without Pay', 'LWP', Decimal('0.00'), False, True, False, False, Decimal('0.00'), 'Authorized unpaid absence beyond standard quota'),
        ]

        created_leave_types = {}
        for comp in [acme, zenith]:
            created_leave_types[comp.code] = {}
            for lt_name, lt_code, quota, paid, half_day, req_att, carry_fwd, max_cf, desc in leave_types_spec:
                lt, _ = LeaveType.objects.get_or_create(
                    company=comp,
                    code=lt_code,
                    defaults={
                        'name': lt_name,
                        'annual_quota': quota,
                        'is_paid': paid,
                        'allow_half_day': half_day,
                        'requires_attachment': req_att,
                        'is_carry_forward': carry_fwd,
                        'max_carry_forward_days': max_cf,
                        'description': desc,
                        'is_active': True,
                    }
                )
                created_leave_types[comp.code][lt_code] = lt

        # 12. Seed Leave Balances for 2026 for all Employees
        current_year = 2026
        for emp in Employee.objects.all():
            comp_types = created_leave_types.get(emp.company.code, {})
            for code, lt in comp_types.items():
                LeaveBalance.objects.get_or_create(
                    employee=emp,
                    leave_type=lt,
                    year=current_year,
                    defaults={
                        'allocated_days': lt.annual_quota,
                        'carried_forward_days': Decimal('2.00') if lt.is_carry_forward else Decimal('0.00'),
                        'accrued_days': Decimal('0.00'),
                        'used_days': Decimal('0.00'),
                        'pending_days': Decimal('0.00'),
                    }
                )

        # 13. Seed Sample Leave Applications
        emp1 = Employee.objects.filter(employee_id='ACME-EMP0004').first()
        emp2 = Employee.objects.filter(employee_id='ACME-EMP0005').first()
        emp3 = Employee.objects.filter(employee_id='ACME-EMP0006').first()
        mgr1 = Employee.objects.filter(employee_id='ACME-EMP0002').first()

        if emp1 and mgr1:
            pl_type = created_leave_types['ACMETEC']['PL']
            # Sample 1: Approved Leave
            app1, created1 = LeaveApplication.objects.get_or_create(
                employee=emp1,
                company=emp1.company,
                leave_type=pl_type,
                start_date=date(2026, 1, 15),
                end_date=date(2026, 1, 16),
                defaults={
                    'is_half_day': False,
                    'total_days': Decimal('2.00'),
                    'reason': 'Family religious gathering in hometown',
                    'status': LeaveApplication.ApplicationStatus.PENDING,
                }
            )
            if created1:
                bal1 = LeaveBalance.objects.filter(employee=emp1, leave_type=pl_type, year=2026).first()
                if bal1:
                    bal1.pending_days += Decimal('2.00')
                    bal1.save()
                app1.approve(mgr1.user)

        if emp2:
            cl_type = created_leave_types['ACMETEC']['CL']
            # Sample 2: Pending Leave
            app2, created2 = LeaveApplication.objects.get_or_create(
                employee=emp2,
                company=emp2.company,
                leave_type=cl_type,
                start_date=date(2026, 3, 10),
                end_date=date(2026, 3, 10),
                defaults={
                    'is_half_day': False,
                    'total_days': Decimal('1.00'),
                    'reason': 'Urgent bank documentation procedure',
                    'status': LeaveApplication.ApplicationStatus.PENDING,
                }
            )
            if created2:
                bal2 = LeaveBalance.objects.filter(employee=emp2, leave_type=cl_type, year=2026).first()
                if bal2:
                    bal2.pending_days += Decimal('1.00')
                    bal2.save()
                LeaveApprovalLog.objects.create(
                    application=app2,
                    action='Applied',
                    acted_by=emp2.user,
                    remarks='Submitted request for approval'
                )

        if emp3 and mgr1:
            sl_type = created_leave_types['ACMETEC']['SL']
            # Sample 3: Rejected Leave
            app3, created3 = LeaveApplication.objects.get_or_create(
                employee=emp3,
                company=emp3.company,
                leave_type=sl_type,
                start_date=date(2026, 2, 9),
                end_date=date(2026, 2, 11),
                defaults={
                    'is_half_day': False,
                    'total_days': Decimal('3.00'),
                    'reason': 'Viral fever and fatigue',
                    'status': LeaveApplication.ApplicationStatus.PENDING,
                }
            )
            if created3:
                bal3 = LeaveBalance.objects.filter(employee=emp3, leave_type=sl_type, year=2026).first()
                if bal3:
                    bal3.pending_days += Decimal('3.00')
                    bal3.save()
                app3.reject(mgr1.user, 'Medical certificate required for sick leave requests exceeding 2 days.')

        # 14. Seed January 2026 Monthly Payroll Run for both companies
        for comp, user_proc in [(acme, hr_user), (zenith, superadmin)]:
            run, created_run = PayrollRun.objects.get_or_create(
                company=comp,
                year=2026,
                month=1,
                defaults={
                    'notes': f'January 2026 Regular Salary Batch for {comp.name}',
                }
            )
            run.generate_payslips(user_proc)

            # Disburse payment for first 3 employees
            for p in run.payslips.all()[:3]:
                p.payment_status = Payslip.PaymentStatus.PAID
                p.payment_date = date(2026, 2, 1)
                p.payment_reference = f'NEFT-{comp.code}-20260201-{p.id:04d}'
                p.save()

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("  Phase 10 Demo Environment Successfully Initialized!"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"  Companies Created:    {Company.objects.count()} (ACMETEC, ZENITH)")
        self.stdout.write(f"  Departments Created:  {Department.objects.count()}")
        self.stdout.write(f"  Designations:         {Designation.objects.count()}")
        self.stdout.write(f"  Total Employees:      {Employee.objects.count()}")
        self.stdout.write(f"  Total Shifts:         {Shift.objects.count()}")
        self.stdout.write(f"  Attendance Records:   {Attendance.objects.count()} (Past 5 days + Today)")
        self.stdout.write(f"  Audit Trail Records:  {AttendanceAuditLog.objects.count()}")
        self.stdout.write(f"  Total Holidays:       {Holiday.objects.count()} (16 per company across 2026)")
        self.stdout.write(f"  Leave Types:          {LeaveType.objects.count()} (PL, CL, SL, LWP per company)")
        self.stdout.write(f"  Leave Balances:       {LeaveBalance.objects.count()} (Initialized for 2026)")
        self.stdout.write(f"  Leave Applications:   {LeaveApplication.objects.count()} (Approved, Pending, Rejected)")
        self.stdout.write(f"  Payroll Runs:         {PayrollRun.objects.count()} (January 2026 Batches)")
        self.stdout.write(f"  Payslips Generated:   {Payslip.objects.count()} (Calculated with LOP & OT)")
        self.stdout.write("=" * 70)
        self.stdout.write(f"{'Role':<15} | {'Username':<12} | {'Assigned Shift':<24} | {'Hours':<6}")
        self.stdout.write("-" * 70)
        self.stdout.write(f"{'HR Admin':<15} | {'hradmin':<12} | {'General (09:00 - 17:00)':<24} | {'8.00':<6}")
        self.stdout.write(f"{'Manager 1':<15} | {'manager1':<12} | {'General (09:00 - 17:00)':<24} | {'8.00':<6}")
        self.stdout.write(f"{'Employee 1':<15} | {'employee1':<12} | {'General (09:00 - 17:00)':<24} | {'8.00':<6}")
        self.stdout.write(f"{'Employee 2':<15} | {'employee2':<12} | {'Morning (06:00 - 14:00)':<24} | {'8.00':<6}")
        self.stdout.write(f"{'Employee 3':<15} | {'employee3':<12} | {'Evening (14:00 - 22:00)':<24} | {'8.00':<6}")
        self.stdout.write(f"{'Employee 4':<15} | {'employee4':<12} | {'Night (22:00 - 06:00)':<24} | {'8.00':<6}")
        self.stdout.write(f"{'Employee 5':<15} | {'employee5':<12} | {'12-Hour (08:00 - 20:00)':<24} | {'12.00':<6}")
        self.stdout.write("=" * 70 + "\n")
