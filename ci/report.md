# Проверка движком

Godot: `4.3.stable.official.77dcf97d8`

## Разбор скриптов (`--check-only`)
```
ok   res://scripts/hud.gd
ok   res://scripts/main.gd
ok   res://scripts/player.gd
ok   res://scripts/zombie.gd
ok   res://tests/check.gd
ok   res://tests/shots.gd
```
## Импорт проекта
```
WARNING: Ignoring face with non-finite normal in LOD generation.
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
остров: земля на атласе (1 поверхностей), растительность с вершинными цветами (57)
заплатки земли: 1 мешей
PASS  medic.glb: «MxWalk» двигает кисть на 17.5 см
  бёдра в мировых координатах: (0.022071, 0.483637, -0.006296)
PASS  zombie.glb: «MxWalk» двигает кисть на 12.9 см
  бёдра в мировых координатах: (-0.00594, 0.446332, -0.005806)
PASS  игроков: 1
PASS  зомби: 3
PASS  остров на сцене: узлов-мешей 60
PASS  остров: земля на родном атласе 4096px
PASS  остров: земля на шейдере ground.gdshader
PASS  шейдер земли получает атлас
PASS  шейдер земли получает зерно
PASS  заплатки земли в дырах острова: треугольников 111152
PASS  заплатки рисуются шейдером земли (атлас + зерно)
PASS  карта высот загружена в float32 (высота в метрах)
PASS  высота арены из карты (1405.00) совпадает с arena.json (1405.00)
PASS  игрок: скелет и AnimationPlayer
PASS  игрок играет клип «MxIdle»
PASS  меч прицеплен к кисти
PASS  игрок бьёт клипом MxAttack
PASS  длительность удара = длине клипа (2.40 / 2.40 с)
PASS  момент попадания внутри клипа (1.32 с)
PASS  зомби: тело 1000 HP (1000)
PASS  зомби: рука 3 HP
PASS  зомби: arm_l отрублена после 3 ударов
PASS  зомби: leg_l отрублена после 3 ударов
PASS  зомби: leg_r отрублена после 3 ударов
PASS  зомби: без двух ног состояние «crawl»
PASS  зомби: клип без рук найден (WalkNoArms)
PASS  зомби: играет «MxCrawl»
PASS  куски конечностей на земле: 3
PASS  куски не наследуют красную вспышку удара
PASS  зомби: тело держит удар (осталось 966 HP)
ERROR: Parameter "m" is null.
   at: mesh_get_surface_count (servers/rendering/dummy/storage/mesh_storage.h:120)

=== итог: 85 проверок, 0 провалов
WARNING: ObjectDB instances leaked at exit (run with --verbose for details).
     at: cleanup (core/object/object.cpp:2284)
exit=0
```
## Скриншоты из движка (llvmpipe / OpenGL 3)

![](ci/shots/01_player.png)
![](ci/shots/02_arena.png)
![](ci/shots/03_zombie.png)
![](ci/shots/04_crawl.png)
![](ci/shots/05_debris.png)
![](ci/shots/06_terrain_only.png)
![](ci/shots/07_water_only.png)
![](ci/shots/08_only_fill.png)
![](ci/shots/08_only_islet.png)
![](ci/shots/08_only_ocean.png)
![](ci/shots/08_only_seafloor.png)
![](ci/shots/08_only_vegetation.png)
![](ci/shots/09_terrain_no_fill.png)
```
WARNING: All audio drivers failed, falling back to the dummy driver.
     at: initialize (servers/audio_server.cpp:247)

остров: земля на атласе (1 поверхностей), растительность с вершинными цветами (57)
заплатки земли: 1 мешей
внешние клипы: +7 из res://models/medic_clips.glb
внешние клипы: +7 из res://models/zombie_clips.glb
shot 01_player (800, 450) -> /tmp/shots/01_player.png err=0
shot 02_arena (800, 450) -> /tmp/shots/02_arena.png err=0
shot 03_zombie (800, 450) -> /tmp/shots/03_zombie.png err=0
зомби-ползун: body y=1405.20 model y=0.00 lowest bone=Hand_R y=1405.58 lowest mesh y=1404.54 on_floor=true
игрок y=1404.20 pos=(1309.365, 1404.197, -69.25084), камера=(1311.558, 1407.285, -77.75944)
shot 04_crawl (800, 450) -> /tmp/shots/04_crawl.png err=0
shot 05_debris (800, 450) -> /tmp/shots/05_debris.png err=0
shot 08_only_ocean (800, 450) -> /tmp/shots/08_only_ocean.png err=0
shot 08_only_seafloor (800, 450) -> /tmp/shots/08_only_seafloor.png err=0
shot 08_only_islet (800, 450) -> /tmp/shots/08_only_islet.png err=0
shot 08_only_vegetation (800, 450) -> /tmp/shots/08_only_vegetation.png err=0
shot 08_only_fill (800, 450) -> /tmp/shots/08_only_fill.png err=0
материалы острова: { "Island": 1, "Ocean": 1, "Seafloor": 1, "Islet": 37, "Vegetation": 20 }
shot 06_terrain_only (800, 450) -> /tmp/shots/06_terrain_only.png err=0
shot 09_terrain_no_fill (800, 450) -> /tmp/shots/09_terrain_no_fill.png err=0
shot 07_water_only (800, 450) -> /tmp/shots/07_water_only.png err=0
готово
exit=0
```
