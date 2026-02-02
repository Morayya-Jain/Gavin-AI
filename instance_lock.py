"""
Instance Lock - Prevents multiple instances of BrainDock from running.

Cross-platform implementation using file locking:
- Unix (macOS/Linux): fcntl.flock()
- Windows: msvcrt.locking()

The lock is automatically released when the process terminates,
even on crashes, making this fail-safe.
"""

import os
import sys
import logging
import atexit
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _get_lock_file_path() -> Path:
    """
    Get the lock file path, using the appropriate directory for bundled apps.
    
    Returns:
        Path to the lock file in a persistent, writable location.
    """
    # Import here to avoid circular imports
    try:
        from config import USER_DATA_DIR
        return USER_DATA_DIR / ".braindock_instance.lock"
    except ImportError:
        # Fallback if config not available
        return Path(__file__).parent / "data" / ".braindock_instance.lock"


def _is_process_running(pid: int) -> bool:
    """
    Check if a process with the given PID is currently running.
    
    Args:
        pid: Process ID to check.
        
    Returns:
        True if the process is running, False otherwise.
    """
    if pid <= 0:
        return False
    
    try:
        if sys.platform == 'win32':
            # Windows: Use ctypes to check process
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            # Unix: Send signal 0 to check if process exists
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:
        # On any error, assume process might be running (safe default)
        return True


# Lock file location - determined at runtime
LOCK_FILE = _get_lock_file_path()


class InstanceLock:
    """
    Cross-platform instance lock using file locking.
    
    Uses OS-level file locking which is automatically released when
    the process terminates (even on crashes), making it fail-safe.
    
    Usage:
        lock = InstanceLock()
        if not lock.acquire():
            print("Another instance is already running")
            sys.exit(1)
        # ... run application ...
        lock.release()  # Optional - released automatically on exit
    """
    
    def __init__(self, lock_file: Path = None):
        """
        Initialize instance lock.
        
        Args:
            lock_file: Path to lock file (default: data/.braindock_instance.lock)
        """
        self.lock_file = lock_file or LOCK_FILE
        self._lock_handle: Optional[object] = None
        self._acquired = False
    
    def _try_acquire_lock(self, write_pid: bool = False) -> bool:
        """
        Internal method to attempt lock acquisition.
        
        Args:
            write_pid: If True, write our PID to the file after acquiring lock.
        
        Returns:
            True if lock acquired, False otherwise.
        """
        try:
            if sys.platform == 'win32':
                # Windows implementation
                # Open file in read/write binary mode with sharing disabled
                # Use 'r+b' if file exists, 'w+b' otherwise (avoids empty file issues)
                import msvcrt
                
                try:
                    if self.lock_file.exists():
                        self._lock_handle = open(self.lock_file, 'r+b')
                    else:
                        # Create with initial content so we have bytes to lock
                        self._lock_handle = open(self.lock_file, 'w+b')
                        self._lock_handle.write(b'0' * 32)  # Write placeholder content
                        self._lock_handle.flush()
                        self._lock_handle.seek(0)
                except (IOError, OSError) as e:
                    logger.debug(f"Failed to open lock file: {e}")
                    if self._lock_handle:
                        try:
                            self._lock_handle.close()
                        except Exception:
                            pass
                        self._lock_handle = None
                    return False
                
                try:
                    # Lock a reasonable number of bytes to ensure proper locking
                    # Lock 32 bytes to avoid issues with empty files
                    msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_NBLCK, 32)
                    if write_pid:
                        self._lock_handle.seek(0)
                        self._lock_handle.truncate()
                        pid_bytes = str(os.getpid()).encode('utf-8').ljust(32, b'\0')
                        self._lock_handle.write(pid_bytes)
                        self._lock_handle.flush()
                    return True
                except (IOError, OSError):
                    self._lock_handle.close()
                    self._lock_handle = None
                    return False
            else:
                # Unix (macOS/Linux) implementation
                # Open lock file - use 'a+' to not truncate existing content
                self._lock_handle = open(self.lock_file, 'a+')
                
                import fcntl
                try:
                    # LOCK_EX = exclusive lock, LOCK_NB = non-blocking
                    fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if write_pid:
                        self._lock_handle.seek(0)
                        self._lock_handle.truncate()
                        self._lock_handle.write(str(os.getpid()))
                        self._lock_handle.flush()
                    return True
                except (IOError, OSError):
                    self._lock_handle.close()
                    self._lock_handle = None
                    return False
        except Exception:
            if self._lock_handle:
                try:
                    self._lock_handle.close()
                except Exception:
                    pass
                self._lock_handle = None
            return False
    
    def _check_and_clean_stale_lock(self) -> bool:
        """
        Check if the existing lock is stale (process no longer running).
        If stale, clean up and return True so we can retry.
        
        Returns:
            True if stale lock was cleaned up, False otherwise.
        """
        try:
            if not self.lock_file.exists():
                return False
            
            # Read the PID from the lock file
            content = self.lock_file.read_text().strip()
            if not content.isdigit():
                # Invalid content, try to remove
                logger.debug("Lock file has invalid content, removing...")
                self.lock_file.unlink()
                return True
            
            old_pid = int(content)
            
            # Don't remove if it's our own PID (shouldn't happen, but safety check)
            if old_pid == os.getpid():
                return False
            
            # Check if the process is still running
            if _is_process_running(old_pid):
                logger.debug(f"Process {old_pid} is still running")
                return False
            
            # Process is not running - this is a stale lock
            logger.info(f"Removing stale lock from dead process {old_pid}")
            try:
                self.lock_file.unlink()
            except Exception as e:
                logger.warning(f"Failed to remove stale lock file: {e}")
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"Error checking stale lock: {e}")
            return False
    
    def acquire(self) -> bool:
        """
        Try to acquire the instance lock.
        
        Includes stale lock detection: if the lock file exists but the
        process that created it is no longer running, the stale lock
        is automatically cleaned up.
        
        Returns:
            True if lock acquired (no other instance running)
            False if another instance is already running
        """
        try:
            # Ensure directory exists
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            
            # First attempt to acquire lock (with PID write)
            if self._try_acquire_lock(write_pid=True):
                self._acquired = True
                logger.debug(f"Instance lock acquired (PID: {os.getpid()})")
                return True
            
            # Lock failed - check if it's a stale lock from a dead process
            try:
                if self._check_and_clean_stale_lock():
                    # Stale lock cleaned up, try again
                    if self._try_acquire_lock(write_pid=True):
                        self._acquired = True
                        logger.info("Instance lock acquired after cleaning stale lock")
                        return True
            except Exception as cleanup_error:
                # Log cleanup error but don't fail - another instance may be running
                logger.warning(f"Error during stale lock cleanup: {cleanup_error}")
                # Clean up any partially-opened lock handle
                if self._lock_handle is not None:
                    try:
                        self._lock_handle.close()
                    except Exception:
                        pass
                    self._lock_handle = None
            
            # Another instance is genuinely running
            return False
            
        except Exception as e:
            logger.error(f"Error acquiring instance lock: {e}")
            # Clean up any partially-opened lock handle on error
            if self._lock_handle is not None:
                try:
                    self._lock_handle.close()
                except Exception:
                    pass
                self._lock_handle = None
            # On unexpected error, return False (fail-closed for safety)
            # This prevents multiple instances if lock mechanism has issues
            # User can still run the app by deleting the lock file manually if needed
            logger.warning("Instance lock failed - returning False to prevent potential multiple instances")
            return False
    
    def release(self):
        """
        Release the instance lock.
        
        Note: Lock is automatically released when process exits,
        but explicit release is cleaner.
        """
        if self._lock_handle is not None:
            try:
                if sys.platform == 'win32':
                    import msvcrt
                    try:
                        # Unlock the same number of bytes we locked
                        msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_UNLCK, 32)
                    except Exception:
                        pass  # Ignore unlock errors
                # On Unix, closing the file releases flock automatically
                
                self._lock_handle.close()
                self._lock_handle = None
                self._acquired = False
                
                # Clean up lock file (optional, but tidy)
                # On Windows, the file might still be in use briefly - retry with exponential backoff
                max_attempts = 5 if sys.platform == 'win32' else 3
                for attempt in range(max_attempts):
                    try:
                        if self.lock_file.exists():
                            self.lock_file.unlink()
                        break
                    except PermissionError:
                        if attempt < max_attempts - 1:
                            import time
                            # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s
                            delay = 0.1 * (2 ** attempt)
                            time.sleep(delay)
                        else:
                            # Final attempt failed - log but don't crash
                            logger.debug(f"Could not delete lock file after {max_attempts} attempts")
                    except Exception:
                        break  # Ignore other cleanup errors
                    
                logger.debug("Instance lock released")
            except Exception as e:
                logger.warning(f"Error releasing instance lock: {e}")
    
    def is_acquired(self) -> bool:
        """Check if lock is currently held by this instance."""
        return self._acquired
    
    def __enter__(self):
        """Context manager entry."""
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - release lock."""
        self.release()
        return False


# Global instance for module-level functions
_instance_lock: Optional[InstanceLock] = None


def check_single_instance() -> bool:
    """
    Check if this is the only running instance of BrainDock.
    
    Call this at application startup. If it returns False,
    another instance is already running and you should exit.
    
    The lock is automatically registered with atexit for cleanup.
    
    Returns:
        True if this is the only instance (safe to proceed)
        False if another instance is running (should exit)
    """
    global _instance_lock
    
    if _instance_lock is not None:
        # Already checked - return current state
        return _instance_lock.is_acquired()
    
    _instance_lock = InstanceLock()
    acquired = _instance_lock.acquire()
    
    if acquired:
        # Register cleanup on exit
        atexit.register(release_instance_lock)
    
    return acquired


def release_instance_lock():
    """
    Release the instance lock.
    
    Called automatically on exit via atexit, but can be called
    manually if needed.
    """
    global _instance_lock
    if _instance_lock is not None:
        _instance_lock.release()
        _instance_lock = None


def get_existing_pid() -> Optional[int]:
    """
    Try to read the PID of an existing instance from the lock file.
    
    Returns:
        PID of existing instance, or None if not readable
    """
    try:
        lock_file = _get_lock_file_path()
        if lock_file.exists():
            content = lock_file.read_text().strip()
            if content.isdigit():
                return int(content)
    except Exception:
        pass
    return None
