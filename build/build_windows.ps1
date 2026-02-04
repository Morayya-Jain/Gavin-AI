#
# BrainDock Windows Build Script (PowerShell)
#
# This script builds the Windows installer using PyInstaller and Inno Setup.
# It creates a professional installer with Start Menu/Desktop shortcuts.
#
# Prerequisites:
#   - Python 3.9+
#   - Inno Setup 6.x (https://jrsoftware.org/isdl.php)
#
# Usage:
#   $env:GEMINI_API_KEY="your-key"
#   $env:STRIPE_SECRET_KEY="your-key"
#   $env:STRIPE_PUBLISHABLE_KEY="your-key"
#   $env:STRIPE_PRICE_ID="your-id"
#   .\build\build_windows.ps1
#
# For code-signed builds (optional):
#   $env:WIN_CODESIGN_CERT="path\to\certificate.pfx"
#   $env:WIN_CODESIGN_PASS="certificate-password"
#   .\build\build_windows.ps1
#
# Output: dist\BrainDock-{VERSION}-Setup.exe
#

$ErrorActionPreference = "Stop"

# Script directory and project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Write-Host "=================================================" -ForegroundColor Blue
Write-Host "        BrainDock Windows Build Script" -ForegroundColor Blue
Write-Host "=================================================" -ForegroundColor Blue
Write-Host ""

# Change to project root
Set-Location $ProjectRoot
Write-Host "Project root: $ProjectRoot" -ForegroundColor Green
Write-Host ""

# Check Python version
try {
    $PythonVersion = python --version 2>&1
    Write-Host "Python version: $PythonVersion" -ForegroundColor Green
} catch {
    Write-Host "Error: Python not found. Please install Python 3.9 or higher." -ForegroundColor Red
    exit 1
}

# Check if GEMINI_API_KEY is set (required)
if (-not $env:GEMINI_API_KEY) {
    Write-Host "Error: GEMINI_API_KEY environment variable is required." -ForegroundColor Red
    Write-Host ""
    Write-Host 'Usage: $env:GEMINI_API_KEY="key"; $env:STRIPE_SECRET_KEY="key"; .\build\build_windows.ps1'
    exit 1
}

Write-Host ""
Write-Host "Gemini API key detected - will be embedded in build." -ForegroundColor Green

# Check OpenAI key (optional)
if ($env:OPENAI_API_KEY) {
    Write-Host "OpenAI API key detected - will be embedded in build." -ForegroundColor Green
} else {
    Write-Host "Note: OpenAI API key not provided (optional - Gemini is primary)." -ForegroundColor Yellow
}

# Check Stripe keys (optional but recommended)
if ($env:STRIPE_SECRET_KEY) {
    Write-Host "Stripe keys detected - will be embedded in build." -ForegroundColor Green
} else {
    Write-Host "Warning: Stripe keys not provided. Payment features will be disabled." -ForegroundColor Yellow
}

# Install dependencies
Write-Host ""
Write-Host "Installing dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet
Write-Host "Dependencies installed." -ForegroundColor Green

# Generate icons if they don't exist
Write-Host ""
Write-Host "Checking icons..." -ForegroundColor Yellow
if (-not (Test-Path "$ScriptDir\icon.ico")) {
    Write-Host "Generating icons..."
    python "$ScriptDir\create_icons.py"
} else {
    Write-Host "Icons already exist." -ForegroundColor Green
}

# Check for Inno Setup installation
Write-Host ""
Write-Host "Checking for Inno Setup..." -ForegroundColor Yellow

$InnoSetupPaths = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)

$InnoSetup = $null
foreach ($path in $InnoSetupPaths) {
    if (Test-Path $path) {
        $InnoSetup = $path
        break
    }
}

# Also try to find ISCC.exe via PATH
if (-not $InnoSetup) {
    $InnoSetupFromPath = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    if ($InnoSetupFromPath) {
        $InnoSetup = $InnoSetupFromPath
    }
}

if (-not $InnoSetup) {
    Write-Host "Error: Inno Setup 6 not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Inno Setup 6 from: https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "After installation, run this script again."
    exit 1
}

Write-Host "Inno Setup found: $InnoSetup" -ForegroundColor Green

# Clean previous builds
Write-Host ""
Write-Host "Cleaning previous builds..." -ForegroundColor Yellow
if (Test-Path "$ProjectRoot\dist\BrainDock") {
    Remove-Item -Recurse -Force "$ProjectRoot\dist\BrainDock"
}
if (Test-Path "$ProjectRoot\build\BrainDock") {
    Remove-Item -Recurse -Force "$ProjectRoot\build\BrainDock"
}
# Clean previous installer files
Get-ChildItem -Path "$ProjectRoot\dist" -Filter "BrainDock-*-Setup.exe" -ErrorAction SilentlyContinue | Remove-Item -Force
# Clean previously generated bundled_keys.py (will be regenerated with fresh keys)
if (Test-Path "$ProjectRoot\bundled_keys.py") {
    Remove-Item -Force "$ProjectRoot\bundled_keys.py"
}
Write-Host "Cleaned." -ForegroundColor Green

# Generate bundled_keys.py with embedded API keys
Write-Host ""
Write-Host "Generating bundled_keys.py with embedded keys..." -ForegroundColor Yellow

$BundledKeys = "$ProjectRoot\bundled_keys.py"
$BundledKeysTemplate = "$ProjectRoot\bundled_keys_template.py"

if (Test-Path $BundledKeysTemplate) {
    # Read template
    $content = Get-Content $BundledKeysTemplate -Raw
    
    # Replace placeholders with actual values (handle special regex characters)
    $content = $content -replace '%%OPENAI_API_KEY%%', ($env:OPENAI_API_KEY -replace '\$', '$$$$')
    $content = $content -replace '%%GEMINI_API_KEY%%', ($env:GEMINI_API_KEY -replace '\$', '$$$$')
    $content = $content -replace '%%STRIPE_SECRET_KEY%%', ($env:STRIPE_SECRET_KEY -replace '\$', '$$$$')
    $content = $content -replace '%%STRIPE_PUBLISHABLE_KEY%%', ($env:STRIPE_PUBLISHABLE_KEY -replace '\$', '$$$$')
    $content = $content -replace '%%STRIPE_PRICE_ID%%', ($env:STRIPE_PRICE_ID -replace '\$', '$$$$')
    
    # Write bundled_keys.py (UTF-8 without BOM for Python compatibility)
    [System.IO.File]::WriteAllText($BundledKeys, $content, [System.Text.UTF8Encoding]::new($false))
    
    Write-Host "bundled_keys.py generated with embedded keys." -ForegroundColor Green
} else {
    Write-Host "Error: Bundled keys template not found at $BundledKeysTemplate" -ForegroundColor Red
    exit 1
}

# Run PyInstaller
Write-Host ""
Write-Host "Running PyInstaller..." -ForegroundColor Yellow
Write-Host "This may take a few minutes..."
Write-Host ""

pyinstaller "$ScriptDir\braindock.spec" `
    --distpath "$ProjectRoot\dist" `
    --workpath "$ProjectRoot\build\pyinstaller-work" `
    --noconfirm

# Check if build succeeded
if (Test-Path "$ProjectRoot\dist\BrainDock") {
    Write-Host ""
    Write-Host "=================================================" -ForegroundColor Green
    Write-Host "        PyInstaller Build Successful!" -ForegroundColor Green
    Write-Host "=================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "App folder: $ProjectRoot\dist\BrainDock" -ForegroundColor Blue
    Write-Host ""
    
    # Code signing configuration
    $ShouldSign = $false
    $SignTool = $null
    
    if ($env:WIN_CODESIGN_CERT -and (Test-Path $env:WIN_CODESIGN_CERT)) {
        Write-Host "Code signing certificate found." -ForegroundColor Green
        
        # Find signtool.exe
        $SignToolPaths = @(
            "C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe",
            "C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x64\signtool.exe",
            "C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe"
        )
        
        foreach ($path in $SignToolPaths) {
            if (Test-Path $path) {
                $SignTool = $path
                break
            }
        }
        
        # Also try to find via where command
        if (-not $SignTool) {
            $SignTool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
        }
        
        if ($SignTool) {
            $ShouldSign = $true
            Write-Host "SignTool found: $SignTool" -ForegroundColor Green
        } else {
            Write-Host "Warning: signtool.exe not found. Install Windows SDK to enable signing." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Note: Code signing not configured. Set WIN_CODESIGN_CERT to enable." -ForegroundColor Yellow
    }
    
    # Sign the main executable before packaging
    if ($ShouldSign) {
        Write-Host ""
        Write-Host "Signing BrainDock.exe..." -ForegroundColor Yellow
        
        $ExePath = "$ProjectRoot\dist\BrainDock\BrainDock.exe"
        $TimestampServer = if ($env:WIN_CODESIGN_TIMESTAMP) { $env:WIN_CODESIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
        
        $signArgs = @(
            "sign",
            "/f", $env:WIN_CODESIGN_CERT,
            "/p", $env:WIN_CODESIGN_PASS,
            "/tr", $TimestampServer,
            "/td", "sha256",
            "/fd", "sha256",
            $ExePath
        )
        
        & $SignTool @signArgs
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "BrainDock.exe signed successfully!" -ForegroundColor Green
        } else {
            Write-Host "Warning: Failed to sign BrainDock.exe" -ForegroundColor Yellow
        }
    }
    
    # Create installer with Inno Setup
    Write-Host ""
    Write-Host "Creating Windows installer with Inno Setup..." -ForegroundColor Yellow
    Write-Host "This may take a minute..."
    Write-Host ""
    
    # Run Inno Setup compiler
    & $InnoSetup "$ScriptDir\installer.iss"
    
    # Read version from installer.iss to ensure consistency (single source of truth)
    $IssContent = Get-Content "$ScriptDir\installer.iss" -Raw
    if ($IssContent -match '#define MyAppVersion "([^"]+)"') {
        $Version = $Matches[1]
    } else {
        $Version = "1.0.0"  # Fallback
    }
    $InstallerName = "BrainDock-$Version-Setup.exe"
    $InstallerPath = "$ProjectRoot\dist\$InstallerName"
    
    if (Test-Path $InstallerPath) {
        Write-Host ""
        Write-Host "Installer created successfully!" -ForegroundColor Green
        
        # Sign the installer
        if ($ShouldSign) {
            Write-Host ""
            Write-Host "Signing installer..." -ForegroundColor Yellow
            
            $signArgs = @(
                "sign",
                "/f", $env:WIN_CODESIGN_CERT,
                "/p", $env:WIN_CODESIGN_PASS,
                "/tr", $TimestampServer,
                "/td", "sha256",
                "/fd", "sha256",
                $InstallerPath
            )
            
            & $SignTool @signArgs
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Installer signed successfully!" -ForegroundColor Green
            } else {
                Write-Host "Warning: Failed to sign installer" -ForegroundColor Yellow
            }
        }
        
        $InstallerSize = (Get-Item $InstallerPath).Length / 1MB
        
        Write-Host ""
        Write-Host "=================================================" -ForegroundColor Green
        Write-Host "        Build Complete!" -ForegroundColor Green
        Write-Host "=================================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "Installer: $InstallerPath" -ForegroundColor Blue
        Write-Host ("Size: {0:N1} MB" -f $InstallerSize) -ForegroundColor Yellow
        
        if ($ShouldSign) {
            Write-Host "Code Signed: Yes" -ForegroundColor Green
        } else {
            Write-Host "Code Signed: No" -ForegroundColor Yellow
        }
        
        Write-Host ""
        Write-Host "To test:" -ForegroundColor Yellow
        Write-Host "  & `"$InstallerPath`""
        Write-Host ""
        Write-Host "To distribute:" -ForegroundColor Yellow
        Write-Host "  Upload $InstallerName to GitHub Releases"
        Write-Host ""
        Write-Host "The installer will:" -ForegroundColor Cyan
        Write-Host "  - Show license agreement"
        Write-Host "  - Install to Program Files"
        Write-Host "  - Create Start Menu shortcut"
        Write-Host "  - Create Desktop shortcut"
        Write-Host "  - Register in Add/Remove Programs"
        
    } else {
        Write-Host ""
        Write-Host "Error: Inno Setup failed to create installer" -ForegroundColor Red
        Write-Host "Check the output above for errors."
        exit 1
    }
    
} else {
    Write-Host ""
    Write-Host "=================================================" -ForegroundColor Red
    Write-Host "        Build Failed!" -ForegroundColor Red
    Write-Host "=================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Check the output above for errors."
    exit 1
}

# Clean up temporary files
Write-Host ""
Write-Host "Cleaning up..." -ForegroundColor Yellow

# Remove bundled_keys.py (contains secrets)
if (Test-Path "$ProjectRoot\bundled_keys.py") {
    Remove-Item -Force "$ProjectRoot\bundled_keys.py"
}

# Remove generated license file
if (Test-Path "$ScriptDir\license.txt") {
    Remove-Item -Force "$ScriptDir\license.txt"
}

Write-Host "Cleanup complete." -ForegroundColor Green

Write-Host ""
Write-Host "Done!" -ForegroundColor Green
