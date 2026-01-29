"""
Licensing module for BrainDock.

Handles license validation and Stripe payment integration.
"""

from licensing.license_manager import LicenseManager, get_license_manager

__all__ = ["LicenseManager", "get_license_manager"]
