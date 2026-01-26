"""
Stripe Integration for BrainDock.

Handles Stripe Checkout session creation, payment verification,
and promo code handling.
"""

import logging
import os
import subprocess
import sys
import traceback
import webbrowser
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Global variable to store the resolved certificate path
_CERT_PATH = None

# Debug log path for instrumentation - use Desktop for visibility from packaged app
_DEBUG_LOG_PATH = os.path.expanduser("~/Desktop/braindock_debug.log")

def _debug_log(hypothesis_id: str, location: str, message: str, data: dict):
    """Write debug log entry to file."""
    # #region agent log
    import json
    import time
    try:
        entry = {"hypothesisId": hypothesis_id, "location": location, "message": message, "data": data, "timestamp": int(time.time() * 1000), "sessionId": "debug-session"}
        with open(_DEBUG_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    # #endregion

# Fix SSL certificates for bundled apps (PyInstaller)
# This must be done BEFORE importing stripe/httpx
def _fix_ssl_certificates():
    """
    Fix SSL certificate paths for PyInstaller bundles.
    
    This function:
    1. Finds the correct certificate path for bundled apps
    2. Sets environment variables for libraries that use them
    3. Patches certifi.where() to return the correct path
    4. Configures httpx to use the correct certificates
    
    Works on both macOS and Windows.
    """
    global _CERT_PATH
    cert_path = None
    
    # Check if we're running from a PyInstaller bundle
    is_bundled = getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')
    
    # #region agent log
    _debug_log("A", "stripe_integration.py:_fix_ssl_certificates:start", "SSL fix starting", {"is_bundled": is_bundled, "meipass": getattr(sys, '_MEIPASS', None), "platform": sys.platform})
    # #endregion
    
    # For bundled apps, explicitly look for certificates in known bundle locations
    if is_bundled:
        meipass = sys._MEIPASS
        
        # Possible certificate locations in PyInstaller bundles
        bundle_cert_paths = [
            os.path.join(meipass, 'certifi', 'cacert.pem'),
        ]
        
        # For macOS .app bundles, also check Resources directory
        if sys.platform == "darwin":
            # _MEIPASS might be .../Contents/MacOS or .../Contents/Frameworks
            # Certificates are often in .../Contents/Resources/certifi
            meipass_parts = meipass.split(os.sep)
            if 'Contents' in meipass_parts:
                contents_idx = meipass_parts.index('Contents')
                contents_path = os.sep.join(meipass_parts[:contents_idx + 1])
                resources_cert = os.path.join(contents_path, 'Resources', 'certifi', 'cacert.pem')
                bundle_cert_paths.insert(0, resources_cert)
        
        # #region agent log
        _debug_log("A", "stripe_integration.py:bundle_paths", "Bundle cert paths to check", {"paths": bundle_cert_paths, "meipass_parts": meipass.split(os.sep)})
        # #endregion
        
        for path in bundle_cert_paths:
            exists = os.path.exists(path)
            # #region agent log
            _debug_log("D", "stripe_integration.py:check_bundle_path", f"Checking bundle path", {"path": path, "exists": exists})
            # #endregion
            if exists:
                cert_path = path
                logger.debug(f"Using bundled SSL certificates: {cert_path}")
                break
        
        if not cert_path:
            logger.warning(f"Could not find certificates in bundle. Searched: {bundle_cert_paths}")
    
    # Platform-specific fallback locations (check BEFORE certifi to use system certs)
    if not cert_path:
        if sys.platform == "darwin":
            # macOS system certificate locations - these always work
            macos_certs = [
                '/etc/ssl/cert.pem',
                '/private/etc/ssl/cert.pem',
                '/usr/local/etc/openssl/cert.pem',
                '/usr/local/etc/openssl@1.1/cert.pem',
                '/opt/homebrew/etc/openssl/cert.pem',
                '/opt/homebrew/etc/openssl@3/cert.pem',
            ]
            for path in macos_certs:
                exists = os.path.exists(path)
                # #region agent log
                _debug_log("B", "stripe_integration.py:check_system_path", f"Checking system path", {"path": path, "exists": exists})
                # #endregion
                if exists:
                    cert_path = path
                    logger.debug(f"Using macOS system SSL certificates: {cert_path}")
                    break
        
        elif sys.platform == "win32":
            # Windows - try ssl module's default paths
            try:
                import ssl
                default_paths = ssl.get_default_verify_paths()
                if default_paths.cafile and os.path.exists(default_paths.cafile):
                    cert_path = default_paths.cafile
                    logger.debug(f"Using Windows SSL default certificates: {cert_path}")
            except Exception:
                pass
    
    # Try certifi module as last resort
    if not cert_path:
        try:
            import certifi
            certifi_path = certifi.where()
            certifi_exists = os.path.exists(certifi_path)
            # #region agent log
            _debug_log("C", "stripe_integration.py:certifi_check", "Certifi.where() result", {"certifi_path": certifi_path, "exists": certifi_exists})
            # #endregion
            if certifi_exists:
                cert_path = certifi_path
                logger.debug(f"Using certifi SSL certificates: {cert_path}")
            else:
                logger.warning(f"certifi.where() returned non-existent path: {certifi_path}")
        except ImportError:
            logger.debug("certifi not available")
        except Exception as e:
            logger.warning(f"Error getting certifi path: {e}")
    
    # #region agent log
    _debug_log("A", "stripe_integration.py:cert_path_result", "Final cert path determined", {"cert_path": cert_path})
    # #endregion
    
    if cert_path:
        _CERT_PATH = cert_path
        
        # Set environment variables
        os.environ['SSL_CERT_FILE'] = cert_path
        os.environ['REQUESTS_CA_BUNDLE'] = cert_path
        os.environ['CURL_CA_BUNDLE'] = cert_path
        
        # Patch certifi.where() to return our path (httpx uses certifi internally)
        try:
            import certifi
            original_where = certifi.where
            certifi.where = lambda: cert_path
            # #region agent log
            _debug_log("C", "stripe_integration.py:certifi_patched", "Patched certifi.where()", {"original": str(original_where()), "patched_to": cert_path})
            # #endregion
            logger.debug("Patched certifi.where() to return correct path")
        except ImportError:
            pass
        
        # CRITICAL: Patch ssl.create_default_context to use our certificate file
        # This is what stripe/httpx actually uses internally
        # We must NOT call the original function because it tries to load_default_certs()
        # which looks for system OpenSSL paths that don't exist in bundled apps
        import ssl
        
        def _patched_create_default_context(purpose=ssl.Purpose.SERVER_AUTH, *, cafile=None, capath=None, cadata=None):
            """Patched ssl.create_default_context that creates context manually."""
            # #region agent log
            _debug_log("G", "stripe_integration.py:patch_called", "Patched create_default_context called", {"purpose": str(purpose), "cafile": cafile, "capath": capath, "cert_path_closure": cert_path})
            # #endregion
            
            try:
                # Create SSLContext with appropriate protocol
                if purpose == ssl.Purpose.SERVER_AUTH:
                    # Client verifying server
                    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    ctx.verify_mode = ssl.CERT_REQUIRED
                    ctx.check_hostname = True
                else:
                    # Server context
                    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    ctx.verify_mode = ssl.CERT_NONE
                    ctx.check_hostname = False
                
                # #region agent log
                _debug_log("G", "stripe_integration.py:context_created", "SSLContext created successfully", {})
                # #endregion
                
                # Set secure defaults (matching what create_default_context does)
                ctx.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
                
                # Load certificates - use provided cafile or our bundled cert
                actual_cafile = cafile if cafile else cert_path
                file_exists = os.path.exists(actual_cafile) if actual_cafile else False
                # #region agent log
                _debug_log("G", "stripe_integration.py:before_load_verify", "About to load_verify_locations", {"actual_cafile": actual_cafile, "file_exists": file_exists, "capath": capath, "cadata_len": len(cadata) if cadata else 0})
                # #endregion
                
                if actual_cafile or capath or cadata:
                    ctx.load_verify_locations(actual_cafile, capath, cadata)
                
                # #region agent log
                _debug_log("G", "stripe_integration.py:load_success", "load_verify_locations succeeded", {})
                # #endregion
                
                return ctx
            except Exception as e:
                # #region agent log
                _debug_log("G", "stripe_integration.py:patch_error", "Error in patched function", {"error": str(e), "error_type": type(e).__name__, "traceback": traceback.format_exc()[-800:]})
                # #endregion
                raise
        
        ssl.create_default_context = _patched_create_default_context
        # #region agent log
        _debug_log("F", "stripe_integration.py:ssl_patched", "Patched ssl.create_default_context() - manual context", {"cert_path": cert_path})
        # #endregion
        logger.debug("Patched ssl.create_default_context to use correct certificates")
        
        logger.info(f"SSL certificates configured: {cert_path}")
    else:
        # #region agent log
        _debug_log("E", "stripe_integration.py:no_cert_found", "No certificate path found!", {})
        # #endregion
        # Log warning but don't fail - some systems use built-in certificate stores
        logger.warning("Could not find SSL certificates - relying on system defaults")
    
    return cert_path

# Apply SSL fix before importing stripe
_CERT_PATH = _fix_ssl_certificates()

# Stripe SDK - imported conditionally to handle missing dependency gracefully
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False
    logger.warning("Stripe SDK not installed. Run: pip install stripe")


class StripeIntegration:
    """
    Handles Stripe API interactions for payment processing.
    
    Provides methods to create checkout sessions, verify payments,
    and handle promo codes.
    """
    
    def __init__(self, secret_key: str, product_price_id: str):
        """
        Initialize Stripe integration.
        
        Args:
            secret_key: Stripe secret API key.
            product_price_id: Stripe Price ID for the product.
        """
        self.secret_key = secret_key
        self.product_price_id = product_price_id
        self._initialized = False
        
        if STRIPE_AVAILABLE and secret_key:
            stripe.api_key = secret_key
            self._initialized = True
            logger.debug("Stripe integration initialized")
        elif not STRIPE_AVAILABLE:
            logger.error("Stripe SDK not available")
        elif not secret_key:
            logger.error("Stripe secret key not configured")
    
    def is_available(self) -> bool:
        """
        Check if Stripe integration is available and configured.
        
        Returns:
            True if Stripe is ready to use.
        """
        return self._initialized
    
    def create_checkout_session(
        self,
        success_url: str = "https://stripe.com",
        cancel_url: str = "https://stripe.com",
        promo_code: Optional[str] = None,
        customer_email: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Create a Stripe Checkout session.
        
        Args:
            success_url: URL to redirect after successful payment.
            cancel_url: URL to redirect if payment is cancelled.
            promo_code: Optional promo code to apply.
            customer_email: Optional pre-filled customer email.
            
        Returns:
            Tuple of (session_id, checkout_url) or (None, error_message) on failure.
        """
        if not self._initialized:
            return None, "Stripe not configured"
        
        try:
            # Import config for terms requirement setting
            import config
            
            # Build session parameters
            session_params = {
                "payment_method_types": ["card"],
                "line_items": [{
                    "price": self.product_price_id,
                    "quantity": 1,
                }],
                "mode": "payment",
                "success_url": success_url + "?session_id={CHECKOUT_SESSION_ID}",
                "cancel_url": cancel_url,
                "allow_promotion_codes": True,  # Allow users to enter promo codes
            }
            
            # Add Terms of Service consent if enabled (requires T&C URL in Stripe Dashboard)
            if config.STRIPE_REQUIRE_TERMS:
                session_params["consent_collection"] = {
                    "terms_of_service": "required"
                }
            
            # Add customer email if provided
            if customer_email:
                session_params["customer_email"] = customer_email
            
            # Apply specific promo code if provided
            if promo_code:
                # Look up the promotion code
                try:
                    promo_codes = stripe.PromotionCode.list(code=promo_code, active=True)
                    if promo_codes.data:
                        session_params["discounts"] = [{
                            "promotion_code": promo_codes.data[0].id
                        }]
                        # Remove allow_promotion_codes if applying a specific code
                        session_params.pop("allow_promotion_codes", None)
                except stripe.error.StripeError as e:
                    logger.warning(f"Failed to apply promo code: {e}")
                    # Continue without the promo code
            
            # Create the session
            # #region agent log
            _debug_log("E", "stripe_integration.py:before_stripe_call", "About to call stripe.checkout.Session.create", {"ssl_cert_file": os.environ.get('SSL_CERT_FILE', 'not set'), "cert_path_global": _CERT_PATH})
            # #endregion
            session = stripe.checkout.Session.create(**session_params)
            
            logger.info(f"Created Stripe checkout session: {session.id[:20]}...")
            return session.id, session.url
            
        except stripe.error.StripeError as e:
            error_msg = str(e)
            logger.error(f"Stripe error creating checkout session: {error_msg}")
            logger.debug(f"Stripe error traceback: {traceback.format_exc()}")
            # #region agent log
            _debug_log("E", "stripe_integration.py:stripe_error", "StripeError caught", {"error": error_msg, "type": type(e).__name__})
            # #endregion
            return None, f"Payment service error: {error_msg}"
        except FileNotFoundError as e:
            # This can happen if SSL certificates are not found or other file issues
            filename = getattr(e, 'filename', None) or 'unknown'
            error_msg = f"File not found: {filename} - {e}"
            logger.error(f"FileNotFoundError in checkout session: {error_msg}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            
            # Log SSL environment for debugging
            ssl_file = os.environ.get('SSL_CERT_FILE', 'not set')
            ssl_exists = os.path.exists(ssl_file) if ssl_file != 'not set' else False
            logger.error(f"SSL_CERT_FILE env: {ssl_file}, exists: {ssl_exists}")
            
            # #region agent log
            _debug_log("E", "stripe_integration.py:file_not_found", "FileNotFoundError caught", {"filename": filename, "error": str(e), "traceback": traceback.format_exc()[-500:], "ssl_cert_file": ssl_file, "ssl_exists": ssl_exists, "cert_path_global": _CERT_PATH})
            # #endregion
            
            # Provide helpful error message
            if 'cert' in str(e).lower() or 'ssl' in str(e).lower() or filename == 'unknown':
                return None, "SSL certificate error. Please restart the app."
            return None, f"Missing file: {filename}"
        except OSError as e:
            # Catch other OS errors (permissions, etc.)
            error_msg = f"OS error: {e}"
            logger.error(f"OSError in checkout session: {error_msg}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return None, f"System error: {e}"
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error creating checkout session: {error_msg}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return None, f"Error: {error_msg}"
    
    def verify_session(self, session_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Verify a Stripe Checkout session payment status.
        
        Args:
            session_id: The Stripe Checkout session ID to verify.
            
        Returns:
            Tuple of (is_paid, session_info) where session_info contains
            payment details or error information.
        """
        if not self._initialized:
            return False, {"error": "Stripe not configured"}
        
        try:
            # Retrieve the session
            session = stripe.checkout.Session.retrieve(session_id)
            
            # Check payment status
            is_paid = session.payment_status == "paid"
            
            info = {
                "session_id": session.id,
                "payment_status": session.payment_status,
                "payment_intent": session.payment_intent,
                "customer_email": session.customer_details.email if session.customer_details else None,
                "amount_total": session.amount_total,
                "currency": session.currency,
                "terms_accepted": session.consent.terms_of_service if session.consent else None,
            }
            
            if is_paid:
                logger.info(f"Session {session_id[:20]}... verified as paid")
            else:
                logger.warning(f"Session {session_id[:20]}... not paid (status: {session.payment_status})")
            
            return is_paid, info
            
        except stripe.error.InvalidRequestError as e:
            error_msg = f"Invalid session ID: {e}"
            logger.error(error_msg)
            return False, {"error": error_msg}
        except stripe.error.StripeError as e:
            error_msg = f"Stripe error: {e}"
            logger.error(error_msg)
            return False, {"error": error_msg}
        except Exception as e:
            error_msg = f"Error verifying session: {e}"
            logger.error(error_msg)
            return False, {"error": error_msg}
    
    def open_checkout(
        self,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        promo_code: Optional[str] = None,
        customer_email: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Create a checkout session and open it in the default browser.
        
        Args:
            success_url: URL to redirect after successful payment.
            cancel_url: URL to redirect if payment is cancelled.
            promo_code: Optional promo code to apply.
            customer_email: Optional pre-filled customer email.
            
        Returns:
            Tuple of (session_id, error_message). Session ID is returned
            even if browser fails to open.
        """
        # Use provided URLs or defaults
        final_success_url = success_url if success_url else "https://stripe.com"
        final_cancel_url = cancel_url if cancel_url else "https://stripe.com"
        
        session_id, result = self.create_checkout_session(
            success_url=final_success_url,
            cancel_url=final_cancel_url,
            promo_code=promo_code,
            customer_email=customer_email
        )
        
        if not session_id:
            return None, result  # result contains error message
        
        # result contains the checkout URL
        checkout_url = result
        
        open_error = self._open_checkout_url(checkout_url)
        if open_error:
            return session_id, open_error
        
        logger.info("Opened Stripe checkout in browser")
        return session_id, None

    def _open_checkout_url(self, checkout_url: str) -> Optional[str]:
        """
        Open the checkout URL in the default browser with fallbacks.
        
        Uses multiple methods to ensure URL opens even in sandboxed/bundled apps.
        
        Args:
            checkout_url: The Stripe Checkout URL to open.
        
        Returns:
            None if opened successfully, otherwise an error message.
        """
        errors = []
        
        # Method 1: macOS - Use AppleScript via osascript (most reliable for bundled apps)
        if sys.platform == "darwin":
            try:
                # AppleScript command to open URL in default browser
                script = f'open location "{checkout_url}"'
                result = subprocess.run(
                    ["/usr/bin/osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    logger.info("Opened URL via AppleScript")
                    return None
                else:
                    errors.append(f"AppleScript failed: {result.stderr}")
                    logger.warning(f"AppleScript failed: {result.stderr}")
            except Exception as e:
                errors.append(f"AppleScript error: {e}")
                logger.warning(f"AppleScript error: {e}")
            
            # Method 2: macOS - Use /usr/bin/open directly
            try:
                result = subprocess.run(
                    ["/usr/bin/open", checkout_url],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    logger.info("Opened URL via /usr/bin/open")
                    return None
                else:
                    errors.append(f"/usr/bin/open failed: {result.stderr}")
                    logger.warning(f"/usr/bin/open failed: {result.stderr}")
            except Exception as e:
                errors.append(f"/usr/bin/open error: {e}")
                logger.warning(f"/usr/bin/open error: {e}")
        
        # Method 3: Windows - Multiple fallback approaches
        if sys.platform.startswith("win"):
            # Method 3a: os.startfile (most common)
            try:
                os.startfile(checkout_url)  # type: ignore[attr-defined]
                logger.info("Opened URL via os.startfile")
                return None
            except Exception as e:
                errors.append(f"Windows startfile error: {e}")
                logger.warning(f"Windows startfile error: {e}")
            
            # Method 3b: Use 'start' command via cmd.exe
            try:
                # 'start' command opens URL in default browser
                result = subprocess.run(
                    ['cmd', '/c', 'start', '', checkout_url],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    shell=False
                )
                if result.returncode == 0:
                    logger.info("Opened URL via cmd start")
                    return None
                else:
                    errors.append(f"cmd start failed: {result.stderr}")
                    logger.warning(f"cmd start failed: {result.stderr}")
            except Exception as e:
                errors.append(f"cmd start error: {e}")
                logger.warning(f"cmd start error: {e}")
            
            # Method 3c: Use PowerShell Start-Process
            try:
                result = subprocess.run(
                    ['powershell', '-Command', f'Start-Process "{checkout_url}"'],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    shell=False
                )
                if result.returncode == 0:
                    logger.info("Opened URL via PowerShell")
                    return None
                else:
                    errors.append(f"PowerShell failed: {result.stderr}")
                    logger.warning(f"PowerShell failed: {result.stderr}")
            except Exception as e:
                errors.append(f"PowerShell error: {e}")
                logger.warning(f"PowerShell error: {e}")
        
        # Method 4: Linux
        if sys.platform.startswith("linux"):
            for cmd in ["/usr/bin/xdg-open", "/usr/bin/gio"]:
                if os.path.exists(cmd):
                    try:
                        args = [cmd, "open", checkout_url] if cmd.endswith("gio") else [cmd, checkout_url]
                        subprocess.Popen(args)
                        logger.info(f"Opened URL via {cmd}")
                        return None
                    except Exception as e:
                        errors.append(f"{cmd} error: {e}")
                        logger.warning(f"{cmd} error: {e}")
        
        # Method 5: Python webbrowser module (last resort)
        try:
            opened = webbrowser.open(checkout_url, new=2)
            if opened:
                logger.info("Opened URL via webbrowser module")
                return None
            errors.append("webbrowser.open returned False")
        except Exception as e:
            errors.append(f"webbrowser error: {e}")
            logger.warning(f"webbrowser error: {e}")
        
        # All methods failed
        error_details = "; ".join(errors) if errors else "Unknown error"
        logger.error(f"All browser open methods failed: {error_details}")
        return f"Could not open browser. Please copy this URL: {checkout_url}"
    
    def validate_promo_code(self, promo_code: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate a promo code with Stripe.
        
        Args:
            promo_code: The promo code to validate.
            
        Returns:
            Tuple of (is_valid, promo_info) with discount details.
        """
        if not self._initialized:
            return False, {"error": "Stripe not configured"}
        
        try:
            # Look up the promotion code
            promo_codes = stripe.PromotionCode.list(code=promo_code, active=True)
            
            if not promo_codes.data:
                return False, {"error": "Invalid or expired promo code"}
            
            promo = promo_codes.data[0]
            coupon = promo.coupon
            
            info = {
                "code": promo_code,
                "promo_id": promo.id,
                "discount_type": "percent" if coupon.percent_off else "amount",
                "discount_value": coupon.percent_off or coupon.amount_off,
                "is_100_percent": coupon.percent_off == 100,
            }
            
            logger.info(f"Promo code '{promo_code}' validated successfully")
            return True, info
            
        except stripe.error.StripeError as e:
            error_msg = f"Stripe error: {e}"
            logger.error(error_msg)
            return False, {"error": error_msg}
        except Exception as e:
            error_msg = f"Error validating promo code: {e}"
            logger.error(error_msg)
            return False, {"error": error_msg}


# Global instance
_stripe_instance: Optional[StripeIntegration] = None


def get_stripe_integration() -> StripeIntegration:
    """
    Get the global StripeIntegration instance.
    
    Returns:
        Singleton StripeIntegration instance.
    """
    global _stripe_instance
    if _stripe_instance is None:
        # Import config here to avoid circular imports
        import config
        _stripe_instance = StripeIntegration(
            secret_key=config.STRIPE_SECRET_KEY,
            product_price_id=config.STRIPE_PRICE_ID
        )
    return _stripe_instance


def reset_stripe_integration() -> None:
    """Reset the global Stripe integration instance (useful for testing)."""
    global _stripe_instance
    _stripe_instance = None
