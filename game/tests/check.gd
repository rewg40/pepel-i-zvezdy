extends SceneTree
## Headless-проверка проекта целиком: импорт моделей, скелет, клипы,
## внешняя библиотека Mixamo из models/*_clips.glb и отрубание конечностей.
##
##   godot --headless --path game --script res://tests/check.gd

var fails := 0
var checks := 0


func ok(cond: bool, what: String) -> void:
	checks += 1
	if cond:
		print("PASS  ", what)
	else:
		fails += 1
		print("FAIL  ", what)


func _initialize() -> void:
	_run.call_deferred()


func _frames(n: int) -> void:
	for i in n:
		await process_frame


func _find(root_node: Node, cls: String) -> Node:
	for c in root_node.find_children("*", cls, true, false):
		return c
	return null


## То же, что _merge_clips в player.gd/zombie.gd: внешняя библиотека клипов.
func _merge_clips(anim: AnimationPlayer, path: String) -> int:
	if anim == null or not ResourceLoader.exists(path):
		return 0
	var holder: Node = (load(path) as PackedScene).instantiate()
	var src: AnimationPlayer = _find(holder, "AnimationPlayer")
	var added := 0
	if src != null:
		if not anim.has_animation_library(""):
			anim.add_animation_library("", AnimationLibrary.new())
		var lib := anim.get_animation_library("")
		for lib_name in src.get_animation_library_list():
			var slib: AnimationLibrary = src.get_animation_library(lib_name)
			for a in slib.get_animation_list():
				if anim.has_animation(String(a)):
					continue
				lib.add_animation(String(a), slib.get_animation(a))
				added += 1
	holder.queue_free()
	return added


func _check_model(path: String, clips_path: String, prefix: String) -> Dictionary:
	print("\n=== ", path)
	var packed := load(path) as PackedScene
	if packed == null:
		ok(false, path + ": не загрузился")
		return {}
	var inst: Node3D = packed.instantiate()
	root.add_child(inst)
	var skel: Skeleton3D = _find(inst, "Skeleton3D")
	var anim: AnimationPlayer = _find(inst, "AnimationPlayer")
	ok(skel != null, path + ": Skeleton3D создан")
	ok(anim != null, path + ": AnimationPlayer создан")
	if skel == null or anim == null:
		return {}
	print("  костей: ", skel.get_bone_count())
	var names := []
	for i in skel.get_bone_count():
		names.append(skel.get_bone_name(i))
	print("  ", ", ".join(names))
	for b in ["Hips", "Spine", "Chest", "Head", "UpperArm_L", "LowerArm_R",
			"Thigh_L", "Shin_R", "Foot_L", "Hand_R"]:
		ok(skel.find_bone(b) >= 0, "%s: кость %s" % [path.get_file(), b])

	var own := anim.get_animation_list()
	print("  родные клипы: ", Array(own))
	ok(own.size() >= 6, "%s: родных клипов %d" % [path.get_file(), own.size()])

	var added := _merge_clips(anim, clips_path)
	print("  внешних клипов добавлено: ", added)
	ok(added > 0, "%s: клипы из %s подмешаны" % [path.get_file(), clips_path.get_file()])

	# все анимации: каждый track должен указывать на существующую кость
	for an in anim.get_animation_list():
		var a: Animation = anim.get_animation(an)
		var bad := 0
		for t in a.get_track_count():
			var p: NodePath = a.track_get_path(t)
			var target: Node = inst.get_node_or_null(NodePath(p.get_concatenated_names()))
			var bone: String = String(p.get_concatenated_subnames())
			if target == null or skel.find_bone(bone) < 0:
				bad += 1
		ok(bad == 0 and a.get_track_count() > 0,
			"%s «%s»: %d дорожек, битых %d, длина %.2f с" %
			[path.get_file(), an, a.get_track_count(), bad, a.length])

	# проигрывание внешнего клипа действительно двигает кости
	var walk := prefix + "Walk"
	if anim.has_animation(walk):
		anim.play(walk)
		anim.seek(0.0, true)
		await _frames(1)
		var i_hand := skel.find_bone("Hand_L")
		var p0 := (skel.global_transform * skel.get_bone_global_pose(i_hand)).origin
		anim.seek(0.4, true)
		await _frames(1)
		var p1 := (skel.global_transform * skel.get_bone_global_pose(i_hand)).origin
		ok(p0.distance_to(p1) > 0.02,
			"%s: «%s» двигает кисть на %.1f см" % [path.get_file(), walk, p0.distance_to(p1) * 100.0])
	var hips := skel.find_bone("Hips")
	if hips >= 0:
		var h := (skel.global_transform * skel.get_bone_global_pose(hips)).origin
		print("  бёдра в мировых координатах: ", h)
	inst.queue_free()
	return {"skel": skel, "anim": anim}


func _run() -> void:
	print("=== Godot ", Engine.get_version_info().string, " / ", OS.get_name())
	_check_model("res://models/medic.glb", "res://models/medic_clips.glb", "Mx")
	_check_model("res://models/zombie.glb", "res://models/zombie_clips.glb", "Mx")

	print("\n=== главная сцена")
	var scene: Node = (load("res://main.tscn") as PackedScene).instantiate()
	root.add_child(scene)
	current_scene = scene
	await _frames(5)
	var zombies: Array = scene.get("zombies")
	var players: Array = scene.get("players")
	ok(players.size() >= 1, "игроков: %d" % players.size())
	ok(zombies.size() == 3, "зомби: %d" % zombies.size())
	var island := scene.get_node_or_null("Island") as Node3D
	var island_meshes := 0
	if island != null:
		for m in island.find_children("*", "MeshInstance3D", true, false):
			island_meshes += 1
	ok(island != null and island_meshes > 0,
		"остров на сцене: узлов-мешей %d" % island_meshes)

	# земля должна рисоваться родным атласом острова, а не синтетической плиткой
	var terrain_tex: Texture2D = null
	var ground_mat: Material = null
	if island != null:
		for m in island.find_children("*", "MeshInstance3D", true, false):
			var mi := m as MeshInstance3D
			if mi.mesh == null:
				continue
			var own: Material = mi.mesh.surface_get_material(0)
			if own is StandardMaterial3D and (own as StandardMaterial3D).albedo_texture != null:
				terrain_tex = (own as StandardMaterial3D).albedo_texture
				ground_mat = mi.get_active_material(0)
				break
	ok(terrain_tex != null and terrain_tex.get_width() >= 2048,
		"остров: земля на родном атласе %s" % [
			"-" if terrain_tex == null else "%dpx" % terrain_tex.get_width()])
	ok(ground_mat is ShaderMaterial,
		"остров: земля на шейдере ground.gdshader")
	if ground_mat is ShaderMaterial:
		var sm := ground_mat as ShaderMaterial
		ok(sm.get_shader_parameter("atlas") != null, "шейдер земли получает атлас")
		ok(sm.get_shader_parameter("detail") != null, "шейдер земли получает зерно")

	# терраин рисуется по картам высот: сетка 1 м у арены + 24 м по острову
	var terrain := scene.get_node_or_null("IslandTerrain")
	var terrain_tris := 0
	var terrain_ok_mat := true
	if terrain != null:
		for m in terrain.find_children("*", "MeshInstance3D", true, false):
			var mi := m as MeshInstance3D
			if mi.mesh != null:
				terrain_tris += mi.mesh.get_faces().size() / 3
			if not (mi.material_override is ShaderMaterial):
				terrain_ok_mat = false
	ok(terrain != null and terrain_tris > 100000,
		"терраин по картам высот: треугольников %d" % terrain_tris)
	ok(terrain_ok_mat, "терраин рисуется шейдером земли (атлас + зерно)")
	var src := scene.get_node_or_null("Island")
	var src_visible := false
	if src != null:
		for m in src.find_children("*", "MeshInstance3D", true, false):
			if String((m as Node).name) == "node_0" and (m as MeshInstance3D).visible:
				src_visible = true
	ok(not src_visible, "исходный меш терраина скрыт")
	var hm: Dictionary = scene.get("_hm")
	ok(not hm.is_empty() and float(hm.get("data", PackedFloat32Array())[0]) > 1000.0,
		"карта высот загружена в float32 (высота в метрах)")
	var arena: Vector3 = scene.get("arena_position")
	ok(absf(scene.call("height_at", arena.x, arena.z) - arena.y) < 0.4,
		"высота арены из карты (%.2f) совпадает с arena.json (%.2f)"
			% [scene.call("height_at", arena.x, arena.z), arena.y])

	if players.size() > 0:
		var pl = players[0]
		ok(pl.skeleton != null and pl.anim != null, "игрок: скелет и AnimationPlayer")
		ok(String(pl.anim.current_animation).begins_with("Mx") or pl.anim.current_animation != "",
			"игрок играет клип «%s»" % pl.anim.current_animation)
		var sword: Node3D = pl.get("sword")
		ok(sword != null, "меч прицеплен к кисти")
		# удар: длительность и момент попадания должны следовать клипу
		pl.start_attack()
		await _frames(1)
		var atk := "MxAttack"
		ok(pl.anim.has_animation(atk), "игрок бьёт клипом %s" % atk)
		var clip_len: float = pl.anim.get_animation(atk).length
		ok(absf(float(pl._attack_len) - clip_len) < 0.02,
			"длительность удара = длине клипа (%.2f / %.2f с)" % [pl._attack_len, clip_len])
		ok(float(pl._attack_hit) > 0.2 and float(pl._attack_hit) < clip_len,
			"момент попадания внутри клипа (%.2f с)" % pl._attack_hit)

	if zombies.size() > 0:
		var z = zombies[0]
		ok(z.hp == 1000.0, "зомби: тело 1000 HP (%.0f)" % z.hp)
		ok(z.part_hp["arm_l"] == 3.0, "зомби: рука 3 HP")
		var skel: Skeleton3D = z.skeleton
		var hits := {}
		for part in ["arm_l", "leg_l", "leg_r"]:
			var bone: String = z.PARTS[part][1]
			var idx := skel.find_bone(bone)
			# кость каждый раз пересчитываем: зомби покачивается в idle, и точка,
			# снятая один раз, к третьему удару уезжает на другую конечность
			for n in 3:
				var xf: Transform3D = skel.global_transform * skel.get_bone_global_pose(idx)
				var p: Vector3 = xf.origin + xf.basis.y * maxf(z.bone_length(idx) * 0.5, 0.05)
				hits[part] = p
				z.receive_hit(p, Vector3.FORWARD, 1.0, 34.0)
				await _frames(1)
			ok(not z.alive[part], "зомби: %s отрублена после 3 ударов" % part)
		await _frames(2)
		ok(z.state == "crawl", "зомби: без двух ног состояние «%s»" % z.state)
		ok(z._clip("WalkNoArms") != "",
			"зомби: клип без рук найден (%s)" % z._clip("WalkNoArms"))
		ok(String(z.anim.current_animation).ends_with("Crawl"),
			"зомби: играет «%s»" % z.anim.current_animation)
		var debris := 0
		var glowing := 0
		for c in scene.find_children("Debris_*", "RigidBody3D", true, false):
			debris += 1
			for mi in c.find_children("*", "MeshInstance3D", true, false):
				var m := mi as MeshInstance3D
				for surf in m.mesh.get_surface_count():
					var mat := m.get_surface_override_material(surf)
					if mat is StandardMaterial3D and (mat as StandardMaterial3D).emission_enabled:
						glowing += 1
		ok(debris >= 3, "куски конечностей на земле: %d" % debris)
		ok(glowing == 0, "куски не наследуют красную вспышку удара")
		# удар по телу: 1000 HP не должен улететь от одного удара
		z.receive_hit(z.global_position + Vector3(0, 0.9, 0), Vector3.FORWARD, 1.0, 34.0)
		await _frames(1)
		ok(z.hp > 900.0, "зомби: тело держит удар (осталось %.0f HP)" % z.hp)

	await _frames(3)
	scene.queue_free()
	await _frames(3)
	print("\n=== итог: %d проверок, %d провалов" % [checks, fails])
	quit(0 if fails == 0 else 1)
