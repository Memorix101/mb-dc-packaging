#!/usr/bin/env python3
# Convert a boot logo PNG into mb_data/bootlogo.raw for the release-build
# loading screen (boot_loading_screen in main.c).
#
# Format: [u16 width][u16 height] little-endian, then width*height u16
# ARGB1555 texels in linear order the same layout png2icon.py emits, but
# WITHOUT the power-of-two constraint: the logo is CPU-blitted straight
# into the RGB565 framebuffer, never uploaded as a PVR texture. Any size
# from 8x8 up to 640x480 works; larger inputs are scaled down to fit.
#
# The alpha channel is thresholded to the single ARGB1555 alpha bit
# (opaque at alpha >= 128). Transparent pixels leave the black screen
# background untouched, so a logo with soft edges should sit on a black
# canvas in the source PNG.
#
# Usage:
#   python3 tools/png2logo.py bootlogo.png mb_data/bootlogo.raw

import struct
import sys
from PIL import Image


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    img = Image.open(sys.argv[1]).convert('RGBA')
    w, h = img.size
    if w > 640 or h > 480:
        s = min(640.0 / w, 480.0 / h)
        w, h = max(8, int(w * s)), max(8, int(h * s))
        img = img.resize((w, h), Image.LANCZOS)
    if w < 8 or h < 8:
        print("logo too small (min 8x8): %dx%d" % (w, h))
        sys.exit(1)
    out = bytearray(struct.pack('<HH', w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            a1 = 1 if a >= 128 else 0
            texel = (a1 << 15) | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
            out += struct.pack('<H', texel)
    with open(sys.argv[2], 'wb') as f:
        f.write(out)
    print("wrote %s (%dx%d, %d bytes)" % (sys.argv[2], w, h, len(out)))


if __name__ == '__main__':
    main()
