# Vision Model A/B Testing Plan

## Objective

Compare **GPT-4o-mini** (current) vs **Gemini 2.0 Flash** for the BrainDock vision detection system to determine if switching provides acceptable quality at lower cost.

---

## Test Scenarios

### Scenario Categories

| Category | Description | Priority |
|----------|-------------|----------|
| **Presence Detection** | Person visible/not visible | High |
| **Desk Proximity** | At desk vs far away/roaming | High |
| **Gadget Detection** | Active phone/tablet/controller use | High |
| **Edge Cases** | Challenging lighting, angles, occlusions | Medium |
| **False Positive Prevention** | Gadget visible but not in use | High |

---

## Test Dataset

### Required Test Images (Capture 5-10 images per scenario)

#### 1. Presence Detection (10 images)
- [ ] Person clearly at desk, facing camera
- [ ] Person at desk, looking sideways
- [ ] Person partially visible (edge of frame)
- [ ] Empty desk/chair
- [ ] Person far in background (10+ feet away)

#### 2. Desk Proximity (10 images)
- [ ] Person at normal working distance (2-3 feet)
- [ ] Person leaning back in chair
- [ ] Person standing behind desk
- [ ] Person walking in background
- [ ] Only hands visible on desk

#### 3. Gadget Detection - TRUE positives (15 images)
- [ ] Person looking at phone in hand
- [ ] Person scrolling tablet on desk
- [ ] Person holding game controller, looking at TV
- [ ] Person using Nintendo Switch handheld
- [ ] Person watching TV (visible in frame)
- [ ] Person texting with phone at desk level

#### 4. Gadget Detection - FALSE positives to avoid (15 images)
- [ ] Phone on desk, person looking at computer
- [ ] Phone face-down on desk
- [ ] Controller on desk, person working
- [ ] Person wearing smartwatch (should NOT detect)
- [ ] Phone in pocket/bag visible
- [ ] Tablet as second monitor (work use)

#### 5. Edge Cases (10 images)
- [ ] Low light conditions
- [ ] Backlit (window behind person)
- [ ] Multiple people in frame
- [ ] Person wearing headphones
- [ ] Partial face occlusion (hand on chin)

---

## Testing Script

Create `tests/test_model_comparison.py`:

```python
"""
A/B Testing Script for Vision Model Comparison
Compares GPT-4o-mini vs Gemini 2.0 Flash
"""

import os
import json
import time
import cv2
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

# Test image directory
TEST_IMAGES_DIR = Path("tests/ab_test_images")
RESULTS_FILE = Path("tests/ab_test_results.json")


def load_test_images() -> Dict[str, List[Tuple[str, dict]]]:
    """
    Load test images with expected results.
    
    Returns:
        Dict mapping category to list of (image_path, expected_result)
    """
    # Expected results format for each image
    # Create a manifest.json in TEST_IMAGES_DIR with this structure:
    # {
    #   "presence_true_01.jpg": {
    #     "person_present": true,
    #     "at_desk": true,
    #     "gadget_visible": false,
    #     "distraction_type": "none"
    #   },
    #   ...
    # }
    
    manifest_path = TEST_IMAGES_DIR / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Create {manifest_path} with expected results")
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    return manifest


def test_single_image(detector, image_path: str) -> Tuple[dict, float]:
    """
    Test a single image and return result + latency.
    
    Args:
        detector: VisionDetector instance
        image_path: Path to test image
        
    Returns:
        (detection_result, latency_ms)
    """
    frame = cv2.imread(str(image_path))
    if frame is None:
        raise ValueError(f"Could not load image: {image_path}")
    
    start = time.perf_counter()
    result = detector.analyze_frame(frame, use_cache=False)
    latency = (time.perf_counter() - start) * 1000
    
    return result, latency


def calculate_accuracy(results: List[dict], expected: List[dict]) -> dict:
    """
    Calculate accuracy metrics.
    
    Returns:
        Dict with accuracy per field and overall
    """
    fields = ["person_present", "at_desk", "gadget_visible"]
    metrics = {}
    
    for field in fields:
        correct = sum(1 for r, e in zip(results, expected) 
                     if r.get(field) == e.get(field))
        metrics[f"{field}_accuracy"] = correct / len(results) * 100
    
    # Overall accuracy (all fields must match)
    all_correct = sum(1 for r, e in zip(results, expected)
                     if all(r.get(f) == e.get(f) for f in fields))
    metrics["overall_accuracy"] = all_correct / len(results) * 100
    
    return metrics


def run_ab_test():
    """Run the complete A/B test."""
    
    # Initialize both detectors
    from camera.vision_detector import VisionDetector
    # from camera.gemini_detector import GeminiDetector  # Create this
    
    openai_detector = VisionDetector(vision_model="gpt-4o-mini")
    # gemini_detector = GeminiDetector(model="gemini-2.0-flash")
    
    manifest = load_test_images()
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "openai": {"results": [], "latencies": [], "metrics": {}},
        "gemini": {"results": [], "latencies": [], "metrics": {}},
        "expected": []
    }
    
    for image_name, expected in manifest.items():
        image_path = TEST_IMAGES_DIR / image_name
        
        # Test OpenAI
        openai_result, openai_latency = test_single_image(
            openai_detector, image_path
        )
        results["openai"]["results"].append(openai_result)
        results["openai"]["latencies"].append(openai_latency)
        
        # Test Gemini (uncomment when detector ready)
        # gemini_result, gemini_latency = test_single_image(
        #     gemini_detector, image_path
        # )
        # results["gemini"]["results"].append(gemini_result)
        # results["gemini"]["latencies"].append(gemini_latency)
        
        results["expected"].append(expected)
        
        # Rate limiting
        time.sleep(0.5)
    
    # Calculate metrics
    results["openai"]["metrics"] = calculate_accuracy(
        results["openai"]["results"], results["expected"]
    )
    # results["gemini"]["metrics"] = calculate_accuracy(
    #     results["gemini"]["results"], results["expected"]
    # )
    
    # Calculate average latency
    results["openai"]["avg_latency_ms"] = (
        sum(results["openai"]["latencies"]) / len(results["openai"]["latencies"])
    )
    
    # Save results
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    
    print_results(results)
    return results


def print_results(results: dict):
    """Print formatted comparison results."""
    print("\n" + "="*60)
    print("VISION MODEL A/B TEST RESULTS")
    print("="*60)
    
    print("\n📊 ACCURACY COMPARISON")
    print("-"*40)
    
    openai_metrics = results["openai"]["metrics"]
    print(f"\nGPT-4o-mini:")
    print(f"  • Person Present:  {openai_metrics['person_present_accuracy']:.1f}%")
    print(f"  • At Desk:         {openai_metrics['at_desk_accuracy']:.1f}%")
    print(f"  • Gadget Visible:  {openai_metrics['gadget_visible_accuracy']:.1f}%")
    print(f"  • Overall:         {openai_metrics['overall_accuracy']:.1f}%")
    print(f"  • Avg Latency:     {results['openai']['avg_latency_ms']:.0f}ms")
    
    # Uncomment when Gemini results available
    # gemini_metrics = results["gemini"]["metrics"]
    # print(f"\nGemini 2.0 Flash:")
    # print(f"  • Person Present:  {gemini_metrics['person_present_accuracy']:.1f}%")
    # ...


if __name__ == "__main__":
    run_ab_test()
```

---

## Setup Instructions

### Step 1: Create Test Image Directory

```bash
mkdir -p tests/ab_test_images
```

### Step 2: Capture Test Images

Use your webcam to capture test images for each scenario:

```python
# Quick capture script (run separately)
import cv2

cap = cv2.VideoCapture(0)
count = 0

while True:
    ret, frame = cap.read()
    cv2.imshow('Press SPACE to capture, Q to quit', frame)
    
    key = cv2.waitKey(1)
    if key == ord(' '):
        filename = f"tests/ab_test_images/test_{count:03d}.jpg"
        cv2.imwrite(filename, frame)
        print(f"Saved: {filename}")
        count += 1
    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```

### Step 3: Create Manifest File

Create `tests/ab_test_images/manifest.json`:

```json
{
  "presence_desk_01.jpg": {
    "person_present": true,
    "at_desk": true,
    "gadget_visible": false,
    "distraction_type": "none"
  },
  "presence_far_01.jpg": {
    "person_present": true,
    "at_desk": false,
    "gadget_visible": false,
    "distraction_type": "none"
  },
  "empty_desk_01.jpg": {
    "person_present": false,
    "at_desk": false,
    "gadget_visible": false,
    "distraction_type": "none"
  },
  "phone_active_01.jpg": {
    "person_present": true,
    "at_desk": true,
    "gadget_visible": true,
    "distraction_type": "phone"
  },
  "phone_on_desk_not_using_01.jpg": {
    "person_present": true,
    "at_desk": true,
    "gadget_visible": false,
    "distraction_type": "none"
  }
}
```

### Step 4: Implement Gemini Detector

Create `camera/gemini_detector.py` (similar structure to `vision_detector.py`).

### Step 5: Run the Test

```bash
python -m tests.test_model_comparison
```

---

## Success Criteria

### Minimum Acceptable Thresholds

| Metric | Threshold | Importance |
|--------|-----------|------------|
| Person Present Accuracy | ≥ 95% | Critical |
| At Desk Accuracy | ≥ 90% | High |
| Gadget Detection Accuracy | ≥ 85% | High |
| False Positive Rate | ≤ 10% | High |
| Average Latency | ≤ 2000ms | Medium |

### Decision Matrix

| Gemini vs GPT-4o-mini | Action |
|-----------------------|--------|
| Accuracy within 5% AND cheaper | **Switch to Gemini** |
| Accuracy 5-10% worse AND 50%+ cheaper | Consider switching, test more |
| Accuracy 10%+ worse | **Stay with GPT-4o-mini** |
| Accuracy better AND cheaper | **Definitely switch** |

---

## Cost Tracking

### During Testing

Track actual API costs for the test run:

| Model | Test Images | Est. Cost |
|-------|-------------|-----------|
| GPT-4o-mini | 60 images | ~$0.02 |
| Gemini 2.0 Flash | 60 images | ~$0.01 |

### Projected Monthly Savings

```
Current (GPT-4o-mini): ~$10/month (at 0.33 FPS, 8hr/day)
Gemini 2.0 Flash:      ~$4/month
Potential Savings:     ~$6/month (60%)
```

---

## Timeline

| Phase | Tasks | Duration |
|-------|-------|----------|
| **1. Setup** | Create test images, manifest | 1-2 hours |
| **2. Implement** | Create Gemini detector | 1-2 hours |
| **3. Test** | Run A/B comparison | 30 min |
| **4. Analyse** | Review results, decide | 30 min |
| **5. Migrate** | Switch if approved | 1 hour |

**Total estimated effort: 4-6 hours**

---

## Notes

- Run tests at different times of day (lighting varies)
- Include your actual workspace setup in test images
- Test with items you actually have (your phone model, etc.)
- Re-run test if either model gets updated
- Keep test images for regression testing after any changes
