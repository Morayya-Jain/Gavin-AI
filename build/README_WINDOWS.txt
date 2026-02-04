===============================================
       BrainDock for Windows
       Quick Start Guide
===============================================

Thank you for downloading BrainDock!


INSTALLATION
------------
1. Run BrainDock-Setup.exe

2. If Windows SmartScreen appears with "Windows protected your PC":
   a. Click "More info"
   b. Click "Run anyway"
   
   Note: This warning appears because the app is from an independent
   developer. The app is safe to install.

3. Follow the installation wizard:
   - Accept the license agreement
   - Choose installation location (default: C:\Program Files\BrainDock)
   - Click Install

4. The installer will create:
   - Start Menu shortcut (BrainDock folder)
   - Desktop shortcut
   - Uninstaller entry in Windows Settings


LAUNCHING BRAINDOCK
-------------------
After installation, you can launch BrainDock by:

- Clicking the Desktop shortcut
- Searching "BrainDock" in the Start Menu
- Opening from: C:\Program Files\BrainDock\BrainDock.exe


PERMISSIONS
-----------
BrainDock needs access to your camera to monitor your focus.
When prompted, allow camera access.

You can manage camera permissions in:
Settings > Privacy & Security > Camera


GETTING STARTED
---------------
1. Launch BrainDock
2. Complete payment via Stripe (if first launch)
3. Click "Start Session" to begin focus tracking
4. The app will monitor your presence and detect distractions
5. Click "Stop Session" when done to generate your report


REPORTS
-------
PDF reports are saved to your Downloads folder.


SCREEN MONITORING (Chrome/Edge URL Detection)
----------------------------------------------
BrainDock can detect distracting websites in Chrome and Microsoft Edge.
When you add a URL to your blocklist (e.g., youtube.com), the app will
detect when you visit that site and mark it as a distraction.

This feature uses Windows UI Automation to read the browser's address bar.
No special permissions are required - it works automatically.


UNINSTALLING
------------
To uninstall BrainDock:

1. Open Windows Settings
2. Go to Apps > Installed apps
3. Find "BrainDock" in the list
4. Click the three dots menu > Uninstall

Or use the uninstaller shortcut in the Start Menu:
Start > BrainDock > Uninstall BrainDock


TROUBLESHOOTING
---------------

"Unable to open file in temporary directory" Error:
This usually happens when antivirus software interferes with the installer.

1. Temporarily disable Windows Defender real-time protection:
   Settings > Privacy & Security > Windows Security > Virus & threat protection
   > Manage settings > Turn off "Real-time protection"
   
2. Run the installer again

3. Re-enable real-time protection after installation completes

4. Add an exclusion for BrainDock:
   Windows Security > Virus & threat protection > Manage settings
   > Exclusions > Add exclusion > Folder
   Add: C:\Program Files\BrainDock

If the app doesn't start:

1. Try running as Administrator:
   Right-click BrainDock shortcut > Run as administrator

2. Check if your antivirus is blocking the app
   You may need to add an exception for BrainDock

3. Make sure your webcam is connected and not in use by another app

4. Reinstall the application

If alert sounds don't play:
- Check your system volume is not muted
- The app uses Windows winsound module for audio (with PowerShell fallback)

If Chrome/Edge URL detection doesn't work:
- Make sure the browser window is in the foreground
- The address bar must be visible (not in full-screen mode)


DATA LOCATIONS
--------------
BrainDock stores user data in:
  %APPDATA%\BrainDock\

This includes:
  - Session data
  - Blocklist settings
  - License information

PDF reports are saved to:
  %USERPROFILE%\Downloads\


TESTING CHECKLIST (For Developers)
----------------------------------
Use this checklist to verify Windows 10/11 compatibility:

[ ] Installation: Installer runs and completes successfully
[ ] Start Menu: Shortcut appears and works
[ ] Desktop: Shortcut appears and works  
[ ] Uninstall: App removes cleanly via Settings
[ ] Sound playback: Alert sound plays when distraction detected
[ ] Chrome URL detection: Blocklist entries like "youtube.com" trigger correctly
[ ] Edge URL detection: Same functionality works in Microsoft Edge
[ ] PDF emoji rendering: Reports show emojis correctly
[ ] Screen monitoring: App names detected correctly for non-elevated apps
[ ] Stripe payment: Checkout flow completes without SSL errors
[ ] Camera access: Webcam opens and detects presence
[ ] Instance lock: Only one instance can run at a time


SUPPORT
-------
If you have any issues, please contact:
Email: morayyajain@gmail.com
Website: https://thebraindock.com


===============================================
         Enjoy focused studying!
===============================================
