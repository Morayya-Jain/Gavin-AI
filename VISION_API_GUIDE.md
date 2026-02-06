# Quick Reference: AI-Powered Detection

## 🤖 System Overview

**Everything is AI-powered now!**

```
Camera → OpenAI Vision (every 1 sec) → Detection Results → Log Events
                                     ↓
                              Person present?
                              Gadget in use?
                              Other distractions?
```

## 💰 Cost Per Session

| Duration | Vision API Calls | Cost (gpt-4o-mini) |
|----------|------------------|---------------------|
| 1 min | 60 | $0.06-0.12 |
| 5 min | 300 | $0.30-0.60 |
| 30 min | 1,800 | $1.80-3.60 |
| 1 hour | 3,600 | $3.60-7.20 |

**Plus:** ~$0.0003 for end-of-session summary

## ⚙️ Configuration (config.py)

```python
# Line 15-16: Models
OPENAI_MODEL = "gpt-4o-mini"         # Text summaries
OPENAI_VISION_MODEL = "gpt-4o-mini"  # Image analysis

# Line 21: Detection frequency
VISION_DETECTION_INTERVAL = 1.0  # Every 1 second

# Line 22: Gadget confidence
GADGET_CONFIDENCE_THRESHOLD = 0.5  # 50% confidence

# Line 31: FPS (how often to analyse)
DETECTION_FPS = 1  # 1 frame per second
```

## 🎯 To Reduce Costs

**Option 1: Analyse less frequently**
```python
DETECTION_FPS = 0.5  # Every 2 seconds (cuts cost in half)
```

**Option 2: Increase cache duration**
Edit `camera/vision_detector.py` line 39:
```python
self.detection_cache_duration = 2.0  # Cache 2 seconds
```

**Option 3: Lower detection quality**
```python
# In vision_detector.py, change detail level:
"detail": "auto"  # From "low" (uses more tokens but better)
```

## 🚀 Adding New Detections

Edit `camera/vision_detector.py` prompt (line 87-101):

```python
prompt = """Analyze this webcam frame.

Return JSON:
{
  "person_present": true/false,
  "gadget_visible": true/false,
  "gadget_confidence": 0.0-1.0,
  "eating_drinking": true/false,       # NEW!
  "talking_to_someone": true/false,    # NEW!
  "distraction_type": "phone" | "tablet" | "controller" | "tv" | "eating" | "social" | "none",
  "description": "What you see"
}
"""
```

Then handle new fields in your code!

## 📊 What AI Detects

✅ **Person Present:** Any human visible in frame  
✅ **Gadget ACTIVELY BEING USED:** Phones, tablets, controllers, TV, etc.  
✅ **Gadget Confidence:** How sure (0-100%)  
✅ **Distraction Type:** What kind of gadget/distraction  
✅ **Description:** Brief summary of scene  

### IMPORTANT: Active Gadget Usage Detection

The system detects **active gadget usage** (phones, tablets, controllers, TV, etc.) based on TWO factors:

**Detection Criteria (BOTH required):**
1. **Attention**: Person's eyes/gaze directed AT the gadget
2. **Device State**: Gadget is actively being used (screen ON, controller held)

**Position is IRRELEVANT:**
- Gadget can be on desk OR in hands
- What matters is attention + active engagement

**✅ WILL Detect:**
- Phone/tablet in hands + person looking at screen + screen ON
- Game controller in hands + person playing
- Person looking at TV instead of work
- Nintendo Switch, Steam Deck, etc. when actively used

**❌ Will NOT Detect:**
- Gadget on desk + person looking at computer/elsewhere (no attention)
- Device screen OFF or put away
- Controller sitting on desk, not being held
- Device visible but person clearly focussed on something else

This prevents false positives while catching all real gadget distractions!

Can add:
- Eating/drinking
- Other people
- Anything AI can see!

## 🧪 Testing

```bash
# Quick test
python3 main.py

# Check OpenAI usage
Visit: https://platform.openai.com/usage
```

## 📝 Important Notes

1. **API Key Required** - App won't work without it
2. **Credits Will Decrease** - Vision API is expensive
3. **Much More Accurate** - AI actually sees gadgets!
4. **Extensible** - Easy to add new detections
5. **No Fallbacks** - If AI fails, detection fails (by design)

## 🎓 Why This Approach

**You wanted:**
- ✅ OpenAI for everything
- ✅ No hardcoded methods
- ✅ Accurate gadget detection
- ✅ Extensible system

**You got:** A professional AI-powered detection system!

**Trade-off:** More expensive but MUCH more accurate and flexible! 🚀
