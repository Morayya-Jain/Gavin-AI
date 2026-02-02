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

# Add Stripe's certificate bundle (required for httpx SSL connections)
try:
    import stripe
    stripe_data_path = os.path.join(os.path.dirname(stripe.__file__), 'data')
    if os.path.exists(stripe_data_path):
        datas.append((stripe_data_path, 'stripe/data'))
except ImportError:
    pass

# CustomTkinter assets - required for proper widget rendering in bundled apps
# Without this, CTkScrollableFrame and other widgets have viewport/layout issues
# that cause content to be invisible or incorrectly positioned
try:
    ctk_datas = collect_data_files('customtkinter')
    if ctk_datas:
        print(f"INFO: Collected {len(ctk_datas)} customtkinter data files")
        datas += ctk_datas
    else:
        print("WARNING: collect_data_files returned empty for customtkinter")
        # Fallback: manually find customtkinter assets
        import customtkinter
        ctk_path = Path(customtkinter.__file__).parent
        ctk_assets = ctk_path / 'assets'
        if ctk_assets.exists():
            print(f"INFO: Manually adding customtkinter assets from {ctk_assets}")
            datas.append((str(ctk_assets), 'customtkinter/assets'))
except Exception as e:
    print(f"WARNING: Could not collect customtkinter assets: {e}")
    # Fallback: try to find customtkinter manually
    try:
        import customtkinter
        ctk_path = Path(customtkinter.__file__).parent
        ctk_assets = ctk_path / 'assets'
        if ctk_assets.exists():
            print(f"INFO: Fallback - adding customtkinter assets from {ctk_assets}")
            datas.append((str(ctk_assets), 'customtkinter/assets'))
    except Exception as e2:
        print(f"ERROR: Could not find customtkinter assets: {e2} - UI may have rendering issues")

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

# Explicitly collect tkinter binaries - required for consistent bundling
# across different Python installation methods (pyenv, official installer, Homebrew)
# Without this, GitHub Actions builds may place tkinter in unexpected locations
binaries = []
if IS_MACOS:
    import sysconfig
    import glob

    # Find _tkinter shared library
    stdlib_path = sysconfig.get_path('stdlib')
    libdynload_path = sysconfig.get_path('platlib')

    # Try multiple locations where _tkinter might be
    # Covers: official Python installer, pyenv, Homebrew (Intel & Apple Silicon)
    tkinter_locations = [
        # Dynamic paths based on current Python installation
        os.path.join(sysconfig.get_config_var('LIBDIR') or '', 'python*', 'lib-dynload', '_tkinter*.so'),
        os.path.join(stdlib_path or '', '..', 'lib-dynload', '_tkinter*.so'),
        os.path.join(sys.prefix, 'lib', 'python*', 'lib-dynload', '_tkinter*.so'),
        # Official Python.org installer
        '/Library/Frameworks/Python.framework/Versions/*/lib/python*/lib-dynload/_tkinter*.so',
        # pyenv installations
        os.path.expanduser('~/.pyenv/versions/*/lib/python*/lib-dynload/_tkinter*.so'),
        # Homebrew Python - Apple Silicon (M1/M2/M3)
        '/opt/homebrew/Cellar/python@*/*/Frameworks/Python.framework/Versions/*/lib/python*/lib-dynload/_tkinter*.so',
        '/opt/homebrew/Frameworks/Python.framework/Versions/*/lib/python*/lib-dynload/_tkinter*.so',
        '/opt/homebrew/opt/python@*/Frameworks/Python.framework/Versions/*/lib/python*/lib-dynload/_tkinter*.so',
        # Homebrew Python - Intel Macs
        '/usr/local/Cellar/python@*/*/Frameworks/Python.framework/Versions/*/lib/python*/lib-dynload/_tkinter*.so',
        '/usr/local/Frameworks/Python.framework/Versions/*/lib/python*/lib-dynload/_tkinter*.so',
        '/usr/local/opt/python@*/Frameworks/Python.framework/Versions/*/lib/python*/lib-dynload/_tkinter*.so',
    ]

    tkinter_found = False
    for pattern in tkinter_locations:
        matches = glob.glob(pattern)
        for match in matches:
            if os.path.exists(match):
                print(f"INFO: Found _tkinter at: {match}")
                # Bundle to the root Frameworks directory for consistent access
                binaries.append((match, '.'))
                tkinter_found = True
                break
        if tkinter_found:
            break

    if not tkinter_found:
        print("WARNING: Could not find _tkinter.so - tkinter may not work in bundled app")

    # Also ensure Tcl/Tk libraries are properly bundled
    # Look for Tcl and Tk frameworks/libraries across all installation methods
    tcltk_locations = [
        # System/Official installer frameworks
        '/Library/Frameworks/Tcl.framework',
        '/Library/Frameworks/Tk.framework',
        # Homebrew tcl-tk - Intel Macs
        '/usr/local/opt/tcl-tk/lib',
        '/usr/local/opt/tcl-tk/lib/libtcl*.dylib',
        '/usr/local/opt/tcl-tk/lib/libtk*.dylib',
        # Homebrew tcl-tk - Apple Silicon
        '/opt/homebrew/opt/tcl-tk/lib',
        '/opt/homebrew/opt/tcl-tk/lib/libtcl*.dylib',
        '/opt/homebrew/opt/tcl-tk/lib/libtk*.dylib',
        # pyenv installations
        os.path.expanduser('~/.pyenv/versions/*/lib/libtcl*.dylib'),
        os.path.expanduser('~/.pyenv/versions/*/lib/libtk*.dylib'),
    ]
    for pattern in tcltk_locations:
        matches = glob.glob(pattern)
        for match in matches:
            if os.path.exists(match) and os.path.isfile(match):
                print(f"INFO: Found Tcl/Tk library at: {match}")
                binaries.append((match, '.'))

# Hidden imports - modules that PyInstaller might miss
hiddenimports = [
    # Bundled API keys module (generated at build time)
    'bundled_keys',
    
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
    
    # Image processing
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',
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
    
    # Stripe
    'stripe',
    
    # Environment
    'dotenv',
    
    # Standard library that might be missed
    'json',
    'logging',
    'threading',
    'queue',
    'tkinter',
    'tkinter.messagebox',
    'tkinter.filedialog',
    'tkinter.font',
]

# Platform-specific hidden imports
if IS_MACOS:
    hiddenimports.extend([
        'AppKit',
        'Foundation',
        'AVFoundation',  # For camera permission handling
        'objc',
        'PyObjCTools',
    ])

if IS_WINDOWS:
    hiddenimports.extend([
        'pywinauto',
        'pywinauto.application',
        'pywinauto.controls',
        'pywinauto.controls.uia_controls',
        'comtypes',
        'comtypes.client',
        # Timezone support - Windows lacks built-in IANA timezone data
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
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'CFBundleExecutable': 'BrainDock',
            'CFBundleIdentifier': 'com.braindock.app',
            'CFBundlePackageType': 'APPL',
            'CFBundleSignature': 'BDCK',  # BrainDock 4-char bundle signature
            # Minimum macOS 10.15 (Catalina) required for Screen Recording permission
            # and modern AVFoundation camera permission APIs
            'LSMinimumSystemVersion': '10.15.0',
            'NSHighResolutionCapable': True,
            # Camera access for focus detection
            'NSCameraUsageDescription': 'BrainDock needs camera access to monitor your focus and detect distractions.',
            # Microphone (reserved for future features)
            'NSMicrophoneUsageDescription': 'BrainDock may use the microphone for future features.',
            # Screen Recording for optional AI screenshot analysis
            'NSScreenCaptureUsageDescription': 'BrainDock can optionally capture screenshots to detect distracting websites and apps (disabled by default).',
            # AppleEvents for detecting active window title and browser URLs
            'NSAppleEventsUsageDescription': 'BrainDock uses AppleScript to detect the active window and browser URL for distraction monitoring.',
            'LSApplicationCategoryType': 'public.app-category.productivity',
        },
    )
