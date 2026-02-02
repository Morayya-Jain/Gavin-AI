# Installation Guide

## Prerequisites

- Python 3.11 or higher
- Webcam (built-in or external)
- API key for AI vision detection (one of the following):
  - **Gemini API key** (recommended, default) - Get from https://aistudio.google.com/app/apikey
  - **OpenAI API key** - Get from https://platform.openai.com/api-keys

## Step 1: Install Python Dependencies

```bash
pip install -r requirements.txt
```

Or if you prefer using pip3:

```bash
pip3 install -r requirements.txt
```

### Dependencies Installed

**Core Dependencies (All Platforms):**
- `opencv-python` - Camera access and image processing
- `openai` - OpenAI Vision API integration
- `google-generativeai` - Gemini Vision API integration (default provider)
- `reportlab` - PDF report generation
- `python-dotenv` - Environment variable management
- `pillow` - Image processing
- `customtkinter` - Modern GUI components
- `stripe` - License/payment processing

**macOS-Specific Dependencies:**
- `pyobjc-framework-Cocoa` - macOS system integration
- `pyobjc-framework-AVFoundation` - Camera permission handling

**Windows-Specific Dependencies:**
- `pywinauto` - Required for browser URL detection in screen monitoring mode

## Step 2: Set Up Environment Variables

1. Create a `.env` file in the project root:

```bash
cp .env.example .env
```

2. Add your API keys to the `.env` file:

```bash
# Required - at least one Vision API key
GEMINI_API_KEY=your-gemini-api-key-here
OPENAI_API_KEY=sk-your-openai-api-key-here

# Optional - for licensed/paid features
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_PRICE_ID=price_...
```

**Note:** By default, BrainDock uses Gemini for vision detection. To switch to OpenAI, set `VISION_PROVIDER=openai` in your `.env` file.

## Step 3: Test Your Camera

Run a quick camera test:

```bash
python3 camera/capture.py
```

You should see output confirming your camera is working.

## Step 4: Run the Application

```bash
python3 main.py
```

For CLI mode (no GUI):

```bash
python3 main.py --cli
```

## Platform-Specific Setup

### macOS

On first launch, BrainDock will request the following permissions:
- **Camera** - Required for focus detection
- **Accessibility** - Required for screen monitoring mode (optional)
- **Screen Recording** - Required for screen monitoring mode (optional)

If you denied permissions accidentally, re-enable them in:
**System Settings → Privacy & Security → [Camera/Accessibility/Screen Recording]**

### Windows

1. **Camera Privacy**: Ensure camera access is enabled in:
   **Settings → Privacy & Security → Camera**

2. **Screen Monitoring**: For full browser URL detection, ensure `pywinauto` is installed:
   ```bash
   pip install pywinauto
   ```

## Troubleshooting

### Camera Issues

**Problem:** "Failed to open camera"

**Solutions:**
- Check if another application is using your webcam (Zoom, Teams, etc.)
- **macOS:** Grant camera permission in System Settings → Privacy & Security → Camera
- **Windows:** Check Settings → Privacy & Security → Camera is enabled
- Try changing `CAMERA_INDEX` in `config.py` (try 0, 1, or 2)

**Problem:** "Camera permission denied" (macOS)

**Solutions:**
- Open System Settings → Privacy & Security → Camera
- Enable BrainDock in the list
- Restart BrainDock

### OpenCV Installation Issues

**Problem:** OpenCV won't install or import

**Solutions:**
- Try installing with: `pip3 install opencv-python-headless`
- On macOS with M1/M2/M3: `arch -arm64 pip3 install opencv-python`

### API Errors

**Problem:** "API key not found"

**Solutions:**
- Verify `.env` file exists in the project root
- Check the API key is correctly formatted
- Ensure there are no extra spaces or quotes around the key

**Problem:** "Rate limit exceeded" or "Quota exceeded"

**Solutions:**
- Check your API account has available credits
- Gemini has generous free tier; OpenAI requires paid credits
- Reduce detection frequency in `config.py` if needed

### Screen Monitoring Issues (Optional Feature)

**Problem:** "Screen monitoring permission denied" (macOS)

**Solutions:**
- Open System Settings → Privacy & Security → Accessibility
- Enable BrainDock
- For URL detection, also enable in Screen Recording
- Restart BrainDock

**Problem:** Browser URLs not detected (Windows)

**Solutions:**
- Ensure `pywinauto` is installed: `pip install pywinauto`
- URL detection works best with Chrome and Edge
- Firefox URL detection is limited due to accessibility API restrictions

**Supported Browsers for URL Detection:**
| Browser | macOS | Windows |
|---------|-------|---------|
| Chrome | ✅ Full | ✅ Full (with pywinauto) |
| Safari | ✅ Full | N/A |
| Edge | ✅ Full | ✅ Full (with pywinauto) |
| Firefox | ❌ Limited* | ❌ Limited* |

*Firefox doesn't expose URLs via accessibility APIs - only app name is detected

## Optional: Virtual Environment

It's recommended to use a virtual environment:

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Monitoring Modes

BrainDock supports three monitoring modes:

1. **Camera Only** (default) - Detects gadgets via webcam
2. **Screen Only** - Monitors active applications/URLs for distractions
3. **Both** - Combines camera and screen monitoring

Configure the mode in settings or via `MONITORING_MODE` in config.

## Next Steps

Once installed, check out the [README.md](README.md) for usage instructions!
