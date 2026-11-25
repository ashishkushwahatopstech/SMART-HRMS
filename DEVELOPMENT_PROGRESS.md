# Smart HRMS &mdash; Development Progress Tracker

## 1. Project Overview
- **Project Name:** Smart HRMS (Face Recognition Attendance, Payroll & Leave Management)
- **Target OS:** Windows PC (Local Network / Wi-Fi Mobile Camera Integration)
- **Framework:** Python 3.14 & Django 6.1 (Monolithic MVT Architecture)
- **UI Framework:** Bootstrap 5, Bootstrap Icons, Chart.js

---

## 2. Completed Phases

### [x] PHASE 1: Project Setup, Database, Authentication, Roles & Dashboard
- **Status:** Completed & Verified (13 Unit Tests Passing)
- **Summary:** Established modular Django architecture, custom user model with 4 distinct roles, role-based authorization decorators, responsive Bootstrap 5 dashboard with dynamic metrics and Chart.js visualizations, automated database migrations, safe demo data seed command, and test suite.

### [x] PHASE 2: Company, Department, Designation and Employee CRUD
- **Status:** Completed & Verified (23 Unit Tests Passing)
- **Summary:**
  - Implemented multi-company model (`companies.Company`) with corporate working schedule, weekly off rules, leave carry-forward caps, dynamic salary calculation policy, and timezone localization.
  - Implemented organizational structure: `Department` (unique per company) and `Designation` (unique per department).
  - Implemented full `Employee` CRUD with automatic ID generator (`COMPANY-EMP####`), compensation models (monthly fixed, daily wage, hourly wage), manager hierarchy, and biometric face registration flag.
  - Enforced strict **Multi-Company Data Isolation**: non-superusers can only access employees and divisions belonging to their contracted company.
  - Enforced **Employee Privacy Safeguards**: regular employees can view only their personal profile and cannot browse peer records.
  - Built comprehensive Bootstrap 5 UI: Company directory, detail view with policy cards, employee directory with multi-field search and filters, profile view with 5 history tabs, and department/designation management.
  - Enhanced demo seeder with 2 companies (`ACMETEC` and `ZENITH`), 5 departments, 9 designations, and 14 employees.

### [x] PHASE 3: Shift Management (8-Hour, 12-Hour, 24-Hour, Overnight Shifts & Grace Periods)
- **Status:** Completed & Verified (31 Unit Tests Passing)
- **Summary:**
  - Implemented configurable `Shift` model supporting standard 8-hour, extended 12-hour, 24-hour mission-critical, and customized rotations.
  - Built smart **Overnight / Cross-Midnight Schedule Handler**: shifts spanning across midnight (e.g. 10:00 PM to 06:00 AM) are automatically detected and bounded by window helper `get_shift_window(date)` so attendance punches do not split into different calendar days.
  - Implemented **Grace Period Engine**: configurable late arrival grace window in minutes (e.g. 15 mins) with boolean verification `is_check_in_late(time)`.
  - Implemented **Net Working Hours Calculation**: automatic deduction of unpaid lunch duration and tea breaks from gross shift duration.
  - Built `ShiftAssignment` historical audit trail: track when shifts are assigned or rotated, which HR administrator made the assignment, and keep the employee's active schedule synchronized.
  - Implemented Shift Deletion Safeguard: prevents deletion of any shift that currently has active employees assigned to it.
  - Enforced strict multi-company isolation on shift listings and assignment views.
  - Built Bootstrap 5 views: shift roster cards with timing badges, shift detail with break breakdown and assigned employee table, shift creation/editing form, shift deletion safeguard dialog, and batch shift assignment form.
  - Seeded 7 distinct corporate shifts and linked them to employees.

### [x] PHASE 4: Attendance Management (Daily Logs, Web Punches, Punctuality, Overtime & Audit Trail)
- **Status:** Completed & Verified (41 Unit Tests Passing)
- **Summary:**
  - Implemented core `Attendance` model with fields for employee, company, date, snapshot shift, check-in time, check-out time, status, verification method, working hours, overtime hours, late arrival flags, early departure flags, and punch IP address.
  - Built **Automated Punctuality & Grace Period Engine**: checks check-in time against shift start time + grace period to flag late arrival and calculate late minutes; checks check-out time against shift end time to flag early departures.
  - Built **Dynamic Overtime & Duration Calculator**: calculates actual hours worked and calculates overtime in excess of assigned shift hours.
  - Built **Cross-Midnight Overnight Attendance**: seamlessly handles overnight shifts (e.g. 10 PM to 6 AM) without date splitting.
  - Built **Self-Service Employee Portal (`/attendance/my/`)**: provides an interactive punch card for one-click check-in and check-out, monthly metrics (Days Present, Late Arrivals, Overtime Hours), and personal history log.
  - Built **HR Manual Adjustment System**: manual creation and adjustment forms with mandatory compliance audit reason.
  - Built **Compliance Audit Trail (`AttendanceAuditLog`)**: records who made manual adjustments, timestamps, field name, old values, new values, and business reasons.
  - Built **Daily Attendance Log Table (`/attendance/`)**: equipped with multi-filter bar (Date range, Department, Shift, Status, Employee Search), summary metric badges, and paginated roster.
  - Connected live attendance data directly to the **Main Dashboard (`/`)**: dynamic cards showing Present Today, Late Arrivals, Active Clocked-in Staff, and Absent Today, along with actual 6-day attendance trend charts.
  - Enhanced demo seeder with 65 attendance records across past 5 days and today.

### [x] PHASE 5 & 6: Face Recognition Biometrics (Enrollment, Local Webcam & Mobile Wi-Fi Camera Kiosk)
- **Status:** Completed & Verified (45 Unit Tests Passing)
- **Summary:**
  - Installed and configured native computer vision engine with `opencv-python` and `opencv-contrib-python` (running OpenCV 5.1).
  - Built **Biometric Engine (`attendance/biometrics.py`)**:
    - Frontal face Haar cascade detector integration (`cv2.CascadeClassifier`) with histogram equalization for contrast normalization.
    - Base64 video frame decoder (`decode_base64_image`) to seamlessly convert browser `<canvas>` frames to OpenCV BGR arrays.
    - Normalized 200x200 grayscale facial training frame processor (`save_face_sample`).
    - Dedicated multi-company isolated LBPH model trainer (`train_company_recognizer` saving to `media/faces/<company_code>/trainer.yml`) ensuring biometric models never cross corporate company boundaries.
    - Real-time video frame face recognizer (`recognize_face_in_frame`) predicting employee identity with human-readable confidence percentages.
  - Built **Face Biometric Enrollment Studio (`/attendance/employees/<id>/enroll-face/`)**:
    - Universal camera access via HTML5 `navigator.mediaDevices.getUserMedia` working on local laptop webcams AND mobile phone cameras over Wi-Fi.
    - Auto-capture sequence capturing 5 training frames across facial poses (front, slight left, slight right, tilt, smile) with progress bar and real-time guidance HUD.
    - Real-time training sample gallery with reset/re-enroll controls.
    - AJAX endpoints: `/attendance/api/save-sample/<id>/` and `/attendance/api/reset-face/<id>/`.
  - Built **Live Face Attendance Kiosk (`/attendance/face-cam/`)**:
    - Futuristic biometric scanning HUD with animated scanning laser, target bounding boxes, and real-time match feedback.
    - Continuous recognition loop streaming frames to `/attendance/api/recognize-face/`.
    - **Anti-flood 3-minute cooldown engine** to prevent duplicate punches when standing near the camera.
    - Automated punch registration: records **Check-In** if employee has not punched today; records **Check-Out** if currently clocked in.
    - Visual pop-up card displaying employee photo/avatar, full name, department, time, match confidence, and punch type.
    - Web Audio API synthesizer chime sound upon successful attendance punch.
    - Real-time sidebar activity feed displaying verified biometric punches today.
    - Wi-Fi mobile URL card displaying `http://<IP>:8000/attendance/face-cam/` for mounting smartphones on office walls as contactless punch stations.
  - Updated Employee profile biometrics tab with live enrollment status and direct action button.
  - Updated Sidebar navigation to link directly to Face Recognition Cam.

### [x] PHASE 7: Holiday Calendar (Corporate Holiday Lists, Mandatory/Optional Holidays, Weekly Offs & Calendar Views)
- **Status:** Completed & Verified (54/54 Total Unit Tests Passing)
- **Summary:**
  - Implemented `Holiday` model with support for Gazetted/Mandatory holidays, Optional/Restricted holidays, and Company Observances with strict `unique_holiday_per_company_per_date` constraint.
  - Implemented core corporate calendar engine:
    - `is_working_day(company, target_date)`: automatically resolves weekly off policy (`SATURDAY_SUNDAY` vs `SUNDAY_ONLY`) and mandatory public holidays.
    - `get_working_days_in_month(company, year, month)`: computes exact count of working days in a calendar month for actual working day salary calculation policies.
  - Built **Interactive Monthly Visual Calendar Grid (`/holidays/calendar/`)**:
    - Full 7-column calendar matrix highlighting color-coded public holidays and scheduled weekly offs.
    - Month navigation controls (previous month, next month, jump to today).
    - Monthly summary statistics bar (Total holidays, working days count, weekly off policy badge).
  - Built **Corporate Holiday Table Roster (`/holidays/`)**:
    - Multi-field search, year selection, holiday type filter, and superuser company dropdown.
    - Dual tabs for "Full Year Schedule" vs "Upcoming Only".
    - Metric cards (Total Observed, Mandatory, Optional, Upcoming Remaining).
  - Built HR CRUD views with zero-collision safeguards: `holiday_create`, `holiday_edit`, `holiday_delete`.
  - Built JSON API endpoint (`/holidays/api/`) providing structured events for dynamic calendar widgets.
  - Connected live Upcoming Holidays widget to the Main Dashboard (`/`).
  - Seeded 32 corporate holidays (16 for Acme Technologies and 16 for Zenith Global Solutions across 2026).

### [x] PHASE 10: Payroll Engine (Salary Structure, Working Day Policies, LWP Deductions, Overtime Pay & Payslips)
- **Status:** Completed & Verified (71/71 Total Unit Tests Passing)
- **Summary:**
  - Implemented core `payroll` models:
    - `PayrollRun`: Monthly batch payroll processing per company with year, month, total gross, deductions, net pay, total employee count, processing timestamps, and lock status (`DRAFT`, `PROCESSED`, `LOCKED`) with unique constraint `(company, year, month)`.
    - `Payslip`: Comprehensive individual employee compensation record with calendar days, working days, present days, paid leaves, unpaid LOP days, overtime hours, per-day rate, hourly rate, gross earnings, itemized statutory deductions (PF 12%, ESI 0.75%, Professional Tax ₹200, TDS), net pay, and disbursal tracking with unique constraint `(employee, year, month)`.
  - Built **Flexible Multi-Policy Salary Engine (`payroll/engine.py`)**:
    - **Policy A (Actual Working Days)**: Divides monthly compensation by exact working days in the month using `Holiday.get_working_days_in_month(company, year, month)` (e.g. 21 days in Jan 2026 for 5-day week companies).
    - **Policy B (Fixed 26 Days)**: Divides monthly compensation by fixed 26 days.
    - **Policy C (Fixed 30 Days)**: Divides monthly compensation by 30 days.
    - Verified Section 12 Trainee case: ₹9,000 monthly salary yields ₹428.57/day under Policy A vs. ₹346.15/day under Policy B.
  - Built **Automated Loss of Pay (LOP) & Overtime Calculator**:
    - Aggregates approved unpaid leaves (LWP) and unexcused absences, deducting `unpaid_days * per_day_rate`.
    - Computes overtime pay at 1.5x hourly rate (`total_ot_hours * hourly_rate * 1.5`).
  - Built **Currency Words Engine (`number_to_words_inr`)**:
    - Converts numerical net salaries into formal Indian Rupee currency words (e.g. ₹45,200 -> *"Rupees Forty Five Thousand Two Hundred Only"*).
  - Built Complete User Interface:
    - **Payroll Dashboard (`/payroll/`)**: Monthly runs ledger with roll-up metrics (Total Disbursed, Total Gross, Total Deductions) and status filters.
    - **Payroll Batch Creation Form (`/payroll/runs/create/`)**: Allows HR / Super Admin to trigger automated calculation for all active company employees.
    - **Payroll Register View (`/payroll/runs/<id>/`)**: Table of all employee payslips with search, recalculate, and lock controls.
    - **Printable Corporate Payslip View (`/payroll/payslips/<id>/`)**: Company letterhead, employee details, attendance summary, earnings vs deductions columns, net pay highlight, and print button with `@media print` layout.
    - **Self-Service Payslip Portal (`/payroll/my-payslips/`)**: Allows employees to view and print their own salary statements with strict privacy safeguards.
  - Enhanced demo seeder with January 2026 payroll runs for both Acme and Zenith, generating 13 payslips with sample paid disbursals.
  - 8 unit tests passing covering salary policies, LOP deductions, overtime additions, currency formatting, run generation, locking safeguards, and privacy scoping.

### [x] PHASE 11: Reports & Data Exports (Attendance Muster, Payroll Ledger, Leave Summary & Directory)
- **Status:** Completed & Verified (77/77 Total Unit Tests Passing)
- **Summary:**
  - Installed and configured `openpyxl` alongside `pandas` for native Excel (`.xlsx`) and CSV (`.csv`) export generation.
  - Built **Reporting Service Engine (`reports/services.py`)**:
    - `generate_attendance_muster`: Generates full 1-to-N monthly attendance matrix with daily status codes (`P`, `L`, `HD`, `A`, `OL`, `WO`, `H`), attendance totals, late arrival counts, and overtime hours.
    - `generate_payroll_ledger`: Generates full monthly salary register with working days, allowances, overtime pay, LOP deductions, statutory taxes, and bank transfer references.
    - `generate_leave_summary`: Generates annual leave entitlement roster showing base quota, carried-forward days, accrued days, utilized days, and remaining available balances per employee.
    - `generate_employee_directory`: Exports master employee database for compliance and auditing.
  - Built **Interactive Reports Center (`/reports/`)**:
    - 4 responsive report download cards with company selectors, year/month dropdowns, format toggles (Excel vs CSV), and one-click export actions.
  - Activated sidebar navigation link for `Reports & Exports`.
  - 6 unit tests passing covering Excel generation, CSV generation, data formatting, and role authorization.

---

## 3. Project Status & Test Suite Summary
- **Current Status:** All Phases 1 Through 11 Fully Complete & Verified!
- **Total Passing Unit Tests:** **77 / 77 Unit Tests Passing (100% Pass Rate)**
  - `accounts`: 13 tests
  - `companies`: 4 tests
  - `employees`: 6 tests
  - `shifts`: 8 tests
  - `attendance`: 10 tests
  - `holidays`: 9 tests
  - `leaves`: 9 tests
  - `payroll`: 8 tests
  - `reports`: 6 tests
  - `dashboard`: system verified

---

## 4. Complete Files Created in Phases 10 & 11

| File Path | Description |
|---|---|
| `payroll/models.py` | `PayrollRun` and `Payslip` models with batch generator and locking methods |
| `payroll/engine.py` | Salary calculation policy engine (Actual working days / 26 days fixed / 30 days), LOP deduction, overtime pay, and `number_to_words_inr` |
| `payroll/forms.py` | `PayrollRunCreateForm`, `PayslipPaymentUpdateForm`, and `PayrollFilterForm` |
| `payroll/views.py` | `payroll_dashboard`, `payroll_run_create`, `payroll_run_detail`, `payroll_run_recalculate`, `payroll_run_lock`, `payslip_detail`, `update_payslip_payment`, `my_payslips` |
| `payroll/urls.py` | Payroll routing (`/payroll/`) |
| `payroll/admin.py` | Django admin configuration with inlines and filters |
| `payroll/tests.py` | 8 unit tests covering rate policies, LOP deduction, overtime, currency words, run locking, and employee privacy |
| `payroll/migrations/0001_initial.py` | Initial migration creating `PayrollRun` and `Payslip` tables |
| `templates/payroll/payroll_dashboard.html` | Monthly payroll runs overview with metric cards and filters |
| `templates/payroll/payroll_run_create.html` | Batch payroll initiation form |
| `templates/payroll/payroll_run_detail.html` | Detailed payroll register table with search and lock controls |
| `templates/payroll/payslip_detail.html` | Printable corporate payslip with print styling and payment tracking |
| `templates/payroll/my_payslips.html` | Self-service employee payslip portal |
| `reports/services.py` | Export services for attendance muster, payroll register, leave summary, and employee directory in Excel and CSV formats using pandas & openpyxl |
| `reports/views.py` | `reports_dashboard` and download handlers (`export_attendance_report`, `export_payroll_report`, `export_leave_report`, `export_employee_report`) |
| `reports/urls.py` | Reports routing (`/reports/`) |
| `reports/tests.py` | 6 unit tests covering Excel and CSV exports and authorization |
| `templates/reports/reports_dashboard.html` | Reports download center with format toggles and date pickers |
| `templates/includes/sidebar.html` | Activated Payroll Engine, My Payslips, and Reports & Exports navigation links |
| `dashboard/views.py` | Connected live pending leave alerts and latest payroll run metrics to main dashboard |
| `templates/dashboard/index.html` | Added pending leave request alerts and updated project roadmap to All Phases Complete |
| `accounts/management/commands/setup_phase1_demo.py` | Seeded January 2026 payroll runs and 13 payslips for Acme and Zenith |
| `DEVELOPMENT_PROGRESS.md` | Updated to Phases 10 & 11 Complete (77/77 Unit Tests Passing) |
