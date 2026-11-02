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
| `build_sword.py` | нормализация меча |
| `render.py` / `check_glb.py` / `filmstrip.py` | офлайн-проверка: скиннинг, кадры анимаций |
| `inspect_glb.py` | структура GLB (узлы, меши, анимации) |
| `retarget.py` | чужие клипы (Mixamo / Quaternius / любой humanoid GLB) → наши кости |
| `selftest_retarget.py` | круговой тест ретаргета: наш клип → чужой риг → обратно |

## Внешние анимации (ретаргет)

Клипы не обязаны быть «своими»: `tools/retarget.py` перепекает любой humanoid-GLB
(Mixamo, Quaternius Universal Animation Library, KayKit…) на **наш** скелет, так
что в Godot не нужны ни BoneMap, ни SkeletonProfile — это обычные glTF-анимации
с нашими именами костей.

```bash
# 1. FBX из Mixamo -> GLB (Blender: File > Export > glTF, без меша достаточно
#    "Selected Objects" = арматура + Action)
# 2. перепечь на нужного персонажа
/tmp/venv/bin/python tools/retarget.py clips/*.glb game/models/zombie.glb \
    game/models/zombie_clips.glb
```

Полезные ключи:

| ключ | зачем |
|---|---|
| `--list` | показать, какая кость источника легла на какую нашу (ничего не пишет) |
| `--map Spine=Spine1` | поправить маппинг вручную, если имена незнакомые |
| `--clips Walk,Run` | оставить только нужные клипы |
| `--strip-xz` | убрать горизонтальное движение бёдер (клип «на месте») |
| `--ground` | приподнять/опустить клип так, чтобы нижняя точка бёдер была на уровне rest |
| `--fps 30` | частота пересэмплирования |
| `--no-probe` | не добавлять служебный квад (без него Godot не создаст Skeleton3D) |

На выходе — файл с rest-скелетом персонажа, кожей и анимациями; имя узла
арматуры совпадает с персонажем (`Medic_Rig` / `Zombie_Rig`), поэтому track-пути
(`Skeleton3D:<bone>`) в Godot такие же, как у родных клипов. `player.gd` и
`zombie.gd` подхватывают файл автоматически, если он лежит по пути из
`extra_clips` (`res://models/medic_clips.glb`, `res://models/zombie_clips.glb`):
клипы вливаются в default-библиотеку `AnimationPlayer` и не перекрывают родные.

Проверка математики без Godot:

```bash
/tmp/venv/bin/python tools/selftest_retarget.py
```
