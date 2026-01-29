"""
License Manager for BrainDock.

Handles license validation, storage, and verification.
Supports Stripe payments as the activation method.
"""

import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class LicenseManager:
    """
    Manages BrainDock license state.
    
    Handles checking license validity, saving license data,
    and verifying Stripe payments.
    """
    
    # License types
    LICENSE_TYPE_STRIPE = "stripe_payment"
    LICENSE_TYPE_PROMO = "promo_code"
    
    def __init__(self, license_file: Path):
        """
        Initialize the license manager.
        
        Args:
            license_file: Path to the license data JSON file.
        """
        self.license_file = license_file
        self.data = self._load_data()
        
    def _load_data(self) -> Dict[str, Any]:
        """
        Load license data from JSON file.
        
        Returns:
            Dict containing license data.
        """
        if self.license_file.exists():
            try:
                with open(self.license_file, 'r') as f:
                    data = json.load(f)
                    # Verify checksum if present
                    if not self._verify_checksum(data):
                        logger.warning("License file checksum mismatch - possible tampering")
                        return self._default_data()
                    logger.debug(f"Loaded license data: licensed={data.get('licensed', False)}")
                    return data
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load license data: {e}")
        
        return self._default_data()
    
    def _default_data(self) -> Dict[str, Any]:
        """Return default license data for unlicensed state."""
        return {
            "licensed": False,
            "license_type": None,
            "stripe_session_id": None,
            "stripe_payment_intent": None,
            "activated_at": None,
            "email": None,
            "checksum": None
        }
    
    def _calculate_checksum(self, data: Dict[str, Any]) -> str:
        """
        Calculate checksum for license data integrity.
        
        Args:
            data: License data dictionary.
            
        Returns:
            SHA256 checksum string.
        """
        # Create a copy without the checksum field
        data_copy = {k: v for k, v in data.items() if k != "checksum"}
        # Sort keys for consistent hashing
        data_str = json.dumps(data_copy, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()[:16]
    
    def _verify_checksum(self, data: Dict[str, Any]) -> bool:
        """
        Verify the checksum of license data.
        
        Args:
            data: License data dictionary.
            
        Returns:
            True if checksum is valid or not present, False if mismatch.
        """
        stored_checksum = data.get("checksum")
        if not stored_checksum:
            return True  # No checksum = old format, accept it
        
        calculated = self._calculate_checksum(data)
        return stored_checksum == calculated
    
    def _save_data(self) -> None:
        """Save license data to JSON file with checksum."""
        try:
            # Ensure parent directory exists
            self.license_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Add checksum before saving
            self.data["checksum"] = self._calculate_checksum(self.data)
            
            with open(self.license_file, 'w') as f:
                json.dump(self.data, f, indent=2)
            logger.debug("Saved license data")
        except IOError as e:
            logger.error(f"Failed to save license data: {e}")
    
    def is_licensed(self) -> bool:
        """
        Check if the app is licensed.
        
        Returns:
            True if licensed, False otherwise.
        """
        return self.data.get("licensed", False)
    
    def get_license_type(self) -> Optional[str]:
        """
        Get the type of license activation.
        
        Returns:
            License type string or None if not licensed.
        """
        return self.data.get("license_type")
    
    def get_license_info(self) -> Dict[str, Any]:
        """
        Get license information for display.
        
        Returns:
            Dict with license details.
        """
        return {
            "licensed": self.data.get("licensed", False),
            "type": self.data.get("license_type"),
            "activated_at": self.data.get("activated_at"),
            "email": self.data.get("email")
        }
    
    def activate_with_stripe(
        self,
        session_id: str,
        payment_intent: Optional[str] = None,
        email: Optional[str] = None
    ) -> bool:
        """
        Activate license after successful Stripe payment.
        
        Args:
            session_id: Stripe Checkout session ID.
            payment_intent: Optional Stripe payment intent ID.
            email: Optional customer email from Stripe.
            
        Returns:
            True if activation successful.
        """
        self.data = {
            "licensed": True,
            "license_type": self.LICENSE_TYPE_STRIPE,
            "stripe_session_id": session_id,
            "stripe_payment_intent": payment_intent,
            "activated_at": datetime.now().isoformat(),
            "email": email,
            "checksum": None
        }
        self._save_data()
        logger.info(f"License activated via Stripe payment (session: {session_id[:20]}...)")
        return True
    
    def activate_with_promo(
        self,
        session_id: str,
        promo_code: str,
        email: Optional[str] = None
    ) -> bool:
        """
        Activate license after successful promo code redemption via Stripe.
        
        Args:
            session_id: Stripe Checkout session ID.
            promo_code: The promo code that was used.
            email: Optional customer email from Stripe.
            
        Returns:
            True if activation successful.
        """
        self.data = {
            "licensed": True,
            "license_type": self.LICENSE_TYPE_PROMO,
            "stripe_session_id": session_id,
            "stripe_payment_intent": None,
            "promo_code": promo_code,  # Store the promo code used
            "activated_at": datetime.now().isoformat(),
            "email": email,
            "checksum": None
        }
        self._save_data()
        logger.info(f"License activated via promo code")
        return True
    
    def revoke_license(self) -> None:
        """Revoke the current license (reset to unlicensed state)."""
        self.data = self._default_data()
        self._save_data()
        logger.info("License revoked")
    
    def get_activation_date(self) -> Optional[datetime]:
        """
        Get the date when the license was activated.
        
        Returns:
            Datetime of activation or None if not licensed.
        """
        activated_at = self.data.get("activated_at")
        if activated_at:
            try:
                return datetime.fromisoformat(activated_at)
            except ValueError:
                pass
        return None


# Global instance for easy access
_license_manager_instance: Optional[LicenseManager] = None


def get_license_manager() -> LicenseManager:
    """
    Get the global LicenseManager instance.
    
    Returns:
        Singleton LicenseManager instance.
    """
    global _license_manager_instance
    if _license_manager_instance is None:
        # Import config here to avoid circular imports
        import config
        _license_manager_instance = LicenseManager(
            license_file=config.LICENSE_FILE
        )
    return _license_manager_instance


def reset_license_manager() -> None:
    """Reset the global license manager instance (useful for testing)."""
    global _license_manager_instance
    _license_manager_instance = None
