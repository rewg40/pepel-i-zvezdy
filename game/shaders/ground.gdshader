shader_type spatial;
// shadows_disabled: у заплаток в дырах высоты восстановлены приблизительно, и
// карта теней рисует на них чёрную «шахматку» самозатенения
render_mode cull_disabled, diffuse_burley, shadows_disabled;

// Земля острова: родной атлас island.glb (4096², ~5 м на тексель) даёт
// настоящую раскладку биомов, а мелкая плитка detail возвращает зерно вблизи
// (иначе у ног игрока один тексель растянут на несколько метров).
// UV считаются из мировой позиции: у острова и у заплатки земли развёртка одна.

uniform sampler2D atlas : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
// detail — не цвет, а множитель, поэтому без source_color (не переводим в linear)
uniform sampler2D detail : filter_linear_mipmap_anisotropic, repeat_enable;

uniform vec2 atlas_u = vec2(0.00005, 0.499974);   // u = x * u.x + u.y
uniform vec2 atlas_v = vec2(0.00007, 0.505151);   // v = z * v.x + v.y
uniform float detail_scale = 0.11;                // ~1 повтор на 9 м
uniform float detail_strength = 0.45;

varying vec3 world_pos;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	vec2 atlas_uv = vec2(
		world_pos.x * atlas_u.x + atlas_u.y,
		world_pos.z * atlas_v.x + atlas_v.y);
	vec3 base = texture(atlas, atlas_uv).rgb;
	float grain = texture(detail, world_pos.xz * detail_scale).r;
	ALBEDO = base * mix(1.0, grain * 1.9, detail_strength);
	ROUGHNESS = 1.0;
	SPECULAR = 0.2;
}
