#!/usr/bin/env python3
# Decompress a Super Monkey Ball GC LZSS archive (.lz) to its raw payload.
# Header: little-endian u32 compressed-size @0, u32 uncompressed-size @4, then
# the LZSS stream. Ported 1:1 from libmkb/src/lzs_decompress.c (4096-byte ring,
# init pos 4078). The output is the raw big-endian GC file (e.g. a .tpl).
#   usage: lzdec.py in.lz out.bin
import struct, sys


def lzs_decompress(src: bytes) -> bytes:
    src_size = struct.unpack_from('<I', src, 0)[0]
    dest_size = struct.unpack_from('<I', src, 4)[0]
    if src_size == 0 or dest_size == 0:
        return b''
    srcp = 8
    dest = bytearray()
    ring = bytearray(4096)
    buf_pos = 4078
    flags = 0
    while True:
        flags >>= 1
        if not (flags & 0x100):
            if srcp >= src_size:
                break
            flags = src[srcp] | 0xFF00
            srcp += 1
        if flags & 1:
            if srcp >= src_size:
                break
            b = src[srcp]
            dest.append(b)
            ring[buf_pos] = b
            buf_pos = (buf_pos + 1) % 4096
            srcp += 1
        else:
            if srcp >= src_size:
                break
            offset = src[srcp]
            if srcp + 1 >= src_size:
                break
            r8 = src[srcp + 1]
            srcp += 2
            length = (r8 & 0xF) + 2
            offset |= (r8 & 0xF0) << 4
            for i in range(length + 1):
                b = ring[(offset + i) % 4096]
                dest.append(b)
                ring[buf_pos] = b
                buf_pos = (buf_pos + 1) % 4096
    return bytes(dest[:dest_size])


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('usage: lzdec.py in.lz out.bin')
    with open(sys.argv[1], 'rb') as f:
        data = f.read()
    out = lzs_decompress(data)
    with open(sys.argv[2], 'wb') as f:
        f.write(out)
    print(f'wrote {sys.argv[2]} ({len(out)} bytes)')
