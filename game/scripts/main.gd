extends Node3D
## Собирает арену: остров, свет, игрок-медик, три зомби, HUD.
## Всё строится кодом, чтобы сцену было легко править из одного файла.

const PLAYER_SCENE := preload("res://scenes/player.tscn")
const ZOMBIE_SCENE := preload("res://scenes/zombie.tscn")
const HUD_SCENE := preload("res://scenes/hud.tscn")

const MODEL_SCALE := 1.65          # модели сделаны ~1.1 м в высоту -> рост ~1.8 м
const ZOMBIE_COUNT := 3

@export var island_path := "res://models/island.glb"
@export var heightmap_json := "res://models/heightmap.json"
@export var arena_json := "res://models/arena.json"

var arena_position := Vector3.ZERO
var arena_y := 0.0
var players: Array = []
var zombies: Array = []
var _hm := {}                       # кэш карты высот


func _ready() -> void:
	_setup_environment()
	_load_arena_meta()
	_spawn_island()
	_spawn_player()
	_spawn_zombies()
	var hud = HUD_SCENE.instantiate()
	add_child(hud)
	hud.setup(self)


func _setup_environment() -> void:
	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	var sky := Sky.new()
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = Color(0.32, 0.42, 0.58)
	sky_mat.sky_horizon_color = Color(0.75, 0.72, 0.66)
	sky_mat.ground_bottom_color = Color(0.20, 0.20, 0.19)
	sky_mat.ground_horizon_color = Color(0.55, 0.52, 0.47)
	sky.sky_material = sky_mat
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.55
	env.fog_enabled = true
	env.fog_light_color = Color(0.66, 0.66, 0.62)
	env.fog_density = 0.0009
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.tonemap_exposure = 0.85

	var world_env := WorldEnvironment.new()
	world_env.environment = env
	add_child(world_env)

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-42, -125, 0)
	sun.light_energy = 1.15
	sun.light_color = Color(1.0, 0.94, 0.86)
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 180.0
	add_child(sun)

	var fill := DirectionalLight3D.new()
	fill.rotation_degrees = Vector3(-18, 60, 0)
	fill.light_energy = 0.25
	fill.light_color = Color(0.6, 0.72, 0.9)
	add_child(fill)


func _load_arena_meta() -> void:
	var f := FileAccess.open(arena_json, FileAccess.READ)
	if f == null:
		push_warning("нет %s — арена в нуле" % arena_json)
		return
	var data: Dictionary = JSON.parse_string(f.get_as_text())
	arena_position = Vector3(data.get("x", 0.0), data.get("y", 0.0), data.get("z", 0.0))
	arena_y = arena_position.y


func _spawn_island() -> void:
	var packed: PackedScene = load(island_path)
	if packed == null:
		push_error("не удалось загрузить " + island_path)
		return
	var island := packed.instantiate()
	island.name = "Island"
	add_child(island)
	_fix_island_materials(island)
	_build_arena_ground(island)
	_make_heightmap_collision()


## Материалы острова. Своей текстуры у земли нет — используем родной атлас
## island.glb (4096², UV 0..1 на всю карту, ~5 м на тексель). Растительность и
## островки раскрашены вершинными цветами — их надо включить, иначе они белые.
func _fix_island_materials(island: Node) -> void:
	var n := 0
	for mi in island.find_children("*", "MeshInstance3D", true, false):
		var mesh_instance := mi as MeshInstance3D
		if mesh_instance.mesh == null:
			continue
		for surf in mesh_instance.mesh.get_surface_count():
			var mat := mesh_instance.get_active_material(surf)
			if not (mat is StandardMaterial3D):
				continue
			var dup: StandardMaterial3D = mat.duplicate()
			dup.roughness = 1.0
			dup.metallic = 0.0
			dup.metallic_specular = 0.12
			dup.vertex_color_use_as_albedo = true
			dup.vertex_color_is_srgb = true
			mesh_instance.set_surface_override_material(surf, dup)
			n += 1
	print("остров: материалы (", n, " поверхностей), вершинные цвета включены")


## UV земли аффинно связан с миром: u = x * UV_U_PER_M + UV_U_OFFSET,
## v = z * UV_V_PER_M + UV_V_OFFSET (коэффициенты сняты с island.glb).
const UV_U_PER_M := 5.0e-5
const UV_U_OFFSET := 0.499974
const UV_V_PER_M := 7.0e-5
const UV_V_OFFSET := 0.505151


## В меше острова есть дыры (у арены — дыры в десятки метров): сквозь них видно
## пустоту/океан. Закрываем их заплаткой земли по heightmap.png с той же
## UV-развёрткой, что у острова, поэтому швов и разницы в цвете не видно.
const PATCH_RADIUS := 95.0        # м от центра арены
const PATCH_SINK := 0.12          # м ниже острова: где меш целый, его и видно
const PATCH_MAX_STEP := 1.0       # м между вершинами


func _build_arena_ground(island: Node) -> void:
	if _hm.is_empty():
		_load_heightmap()
	if _hm.is_empty():
		push_warning("нет heightmap.png — заплатка земли не построена")
		return
	var mat: Material = null
	for mi in island.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		for surf in m.mesh.get_surface_count() if m.mesh else 0:
			var candidate := m.get_active_material(surf)
			if candidate is StandardMaterial3D and (candidate as StandardMaterial3D).albedo_texture != null:
				mat = candidate
				break
		if mat != null:
			break
	var cx := arena_position.x
	var cz := arena_position.z
	var half := int(ceil(PATCH_RADIUS / PATCH_MAX_STEP))
	var side := half * 2 + 1
	var step: float = (2.0 * PATCH_RADIUS) / float(side - 1)

	var verts := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	verts.resize(side * side)
	normals.resize(side * side)
	uvs.resize(side * side)
	for iz in side:
		for ix in side:
			var x := cx - PATCH_RADIUS + float(ix) * step
			var z := cz - PATCH_RADIUS + float(iz) * step
			var idx := iz * side + ix
			verts[idx] = Vector3(x, height_at(x, z) - PATCH_SINK, z)
			var hl := height_at(x - step, z)
			var hr := height_at(x + step, z)
			var hu := height_at(x, z - step)
			var hd := height_at(x, z + step)
			normals[idx] = Vector3(hl - hr, 2.0 * step, hu - hd).normalized()
			uvs[idx] = Vector2(x * UV_U_PER_M + UV_U_OFFSET, z * UV_V_PER_M + UV_V_OFFSET)

	var indices := PackedInt32Array()
	indices.resize((side - 1) * (side - 1) * 6)
	var k := 0
	for iz in side - 1:
		for ix in side - 1:
			var a := iz * side + ix
			var b := a + 1
			var c := a + side
			var d := c + 1
			indices[k] = a
			indices[k + 1] = c
			indices[k + 2] = b
			indices[k + 3] = b
			indices[k + 4] = c
			indices[k + 5] = d
			k += 6

	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = verts
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_INDEX] = indices
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	var patch := MeshInstance3D.new()
	patch.name = "ArenaGroundPatch"
	patch.mesh = mesh
	patch.material_override = mat
	add_child(patch)
	print("заплатка земли: ", side, "x", side, " вершин, шаг ", "%.2f" % step, " м")


## Коллизия земли: HeightMapShape3D из heightmap.png (1 м на клетку).
func _make_heightmap_collision() -> void:
	var f := FileAccess.open(heightmap_json, FileAccess.READ)
	if f == null:
		push_warning("нет heightmap.json — земля без коллизии")
		return
	var meta: Dictionary = JSON.parse_string(f.get_as_text())
	if _hm.is_empty():
		_load_heightmap()
	if _hm.is_empty():
		push_warning("нет heightmap.png — земля без коллизии")
		return
	var w: int = _hm.res
	var d: int = _hm.res
	var data: PackedFloat32Array = _hm.data
	var shape := HeightMapShape3D.new()
	shape.map_width = w
	shape.map_depth = d
	shape.map_data = data
	var body := StaticBody3D.new()
	body.name = "Ground"
	body.collision_layer = 1
	body.collision_mask = 0
	var cs := CollisionShape3D.new()
	cs.shape = shape
	body.add_child(cs)
	var cell: float = meta.get("cell", 1.0)
	body.scale = Vector3(cell, 1.0, cell)
	# узел HeightMapShape3D центрирован в нуле: сдвигаем в центр участка
	body.position = Vector3(
		(meta.get("x0", 0.0) + meta.get("x1", 0.0)) * 0.5,
		0.0,
		(meta.get("z0", 0.0) + meta.get("z1", 0.0)) * 0.5)
	add_child(body)


func _spawn_player() -> void:
	var p = PLAYER_SCENE.instantiate()
	add_child(p)
	p.model_scale = MODEL_SCALE
	# игрок в 6 м перед ареной, смотрит в -Z (туда же, куда смотрит камера)
	var py := height_at(arena_position.x, arena_position.z + 6.0) + 0.15
	p.global_position = Vector3(arena_position.x, py, arena_position.z + 6.0)
	p.rotation.y = 0.0
	players.append(p)


func _spawn_zombies() -> void:
	# три зомби полукругом в шести метрах от игрока
	var offsets := [Vector3(-4.0, 0, -7.0), Vector3(0.0, 0, -9.0), Vector3(4.0, 0, -7.0)]
	var names := ["Зомби 1", "Зомби 2", "Зомби 3"]
	for i in ZOMBIE_COUNT:
		var z = ZOMBIE_SCENE.instantiate()
		z.name = "Zombie%d" % (i + 1)
		z.model_scale = MODEL_SCALE
		add_child(z)
		var pos: Vector3 = arena_position + offsets[i]
		pos.y = height_at(pos.x, pos.z) + 0.05
		z.global_position = pos
		# модели смотрят в +Z: разворачиваем к игроку
		z.rotation.y = atan2(pos.x - arena_position.x, pos.z - (arena_position.z + 6.0))
		z.title = names[i]
		zombies.append(z)


## Высота рельефа по карте высот (та же, что у коллизии).
func height_at(x: float, z: float) -> float:
	if _hm.is_empty():
		_load_heightmap()
	if _hm.is_empty():
		return arena_position.y
	var ix := int(round((x - _hm.x0) / _hm.cell))
	var iz := int(round((z - _hm.z0) / _hm.cell))
	if ix < 0 or iz < 0 or ix >= _hm.res or iz >= _hm.res:
		return arena_position.y
	return _hm.data[iz * _hm.res + ix]


func _load_heightmap() -> void:
	var f := FileAccess.open(heightmap_json, FileAccess.READ)
	if f == null:
		return
	var meta: Dictionary = JSON.parse_string(f.get_as_text())
	var res: int = meta.get("res", 0)
	var data := PackedFloat32Array()
	# heightmap.f32 (float32, абсолютные высоты) — точный вариант:
	# PNG после импорта в движок отдаёт 8 бит, это 0.28 м ступенек по высоте
	var raw := FileAccess.get_file_as_bytes("res://models/heightmap.f32")
	if raw.size() == res * res * 4 and res > 0:
		data.resize(res * res)
		for i in res * res:
			data[i] = raw.decode_float(i * 4)
	else:
		data = _heightmap_from_png(meta)
		if data.is_empty():
			return
	_hm = {
		"res": res, "data": data,
		"x0": meta.get("x0", 0.0), "z0": meta.get("z0", 0.0),
		"cell": meta.get("cell", 1.0),
	}


## Запасной путь: 8-битная карта высот из PNG (если нет heightmap.f32).
func _heightmap_from_png(meta: Dictionary) -> PackedFloat32Array:
	var tex := load("res://models/heightmap.png") as Texture2D
	if tex == null:
		return PackedFloat32Array()
	var img := tex.get_image()
	img.convert(Image.FORMAT_R8)
	var res: int = meta.get("res", img.get_width())
	var y_min: float = meta.get("y_min", 0.0)
	var y_max: float = meta.get("y_max", 1.0)
	var data := PackedFloat32Array()
	data.resize(res * res)
	for z in res:
		for x in res:
			data[z * res + x] = y_min + img.get_pixel(x, z).r * (y_max - y_min)
	return data
func alive_zombies() -> int:
	var n := 0
	for z in zombies:
		if is_instance_valid(z) and not z.dead:
			n += 1
	return n
