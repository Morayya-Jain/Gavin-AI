# AI-Powered Detection System

## 🤖 Complete Architecture Overview

BrainDock uses **OpenAI for EVERYTHING**:

```
┌─────────────────────────────────────────────────────┐
│  BRAINDOCK ARCHITECTURE                             │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Camera Frame                                       │
│      ↓                                              │
│  OpenAI Vision API (gpt-4o-mini)                   │
│      ├→ Detects: Person present?                   │
│      ├→ Detects: At desk (close to camera)?        │
│      ├→ Detects: Gadget in use?                    │
│      ├→ Detects: Other distractions?               │
│      └→ Returns: JSON detection results            │
│      ↓                                              │
│  Session Logger                                     │
│      └→ Logs: Event types & timestamps             │
│      ↓                                              │
│  At Session End:                                    │
│      ↓                                              │
│  OpenAI GPT API (gpt-4o-mini)                      │
│      ├→ Analyses: Session statistics               │
│      ├→ Generates: Friendly summary                │
│      └→ Provides: Personalised suggestions         │
│      ↓                                              │
│  PDF Report Generated and Downloaded                 │
│                                                      │
└─────────────────────────────────────────────────────┘
```

## ⚡ Where OpenAI Is Used

### 1. **During Session (Real-Time Detection)**

**File:** `camera/vision_detector.py`  
**When:** Every second (configurable via `DETECTION_FPS`)  
**What:** Analyses camera frame

```python
# Every 1 second:
detector.get_detection_state(frame)
    ↓
OpenAI Vision API Call
    ↓
Returns:
{
  "person_present": true/false,  # Is any body part visible?
  "at_desk": true/false,         # Is person at working distance? (not roaming far away)
  "gadget_visible": true/false,
  "gadget_confidence": 0.0-1.0,
  "distraction_type": "phone" | "tablet" | "controller" | "tv" | "none"
}
```

**Distance-Aware Detection:**
- `person_present=true` + `at_desk=true` → Focussed (at desk)
- `person_present=true` + `at_desk=false` → Away (roaming around room)
- `person_present=false` → Away (not visible)

---

### 2. **After Session (Summary Generation)**

**File:** `main.py` line 191  
**When:** After you press Enter to end session  
**What:** Generates detailed AI insights

```python
# After session ends:
summariser.generate_summary(stats)
    ↓
OpenAI GPT API Call (gpt-4o-mini)
    ↓
Returns:
{
  "summary": "Detailed 4-5 sentence analysis with behaviour patterns...",
  "suggestions": ["specific takeaway 1", "specific takeaway 2", ...]
}
```

**Features:**
- **Detailed Summary (4-5 sentences):** Overall session quality, behaviour patterns, timing/context of distractions, what worked vs what didn't
- **5 Specific Takeaways:** Data-driven recommendations based on actual session patterns, references specific times/events, concrete actionable strategies
- **Pattern Recognition:** Identifies trends like "strong initial focus followed by gadget distraction" or "frequent short breaks vs few long breaks"
- **Honest Assessment:** Direct analysis without generic encouragement

**Cost:** ~$0.0005 per session (increased due to more detailed output)  
**Frequency:** Once per session

---

## 💰 Cost Breakdown

### Per Minute of Session:

| Component | API Calls | Cost |
|-----------|-----------|------|
| Vision API (person detection) | 60/min | $0.06-0.12 |
| Vision API (gadget detection) | 60/min | (same frames) |
| Text Summary | 1/session | $0.0003 |

**Total:** ~$0.06-0.12 per minute + $0.0003 per session

### Example Sessions:

| Duration | Vision Calls | Total Cost |
|----------|--------------|------------|
| 1 minute | 60 | ~$0.06-0.12 |
| 5 minutes | 300 | ~$0.30-0.60 |
| 30 minutes | 1,800 | ~$1.80-3.60 |
| 1 hour | 3,600 | ~$3.60-7.20 |

**Note:** Much more expensive than hardcoded detection, but MUCH more accurate!

---

## ⚙️ Configuration

### File: `config.py`

```python
# Line 15: Model for text summaries
OPENAI_MODEL = "gpt-4o-mini"

# Line 16: Model for vision detection
OPENAI_VISION_MODEL = "gpt-4o-mini"

# Line 21: How often to analyse frames
VISION_DETECTION_INTERVAL = 1.0  # Every 1 second

# Line 22: Gadget confidence threshold
PHONE_CONFIDENCE_THRESHOLD = 0.5  # 50% confidence
```

### Cost Optimisation Options:

**Option 1: Reduce Detection Frequency**
```python
DETECTION_FPS = 0.5  # Analyse every 2 seconds instead of 1
# Cuts cost in half!
```

**Option 2: Use Cheaper Vision Model** (if available)
```python
OPENAI_VISION_MODEL = "gpt-4o-mini"  # Current (cheapest with vision)
```

**Option 3: Increase Cache Duration**
```python
# In vision_detector.py line 39:
self.detection_cache_duration = 2.0  # Cache for 2 seconds instead of 1
```

---

## 🎯 Why This Is Better

### Old System (Hardcoded):
```
❌ MediaPipe face detection
   • Miss: If face at angle
   • Miss: Poor lighting
   • Miss: Partial occlusion

❌ Shape-based gadget detection
   • Miss: Device held at angle
   • Miss: Device partially visible
   • Miss: Dark screens
   • False positive: Books, papers

❌ Behavioural heuristics
   • False positive: Looking at notes
   • False positive: Thinking
   • Miss: Gadget on desk
```

### New System (AI-Powered):
```
✅ OpenAI Vision (GPT-4o-mini with vision)
   • Understands context
   • Recognises all gadget types at any angle
   • Handles poor lighting
   • Distinguishes gadgets from other objects
   • Detects phones, tablets, controllers, TV, etc.
   • Extensible to new detection types
```

---

## 🎯 Gadget Detection: Active Usage Only

### Important Distinction

The system detects **active gadget usage** (phones, tablets, controllers, TV, etc.) based on two key factors:

**Detection Criteria (BOTH required):**
1. **Attention**: Person's eyes/gaze directed AT the gadget
2. **Device State**: Gadget is actively being used (screen ON, controller held)

**Position is IRRELEVANT** - gadget can be anywhere!

**✅ WILL Detect (Active Usage):**
- Phone/tablet in hands + person looking at screen + screen ON
- Game controller in hands + person playing
- Person looking at TV instead of work
- Any scenario where attention + active engagement are present

**❌ Will NOT Detect (Passive Presence):**
- Gadget on desk + person looking at computer/book
- Device screen OFF or black
- Controller sitting on desk, not being held
- Device in pocket/bag
- Device visible but person's attention elsewhere

### Why This Matters

**Problem Solved:**
- People often have devices on their desks while working
- A gadget lying inactive shouldn't count as a distraction
- A device on desk while user works on computer shouldn't count
- Only active engagement (attention + device active) is a true distraction

**Key Insight:**
- **Position doesn't matter** (desk vs. hands vs. lap)
- **What matters:** Where is the person looking? Is the screen on?

**Implementation:**
The Vision API prompt explicitly instructs the AI to check:
1. **Attention**: Is person's gaze directed at the gadget? ✓
2. **Device state**: Is the device actively being used? ✓

This dramatically reduces false positives and accurately tracks real gadget distractions!

---

## 📊 What Gets Detected Now

The Vision API analyses each frame for:

1. **Person Presence**
   - Is someone sitting at the desk?
   - Are they visible in frame?
   - Are they facing the camera?

2. **Gadget Usage**
   - Is any gadget being ACTIVELY USED?
   - Detects: phones, tablets, game controllers, Nintendo Switch, TV
   - Is person's attention/gaze directed AT the gadget?
   - Is the device active (screen ON, controller in use)?
   - Position doesn't matter (can be on desk or in hands)
   - What's the confidence level?

3. **Distractions** (Extensible!)
   - All device types detected as gadgets
   - Games (via controllers)
   - Social media on screen (if visible)
   - Eating/drinking
   - Talking to others
   - Anything AI can identify as distraction!

---

## 🚀 Adding New Detection Types

Want to detect other things? Just modify the prompt!

**File:** `camera/vision_detector.py` line 87-101

**Current prompt:**
```python
prompt = """Analyze this webcam frame for a focus tracking system.

Return a JSON object with these fields:
{
  "person_present": true/false,
  "gadget_visible": true/false (ONLY if actively being used),
  "gadget_confidence": 0.0-1.0,
  "distraction_type": "phone" or "tablet" or "controller" or "tv" or "none",
  "description": "Brief description"
}

CRITICAL: Only detect gadget_visible=true if BOTH conditions are met:
1. Person's attention/gaze is directed AT the gadget
2. Gadget is actively being used (screen ON, controller in hands, etc.)

Position doesn't matter - gadget can be on desk, in hands, on lap, etc.
What matters is: Is person looking at/engaged with it? Is device active?

Examples:
✓ Phone/tablet in hands + person looking at it + screen on = DETECT
✓ Controller in hands + person playing = DETECT
✓ Person watching TV instead of working = DETECT
✗ Phone on desk + person looking at computer = DO NOT DETECT
✗ Controller on desk, not held = DO NOT DETECT
"""
```

**Add more detection:**
```python
prompt = """Analyze this webcam frame for a focus tracking system.

Return a JSON object with these fields:
{
  "person_present": true/false,
  "gadget_visible": true/false,
  "gadget_confidence": 0.0-1.0,
  "eating_drinking": true/false,
  "talking_to_someone": true/false,
  "distraction_type": "phone" or "tablet" or "controller" or "tv" or "eating" or "social" or "none",
  "description": "Brief description"
}
"""
```

Then update your code to handle new fields!

---

## 🔍 How It Works In Detail

### Frame Analysis Flow:

```python
# 1. Capture frame from camera
frame = camera.read_frame()

# 2. Encode to base64
base64_image = encode_frame(frame)

# 3. Send to OpenAI Vision API
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
        ]
    }],
    max_tokens=200
)

# 4. Parse JSON response
result = json.loads(response.choices[0].message.content)

# 5. Log events based on detection
if result["gadget_visible"]:
    session.log_event("gadget_suspected")
```

---

## 💡 Advanced Features You Can Add

### 1. **Posture Detection**
```json
{
  "slouching": true/false,
  "proper_posture": true/false
}
```

### 2. **Screen Visibility**
```json
{
  "screen_visible": true/false,
  "screen_content": "working" or "social_media" or "games"
}
```

### 3. **Fatigue Detection**
```json
{
  "appears_tired": true/false,
  "yawning": true/false,
  "rubbing_eyes": true/false
}
```

### 4. **Environment Quality**
```json
{
  "lighting_quality": "good" or "poor",
  "workspace_organized": true/false,
  "multiple_distractions": true/false
}
```

Just add fields to the prompt and handle them in your code!

---

## 🛡️ Privacy Considerations

**Important:** BrainDock does NOT perform facial verification or identification. We do NOT create or retain biometric templates. The system only detects presence/absence and active gadget usage—no identity processing occurs.

### Frame Capture & Storage:

**What We Do:**
- ✅ Capture frames for analysis; we don't store them locally
- ✅ Frames sent to OpenAI every second (base64 encoded)
- ✅ All detection happens in real-time
- ❌ No video or images saved on your device

**After Session:**
- ✅ Anonymous statistics only (timestamps, event types)
- ❌ NO images sent for summary generation

### OpenAI Data Retention (Vendor Terms):

Per [OpenAI's API Data Usage Policy](https://openai.com/policies/api-data-usage-policies):
- Data retained for up to 30 days for safety/abuse monitoring
- Then permanently deleted
- NOT used to train models
- Zero-day retention available for enterprise (not enabled by default)

**Full policy:** https://openai.com/policies/api-data-usage-policies

---

## 🎓 Best Practices

1. **Cost Management**
   - Start with `DETECTION_FPS = 0.5` (every 2 seconds)
   - Monitor your OpenAI usage dashboard
   - Increase frequency only if needed

2. **Accuracy**
   - Use `gpt-4o-mini` for cost (already very accurate)
   - Upgrade to `gpt-4o` only if you need perfect accuracy

3. **Privacy**
   - Be aware frames are sent to OpenAI
   - All processing is still real-time
   - No local storage of images

4. **Extensibility**
   - Easy to add new detection types
   - Just modify the prompt
   - AI handles the rest!

---

## 🐛 Troubleshooting

### "No person detected when I'm present"

**Check:**
- Is camera positioned correctly?
- Are you in frame?
- Is lighting adequate?
- Check terminal logs for API errors

**Adjust:**
```python
# Be more lenient with presence detection
# Modify vision_detector.py to accept lower confidence
```

### "Gadget not detected when using it"

**Check:**
- Is gadget visible in camera frame?
- Is device screen/controls facing camera?
- Use for 2+ seconds

**Adjust:**
```python
# Lower confidence threshold in config.py
PHONE_CONFIDENCE_THRESHOLD = 0.3  # From 0.5
```

### "Too many API errors"

**Check:**
- API key valid?
- OpenAI account has credits?
- Internet connection stable?

### "Costs too high"

**Reduce:**
```python
DETECTION_FPS = 0.33  # Every 3 seconds
VISION_DETECTION_INTERVAL = 3.0
```

---

## 📈 Expected Results

### Terminal Output During Session:

```
✓ Session started at 09:30 PM
💡 Monitoring your focus session...

INFO: 📱 Gadget detected by AI! Type: phone, Confidence: 0.85
📱 On another gadget (09:32 PM)

INFO: ✓ Gadget no longer in use
✓ Back at desk (09:33 PM)
```

### After Session:

```
🤖 Generating AI insights...
✓ AI summary generated

📊 Session Summary
⏱️  Total Duration: 5m 30s
🎯 Focussed Time: 4m 15s (77.3%)
📺 Gadget Usage: 45s
```

---

## 🎯 Bottom Line

**Complete AI-Powered System:**

✅ **Detection:** OpenAI Vision API  
✅ **Summaries:** OpenAI GPT API  
✅ **No hardcoded fallbacks**  
✅ **Extensible for any detection type**  
✅ **Much more accurate**  
💰 **More expensive** (~$0.06-0.12 per minute)

**This is a professional-grade solution!** 🚀
