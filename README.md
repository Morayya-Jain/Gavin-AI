# BrainDock

A local AI-powered focus tracker that monitors presence and **gadget distractions** via webcam, logs events, and generates PDF reports.

## Features

- **Desktop GUI**: Modern, minimal interface with Start/Stop button, status indicator, and timer
- **AI-Powered Detection**: Uses OpenAI Vision API to detect person presence and gadget distractions
- **Smart Gadget Detection**: Detects device usage based on attention + active engagement (not physical position)
  - Detects: Phones, tablets/iPads, game controllers, Nintendo Switch, TV, etc.
  - Detects: Person actively using any gadget (looking at it + device active)
  - Ignores: Gadget on desk but person looking elsewhere, or device inactive
  - Ignores: Smartwatches/Apple Watch (used for time/notifications, not distractions)
- **Session Analytics**: Computes focussed time, away time, and gadget usage statistics
- **PDF Reports**: Professional combined PDF with summary statistics and full session logs
- **Privacy-Conscious**: We capture frames for analysis; we don't store them locally. See [OpenAI's retention policy](https://openai.com/policies/api-data-usage-policies)

## Requirements

- Python 3.11+
- Webcam
- OpenAI API key

## Installation

1. Clone this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and add your OpenAI API key:
   ```bash
   cp .env.example .env
   ```

4. Edit `.env` and add your OpenAI API key:
   ```
   OPENAI_API_KEY=your_actual_api_key_here
   ```

## Usage

### GUI Mode (Default)

Launch the desktop application:

```bash
python main.py
```

The GUI provides:
- **Start/Stop Button** - Control your session
- **Status Indicator** - Real-time display of Focussed/Away/On another gadget
- **Timer** - Track session duration
- **Generate Report** - Create PDF report after session ends

### CLI Mode

For terminal-based usage:

```bash
python main.py --cli
```

### Session Flow

**GUI Mode:**
1. Click "Start Session" to begin
2. The status indicator shows your current state
3. Click "Stop Session" when done
4. Click "Generate Report" to create your PDF

**CLI Mode:**
1. Press Enter to start a focus session
2. The app monitors your presence via webcam
3. Events are logged (present, away, gadget_suspected)
4. Press 'q' or Enter to end the session
5. A PDF report is automatically generated

**Reports include:**
- Page 1: Session statistics (duration, focus rate, time breakdown)
- Page 2+: Complete timeline of all events (showing when you were focussed/away/distracted)

### Reports

PDF reports are automatically saved to your **Downloads folder**:
```
~/Downloads/BrainDock Monday 2.45 PM.pdf
```

Session data is also saved as JSON in `data/sessions/` for future analysis.

## Project Structure

```
braindock/
├── main.py                    # Main entry point (GUI by default, --cli for CLI)
├── config.py                  # Configuration and constants
├── .env.example               # Example environment variables
├── requirements.txt           # Dependencies
├── README.md                  # Documentation
├── assets/                    # Logo images
│   ├── logo_icon.png
│   └── logo_with_text.png
├── gui/
│   ├── __init__.py
│   └── app.py                # Desktop GUI application (tkinter)
├── camera/
│   ├── __init__.py
│   ├── capture.py            # Webcam management
│   └── vision_detector.py    # AI-powered detection (OpenAI Vision API)
├── tracking/
│   ├── __init__.py
│   ├── session.py            # Session management & event logging
│   ├── analytics.py          # Event summarisation & statistics
│   └── usage_limiter.py      # MVP usage time tracking & limits
├── reporting/
│   ├── __init__.py
│   └── pdf_report.py         # PDF generation
├── ai/
│   └── __init__.py
├── data/
│   └── sessions/             # Stored session JSON files
└── tests/
    ├── test_session.py
    └── test_analytics.py
    
Reports are saved to: ~/Downloads/
```

## MVP Usage Limit

This MVP includes a **configurable trial limit** (default: 2 hours) to manage API costs:

- **Time Display**: A badge at the top shows your remaining time
- **Click for Details**: Click the badge to see full usage statistics
- **Time Exhausted**: When time runs out, a lockout screen appears
- **Extend Time**: Click "Request More Time" and enter the password to add 2 more hours

### Setting the Unlock Password

Add the password to your `.env` file:

```
MVP_UNLOCK_PASSWORD=your-secret-password
```

Share this password with authorized users when they need more time.

## Configuration

Edit `config.py` to customise:
- Detection thresholds (face confidence, phone detection angle)
- Camera settings (resolution, FPS)
- OpenAI model selection
- Grace periods for state changes
- MVP usage limits (`MVP_LIMIT_SECONDS`, `MVP_EXTENSION_SECONDS`)

## Privacy & Data

### Frame Capture & Storage
- **We capture frames for analysis; we don't store them locally**
- Frames sent to OpenAI Vision API every 1 second for real-time detection
- No video or images saved on your device

### OpenAI Data Retention (Vendor Terms)
Per [OpenAI's API Data Usage Policy](https://openai.com/policies/api-data-usage-policies):
- Data retained for up to 30 days for safety/abuse monitoring
- Then permanently deleted
- NOT used to train models

### Gadget Detection Privacy
- System detects **active gadget usage** based on two factors:
  1. **Attention**: Is the person looking at/engaged with the gadget?
  2. **Device State**: Is the gadget actively being used?
- **Gadgets detected**: Phones, tablets/iPads, game controllers, Nintendo Switch, TV, etc.
- **Explicitly excluded**: Smartwatches/Apple Watch (not considered distractions)
- **Position doesn't matter**: Gadget can be on desk or in hands
- **Examples:**
  - Phone/tablet in use + looking at it = Detected
  - Game controller in hands + playing = Detected
  - Phone on desk + looking at computer = NOT detected
  - Controller sitting on desk = NOT detected
  - Smartwatch on wrist = NOT detected (checking time is fine)

### Local Data Storage
- **Session data**: Stored locally as JSON (timestamps and event types only)
- **Reports**: PDF files saved to your Downloads folder
- **Frames**: Captured for analysis but never saved to disk

## Troubleshooting

### Reset License/Authentication Status

If you need to reset your Stripe authentication status (e.g., to test the payment flow again or switch accounts), delete the license file:

**macOS:**
```bash
rm ~/Library/Application\ Support/BrainDock/license.json
```

**Windows (Command Prompt):**
```cmd
del "%APPDATA%\BrainDock\license.json"
```

This will clear your saved license and prompt you to authenticate again on next launch.

## Future Enhancements

- macOS/Windows packaging (.app/.exe)
- Session history viewer
- Dashboard with charts and trends
- Configurable detection sensitivity
- Multiple profile support
- Export to CSV/Excel

## License

MIT License - Feel free to use and modify for personal or educational purposes.
