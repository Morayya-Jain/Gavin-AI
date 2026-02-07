# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for BrainDock

This creates standalone executables for macOS and Windows.
Run with: pyinstaller build/braindock.spec

For macOS: Creates BrainDock.app bundle
For Windows: Creates BrainDock.exe
"""

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

# Get the project root directory
SPEC_DIR = Path(SPECPATH)
PROJECT_ROOT = SPEC_DIR.parent

# Platform detection
IS_MACOS = sys.platform == 'darwin'
IS_WINDOWS = sys.platform == 'win32'

# Icon paths
ICON_ICNS = str(SPEC_DIR / 'icon.icns')
ICON_ICO = str(SPEC_DIR / 'icon.ico')

# Choose icon based on platform
if IS_MACOS:
    ICON = ICON_ICNS if os.path.exists(ICON_ICNS) else None
else:
    ICON = ICON_ICO if os.path.exists(ICON_ICO) else None

# Data files to include
# Format: (source_path, destination_folder)
datas = [
    # Data files
    (str(PROJECT_ROOT / 'data' / 'focus_statements.json'), 'data'),
    (str(PROJECT_ROOT / 'data' / 'braindock_alert_sound.mp3'), 'data'),
    (str(PROJECT_ROOT / 'data' / 'braindock_alert_sound.wav'), 'data'),  # WAV for Windows
    # Assets (includes fonts in assets/fonts/ for cross-platform typography)
    # Bundled fonts: Inter (sans-serif), Lora (serif) - both SIL Open Font License
    (str(PROJECT_ROOT / 'assets'), 'assets'),
]

# Add bundled_keys.py if it exists (generated at build time with API keys)
bundled_keys_path = PROJECT_ROOT / 'bundled_keys.py'
if bundled_keys_path.exists():
    datas.append((str(bundled_keys_path), '.'))
else:
    print("WARNING: bundled_keys.py not found - API keys will not be embedded!")

# Note: SSL certificates are handled automatically by PyInstaller's certifi hook
# (hook-certifi.py from pyinstaller-hooks-contrib)

# Windows-only: Bundle timezone data (tzdata package)
# On Windows, Python uses tzdata for timezone info since the OS doesn't have
# built-in IANA timezone data like macOS/Linux. Without bundling this,
# the app shows "Downloading America/New_York..." popups on first launch
# as it extracts 600+ timezone files, causing a 5+ minute delay.
# macOS has /usr/share/zoneinfo/ built-in, so this is not needed there.
if IS_WINDOWS:
    try:
        datas += collect_data_files('tzdata')
        print("INFO: Bundled tzdata for Windows timezone support")
    except Exception as e:
        print("=" * 60)
        print("CRITICAL WARNING: Could not collect tzdata!")
        print(f"Error: {e}")
        print("")
        print("Without tzdata, the Windows app will have a 5+ minute delay")
        print("on first launch as it downloads timezone data.")
        print("")
        print("To fix: pip install tzdata")
        print("=" * 60)
    
    # Add Windows icon for taskbar (must be bundled for runtime use)
    # The .ico file is used by the app at runtime to set the taskbar icon
    icon_ico_path = SPEC_DIR / 'icon.ico'
    if icon_ico_path.exists():
        datas.append((str(icon_ico_path), 'assets'))

# No tkinter binary bundling needed — menu bar apps don't use tkinter
binaries = []

# Hidden imports - modules that PyInstaller might miss
hiddenimports = [
    # Bundled API keys module (generated at build time)
    'bundled_keys',

    # Core/menubar/sync packages
    'core',
    'core.engine',
    'core.permissions',
    'menubar',
    'sync',
    'sync.supabase_client',
    'sync.auth_server',

    # OpenAI and HTTP clients
    'openai',
    'openai.resources',
    'openai._streaming',
    'httpx',
    'httpcore',
    'h11',
    'anyio',
    'sniffio',
    'certifi',
    'httpx._transports',
    'httpx._transports.default',

    # Google Generative AI
    'google.generativeai',
    'google.ai.generativelanguage',
    'google.api_core',
    'google.auth',
    'google.protobuf',
    'proto',

    # Supabase
    'supabase',

    # Image processing
    'PIL',
    'PIL.Image',
    'cv2',
    'numpy',

    # PDF generation
    'reportlab',
    'reportlab.lib',
    'reportlab.lib.colors',
    'reportlab.lib.pagesizes',
    'reportlab.lib.styles',
    'reportlab.lib.units',
    'reportlab.platypus',
    'reportlab.graphics',

    # Environment
    'dotenv',

    # Standard library that might be missed
    'json',
    'logging',
    'threading',
    'queue',
]

# Platform-specific hidden imports
if IS_MACOS:
    hiddenimports.extend([
        'rumps',
        'AppKit',
        'Foundation',
        'AVFoundation',
        'objc',
        'PyObjCTools',
    ])

if IS_WINDOWS:
    hiddenimports.extend([
        'pystray',
        'pystray._win32',
        'pywinauto',
        'pywinauto.application',
        'pywinauto.controls',
        'pywinauto.controls.uia_controls',
        'comtypes',
        'comtypes.client',
        'tzdata',
        'zoneinfo',
    ])

# Exclude unnecessary modules to reduce size
# NOTE: Do NOT exclude 'unittest' - pyparsing.testing imports it (used by google-generativeai)
excludes = [
    'matplotlib',
    'scipy',
    'pandas',
    'notebook',
    'jupyter',
    'IPython',
    'test',
    'tests',
    # 'unittest',  # Required by pyparsing.testing
    'pytest',
]

# No runtime hooks needed - API keys are embedded via bundled_keys.py module
runtime_hooks = []

# Analysis step
a = Analysis(
    [str(PROJECT_ROOT / 'main.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=excludes,
    noarchive=False,
)

# Remove duplicate data files
pyz = PYZ(a.pure)

# Create the executable
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BrainDock',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

# Collect all files
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BrainDock',
)

# macOS-specific: Create app bundle
if IS_MACOS:
    app = BUNDLE(
        coll,
        name='BrainDock.app',
        icon=ICON_ICNS if os.path.exists(ICON_ICNS) else None,
        bundle_identifier='com.braindock.app',
        info_plist={
            'CFBundleName': 'BrainDock',
            'CFBundleDisplayName': 'BrainDock',
            'CFBundleVersion': '2.0.0',
            'CFBundleShortVersionString': '2.0.0',
            'CFBundleExecutable': 'BrainDock',
            'CFBundleIdentifier': 'com.braindock.app',
            'CFBundlePackageType': 'APPL',
            'CFBundleSignature': 'BDCK',
            'LSMinimumSystemVersion': '10.15.0',
            'NSHighResolutionCapable': True,
            # Menu bar agent — no Dock icon, no main window
            'LSUIElement': True,
            # Camera access for focus detection
            'NSCameraUsageDescription': 'BrainDock needs camera access to monitor your focus and detect distractions.',
            'NSMicrophoneUsageDescription': 'BrainDock may use the microphone for future features.',
            'NSScreenCaptureUsageDescription': 'BrainDock can optionally capture screenshots to detect distracting websites and apps (disabled by default).',
            'NSAppleEventsUsageDescription': 'BrainDock uses AppleScript to detect the active window and browser URL for distraction monitoring.',
            'LSApplicationCategoryType': 'public.app-category.productivity',
        },
    )
