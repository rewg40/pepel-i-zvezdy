"""Print the structure of a GLB (nodes, meshes, materials, skins, animations)."""
import json
import struct
import sys


def load(path):
    b = open(path, 'rb').read()
    ln = struct.unpack('<I', b[12:16])[0]
    js = json.loads(b[20:20 + ln])
    off = 20 + ln
    off += (4 - off % 4) % 4
    blen = struct.unpack('<I', b[off:off + 4])[0]
    return js, b[off + 8:off + 8 + blen]


if __name__ == '__main__':
    for p in sys.argv[1:]:
        js, _ = load(p)
        print('==', p)
        print(' nodes', len(js['nodes']), 'meshes', len(js['meshes']), 'mats', len(js['materials']),
              'imgs', len(js.get('images', [])), 'skins', len(js.get('skins', [])),
              'anims', len(js.get('animations', [])))
        for i, n in enumerate(js['nodes'][:10]):
            print('  node', i, n.get('name'), 'mesh' in n, 'skin' in n,
                  {k: v for k, v in n.items() if k in ('translation', 'rotation', 'scale')})
        for i, m in enumerate(js['meshes']):
            pr = m['primitives'][0]
            print('  mesh', i, m.get('name'), 'prims', len(m['primitives']),
                  'verts', js['accessors'][pr['attributes']['POSITION']]['count'],
                  list(pr['attributes']), 'mat', pr.get('material'))
        print('  anims', [a.get('name') for a in js.get('animations', [])])
        for i, m in enumerate(js['materials']):
            print('  mat', i, m.get('name'), list(m.get('pbrMetallicRoughness', {}).keys()))
        print('  scene nodes', js['scenes'][0]['nodes'])
