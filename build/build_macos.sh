#!/bin/bash
#
# BrainDock macOS Build Script
#
# This script builds the macOS .app bundle using PyInstaller,
# signs it with a Developer ID certificate, and notarizes it
# with Apple for Gatekeeper approval.
#
# Usage:
#   GEMINI_API_KEY=your-key ./build/build_macos.sh
#
# For signed and notarized builds (recommended for distribution):
#   GEMINI_API_KEY=your-key \
#   APPLE_ID=your-apple-id@email.com \
#   APPLE_APP_SPECIFIC_PASSWORD=xxxx-xxxx-xxxx-xxxx \
#   ./build/build_macos.sh
#
# The built app will be in: dist/BrainDock.app
# The DMG installer will be in: dist/BrainDock-VERSION-macOS.dmg
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}        BrainDock macOS Build Script${NC}"
echo -e "${BLUE}=================================================${NC}"
echo ""

# Change to project root
cd "$PROJECT_ROOT"
echo -e "${GREEN}Project root:${NC} $PROJECT_ROOT"
echo ""

# Check if we're on macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}Error: This script is for macOS only.${NC}"
    echo "For Windows builds, use GitHub Actions or build on a Windows machine."
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
echo -e "${GREEN}Python version:${NC} $PYTHON_VERSION"

# Check if Python 3.9+ is available
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f2)
if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 9 ]]; then
    echo -e "${RED}Error: Python 3.9 or higher is required.${NC}"
    exit 1
fi

# Create/activate virtual environment
VENV_DIR="$PROJECT_ROOT/.venv-build"
echo ""
echo -e "${YELLOW}Setting up virtual environment...${NC}"

if [[ -d "$VENV_DIR" ]]; then
    echo "Using existing virtual environment at $VENV_DIR"
else
    echo "Creating new virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"
echo -e "${GREEN}Virtual environment activated.${NC}"

# Upgrade pip
echo ""
echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip --quiet

# Install dependencies
echo ""
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet
echo -e "${GREEN}Dependencies installed.${NC}"

# Generate icons if they don't exist
echo ""
echo -e "${YELLOW}Checking icons...${NC}"
if [[ ! -f "$SCRIPT_DIR/icon.icns" ]]; then
    echo "Generating icons..."
    python3 "$SCRIPT_DIR/create_icons.py"
else
    echo -e "${GREEN}Icons already exist.${NC}"
fi

# Set bundled Gemini API key (required)
if [[ -z "$GEMINI_API_KEY" ]]; then
    echo -e "${RED}Error: GEMINI_API_KEY environment variable is required.${NC}"
    echo ""
    echo "Usage: GEMINI_API_KEY=key [OPENAI_API_KEY=key] ./build/build_macos.sh"
    exit 1
fi

echo ""
echo -e "${GREEN}Gemini API key detected - will be embedded in build.${NC}"

# Set bundled OpenAI API key (optional - for fallback/alternative)
if [[ -n "$OPENAI_API_KEY" ]]; then
    echo -e "${GREEN}OpenAI API key detected - will be embedded in build.${NC}"
else
    echo -e "${YELLOW}Note: OpenAI API key not provided (optional - Gemini is primary).${NC}"
fi

# Stripe keys no longer needed — payments handled via web dashboard

# Generate bundled_keys.py with embedded API keys
# This module is imported by config.py to get the actual key values
echo ""
echo -e "${YELLOW}Generating bundled_keys.py with embedded keys...${NC}"

BUNDLED_KEYS="$PROJECT_ROOT/bundled_keys.py"
BUNDLED_KEYS_TEMPLATE="$PROJECT_ROOT/bundled_keys_template.py"

if [[ -f "$BUNDLED_KEYS_TEMPLATE" ]]; then
    # Copy template and replace placeholders with actual values
    cp "$BUNDLED_KEYS_TEMPLATE" "$BUNDLED_KEYS"
    
    # Use sed to replace placeholders (handle special characters in keys)
    # We use | as delimiter since keys might contain /
    sed -i '' "s|%%OPENAI_API_KEY%%|${OPENAI_API_KEY:-}|g" "$BUNDLED_KEYS"
    sed -i '' "s|%%GEMINI_API_KEY%%|${GEMINI_API_KEY}|g" "$BUNDLED_KEYS"
    sed -i '' "s|%%SUPABASE_URL%%|${SUPABASE_URL:-}|g" "$BUNDLED_KEYS"
    sed -i '' "s|%%SUPABASE_ANON_KEY%%|${SUPABASE_ANON_KEY:-}|g" "$BUNDLED_KEYS"
    # Stripe keys removed — payments handled via web dashboard
    
    echo -e "${GREEN}bundled_keys.py generated with embedded keys.${NC}"
else
    echo -e "${RED}Error: Bundled keys template not found at $BUNDLED_KEYS_TEMPLATE${NC}"
    exit 1
fi


# Clean previous builds
echo ""
echo -e "${YELLOW}Cleaning previous builds...${NC}"
rm -rf "$PROJECT_ROOT/dist/BrainDock"
rm -rf "$PROJECT_ROOT/dist/BrainDock.app"
rm -rf "$PROJECT_ROOT/build/BrainDock"
# NOTE: Don't delete bundled_keys.py here - it was just generated above!
echo -e "${GREEN}Cleaned.${NC}"

# Run PyInstaller
echo ""
echo -e "${YELLOW}Running PyInstaller...${NC}"
echo "This may take a few minutes..."
echo ""

pyinstaller "$SCRIPT_DIR/braindock.spec" \
    --distpath "$PROJECT_ROOT/dist" \
    --workpath "$PROJECT_ROOT/build/pyinstaller-work" \
    --noconfirm

# Check if build succeeded
if [[ -d "$PROJECT_ROOT/dist/BrainDock.app" ]]; then
    echo ""
    echo -e "${GREEN}=================================================${NC}"
    echo -e "${GREEN}        App Bundle Created!${NC}"
    echo -e "${GREEN}=================================================${NC}"
    echo ""
    echo -e "App bundle: ${BLUE}$PROJECT_ROOT/dist/BrainDock.app${NC}"
    
    # Show app size
    APP_SIZE=$(du -sh "$PROJECT_ROOT/dist/BrainDock.app" | cut -f1)
    echo -e "App size: ${YELLOW}$APP_SIZE${NC}"
    echo ""
    
    # Code Signing Configuration
    # These can be overridden via environment variables for different developers
    CODESIGN_IDENTITY="${CODESIGN_IDENTITY:-Developer ID Application: Morayya Jain (B62872437T)}"
    TEAM_ID="${TEAM_ID:-B62872437T}"
    ENTITLEMENTS="$SCRIPT_DIR/entitlements.plist"
    
    # Check if we should sign and notarize
    SHOULD_SIGN=false
    SHOULD_NOTARIZE=false
    
    # Check if signing identity exists
    if security find-identity -v -p codesigning | grep -q "$CODESIGN_IDENTITY"; then
        SHOULD_SIGN=true
        echo -e "${GREEN}Developer ID certificate found. Will sign the app.${NC}"
    else
        echo -e "${YELLOW}Warning: Developer ID certificate not found.${NC}"
        echo -e "${YELLOW}The app will not be signed and users will see Gatekeeper warnings.${NC}"
        echo ""
    fi
    
    # Check if notarization credentials are provided
    if [[ -n "$APPLE_ID" && -n "$APPLE_APP_SPECIFIC_PASSWORD" ]]; then
        SHOULD_NOTARIZE=true
        echo -e "${GREEN}Notarization credentials found. Will notarize the app.${NC}"
    else
        echo -e "${YELLOW}Note: Notarization credentials not provided.${NC}"
        echo -e "${YELLOW}Set APPLE_ID and APPLE_APP_SPECIFIC_PASSWORD to enable notarization.${NC}"
        echo ""
    fi
    
    # Sign the app bundle
    if [[ "$SHOULD_SIGN" == true ]]; then
        echo ""
        echo -e "${YELLOW}Signing app bundle with Developer ID...${NC}"
        
        # Sign all nested components first (deep signing)
        # Sign frameworks and dylibs
        find "$PROJECT_ROOT/dist/BrainDock.app" -name "*.dylib" -o -name "*.so" -o -name "*.framework" 2>/dev/null | while read -r file; do
            codesign --force --options runtime --timestamp \
                --entitlements "$ENTITLEMENTS" \
                --sign "$CODESIGN_IDENTITY" \
                "$file" 2>/dev/null || true
        done
        
        # Sign Python executables
        find "$PROJECT_ROOT/dist/BrainDock.app" -name "python*" -type f -perm +111 2>/dev/null | while read -r file; do
            codesign --force --options runtime --timestamp \
                --entitlements "$ENTITLEMENTS" \
                --sign "$CODESIGN_IDENTITY" \
                "$file" 2>/dev/null || true
        done
        
        # Sign the main executable
        codesign --force --options runtime --timestamp \
            --entitlements "$ENTITLEMENTS" \
            --sign "$CODESIGN_IDENTITY" \
            "$PROJECT_ROOT/dist/BrainDock.app/Contents/MacOS/BrainDock"
        
        # Sign the entire app bundle
        codesign --force --options runtime --timestamp \
            --entitlements "$ENTITLEMENTS" \
            --sign "$CODESIGN_IDENTITY" \
            "$PROJECT_ROOT/dist/BrainDock.app"
        
        # Verify the signature
        echo -e "${YELLOW}Verifying signature...${NC}"
        codesign --verify --verbose=2 "$PROJECT_ROOT/dist/BrainDock.app"
        
        if [[ $? -eq 0 ]]; then
            echo -e "${GREEN}App signed successfully!${NC}"
        else
            echo -e "${RED}Warning: Signature verification failed.${NC}"
        fi
        echo ""
    fi
    
    # Notarize the app
    if [[ "$SHOULD_SIGN" == true && "$SHOULD_NOTARIZE" == true ]]; then
        echo -e "${YELLOW}Notarizing app with Apple...${NC}"
        echo "This may take several minutes..."
        echo ""
        
        # Create a ZIP for notarization
        NOTARIZE_ZIP="$PROJECT_ROOT/dist/BrainDock-notarize.zip"
        ditto -c -k --keepParent "$PROJECT_ROOT/dist/BrainDock.app" "$NOTARIZE_ZIP"
        
        # Submit for notarization
        echo -e "${YELLOW}Submitting to Apple notarization service...${NC}"
        
        NOTARIZE_OUTPUT=$(xcrun notarytool submit "$NOTARIZE_ZIP" \
            --apple-id "$APPLE_ID" \
            --password "$APPLE_APP_SPECIFIC_PASSWORD" \
            --team-id "$TEAM_ID" \
            --wait 2>&1)
        
        echo "$NOTARIZE_OUTPUT"
        
        # Check if notarization succeeded
        if echo "$NOTARIZE_OUTPUT" | grep -q "status: Accepted"; then
            echo ""
            echo -e "${GREEN}Notarization successful!${NC}"
            
            # Staple the notarization ticket to the app
            echo -e "${YELLOW}Stapling notarization ticket...${NC}"
            xcrun stapler staple "$PROJECT_ROOT/dist/BrainDock.app"
            
            if [[ $? -eq 0 ]]; then
                echo -e "${GREEN}Notarization ticket stapled successfully!${NC}"
            else
                echo -e "${RED}Warning: Failed to staple notarization ticket.${NC}"
            fi
        else
            echo ""
            echo -e "${RED}Warning: Notarization may have failed. Check the output above.${NC}"
            echo -e "${YELLOW}You can check notarization history with:${NC}"
            echo "  xcrun notarytool history --apple-id $APPLE_ID --team-id $TEAM_ID"
        fi
        
        # Clean up the zip
        rm -f "$NOTARIZE_ZIP"
        echo ""
    fi
    
    # Create DMG
    echo -e "${YELLOW}Creating DMG installer...${NC}"
    
    # Version for filename
    VERSION="2.0.0"
    DMG_NAME="BrainDock-${VERSION}-macOS.dmg"
    DMG_PATH="$PROJECT_ROOT/dist/$DMG_NAME"
    
    # Clean up any existing DMG
    rm -f "$DMG_PATH"
    
    # Generate DMG background image with arrow
    echo -e "${YELLOW}Generating DMG background...${NC}"
    python3 "$SCRIPT_DIR/create_dmg_background.py"
    DMG_BACKGROUND="$SCRIPT_DIR/dmg_background.png"
    
    if [[ ! -f "$DMG_BACKGROUND" ]]; then
        echo -e "${RED}Error: Failed to generate DMG background${NC}"
        exit 1
    fi
    echo -e "${GREEN}DMG background generated.${NC}"
    
    # Check if create-dmg is installed
    if ! command -v create-dmg &> /dev/null; then
        echo ""
        echo -e "${YELLOW}Installing create-dmg via Homebrew...${NC}"
        if command -v brew &> /dev/null; then
            brew install create-dmg
        else
            echo -e "${RED}Error: Homebrew not found. Please install create-dmg manually:${NC}"
            echo "  brew install create-dmg"
            echo ""
            echo "Or install Homebrew first: https://brew.sh"
            exit 1
        fi
    fi
    
    echo -e "${YELLOW}Creating styled DMG with create-dmg...${NC}"
    
    # Create the DMG using create-dmg with professional styling
    # Icon positions: BrainDock.app at (180, 190), Applications at (480, 190)
    # These match the background image layout
    create-dmg \
        --volname "BrainDock" \
        --volicon "$SCRIPT_DIR/icon.icns" \
        --background "$DMG_BACKGROUND" \
        --window-pos 200 120 \
        --window-size 660 400 \
        --icon-size 100 \
        --icon "BrainDock.app" 180 190 \
        --hide-extension "BrainDock.app" \
        --app-drop-link 480 190 \
        --no-internet-enable \
        "$DMG_PATH" \
        "$PROJECT_ROOT/dist/BrainDock.app"
    
    # Check if DMG was created
    if [[ -f "$DMG_PATH" ]]; then
        # Sign the DMG
        if [[ "$SHOULD_SIGN" == true ]]; then
            echo ""
            echo -e "${YELLOW}Signing DMG...${NC}"
            codesign --force --timestamp \
                --sign "$CODESIGN_IDENTITY" \
                "$DMG_PATH"
            
            # Verify DMG signature
            codesign --verify --verbose=2 "$DMG_PATH"
            echo -e "${GREEN}DMG signed successfully!${NC}"
        fi
        
        # Notarize the DMG
        if [[ "$SHOULD_SIGN" == true && "$SHOULD_NOTARIZE" == true ]]; then
            echo ""
            echo -e "${YELLOW}Notarizing DMG with Apple...${NC}"
            echo "This may take several minutes..."
            
            NOTARIZE_DMG_OUTPUT=$(xcrun notarytool submit "$DMG_PATH" \
                --apple-id "$APPLE_ID" \
                --password "$APPLE_APP_SPECIFIC_PASSWORD" \
                --team-id "$TEAM_ID" \
                --wait 2>&1)
            
            echo "$NOTARIZE_DMG_OUTPUT"
            
            if echo "$NOTARIZE_DMG_OUTPUT" | grep -q "status: Accepted"; then
                echo ""
                echo -e "${GREEN}DMG notarization successful!${NC}"
                
                # Staple the notarization ticket to the DMG
                echo -e "${YELLOW}Stapling notarization ticket to DMG...${NC}"
                xcrun stapler staple "$DMG_PATH"
                
                if [[ $? -eq 0 ]]; then
                    echo -e "${GREEN}DMG notarization ticket stapled!${NC}"
                fi
            else
                echo -e "${YELLOW}Warning: DMG notarization may have failed.${NC}"
            fi
        fi
        
        DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
        echo ""
        echo -e "${GREEN}=================================================${NC}"
        echo -e "${GREEN}        Build Successful!${NC}"
        echo -e "${GREEN}=================================================${NC}"
        echo ""
        echo -e "DMG installer: ${BLUE}$DMG_PATH${NC}"
        echo -e "DMG size: ${YELLOW}$DMG_SIZE${NC}"
        
        # Show signing/notarization status
        if [[ "$SHOULD_SIGN" == true && "$SHOULD_NOTARIZE" == true ]]; then
            echo -e "Signed: ${GREEN}Yes${NC}"
            echo -e "Notarized: ${GREEN}Yes${NC}"
            echo ""
            echo -e "${GREEN}The app is ready for distribution!${NC}"
            echo -e "${GREEN}Users will NOT see Gatekeeper warnings.${NC}"
        elif [[ "$SHOULD_SIGN" == true ]]; then
            echo -e "Signed: ${GREEN}Yes${NC}"
            echo -e "Notarized: ${YELLOW}No${NC}"
            echo ""
            echo -e "${YELLOW}Note: App is signed but not notarized.${NC}"
            echo -e "${YELLOW}Users may still see 'unidentified developer' warnings.${NC}"
        else
            echo -e "Signed: ${RED}No${NC}"
            echo -e "Notarized: ${RED}No${NC}"
            echo ""
            echo -e "${YELLOW}Warning: App is not signed or notarized.${NC}"
            echo -e "${YELLOW}Users will see Gatekeeper warnings.${NC}"
        fi
        
        echo ""
        echo -e "${YELLOW}To test:${NC}"
        echo "  open \"$DMG_PATH\""
        echo ""
        echo -e "${YELLOW}To distribute:${NC}"
        echo "  Upload $DMG_NAME to GitHub Releases or your website"
    else
        echo -e "${RED}Error: Failed to create DMG${NC}"
        exit 1
    fi
    
else
    echo ""
    echo -e "${RED}=================================================${NC}"
    echo -e "${RED}        Build Failed!${NC}"
    echo -e "${RED}=================================================${NC}"
    echo ""
    echo "Check the output above for errors."
    exit 1
fi

# Clean up bundled_keys.py after build (contains secrets - don't commit)
rm -f "$PROJECT_ROOT/bundled_keys.py"

# Deactivate virtual environment
deactivate

echo ""
echo -e "${GREEN}Done!${NC}"
