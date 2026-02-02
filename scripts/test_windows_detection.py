#!/usr/bin/env python3
"""
Windows Screen Detection Test Script

Run this script on Windows while a browser is open with YouTube or another
blocked site to see what BrainDock is detecting.

Usage:
    python scripts/test_windows_detection.py
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screen.window_detector import WindowDetector, get_screen_state
from screen.blocklist import Blocklist, BlocklistManager, QUICK_SITES
import config


def main():
    print("=" * 60)
    print("BrainDock Windows Detection Test")
    print("=" * 60)
    print()
    
    # Test 1: Check platform
    print(f"1. Platform: {sys.platform}")
    if sys.platform != "win32":
        print("   WARNING: This script is designed for Windows!")
    print()
    
    # Test 2: Check quick sites configuration
    print("2. Quick Sites Configuration:")
    print(f"   Available quick sites: {list(QUICK_SITES.keys())}")
    
    blocklist = Blocklist()  # Create with defaults
    print(f"   Enabled quick sites: {blocklist.enabled_quick_sites}")
    print(f"   All patterns: {blocklist.get_all_patterns()[:10]}...")  # First 10
    print()
    
    # Test 3: Window detection
    print("3. Window Detection Test:")
    detector = WindowDetector()
    
    # Check permission
    has_permission = detector.check_permission()
    print(f"   Permission check: {has_permission}")
    
    # Get active window
    window_info = detector.get_active_window()
    
    if window_info:
        print(f"   App Name: '{window_info.app_name}'")
        print(f"   Window Title: '{window_info.window_title}'")
        print(f"   Is Browser: {window_info.is_browser}")
        print(f"   URL: {window_info.url}")
        print(f"   Page Title: '{window_info.page_title}'")
    else:
        print("   ERROR: Could not get window info!")
    print()
    
    # Test 4: Full screen state with blocklist
    print("4. Screen State with Blocklist:")
    screen_state = get_screen_state(blocklist)
    print(f"   Is Distracted: {screen_state.get('is_distracted')}")
    print(f"   Distraction Source: {screen_state.get('distraction_source')}")
    print(f"   App Name: {screen_state.get('app_name')}")
    print(f"   Window Title: {screen_state.get('window_title')}")
    print(f"   URL: {screen_state.get('url')}")
    print(f"   Page Title: {screen_state.get('page_title')}")
    print(f"   Is Browser: {screen_state.get('is_browser')}")
    print(f"   Error: {screen_state.get('error')}")
    print()
    
    # Test 5: Manual pattern matching test
    print("5. Manual Pattern Match Test:")
    
    if window_info:
        # Test matching against youtube.com
        test_patterns = ["youtube.com", "instagram.com", "netflix.com"]
        
        for pattern in test_patterns:
            is_match, source = blocklist.check_distraction(
                url=window_info.url,
                window_title=window_info.window_title,
                app_name=window_info.app_name,
                page_title=window_info.page_title if hasattr(window_info, 'page_title') else None
            )
            if is_match:
                print(f"   Pattern '{pattern}': MATCHED via '{source}'")
                break
        else:
            print("   No patterns matched.")
            
            # Debug: check what patterns would match
            print()
            print("   Debug - checking individual components:")
            
            if window_info.url:
                print(f"   - URL present: '{window_info.url[:50]}...'")
            else:
                print("   - URL: None (this is why domain matching may fail)")
                
            if window_info.page_title:
                print(f"   - Page title: '{window_info.page_title}'")
                # Check if youtube would match
                if "youtube" in window_info.page_title.lower():
                    print("     ^ 'youtube' IS in page title!")
                else:
                    print("     ^ 'youtube' NOT in page title")
            else:
                print("   - Page title: None")
    
    print()
    print("=" * 60)
    print("Test complete!")
    print()
    print("NEXT STEPS:")
    print("1. Open YouTube (or another blocked site) in your browser")
    print("2. Wait 2 seconds, then run this script again")
    print("3. Share the output to help debug the issue")
    print("=" * 60)


if __name__ == "__main__":
    main()
