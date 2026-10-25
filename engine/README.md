# Deskling Godot 4 render shell

This folder is an **optional** renderer for characters packed by the normal
Deskling importer.  The PyQt application remains the controller, tray and input
layer.  Godot only paints a transparent borderless window from `skeleton.json`
and the per-frame state file written by Python.

## Requirements

- Godot 4.x (stable).  Put it on `PATH`, set `GODOT_BIN`, or pass `--godot`.
- A character folder containing at least:
  - `body.png`
  - `head.png`
  - `skeleton.json`
  - optional pose files (`sit.png`, `walk_left.png`, `walk_right.png`, ...)

No network service, cloud model or API key is used by this shell.

## Run a preview

From the repository root:

```powershell
python -m engine.bridge --character characters/elaina --width 288 --height 432 --x 100 --y 100
```

The Python bridge launches:

```text
godot --path engine -- --character <folder> --state <temp state json>
```

and updates the state file with window position, size, pose, activity and
horizontal drag velocity.  The Godot scene:

1. loads `skeleton.json`;
2. creates a `Skeleton2D` with the `Root → Torso → Neck → Head` Bone2D chain;
3. attaches `body.png` to the torso bone and `head.png` to the neck bone;
4. applies a 1.3 Hz breathing scale, damped ±10° drag swing and walk sway;
5. switches body textures for `sit` / `walk_left` / `walk_right` / `drag` when
   those files exist.

## Project settings

`project.godot` enables:

- borderless window;
- per-pixel transparency;
- transparent clear colour;
- GL Compatibility renderer (works on machines without Vulkan).

The window is intentionally not a full-screen game: Python controls its
position and size.  If Godot is absent, `GodotBridge.available` is `False` and
the normal PyQt desktop pet continues to run unchanged.

## Python API

```python
from engine.bridge import GodotBridge

bridge = GodotBridge(character.folder)
if bridge.available:
    bridge.start(width=288, height=432, x=1200, y=600)
    bridge.update(pose="walk_left", state="walk", vx=30, x=1190)
    # ...
    bridge.stop()
```

The bridge is deliberately transport-free: one atomic JSON state file, no
sockets, no HTTP, no model inference.
