"""
Bundled API Keys Template.

This file is used as a TEMPLATE by the build script.
The build script replaces the placeholder values with actual API keys
and saves it as bundled_keys.py before bundling.

DO NOT COMMIT ACTUAL KEYS TO THIS FILE.

At runtime, config.py imports this module to get the embedded keys.
"""

# AI API Keys - replaced at build time
OPENAI_API_KEY = "%%OPENAI_API_KEY%%"
GEMINI_API_KEY = "%%GEMINI_API_KEY%%"

# Supabase (auth, sync, session upload) - replaced at build time
SUPABASE_URL = "%%SUPABASE_URL%%"
SUPABASE_ANON_KEY = "%%SUPABASE_ANON_KEY%%"

# Stripe Payment Keys - replaced at build time
STRIPE_SECRET_KEY = "%%STRIPE_SECRET_KEY%%"
STRIPE_PUBLISHABLE_KEY = "%%STRIPE_PUBLISHABLE_KEY%%"
STRIPE_PRICE_ID = "%%STRIPE_PRICE_ID%%"


def get_key(key_name: str) -> str:
    """
    Get a bundled API key by name.
    
    Args:
        key_name: Name of the key (e.g., 'STRIPE_SECRET_KEY')
        
    Returns:
        The key value, or empty string if not found or is a placeholder.
    """
    value = globals().get(key_name, "")
    # Return empty string if it's still a placeholder
    if value and value.startswith("%%") and value.endswith("%%"):
        return ""
    return value
