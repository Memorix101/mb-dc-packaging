#!/usr/bin/env python3
# Convert a HUD icon PNG (made in Photoshop, with a real alpha channel) into
# the DC-ready icon texture ".raw" for /cd/mb_data.
#
# Format: [u16 width][u16 height] little-endian, then width*height u16
# ARGB1555 texels (linear order; the game twiddles at upload). This matches
# render_hud_sprite (PVR_TXRFMT_ARGB1555 | TWIDDLED), so the icon draws like
# any other HUD sprite (ape face, GOAL banner).
#
# Width/height must be powers of two (the image is resized if not).
#
# Unlike png2star.py (additive sparkle, alpha derived from luminance), this
# keeps the PNG's REAL alpha, thresholded to the single ARGB1555 alpha bit:
# a pixel is opaque when its alpha >= 128, transparent otherwise. Design the
# icon with a fully transparent background and mostly opaque interior.
#
# Usage:
#   python3 tools/png2icon.py goalicon.png mb_data/goalicon.raw

import struct
import sys
from PIL import Image


def pot(n):
    p = 8
    while p < n and p < 256:
        p *= 2
    return p


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    img = Image.open(sys.argv[1]).convert('RGBA')
    w, h = pot(img.width), pot(img.height)
    if (w, h) != img.size:
        img = img.resize((w, h), Image.LANCZOS)
    out = bytearray(struct.pack('<HH', w, h))
    for y in range(h):
        for x in range(w):
            r, g, b, a = img.getpixel((x, y))
            a1 = 1 if a >= 128 else 0
            texel = (a1 << 15) | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
            out += struct.pack('<H', texel)
    with open(sys.argv[2], 'wb') as f:
        f.write(out)
    print("wrote %s (%dx%d, %d bytes)" % (sys.argv[2], w, h, len(out)))


if __name__ == '__main__':
    main()
