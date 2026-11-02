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
