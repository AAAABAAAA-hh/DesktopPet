"""Pure-Python 2D skeleton / mesh extraction for imported characters.

The exported hierarchy is engine-neutral::

    Root -> Torso -> Neck -> Head
                  \\-> Skirt      \\-> Hair

Both an outer silhouette polygon and a Delaunay-triangulated skin mesh are
emitted (with a coarse grid fallback when scipy is unavailable).  The
JSON shape is documented for Godot 4 consumers: node transforms are normalised
to the 360×540 design canvas (top-left origin), and every mesh vertex carries a
single-bone weight so it can be imported into ``Bone2D`` / ``Polygon2D`` or a
custom 2D skinning pipeline without guessing axis conventions.
"""

from __future__ import annotations

from typing import Callable

BONE_ORDER = ("Root", "Torso", "Neck", "Head", "Hair", "Skirt")


def _normalise_bbox(
    bbox: tuple[int, int, int, int],
    width: float,
    height: float,
) -> tuple[float, float, float, float]:
    left, top, w, h = bbox
    return (
        max(0.0, min(1.0, left / width)),
        max(0.0, min(1.0, top / height)),
        max(0.0, min(1.0, w / width)),
        max(0.0, min(1.0, h / height)),
    )


def _outer_outline(
    bbox: tuple[int, int, int, int],
    width: int,
    height: int,
    alpha_at: Callable[[int, int], int],
    *,
    row_samples: int = 48,
    threshold: int = 24,
) -> list[list[float]]:
    """Approximate the silhouette with left/right row spans.

    A row-span contour is stable for the upright paper-doll silhouettes this
    app targets and avoids a full marching-squares dependency.  The polygon is
    returned in clockwise reading order (right side top→bottom, left side
    bottom→top) without a duplicated closing point.
    """

    left, top, w, h = bbox
    if w <= 0 or h <= 0:
        return []
    step_y = max(1, h // max(1, row_samples))
    right_side: list[list[float]] = []
    left_side: list[list[float]] = []
    for y in range(top, top + h, step_y):
        first: int | None = None
        last: int | None = None
        for x in range(left, left + w, 2):
            if alpha_at(x, y) > threshold:
                if first is None:
                    first = x
                last = x
        if first is None or last is None:
            continue
        right_side.append([last / width, y / height])
        left_side.append([first / width, y / height])
    return right_side + list(reversed(left_side))


def _vertex(bone: str, x: float, y: float) -> dict:
    return {
        "position": [round(x, 6), round(y, 6)],
        "weights": {bone: 1.0},
    }


def _bone_at(
    y_norm: float,
    neck_y: float,
    *,
    x_norm: float | None = None,
    head_cx: float | None = None,
    head_top: float | None = None,
    head_h: float | None = None,
    body_top: float | None = None,
    body_h: float | None = None,
) -> str:
    # Secondary skirt bone: the lower third of the body swings with the hips.
    if (
        body_top is not None
        and body_h is not None
        and y_norm > body_top + body_h * 0.66
        and y_norm > neck_y + 0.08
    ):
        return "Skirt"
    # Secondary hair/braid bone: lower head vertices away from the face.
    if (
        x_norm is not None
        and head_cx is not None
        and head_top is not None
        and head_h is not None
        and y_norm > head_top + head_h * 0.52
        and y_norm < neck_y + 0.055
        and abs(x_norm - head_cx) > 0.075
    ):
        return "Hair"
    if y_norm < neck_y - 0.012:
        return "Head"
    if y_norm > neck_y + 0.035:
        return "Torso"
    return "Neck"


def _build_delaunay_mesh(
    bbox: tuple[int, int, int, int],
    width: int,
    height: int,
    alpha_at: Callable[[int, int], int],
    neck_y: float,
    *,
    head_cx: float | None = None,
    head_top: float | None = None,
    head_h: float | None = None,
    body_top: float | None = None,
    body_h: float | None = None,
    columns: int = 20,
    rows: int = 28,
    threshold: int = 24,
) -> tuple[list[dict], list[list[int]]]:
    """Delaunay-triangulate the alpha silhouette into a dense skin mesh.

    A 20×28 interior sampling plus the silhouette points yields hundreds of
    small triangles on a normal 720×1080 export.  Triangles whose centroid
    falls outside the alpha mask are discarded, so concavities (armpits,
    skirt gaps) do not get bridged by a giant background triangle.
    """

    left, top, w, h = bbox
    if w <= 0 or h <= 0:
        return [], []
    try:
        from scipy.spatial import Delaunay
    except Exception:
        return _build_mesh(bbox, width, height, alpha_at, neck_y)

    points: list[tuple[float, float]] = []
    seen: set[tuple[int, int]] = set()

    def add_point(px: float, py: float) -> None:
        ix = max(0, min(width - 1, int(round(px))))
        iy = max(0, min(height - 1, int(round(py))))
        key = (ix, iy)
        if key in seen:
            return
        if alpha_at(ix, iy) <= threshold:
            return
        seen.add(key)
        points.append((float(ix), float(iy)))

    # Interior samples.
    for row in range(rows + 1):
        py = top + (h * row / max(1, rows))
        for col in range(columns + 1):
            px = left + (w * col / max(1, columns))
            add_point(px, py)

    # Silhouette samples, especially useful for the outer 1–2 px.
    outline = _outer_outline(bbox, width, height, alpha_at, row_samples=rows)
    for nx, ny in outline:
        add_point(nx * width, ny * height)

    if len(points) < 3:
        return [], []
    try:
        triangulation = Delaunay(points)
    except Exception:
        return _build_mesh(bbox, width, height, alpha_at, neck_y)

    vertices: list[dict] = []
    triangles: list[list[int]] = []
    index_by_point: dict[tuple[float, float], int] = {}
    for simplex in triangulation.simplices:
        clipped = []
        cx = cy = 0.0
        for point_index in simplex:
            px, py = points[int(point_index)]
            cx += px
            cy += py
        cx /= 3.0
        cy /= 3.0
        if alpha_at(int(cx), int(cy)) <= threshold:
            continue
        for point_index in simplex:
            point = points[int(point_index)]
            index = index_by_point.get(point)
            if index is None:
                x_norm = max(0.0, min(1.0, point[0] / width))
                y_norm = max(0.0, min(1.0, point[1] / height))
                index = len(vertices)
                index_by_point[point] = index
                bone = _bone_at(
                    y_norm,
                    neck_y,
                    x_norm=x_norm,
                    head_cx=head_cx,
                    head_top=head_top,
                    head_h=head_h,
                    body_top=body_top,
                    body_h=body_h,
                )
                vertices.append(_vertex(bone, x_norm, y_norm))
            clipped.append(index)
        if len(clipped) == 3:
            triangles.append(clipped)
    return vertices, triangles


def _build_mesh(
    bbox: tuple[int, int, int, int],
    width: int,
    height: int,
    alpha_at: Callable[[int, int], int],
    neck_y: float,
    *,
    columns: int = 8,
    rows: int = 12,
    threshold: int = 24,
) -> tuple[list[dict], list[list[int]]]:
    """Coarse quad mesh clipped by the alpha mask."""

    left, top, w, h = bbox
    if w <= 0 or h <= 0:
        return [], []
    step_x = max(1, w // columns)
    step_y = max(1, h // rows)
    lookup: dict[tuple[float, float], int] = {}
    vertices: list[dict] = []
    triangles: list[list[int]] = []

    def add_vertex(x: int, y: int) -> int:
        key = (round(x * 1000.0 / width), round(y * 1000.0 / height))
        index = lookup.get(key)
        if index is not None:
            return index
        x_norm = max(0.0, min(1.0, x / width))
        y_norm = max(0.0, min(1.0, y / height))
        bone = _bone_at(y_norm, neck_y)
        index = len(vertices)
        lookup[key] = index
        vertices.append(_vertex(bone, x_norm, y_norm))
        return index

    for row in range(rows):
        y0 = top + row * step_y
        y1 = min(top + h, y0 + step_y)
        if y1 <= y0:
            continue
        for col in range(columns):
            x0 = left + col * step_x
            x1 = min(left + w, x0 + step_x)
            if x1 <= x0:
                continue
            cx = (x0 + x1) // 2
            cy = (y0 + y1) // 2
            samples = [
                alpha_at(x0, y0),
                alpha_at(x1 - 1, y0),
                alpha_at(x0, y1 - 1),
                alpha_at(x1 - 1, y1 - 1),
                alpha_at(cx, cy),
            ]
            if sum(1 for value in samples if value > threshold) < 3:
                continue
            a = add_vertex(x0, y0)
            b = add_vertex(x1, y0)
            c = add_vertex(x1, y1)
            d = add_vertex(x0, y1)
            triangles.append([a, b, c])
            triangles.append([a, c, d])
    return vertices, triangles


def build_skeleton(
    *,
    canvas: tuple[int, int],
    head_bbox: tuple[int, int, int, int],
    body_bbox: tuple[int, int, int, int],
    neck: tuple[float, float],
    alpha_at: Callable[[int, int], int],
) -> dict:
    """Build the standardized skeleton + mesh document.

    ``neck`` is normalised ``(x, y)`` on the design canvas; ``alpha_at`` is a
    callable returning the source image alpha at export-pixel coordinates.
    """

    width, height = canvas
    head_l, head_t, head_w, head_h = head_bbox
    body_l, body_t, body_w, body_h = body_bbox
    fig_left = max(0, min(head_l, body_l))
    fig_top = max(0, min(head_t, body_t))
    fig_right = min(width, max(head_l + head_w, body_l + body_w))
    fig_bottom = min(height, max(head_t + head_h, body_t + body_h))
    figure = (fig_left, fig_top, max(1, fig_right - fig_left), max(1, fig_bottom - fig_top))

    neck_x, neck_y = float(neck[0]), float(neck[1])
    head_cx = (head_l + head_w / 2.0) / width
    head_center_y = (head_t + head_h * 0.45) / height
    body_cx = (body_l + body_w / 2.0) / width
    torso_y = (body_t + body_h * 0.38) / height
    root_y = min(0.995, (fig_bottom - max(1, fig_bottom - fig_top) * 0.015) / height)

    head_top_norm = head_t / height
    head_h_norm = head_h / height
    body_top_norm = body_t / height
    body_h_norm = body_h / height
    positions = {
        "Root": (body_cx, root_y),
        "Torso": (body_cx, torso_y),
        "Neck": (neck_x, neck_y),
        "Head": (head_cx, head_center_y),
        "Hair": (head_cx, min(0.98, neck_y + 0.035)),
        "Skirt": (body_cx, min(0.98, body_top_norm + body_h_norm * 0.72)),
    }
    parents = {
        "Root": None,
        "Torso": "Root",
        "Neck": "Torso",
        "Head": "Neck",
        "Hair": "Head",
        "Skirt": "Torso",
    }
    children: dict[str, list[str]] = {name: [] for name in BONE_ORDER}
    for name in BONE_ORDER:
        parent = parents[name]
        if parent is not None:
            children[parent].append(name)
    nodes: list[dict] = []
    for name in BONE_ORDER:
        x, y = positions[name]
        parent = parents[name]
        if parent is None:
            local = [round(x, 6), round(y, 6)]
        else:
            px, py = positions[parent]
            local = [round(x - px, 6), round(y - py, 6)]
        nodes.append(
            {
                "name": name,
                "parent": parent,
                "children": children[name],
                "position": [round(x, 6), round(y, 6)],
                "local_position": local,
                "rotation": 0.0,
                "scale": [1.0, 1.0],
            }
        )

    outline = _outer_outline(figure, width, height, alpha_at)
    if not outline:
        outline = [
            [figure[0] / width, figure[1] / height],
            [(figure[0] + figure[2]) / width, figure[1] / height],
            [(figure[0] + figure[2]) / width, (figure[1] + figure[3]) / height],
            [figure[0] / width, (figure[1] + figure[3]) / height],
        ]
    vertices, triangles = _build_delaunay_mesh(
        figure,
        width,
        height,
        alpha_at,
        neck_y,
        head_cx=head_cx,
        head_top=head_top_norm,
        head_h=head_h_norm,
        body_top=body_top_norm,
        body_h=body_h_norm,
    )
    mesh_method = "delaunay" if len(triangles) > 4 else "grid-fallback"
    if len(triangles) <= 4:
        vertices, triangles = _build_mesh(
            figure, width, height, alpha_at, neck_y
        )
        mesh_method = "grid-fallback"
    if not vertices:
        vertices = [
            _vertex("Head", figure[0] / width, figure[1] / height),
            _vertex("Head", (figure[0] + figure[2]) / width, figure[1] / height),
            _vertex("Torso", (figure[0] + figure[2]) / width, (figure[1] + figure[3]) / height),
            _vertex("Torso", figure[0] / width, (figure[1] + figure[3]) / height),
        ]
        triangles = [[0, 1, 2], [0, 2, 3]]
    return {
        "schema": "deskling.2d-skeleton/1",
        "coordinate_space": "normalized-top-left",
        "canvas": [360, 540],
        "export_canvas": [width, height],
        "figure_bbox": list(_normalise_bbox(figure, width, height)),
        "head_bbox": list(_normalise_bbox(head_bbox, width, height)),
        "body_bbox": list(_normalise_bbox(body_bbox, width, height)),
        "root_bone": "Root",
        "root": "Root",
        "bone_order": list(BONE_ORDER),
        "nodes": nodes,
        "bones": nodes,
        "outline": outline,
        "mesh": {
            "method": mesh_method,
            "vertices": vertices,
            "triangles": triangles,
            "indices": triangles,
            "uv": [vertex["position"] for vertex in vertices],
        },
        "godot": {
            "format": "Bone2D+Polygon2D",
            "root": "Root",
            "bone_paths": [
                "Root",
                "Root/Torso",
                "Root/Torso/Neck",
                "Root/Torso/Neck/Head",
                "Root/Torso/Neck/Head/Hair",
                "Root/Torso/Skirt",
            ],
            "pixel_canvas": [width, height],
        },
    }
