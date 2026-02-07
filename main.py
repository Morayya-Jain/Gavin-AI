#!/usr/bin/env python3
"""
BrainDock - Main Entry Point

A local AI-powered focus tracker that monitors presence and phone usage
via webcam, logs events, and generates PDF reports with AI-powered insights.

Usage:
    python main.py          # Launch menu bar app (default)
    python main.py --cli    # Launch CLI mode
"""

# =============================================================================
# PyInstaller bundled app path fix - MUST BE BEFORE ANY OTHER IMPORTS
# =============================================================================
import os
import sys

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _bundle_dir = sys._MEIPASS
    os.chdir(_bundle_dir)
    if _bundle_dir not in sys.path:
        sys.path.insert(0, _bundle_dir)

import time
import logging
import threading
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

import config
from instance_lock import check_single_instance, get_existing_pid
from camera.capture import CameraCapture
from camera import create_vision_detector, get_event_type
from tracking.session import Session
from tracking.analytics import compute_statistics
from reporting.pdf_report import generate_report

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT
)
logger = logging.getLogger(__name__)

# Suppress noisy third-party library logs (HTTP requests, etc.)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


class BrainDock:
    """
    Main application class that orchestrates the focus tracking session.
    """
    
    def __init__(self):
        """Initialize BrainDock."""
        self.session: Optional[Session] = None
        self.running = False
        self.should_stop = False
        self.session_end_time: Optional[datetime] = None  # Captures precise end time
        
    def check_requirements(self) -> bool:
        """
        Check if all requirements are met before starting.
        
        Validates the appropriate API key based on the configured vision provider.
        
        Returns:
            True if all requirements met, False otherwise
        """
        print("\n🔍 Checking requirements...")
        
        # Check the appropriate API key based on vision provider
        vision_provider = config.VISION_PROVIDER.lower()
        
        if vision_provider == "gemini":
            # Gemini is the default provider for bundled builds
            if not config.GEMINI_API_KEY:
                print("\n❌ ERROR: Gemini API key is REQUIRED!")
                print("   This app uses Gemini Vision API for detection.")
                print("   Please set GEMINI_API_KEY in your .env file.")
                print("\n   Get your API key from: https://aistudio.google.com/app/apikey")
                return False
            else:
                print("✓ Gemini API key found")
                print(f"✓ Using vision model: {config.GEMINI_VISION_MODEL}")
        else:
            # OpenAI provider (explicit or fallback)
            if not config.OPENAI_API_KEY:
                print("\n❌ ERROR: OpenAI API key is REQUIRED!")
                print("   This app uses OpenAI Vision API for detection.")
                print("   Please set OPENAI_API_KEY in your .env file.")
                print("\n   Get your API key from: https://platform.openai.com/api-keys")
                return False
            else:
                print("✓ OpenAI API key found")
                print(f"✓ Using vision model: {config.OPENAI_VISION_MODEL}")
        
        # Check camera availability
        print("✓ Camera access ready")
        
        return True
    
    def display_welcome(self):
        """Display welcome message and instructions."""
        print("\n" + "=" * 60)
        print("🎯 BrainDock - AI-Powered Focus Assistant")
        print("=" * 60)
        print("\nThis app will:")
        print("  • Monitor your presence via OpenAI Vision API")
        print("  • Detect phone usage using AI")
        print("  • Generate detailed PDF reports with AI insights")
        print("\nPrivacy: We capture frames for analysis; we don't store them locally.")
        print("OpenAI retains data for up to 30 days per their API data policy.")
        print("All detections and summaries powered by AI!")
        print("\n" + "=" * 60)
    
    def wait_for_start(self):
        """Wait for user to press Enter to start the session."""
        print("\n📚 Press Enter to start your focus session...")
        try:
            input()
            # Small delay to ensure input buffer is clear before starting session
            time.sleep(0.2)
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            sys.exit(0)
    
    def run_session(self):
        """
        Run the main focus session with camera monitoring.
        """
        self.session = Session()
        self.session.start()
        self.running = True
        
        # Small delay to ensure previous input is cleared
        time.sleep(0.3)
        
        # Flush any pending input
        if sys.stdin.isatty():
            try:
                import termios
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
            except (ImportError, OSError):
                pass  # Not available on all platforms (e.g., Windows)
        
        # Start keyboard listener in separate thread
        stop_event = threading.Event()
        keyboard_thread = threading.Thread(
            target=self._keyboard_listener,
            args=(stop_event,),
            daemon=True
        )
        keyboard_thread.start()
        
        print("\n💡 Monitoring your focus session...")
        print("   Press Enter or 'q' to end the session\n")
        
        try:
            # Initialize detector and camera
            detector = create_vision_detector()
            
            with CameraCapture() as camera:
                if not camera.is_opened:
                    print("❌ Failed to open camera. Please check your webcam.")
                    return
                
                frame_count = 0
                last_detection_time = time.time()
                
                # Main monitoring loop
                for frame in camera.frame_iterator():
                    if stop_event.is_set() or self.should_stop:
                        break
                    
                    frame_count += 1
                    
                    # Throttle detection to configured FPS
                    current_time = time.time()
                    time_since_detection = current_time - last_detection_time
                    
                    if time_since_detection >= (1.0 / config.DETECTION_FPS):
                        # Perform detection using OpenAI Vision
                        detection_state = detector.get_detection_state(frame)
                        
                        # Determine event type from detection
                        event_type = get_event_type(detection_state)
                        
                        # Log event if state changed
                        self.session.log_event(event_type)
                        
                        last_detection_time = current_time
                    
                    # Small sleep to prevent CPU overload
                    time.sleep(0.1)
            
        except KeyboardInterrupt:
            print("\n\n⏸️  Session interrupted by user")
        except Exception as e:
            logger.error(f"Error during session: {e}")
            print(f"\n❌ An error occurred: {e}")
        finally:
            # Capture precise end time immediately when session ends
            self.session_end_time = datetime.now()
            self.running = False
            stop_event.set()
    
    def _keyboard_listener(self, stop_event: threading.Event):
        """
        Listen for keyboard input to stop the session.
        
        Args:
            stop_event: Threading event to signal stop
        """
        try:
            # Wait for Enter or 'q'
            user_input = input()
            if not stop_event.is_set():  # Only stop if not already stopped
                stop_event.set()
                self.should_stop = True
        except (EOFError, OSError):
            # Handle input errors gracefully
            pass
        except Exception as e:
            logger.debug(f"Keyboard listener error: {e}")
    
    def end_session(self):
        """End the session and generate report."""
        if not self.session:
            return
        
        print("\n" + "=" * 60)
        print("📊 Finalizing session...")
        print("=" * 60 + "\n")
        
        # End the session with precise end time captured when session actually ended
        # This ensures accurate duration calculation even if report generation takes time
        self.session.end(end_time=self.session_end_time)
        
        # Compute statistics
        print("⚙️  Computing analytics...")
        stats = compute_statistics(
            self.session.events,
            self.session.get_duration()
        )
        
        # Generate PDF report (summary + logs combined)
        print("📄 Generating PDF report...")
        try:
            report_path = generate_report(
                stats,
                self.session.session_id,
                self.session.start_time,
                self.session.end_time
            )
            print(f"✓ Report saved: {report_path}")
        except Exception as e:
            logger.error(f"Failed to generate PDF: {e}")
            print(f"❌ PDF generation failed: {e}")
            return
        
        # Display summary
        self._display_summary(stats)
        
        print(f"\n📂 Your report is ready:")
        print(f"   {report_path}")
        print("\n" + "=" * 60)
        print("✨ Session complete! Keep up the great work!")
        print("=" * 60 + "\n")
    
    def _display_summary(self, stats: dict):
        """
        Display session summary in the console.
        
        Args:
            stats: Statistics dictionary
        """
        print("\n" + "=" * 60)
        print("📈 Session Summary")
        print("=" * 60)
        
        # Statistics
        total_min = stats["total_minutes"]
        focused_min = stats["focused_minutes"]
        away_min = stats["away_minutes"]
        gadget_min = stats["gadget_minutes"]
        focus_pct = (focused_min / total_min * 100) if total_min > 0 else 0
        
        print(f"\n⏱️  Total Duration: {total_min:.1f} minutes")
        print(f"🎯 Focussed Time: {focused_min:.1f} minutes ({focus_pct:.1f}%)")
        print(f"🚶 Away Time: {away_min:.1f} minutes")
        print(f"📱 Gadget Usage: {gadget_min:.1f} minutes")


def check_license_cli() -> bool:
    """
    Check license status for CLI mode.
    
    Returns:
        True if licensed (or license check skipped), False otherwise.
    """
    from licensing.license_manager import get_license_manager
    
    # Check for skip flag
    if config.SKIP_LICENSE_CHECK:
        logger.info("License check skipped (SKIP_LICENSE_CHECK=true)")
        return True
    
    license_manager = get_license_manager()
    
    if license_manager.is_licensed():
        return True
    
    # Not licensed - inform user to use GUI for payment
    print("\n" + "=" * 60)
    print("🔐 License Required")
    print("=" * 60)
    print("\nBrainDock requires a valid license to run.")
    print("\nTo activate your license:")
    print("  1. Run the GUI version: python main.py")
    print("  2. Complete payment via Stripe")
    print("  3. Then you can use CLI mode")
    print("\n" + "=" * 60)
    
    return False


def main_cli():
    """Run the CLI version of the application."""
    # Check license first
    if not check_license_cli():
        sys.exit(0)
    
    tracker = BrainDock()
    
    # Display welcome and check requirements
    tracker.display_welcome()
    
    if not tracker.check_requirements():
        print("\n❌ Requirements not met. Exiting.")
        sys.exit(1)
    
    # Wait for user to start
    tracker.wait_for_start()
    
    # Run the session
    tracker.run_session()
    
    # End session and generate report
    tracker.end_session()


def main_menubar():
    """Run the menu bar / system tray application."""
    from menubar import run_menubar_app
    run_menubar_app()


def main():
    """
    Main entry point — parses arguments and launches appropriate mode.

    Default mode is menu bar unless --cli is specified.
    """
    parser = argparse.ArgumentParser(
        description="BrainDock - AI-Powered Focus Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py          Launch menu bar app (default)
  python main.py --cli    Launch CLI mode
        """
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in CLI mode (terminal-based)",
    )

    args = parser.parse_args()

    # Single instance enforcement
    if not check_single_instance():
        # On Windows, if this process was launched with braindock:// (e.g. auth callback),
        # hand off the URL to the running instance via a file so it can complete login.
        if sys.platform == "win32":
            for arg in sys.argv[1:]:
                if arg.strip().startswith("braindock://"):
                    try:
                        import config
                        config.USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
                        pending = config.USER_DATA_DIR / "pending_deeplink.txt"
                        pending.write_text(arg.strip())
                    except Exception:
                        pass
                    break
        existing_pid = get_existing_pid()
        pid_info = f" (PID: {existing_pid})" if existing_pid else ""
        print(f"\nBrainDock is already running{pid_info}.")
        print("Only one instance can run at a time.\n")
        sys.exit(1)

    if args.cli:
        try:
            main_cli()
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            print(f"\nFatal error: {e}")
            sys.exit(1)
    else:
        # Default to menu bar app
        try:
            main_menubar()
        except KeyboardInterrupt:
            sys.exit(0)
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            print(f"\nFatal error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()

