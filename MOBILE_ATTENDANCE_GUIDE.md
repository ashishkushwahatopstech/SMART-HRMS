# Mobile Phone Camera Attendance & Live Server Guide &mdash; Smart HRMS

This comprehensive, step-by-step operational guide explains how to run Smart HRMS live on your network and use any mobile phone camera (or tablet mounted on an office wall) as a contactless biometric attendance kiosk.

---

## 1. Network & System Prerequisites

- **PC Host IP Address:** `10.27.5.77` *(or your local LAN/Wi-Fi IPv4 address)*
- **Wi-Fi Connectivity:** Both your Windows PC and your mobile phone **must be connected to the same Wi-Fi router / network hotspot**.
- **Supported Phone Browsers:**
  - **Android:** Google Chrome, Brave, Firefox, Edge, Samsung Internet
  - **iOS (iPhone/iPad):** Safari, Chrome

---

## 2. Starting the Live Server (Two Methods)

Mobile browsers enforce security policies that restrict camera access (`getUserMedia`) on network IP addresses unless running over **HTTPS (Secure Context)** or when explicitly whitelisted.

### Method A: HTTPS Mode (Recommended & Easiest for Mobile Phones)
This runs the built-in development SSL certificate so modern mobile browsers directly permit camera access:

```powershell
python manage.py runsslserver 0.0.0.0:8000
```

1. On your phone browser, navigate to:  
   **`https://10.27.5.77:8000/attendance/face-cam/`**
2. Your phone browser may display *"Your connection is not private"* (standard for local self-signed dev certificates).
   - Tap **Advanced** (or *Show Details*).
   - Tap **Proceed to 10.27.5.77 (unsafe)**.
3. The page will load securely over HTTPS.
4. When prompted: *"Allow Smart HRMS to use your camera?"* &rarr; Tap **Allow**!

---

### Method B: Standard HTTP Mode (With Chrome Insecure Flag)
If you prefer running standard HTTP:

```powershell
python manage.py runserver 0.0.0.0:8000
```

1. On your Android phone, open Chrome and type in the URL address bar:  
   `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
2. Set the dropdown to **Enabled**.
3. In the text box below it, enter:  
   `http://10.27.5.77:8000`
4. Tap the blue **Relaunch** button at the bottom.
5. Now open:  
   **`http://10.27.5.77:8000/attendance/face-cam/`**
6. Chrome will treat the IP as secure and allow full camera streaming!

---

## 3. Step-by-Step Biometric Attendance Walkthrough

Follow these 4 sequential steps to enroll an employee's face and punch attendance via phone camera:

### Step 1: Log in as HR Administrator
1. On your PC (or phone), open: `http://localhost:8000/accounts/login/` *(or via your LAN IP)*.
2. Sign in with HR Admin credentials:
   - **Username:** `hradmin`
   - **Password:** `Hradmin@123`

---

### Step 2: Enroll the Employee's Face Samples
1. In the sidebar, navigate to **Employees** (`/employees/`).
2. Click on the employee you wish to enroll (e.g., **A-EMP0004 &mdash; John Doe**).
3. In the employee profile header, click the blue **Enroll Face** button (or navigate to `/attendance/employees/4/enroll-face/`).
4. Click **Start Camera Stream** (allow camera access).
5. Look directly into the camera guide oval and click **Auto Capture (5 Samples)**.
   - Sample 1: Look straight forward (Front pose).
   - Sample 2: Turn head slightly to the left.
   - Sample 3: Turn head slightly to the right.
   - Sample 4: Tilt head slightly up.
   - Sample 5: Smile naturally.
6. The system captures the frames, extracts 200&times;200 normalized grayscale face crops, and trains the company's dedicated **LBPH Face Recognizer** model (`media/faces/ACMETEC/trainer.yml`).
7. The status updates to **Enrolled (Ready for Recognition)**.

---

### Step 3: Launch the Contactless Attendance Kiosk on Phone
1. Mount or position your smartphone at eye level facing the entrance or punch area.
2. Open the Kiosk URL in the phone's browser:
   - **`https://10.27.5.77:8000/attendance/face-cam/`** (if running `runsslserver`)
   - OR **`http://10.27.5.77:8000/attendance/face-cam/`** (if running `runserver`)
3. Tap **Start Biometric Scanner**.
4. The scanner activates:
   - The front-facing selfie camera turns on.
   - The animated cyan laser HUD sweeps across the screen.
   - The status bar displays `SCANNING: Looking for faces in camera view...`.

---

### Step 4: Stand Before Camera & Perform Punch
1. Bring your face into the camera viewport.
2. The computer vision engine:
   - Detects the face region using Haar Cascades.
   - Decodes and sends the frame to `/attendance/api/recognize-face/`.
   - Computes LBPH Euclidean distance confidence score.
   - Automatically determines punch type:
     - If employee has **not checked in today** &rarr; logs **CHECK-IN**.
     - If employee is **currently clocked in** &rarr; logs **CHECK-OUT**.
3. Feedback triggers instantly:
   - **Audio Chime:** A positive two-tone synthesizer chime (`A5 &rarr; D6`) plays through the phone speaker.
   - **Visual Pop-Up Card:** Flashes employee photo, name, designation, punch time, and confidence badge.
   - **Live Activity Feed:** Adds the verified punch to the live right-hand feed with timestamp.

---

## 4. Built-in Security & Safeguards

- **3-Minute Anti-Flood Cooldown:** Prevents continuous duplicate punches if an employee lingers near the camera station. Once punched, subsequent scans within 3 minutes are acknowledged without creating duplicate records.
- **Multi-Company Biometric Isolation:** OpenCV LBPH models are trained and saved per-company code. An employee from Acme Technologies cannot punch attendance at a Zenith Global kiosk.
- **Punctuality & Grace Period:** If the employee clocks in after their shift's scheduled grace period (e.g., General Shift 09:00 + 15 mins), the system automatically flags the record as `LATE` and records late minutes for payroll calculation.

---

## 5. Windows Firewall Troubleshooting

If your phone cannot reach your PC at `10.27.5.77:8000`:

1. Open **PowerShell as Administrator** on your Windows PC.
2. Allow incoming traffic on port 8000:
   ```powershell
   New-NetFirewallRule -DisplayName "Smart HRMS Dev Server" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
   ```
3. Test connectivity by opening `http://10.27.5.77:8000` in your PC's browser first.
4. Ensure your phone is connected to the same local Wi-Fi router (not mobile data).

---

## 6. Quick Reference URLs

### When running `runsslserver` (Current Live Mode - HTTPS):
| Screen / Feature | Local PC URL | Mobile Wi-Fi URL |
|---|---|---|
| **Main Dashboard** | `https://127.0.0.1:8000/` | `https://10.27.5.77:8000/` |
| **Live Face Attendance Kiosk** | `https://127.0.0.1:8000/attendance/face-cam/` | `https://10.27.5.77:8000/attendance/face-cam/` |
| **Face Biometric Enrollment** | `https://127.0.0.1:8000/attendance/employees/4/enroll-face/` | `https://10.27.5.77:8000/attendance/employees/4/enroll-face/` |
| **Daily Attendance Log** | `https://127.0.0.1:8000/attendance/` | `https://10.27.5.77:8000/attendance/` |
| **My Attendance (Self-Service)**| `https://127.0.0.1:8000/attendance/my/` | `https://10.27.5.77:8000/attendance/my/` |
| **Payroll Runs & Payslips** | `https://127.0.0.1:8000/payroll/` | `https://10.27.5.77:8000/payroll/` |
| **Reports & Excel Exports** | `https://127.0.0.1:8000/reports/` | `https://10.27.5.77:8000/reports/` |

*(Note: If you run standard `python manage.py runserver 0.0.0.0:8000` instead, replace `https://` with `http://`)*
