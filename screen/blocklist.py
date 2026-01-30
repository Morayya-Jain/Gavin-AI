"""
Blocklist management for screen monitoring.

Provides preset categories and custom URL/app blocking
for distraction detection during focus sessions.
"""

import json
import logging
from pathlib import Path
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
    "twitter": {"name": "twitter.com / x.com", "patterns": ["twitter.com", "x.com"]},
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
    custom_urls: List[str] = field(default_factory=list)
    custom_apps: List[str] = field(default_factory=list)
    # Legacy field for backward compatibility (migrated on load)
    custom_patterns: List[str] = field(default_factory=list)
    # Track patterns that need to be removed (self-cleaning)
    _patterns_to_remove: List[str] = field(default_factory=list, repr=False)
    
    def __post_init__(self):
        """Initialize with default enabled categories if empty."""
        if not self.enabled_categories:
            self.enabled_categories = {
                cat_id for cat_id, cat_data in PRESET_CATEGORIES.items()
                if cat_data.get("default_enabled", False)
            }
        
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
        app_name: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if the current screen content matches any blocklist pattern.
        
        This method is safe and never crashes - invalid patterns are automatically
        removed from the blocklist (self-cleaning behavior).
        
        Args:
            url: Current browser URL (if available)
            window_title: Active window title
            app_name: Active application name
            
        Returns:
            Tuple of (is_distracted, matched_pattern)
        """
        patterns = self.get_all_patterns()
        patterns_to_remove = []
        
        # Combine all text to check (lowercase for case-insensitive matching)
        check_texts = []
        if url:
            try:
                check_texts.append(url.lower())
            except Exception as e:
                logger.warning(f"Error processing URL '{url}': {e}")
        if window_title:
            try:
                check_texts.append(window_title.lower())
            except Exception as e:
                logger.warning(f"Error processing window_title '{window_title}': {e}")
        if app_name:
            try:
                check_texts.append(app_name.lower())
            except Exception as e:
                logger.warning(f"Error processing app_name '{app_name}': {e}")
        
        # Check each pattern against all texts (with error handling)
        for pattern in patterns:
            try:
                pattern_lower = pattern.lower()
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
    
    def _remove_invalid_patterns(self, patterns: List[str]):
        """
        Remove invalid patterns from both custom_urls and custom_apps.
        
        This is called automatically when a pattern causes errors during
        check_distraction() - self-cleaning behavior.
        
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
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Invalid blocklist file, using defaults: {e}")
                self._blocklist = Blocklist()
        else:
            self._blocklist = Blocklist()
            logger.info("Created default blocklist")
        
        return self._blocklist
    
    def save(self, blocklist: Optional[Blocklist] = None) -> bool:
        """
        Save blocklist to file.
        
        Args:
            blocklist: Blocklist to save (uses cached if None)
            
        Returns:
            True if saved successfully, False otherwise
        """
        if blocklist is not None:
            self._blocklist = blocklist
        
        if self._blocklist is None:
            logger.warning("No blocklist to save")
            return False
        
        try:
            # Ensure parent directory exists
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.settings_path, "w") as f:
                json.dump(self._blocklist.to_dict(), f, indent=2)
            
            logger.info(f"Saved blocklist to {self.settings_path}")
            return True
            
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
