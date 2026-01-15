# Gavin AI

A local AI-powered study session tracker that monitors student presence and **active phone usage** via webcam, logs events, and generates PDF reports with OpenAI-powered insights.

## Features

- **Desktop GUI**: Modern, minimal interface with Start/Stop button, status indicator, and timer
- **AI-Powered Detection**: Uses OpenAI Vision API to detect person presence and active phone usage
- **Smart Phone Detection**: Detects phone usage based on attention + screen state (not physical position)
  - ✅ Detects: Person looking at phone + screen ON (whether on desk or in hands)
  - ❌ Ignores: Phone on desk but person looking elsewhere, or screen OFF
- **Session Analytics**: Computes focused time, away time, and phone usage statistics
- **AI-Generated Insights**: OpenAI GPT provides detailed, personalized summaries and actionable takeaways
  - 4-5 sentence summaries with behavior pattern analysis
  - 5 specific, data-driven recommendations with time references
  - Honest assessment of what worked and what needs improvement
- **PDF Reports**: Professional reports with elegant gradient design, statistics, and AI-generated insights
- **Privacy-Conscious**: Camera frames analyzed by OpenAI (30-day retention), no local video storage

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
- **Status Indicator** - Real-time display of Focused/Away/Phone Detected
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
1. Press Enter to start a study session
2. The app monitors your presence via webcam
3. Events are logged (present, away, phone_suspected)
4. Press 'q' or Enter to end the session
5. A PDF report is automatically generated

**Reports include:**
- Session statistics (duration, focus rate, time breakdown)
- Timeline of events (showing when you were focused/away/distracted)
- **Detailed AI-generated summary**: 4-5 sentence analysis identifying behavior patterns
- **5 specific takeaways**: Data-driven recommendations based on your actual session

### Reports

PDF reports are automatically saved to your **Downloads folder**:
```
~/Downloads/Gavin_AI Monday 2.45 PM.pdf
```

Session data is also saved as JSON in `data/sessions/` for future analysis.

## Project Structure

```
gavin_ai/
├── main.py                    # Main entry point (GUI by default, --cli for CLI)
├── config.py                  # Configuration and constants
├── .env.example               # Example environment variables
├── requirements.txt           # Dependencies
├── README.md                  # Documentation
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
│   └── analytics.py          # Event summarization & statistics
├── reporting/
│   ├── __init__.py
│   └── pdf_report.py         # PDF generation
├── ai/
│   ├── __init__.py
│   └── summariser.py         # OpenAI API integration
├── data/
│   └── sessions/             # Stored session JSON files
└── tests/
    ├── test_session.py
    └── test_analytics.py
    
Reports are saved to: ~/Downloads/
```

## Configuration

Edit `config.py` to customize:
- Detection thresholds (face confidence, phone detection angle)
- Camera settings (resolution, FPS)
- OpenAI model selection
- Grace periods for state changes

## Privacy & Data

### What Gets Analyzed
- **Camera frames** sent to OpenAI Vision API every 1 second
- OpenAI retains images for 30 days (abuse monitoring), then automatically deletes them
- No video or images stored locally on your device

### Phone Detection Privacy
- System detects **active phone usage** based on two factors:
  1. **Attention**: Is the person looking at the phone?
  2. **Screen State**: Is the phone screen ON?
- **Position doesn't matter**: Phone can be on desk or in hands
- **Examples:**
  - ✅ Phone on desk + looking down at it + screen on = Detected
  - ❌ Phone on desk + looking at computer = NOT detected
  - ❌ Phone anywhere + screen off/face-down = NOT detected

### Data Storage
- **Session data**: Stored locally as JSON (timestamps and event types only)
- **Reports**: PDF files saved to your Downloads folder
- **No video recordings**: Camera frames are never saved to disk

### OpenAI Data Usage
- Vision API: Camera frames (for real-time detection)
- GPT API: Session statistics only (no images)
- All data processed per OpenAI's privacy policy

## Future Enhancements

- macOS/Windows packaging (.app/.exe)
- Session history viewer
- Dashboard with charts and trends
- Configurable detection sensitivity
- Multiple profile support
- Export to CSV/Excel

## License

MIT License - Feel free to use and modify for personal or educational purposes.

