"""Per-character animation sets and export settings."""
import rig as R

MEDIC = [
    ('Idle', R.idle, 2.0, True),
    ('Walk', R.walk, 1.0, True),
    ('Run', R.run, 0.7, True),
    ('Attack', R.attack, 1.0, False),
    ('Hit', R.hit, 0.45, False),
    ('Death', R.death, 1.2, False),
]

ZOMBIE = [
    ('Idle', R.zombie_idle, 2.5, True),
    ('Walk', R.zombie_walk, 1.2, True),
    ('WalkNoArms', lambda t: R.zombie_walk(t, arms=False), 1.2, True),
    ('Attack', R.zombie_attack, 1.0, False),
    ('Hit', R.hit, 0.45, False),
    ('Death', R.death, 1.2, False),
    ('Crawl', R.crawl, 1.2, True),
]

SETS = {'default': MEDIC, 'medic': MEDIC, 'zombie': ZOMBIE}

CONFIG = {
    'medic': {'name': 'Medic', 'scale': 1.0, 'texture': 2048},
    'zombie': {'name': 'Zombie', 'scale': 1.0, 'texture': 2048},
}
