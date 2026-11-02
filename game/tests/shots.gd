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
	img.save_png("res://ci/shots/%s.png" % name)
	print("shot ", name, " ", img.get_size())


func _place(pos: Vector3, look_at_point: Vector3) -> void:
	cam.look_at_from_position(pos, look_at_point, Vector3.UP)
	# у самой камеры свой Environment не нужен, но мелкий клип убирает джиттер
	await _frames(2)


func _run() -> void:
	DirAccess.make_dir_recursive_absolute("res://ci/shots")
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
	await _place(zp + Vector3(2.4, 1.3, 2.8), zp + Vector3(0, 0.4, 0))
	await _shot("04_crawl")

	# 5. тот же зомби чуть сверху: видно куски на земле
	await _place(zp + Vector3(3.0, 3.2, 3.4), zp + Vector3(0, 0.2, 0))
	await _shot("05_debris")

	print("готово")
	quit(0)
