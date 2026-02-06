# Quick Start Guide

Get BrainDock running in 3 minutes!

## 1. Install Dependencies (1 minute)

```bash
pip3 install -r requirements.txt
```

## 2. Set Your OpenAI API Key (30 seconds)

Create a `.env` file:

```bash
echo "OPENAI_API_KEY=your-key-here" > .env
```

Replace `your-key-here` with your actual OpenAI API key from https://platform.openai.com/api-keys

**Note:** This MVP has a **configurable trial limit** (see `config.py`). When time runs out, enter the unlock password to add more time.

## 3. Run It! (30 seconds)

```bash
python3 main.py
```

## What Happens Next?

### GUI Mode (Default)

1. A modern desktop window opens
2. Click **"Start Session"** to begin tracking
3. Watch the status indicator show Focussed/Away/On another gadget
4. Click **"Stop Session"** when you're done
5. Click **"Generate Report"** to get your PDF!

### CLI Mode (Alternative)

Run with `python3 main.py --cli` for terminal-based tracking:

1. Press **Enter** to start tracking
2. Work while the app monitors via webcam
3. Press **Enter** or **'q'** to end the session
4. Get your PDF report with AI insights!

## Example Sessions

### GUI Mode

```
┌────────────────────────────────────┐
│         BrainDock                  │
│         Focus Tracker              │
│          [1h 45m left]             │
│                                    │
│  ● Focussed                        │
│                                    │
│        01:23:45                    │
│      Session Duration              │
│                                    │
│    [ Stop Session ]                │
│                                    │
└────────────────────────────────────┘
```

The badge shows your remaining trial time. Click it for details.

### CLI Mode

```
BrainDock - AI-Powered Focus Assistant
================================================

Press Enter to start your focus session...

Session started at 02:30 PM
Monitoring your focus session...

Moved away from desk (02:35 PM)
Back at desk (02:37 PM)
On another gadget (02:42 PM)

Session ended. Duration: 45m

Finalizing session...
Report saved: ~/Downloads/BrainDock Monday 2.30 PM.pdf
```

## Tips for Best Results

- **Lighting:** Ensure good lighting on your face
- **Position:** Sit facing the camera
- **Distance:** Stay within 1-2 meters of the camera
- **Gadget Detection:** System detects phones, tablets, game controllers, TV, etc.
  - Actively using any gadget = Detected (regardless of position)
  - Gadget on desk but looking at computer = Not detected
- **False Positives:** Device position doesn't matter - it's about active engagement

## Need Help?

- Camera not working? Check [INSTALL.md](INSTALL.md) troubleshooting section
- Questions? Read the full [README.md](README.md)

## What's in the Report?

Your PDF report includes:

- Total session duration  
- Focussed time percentage  
- Away time tracking  
- Gadget usage detection  
- Timeline of your session  
- AI-generated insights  
- Personalised improvement suggestions  

Stay focussed!
