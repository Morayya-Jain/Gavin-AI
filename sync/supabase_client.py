"""
BrainDockSync — Supabase authentication and data synchronisation client.

Handles:
- Auth token storage and refresh
- Browser-based login (Cursor-style local HTTP callback)
- Subscription checks
- Settings fetch (with local caching for offline fallback)
- Session upload after completion
- Device registration

All file paths use config.USER_DATA_DIR for cross-platform support.
"""

import sys
import json
import hashlib
import platform
import uuid
import logging
import webbrowser
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional

import config
from screen.blocklist import Blocklist

logger = logging.getLogger(__name__)


class BrainDockSync:
    """
    Supabase client wrapper for BrainDock desktop app.

    Manages authentication, settings sync, and session uploads.
    Works offline gracefully by caching settings locally.
    """

    def __init__(self, supabase_url: str = "", supabase_key: str = "") -> None:
        """
        Initialise the sync client.

        Args:
            supabase_url: Supabase project URL (falls back to config).
            supabase_key: Supabase anon/public key (falls back to config).
        """
        self._url = supabase_url or getattr(config, "SUPABASE_URL", "")
        self._key = supabase_key or getattr(config, "SUPABASE_ANON_KEY", "")

        # Paths (platform-aware via config.USER_DATA_DIR)
        self.data_dir: Path = config.USER_DATA_DIR
        self.auth_file: Path = self.data_dir / "auth.json"
        self.settings_cache_file: Path = self.data_dir / "settings_cache.json"

        # Supabase client (lazy — only created when credentials exist)
        self._client = None
        self._init_client()

    # ------------------------------------------------------------------
    # Client initialisation
    # ------------------------------------------------------------------

    def _init_client(self) -> None:
        """Create the Supabase client if credentials are available."""
        if not self._url or not self._key:
            logger.info("Supabase credentials not configured — sync disabled")
            return
        try:
            from supabase import create_client
            self._client = create_client(self._url, self._key)
            self._load_stored_session()
            logger.info("Supabase client initialised")
        except ImportError:
            logger.warning("supabase package not installed — sync disabled")
        except Exception as e:
            logger.warning(f"Failed to initialise Supabase client: {e}")

    # ------------------------------------------------------------------
    # Auth token persistence
    # ------------------------------------------------------------------

    def _load_stored_session(self) -> None:
        """Load stored auth tokens from disk if they exist."""
        if not self._client or not self.auth_file.exists():
            return
        try:
            data = json.loads(self.auth_file.read_text())
            access_token = data.get("access_token", "")
            refresh_token = data.get("refresh_token", "")
            if access_token and refresh_token:
                self._client.auth.set_session(access_token, refresh_token)
                logger.info(f"Loaded stored session for {data.get('email', 'unknown')}")
        except Exception as e:
            logger.warning(f"Failed to load stored session: {e}")

    def _save_session(self, session) -> None:
        """
        Save auth tokens to local storage.

        Args:
            session: Supabase auth session object.
        """
        try:
            self.auth_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "user_id": session.user.id,
                "email": session.user.email,
                "expires_at": session.expires_at,
            }
            self.auth_file.write_text(json.dumps(data, indent=2))
            logger.info(f"Auth session saved for {session.user.email}")
        except Exception as e:
            logger.warning(f"Failed to save auth session: {e}")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Check if the sync client is configured and ready."""
        return self._client is not None and bool(self._url) and bool(self._key)

    def is_authenticated(self) -> bool:
        """
        Check if user is currently authenticated.

        Returns:
            True if a valid user session exists.
        """
        if not self._client:
            return False
        try:
            user = self._client.auth.get_user()
            return user is not None
        except Exception:
            return False

    def get_user_email(self) -> str:
        """
        Get current user's email.

        Returns:
            Email string, or empty string if not authenticated.
        """
        if not self._client:
            return ""
        try:
            user = self._client.auth.get_user()
            return user.user.email if user else ""
        except Exception:
            return ""

    def get_stored_email(self) -> str:
        """
        Get email from locally stored auth file (no network call).

        Returns:
            Stored email, or empty string.
        """
        try:
            if self.auth_file.exists():
                data = json.loads(self.auth_file.read_text())
                return data.get("email", "")
        except Exception:
            pass
        return ""

    def login_with_browser(self, dashboard_url: str = "") -> bool:
        """
        Start browser-based login flow (Cursor-style).

        Opens the browser to the BrainDock website login page with a
        localhost callback URL. A local HTTP server captures the auth
        tokens after the user logs in on the website.

        Args:
            dashboard_url: Base URL of the web dashboard.

        Returns:
            True if login succeeded, False otherwise.
        """
        from sync.auth_server import run_auth_callback_server

        url = dashboard_url or getattr(config, "DASHBOARD_URL", "https://braindock.com")

        # Start local server and get port
        result = run_auth_callback_server(website_url=url)

        if result and result.get("access_token"):
            # We got tokens from the callback
            if self._client:
                try:
                    self._client.auth.set_session(
                        result["access_token"],
                        result["refresh_token"],
                    )
                    # Save session to disk
                    session = self._client.auth.get_session()
                    if session:
                        self._save_session(session)

                    # Register device on first login
                    self.register_device()
                    return True
                except Exception as e:
                    logger.error(f"Failed to set session from browser login: {e}")
            else:
                # No Supabase client, but we can still store tokens locally
                try:
                    self.auth_file.parent.mkdir(parents=True, exist_ok=True)
                    self.auth_file.write_text(json.dumps({
                        "access_token": result["access_token"],
                        "refresh_token": result["refresh_token"],
                        "email": result.get("email", ""),
                    }, indent=2))
                    return True
                except Exception as e:
                    logger.error(f"Failed to save browser login tokens: {e}")

        return False

    def login_with_email(self, email: str, password: str) -> Dict:
        """
        Login with email and password (fallback for testing).

        Args:
            email: User email.
            password: User password.

        Returns:
            {"success": bool, "error": str | None}
        """
        if not self._client:
            return {"success": False, "error": "Supabase not configured"}
        try:
            result = self._client.auth.sign_in_with_password({
                "email": email,
                "password": password,
            })
            self._save_session(result.session)
            self.register_device()
            return {"success": True, "error": None}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def logout(self) -> None:
        """Sign out and clear stored tokens."""
        if self._client:
            try:
                self._client.auth.sign_out()
            except Exception:
                pass
        if self.auth_file.exists():
            try:
                self.auth_file.unlink()
            except Exception:
                pass
        logger.info("Logged out and cleared local tokens")

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def check_subscription(self) -> Dict:
        """
        Check if user has active subscription.

        Returns:
            {"has_access": bool, "tier": str, "features": dict}
        """
        if not self._client:
            return {"has_access": False, "tier": "unknown", "features": {}}
        try:
            result = (
                self._client.table("subscriptions")
                .select("status, subscription_tiers(name, features)")
                .eq("status", "active")
                .single()
                .execute()
            )
            if result.data:
                tier = result.data.get("subscription_tiers", {})
                return {
                    "has_access": True,
                    "tier": tier.get("name", "starter"),
                    "features": tier.get("features", {}),
                }
            return {"has_access": False, "tier": "none", "features": {}}
        except Exception as e:
            logger.warning(f"Failed to check subscription: {e}")
            return {"has_access": False, "tier": "unknown", "features": {}}

    # ------------------------------------------------------------------
    # Settings sync
    # ------------------------------------------------------------------

    def fetch_settings(self) -> Dict:
        """
        Fetch user settings and blocklist from Supabase.

        Called once at session start. Falls back to local cache if offline.

        Returns:
            Settings dict with monitoring_mode, enabled_gadgets,
            vision_provider, and blocklist config.
        """
        if not self._client:
            return self._load_cached_settings()

        try:
            settings_result = (
                self._client.table("user_settings")
                .select("*")
                .single()
                .execute()
            )
            blocklist_result = (
                self._client.table("blocklist_configs")
                .select("*")
                .single()
                .execute()
            )

            settings = settings_result.data or {}
            bl = blocklist_result.data or {}

            result = {
                "monitoring_mode": settings.get("monitoring_mode", "camera_only"),
                "enabled_gadgets": settings.get("enabled_gadgets", ["phone"]),
                "vision_provider": settings.get("vision_provider", "gemini"),
                "blocklist": {
                    "enabled_categories": bl.get("enabled_categories", []),
                    "enabled_quick_sites": bl.get("enabled_quick_sites", []),
                    "custom_urls": bl.get("custom_urls", []),
                    "custom_apps": bl.get("custom_apps", []),
                },
            }

            # Cache locally for offline fallback
            self._cache_settings(result)
            return result

        except Exception as e:
            logger.warning(f"Failed to fetch settings from cloud, using cache: {e}")
            return self._load_cached_settings()

    def _cache_settings(self, settings: Dict) -> None:
        """Cache settings locally for offline use."""
        try:
            self.settings_cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.settings_cache_file.write_text(json.dumps(settings, indent=2))
        except Exception as e:
            logger.debug(f"Could not cache settings: {e}")

    def _load_cached_settings(self) -> Dict:
        """Load cached settings (offline fallback)."""
        try:
            if self.settings_cache_file.exists():
                return json.loads(self.settings_cache_file.read_text())
        except Exception:
            pass
        # Return defaults if no cache exists
        return {
            "monitoring_mode": "camera_only",
            "enabled_gadgets": ["phone"],
            "vision_provider": "gemini",
            "blocklist": {
                "enabled_categories": [],
                "enabled_quick_sites": [],
                "custom_urls": [],
                "custom_apps": [],
            },
        }

    # ------------------------------------------------------------------
    # Session upload
    # ------------------------------------------------------------------

    def upload_session(self, session_data: Dict) -> bool:
        """
        Upload completed session data to Supabase.

        Called after session ends and report is generated.

        Args:
            session_data: Dict from SessionEngine._build_session_data().

        Returns:
            True if upload succeeded, False otherwise.
        """
        if not self._client:
            logger.info("Supabase not configured — skipping session upload")
            return False

        try:
            user = self._client.auth.get_user()
            if not user:
                logger.warning("Not authenticated — skipping session upload")
                return False

            session_result = (
                self._client.table("sessions")
                .insert({
                    "user_id": user.user.id,
                    "session_name": session_data.get("session_name"),
                    "start_time": session_data.get("start_time"),
                    "end_time": session_data.get("end_time"),
                    "duration_seconds": session_data.get("duration_seconds"),
                    "active_seconds": session_data.get("active_seconds"),
                    "paused_seconds": session_data.get("paused_seconds", 0),
                    "monitoring_mode": session_data.get("monitoring_mode"),
                    "summary_stats": session_data.get("summary_stats", {}),
                })
                .execute()
            )

            session_id = session_result.data[0]["id"]

            # Upload individual events for the web dashboard
            events = session_data.get("events", [])
            if events:
                event_rows = [
                    {
                        "session_id": session_id,
                        "event_type": e.get("type", ""),
                        "start_time": e.get("start_time"),
                        "end_time": e.get("end_time"),
                        "duration_seconds": e.get("duration", 0),
                    }
                    for e in events
                ]
                self._client.table("session_events").insert(event_rows).execute()

            logger.info(f"Session uploaded to cloud: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to upload session: {e}")
            return False

    # ------------------------------------------------------------------
    # Device registration
    # ------------------------------------------------------------------

    def register_device(self) -> None:
        """Register this device with the user's account."""
        if not self._client:
            return

        try:
            user = self._client.auth.get_user()
            if not user:
                return

            mac = uuid.getnode()
            machine_id = hashlib.sha256(str(mac).encode()).hexdigest()[:32]
            device_name = platform.node() or "Unknown Device"
            os_name = sys.platform

            self._client.table("devices").upsert(
                {
                    "user_id": user.user.id,
                    "machine_id": machine_id,
                    "device_name": device_name,
                    "os": os_name,
                    "app_version": "2.0.0",
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="user_id,machine_id",
            ).execute()

            logger.info(f"Device registered: {device_name} ({os_name})")
        except Exception as e:
            logger.warning(f"Device registration failed (non-critical): {e}")

    # ------------------------------------------------------------------
    # Blocklist conversion
    # ------------------------------------------------------------------

    @staticmethod
    def cloud_settings_to_blocklist(settings: Dict) -> Blocklist:
        """
        Convert cloud settings dict to a local Blocklist object.

        Uses the correct Blocklist dataclass field names:
        enabled_categories, enabled_quick_sites, enabled_gadgets,
        custom_urls, custom_apps.

        Args:
            settings: Settings dict from fetch_settings().

        Returns:
            Blocklist instance for use with the engine.
        """
        bl = settings.get("blocklist", {})
        return Blocklist(
            enabled_categories=set(bl.get("enabled_categories", [])),
            enabled_quick_sites=set(bl.get("enabled_quick_sites", [])),
            enabled_gadgets=set(settings.get("enabled_gadgets", ["phone"])),
            custom_urls=bl.get("custom_urls", []),
            custom_apps=bl.get("custom_apps", []),
        )
