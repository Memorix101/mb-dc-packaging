#!/usr/bin/env python3
#
# Convert a full-screen title/menu background PNG into title_bg.raw.
#
# The PVR needs power-of-two textures and the per-floor VRAM arena is only
# 960 KB, so a 1024x512 POT (1 MB) will not fit. We resample the image to a
# 512x512 POT (512 KB) and let render_sky STRETCH it full-screen (640x480):
# the 4:3 framing is preserved (full image -> full screen), only a light
# resample, invisible on a backdrop.
#
# Output .raw layout (little-endian):
#   [u16 pw][u16 ph][u16 cw][u16 ch]   (all 512 here: content == whole texture)
#   pw*ph  ARGB1555 texels, LINEAR row-major (main.c twiddles on upload).
# Alpha bit is forced opaque (1) - it is an opaque backdrop.

import sys
import struct

try:
    from PIL import Image
except ImportError:
    sys.exit("png2bg: needs Pillow (pip install Pillow)")

src = sys.argv[1] if len(sys.argv) > 1 else "custom_assets/title_bg.png"
dst = sys.argv[2] if len(sys.argv) > 2 else "mb_data/title_bg.raw"
# 512x512 POT = 512 KB. The RELEASE title skips the stage texture upload
# (skybox-only), so the 960 KB floor arena holds only the front-end art + bg;
# the custom title_bg is loaded into the arena leftover and stretched to
# 640x480 by render_sky. Header carries pw/ph/cw/ch so the loader stays generic.
PW, PH = 512, 512

im = Image.open(src).convert("RGB").resize((PW, PH), Image.LANCZOS)
px = im.load()

with open(dst, "wb") as f:
    f.write(struct.pack("<HHHH", PW, PH, PW, PH))
    for y in range(PH):
        row = bytearray()
        for x in range(PW):
            r, g, b = px[x, y]
            v = 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
            row += struct.pack("<H", v)
        f.write(row)

print(f"png2bg: wrote {dst} ({PW}x{PH} POT ARGB1555, stretched to 640x480)")
