#!/usr/bin/env python3
# Convert a star/particle PNG into
# the DC-ready sparkle texture "star.raw" for /cd/mb_data.
#
# Format: [u16 width][u16 height] little-endian, then width*height u16
# ARGB4444 texels (linear order; the game twiddles at upload).
# Width/height must be powers of two (the image is resized if not).
#
# Usage:
#   python3 tools/png2star.py beautifulstar.png mb_data/star.raw
#
# The game (src/main.c) probes <asset base>/star.raw at startup and uses it
# for the goal-rise sparkles; without the file it falls back to the
# procedural star.

import struct
import sys
from PIL import Image

# Cap at 128: the sparkles draw at ~50-100px and the PVR has no mipmaps -
# heavy bilinear minification of a larger texture shatters thin star rays
# into speckles (hard-learned on the console).
def pot(n):
    p = 8
    while p < n and p < 128:
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
            # additive sprites are usually white-on-black with no alpha:
            # derive alpha from luminance when the image is fully opaque
            if a == 255:
                a = max(r, g, b)
            texel = ((a >> 4) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
            out += struct.pack('<H', texel)
    with open(sys.argv[2], 'wb') as f:
        f.write(out)
    print("wrote %s (%dx%d, %d bytes)" % (sys.argv[2], w, h, len(out)))

if __name__ == '__main__':
    main()
