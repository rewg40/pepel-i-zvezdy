"""Tiny glTF/GLB writer."""
import json
import struct

import numpy as np

ACC = {np.dtype('float32'): (5126, 'f'), np.dtype('uint32'): (5125, 'I'),
       np.dtype('uint16'): (5123, 'H'), np.dtype('uint8'): (5121, 'B'),
       np.dtype('int16'): (5122, 'h'), np.dtype('float64'): (5126, 'f')}
TYPEN = {1: 'SCALAR', 2: 'VEC2', 3: 'VEC3', 4: 'VEC4', 16: 'MAT4'}


class GLB:
    def __init__(self, name='scene'):
        self.bin = bytearray()
        self.g = {
            'asset': {'version': '2.0', 'generator': 'pepel-i-zvezdy asset builder'},
            'scene': 0,
            'scenes': [{'name': name, 'nodes': []}],
            'nodes': [], 'meshes': [], 'materials': [], 'accessors': [],
            'bufferViews': [], 'images': [], 'textures': [], 'samplers': [],
            'skins': [], 'animations': [],
        }

    # ---------------- low level
    def _align(self):
        while len(self.bin) % 4:
            self.bin.append(0)

    def buffer_view(self, data, target=None):
        self._align()
        off = len(self.bin)
        self.bin.extend(data)
        bv = {'buffer': 0, 'byteOffset': off, 'byteLength': len(data)}
        if target:
            bv['target'] = target
        self.g['bufferViews'].append(bv)
        return len(self.g['bufferViews']) - 1

    def accessor(self, arr, target=None, ttype=None):
        arr = np.ascontiguousarray(arr)
        if arr.dtype not in ACC:
            arr = arr.astype(np.float32)
        ct, _ = ACC[arr.dtype]
        n = arr.shape[0]
        ncomp = 1 if arr.ndim == 1 else arr.shape[1]
        bv = self.buffer_view(arr.tobytes(), target)
        a = {'bufferView': bv, 'componentType': ct, 'count': int(n),
             'type': ttype or TYPEN[ncomp]}
        if arr.dtype == np.float32:
            flat = arr.reshape(n, -1)
            a['min'] = [float(x) for x in flat.min(axis=0)]
            a['max'] = [float(x) for x in flat.max(axis=0)]
        self.g['accessors'].append(a)
        return len(self.g['accessors']) - 1

    # ---------------- resources
    def image(self, data, name='tex', mime='image/jpeg'):
        bv = self.buffer_view(data)
        self.g['images'].append({'bufferView': bv, 'mimeType': mime, 'name': name})
        return len(self.g['images']) - 1

    def sampler(self, wrap=10497):
        self.g['samplers'].append({'magFilter': 9729, 'minFilter': 9987,
                                   'wrapS': wrap, 'wrapT': wrap})
        return len(self.g['samplers']) - 1

    def texture(self, image_idx, sampler_idx=None):
        t = {'source': image_idx}
        if sampler_idx is not None:
            t['sampler'] = sampler_idx
        self.g['textures'].append(t)
        return len(self.g['textures']) - 1

    def material(self, name='M', base_color=None, base_tex=None, normal_tex=None,
                 metallic=0.0, roughness=0.9, double_sided=True, emissive=None,
                 alpha_blend=False, alpha_cutoff=None):
        m = {'name': name, 'doubleSided': double_sided,
             'pbrMetallicRoughness': {'metallicFactor': metallic,
                                      'roughnessFactor': roughness}}
        if base_color is not None:
            m['pbrMetallicRoughness']['baseColorFactor'] = list(base_color)
        if base_tex is not None:
            m['pbrMetallicRoughness']['baseColorTexture'] = {'index': base_tex}
        if normal_tex is not None:
            m['normalTexture'] = {'index': normal_tex}
        if emissive is not None:
            m['emissiveFactor'] = list(emissive)
        if alpha_blend:
            m['alphaMode'] = 'BLEND'
        if alpha_cutoff is not None:
            m['alphaMode'] = 'MASK'
            m['alphaCutoff'] = float(alpha_cutoff)
        self.g['materials'].append(m)
        return len(self.g['materials']) - 1

    def mesh(self, name, prims):
        out = []
        for p in prims:
            attrs = {}
            for k, v in p['attributes'].items():
                attrs[k] = self.accessor(v, 34962)
            prim = {'attributes': attrs}
            if p.get('indices') is not None:
                prim['indices'] = self.accessor(p['indices'].astype(np.uint32),
                                                target=34963, ttype='SCALAR')
            if p.get('material') is not None:
                prim['material'] = p['material']
            out.append(prim)
        self.g['meshes'].append({'name': name, 'primitives': out})
        return len(self.g['meshes']) - 1

    def node(self, name, mesh=None, skin=None, translation=None, rotation=None,
             scale=None, children=None, extras=None):
        n = {'name': name}
        if mesh is not None:
            n['mesh'] = mesh
        if skin is not None:
            n['skin'] = skin
        if translation is not None:
            n['translation'] = [float(x) for x in translation]
        if rotation is not None:
            n['rotation'] = [float(x) for x in rotation]
        if scale is not None:
            n['scale'] = [float(x) for x in scale]
        if children:
            n['children'] = [int(c) for c in children]
        if extras:
            n['extras'] = extras
        self.g['nodes'].append(n)
        return len(self.g['nodes']) - 1

    def write(self, path):
        self.g['buffers'] = [{'byteLength': len(self.bin)}]
        js = json.dumps(self.g, separators=(',', ':')).encode()
        while len(js) % 4:
            js += b' '
        b = bytearray()
        b += struct.pack('<III', len(self.bin) + len(js) + 20, 0x4E4F534A, 2)
        b += struct.pack('<II', len(b'glTF'), 0x46546C67)
        b = bytearray(struct.pack('<4sII', b'glTF', 2, 20 + len(js) + len(self.bin)))
        b += struct.pack('<II', len(js), 0x4E4F534A) + js
        b += struct.pack('<II', len(self.bin), 0x004E4942) + bytes(self.bin)
        with open(path, 'wb') as fh:
            fh.write(b)
        return len(b)
