#!/usr/bin/env python3
# Dump textures from a Super Monkey Ball GC TPL (big-endian). Lists every
# texture's format/size and decodes RGBA32 (fmt 6), RGB5A3 (5), RGB565 (4),
# IA8 (3), I8 (1), I4 (0), IA4 (2) tiles to PNG.
#   usage: tpldump.py common_nl.tpl outdir [index]
import struct, sys, os
from PIL import Image


def be16(b, o): return struct.unpack_from('>H', b, o)[0]
def be32(b, o): return struct.unpack_from('>I', b, o)[0]


def rgb5a3(v):
    if v & 0x8000:
        a = 255
        r = ((v >> 10) & 0x1f) * 255 // 31
        g = ((v >> 5) & 0x1f) * 255 // 31
        b = (v & 0x1f) * 255 // 31
    else:
        a = ((v >> 12) & 7) * 255 // 7
        r = ((v >> 8) & 0xf) * 255 // 15
        g = ((v >> 4) & 0xf) * 255 // 15
        b = (v & 0xf) * 255 // 15
    return (r, g, b, a)


def decode(buf, off, w, h, fmt):
    px = [(0, 0, 0, 0)] * (w * h)
    def put(x, y, c):
        if x < w and y < h:
            px[y * w + x] = c
    p = off
    if fmt == 6:  # RGBA32: 4x4 tiles, 64 bytes each (AR x16, then GB x16)
        for ty in range(0, h, 4):
            for tx in range(0, w, 4):
                for i in range(16):
                    a = buf[p + i * 2]; r = buf[p + i * 2 + 1]
                    g = buf[p + 32 + i * 2]; b = buf[p + 32 + i * 2 + 1]
                    put(tx + i % 4, ty + i // 4, (r, g, b, a))
                p += 64
    elif fmt in (5, 4):  # RGB5A3 / RGB565: 4x4 tiles, 16-bit
        for ty in range(0, h, 4):
            for tx in range(0, w, 4):
                for i in range(16):
                    v = be16(buf, p); p += 2
                    if fmt == 5:
                        c = rgb5a3(v)
                    else:
                        c = (((v >> 11) & 0x1f) * 255 // 31,
                             ((v >> 5) & 0x3f) * 255 // 63,
                             (v & 0x1f) * 255 // 31, 255)
                    put(tx + i % 4, ty + i // 4, c)
    elif fmt == 3:  # IA8: 4x4 tiles
        for ty in range(0, h, 4):
            for tx in range(0, w, 4):
                for i in range(16):
                    a = buf[p]; ii = buf[p + 1]; p += 2
                    put(tx + i % 4, ty + i // 4, (ii, ii, ii, a))
    elif fmt == 1:  # I8: 8x4 tiles
        for ty in range(0, h, 4):
            for tx in range(0, w, 8):
                for i in range(32):
                    ii = buf[p]; p += 1
                    put(tx + i % 8, ty + i // 8, (ii, ii, ii, 255))
    else:
        return None
    im = Image.new('RGBA', (w, h))
    im.putdata(px)
    return im


with open(sys.argv[1], 'rb') as f:
    buf = f.read()
outdir = sys.argv[2]
os.makedirs(outdir, exist_ok=True)
only = int(sys.argv[3]) if len(sys.argv) > 3 else -1
count = be32(buf, 0)
print(f'{count} textures')
for i in range(count):
    e = 4 + i * 0x10
    fmt = be32(buf, e); off = be32(buf, e + 4)
    w = be16(buf, e + 8); h = be16(buf, e + 0xa)
    print(f'  tex[{i}] fmt={fmt} {w}x{h} off=0x{off:x}')
    if only >= 0 and i != only:
        continue
    if w and h:
        im = decode(buf, off, w, h, fmt)
        if im:
            im.save(os.path.join(outdir, f'tex{i:02d}_{w}x{h}_fmt{fmt}.png'))
