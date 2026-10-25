"""Compatibility wrapper for the generic character packager.

The real pipeline lives in :mod:`petapp.packager`.  The old name is kept so
existing imports, tests and settings code keep working; new code should import
``petapp.packager`` directly.
"""

from __future__ import annotations

from .packager import create_character, load_photo, package_character

__all__ = ["create_character", "load_photo", "package_character"]
