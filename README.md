# Smart HRMS &mdash; Enterprise Face Recognition Attendance, Payroll & Leave Management System

[![Python 3.14](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![Django 6.1](https://img.shields.io/badge/Django-6.1-green.svg)](https://www.djangoproject.com/)
[![OpenCV 5.1](https://img.shields.io/badge/OpenCV-5.1.0--contrib-red.svg)](https://opencv.org/)
[![Test Suite](https://img.shields.io/badge/Tests-77%20Passing-brightgreen.svg)]()
[![Platform](https://img.shields.io/badge/Platform-Windows%20PC%20%7C%20Wi--Fi%20Kiosk-lightgrey.svg)]()

Smart HRMS is an enterprise-grade Human Resource Management System built on Python 3.14 and Django 6.1. It combines multi-tenant corporate HR administration with real-time biometric face recognition, automated punctuality scoring, dynamic shift scheduling, public holiday-aware leave balance deduction, and a comprehensive payroll engine supporting both actual business working days and fixed-rate policies.

---

## 1. System Architecture & Tech Stack

```
Smart HRMS Architecture
├── Monolithic MVT Engine: Python 3.14, Django 6.1
├── Database Layer: SQLite 3 (Production schema with ACID constraints & foreign keys)
├── Computer Vision Biometrics: OpenCV 5.1 (Haar Cascade + LBPH Face Recognizer)
├── Data Analysis & Exporting: Pandas & Openpyxl (Excel .xlsx & CSV formats)
├── UI & UX Styling: Bootstrap 5, Bootstrap Icons, Chart.js, HTML5 Canvas & Web Audio API
└── Network Topology: Localhost + LAN Wi-Fi support (Mobile phone wall-mounted kiosk)
```

---

## 2. Default Demo Login Credentials

The system comes pre-loaded with a comprehensive enterprise demo dataset covering two companies: **Acme Technologies Pvt Ltd (`ACMETEC`)** and **Zenith Global Solutions Ltd (`ZENITH`)**.

| Role | Username | Password | Notes & Authority Scope |
|---|---|---|---|
| **Super Admin** | `superadmin` | `Admin@123` | Master system superuser with full global multi-company access. |
| **HR Administrator** | `hradmin` | `Hradmin@123` | Head of People Operations for Acme Technologies (isolated to ACMETEC). |
| **Engineering Manager** | `manager1` | `Manager@123` | Reports to HR; manages Employee 1, 2, 3, 4, 6, 7, 9, 10. |
| **Sales Manager** | `manager2` | `Manager@123` | Reports to HR; manages Employee 8. |
| **Employee 1 (Senior Dev)** | `employee1` | `Employee@123` | General Shift (09:00 - 17:00), ₹50,000/mo, face enrolled. |
| **Employee 2 (DevOps)** | `employee2` | `Employee@123` | Morning Shift (06:00 - 14:00), ₹45,000/mo. |
| **Employee 3 (DBA)** | `employee3` | `Employee@123` | Evening Shift (14:00 - 22:00), ₹48,000/mo. |
| **Employee 4 (Support Eng)**| `employee4` | `Employee@123` | Overnight Shift (22:00 - 06:00 cross-midnight), ₹52,000/mo. |
| **Employee 5 (Finance)** | `employee5` | `Employee@123` | 12-Hour Critical Shift (08:00 - 20:00), ₹55,000/mo. |
| **Employee 6 (Trainee)** | `employee6` | `Employee@123` | Trainee, ₹9,000/mo (Policy comparison reference). |
| **Employee 7 (Contract)** | `employee7` | `Employee@123` | Daily Wage Contract Worker, ₹15,000/mo. |
| **Employees 8 &ndash; 10** | `employee8`..`10` | `Employee@123` | Standard self-service employee portals. |

---

## 3. Quick Start & Execution Guide

### 3.1 Initializing the Database & Seeding Data
Run the following commands in PowerShell from the project root:

```powershell
# 1. Apply all migrations
python manage.py migrate

# 2. Seed all 11 phases of demo data (Companies, Employees, Shifts, Holidays, Leaves, Payroll)
python manage.py setup_phase1_demo
```

### 3.2 Starting the Development Server
To enable local PC access and mobile phone camera stations on the same Wi-Fi network:

```powershell
python manage.py runserver 0.0.0.0:8000
```

- **Local PC Portal:** [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Mobile Wi-Fi Attendance Kiosk:** `http://<YOUR_LOCAL_IP>:8000/attendance/face-cam/`

---

## 4. Module-by-Module Features (Phases 1 &ndash; 11)

### Phase 1: Authentication, Custom User Model & Base Dashboard
- Custom User Model (`accounts.User`) with 4 distinct roles: Super Admin, HR Admin, Manager, and Employee.
- Role-based authorization decorators (`@super_admin_required`, `@hr_admin_required`, `@manager_required`).
- Main interactive dashboard with dynamic metric cards, Chart.js role doughnut chart, and live weekly attendance trend bars.

### Phase 2: Multi-Company, Organizational Structure & Privacy
- `Company` model encapsulating weekly off policies, working days per week, and salary calculation policy.
- `Department` and `Designation` with unique constraints per company.
- `Employee` model with automatic ID generation (`COMPANY-EMP####`), compensation models, manager hierarchy, and face registration flag.
- Strict **Multi-Company Data Isolation**: non-superusers can only access employees and divisions belonging to their contracted company.
- Strict **Employee Privacy Safeguards**: regular employees can view only their personal profile and cannot browse peer records.

### Phase 3: Shift Management & Overnight Windows
- Supports standard 8-hour, extended 12-hour, 24-hour mission-critical, and customized rotations.
- **Overnight Schedule Handler:** Shifts spanning across midnight (e.g. 10:00 PM to 06:00 AM) are automatically bounded by `get_shift_window(date)` so attendance punches do not split into different calendar days.
- **Grace Period Engine:** Configurable late arrival grace window in minutes (e.g. 15 mins).
- **Net Working Hours Calculation:** Automatic deduction of unpaid lunch duration and tea breaks from gross shift duration.
- `ShiftAssignment` audit trail tracking schedule rotations with safeguard preventing deletion of active shifts.

### Phase 4: Daily Attendance & Compliance Audit Trail
- Daily `Attendance` records with check-in, check-out, working hours, overtime hours, and punch IP address.
- Automated Punctuality Engine: flags late arrivals past grace period and computes late minutes; detects early departures before shift end.
- Self-Service Employee Portal (`/attendance/my/`) for one-click web punches and personal history.
- HR Manual Clock Correction system backed by immutable `AttendanceAuditLog` recording changed fields, old values, new values, and mandatory business justifications.

### Phase 5 & 6: Computer Vision Biometrics & Contactless Attendance Kiosk
- Native computer vision using `opencv-contrib-python-5.1.0.95`.
- **Biometric Enrollment Studio (`/attendance/employees/<id>/enroll-face/`):** Universal camera access via HTML5 `getUserMedia` capturing 5 pose frames with Haar cascade face detection and grayscale ROI normalization.
- Multi-company isolated LBPH model training (`media/faces/<company>/trainer.yml`) ensuring biometric models never cross corporate boundaries.
- **Live Attendance Kiosk (`/attendance/face-cam/`):**
  - Futuristic scanning laser HUD with target bounding box.
  - Web Audio API synthesizer chime sound on verification.
  - **Anti-flood 3-minute cooldown engine** preventing duplicate punches when standing near the camera.
  - Automatically records **Check-In** if employee has not punched today, or **Check-Out** if currently clocked in.
  - Works on laptop webcams AND mobile smartphones on the same Wi-Fi.

### Phase 7: Corporate Holiday Calendar
- Configurable `Holiday` model supporting Gazetted/Mandatory holidays, Optional/Restricted holidays, and Company Observances.
- Core calculation engine:
  - `is_working_day(company, target_date)`: resolves 5-day vs 6-day weekly offs and mandatory public holidays.
  - `get_working_days_in_month(company, year, month)`: computes exact count of actual working days in a month.
- Interactive Monthly Visual Calendar Grid (`/holidays/calendar/`) and full tabular holiday roster.

### Phase 8 & 9: Leave Management & Attendance Synchronization
- Configurable `LeaveType` (Paid Leave, Casual Leave, Sick Leave, Leave Without Pay) with quotas, half-day permission, mandatory attachment rules, and carry-forward caps.
- `LeaveBalance` tracking base quota, carry-forward, accrued, used, pending, and available days.
- **Non-Working Day Auto-Exclusion:** Automatically queries `Holiday.is_working_day` across requested dates to exclude weekends and public holidays from being charged against employee balances.
- Live Net Days & Balance API (`/leaves/api/calculate-days/`) providing instant validation during application.
- Multi-tier workflow: approving a request moves days from pending to used on the balance ledger and automatically creates/syncs `Attendance` records as `status='on_leave'`.

### Phase 10: Payroll Engine & Payslips
- `PayrollRun` monthly batch execution per company with locking controls (`DRAFT`, `PROCESSED`, `LOCKED`).
- **Flexible Multi-Policy Salary Engine:**
  - **Policy A (Actual Working Days):** `Per_Day_Rate = Monthly_Salary / Actual_Working_Days_In_Month` (e.g. 21 days in Jan 2026 for 5-day week companies; ₹9,000 trainee salary yields ₹428.57/day).
  - **Policy B (Fixed 26 Days):** `Per_Day_Rate = Monthly_Salary / 26` (yields ₹346.15/day).
  - **Policy C (Fixed 30 Days):** `Per_Day_Rate = Monthly_Salary / 30`.
- Automated Loss of Pay (LOP) deduction (`unpaid_days * per_day_rate`) and Overtime pay (1.5x hourly rate).
- Statutory deductions: Provident Fund (12% of basic), ESI (0.75%), Professional Tax (₹200).
- `number_to_words_inr`: Generates net salary in formal Indian Rupee words (e.g. *"Rupees Forty Five Thousand Two Hundred Only"*).
- Printable corporate payslip view (`/payroll/payslips/<id>/`) with company letterhead, attendance summary, earnings vs deductions columns, and `@media print` layout.
- Self-service "My Payslips" portal for employees.

### Phase 11: Reports & Data Exports
- Powered by `pandas` and `openpyxl` with dual Excel (`.xlsx`) and CSV (`.csv`) export formats.
- **Attendance Muster Sheet (`/reports/export/attendance/`):** Full 1-to-N monthly attendance matrix with status markers (`P`, `L`, `HD`, `A`, `OL`, `WO`, `H`), late arrival counts, and overtime hours.
- **Payroll Disbursal Ledger (`/reports/export/payroll/`):** Monthly salary breakdown with gross pay, deductions, net salary, and bank transfer reference numbers.
- **Leave Quota Summary (`/reports/export/leaves/`):** Annual entitlement, utilization, and remaining balance report.
- **Employee Master Directory (`/reports/export/employees/`):** Complete employee database for compliance and auditing.

---

## 5. Verification & Test Suite

The project includes an automated test suite verifying all business logic, multi-company isolation, mathematical accuracy, and permission checks.

To execute the complete test suite:

```powershell
python manage.py test
```

### Test Suite Summary:
```
Ran 77 tests in 144.931s
OK
System check identified no issues (0 silenced).
```

| Application | Test Count | Test Coverage |
|---|:---:|---|
| `accounts` | 13 | User roles, RBAC permissions, profile edits, password updates |
| `companies` | 4 | Multi-tenant isolation, working day and weekly holiday policies |
| `employees` | 6 | Auto ID generation, compensation models, manager hierarchy, privacy |
| `shifts` | 8 | Overnight shifts, grace periods, net working hours, assignment audit |
| `attendance` | 10 | Daily punches, punctuality engine, overtime calculation, audit log |
| `holidays` | 9 | Mandatory/optional holidays, calendar matrix, working days logic |
| `leaves` | 9 | Quotas, non-working day auto-exclusion, approvals, attendance sync |
| `payroll` | 8 | Rate policies (Actual vs 26-day), LOP deductions, overtime, payslips |
| `reports` | 6 | Excel/CSV muster sheets, payroll ledgers, leave summaries, directory |
| **Total** | **77** | **100% Pass Rate Across All 9 Modules** |

---

## 6. Project Directory Map

```
HRMS/
├── accounts/         # Custom User model, RBAC, authentication, profile
├── attendance/       # Punches, punctuality, audit log, OpenCV face biometrics
├── companies/        # Multi-company multi-tenant corporate policies
├── config/           # Django settings, root URLs, WSGI/ASGI
├── dashboard/        # Main landing dashboard, metric cards, Chart.js trends
├── employees/        # Employee profiles, departments, designations, privacy
├── holidays/         # Corporate holiday calendar, monthly grid, working day engine
├── leaves/           # Leave quotas, balances, working day auto-exclusion, approvals
├── payroll/          # Salary policy engine, LOP, overtime pay, payslips
├── reports/          # Excel & CSV export services for muster, payroll & leaves
├── shifts/           # Shifts, overnight window handler, grace periods, audit
├── static/           # CSS stylesheets, branding assets, custom scripts
├── templates/        # Bootstrap 5 HTML templates organized by application
├── DEVELOPMENT_PROGRESS.md # Phase-by-phase implementation log
├── manage.py         # Django CLI entrypoint
└── README.md         # System manual and deployment guide
```
