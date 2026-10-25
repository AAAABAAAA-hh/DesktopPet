extends Node2D
## Minimal Deskling Godot 4 renderer.
##
## Python owns the tray/console and sends JSON state to 127.0.0.1:<port> over
## UDP.  This scene reads skeleton.json, builds a Skeleton2D Bone2D chain and
## a textured Polygon2D body from the exported outline, then applies breathing
## and a damped drag swing.  No external/network service is used.

const DESIGN := Vector2(360.0, 540.0)
const TAU := 6.283185307179586

var character_dir := ""
var state_path := ""
var udp_port := 0
var udp := PacketPeerUDP.new()
var skeleton: Dictionary = {}
var bones: Dictionary = {}
var bone_abs: Dictionary = {}
var skeleton_root: Skeleton2D
var body_node: CanvasItem
var body_mesh: MeshInstance2D
var body_polygon: Polygon2D
var body_sprite: Sprite2D
var head_sprite: Sprite2D
var head_texture: Texture2D
var current_pose := ""
var control_state: Dictionary = {}
var elapsed := 0.0
var drag_tilt := 0.0
var display_scale := 0.8
var last_state_poll := 0.0
var hop_elapsed := 0.0
var hop_total := 1.66
var hop_y := 0.0
var hop_scale := Vector2.ONE
var draw_offset := Vector2.ZERO

func _ready() -> void:
	_parse_args()
	_configure_window()
	if character_dir != "":
		_load_character()
	if udp_port > 0:
		var err := udp.bind(udp_port, "127.0.0.1")
		if err != OK:
			push_warning("UDP bind failed, using state-file fallback")
	if state_path != "":
		_read_state_file()
	set_process(true)

func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		var arg := str(args[index])
		if arg == "--character" and index + 1 < args.size():
			index += 1
			character_dir = str(args[index])
		elif arg == "--state" and index + 1 < args.size():
			index += 1
			state_path = str(args[index])
		elif arg == "--port" and index + 1 < args.size():
			index += 1
			udp_port = int(args[index])
		index += 1

func _configure_window() -> void:
	get_window().transparent = true
	get_viewport().transparent_bg = true
	RenderingServer.set_default_clear_color(Color(0, 0, 0, 0))
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_BORDERLESS, true)
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_ALWAYS_ON_TOP, true)
	# Let mouse input fall through to the PyQt controller window underneath.
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_MOUSE_PASSTHROUGH, true)

func _load_character() -> void:
	_load_skeleton()
	_build_bone_tree()
	_build_body()
	_build_head()

func _load_skeleton() -> void:
	var file := FileAccess.open(character_dir.path_join("skeleton.json"), FileAccess.READ)
	if file == null:
		push_warning("skeleton.json missing for " + character_dir)
		return
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		skeleton = parsed

func _load_texture(path: String) -> Texture2D:
	if not FileAccess.file_exists(path):
		return null
	var image := Image.new()
	if image.load(path) != OK:
		return null
	return ImageTexture.create_from_image(image)

func _build_bone_tree() -> void:
	skeleton_root = Skeleton2D.new()
	skeleton_root.name = "DesklingSkeleton"
	add_child(skeleton_root)
	var nodes: Array = skeleton.get("nodes", [])
	for entry in nodes:
		if not (entry is Dictionary):
			continue
		var node_name := str(entry.get("name", ""))
		if node_name == "":
			continue
		var bone := Bone2D.new()
		bone.name = node_name
		var local: Array = entry.get("local_position", entry.get("position", [0.0, 0.0]))
		bone.position = Vector2(float(local[0]), float(local[1])) * DESIGN
		bone.rotation = deg_to_rad(float(entry.get("rotation", 0.0)))
		bones[node_name] = bone
		var absolute: Array = entry.get("position", local)
		bone_abs[node_name] = Vector2(float(absolute[0]), float(absolute[1])) * DESIGN
	for entry in nodes:
		if not (entry is Dictionary):
			continue
		var node_name := str(entry.get("name", ""))
		if not bones.has(node_name):
			continue
		var parent: Variant = entry.get("parent", null)
		if parent != null and bones.has(str(parent)):
			bones[str(parent)].add_child(bones[node_name])
		else:
			skeleton_root.add_child(bones[node_name])

func _build_body() -> void:
	var holder: Node = bones.get("Torso", self)
	var texture := _load_texture(character_dir.path_join("body.png"))
	var mesh_info: Dictionary = skeleton.get("mesh", {})
	var raw_vertices: Array = mesh_info.get("vertices", [])
	var raw_triangles: Array = mesh_info.get("triangles", [])
	if texture != null and raw_vertices.size() >= 3 and raw_triangles.size() >= 3:
		# True Delaunay-triangulated 2D skin mesh (hundreds of triangles).
		var points := PackedVector2Array()
		var uvs := PackedVector2Array()
		for vertex in raw_vertices:
			var pos: Array = vertex.get("position", [0.0, 0.0])
			var p := Vector2(float(pos[0]), float(pos[1])) * DESIGN
			points.append(p)
			uvs.append(p / Vector2(texture.get_width(), texture.get_height()))
		var indices := PackedInt32Array()
		for tri in raw_triangles:
			if tri.size() >= 3:
				indices.append(int(tri[0]))
				indices.append(int(tri[1]))
				indices.append(int(tri[2]))
		var arrays := []
		arrays.resize(Mesh.ARRAY_MAX)
		arrays[Mesh.ARRAY_VERTEX] = points
		arrays[Mesh.ARRAY_TEX_UV] = uvs
		arrays[Mesh.ARRAY_INDEX] = indices
		var array_mesh := ArrayMesh.new()
		array_mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
		body_mesh = MeshInstance2D.new()
		body_mesh.name = "BodySkinMesh"
		body_mesh.mesh = array_mesh
		body_mesh.texture = texture
		body_mesh.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
		body_mesh.position = -bone_abs.get("Torso", Vector2.ZERO)
		holder.add_child(body_mesh)
		body_node = body_mesh
		return

	var outline: Array = skeleton.get("outline", [])
	if outline.size() >= 3 and texture != null:
		body_polygon = Polygon2D.new()
		body_polygon.name = "BodyOutlineMesh"
		body_polygon.texture = texture
		body_polygon.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
		var points := PackedVector2Array()
		var uvs := PackedVector2Array()
		for point in outline:
			var p := Vector2(float(point[0]), float(point[1])) * DESIGN
			points.append(p)
			uvs.append(p / Vector2(texture.get_width(), texture.get_height()))
		body_polygon.polygon = points
		body_polygon.uv = uvs
		body_polygon.position = -bone_abs.get("Torso", Vector2.ZERO)
		holder.add_child(body_polygon)
		body_node = body_polygon
	else:
		body_sprite = Sprite2D.new()
		body_sprite.name = "Body"
		body_sprite.centered = false
		body_sprite.texture = texture
		if texture != null:
			body_sprite.scale = DESIGN / Vector2(texture.get_width(), texture.get_height())
		body_sprite.position = -bone_abs.get("Torso", Vector2.ZERO)
		holder.add_child(body_sprite)
		body_node = body_sprite

func _build_head() -> void:
	head_texture = _load_texture(character_dir.path_join("head.png"))
	var holder: Node = bones.get("Neck", self)
	head_sprite = Sprite2D.new()
	head_sprite.name = "Head"
	head_sprite.centered = false
	head_sprite.texture = head_texture
	if head_texture != null:
		head_sprite.scale = DESIGN / Vector2(head_texture.get_width(), head_texture.get_height())
	head_sprite.position = -bone_abs.get("Neck", Vector2.ZERO)
	holder.add_child(head_sprite)

func _process(delta: float) -> void:
	elapsed += delta
	var received := false
	while udp.get_available_packet_count() > 0:
		var packet := udp.get_packet()
		_apply_state_text(packet.get_string_from_utf8())
		received = true
	last_state_poll += delta
	if not received and last_state_poll >= 0.10:
		last_state_poll = 0.0
		_read_state_file()
	_apply_motion(delta)

func _read_state_file() -> void:
	if state_path == "":
		return
	var file := FileAccess.open(state_path, FileAccess.READ)
	if file == null:
		return
	_apply_state_text(file.get_as_text())

func _apply_state_text(text: String) -> void:
	var parsed: Variant = JSON.parse_string(text)
	if not (parsed is Dictionary):
		return
	var data: Dictionary = parsed
	control_state = data
	if bool(data.get("quit", false)):
		get_tree().quit()
		return
	var width := int(data.get("width", DESIGN.x * display_scale))
	var height := int(data.get("height", DESIGN.y * display_scale))
	display_scale = clampf(float(data.get("scale", 0.8)), 0.05, 4.0)
	draw_offset = Vector2(
		float(data.get("offset_x", 0)),
		float(data.get("offset_y", 0))
	)
	self.scale = Vector2(display_scale, display_scale)
	get_window().size = Vector2i(maxi(16, width), maxi(16, height))
	DisplayServer.window_set_position(Vector2i(int(data.get("x", 0)), int(data.get("y", 0))))
	var pose := str(data.get("pose", "idle"))
	if pose != "" and pose != current_pose:
		_switch_pose(pose)

func _switch_pose(pose: String) -> void:
	current_pose = pose
	var path := character_dir.path_join(pose + ".png")
	if not FileAccess.file_exists(path):
		path = character_dir.path_join("body.png")
	var texture := _load_texture(path)
	if texture == null:
		return
	if body_mesh != null:
		body_mesh.texture = texture
	elif body_polygon != null:
		body_polygon.texture = texture
	elif body_sprite != null:
		body_sprite.texture = texture
		body_sprite.scale = DESIGN / Vector2(texture.get_width(), texture.get_height())

func _apply_motion(delta: float) -> void:
	var mode := str(control_state.get("state", "idle"))
	var vx := float(control_state.get("vx", 0.0))
	var target_tilt := 0.0
	if mode == "drag":
		target_tilt = clampf(-vx * 0.012, -10.0, 10.0)
	drag_tilt = lerpf(drag_tilt, target_tilt, 1.0 - exp(-delta * 8.0))

	var torso := bones.get("Torso") as Bone2D
	var neck := bones.get("Neck") as Bone2D
	var hair := bones.get("Hair") as Bone2D
	var skirt := bones.get("Skirt") as Bone2D
	var breath := sin(elapsed * TAU * 1.3) * 0.006

	if mode == "walk":
		hop_elapsed = fmod(hop_elapsed + delta, hop_total)
		if hop_elapsed < 0.12:
			var crouch := hop_elapsed / 0.12
			hop_scale = Vector2(1.0 + 0.02 * crouch, 1.0 - 0.04 * crouch)
			hop_y = 0.0
		elif hop_elapsed < 0.54:
			var air := (hop_elapsed - 0.12) / 0.42
			hop_y = -12.0 * sin(PI * air)
			hop_scale = Vector2(1.0 - 0.01 * sin(PI * air), 1.0 + 0.02 * sin(PI * air))
		elif hop_elapsed < 0.66:
			var land := (hop_elapsed - 0.54) / 0.12
			hop_y = 0.0
			hop_scale = Vector2(1.02 - 0.02 * land, 0.95 + 0.05 * land)
		else:
			# Grounded rest: no bounce, no squash, just breathing.
			hop_y = 0.0
			hop_scale = Vector2.ONE
	else:
		hop_elapsed = 0.0
		hop_y = 0.0
		hop_scale = Vector2.ONE
	self.position = draw_offset + Vector2(0.0, hop_y)

	if torso != null:
		var walk_sway := sin(elapsed * TAU * 1.3) * 1.5 if mode == "walk" else 0.0
		torso.rotation_degrees = drag_tilt + walk_sway
		torso.scale = Vector2(
			(1.0 - breath * 0.3) * hop_scale.x,
			(1.0 + breath) * hop_scale.y
		)
	if neck != null:
		neck.rotation_degrees = -drag_tilt * 0.3 + sin(elapsed * 1.3 + 0.6) * 0.5
	if hair != null:
		# Braids trail the body and swing a little more than the head.
		hair.rotation_degrees = -drag_tilt * 0.65 + sin(elapsed * 2.1 + 0.4) * 2.2
	if skirt != null:
		skirt.rotation_degrees = -drag_tilt * 0.20 + sin(elapsed * 1.7 + 1.1) * 1.2
