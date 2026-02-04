#!/bin/bash
#
# BrainDock Local Build Script (No Code Signing)
#
# Quick build for local testing - creates unsigned .app and .dmg
#
# Usage:
#   ./build/build_local.sh
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
echo -e "${BLUE}     BrainDock Local Build (No Signing)${NC}"
echo -e "${BLUE}=================================================${NC}"
echo ""

# Change to project root
cd "$PROJECT_ROOT"
echo -e "${GREEN}Project root:${NC} $PROJECT_ROOT"

# Check if we're on macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}Error: This script is for macOS only.${NC}"
    exit 1
fi

# Use existing venv or create one
VENV_DIR="$PROJECT_ROOT/.venv-build"
if [[ -d "$VENV_DIR" ]]; then
    echo "Using existing virtual environment..."
    source "$VENV_DIR/bin/activate"
else
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    pip install pyinstaller --quiet
fi

echo -e "${GREEN}Virtual environment activated.${NC}"

# Clean previous build
echo ""
echo -e "${YELLOW}Cleaning previous build...${NC}"
rm -rf dist/BrainDock.app dist/*.dmg build/pyinstaller-work

# Get version (hardcoded to match build_macos.sh)
VERSION="1.0.0"
echo -e "${GREEN}Building version:${NC} $VERSION"

# Build with PyInstaller
echo ""
echo -e "${YELLOW}Building app with PyInstaller...${NC}"
pyinstaller build/braindock.spec --noconfirm

# Check if build succeeded
if [[ ! -d "dist/BrainDock.app" ]]; then
    echo -e "${RED}Error: Build failed - BrainDock.app not found${NC}"
    exit 1
fi

echo -e "${GREEN}App built successfully!${NC}"

# Create DMG
echo ""
echo -e "${YELLOW}Creating DMG...${NC}"

DMG_NAME="BrainDock-${VERSION}-macOS-LOCAL.dmg"
DMG_PATH="dist/$DMG_NAME"

# Remove existing DMG
rm -f "$DMG_PATH"

# Generate DMG background image with arrow
echo -e "${YELLOW}Generating DMG background...${NC}"
python3 "$SCRIPT_DIR/create_dmg_background.py"
DMG_BACKGROUND="$SCRIPT_DIR/dmg_background.png"

if [[ ! -f "$DMG_BACKGROUND" ]]; then
    echo -e "${RED}Error: Failed to generate DMG background${NC}"
    exit 1
fi

# Check if create-dmg is installed
if ! command -v create-dmg &> /dev/null; then
    echo ""
    echo -e "${YELLOW}Installing create-dmg via Homebrew...${NC}"
    if command -v brew &> /dev/null; then
        brew install create-dmg
    else
        echo -e "${RED}Error: Homebrew not found. Please install create-dmg manually:${NC}"
        echo "  brew install create-dmg"
        exit 1
    fi
fi

# Create the DMG using create-dmg with professional styling
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
    "dist/BrainDock.app"

echo -e "${GREEN}DMG created: $DMG_PATH${NC}"

# Copy to Downloads
echo ""
echo -e "${YELLOW}Copying to Downloads...${NC}"
cp "$DMG_PATH" ~/Downloads/
echo -e "${GREEN}DMG copied to: ~/Downloads/$DMG_NAME${NC}"

echo ""
echo -e "${BLUE}=================================================${NC}"
echo -e "${GREEN}Build complete!${NC}"
echo -e "${BLUE}=================================================${NC}"
echo ""
echo "DMG location: ~/Downloads/$DMG_NAME"
echo ""
echo -e "${YELLOW}Note: This build is NOT signed. macOS will show${NC}"
echo -e "${YELLOW}security warnings. Right-click and select 'Open'${NC}"
echo -e "${YELLOW}to bypass Gatekeeper for testing.${NC}"
