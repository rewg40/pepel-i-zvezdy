extends CharacterBody3D
## Зомби: тело 1000 HP, руки/ноги по 3 HP. Отрубленные части падают как
## RigidBody3D и остаются лежать, зомби меняет способ передвижения.

signal limb_cut(zombie, part: String)
signal died(zombie)

const GRAVITY := 24.0
const WALK_SPEED := 1.35
const CRAWL_SPEED := 0.55
const LIMP_SPEED := 0.85
const ATTACK_RANGE := 2.0
const ATTACK_DAMAGE := 8.0
const ATTACK_COOLDOWN := 2.2
const LIMB_PICK_RADIUS := 0.16   # насколько близко к кости должен прийти удар

const BODY_HP := 1000.0
const LIMB_HP := 3.0
const HEAD_HP := 20.0

# логическое имя части -> (суффикс узла в модели, кость, которая её носит)
const PARTS := {
	"body": ["Body", ""],
	"head": ["Head", "Head"],
	"arm_l": ["ArmL", "UpperArm_L"],
	"arm_r": ["ArmR", "UpperArm_R"],
	"leg_l": ["LegL", "Thigh_L"],
	"leg_r": ["LegR", "Thigh_R"],
}

@export var model_scale := 1.65
@export_file("*.glb") var extra_clips := "res://models/zombie_clips.glb"
## Префикс имён клипов из extra_clips ("Mx" -> MxWalk, MxCrawl…). Пусто — родные.
@export var clip_prefix := "Mx"
@export var max_hp := BODY_HP
@export var title := "Зомби"

var model: Node3D
var skeleton: Skeleton3D
var anim: AnimationPlayer
var pieces_root: Node3D
var targets: Array = []          # узлы игроков, за кем идти

var hp := BODY_HP
var dead := false
var part_hp := {}
var alive := {}
var last_part_hit := "body"
var state := "walk"              # walk | limp | crawl | wait

var _attack_cd := 0.0
var _anim_name := ""


func _ready() -> void:
	collision_layer = 4
	collision_mask = 1
	var cap := CapsuleShape3D.new()
	cap.height = 1.8
	cap.radius = 0.35
	var cs := CollisionShape3D.new()
	cs.shape = cap
	cs.name = "BodyShape"
	cs.position.y = 0.9
	add_child(cs)

	model = load("res://models/zombie.glb").instantiate()
	model.name = "ZombieModel"
	model.scale = Vector3.ONE * model_scale
	add_child(model)

	anim = _find(model, "AnimationPlayer")
	skeleton = _find(model, "Skeleton3D")
	_merge_clips(anim, extra_clips)
	pieces_root = _find_node_suffix(model, "_Pieces")
	if pieces_root:
		pieces_root.visible = false      # копии деталей нужны только для физики
	# кровавые заглушки живут внутри мешей частей: скрывая часть, скрываем и их

	hp = max_hp
	part_hp = {
		"body": BODY_HP, "head": HEAD_HP,
		"arm_l": LIMB_HP, "arm_r": LIMB_HP,
		"leg_l": LIMB_HP, "leg_r": LIMB_HP,
	}
	alive = {"body": true, "head": true, "arm_l": true, "arm_r": true,
		"leg_l": true, "leg_r": true}
	_play(_move_anim())
	# идём к ближайшему игроку
	for n in get_tree().get_nodes_in_group("player"):
		targets.append(n)


## Дополнительная библиотека клипов (сборка tools/retarget.py). Если файла нет,
## игра работает как раньше: анимации берутся из самой модели.
func _merge_clips(p: AnimationPlayer, path: String) -> int:
	if p == null or path.is_empty() or not ResourceLoader.exists(path):
		return 0
	var packed := load(path) as PackedScene
	if packed == null:
		return 0
	var holder := packed.instantiate()
	var src: AnimationPlayer = null
	for c in holder.find_children("*", "AnimationPlayer", true, false):
		src = c
		break
	var added := 0
	if src != null:
		if not p.has_animation_library(""):
			p.add_animation_library("", AnimationLibrary.new())
		var dst_lib := p.get_animation_library("")
		for lib_name in src.get_animation_library_list():
			var lib: AnimationLibrary = src.get_animation_library(lib_name)
			if lib == null:
				continue
			for a in lib.get_animation_list():
				var an := String(a)
				if p.has_animation(an):
					continue          # своя анимация важнее внешней
				dst_lib.add_animation(an, lib.get_animation(an))
				added += 1
	holder.queue_free()
	if added > 0:
		print("внешние клипы: +", added, " из ", path)
	return added

func _find(root: Node, cls: String) -> Node:
	for c in root.find_children("*", cls, true, false):
		return c
	return null


func _find_node_suffix(root: Node, suffix: String) -> Node3D:
	for c in root.find_children("*", "Node3D", true, false):
		if String(c.name).ends_with(suffix):
			return c
	return null


func _part_node(part: String) -> Node3D:
	var suffix: String = PARTS[part][0]
	for c in model.find_children("*", "MeshInstance3D", true, false):
		var nm := String(c.name)
		if nm.ends_with("_" + suffix) and not nm.contains("Cap") and not nm.contains("Piece"):
			return c
	return null


func _physics_process(delta: float) -> void:
	if dead:
		return
	_attack_cd = max(0.0, _attack_cd - delta)
	var target = _nearest_target()
	if target == null:
		_play("Idle")
		return
	var to_target: Vector3 = target.global_position - global_position
	to_target.y = 0.0
	var dist := to_target.length()
	var speed := WALK_SPEED
	match state:
		"crawl": speed = CRAWL_SPEED
		"limp": speed = LIMP_SPEED
	if dist > ATTACK_RANGE * 0.9:
		velocity.x = to_target.normalized().x * speed
		velocity.z = to_target.normalized().z * speed
		if to_target.length() > 0.01:
			var desired := atan2(to_target.x, to_target.z)
			rotation.y = lerp_angle(rotation.y, desired, 5.0 * delta)
		_play(_move_anim())
	else:
		velocity.x = 0.0
		velocity.z = 0.0
		if _attack_cd <= 0.0:
			_attack_cd = ATTACK_COOLDOWN
			_play("Attack", true)
			if target.has_method("take_damage"):
				target.take_damage(ATTACK_DAMAGE)
	if not is_on_floor():
		velocity.y -= GRAVITY * delta
	else:
		velocity.y = -0.5
	move_and_slide()


func _move_anim() -> String:
	match state:
		"crawl": return "Crawl"
		"limp": return "Walk"
	if not alive["arm_l"] and not alive["arm_r"]:
		return "WalkNoArms" if _has_anim("WalkNoArms") else "Walk"
	return "Walk"


func _nearest_target():
	var best = null
	var best_d := INF
	for t in targets:
		if not is_instance_valid(t):
			continue
		var d := global_position.distance_to(t.global_position)
		if d < best_d:
			best_d = d
			best = t
	return best


func _has_anim(n: String) -> bool:
	return _clip(n) != ""


## Имя клипа с учётом clip_prefix: MxWalk, если он есть, иначе родной Walk.
func _clip(base_name: String) -> String:
	if anim == null:
		return ""
	if not clip_prefix.is_empty() and anim.has_animation(clip_prefix + base_name):
		return clip_prefix + base_name
	return base_name if anim.has_animation(base_name) else ""


func _play(n: String, restart := false) -> void:
	if anim == null:
		return
	if _anim_name == n and not restart:
		return
	var clip := _clip(n)
	if not clip.is_empty():
		anim.play(clip, 0.12)
		_anim_name = n


## Точка удара: игрок бьёт лучом, сюда приходит точка попадания.
func receive_hit(point: Vector3, _dir: Vector3, dmg_limb: float, dmg_body: float) -> void:
	if dead:
		return
	var part := _closest_part(point)
	last_part_hit = part
	if part == "body" or part == "head":
		hp -= dmg_body if part == "body" else dmg_body * 1.5
		if hp <= 0.0:
			_die()
		_flash()
		return
	part_hp[part] -= dmg_limb
	_flash()
	if part_hp[part] <= 0.0:
		_sever(part)


## Какая часть ближе всего к точке попадания (только живые).
func _closest_part(point: Vector3) -> String:
	if skeleton == null:
		return "body"
	var best := "body"
	var best_d := LIMB_PICK_RADIUS
	for part in ["head", "arm_l", "arm_r", "leg_l", "leg_r"]:
		if not alive.get(part, false):
			continue
		var bone: String = PARTS[part][1]
		var idx := skeleton.find_bone(bone)
		if idx < 0:
			continue
		var pose: Transform3D = skeleton.global_transform * skeleton.get_bone_global_pose(idx)
		var a: Vector3 = pose.origin
		var b: Vector3 = pose * Vector3(0, bone_length(idx), 0)
		var d := _dist_to_segment(point, a, b)
		if d < best_d:
			best_d = d
			best = part
	return best


## Длина кости: в Godot 4.3 нет Skeleton3D.get_bone_length(), считаем
## по rest-позе дочерней кости (0.12 м для листьев — кисти, стопы).
func bone_length(idx: int) -> float:
	if skeleton == null or idx < 0:
		return 0.12
	for c in skeleton.get_bone_count():
		if skeleton.get_bone_parent(c) == idx:
			return skeleton.get_bone_rest(c).origin.length()
	return 0.12


func _dist_to_segment(p: Vector3, a: Vector3, b: Vector3) -> float:
	var ab := b - a
	var l2 := ab.length_squared()
	if l2 < 1e-8:
		return p.distance_to(a)
	var t := clampf((p - a).dot(ab) / l2, 0.0, 1.0)
	return p.distance_to(a + ab * t)


func _sever(part: String) -> void:
	if not alive.get(part, false):
		return
	alive[part] = false
	var node := _part_node(part)
	if node:
		node.visible = false
	_spawn_debris(part)
	_update_state()
	limb_cut.emit(self, part)
	if part == "head":
		_die()


func _spawn_debris(part: String) -> void:
	var suffix: String = PARTS[part][0]
	var piece: Node3D = null
	for c in model.find_children("*", "MeshInstance3D", true, false):
		if String(c.name).ends_with("_Piece_" + suffix):
			piece = c
			break
	if piece == null:
		return
	var xform: Transform3D = global_transform
	if skeleton != null:
		var idx := skeleton.find_bone(PARTS[part][1])
		if idx >= 0:
			xform = skeleton.global_transform * skeleton.get_bone_global_pose(idx)
	var body := RigidBody3D.new()
	body.name = "Debris_" + part
	body.collision_layer = 8
	body.collision_mask = 1 | 8
	body.mass = 3.0
	body.linear_damp = 0.6
	body.angular_damp = 1.2
	var mesh := piece.duplicate()
	mesh.position = Vector3.ZERO
	mesh.rotation = Vector3.ZERO
	body.add_child(mesh)
	var aabb := _aabb_of(mesh)
	var shape := BoxShape3D.new()
	shape.size = aabb.size.max(Vector3.ONE * 0.06)
	var cs := CollisionShape3D.new()
	cs.shape = shape
	cs.position = aabb.get_center()
	body.add_child(cs)
	get_tree().current_scene.add_child(body)
	body.global_transform = Transform3D(xform.basis.orthonormalized(), xform.origin)
	body.apply_central_impulse(-xform.basis.z * 1.5 + Vector3.UP * 1.2)


func _aabb_of(n: Node) -> AABB:
	if n is MeshInstance3D:
		return (n as MeshInstance3D).get_aabb()
	var box := AABB()
	for c in n.get_children():
		box = box.merge(_aabb_of(c))
	return box


func _update_state() -> void:
	var legs := int(alive["leg_l"]) + int(alive["leg_r"])
	var arms := int(alive["arm_l"]) + int(alive["arm_r"])
	if legs == 0:
		state = "crawl"
		_set_capsule(0.65, 0.35)
		_play("Crawl")
	elif legs == 1:
		state = "limp"
		_set_capsule(1.5, 0.75)
	else:
		state = "walk"
		_set_capsule(1.8, 0.9)
	_anim_name = ""


func _set_capsule(height: float, centre: float) -> void:
	var cs := get_node_or_null("BodyShape") as CollisionShape3D
	if cs == null:
		return
	var cap := CapsuleShape3D.new()
	cap.height = height
	cap.radius = 0.35
	cs.shape = cap
	cs.position.y = centre


func _flash() -> void:
	# короткая вспышка на модели, чтобы удар читался
	if model == null:
		return
	var meshes := model.find_children("*", "MeshInstance3D", true, false)
	for m in meshes:
		if not (m is MeshInstance3D):
			continue
		var mat: Material = m.get_active_material(0)
		if mat is StandardMaterial3D:
			var dup: StandardMaterial3D = mat.duplicate()
			dup.emission_enabled = true
			dup.emission = Color(0.9, 0.1, 0.1)
			dup.emission_energy_multiplier = 0.6
			m.set_surface_override_material(0, dup)
	await get_tree().create_timer(0.09).timeout
	if is_instance_valid(self):
		for m in meshes:
			if is_instance_valid(m) and m is MeshInstance3D:
				m.set_surface_override_material(0, null)


func _die() -> void:
	if dead:
		return
	dead = true
	_play("Death")
	collision_layer = 0
	set_physics_process(false)
	died.emit(self)
