# Deskling Godot 4 runtime

This folder is generated/maintained by `petapp.godot_bridge`.  It contains a
minimal Godot 4 project that renders one character in a **borderless,
transparent, always-on-top** window.

- `project.godot` — borderless/transparent/per-pixel-alpha settings.
- `pet_renderer.tscn` — single Node2D scene.
- `pet_renderer.gd` — loads `skeleton.json`, builds
  `Skeleton2D -> Bone2D (Root/Torso/Neck/Head/Hair/Skirt)`, creates a textured
  `MeshInstance2D` from the Delaunay triangles/UVs (or a `Polygon2D` /
  `Sprite2D` fallback), and attaches `head.png` to the neck bone.
- Body poses (`sit.png`, `walk_left.png`, `walk_right.png`, `drag.png`) are
  swapped automatically when Python publishes them.

## Control protocol

Python starts:

```text
godot --path godot_runtime -- --character <folder> --state <json> --port <udp>
```

and sends compact JSON state datagrams to `127.0.0.1:<udp>`:

```json
{"x":1200,"y":600,"width":340,"height":470,"scale":0.4,
 "offset_x":26,"offset_y":103,"state":"drag","pose":"drag",
 "vx":-420.0,"quit":false}
```

`offset_x/offset_y` place the 360×540 design canvas inside the transparent Qt
window; `scale` is the same display scale used by the PyQt fallback.  Godot is
auto-launched when `engine/godot.exe` (or `GODOT_BIN`) exists, and the PyQt pet
keeps handling input through the click-through Godot window.  If Godot exits,
the QPainter renderer resumes automatically.

The state file is refreshed as a fallback when UDP is unavailable.  The Python
side is `petapp/godot_bridge.py`; if no Godot 4 executable is found,
`GodotBridge.available` is `False` and the app keeps using its PyQt renderer.

No network access beyond the loopback UDP socket is used.
