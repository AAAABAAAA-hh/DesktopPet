"""Optional Godot 4 render shell for Deskling.

The PyQt application remains the controller/tray; this package contains the
Godot project and a small Python bridge that can launch it and feed window /
state JSON.  It is intentionally optional: without a local Godot 4 binary the
normal PyQt renderer keeps working.
"""

from .bridge import GodotBridge, find_godot

__all__ = ["GodotBridge", "find_godot"]
