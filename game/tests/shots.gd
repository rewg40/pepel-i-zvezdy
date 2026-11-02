extends SceneTree
## Кадры из живого движка для визуальной проверки (нужен GPU или llvmpipe):
##
##   xvfb-run -a godot --path game --rendering-driver opengl3 \
##       --script res://tests/shots.gd

var scene: Node
var cam: Camera3D


func _initialize() -> void:
	_run.call_deferred()


func _frames(n: int) -> void:
	for i in n:
		await process_frame


func _find(root_node: Node, cls: String) -> Node:
	for c in root_node.find_children("*", cls, true, false):
		return c
	return null


func _shot(name: String) -> void:
	await _frames(3)
	var img := root.get_texture().get_image()
	var dir := OS.get_environment("SHOT_DIR")
	if dir.is_empty():
		dir = "res://ci/shots"
	DirAccess.make_dir_recursive_absolute(dir)
	var path := dir.path_join("%s.png" % name)
	var err := img.save_png(path)
	print("shot ", name, " ", img.get_size(), " -> ", path, " err=", err)


## Диагностика: где находится модель относительно земли.
func _debug_ground(node: Node, label: String) -> void:
	var skel: Skeleton3D = node.get("skeleton")
	var model: Node3D = node.get("model")
	var lowest := INF
	var lowest_name := ""
	if skel != null:
		for i in skel.get_bone_count():
			var y: float = (skel.global_transform * skel.get_bone_global_pose(i)).origin.y
			if y < lowest:
				lowest = y
				lowest_name = skel.get_bone_name(i)
	var aabb_y := INF
	var on_floor: bool = bool(node.call("is_on_floor")) if node.has_method("is_on_floor") else false
	if model != null:
		for mi in model.find_children("*", "MeshInstance3D", true, false):
			var m := mi as MeshInstance3D
			if not m.visible:
				continue
			aabb_y = minf(aabb_y, (m.global_transform * m.get_aabb()).position.y)
	print("%s: body y=%.2f model y=%.2f lowest bone=%s y=%.2f lowest mesh y=%.2f on_floor=%s" % [
		label, (node as Node3D).global_position.y, model.position.y if model else 0.0,
		lowest_name, lowest, aabb_y, on_floor])


## Оставляем видимыми только меши с указанными материалами ([] — все).
func _only_materials(island: Node, allowed: Array) -> void:
	for mi in island.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		if m.mesh == null:
			continue
		var own := m.mesh.surface_get_material(0)
		var nm := "-" if own == null else String(own.resource_name)
		m.visible = allowed.is_empty() or allowed.has(nm)


func _place(pos: Vector3, look_at_point: Vector3) -> void:
	cam.look_at_from_position(pos, look_at_point, Vector3.UP)
	# у самой камеры свой Environment не нужен, но мелкий клип убирает джиттер
	await _frames(2)


func _run() -> void:
	scene = (load("res://main.tscn") as PackedScene).instantiate()
	root.add_child(scene)
	current_scene = scene
	await _frames(12)

	var players: Array = scene.get("players")
	var zombies: Array = scene.get("zombies")
	var pl = players[0]
	cam = Camera3D.new()
	cam.fov = 55.0
	scene.add_child(cam)
	cam.current = true

	# 1. игрок вблизи, сбоку
	var pp: Vector3 = pl.global_position
	await _place(pp + Vector3(2.6, 1.5, 2.6), pp + Vector3(0, 1.1, 0))
	await _shot("01_player")

	# 2. вся арена: игрок и три зомби
	await _place(pp + Vector3(7.0, 6.5, 8.5), pp + Vector3(0, 0.8, -6.0))
	await _shot("02_arena")

	# 3. зомби вблизи
	var z = zombies[1]
	var zp: Vector3 = z.global_position
	await _place(zp + Vector3(2.2, 1.6, 2.6), zp + Vector3(0, 1.0, 0))
	await _shot("03_zombie")

	# 4. отрубаем зомби ноги и руку, смотрим на ползущего
	var skel: Skeleton3D = z.skeleton
	for part in ["leg_l", "leg_r", "arm_r"]:
		var bone: String = z.PARTS[part][1]
		var idx := skel.find_bone(bone)
		for n in 3:
			var xf: Transform3D = skel.global_transform * skel.get_bone_global_pose(idx)
			z.receive_hit(xf.origin + xf.basis.y * 0.1, Vector3.FORWARD, 1.0, 34.0)
			await _frames(1)
	await _frames(20)
	# зомби ползёт и успевает уйти из кадра — фиксируем его на месте
	z.set_physics_process(false)
	zp = z.global_position
	_debug_ground(z, "зомби-ползун")
	print("игрок y=%.2f pos=%s, камера=%s" % [pl.global_position.y, pl.global_position, cam.global_position])
	await _place(zp + Vector3(2.4, 1.3, 2.8), zp + Vector3(0, 0.4, 0))
	await _shot("04_crawl")

	# 5. тот же зомби чуть сверху: видно куски на земле
	await _place(zp + Vector3(3.0, 3.2, 3.4), zp + Vector3(0, 0.2, 0))
	await _shot("05_debris")

	# 6-7. диагностика: что именно занимает дальний план
	var island := scene.get_node_or_null("Island")
	if island != null:
		# по одному материалу с того же ракурса, что 02
		await _place(pp + Vector3(7.0, 6.5, 8.5), pp + Vector3(0, 0.8, -6.0))
		for mname in ["Ocean", "Seafloor", "Islet", "Vegetation"]:
			_only_materials(island, [mname])
			await _shot("08_only_" + mname.to_lower())
		_only_materials(island, [])
		var by_mat := {}
		for mi in island.find_children("*", "MeshInstance3D", true, false):
			var m := mi as MeshInstance3D
			if m.mesh == null:
				continue
			var own := m.mesh.surface_get_material(0)
			var nm := "-" if own == null else String(own.resource_name)
			by_mat[nm] = int(by_mat.get(nm, 0)) + 1
		print("материалы острова: ", by_mat)
		var far := pp + Vector3(0, 30, 90)
		await _place(far, pp + Vector3(0, 40, -600))
		_only_materials(island, ["Island"])
		await _shot("06_terrain_only")
		_only_materials(island, ["Ocean", "Seafloor", "Islet"])
		await _shot("07_water_only")
		_only_materials(island, [])

	print("готово")
	quit(0)
