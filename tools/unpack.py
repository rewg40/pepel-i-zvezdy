"""Extract the split-archive GLBs stored in the repository.

The repository keeps large models as `name.zip` + `name.z01`, `.z02` ... (a plain
split zip).  `zipfile` refuses those because the central directory offsets are not
fixed up, so we walk the local file headers manually and inflate every entry.

usage:  python tools/unpack.py <dir with archives> <output dir>
"""
import os
import struct
import sys
import zlib

SIG_LOCAL = b'PK\x03\x04'


def split_entries(paths):
    """Concatenate a split zip and yield (name, is_deflate, data) for each entry."""
    blob = b''.join(open(p, 'rb').read() for p in paths)
    pos = 0
    while True:
        pos = blob.find(SIG_LOCAL, pos)
        if pos < 0:
            break
        (sig, ver, flags, method, mtime, mdate, crc, csize, usize,
         nlen, elen) = struct.unpack('<4s5H3I2H', blob[pos:pos + 30])
        name = blob[pos + 30:pos + 30 + nlen].decode('utf-8', 'replace')
        start = pos + 30 + nlen + elen
        if flags & 0x08:                      # sizes are in a trailing descriptor
            data = blob[start:]
        else:
            data = blob[start:start + csize]
        pos = start + (csize if not flags & 0x08 else 0)
        if name.endswith('/'):
            continue
        yield name, method, data


def unpack(directory, outdir):
    os.makedirs(outdir, exist_ok=True)
    archives = {}
    for f in sorted(os.listdir(directory)):
        low = f.lower()
        if low.endswith('.zip'):
            base = f[:-4]
            archives.setdefault(base, []).append(os.path.join(directory, f))
        elif low.endswith(('.z01', '.z02', '.z03')):
            base = f[:-4]
            archives.setdefault(base, []).append(os.path.join(directory, f))
    for base, paths in archives.items():
        paths = sorted(paths, key=lambda p: p[-3:])
        for name, method, data in split_entries(paths):
            if not name.lower().endswith('.glb'):
                continue
            raw = zlib.decompressobj(-15).decompress(data) if method == 8 else data
            out = os.path.join(outdir, os.path.basename(name))
            with open(out, 'wb') as fh:
                fh.write(raw)
            print(f'{base}: {name} -> {out} ({len(raw) / 1e6:.1f} MB)')


if __name__ == '__main__':
    unpack(sys.argv[1], sys.argv[2])
