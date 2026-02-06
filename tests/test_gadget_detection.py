#!/usr/bin/env python3
"""
Test script to verify the gadget detection functionality.

This script helps you test that the system correctly distinguishes between:
1. Active gadget usage (should detect)
2. Passive gadget presence (should NOT detect)

Gadgets include: phones, tablets, game controllers, Nintendo Switch, TV, etc.
"""

import sys
import os
from pathlib import Path
import cv2
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from camera.vision_detector import VisionDetector
from dotenv import load_dotenv
import config

# Load environment
load_dotenv()

print("═══════════════════════════════════════════════════════")
print("🧪 Gadget Detection Test - Active Usage Only")
print("═══════════════════════════════════════════════════════\n")

# Check API key
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("❌ No API key found in .env file")
    print("   Please add: OPENAI_API_KEY=your-key-here")
    sys.exit(1)

print("✓ API key found\n")

# Initialize detector
print("Initializing Vision Detector...")
try:
    detector = VisionDetector(api_key=api_key)
    print("✓ Vision detector initialized\n")
except Exception as e:
    print(f"❌ Failed to initialize detector: {e}")
    sys.exit(1)

# Open camera
print("Opening camera...")
cap = cv2.VideoCapture(config.CAMERA_INDEX)

if not cap.isOpened():
    print("❌ Failed to open camera")
    sys.exit(1)

print("✓ Camera opened\n")

print("═══════════════════════════════════════════════════════")
print("📋 Test Scenarios")
print("═══════════════════════════════════════════════════════")
print("\nTest each scenario for 5-10 seconds:\n")
print("1. 📱 Phone on desk + looking at computer")
print("   Expected: gadget_visible = FALSE\n")
print("2. 📱 Phone/tablet in hands + looking at it + screen ON")
print("   Expected: gadget_visible = TRUE (type: phone/tablet)\n")
print("3. 🎮 Game controller in hands + playing")
print("   Expected: gadget_visible = TRUE (type: controller)\n")
print("4. 📺 Looking at TV instead of work")
print("   Expected: gadget_visible = TRUE (type: tv)\n")
print("5. 🎮 Controller on desk, not being held")
print("   Expected: gadget_visible = FALSE\n")
print("KEY: Position doesn't matter - it's attention + active usage!")
print("═══════════════════════════════════════════════════════")
print("\nPress Ctrl+C to stop testing\n")

try:
    frame_count = 0
    last_detection_time = 0
    detection_interval = 3  # Test every 3 seconds
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("❌ Failed to read frame")
            break
        
        # Show camera feed
        cv2.imshow("Gadget Detection Test - Press ESC to quit", frame)
        
        # Test detection every N seconds
        current_time = time.time()
        if current_time - last_detection_time >= detection_interval:
            print(f"\n⏱️  Testing at {time.strftime('%H:%M:%S')}...")
            
            try:
                # Analyse frame
                result = detector.analyze_frame(frame, use_cache=False)
                
                # Print results
                print("─" * 55)
                print(f"  Person Present:    {result['person_present']}")
                print(f"  At Desk:           {result.get('at_desk', 'N/A')}")
                print(f"  Gadget Visible:    {result['gadget_visible']}")
                print(f"  Gadget Confidence: {result['gadget_confidence']:.2f}")
                print(f"  Distraction Type:  {result['distraction_type']}")
                print("─" * 55)
                
                # Interpretation
                if result['gadget_visible']:
                    print(f"  ✅ DETECTED: Active {result['distraction_type']} usage")
                    if result['gadget_confidence'] > 0.7:
                        print("  💪 High confidence - clear gadget usage")
                    else:
                        print("  ⚠️  Moderate confidence - possible gadget usage")
                else:
                    print("  ✓ NO DETECTION: Not actively using any gadget")
                
            except Exception as e:
                print(f"  ❌ Error during detection: {e}")
            
            last_detection_time = current_time
        
        # Check for quit
        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC key
            break
        elif key == ord('q'):
            break
        
        frame_count += 1

except KeyboardInterrupt:
    print("\n\n✓ Test stopped by user")

finally:
    cap.release()
    cv2.destroyAllWindows()
    print("\n═══════════════════════════════════════════════════════")
    print("Test completed")
    print("═══════════════════════════════════════════════════════")
    print("\n✅ If the detection worked correctly:")
    print("   - Gadget on desk + looking at computer: gadget_visible = False")
    print("   - Gadget in use + looking at it: gadget_visible = True")
    print("   - Position doesn't matter - it's attention + active engagement!")
    print("\n❌ If detection wasn't accurate:")
    print("   - Try adjusting GADGET_CONFIDENCE_THRESHOLD in config.py")
    print("   - Ensure good lighting for better AI vision")
    print("   - Make attention clear (look directly at gadget or away)")
    print("   - Ensure device screen brightness is visible to camera")
    print()
