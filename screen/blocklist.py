"""
Blocklist management for screen monitoring.

Provides preset categories and custom URL/app blocking
for distraction detection during focus sessions.
"""

import json
import logging
from pathlib import Path

import config
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Preset blocklist categories
# Each pattern covers both web URLs and desktop app window titles where applicable
PRESET_CATEGORIES = {
    "social_media": {
        "name": "Social Media",
        "description": "Social networking sites and apps",
        "patterns": [
            # Facebook
            "facebook.com",
            "fb.com",
            "messenger.com",
            # Twitter/X
            "twitter.com",
            "://x.com",  # More specific to avoid matching netflix.com
            # Instagram
            "instagram.com",
            # TikTok
            "tiktok.com",
            # Reddit
            "reddit.com",
            # LinkedIn
            "linkedin.com",
            # Snapchat
            "snapchat.com",
            "web.snapchat.com",
            # Pinterest
            "pinterest.com",
            # Tumblr
            "tumblr.com",
            # Threads
            "threads.net",
            # BeReal
            "bereal.com",
        ],
        "default_enabled": True,
    },
    "video_streaming": {
        "name": "Video Streaming",
        "description": "Video and streaming platforms",
        "patterns": [
            # YouTube
            "youtube.com",
            "youtu.be",
            # Netflix
            "netflix.com",
            "Netflix",  # Desktop app
            # Hulu
            "hulu.com",
            # Disney+
            "disneyplus.com",
            "Disney+",  # Desktop app
            # Amazon Prime Video
            "primevideo.com",
            "amazon.com/video",
            "Prime Video",  # Desktop app
            # Twitch
            "twitch.tv",
            "Twitch",  # Desktop app
            # Vimeo
            "vimeo.com",
            # Dailymotion
            "dailymotion.com",
            # Crunchyroll
            "crunchyroll.com",
            # HBO Max
            "max.com",
            "hbomax.com",
            # Peacock
            "peacocktv.com",
            # Paramount+
            "paramountplus.com",
            # Apple TV+
            "tv.apple.com",
        ],
        "default_enabled": True,
    },
    "gaming": {
        "name": "Gaming",
        "description": "Gaming platforms, sites, and apps",
        "patterns": [
            # Steam
            "Steam",  # Desktop app
            "steampowered.com",
            "store.steampowered.com",
            # Discord
            "Discord",  # Desktop app
            "discord.com",
            "discord.gg",
            # Epic Games
            "Epic Games",  # Desktop app
            "epicgames.com",
            # Roblox
            "Roblox",  # Desktop app
            "roblox.com",
            # Minecraft
            "Minecraft",  # Desktop app
            "minecraft.net",
            # Xbox
            "xbox.com",
            "Xbox",  # Desktop app
            # PlayStation
            "playstation.com",
            # Itch.io
            "itch.io",
            # GOG
            "gog.com",
            "GOG Galaxy",  # Desktop app
            # Battle.net
            "battle.net",
            "Battle.net",  # Desktop app
            # League of Legends
            "leagueoflegends.com",
            "League of Legends",  # Desktop app
            # Valorant
            "playvalorant.com",
            "VALORANT",  # Desktop app
            # Origin/EA
            "origin.com",
            "ea.com",
            "EA app",  # Desktop app
        ],
        "default_enabled": True,
    },
    "messaging": {
        "name": "Messaging",
        "description": "Chat and messaging apps (some may be productive)",
        "patterns": [
            # WhatsApp
            "WhatsApp",  # Desktop app
            "web.whatsapp.com",
            "whatsapp.com",
            # Telegram
            "Telegram",  # Desktop app
            "web.telegram.org",
            "telegram.org",
            # Messenger (already in social media too)
            "Messenger",  # Desktop app
            # Signal
            "Signal",  # Desktop app
            "signal.org",
            # WeChat
            "WeChat",  # Desktop app
            "wechat.com",
            # Viber
            "Viber",  # Desktop app
            "viber.com",
            # Slack (disabled by default - often productive)
            # "slack.com",
            # "Slack",
        ],
        "default_enabled": False,  # Off by default - may be productive
    },
    "news_entertainment": {
        "name": "News & Entertainment",
        "description": "News sites and entertainment portals",
        "patterns": [
            # Entertainment
            "buzzfeed.com",
            "9gag.com",
            "imgur.com",
            "boredpanda.com",
            "tmz.com",
            "thechive.com",
            # Sports
            "espn.com",
            "bleacherreport.com",
            "sportskeeda.com",
            # Memes/Fun
            "knowyourmeme.com",
            "memedroid.com",
            # Celebrity gossip
            "eonline.com",
            "perezhilton.com",
        ],
        "default_enabled": False,  # Off by default - news may be needed
    },
}


# Quick toggle sites - simplified preset for common distractions
# These are the 6 most common distraction sites that users can quickly toggle
QUICK_SITES = {
    "instagram": {"name": "instagram.com", "patterns": ["instagram.com"]},
    "youtube": {"name": "youtube.com", "patterns": ["youtube.com"]},
    "netflix": {"name": "netflix.com", "patterns": ["netflix.com"]},
    "reddit": {"name": "reddit.com", "patterns": ["reddit.com"]},
    "tiktok": {"name": "tiktok.com", "patterns": ["tiktok.com"]},
    "twitter": {"name": "twitter.com / x.com", "patterns": ["twitter.com", "://x.com", "/x.com/"]},
}


# Page-title matching: structural positions only (exact, start/end after separator).
# Used when URL is unavailable; avoids false positives like "Share to Twitter".
SITE_TITLE_PATTERNS = {
    "youtube": {"variations": ["youtube", "yt"], "mode": "position"},
    "facebook": {"variations": ["facebook", "fb"], "mode": "position"},
    "instagram": {"variations": ["instagram", "ig"], "mode": "position"},
    "twitter": {
        "variations": ["twitter"],
        "mode": "position",
        "exact_end_patterns": [" / x"],  # X.com titles always end "... / X"
    },
    "tiktok": {"variations": ["tiktok", "tik tok"], "mode": "position"},
    "reddit": {"variations": ["reddit"], "mode": "position"},
    "netflix": {"variations": ["netflix"], "mode": "position"},
    "twitch": {"variations": ["twitch"], "mode": "position"},
    "discord": {"variations": ["discord"], "mode": "position"},
    "whatsapp": {"variations": ["whatsapp"], "mode": "position"},
    "telegram": {"variations": ["telegram"], "mode": "position"},
    "snapchat": {"variations": ["snapchat"], "mode": "position"},
    "pinterest": {"variations": ["pinterest"], "mode": "position"},
    "linkedin": {"variations": ["linkedin"], "mode": "position"},
}


@dataclass
class Blocklist:
    """
    Manages the blocklist of distracting URLs and apps.
    
    Combines preset categories with custom user additions.
    URLs and app names are stored separately for better validation.
    """
    
    enabled_categories: Set[str] = field(default_factory=set)
    enabled_quick_sites: Set[str] = field(default_factory=set)
    enabled_gadgets: Set[str] = field(default_factory=set)
    custom_urls: List[str] = field(default_factory=list)
    custom_apps: List[str] = field(default_factory=list)
    # Legacy field for backward compatibility (migrated on load)
    custom_patterns: List[str] = field(default_factory=list)
    # Track patterns that need to be removed (self-cleaning)
    _patterns_to_remove: List[str] = field(default_factory=list, repr=False)
    
    def __post_init__(self):
        """Initialize with default enabled categories and quick sites if empty."""
        if not self.enabled_categories:
            self.enabled_categories = {
                cat_id for cat_id, cat_data in PRESET_CATEGORIES.items()
                if cat_data.get("default_enabled", False)
            }
        
        # Enable all 6 quick sites by default
        if not self.enabled_quick_sites:
            self.enabled_quick_sites = set(QUICK_SITES.keys())
        
        # Default enabled gadgets (only phone if empty)
        if not self.enabled_gadgets:
            self.enabled_gadgets = set(config.DEFAULT_ENABLED_GADGETS)
        
        # Migrate legacy custom_patterns to appropriate fields
        if self.custom_patterns:
            self._migrate_legacy_patterns()
    
    def _migrate_legacy_patterns(self):
        """
        Migrate old custom_patterns to custom_urls or custom_apps.
        
        Heuristic: patterns with dots (.) are URLs, others are app names.
        """
        for pattern in self.custom_patterns:
            if '.' in pattern and not pattern.startswith(' '):
                # Looks like a URL/domain
                if pattern not in self.custom_urls:
                    self.custom_urls.append(pattern)
                    logger.info(f"Migrated legacy pattern '{pattern}' to custom_urls")
            else:
                # Looks like an app name
                if pattern not in self.custom_apps:
                    self.custom_apps.append(pattern)
                    logger.info(f"Migrated legacy pattern '{pattern}' to custom_apps")
        
        # Clear legacy patterns after migration
        self.custom_patterns = []
    
    def get_all_patterns(self) -> List[str]:
        """
        Get all active blocking patterns.
        
        Returns:
            Combined list of patterns from enabled categories, quick sites, and custom additions.
        """
        patterns = []
        
        # Add patterns from enabled categories
        for cat_id in self.enabled_categories:
            if cat_id in PRESET_CATEGORIES:
                patterns.extend(PRESET_CATEGORIES[cat_id]["patterns"])
        
        # Add patterns from enabled quick sites
        for site_id in self.enabled_quick_sites:
            if site_id in QUICK_SITES:
                patterns.extend(QUICK_SITES[site_id]["patterns"])
        
        # Add custom URLs and apps (new separated fields)
        patterns.extend(self.custom_urls)
        patterns.extend(self.custom_apps)
        
        # Legacy support: also add any remaining custom_patterns
        patterns.extend(self.custom_patterns)
        
        return patterns
    
    def check_distraction(
        self,
        url: Optional[str] = None,
        window_title: Optional[str] = None,
        app_name: Optional[str] = None,
        page_title: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if the current screen content matches any blocklist pattern.
        
        This method is safe and never crashes - invalid patterns are automatically
        removed from the blocklist (self-cleaning behaviour).
        
        Domain Matching Rules:
        - Patterns like "x.com" are matched as domain boundaries (not substring)
        - "x.com" will match "x.com", "www.x.com", "://x.com" but NOT "netflix.com"
        - Patterns starting with "://" require that exact prefix (e.g., "://x.com")
        - App names are still matched as substrings for flexibility
        
        Page Title Matching (for browsers when URL unavailable):
        - Extracts site names from page titles (e.g., "YouTube" from window title)
        - Uses smart matching to detect common sites even without URL
        
        Args:
            url: Current browser URL (if available)
            window_title: Active window title
            app_name: Active application name
            page_title: Extracted page title from browser window (fallback when no URL)
            
        Returns:
            Tuple of (is_distracted, matched_pattern)
        """
        patterns = self.get_all_patterns()
        patterns_to_remove = []
        
        # Prepare texts for matching (lowercase)
        url_lower = url.lower() if url else None
        window_title_lower = window_title.lower() if window_title else None
        app_name_lower = app_name.lower() if app_name else None
        page_title_lower = page_title.lower() if page_title else None
        
        # Check each pattern against appropriate targets
        for pattern in patterns:
            try:
                pattern_lower = pattern.lower()
                
                # Determine if pattern is a domain pattern (contains '.')
                is_domain_pattern = '.' in pattern_lower and not pattern_lower.startswith(' ')
                
                if is_domain_pattern:
                    # Domain matching: use boundary-aware matching to prevent
                    # "x.com" from matching "netflix.com"
                    if url_lower and self._match_domain(pattern_lower, url_lower):
                        logger.debug(f"Distraction detected: '{pattern}' matched URL '{url[:50]}'")
                        return True, pattern
                    if window_title_lower and self._match_domain(pattern_lower, window_title_lower):
                        logger.debug(f"Distraction detected: '{pattern}' matched window title")
                        return True, pattern
                    
                    # Only fall back to page title when URL is truly unavailable
                    if page_title_lower and not url_lower:
                        domain_name = self._extract_domain_name(pattern_lower)
                        if domain_name and self._match_site_in_title(domain_name, page_title_lower):
                            logger.debug(f"Distraction detected: '{pattern}' matched page title '{(page_title or '')[:50]}'")
                            return True, pattern
                else:
                    # App name matching: use simple substring match
                    # Check all text sources for app name patterns
                    check_texts = [t for t in [window_title_lower, app_name_lower, page_title_lower] if t]
                    for text in check_texts:
                        if pattern_lower in text:
                            logger.debug(f"Distraction detected: '{pattern}' found in '{text[:50]}'")
                            return True, pattern
                    
            except Exception as e:
                # Log the error and mark pattern for removal (self-cleaning)
                logger.error(f"Invalid pattern '{pattern}' caused error: {e} - marking for removal")
                patterns_to_remove.append(pattern)
                continue  # Move to next pattern
        
        # Auto-clean: remove problematic patterns
        if patterns_to_remove:
            self._remove_invalid_patterns(patterns_to_remove)
        
        return False, None
    
    def _extract_domain_name(self, domain_pattern: str) -> Optional[str]:
        """
        Extract the site name from a domain pattern.
        
        For example:
        - "youtube.com" -> "youtube"
        - "www.facebook.com" -> "facebook"
        - "://x.com" -> "x"
        
        Args:
            domain_pattern: Domain pattern (lowercase)
            
        Returns:
            Site name or None
        """
        # Remove protocol prefixes
        clean = domain_pattern
        for prefix in ["://", "www.", "http://", "https://"]:
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
        
        # Remove path and everything after
        if "/" in clean:
            clean = clean.split("/")[0]
        
        # Get the domain name (before .com, .net, etc.)
        if "." in clean:
            parts = clean.split(".")
            # Usually the first part is the site name
            # But handle cases like "co.uk" domains
            if len(parts) >= 2:
                return parts[0] if parts[0] not in ["www", "m", "mobile", "web"] else parts[1] if len(parts) > 1 else None
        
        return clean if clean else None
    
    def _match_site_in_title(self, site_name: str, title: str) -> bool:
        """
        Check if a site name appears in a page title in a structural position.
        
        Only matches when the site is the primary subject (exact match, start
        or end of title after a separator). Never matches casual mentions
        like "Share to Twitter". For X/Twitter, only matches the exact end
        pattern " / X" to avoid matching the letter "x" everywhere.
        
        Args:
            site_name: Site name to search for (lowercase, e.g., "youtube")
            title: Page title to search in (lowercase)
            
        Returns:
            True if site appears in a structural position in title
        """
        if not site_name or not title:
            return False
        
        config = SITE_TITLE_PATTERNS.get(site_name)
        if not config:
            return False
        
        # X/Twitter: only match exact end patterns, never "x" as substring
        exact_end = config.get("exact_end_patterns") or []
        for pattern in exact_end:
            if title.endswith(pattern):
                return True
        
        # Position-aware matching for variations
        separators = (" - ", " | ", " / ", " -- ")
        short_name_max_len = 3  # variations this short only match exact or end-of-title
        
        for variation in config.get("variations", []):
            if self._title_matches_variation(variation, title, separators, short_name_max_len):
                return True
        
        return False
    
    def _title_matches_variation(
        self, variation: str, title: str, separators: tuple, short_name_max_len: int
    ) -> bool:
        """
        Check if a variation appears in title in a structural position.
        
        Matches: exact title, end-of-title after separator, or (for longer
        names) start-of-title before separator. Short variations (e.g. yt, fb)
        only match exact or end-of-title to avoid false positives.
        """
        if not variation or not title:
            return False
        
        # Exact match
        if title == variation or title.strip() == variation:
            return True
        
        # End-of-title: last segment after a separator equals variation
        for sep in separators:
            if sep in title:
                segments = title.split(sep)
                last = segments[-1].strip() if segments else ""
                if last == variation:
                    return True
        
        # Start-of-title: only for variations longer than short_name_max_len
        if len(variation) <= short_name_max_len:
            return False
        for sep in separators:
            if title.startswith(variation + sep):
                return True
        
        return False
    
    def _match_domain(self, pattern: str, text: str) -> bool:
        """
        Match a domain pattern against text with proper boundary checking.
        
        Prevents false positives like "x.com" matching "netflix.com".
        Supports:
        - Exact match: "x.com" in URL containing "/x.com/"
        - Protocol prefix: "://x.com"
        - www prefix: "www.x.com"
        - Subdomain: ".x.com" (e.g., "mail.x.com")
        
        Args:
            pattern: Domain pattern (lowercase)
            text: Text to search in (lowercase)
            
        Returns:
            True if domain pattern matches with proper boundaries
        """
        # If pattern includes protocol prefix (e.g., "://x.com"), match directly
        if pattern.startswith("://") or pattern.startswith("/"):
            return pattern in text
        
        # Check for exact domain boundaries
        # Valid domain boundaries: start of string, protocol (://), slash (/), dot (.)
        
        # Match patterns for domain boundaries
        boundary_prefixes = [
            f"://{pattern}",      # Protocol: "://x.com"
            f"://www.{pattern}",  # Protocol with www: "://www.x.com"
            f".{pattern}",        # Subdomain: ".x.com" (must have preceding char)
            f"/{pattern}",        # Path start: "/x.com"
        ]
        
        for prefix in boundary_prefixes:
            if prefix in text:
                return True
        
        # Also check if pattern is at the very start (rare but possible)
        if text.startswith(pattern) or text.startswith(f"www.{pattern}"):
            return True
        
        return False
    
    def _remove_invalid_patterns(self, patterns: List[str]):
        """
        Remove invalid patterns from both custom_urls and custom_apps.
        
        This is called automatically when a pattern causes errors during
        check_distraction() - self-cleaning behaviour.
        
        Args:
            patterns: List of patterns to remove
        """
        for pattern in patterns:
            removed = False
            if pattern in self.custom_urls:
                self.custom_urls.remove(pattern)
                removed = True
            if pattern in self.custom_apps:
                self.custom_apps.remove(pattern)
                removed = True
            if pattern in self.custom_patterns:
                self.custom_patterns.remove(pattern)
                removed = True
            
            if removed:
                logger.warning(f"Auto-removed invalid pattern '{pattern}' from blocklist")
        
        # Mark that patterns were removed (for external save trigger)
        self._patterns_to_remove.extend(patterns)
    
    def enable_category(self, category_id: str) -> bool:
        """
        Enable a preset category.
        
        Args:
            category_id: ID of the category to enable
            
        Returns:
            True if category was enabled, False if invalid category
        """
        if category_id in PRESET_CATEGORIES:
            self.enabled_categories.add(category_id)
            logger.info(f"Enabled blocklist category: {category_id}")
            return True
        return False
    
    def disable_category(self, category_id: str) -> bool:
        """
        Disable a preset category.
        
        Args:
            category_id: ID of the category to disable
            
        Returns:
            True if category was disabled, False if wasn't enabled
        """
        if category_id in self.enabled_categories:
            self.enabled_categories.discard(category_id)
            logger.info(f"Disabled blocklist category: {category_id}")
            return True
        return False
    
    def enable_quick_site(self, site_id: str) -> bool:
        """
        Enable a quick block site.
        
        Args:
            site_id: ID of the quick site to enable (e.g., "youtube", "instagram")
            
        Returns:
            True if site was enabled, False if invalid site
        """
        if site_id in QUICK_SITES:
            self.enabled_quick_sites.add(site_id)
            logger.info(f"Enabled quick block site: {site_id}")
            return True
        return False
    
    def disable_quick_site(self, site_id: str) -> bool:
        """
        Disable a quick block site.
        
        Args:
            site_id: ID of the quick site to disable
            
        Returns:
            True if site was disabled, False if wasn't enabled
        """
        if site_id in self.enabled_quick_sites:
            self.enabled_quick_sites.discard(site_id)
            logger.info(f"Disabled quick block site: {site_id}")
            return True
        return False
    
    def add_custom_url(self, url: str) -> bool:
        """
        Add a custom URL/domain pattern to block.
        
        Args:
            url: URL or domain pattern to block (e.g., "example.com")
            
        Returns:
            True if URL was added, False if already exists
        """
        url = url.strip().lower()
        if url and url not in self.custom_urls:
            self.custom_urls.append(url)
            logger.info(f"Added custom blocklist URL: {url}")
            return True
        return False
    
    def add_custom_app(self, app_name: str) -> bool:
        """
        Add a custom app name pattern to block.
        
        Args:
            app_name: Application name to block (e.g., "Steam", "Discord")
            
        Returns:
            True if app was added, False if already exists
        """
        app_name = app_name.strip()
        if app_name and app_name not in self.custom_apps:
            self.custom_apps.append(app_name)
            logger.info(f"Added custom blocklist app: {app_name}")
            return True
        return False
    
    def remove_custom_url(self, url: str) -> bool:
        """
        Remove a custom URL pattern.
        
        Args:
            url: URL to remove
            
        Returns:
            True if URL was removed, False if not found
        """
        if url in self.custom_urls:
            self.custom_urls.remove(url)
            logger.info(f"Removed custom blocklist URL: {url}")
            return True
        return False
    
    def remove_custom_app(self, app_name: str) -> bool:
        """
        Remove a custom app name pattern.
        
        Args:
            app_name: App name to remove
            
        Returns:
            True if app was removed, False if not found
        """
        if app_name in self.custom_apps:
            self.custom_apps.remove(app_name)
            logger.info(f"Removed custom blocklist app: {app_name}")
            return True
        return False
    
    def add_custom_pattern(self, pattern: str) -> bool:
        """
        Add a custom blocking pattern (legacy method for backward compatibility).
        Automatically routes to custom_urls or custom_apps based on pattern type.
        
        Args:
            pattern: URL or app name pattern to block
            
        Returns:
            True if pattern was added, False if already exists
        """
        pattern = pattern.strip()
        if not pattern:
            return False
        
        # Route to appropriate field based on pattern type
        if '.' in pattern:
            return self.add_custom_url(pattern)
        else:
            return self.add_custom_app(pattern)
    
    def remove_custom_pattern(self, pattern: str) -> bool:
        """
        Remove a custom blocking pattern (legacy method for backward compatibility).
        Attempts to remove from both custom_urls and custom_apps.
        
        Args:
            pattern: Pattern to remove
            
        Returns:
            True if pattern was removed, False if not found
        """
        removed = False
        if pattern in self.custom_urls:
            self.custom_urls.remove(pattern)
            logger.info(f"Removed custom blocklist URL: {pattern}")
            removed = True
        if pattern in self.custom_apps:
            self.custom_apps.remove(pattern)
            logger.info(f"Removed custom blocklist app: {pattern}")
            removed = True
        # Also check legacy field
        if pattern in self.custom_patterns:
            self.custom_patterns.remove(pattern)
            logger.info(f"Removed legacy custom blocklist pattern: {pattern}")
            removed = True
        return removed
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert blocklist to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of blocklist settings.
        """
        return {
            "enabled_categories": list(self.enabled_categories),
            "enabled_quick_sites": list(self.enabled_quick_sites),
            "enabled_gadgets": list(self.enabled_gadgets),
            "custom_urls": self.custom_urls,
            "custom_apps": self.custom_apps,
            # Don't save legacy custom_patterns - they should be migrated
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Blocklist':
        """
        Create a Blocklist from a dictionary.
        
        Handles backward compatibility with old format that used custom_patterns.
        
        Args:
            data: Dictionary with blocklist settings
            
        Returns:
            New Blocklist instance
        """
        return cls(
            enabled_categories=set(data.get("enabled_categories", [])),
            enabled_quick_sites=set(data.get("enabled_quick_sites", [])),
            enabled_gadgets=set(data.get("enabled_gadgets", [])),
            custom_urls=data.get("custom_urls", []),
            custom_apps=data.get("custom_apps", []),
            # Load legacy custom_patterns for migration (will be migrated in __post_init__)
            custom_patterns=data.get("custom_patterns", []),
        )


class BlocklistManager:
    """
    Manages persistence and loading of blocklist settings.
    """
    
    def __init__(self, settings_path: Path):
        """
        Initialize the blocklist manager.
        
        Args:
            settings_path: Path to the JSON settings file
        """
        self.settings_path = settings_path
        self._blocklist: Optional[Blocklist] = None
    
    def load(self) -> Blocklist:
        """
        Load blocklist from file, or create default if not exists.
        
        Returns:
            Loaded or default Blocklist instance
        """
        if self._blocklist is not None:
            return self._blocklist
        
        if self.settings_path.exists():
            try:
                with open(self.settings_path, "r") as f:
                    data = json.load(f)
                self._blocklist = Blocklist.from_dict(data)
                logger.info(f"Loaded blocklist from {self.settings_path}")
            except (json.JSONDecodeError, KeyError, IOError, OSError) as e:
                logger.warning(f"Invalid blocklist file, using defaults: {e}")
                self._blocklist = Blocklist()
        else:
            self._blocklist = Blocklist()
            logger.info("Created default blocklist")
        
        return self._blocklist
    
    def save(self, blocklist: Optional[Blocklist] = None) -> bool:
        """
        Save blocklist to file atomically.
        
        Uses atomic write (write to temp file, then rename) to prevent
        data corruption if the app crashes during save.
        
        Args:
            blocklist: Blocklist to save (uses cached if None)
            
        Returns:
            True if saved successfully, False otherwise
        """
        import tempfile
        import os
        
        if blocklist is not None:
            self._blocklist = blocklist
        
        if self._blocklist is None:
            logger.warning("No blocklist to save")
            return False
        
        try:
            # Ensure parent directory exists
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to a temp file in the same directory first (for atomic rename)
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.tmp',
                prefix='blocklist_',
                dir=self.settings_path.parent
            )
            
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(self._blocklist.to_dict(), f, indent=2)
                
                # Atomic rename (on POSIX systems)
                # On Windows, this may fail if target exists, so we handle that
                try:
                    os.replace(temp_path, self.settings_path)
                except OSError:
                    # Fallback for systems where replace doesn't work
                    if self.settings_path.exists():
                        self.settings_path.unlink()
                    os.rename(temp_path, self.settings_path)
                
                logger.info(f"Saved blocklist to {self.settings_path}")
                return True
                
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise
            
        except Exception as e:
            logger.error(f"Failed to save blocklist: {e}")
            return False
    
    def get_blocklist(self) -> Blocklist:
        """
        Get the current blocklist, loading if necessary.
        
        Returns:
            Current Blocklist instance
        """
        if self._blocklist is None:
            return self.load()
        return self._blocklist
    
    @staticmethod
    def get_preset_categories() -> Dict[str, Dict[str, Any]]:
        """
        Get information about all preset categories.
        
        Returns:
            Dictionary of category info for UI display
        """
        return {
            cat_id: {
                "name": cat_data["name"],
                "description": cat_data["description"],
                "pattern_count": len(cat_data["patterns"]),
                "default_enabled": cat_data.get("default_enabled", False),
            }
            for cat_id, cat_data in PRESET_CATEGORIES.items()
        }
