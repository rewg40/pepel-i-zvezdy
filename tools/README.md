# Пайплайн сборки игровых ассетов

Всё, что лежит в `game/models/`, получено этими скриптами из моделей репозитория
(`остров/`, `зомби/`, `персонаж/`, `предмет/`). Нужен Python 3.10+:

```
python -m venv /tmp/venv
/tmp/venv/bin/pip install numpy scipy pillow trimesh fast-simplification gdtoolkit
```

## Шаги

```bash
# 1. распаковать разрезанные архивы (.z01/.z02/.zip) в /tmp/models
python tools/unpack.py зомби      /tmp/models
python tools/unpack.py персонаж   /tmp/models
python tools/unpack.py остров     /tmp/models
# (файлы переименовать в /tmp/models/{zombie,medic,island}.glb,
#  меч скопировать как /tmp/models/sword.glb)

# 2. персонажи: сварка -> UV-чарты -> децимация -> /tmp/work/*_mesh.npz + атлас
python tools/prep_mesh.py medic  /tmp/work/medic_mesh.npz  150000
python tools/prep_mesh.py zombie /tmp/work/zombie_mesh.npz 150000

# 3. скелет + скин + анимации + культи + куски -> game/models/*.glb
python tools/build_char.py medic  game/models/medic.glb
python tools/build_char.py zombie game/models/zombie.glb

# 4. карта, карта высот, точка арены
python tools/build_island.py /tmp/models/island.glb

# 5. меч: метры, рукоять в нуле
python tools/build_sword.py game/models/sword.glb
```

## Модули

| файл | что делает |
|---|---|
| `unpack.py` | ручной разбор split-zip архивов (обычные `.z01/.z02` + `.zip`) |
| `glb_io.py` / `glbw.py` | чтение и запись GLB |
| `mesh_ops.py` | сварка вершин, поиск UV-чартов, децимация внутри чартов |
| `prep_mesh.py` | загрузка модели → рендер-готовый меш с исходным атласом |
| `skeleton.py` | шаблон скелета, автоподгонка по геометрии, веса скина |
| `rig.py` | кости/матрицы, позы (idle, walk, run, attack, hit, death, crawl…) |
| `build_char.py` | сборка GLB персонажа: 6 частей, культи, копии деталей, анимации |
| `build_island.py` | децимация острова + heightmap + выбор арены |
| `make_terrain.py` | терраин игры из ИСХОДНОГО меша: 1 м у арены (та же карта идёт в коллизию) + 24 м по острову → `game/models/island_terrain.glb` |
| `make_ground_mottle.py` | бежевые разводы из родного атласа (повтор ~320 м) → `game/models/ground_mottle.png` |
| `make_ground_detail.py` | мелкое зерно-множитель из атласа (повтор ~9 м) → `game/models/ground_detail.png` |
| `make_island_fill.py` / `hide_plateau.py` / `fix_terrain_normals.py` / `rebake_heightmap.py` | старые шаги заплаток в децимированном меше; после перехода на `make_terrain.py` не нужны |
| `build_sword.py` | нормализация меча |
| `render.py` / `check_glb.py` / `filmstrip.py` | офлайн-проверка: скиннинг, кадры анимаций |
| `inspect_glb.py` | структура GLB (узлы, меши, анимации) |
| `retarget.py` | чужие клипы (Mixamo / Quaternius / любой humanoid GLB) → наши кости |
| `selftest_retarget.py` | круговой тест ретаргета: наш клип → чужой риг → обратно |
| `fbx2glb.js` | FBX → GLB через assimp/wasm (`node`), нужен только для `.fbx`-клипов |

## Внешние анимации (ретаргет)

Клипы не обязаны быть «своими»: `tools/retarget.py` перепекает любой humanoid-клип
(Mixamo, Quaternius Universal Animation Library, KayKit, UE…) на **наш** скелет,
так что в Godot не нужны ни BoneMap, ни SkeletonProfile — это обычные glTF-анимации
с нашими именами костей.

```bash
# FBX и GLB можно мешать; папки тоже принимаются
/tmp/venv/bin/python tools/retarget.py clips/ game/models/zombie.glb \
    game/models/zombie_clips.glb --prefix Mx \
    --rename walking=Walk --rename crawling=Crawl
```

FBX конвертируется сам, через `tools/fbx2glb.js` (assimp в WebAssembly, Blender не
нужен; требуется `node` и `npm install assimpjs` в корне репозитория).

| ключ | зачем |
|---|---|
| `--list` | показать, какая кость источника легла на какую нашу (ничего не пишет) |
| `--map Spine=Spine1` | поправить маппинг вручную, если имена незнакомые |
| `--clips Walk,Run` | оставить только нужные клипы |
| `--prefix Mx` | префикс ко всем именам (`MxWalk`), чтобы не перекрывать родные клипы |
| `--rename walking=Walk` | переименовать клип (или файл), удобно для `mixamo.com` и `Ch31_nonPBR@Running` |
| `--ref auto\|bind\|first\|mean` | опорная поза ретаргета (см. ниже), по умолчанию `auto` |
| `--mode aim\|rot` | `aim` — переносить направления костей (дефолт), `rot` — полные мировые повороты |
| `--strip-xz` | убрать горизонтальное движение бёдер (клип «на месте») |
| `--ground` | приподнять/опустить клип так, чтобы нижняя точка бёдер была на уровне rest |
| `--fps 30` | частота пересэмплирования |
| `--no-probe` | не добавлять служебный квад (без него Godot не создаст Skeleton3D) |

### Почему `--ref` важен

Ретаргет переносит «насколько кость ушла от опорной позы». Опорой может быть
bind-поза файла или сама анимация:

* Mixamo биндит скелет в **T-позе**, а наши персонажи стоят с опущенными руками.
  Если взять bind, руки в каждом клипе уезжают вниз на ~70° — персонаж идёт
  сгорбившись и с руками за спиной;
* `--ref mean` (усреднённая поза клипа) и `--ref first` (первый кадр) решают это:
  наш rest выравнивается по нейтральной стойке клипа, и ноги сгибаются в коленях
  так же глубоко, как в оригинале;
* `auto` считает оба варианта и берёт тот, где наш rest ближе к нейтрали клипа
  (для Mixamo это всегда `mean`, для Quaternius/KayKit — часто `bind`).

`--mode aim` переносит направления костей (бедро→колено, плечо→локоть), листья
(кисти, стопы) и бёдра — полными поворотами. Это устойчиво к разной длине
конечностей и к разной bind-позе.

### Где брать клипы

* **Mixamo** (mixamo.com) — ~2500 клипов, скачиваются как FBX for Unity / FBX
  Binary, «Without Skin» — как раз то, что нужно. Сеть песочницы до mixamo.com не
  достаёт, но файлы прекрасно лежат в открытых репозиториях на GitHub — их и
  использовали для сборки `game/models/*_clips.glb`:
  `Walking`, `Running`, `Breathing Idle`, `Crawling`, `Great Sword Slash`,
  `Standing Melee Attack Horizontal`, `Hit Reaction`, `Death From The Front`.
* **Quaternius Universal Animation Library 1/2** — 120+/130+ клипов, CC0, один
  humanoid-риг, GLB/FBX/Blend.
* **KayKit / Kenney** — CC0; **Microsoft Rocketbox** — FBX, читать условия.

### Проверка без Godot

```bash
/tmp/venv/bin/python tools/selftest_retarget.py
```

Тест печёт наш клип в «чужой» риг (mixamo-имена, другие rest-ориентации, лишняя
кость) и ретаргетит обратно: ошибка 0 и по кватернионам, и по бёдрам, и по
матрицам из записанного файла. Плюс живой прогон на реальном клипе:

```bash
/tmp/venv/bin/python tools/retarget.py /tmp/mx/walking.fbx \
    game/models/medic.glb /tmp/w.glb
# кадры: game/preview/mixamo_medic.png, game/preview/mixamo_zombie.png
```

### Что пришлось учесть (грабли)

* assimp-конвертация FBX вставляет узлы
  `<кость>_$AssimpFbx$_Translation/_PreRotation/_Rotation` и пишет канал FBX
  (в котором уже есть joint orient) прямо на кость — pre-rotation применяется
  дважды, и конечности выворачиваются на 180°. `fix_assimp_tracks()` снимает
  эти хелперы с трека (порядок умножения — от родителя к ребёнку).
* В таких файлах есть анимированный объект-арматура с масштабом 100 (единицы
  FBX). Всё, что выше верхней смаппленной кости, считается движением объекта и
  отбрасывается, а масштаб не учитывается при чтении скелета.
* Корень Mixamo (`mixamorig:Hips`) — это наши `Root`+`Hips` одновременно;
  отдельной кости `Root` в клипе нет, поэтому позиция берётся из бёдер.
