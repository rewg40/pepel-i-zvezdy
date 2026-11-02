extends CharacterBody3D
## Медик от третьего лица: ходьба/бег, камера мышью, удар мечом по частям зомби.

signal hit_part(zombie, part: String, point: Vector3)

const GRAVITY := 24.0
const SPEED := 4.2
const SPRINT := 6.6
const ACCEL := 12.0
const MODEL_SCALE_DEFAULT := 1.65

const ATTACK_LENGTH := 1.0          # длительность родного клипа Attack, сек
const ATTACK_HIT_TIME := 0.5       # момент удара внутри родного клипа
const ATTACK_HIT_PHASE := 0.55     # доля длины клипа, на которой приходит удар
const ATTACK_REACH := 3.0
const ATTACK_DAMAGE_LIMB := 1.0     # у конечности 3 HP -> 3 удара
const ATTACK_DAMAGE_BODY := 34.0    # у тела 1000 HP -> ~30 ударов
const ANIMS := {
	"idle": "Idle", "walk": "Walk", "run": "Run",
	"attack": "Attack", "hit": "Hit", "death": "Death",
}

@export var model_scale := MODEL_SCALE_DEFAULT
@export_file("*.glb") var extra_clips := "res://models/medic_clips.glb"
## Префикс имён клипов из extra_clips ("Mx" -> MxIdle, MxWalk…). Пусто — родные.
@export var clip_prefix := "Mx"
@export var mouse_sensitivity := 0.0025
@export var sword_offset := Vector3(0.0, 0.02, 0.0)
@export var sword_rotation_deg := Vector3(180.0, 0.0, 0.0)

var model: Node3D
var skeleton: Skeleton3D
var anim: AnimationPlayer
var camera: Camera3D
var arm: SpringArm3D
var sword: Node3D
var hp := 100.0

var _yaw := 0.0
var _pitch := -0.12
var _attacking := false
var _attack_timer := 0.0
var _attack_len := ATTACK_LENGTH
var _attack_hit := ATTACK_HIT_TIME
var _hit_done := false


func _ready() -> void:
	collision_layer = 2
	collision_mask = 1
	var cap := CapsuleShape3D.new()
	cap.height = 1.8
	cap.radius = 0.34
	var cs := CollisionShape3D.new()
	cs.shape = cap
	cs.position.y = 0.9
	add_child(cs)

	model = load("res://models/medic.glb").instantiate()
	model.name = "MedicModel"
	model.scale = Vector3.ONE * model_scale
	add_child(model)

	# у медика тоже есть служебные узлы (культи-заглушки и копии деталей) — прячем
	for c in model.find_children("*", "Node3D", true, false):
		var nm := String(c.name)
		if nm.ends_with("_Pieces") or nm.contains("_Piece_"):
			c.visible = false

	anim = _find_anim(model)
	skeleton = _find_skeleton(model)
	_merge_clips(anim, extra_clips)
	for n in ANIMS.values():
		if anim and not anim.has_animation(n) and not anim.has_animation(clip_prefix + n):
			push_warning("в модели нет анимации " + n)

	arm = SpringArm3D.new()
	arm.spring_length = 4.2
	arm.position.y = 1.55
	arm.collision_mask = 1
	arm.margin = 0.35
	add_child(arm)
	camera = Camera3D.new()
	camera.fov = 62.0
	camera.position = Vector3(0.55, 0.0, 0.0)   # лёгкий сдвиг вправо, "через плечо"
	arm.add_child(camera)

	_attach_sword()
	play("idle")
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _find_anim(root: Node) -> AnimationPlayer:
	for c in root.find_children("*", "AnimationPlayer", true, false):
		return c
	return null


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

func _find_skeleton(root: Node) -> Skeleton3D:
	for c in root.find_children("*", "Skeleton3D", true, false):
		return c
	return null


## Меч цепляется к кости кисти через BoneAttachment3D.
func _attach_sword() -> void:
	if skeleton == null:
		push_warning("нет Skeleton3D — меч не прикрепить")
		return
	var bone := -1
	for name in ["Hand_R", "Hand.R", "mixamorig:RightHand", "RightHand"]:
		bone = skeleton.find_bone(name)
		if bone >= 0:
			break
	if bone < 0:
		push_warning("не найдена кость кисти")
		return
	var attach := BoneAttachment3D.new()
	attach.name = "SwordSocket"
	skeleton.add_child(attach)
	attach.bone_idx = bone
	attach.bone_name = skeleton.get_bone_name(bone)

	var packed: PackedScene = load("res://models/sword.glb")
	if packed:
		sword = packed.instantiate()
		sword.name = "Sword"
		# модель меча: рукоять в нуле, клинок вдоль -Y; разворачиваем вдоль кости
		sword.position = sword_offset
		sword.rotation_degrees = sword_rotation_deg
		sword.scale = Vector3.ONE / max(model_scale, 0.001)
		attach.add_child(sword)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		_yaw -= event.relative.x * mouse_sensitivity
		_pitch = clamp(_pitch - event.relative.y * mouse_sensitivity, -1.2, 0.6)
	if event.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE if \
			Input.mouse_mode == Input.MOUSE_MODE_CAPTURED else Input.MOUSE_MODE_CAPTURED
	if event.is_action_pressed("attack"):
		start_attack()


func _physics_process(delta: float) -> void:
	# --- движение
	var input := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var dir := Vector3(input.x, 0.0, input.y).rotated(Vector3.UP, _yaw)
	var speed := SPRINT if Input.is_action_pressed("sprint") else SPEED
	if _attacking:
		speed *= 0.35
	var target := dir * speed
	velocity.x = move_toward(velocity.x, target.x, ACCEL * speed * delta)
	velocity.z = move_toward(velocity.z, target.z, ACCEL * speed * delta)
	if not is_on_floor():
		velocity.y -= GRAVITY * delta
	else:
		velocity.y = -0.5
	move_and_slide()

	# --- поворот модели по камере
	if model:
		# модель смотрит в +Z, камера в -Z: разворачиваем модель на 180°
		model.rotation.y = lerp_angle(model.rotation.y, _yaw + PI, 12.0 * delta)
	if arm:
		arm.rotation.x = _pitch
		arm.rotation.y = _yaw

	# --- анимация
	if _attacking:
		_attack_timer += delta
		if not _hit_done and _attack_timer >= _attack_hit:
			_hit_done = true
			_do_hit()
		if _attack_timer >= _attack_len:
			_attacking = false
			play("idle")
	elif velocity.length() > 0.4:
		play("run" if speed > SPEED + 0.1 else "walk")
	else:
		play("idle")


func take_damage(amount: float) -> void:
	hp = max(0.0, hp - amount)
	if hp <= 0.0:
		hp = 100.0
		global_position += Vector3(0, 0.5, 0)
		play("hit")


func play(anim_name: String) -> void:
	if anim == null:
		return
	var a := _clip(ANIMS.get(anim_name, anim_name))
	if a.is_empty():
		return
	if anim.current_animation == a and anim.is_playing():
		return
	anim.play(a, 0.15)


## Имя клипа с учётом clip_prefix: MxIdle, если он есть, иначе родной Idle.
func _clip(base_name: String) -> String:
	if not clip_prefix.is_empty() and anim != null:
		var pref := clip_prefix + base_name
		if anim.has_animation(pref):
			return pref
	return base_name if anim != null and anim.has_animation(base_name) else ""


func start_attack() -> void:
	if _attacking:
		return
	_attacking = true
	_attack_timer = 0.0
	_hit_done = false
	var atk := _clip(ANIMS["attack"])
	if not atk.is_empty():
		# длительность берём из клипа: у Mixamo замах 1.8 с, у родного 1.0 с
		_attack_len = maxf(anim.get_animation(atk).length, 0.2)
		_attack_hit = _attack_len * ATTACK_HIT_PHASE
		anim.play(atk, 0.05, 1.0)
		anim.speed_scale = 1.0


## Луч из камеры; при попадании в зомби выбираем ближайшую к точке удара часть.
func _do_hit() -> void:
	if camera == null:
		return
	var from := camera.global_position
	var dir := -camera.global_transform.basis.z
	var to := from + dir * ATTACK_REACH
	var space := get_world_3d().direct_space_state
	var q := PhysicsRayQueryParameters3D.create(from, to, 1 | 4)
	q.exclude = [get_rid()]
	var hit := space.intersect_ray(q)
	if hit.is_empty():
		return
	var collider = hit.get("collider")
	if collider == null or not collider.has_method("receive_hit"):
		return
	var part_point: Vector3 = hit.position
	collider.receive_hit(part_point, dir, ATTACK_DAMAGE_LIMB, ATTACK_DAMAGE_BODY)
	hit_part.emit(collider, collider.last_part_hit, part_point)
