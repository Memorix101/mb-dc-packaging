#!/usr/bin/env python3
# Convert a single PNG into a PVR VQ texture blob for /cd/mb_data (the
# pause-menu How-to-play controller diagram, src/howto.c).
#
# Output: [u16 width][u16 height] little-endian, then the PVR VQ layout the
# runtime draws as is: 2048-byte codebook (256 entries of 2x2 ARGB1555 texels,
# order TL,BL,TR,BR) followed by one index byte per 2x2 block in twiddle
# order (no mip chain). Size for 256x256: 4 + 2048 + 16384 bytes.
#
# The codebook is k-means fitted (vqenc.py), which keeps the few coloured
# pixels of a mostly white/grey line-art image; the game's runtime encoder
# spaces its codebook over brightness only and turned the pad's coloured
# buttons grey. Alpha is thresholded to the ARGB1555 bit (>= 128 opaque).
#
# The image is resized to a square power of two, at most 256 (VRAM: the
# in-game pool has a few dozen KB; 256x256 VQ is 18 KB).
#
# Usage:
#   python3 tools/png2vq.py custom_assets/dc_controller.png mb_data/dc_controller.vq

import os
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vqenc  # noqa: E402  (k-means VQ, ARGB1555 helpers)

MAX_DIM = 256


def pot(n):
    p = 8
    while p < n and p < MAX_DIM:
        p *= 2
    return p


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    img = Image.open(sys.argv[1]).convert('RGBA')
    d = pot(max(img.width, img.height))
    if (d, d) != img.size:
        img = img.resize((d, d), Image.LANCZOS)
    tex16 = vqenc.to_argb1555(np.asarray(img, dtype=np.uint8))
    blob = vqenc.kmeans_vq(tex16, d, d)          # codebook + mip chain
    k = d.bit_length() - 1
    nb = (d * d) // 4
    base = 2048 + vqenc.VQ_MIP_OFS[k]
    out = struct.pack('<HH', d, d) + blob[:2048] + blob[base:base + nb]
    with open(sys.argv[2], 'wb') as f:
        f.write(out)
    print("wrote %s (%dx%d VQ, %d bytes)" % (sys.argv[2], d, d, len(out)))


if __name__ == '__main__':
    main()
