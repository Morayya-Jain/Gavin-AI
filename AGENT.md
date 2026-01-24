# BrainDock - Agent Quick Reference

**TL;DR**: Python focus tracker using OpenAI Vision API + screen monitoring to detect present/away/gadget/screen_distraction/paused states. Generates PDF reports.

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | **ALL constants** (models, FPS, thresholds, modes, Stripe keys) |
| `camera/vision_detector.py` | Camera detection logic (`analyze_frame()`) |
| `screen/window_detector.py` | Screen monitoring (Chrome URLs, window titles) |
| `screen/blocklist.py` | Distracting sites/apps blocklist management |
| `tracking/analytics.py` | **Stats computation - MATH MUST ADD UP** |
| `licensing/license_manager.py` | License validation, Stripe payment, license keys |
| `licensing/stripe_integration.py` | Stripe Checkout API wrapper |
| `gui/payment_screen.py` | Payment gate UI (first launch) |
| `gui/app.py` | Desktop GUI (tkinter) - main application |

*Ignore: `detection.py`, `phone_detector.py` (legacy)*

## Critical Rules

1. **Math Must Add Up**: `present + away + gadget + screen_distraction + paused = total` in `analytics.py`
2. **AI-Only Detection** (Camera): OpenAI Vision API only (~$0.06-0.12/min)
3. **Screen Detection**: Local pattern matching first, AI fallback optional
4. **Time Format**: Use `_format_time()` → "1m 30s" not "1.5 minutes"

## Event Types

- `present`: At desk, focused
- `away`: Not visible or far from desk
- `gadget_suspected`: Actively using phone/tablet/controller/TV
- `screen_distraction`: Distracting website/app detected (YouTube, Netflix, etc.)
- `paused`: User manually paused session

## Monitoring Modes

- `camera_only`: Default - camera detection only (backward compatible)
- `screen_only`: Screen monitoring only (no API calls for camera)
- `both`: Camera + screen monitoring (combined detection)

## Pause & Alerts

- Pause: Timer freezes, no API calls. Focus rate = present/(total-paused)
- Unfocused alerts: 20s → 60s → 120s, then stops until refocus

## Key Constants (config.py)

```python
DETECTION_FPS = 0.33                    # ~3s between camera API calls
SCREEN_CHECK_INTERVAL = 3               # 3s between screen checks
STRIPE_SECRET_KEY, STRIPE_PRICE_ID      # Payment (from .env)
LICENSE_FILE, LICENSE_KEYS_FILE         # License paths
SKIP_LICENSE_CHECK                      # Dev bypass
```

## Common Issues

| Issue | Fix |
|-------|-----|
| "Vision API Error: Expecting value" | JSON parsing failed. Check markdown wrapping |
| "Statistics don't add up" | Verify math in `analytics.py` |
| "Gadget not detected" | Must be actively in use with person looking at it |

## What NOT to Do

- Fallback detection (AI-only) | Save frames to disk (privacy) | Increase API frequency
- Decimal minutes | Stats that don't sum | Run multiple instances

## Setup & Test

```bash
# Required: .env with OPENAI_API_KEY, STRIPE_SECRET_KEY, STRIPE_PRICE_ID
# Or set SKIP_LICENSE_CHECK=true for dev
pip install stripe  # If not installed
python3 main.py     # GUI launches, check ~/Downloads/ for PDF
```

## Data Files

- `data/focus_statements.json` - **REQUIRED** - PDF feedback templates
- `data/blocklist.json` - Screen monitoring blocklist (auto-created)
- `data/license.json` - User license status (gitignored)
- `data/license_keys.json` - Valid key hashes (shipped with app)

## Licensing & Payment

- **Payment**: Stripe Checkout (one-time) - config keys in `.env`
- **Bypass**: License keys (hashed in `license_keys.json`) or `SKIP_LICENSE_CHECK=true`
- **Generate keys**: `python scripts/generate_license_keys.py --count 10 --add-to-file`
- **Flow**: First launch → payment screen → Stripe/key → `license.json` → app starts

## Add New Detection Type

1. Add to `config.py` → 2. Handle in `session.py` → 3. Stats in `analytics.py` → 4. PDF in `pdf_report.py` → 5. GUI status color in `app.py`

## Screen Monitoring & Blocklist

- Blocklist categories: Social Media, Video Streaming, Gaming (toggle in settings)
- **Separate fields**: URLs (`custom_urls`) and Apps (`custom_apps`) in `screen/blocklist.py`
- **URL validation**: TLD check + DNS lookup (with network fallback) in `gui/app.py`
- **App validation**: `KNOWN_APPS` whitelist (1500+ apps) in `gui/app.py` - DO NOT read entire list into context
  - Known apps → accepted silently | Unknown apps → warning "not recognized"
- **Self-cleaning**: Invalid patterns auto-removed at runtime in `check_distraction()`
- Chrome URL detection: macOS (AppleScript), Windows (pywin32)

## Code Standards

Type hints required • Docstrings • `pathlib.Path` • Python 3.9+ • `logger.info()` internal, `print()` user-facing

**Privacy**: Camera frames → OpenAI (30-day retention) → deleted. No video saved locally.
