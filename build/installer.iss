; =============================================================================
; BrainDock Windows Installer Script (Inno Setup)
; =============================================================================
;
; This script creates a professional Windows installer for BrainDock.
; It requires Inno Setup 6.x: https://jrsoftware.org/isdl.php
;
; Usage:
;   1. Build the app with PyInstaller first (build_windows.ps1 handles this)
;   2. Run: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;
; The output will be: dist\BrainDock-{VERSION}-Setup.exe
;
; =============================================================================

#define MyAppName "BrainDock"
; Version is the single source of truth - build_windows.ps1 reads this value
#define MyAppVersion "1.0.0"
#define MyAppPublisher "BrainDock"
#define MyAppURL "https://thebraindock.com"
#define MyAppExeName "BrainDock.exe"
#define MyAppDescription "AI-powered focus tracking application"

[Setup]
; Application identity
AppId={{8F7D3A2E-5B4C-4D6E-9A1F-2C3B4D5E6F7A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Installation directories
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}

; Output settings
OutputDir=..\dist
OutputBaseFilename=BrainDock-Setup
; Use zip compression for fastest installation speed
; Trade-off: ~20-25% larger installer but 5-10x faster to install
Compression=zip/9
SolidCompression=no

; Appearance - BrainDock branding
SetupIconFile=icon.ico
WizardStyle=modern
WizardSizePercent=100

; Uninstaller settings
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

; Version info embedded in the installer exe
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppDescription}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

; Privileges - install for current user by default, allow admin install
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Disable features we don't need
DisableProgramGroupPage=yes
DisableWelcomePage=no

; Allow user to see what's happening
ShowLanguageDialog=auto

; Minimum Windows version (Windows 10+)
MinVersion=10.0

; Performance and compatibility settings
; Helps with "Unable to open file in temporary directory" errors
DisableStartupPrompt=yes
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

; Use 32-bit installer for maximum compatibility (runs on both 32/64-bit Windows)
; Note: The app itself is still 64-bit, this just affects the installer stub
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Include all files from the PyInstaller output
Source: "..\dist\BrainDock\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Include README for Windows users
Source: "README_WINDOWS.txt"; DestDir: "{app}"; Flags: ignoreversion; DestName: "README.txt"

[Icons]
; Start Menu shortcut with BrainDock icon
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Comment: "{#MyAppDescription}"

; Start Menu uninstall shortcut
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\{#MyAppExeName}"

; Desktop shortcut with BrainDock icon (always created)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Comment: "{#MyAppDescription}"

[Run]
; Option to launch the app after installation
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up any files created during runtime (user data is stored elsewhere)
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\*.pyc"

[Code]
// Pascal script for custom installer behavior

// Check if application is already running
function IsAppRunning(): Boolean;
var
  ResultCode: Integer;
begin
  // Use tasklist to check if BrainDock.exe is running
  Result := False;
  if Exec('cmd.exe', '/c tasklist /FI "IMAGENAME eq BrainDock.exe" | find /i "BrainDock.exe"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Result := (ResultCode = 0);
  end;
end;

// Warn user if app is running before install
function InitializeSetup(): Boolean;
begin
  Result := True;
  
  if IsAppRunning() then
  begin
    if MsgBox('BrainDock is currently running.' + #13#10 + #13#10 +
              'Please close BrainDock before continuing with the installation.' + #13#10 + #13#10 +
              'Click OK to continue anyway, or Cancel to exit setup.',
              mbConfirmation, MB_OKCANCEL) = IDCANCEL then
    begin
      Result := False;
    end;
  end;
end;

// Warn user if app is running before uninstall
function InitializeUninstall(): Boolean;
begin
  Result := True;
  
  if IsAppRunning() then
  begin
    if MsgBox('BrainDock is currently running.' + #13#10 + #13#10 +
              'Please close BrainDock before uninstalling.' + #13#10 + #13#10 +
              'Click OK to continue anyway, or Cancel to exit.',
              mbConfirmation, MB_OKCANCEL) = IDCANCEL then
    begin
      Result := False;
    end;
  end;
end;
