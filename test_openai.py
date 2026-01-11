#!/usr/bin/env python3
"""
Test script to verify OpenAI API integration.
This will make an actual API call and show you the response.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from ai.summariser import SessionSummariser
from dotenv import load_dotenv

# Load environment
load_dotenv()

print("═══════════════════════════════════════════════════════")
print("🧪 OpenAI API Test")
print("═══════════════════════════════════════════════════════\n")

# Check API key
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("❌ No API key found in .env file")
    print("   Please add: OPENAI_API_KEY=your-key-here")
    sys.exit(1)

print(f"✓ API key found: {api_key[:7]}...{api_key[-4:]}")
print(f"  Length: {len(api_key)} characters\n")

# Create summariser
print("Initializing SessionSummariser...")
summariser = SessionSummariser()

if not summariser.client:
    print("❌ OpenAI client failed to initialize")
    sys.exit(1)

print(f"✓ Client initialized")
print(f"  Model: {summariser.model}\n")

# Create test session data
print("Creating test session data...")
test_stats = {
    "total_minutes": 30.0,
    "focused_minutes": 22.0,
    "away_minutes": 5.0,
    "phone_minutes": 3.0,
    "events": [
        {
            "type": "present",
            "type_label": "Focused",
            "start": "02:00 PM",
            "end": "02:22 PM",
            "duration_minutes": 22.0
        },
        {
            "type": "away",
            "type_label": "Away",
            "start": "02:22 PM",
            "end": "02:27 PM",
            "duration_minutes": 5.0
        },
        {
            "type": "phone_suspected",
            "type_label": "Phone Usage",
            "start": "02:27 PM",
            "end": "02:30 PM",
            "duration_minutes": 3.0
        }
    ]
}

print("✓ Test data created")
print(f"  Session: 30 min, 73% focused\n")

# Make API call
print("═══════════════════════════════════════════════════════")
print("🚀 Making OpenAI API call...")
print("═══════════════════════════════════════════════════════\n")

try:
    result = summariser.generate_summary(test_stats)
    
    if result["success"]:
        print("✅ SUCCESS! OpenAI API call worked!\n")
        print("═══════════════════════════════════════════════════════")
        print("📝 AI-Generated Summary:")
        print("═══════════════════════════════════════════════════════")
        print(result["summary"])
        print("\n" + "═══════════════════════════════════════════════════════")
        print("💡 AI-Generated Suggestions:")
        print("═══════════════════════════════════════════════════════")
        for i, suggestion in enumerate(result["suggestions"], 1):
            print(f"{i}. {suggestion}")
        
        print("\n" + "═══════════════════════════════════════════════════════")
        print("✅ TEST PASSED!")
        print("═══════════════════════════════════════════════════════")
        print("\nYour OpenAI API is working correctly!")
        print("Credits should be deducted from your account.")
        print(f"\nEstimated cost of this test: ~$0.0003")
        
    else:
        print("⚠️  API call failed, using fallback")
        print("\n" + "═══════════════════════════════════════════════════════")
        print("Fallback Summary:")
        print("═══════════════════════════════════════════════════════")
        print(result["summary"])
        print("\nSuggestions:")
        for i, suggestion in enumerate(result["suggestions"], 1):
            print(f"{i}. {suggestion}")
        
        print("\n❌ OpenAI API not working - check your API key")
        
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    print("\nPossible issues:")
    print("  1. Invalid API key")
    print("  2. No credits in OpenAI account")
    print("  3. Network connectivity issue")
    print("  4. API key permissions")
    
    import traceback
    print("\nFull traceback:")
    traceback.print_exc()

print("\n═══════════════════════════════════════════════════════")
