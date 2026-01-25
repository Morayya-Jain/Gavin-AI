#!/bin/bash
#
# BrainDock macOS Build Script
#
# This script builds the macOS .app bundle using PyInstaller.
# It sets up a clean virtual environment, installs dependencies,
# and creates the final application bundle.
#
# Usage:
#   GEMINI_API_KEY=your-key ./build/build_macos.sh
#
# The built app will be in: dist/BrainDock.app
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
    echo "Usage: GEMINI_API_KEY=key STRIPE_SECRET_KEY=key STRIPE_PUBLISHABLE_KEY=key STRIPE_PRICE_ID=id ./build/build_macos.sh"
    exit 1
fi

echo ""
echo -e "${GREEN}Gemini API key detected - will be embedded in build.${NC}"
export BUNDLED_GEMINI_API_KEY="$GEMINI_API_KEY"

# Set bundled Stripe keys (optional but recommended)
if [[ -n "$STRIPE_SECRET_KEY" ]]; then
    echo -e "${GREEN}Stripe keys detected - will be embedded in build.${NC}"
    export BUNDLED_STRIPE_SECRET_KEY="$STRIPE_SECRET_KEY"
    export BUNDLED_STRIPE_PUBLISHABLE_KEY="$STRIPE_PUBLISHABLE_KEY"
    export BUNDLED_STRIPE_PRICE_ID="$STRIPE_PRICE_ID"
else
    echo -e "${YELLOW}Warning: Stripe keys not provided. Payment features will be disabled.${NC}"
fi

# Clean previous builds
echo ""
echo -e "${YELLOW}Cleaning previous builds...${NC}"
rm -rf "$PROJECT_ROOT/dist/BrainDock"
rm -rf "$PROJECT_ROOT/dist/BrainDock.app"
rm -rf "$PROJECT_ROOT/build/BrainDock"
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
    echo -e "${GREEN}        Build Successful!${NC}"
    echo -e "${GREEN}=================================================${NC}"
    echo ""
    echo -e "App bundle: ${BLUE}$PROJECT_ROOT/dist/BrainDock.app${NC}"
    echo ""
    
    # Show app size
    APP_SIZE=$(du -sh "$PROJECT_ROOT/dist/BrainDock.app" | cut -f1)
    echo -e "App size: ${YELLOW}$APP_SIZE${NC}"
    echo ""
    
    # Instructions
    echo -e "${YELLOW}To test the app:${NC}"
    echo "  open dist/BrainDock.app"
    echo ""
    echo -e "${YELLOW}To distribute:${NC}"
    echo "  1. Compress: zip -r BrainDock-macOS.zip dist/BrainDock.app"
    echo "  2. Upload to GitHub Releases"
    echo ""
    echo -e "${YELLOW}Note:${NC} Users will need to right-click > Open on first launch"
    echo "      to bypass the 'unidentified developer' warning."
    
else
    echo ""
    echo -e "${RED}=================================================${NC}"
    echo -e "${RED}        Build Failed!${NC}"
    echo -e "${RED}=================================================${NC}"
    echo ""
    echo "Check the output above for errors."
    exit 1
fi

# Deactivate virtual environment
deactivate

echo ""
echo -e "${GREEN}Done!${NC}"
