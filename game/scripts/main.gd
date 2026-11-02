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
	env.fog_light_color = Color(0.72, 0.70, 0.66)
	env.fog_density = 0.0016
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
	_make_heightmap_collision()


## Остров собран из одного меша на 20×20 км с UV 0..1 на всю карту: у арены
## остаётся 8 вершин на 120 м, и текстура растягивается в ровное пятно.
## Поэтому включаем тайлинг материала — детализация возвращается.
func _fix_island_materials(island: Node) -> void:
	var n := 0
	for mi in island.find_children("*", "MeshInstance3D", true, false):
		var mesh_instance := mi as MeshInstance3D
		var count := mesh_instance.mesh.get_surface_count() if mesh_instance.mesh else 0
		for surf in count:
			var mat := mesh_instance.get_active_material(surf)
			if not (mat is StandardMaterial3D):
				continue
			if mat.albedo_texture == null:
				continue          # вода и морское дно — однотонные
			var dup: StandardMaterial3D = mat.duplicate()
			dup.uv1_scale = Vector3(120.0, 120.0, 1.0)
			dup.texture_repeat = true
			mesh_instance.set_surface_override_material(surf, dup)
			n += 1
	if n > 0:
		print("остров: тайлинг текстуры включён для ", n, " поверхностей")


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
	var tex := load("res://models/heightmap.png") as Texture2D
	if tex == null:
		return
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
	_hm = {
		"res": res, "data": data,
		"x0": meta.get("x0", 0.0), "z0": meta.get("z0", 0.0),
		"cell": meta.get("cell", 1.0),
	}


func alive_zombies() -> int:
	var n := 0
	for z in zombies:
		if is_instance_valid(z) and not z.dead:
			n += 1
	return n
