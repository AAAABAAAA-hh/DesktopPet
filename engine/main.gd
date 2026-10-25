extends Node2D
## Minimal Deskling Godot 4 render shell.
##
## Python (engine/bridge.py) owns the process, window position and interaction
## state.  This scene only loads the character folder, builds the Bone2D chain
## described by skeleton.json, and paints body.png / head.png with gentle
## breathing and a damped drag swing.

const DESIGN := Vector2(360.0, 540.0)
const TAU := 6.283185307179586

var character_dir := ""
var state_path := ""
var skeleton: Dictionary = {}
var bones: Dictionary = {}
var bone_abs: Dictionary = {}
var skeleton_root: Skeleton2D
var body_sprite: Sprite2D
var head_sprite: Sprite2D
var head_texture: Texture2D
var current_pose := ""
var last_state_check := 0.0
var display_scale := 0.8
var drag_tilt := 0.0
var elapsed := 0.0
var control_state: Dictionary = {}

func _ready() -> void:
	_parse_args()
	_configure_window()
	if character_dir != "":
		_load_character()
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
		index += 1

func _configure_window() -> void:
	get_window().transparent = true
	get_viewport().transparent_bg = true
	RenderingServer.set_default_clear_color(Color(0, 0, 0, 0))
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_BORDERLESS, true)
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_ALWAYS_ON_TOP, true)

func _load_character() -> void:
	_load_skeleton()
	var body_texture := _load_texture(character_dir.path_join("body.png"))
	head_texture = _load_texture(character_dir.path_join("head.png"))
	_build_bone_tree()
	_build_sprites(body_texture)
	if state_path != "":
		_read_state()

func _load_skeleton() -> void:
	var path := character_dir.path_join("skeleton.json")
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_warning("skeleton.json missing: " + path)
		return
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		skeleton = parsed

func _load_texture(path: String) -> Texture2D:
	if not FileAccess.file_exists(path):
		return null
	var image := Image.new()
	var err := image.load(path)
	if err != OK:
		push_warning("cannot load texture: " + path)
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
		var name := str(entry.get("name", ""))
		if name == "":
			continue
		var bone := Bone2D.new()
		bone.name = name
		var local: Array = entry.get("local_position", entry.get("position", [0.0, 0.0]))
		bone.position = Vector2(float(local[0]), float(local[1])) * DESIGN
		bone.rotation = deg_to_rad(float(entry.get("rotation", 0.0)))
		bones[name] = bone
		var absolute: Array = entry.get("position", local)
		bone_abs[name] = Vector2(float(absolute[0]), float(absolute[1])) * DESIGN
	for entry in nodes:
		if not (entry is Dictionary):
			continue
		var name := str(entry.get("name", ""))
		if not bones.has(name):
			continue
		var parent := entry.get("parent", null)
		if parent != null and bones.has(str(parent)):
			bones[str(parent)].add_child(bones[name])
		else:
			skeleton_root.add_child(bones[name])

func _build_sprites(body_texture: Texture2D) -> void:
	var body_holder: Node = bones.get("Torso", self)
	var head_holder: Node = bones.get("Neck", self)
	body_sprite = Sprite2D.new()
	body_sprite.name = "Body"
	body_sprite.centered = false
	body_sprite.texture = body_texture
	if body_texture != null:
		body_sprite.scale = DESIGN / Vector2(body_texture.get_width(), body_texture.get_height())
	body_sprite.position = -bone_abs.get("Torso", Vector2.ZERO)
	body_holder.add_child(body_sprite)

	head_sprite = Sprite2D.new()
	head_sprite.name = "Head"
	head_sprite.centered = false
	head_sprite.texture = head_texture
	if head_texture != null:
		head_sprite.scale = DESIGN / Vector2(head_texture.get_width(), head_texture.get_height())
	head_sprite.position = -bone_abs.get("Neck", Vector2.ZERO)
	head_holder.add_child(head_sprite)

func _process(delta: float) -> void:
	elapsed += delta
	last_state_check += delta
	if state_path != "" and last_state_check >= 0.05:
		last_state_check = 0.0
		_read_state()
	_apply_motion(delta)

func _read_state() -> void:
	var file := FileAccess.open(state_path, FileAccess.READ)
	if file == null:
		return
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not (parsed is Dictionary):
		return
	var data: Dictionary = parsed
	control_state = data
	if bool(data.get("quit", false)):
		get_tree().quit()
		return
	var width := int(data.get("width", DESIGN.x * display_scale))
	var height := int(data.get("height", DESIGN.y * display_scale))
	display_scale = clampf(float(width) / DESIGN.x, 0.05, 4.0)
	self.scale = Vector2(display_scale, display_scale)
	get_window().size = Vector2i(maxi(16, width), maxi(16, height))
	DisplayServer.window_set_position(
		Vector2i(int(data.get("x", 0)), int(data.get("y", 0)))
	)
	var pose := str(data.get("pose", "idle"))
	if pose != "" and pose != current_pose:
		_switch_pose(pose)

func _switch_pose(pose: String) -> void:
	current_pose = pose
	if body_sprite == null:
		return
	var path := character_dir.path_join(pose + ".png")
	if not FileAccess.file_exists(path):
		path = character_dir.path_join("body.png")
	var texture := _load_texture(path)
	if texture != null:
		body_sprite.texture = texture
		body_sprite.scale = DESIGN / Vector2(texture.get_width(), texture.get_height())

func _apply_motion(delta: float) -> void:
	var data: Dictionary = control_state
	var mode := str(data.get("state", "idle"))
	var vx := float(data.get("vx", 0.0))
	var target_tilt := 0.0
	if mode == "drag":
		target_tilt = clampf(-vx * 0.012, -10.0, 10.0)
	drag_tilt = lerpf(drag_tilt, target_tilt, 1.0 - exp(-delta * 8.0))

	var torso := bones.get("Torso") as Bone2D
	var neck := bones.get("Neck") as Bone2D
	var breath := sin(elapsed * TAU * 1.3) * 0.006
	if torso != null:
		var walk_sway := 0.0
		if mode == "walk":
			walk_sway = sin(elapsed * TAU * 1.3) * 1.5
		torso.rotation_degrees = drag_tilt + walk_sway
		torso.scale = Vector2(1.0 - breath * 0.3, 1.0 + breath)
	if neck != null:
		neck.rotation_degrees = -drag_tilt * 0.3 + sin(elapsed * 1.3 + 0.6) * 0.5
