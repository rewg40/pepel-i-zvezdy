# Проверка движком

Godot: `4.3.stable.official.77dcf97d8`

## Импорт проекта
```
WARNING: Ignoring face with non-finite normal in LOD generation.
SCRIPT ERROR: Parse Error: The variable type is being inferred from a Variant value, so it will be typed as Variant. (Warning treated as error.)
ERROR: Failed to load script "res://scripts/hud.gd" with error "Parse error".
```
## tests/check.gd
```
Godot Engine v4.3.stable.official.77dcf97d8 - https://godotengine.org

=== Godot 4.3-stable (official) / Linux

=== res://models/medic.glb
PASS  res://models/medic.glb: Skeleton3D создан
PASS  res://models/medic.glb: AnimationPlayer создан
  костей: 20
  Root, Hips, Spine, Chest, Neck, Head, Shoulder_L, UpperArm_L, LowerArm_L, Hand_L, Shoulder_R, UpperArm_R, LowerArm_R, Hand_R, Thigh_L, Shin_L, Foot_L, Thigh_R, Shin_R, Foot_R
PASS  medic.glb: кость Hips
PASS  medic.glb: кость Spine
PASS  medic.glb: кость Chest
PASS  medic.glb: кость Head
PASS  medic.glb: кость UpperArm_L
PASS  medic.glb: кость LowerArm_R
PASS  medic.glb: кость Thigh_L
PASS  medic.glb: кость Shin_R
PASS  medic.glb: кость Foot_L
PASS  medic.glb: кость Hand_R
  родные клипы: ["Attack", "Death", "Hit", "Idle", "Run", "Walk"]
PASS  medic.glb: родных клипов 6
  внешних клипов добавлено: 7
PASS  medic.glb: клипы из medic_clips.glb подмешаны
PASS  medic.glb «Attack»: 18 дорожек, битых 0, длина 1.00 с
PASS  medic.glb «Death»: 18 дорожек, битых 0, длина 1.20 с
PASS  medic.glb «Hit»: 18 дорожек, битых 0, длина 0.47 с
PASS  medic.glb «Idle»: 18 дорожек, битых 0, длина 2.00 с
PASS  medic.glb «MxAttack»: 21 дорожек, битых 0, длина 2.40 с
PASS  medic.glb «MxDeath»: 21 дорожек, битых 0, длина 3.43 с
PASS  medic.glb «MxHit»: 21 дорожек, битых 0, длина 2.27 с
PASS  medic.glb «MxIdle»: 21 дорожек, битых 0, длина 9.93 с
PASS  medic.glb «MxRun»: 21 дорожек, битых 0, длина 0.63 с
PASS  medic.glb «MxSlash»: 21 дорожек, битых 0, длина 1.82 с
PASS  medic.glb «MxWalk»: 21 дорожек, битых 0, длина 1.40 с
PASS  medic.glb «Run»: 18 дорожек, битых 0, длина 0.70 с
PASS  medic.glb «Walk»: 18 дорожек, битых 0, длина 1.00 с

=== res://models/zombie.glb
PASS  res://models/zombie.glb: Skeleton3D создан
PASS  res://models/zombie.glb: AnimationPlayer создан
  костей: 20
  Root, Hips, Spine, Chest, Neck, Head, Shoulder_L, UpperArm_L, LowerArm_L, Hand_L, Shoulder_R, UpperArm_R, LowerArm_R, Hand_R, Thigh_L, Shin_L, Foot_L, Thigh_R, Shin_R, Foot_R
PASS  zombie.glb: кость Hips
PASS  zombie.glb: кость Spine
PASS  zombie.glb: кость Chest
PASS  zombie.glb: кость Head
PASS  zombie.glb: кость UpperArm_L
PASS  zombie.glb: кость LowerArm_R
PASS  zombie.glb: кость Thigh_L
PASS  zombie.glb: кость Shin_R
PASS  zombie.glb: кость Foot_L
PASS  zombie.glb: кость Hand_R
  родные клипы: ["Attack", "Crawl", "Death", "Hit", "Idle", "Walk", "WalkNoArms"]
PASS  zombie.glb: родных клипов 7
  внешних клипов добавлено: 7
PASS  zombie.glb: клипы из zombie_clips.glb подмешаны
PASS  zombie.glb «Attack»: 22 дорожек, битых 0, длина 1.00 с
PASS  zombie.glb «Crawl»: 22 дорожек, битых 0, длина 1.20 с
PASS  zombie.glb «Death»: 22 дорожек, битых 0, длина 1.20 с
PASS  zombie.glb «Hit»: 22 дорожек, битых 0, длина 0.47 с
PASS  zombie.glb «Idle»: 22 дорожек, битых 0, длина 2.50 с
PASS  zombie.glb «MxAttack»: 21 дорожек, битых 0, длина 2.40 с
PASS  zombie.glb «MxCrawl»: 21 дорожек, битых 0, длина 1.80 с
PASS  zombie.glb «MxDeath»: 21 дорожек, битых 0, длина 3.43 с
PASS  zombie.glb «MxHit»: 21 дорожек, битых 0, длина 2.27 с
PASS  zombie.glb «MxIdle»: 21 дорожек, битых 0, длина 9.93 с
PASS  zombie.glb «MxRun»: 21 дорожек, битых 0, длина 0.63 с
PASS  zombie.glb «MxWalk»: 21 дорожек, битых 0, длина 1.40 с
PASS  zombie.glb «Walk»: 22 дорожек, битых 0, длина 1.20 с
PASS  zombie.glb «WalkNoArms»: 22 дорожек, битых 0, длина 1.20 с

=== главная сцена
SCRIPT ERROR: Parse Error: The variable type is being inferred from a Variant value, so it will be typed as Variant. (Warning treated as error.)
          at: GDScript::reload (res://scripts/hud.gd:54)
ERROR: Failed to load script "res://scripts/hud.gd" with error "Parse error".
   at: load (modules/gdscript/gdscript.cpp:2936)
SCRIPT ERROR: Invalid call. Nonexistent function 'setup' in base 'CanvasLayer'.
          at: _ready (res://scripts/main.gd:31)
PASS  medic.glb: «MxWalk» двигает кисть на 17.5 см
  бёдра в мировых координатах: (0.022071, 0.483637, -0.006296)
PASS  zombie.glb: «MxWalk» двигает кисть на 12.9 см
  бёдра в мировых координатах: (-0.00594, 0.446332, -0.005806)
PASS  игроков: 1
PASS  зомби: 3
FAIL  остров на сцене
PASS  игрок: скелет и AnimationPlayer
PASS  игрок играет клип «MxIdle»
PASS  меч прицеплен к кисти
PASS  зомби: тело 1000 HP (1000)
PASS  зомби: рука 3 HP
SCRIPT ERROR: Invalid call. Nonexistent function 'get_bone_length' in base 'Skeleton3D'.
          at: _run (res://tests/check.gd:161)
exit=124
```
