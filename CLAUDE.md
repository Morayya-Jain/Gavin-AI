# CLAUDE.md

BrainDock: AI-powered focus tracking app using webcam detection (OpenAI/Gemini Vision APIs), generates PDF reports.

**Tech Stack:** Python 3.11+, tkinter, OpenAI/Gemini Vision APIs, OpenCV, ReportLab, Stripe

## Commands

```bash
python main.py                              # Run GUI
python main.py --cli                        # Run CLI
python -m unittest tests.test_session       # Run tests
./build/build_macos.sh                      # Build macOS DMG
```

## Environment (.env)

```
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AI...
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_PRICE_ID=price_...
```

Dev mode: `SKIP_LICENSE_CHECK=true` | Vision: `VISION_PROVIDER=gemini` (default) or `openai`

## Architecture

**Detection Flow:** Camera Frame → Vision API → Detection State → Session Logger → PDF Report

**Event Types:** `present` (focussed), `away` (not at desk), `gadget_suspected` (phone/tablet), `screen_distraction`, `paused`

**Monitoring Modes:** `camera_only` (default), `screen_only`, `both`

**Key Modules:**
- `camera/vision_detector.py`, `camera/gemini_detector.py` - Vision detection
- `tracking/session.py`, `tracking/analytics.py` - Session & stats (**math must add up**)
- `gui/app.py` - Main GUI | `reporting/pdf_report.py` - PDF generation
- `licensing/` - Stripe payments | `screen/` - Screen monitoring

## Code Standards

- Type hints + docstrings required | Use `pathlib.Path` | Use `logging` (not print)
- Time formatting: `format_duration()` → "1m 30s" | Never use `cursor="hand2"` in tkinter

## Critical Rules

1. **AI-Only Detection** - No hardcoded methods, Vision API only
2. **Gadget Detection** - Requires attention AND active engagement
3. **Stats Math** - `present + away + gadget + screen + paused = total`
4. **Privacy** - Frames never saved to disk
5. **Cost** - ~$0.06-0.12/min at 1 FPS, default 0.33 FPS

## Config (config.py)

`DETECTION_FPS=0.33` | `SCREEN_CHECK_INTERVAL=3` | Models: `gpt-4o-mini`, `gemini-2.0-flash`

**Data:** `data/focus_statements.json` (required), `~/Library/Application Support/BrainDock/` (macOS user data)

## Building macOS DMG

**Prerequisites:** macOS, Python 3.9+, `brew install create-dmg`

**Build Steps:**
```bash
# 1. Create fresh venv with public PyPI
cd /Users/morayya/Development/BrainDock
rm -rf .venv-build
python3 -m venv .venv-build
source .venv-build/bin/activate
pip config set global.index-url https://pypi.org/simple/
pip install --upgrade pip
pip install -r requirements.txt pyinstaller --quiet

# 2. Export keys and build (don't use `source .env` - fails on lines with spaces)
export OPENAI_API_KEY="<from .env>"
export GEMINI_API_KEY="<from .env>"
export STRIPE_SECRET_KEY="<from .env>"
export STRIPE_PUBLISHABLE_KEY="<from .env>"
export STRIPE_PRICE_ID="<from .env>"
./build/build_macos.sh

# 3. Copy to Downloads
cp dist/BrainDock-1.0.0-macOS.dmg ~/Downloads/
```

**Common Issues:**
1. **pip Artifactory errors** - Run `pip config set global.index-url https://pypi.org/simple/`
2. **"Resource busy" DMG** - `hdiutil detach /dev/diskN -force && rm -f dist/*.dmg`
3. **Signing warnings** - Without Apple credentials, users right-click → Open to bypass Gatekeeper

**Output:** `dist/BrainDock.app`, `dist/BrainDock-1.0.0-macOS.dmg` (~99 MB)

**Cleanup:** Build script auto-removes `bundled_keys.py` (contains secrets)

### Quick Local Build (No Keys)

```bash
./build/build_local.sh  # Creates unsigned DMG, requires .env at runtime
```
