#!/usr/bin/env python3
"""
Gavin AI - Main Entry Point

A local AI-powered study session tracker that monitors student presence
and phone usage via webcam, logs events, and generates PDF reports with
OpenAI-powered insights.

Usage:
    python main.py          # Launch GUI (default)
    python main.py --cli    # Launch CLI mode
    python main.py --gui    # Launch GUI mode (explicit)
"""

import sys
import time
import logging
import threading
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

import config
from camera.capture import CameraCapture
from camera.vision_detector import VisionDetector
from tracking.session import Session
from tracking.analytics import compute_statistics
from ai.summariser import SessionSummariser
from reporting.pdf_report import generate_full_report

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


class GavinAI:
    """
    Main application class that orchestrates the focus tracking session.
    """
    
    def __init__(self):
        """Initialize Gavin AI."""
        self.session: Optional[Session] = None
        self.running = False
        self.should_stop = False
        
    def check_requirements(self) -> bool:
        """
        Check if all requirements are met before starting.
        
        Returns:
            True if all requirements met, False otherwise
        """
        print("\n🔍 Checking requirements...")
        
        # Check OpenAI API key - REQUIRED for vision detection
        if not config.OPENAI_API_KEY:
            print("\n❌ ERROR: OpenAI API key is REQUIRED!")
            print("   This app now uses OpenAI Vision API for detection.")
            print("   Please set OPENAI_API_KEY in your .env file.")
            print("\n   Get your API key from: https://platform.openai.com/api-keys")
            return False
        else:
            print("✓ OpenAI API key found")
            print(f"✓ Using vision model: {config.OPENAI_VISION_MODEL}")
            print(f"✓ Using text model: {config.OPENAI_MODEL}")
        
        # Check camera availability
        print("✓ Camera access ready")
        
        return True
    
    def display_welcome(self):
        """Display welcome message and instructions."""
        print("\n" + "=" * 60)
        print("🎯 Gavin AI - AI-Powered Study Assistant")
        print("=" * 60)
        print("\nThis app will:")
        print("  • Monitor your presence via OpenAI Vision API")
        print("  • Detect phone usage using AI")
        print("  • Generate detailed PDF reports with AI insights")
        print("\nPrivacy: Camera frames are sent to OpenAI for analysis.")
        print("Frames are NOT stored long-term (30-day retention for abuse only).")
        print("All detections and summaries powered by AI!")
        print("\n" + "=" * 60)
    
    def wait_for_start(self):
        """Wait for user to press Enter to start the session."""
        print("\n📚 Press Enter to start your study session...")
        try:
            input()
            # Small delay to ensure input buffer is clear before starting session
            time.sleep(0.2)
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            sys.exit(0)
    
    def run_session(self):
        """
        Run the main study session with camera monitoring.
        """
        self.session = Session()
        self.session.start()
        self.running = True
        
        # Small delay to ensure previous input is cleared
        time.sleep(0.3)
        
        # Flush any pending input
        import sys
        if sys.stdin.isatty():
            try:
                import termios
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
            except:
                pass  # Not available on all platforms
        
        # Start keyboard listener in separate thread
        stop_event = threading.Event()
        keyboard_thread = threading.Thread(
            target=self._keyboard_listener,
            args=(stop_event,),
            daemon=True
        )
        keyboard_thread.start()
        
        print("\n💡 Monitoring your study session...")
        print("   Press Enter or 'q' to end the session\n")
        
        try:
            # Initialize detector and camera
            detector = VisionDetector()
            
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
                        from camera import get_event_type
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
        
        # End the session
        self.session.end()
        
        # Compute statistics
        print("⚙️  Computing analytics...")
        stats = compute_statistics(
            self.session.events,
            self.session.get_duration()
        )
        
        # Generate AI summary
        print("🤖 Generating AI insights...")
        summariser = SessionSummariser()
        summary_data = summariser.generate_summary(stats)
        
        if summary_data["success"]:
            print("✓ AI summary generated")
        else:
            print("⚠️  Using fallback summary (OpenAI unavailable)")
        
        # Save session data
        print("💾 Saving session data...")
        session_file = self.session.save()
        print(f"   Session saved: {session_file}")
        
        # Generate PDF reports (summary + logs)
        print("📄 Generating PDF reports...")
        try:
            summary_path, logs_path = generate_full_report(
                stats,
                summary_data,
                self.session.session_id,
                self.session.start_time,
                self.session.end_time
            )
            print(f"✓ Summary report saved: {summary_path}")
            print(f"✓ Detailed logs saved: {logs_path}")
        except Exception as e:
            logger.error(f"Failed to generate PDF: {e}")
            print(f"❌ PDF generation failed: {e}")
            return
        
        # Display summary
        self._display_summary(stats, summary_data)
        
        print(f"\n📂 Your reports are ready:")
        print(f"   Summary: {summary_path}")
        print(f"   Logs: {logs_path}")
        print("\n" + "=" * 60)
        print("✨ Session complete! Keep up the great work!")
        print("=" * 60 + "\n")
    
    def _display_summary(self, stats: dict, summary_data: dict):
        """
        Display session summary in the console.
        
        Args:
            stats: Statistics dictionary
            summary_data: AI summary data
        """
        print("\n" + "=" * 60)
        print("📈 Session Summary")
        print("=" * 60)
        
        # Statistics
        total_min = stats["total_minutes"]
        focused_min = stats["focused_minutes"]
        away_min = stats["away_minutes"]
        phone_min = stats["phone_minutes"]
        focus_pct = (focused_min / total_min * 100) if total_min > 0 else 0
        
        print(f"\n⏱️  Total Duration: {total_min:.1f} minutes")
        print(f"🎯 Focused Time: {focused_min:.1f} minutes ({focus_pct:.1f}%)")
        print(f"🚶 Away Time: {away_min:.1f} minutes")
        print(f"📱 Phone Usage: {phone_min:.1f} minutes")


def main_cli():
    """Run the CLI version of the application."""
    tracker = GavinAI()
    
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


def main_gui():
    """Run the GUI version of the application."""
    from gui.app import main as gui_main
    gui_main()


def main():
    """
    Main entry point - parses arguments and launches appropriate mode.
    
    Default mode is GUI unless --cli is specified.
    """
    parser = argparse.ArgumentParser(
        description="Gavin AI - AI-Powered Study Focus Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py          Launch GUI (default)
  python main.py --gui    Launch GUI explicitly
  python main.py --cli    Launch CLI mode
        """
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in CLI mode (terminal-based)"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Run in GUI mode (default)"
    )
    
    args = parser.parse_args()
    
    # CLI mode if explicitly requested
    if args.cli:
        try:
            main_cli()
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            print(f"\n❌ Fatal error: {e}")
            sys.exit(1)
    else:
        # Default to GUI mode
        try:
            main_gui()
        except KeyboardInterrupt:
            sys.exit(0)
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            print(f"\n❌ Fatal error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()

