===============================================
       BrainDock for Windows
       Quick Start Guide
===============================================

Thank you for downloading BrainDock!

FIRST-TIME LAUNCH
-----------------
Since this app is from an independent developer, Windows SmartScreen
may show a warning the first time you run it.

To open BrainDock:

1. Extract the ZIP file to a folder of your choice
   (Right-click > Extract All)

2. Open the extracted folder and double-click BrainDock.exe

3. If Windows SmartScreen appears with "Windows protected your PC":
   a. Click "More info"
   b. Click "Run anyway"

4. The app will now open, and you shouldn't see this warning again
   for this installation


PERMISSIONS
-----------
BrainDock needs access to your camera to monitor your focus.
When prompted, allow camera access.

You can manage camera permissions in:
Settings > Privacy > Camera


GETTING STARTED
---------------
1. Launch BrainDock.exe
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


TROUBLESHOOTING
---------------
If the app doesn't start:

1. Make sure you extracted the entire ZIP file, not just the .exe
   (All files in the folder are needed)

2. Try running as Administrator:
   Right-click BrainDock.exe > Run as administrator

3. Check if your antivirus is blocking the app
   You may need to add an exception for BrainDock

4. Make sure your webcam is connected and not in use by another app

If alert sounds don't play:
- Check your system volume is not muted
- The app uses Windows Media.SoundPlayer for audio

If Chrome/Edge URL detection doesn't work:
- Make sure the browser window is in the foreground
- The address bar must be visible (not in full-screen mode)


TESTING CHECKLIST (For Developers)
----------------------------------
Use this checklist to verify Windows 10/11 compatibility:

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
[Your support email/website here]


===============================================
         Enjoy focused studying!
===============================================
