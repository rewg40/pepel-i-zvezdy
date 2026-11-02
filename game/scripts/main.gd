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
	sky_mat.sky_top_color = Color(0.26, 0.37, 0.55)
	sky_mat.sky_horizon_color = Color(0.60, 0.63, 0.68)
	# нижняя полусфера неба — песочная: сквозь редкие дыры в меше острова
	# (децимация) видно именно её, и с тёмно-серым цветом они читались как
	# чёрные многоугольники посреди песка
	sky_mat.ground_bottom_color = Color(0.55, 0.47, 0.34)
	sky_mat.ground_horizon_color = Color(0.72, 0.66, 0.55)
	sky.sky_material = sky_mat
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.40
	env.fog_enabled = true
	env.fog_light_color = Color(0.62, 0.66, 0.72)
	env.fog_density = 0.0007
	# ACES не задирает средние тона: атлас острова сам по себе светлый (песок
	# ~0.8), с FILMIC + ambient 0.55 земля уходила в сплошной белый
	env.tonemap_mode = Environment.TONE_MAPPER_ACES
	env.tonemap_exposure = 0.85

	var world_env := WorldEnvironment.new()
	world_env.environment = env
	add_child(world_env)

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-42, -125, 0)
	sun.light_energy = 0.95
	sun.light_color = Color(1.0, 0.97, 0.92)
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 180.0
	add_child(sun)

	var fill := DirectionalLight3D.new()
	fill.rotation_degrees = Vector3(-18, 60, 0)
	fill.light_energy = 0.15
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
	_spawn_terrain()
	_raise_water()
	_make_heightmap_collision()


## Материалы острова. Земля рисуется родным атласом island.glb (4096²,
## ~5 м на тексель) через свой шейдер: атлас даёт настоящую раскладку биомов,
## а мелкое зерно detail возвращает фактуру вблизи (shaders/ground.gdshader).
## Растительность и островки раскрашены вершинными цветами — их надо включить,
## иначе они белые плоские треугольники.
const GROUND_SHADER := "res://shaders/ground.gdshader"
const GROUND_DETAIL := "res://models/ground_detail.png"

var _ground_mat: Material = null


func _fix_island_materials(island: Node) -> void:
	var atlas := _terrain_atlas(island)
	_ground_mat = _make_ground_material(atlas)
	var ground := 0
	var vcol := 0
	for mi in island.find_children("*", "MeshInstance3D", true, false):
		var mesh_instance := mi as MeshInstance3D
		if mesh_instance.mesh == null:
			continue
		# в меше острова есть наложенные слои поверхности на 10–40 м выше земли:
		# они отбрасывают на песок чёрные многоугольные тени. Тени острову не
		# нужны (свет ровный), а растительность и персонажи теньят как обычно.
		if String(mesh_instance.name).begins_with("node_"):
			mesh_instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		for surf in mesh_instance.mesh.get_surface_count():
			var mat := mesh_instance.get_active_material(surf)
			if not (mat is StandardMaterial3D):
				continue
			var std_mat := mat as StandardMaterial3D
			# вода и дно были почти чёрными (0.003 / 0.008) — сквозь дыры в
			# меше и на горизонте они читались как чёрные провалы, красим в
			# нормальные морские цвета
			if String(mat.resource_name) == "Ocean":
				var water: StandardMaterial3D = std_mat.duplicate()
				water.albedo_color = Color(0.10, 0.26, 0.38, 0.88)
				water.roughness = 0.12
				water.metallic_specular = 0.6
				mesh_instance.set_surface_override_material(surf, water)
				continue
			if String(mat.resource_name) == "Seafloor":
				var floor_mat: StandardMaterial3D = std_mat.duplicate()
				floor_mat.albedo_color = Color(0.26, 0.25, 0.20)
				mesh_instance.set_surface_override_material(surf, floor_mat)
				continue
			if std_mat.albedo_texture != null and _ground_mat != null:
				mesh_instance.set_surface_override_material(surf, _ground_mat)
				ground += 1
				continue
			var dup: StandardMaterial3D = std_mat.duplicate()
			dup.roughness = 1.0
			dup.metallic = 0.0
			dup.metallic_specular = 0.12
			dup.vertex_color_use_as_albedo = true
			dup.vertex_color_is_srgb = true
			mesh_instance.set_surface_override_material(surf, dup)
			vcol += 1
	print("остров: земля на атласе (", ground, " поверхностей), ",
		"растительность с вершинными цветами (", vcol, ")")


## Шейдер земли: родной атлас + мелкое зерно; UV считаются из мировой позиции.
func _make_ground_material(atlas: Texture2D) -> Material:
	if atlas == null or not ResourceLoader.exists(GROUND_SHADER):
		push_warning("нет " + GROUND_SHADER + " — земля на стандартном материале")
		return null
	var shader := load(GROUND_SHADER) as Shader
	if shader == null:
		return null
	var mat := ShaderMaterial.new()
	mat.shader = shader
	mat.set_shader_parameter("atlas", atlas)
	if ResourceLoader.exists(GROUND_DETAIL):
		mat.set_shader_parameter("detail", load(GROUND_DETAIL))
	return mat


## Атлас острова — текстура того материала, у которого она вообще есть.
func _terrain_atlas(island: Node) -> Texture2D:
	for mi in island.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		if m.mesh == null:
			continue
		for surf in m.mesh.get_surface_count():
			var candidate := m.get_active_material(surf)
			if candidate is StandardMaterial3D and (candidate as StandardMaterial3D).albedo_texture != null:
				return (candidate as StandardMaterial3D).albedo_texture
	return null


## UV земли аффинно связан с миром: u = x * UV_U_PER_M + UV_U_OFFSET,
## v = z * UV_V_PER_M + UV_V_OFFSET (коэффициенты сняты с island.glb).
const UV_U_PER_M := 5.0e-5
const UV_U_OFFSET := 0.499974
const UV_V_PER_M := 7.0e-5
const UV_V_OFFSET := 0.505151


## Терраин рисуется заново по высотам (tools/make_terrain.py →
## models/island_terrain.glb): у арены сетка 1 м по heightmap.f32 (она же
## коллизия), остальной остров — сетка 24 м по верхней огибающей меша.
## Исходный меш острова для этого не годится: децимация оставила дыры,
## наложенные слои и треугольники размером в километр.
const TERRAIN := "res://models/island_terrain.glb"
const TERRAIN_MESH_NAME := "node_0"


func _spawn_terrain() -> void:
	var island := get_node_or_null("Island")
	if island != null:
		# прячем исходный меш терраина (растительность и островки остаются)
		for mi in island.find_children("*", "MeshInstance3D", true, false):
			if String((mi as Node).name) == TERRAIN_MESH_NAME:
				(mi as MeshInstance3D).visible = false
	if not ResourceLoader.exists(TERRAIN):
		push_warning("нет " + TERRAIN + " — земля не нарисована")
		return
	var packed := load(TERRAIN) as PackedScene
	if packed == null:
		push_warning(TERRAIN + " не загрузился")
		return
	var terrain := packed.instantiate()
	terrain.name = "IslandTerrain"
	add_child(terrain)
	var n := 0
	for mi in terrain.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		if _ground_mat != null:
			m.material_override = _ground_mat
		m.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		n += 1
	print("терраин: ", n, " мешей по картам высот")


## Море и дно в исходной модели висят на y = 0, а остров — на ~1400 м,
## то есть «вода» оказывалась в 1.4 км ниже земли. Поднимаем её к острову.
const WATER_LEVEL := 1330.0


func _raise_water() -> void:
	var island := get_node_or_null("Island")
	if island == null:
		return
	for mi in island.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		if m.mesh == null:
			continue
		var mat := m.mesh.surface_get_material(0)
		var nm := "" if mat == null else String(mat.resource_name)
		if nm == "Ocean" or nm == "Seafloor":
			m.global_position.y += WATER_LEVEL
			m.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF


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
