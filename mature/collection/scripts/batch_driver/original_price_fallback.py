"""User-authorized original-price fallback resolver (2026-10-15).
Pure helper: no package_live import, so callers control which package_live is patched."""
import json
import re

PENDING_SOURCES = ('live_signed_page_arrival_pending', 'live_native_page_arrival_pending')
FALLBACK_PRICE_SOURCE = None  # Never an authorization signal; retained name only for old imports.


def attach_fallback(package_live):
    """Use mature package_live's actual per-batch authorization, not a copied past marker."""
    if not package_live.fallback_marker():
        raise RuntimeError('ORIGINAL_PRICE_FALLBACK_AUTHORIZATION_REQUIRED')
    return package_live.live_data
