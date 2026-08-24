#!/usr/bin/env python3
"""Offline PVR VQ encoder for SMB TPL texture sets.

For every texture in a TPL that is square, power-of-two and >= MIN_DIM,
decode it to ARGB1555, k-means a 256-entry codebook of 2x2 blocks and emit
the exact PVR VQ layout the runtime already draws (see src/vq.c): 2048-byte
codebook (entry texel order TL,BL,TR,BR) followed by one index byte per 2x2
block in twiddle order. Textures above MAX_DIM are box-halved first.

Every VQ texture also carries a full mip chain (PVR VQ mipmaps): all
levels share the base level's codebook; the index planes are stored
smallest level first at the fixed hardware offsets.

Output: one little-endian sidecar per TPL:
    u32 magic 'SVQ2', u32 count,
    count * { u32 offset, u32 size, u16 w, u16 h, u32 flags }  (offset 0 =
    no VQ; flags bit0 = mip chain present)
    ... blobs ...

Usage: vqenc.py <in.tpl> <out.vqt>      (single file)
       vqenc.py --batch <src_root> <out_dir>
"""
import struct
import sys
import os
import numpy as np

MIN_DIM = 64
# 256 (was 512): 512x512 VQ+MIP blobs render as noise on real PVR hardware
# (st039/040 "digital snow"); 256+mips is proven good everywhere and keeps
# the texture-cache benefit that flat-512 uploads lose. The runtime's
# flat-top-level conversion (texcache.c) stays as a backstop for any old
# oversized sidecar entry.
MAX_DIM = 256
CB_SIZE = 256
KMEANS_ITERS = 12


def twiddle(x, y, w, h):
    rv = 0
    sh = 0
    xs, ys = w >> 1, h >> 1
    while xs or ys:
        if ys:
            rv |= (y & 1) << sh
            ys >>= 1
            y >>= 1
            sh += 1
        if xs:
            rv |= (x & 1) << sh
            xs >>= 1
            x >>= 1
            sh += 1
    return rv


# ---- GC texture decode (to RGBA u8 arrays) -------------------------------

def dec_cmpr(d, off, w, h):
    img = np.zeros((h, w, 4), np.uint8)
    p = off
    for by in range(0, h, 8):
        for bx in range(0, w, 8):
            for sy in range(2):
                for sx in range(2):
                    c0, c1 = struct.unpack_from('>HH', d, p)
                    bits = struct.unpack_from('>I', d, p + 4)[0]
                    p += 8
                    def col(c):
                        return np.array([(c >> 11 & 31) * 255 // 31,
                                         (c >> 5 & 63) * 255 // 63,
                                         (c & 31) * 255 // 31, 255], np.int32)
                    pal = [col(c0), col(c1)]
                    if c0 > c1:
                        pal.append((2 * pal[0] + pal[1]) // 3)
                        pal.append((pal[0] + 2 * pal[1]) // 3)
                    else:
                        pal.append((pal[0] + pal[1]) // 2)
                        pal.append(np.array([0, 0, 0, 0], np.int32))
                    for py in range(4):
                        Y = by + sy * 4 + py
                        if Y >= h:
                            continue
                        for px in range(4):
                            X = bx + sx * 4 + px
                            if X >= w:
                                continue
                            img[Y, X] = pal[(bits >> (30 - 2 * (py * 4 + px))) & 3]
    return img


def dec_rgb5a3(d, off, w, h):
    img = np.zeros((h, w, 4), np.uint8)
    p = off
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            for py in range(4):
                for px in range(4):
                    v = struct.unpack_from('>H', d, p)[0]
                    p += 2
                    Y, X = by + py, bx + px
                    if Y >= h or X >= w:
                        continue
                    if v & 0x8000:
                        img[Y, X] = ((v >> 10 & 31) * 255 // 31,
                                     (v >> 5 & 31) * 255 // 31,
                                     (v & 31) * 255 // 31, 255)
                    else:
                        img[Y, X] = ((v >> 8 & 15) * 255 // 15,
                                     (v >> 4 & 15) * 255 // 15,
                                     (v & 15) * 255 // 15,
                                     (v >> 12 & 7) * 255 // 7)
    return img


def dec_rgb565(d, off, w, h):
    img = np.zeros((h, w, 4), np.uint8)
    p = off
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            for py in range(4):
                for px in range(4):
                    v = struct.unpack_from('>H', d, p)[0]
                    p += 2
                    Y, X = by + py, bx + px
                    if Y >= h or X >= w:
                        continue
                    img[Y, X] = ((v >> 11 & 31) * 255 // 31,
                                 (v >> 5 & 63) * 255 // 63,
                                 (v & 31) * 255 // 31, 255)
    return img


def dec_i8(d, off, w, h):
    img = np.zeros((h, w, 4), np.uint8)
    p = off
    for by in range(0, h, 4):
        for bx in range(0, w, 8):
            for py in range(4):
                for px in range(8):
                    v = d[p]
                    p += 1
                    Y, X = by + py, bx + px
                    if Y >= h or X >= w:
                        continue
                    img[Y, X] = (v, v, v, 255)
    return img


def dec_ia4(d, off, w, h):
    img = np.zeros((h, w, 4), np.uint8)
    p = off
    for by in range(0, h, 4):
        for bx in range(0, w, 8):
            for py in range(4):
                for px in range(8):
                    v = d[p]
                    p += 1
                    Y, X = by + py, bx + px
                    if Y >= h or X >= w:
                        continue
                    i = (v & 15) * 17
                    img[Y, X] = (i, i, i, (v >> 4) * 17)
    return img


def dec_rgba8(d, off, w, h):
    img = np.zeros((h, w, 4), np.uint8)
    p = off
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            ar = d[p:p + 32]
            gb = d[p + 32:p + 64]
            p += 64
            for py in range(4):
                for px in range(4):
                    Y, X = by + py, bx + px
                    if Y >= h or X >= w:
                        continue
                    k = (py * 4 + px) * 2
                    img[Y, X] = (ar[k + 1], gb[k], gb[k + 1], ar[k])
    return img


DECODERS = {0x4: dec_rgb565, 0x5: dec_rgb5a3, 0x1: dec_i8, 0x2: dec_ia4,
            0x6: dec_rgba8, 0xE: dec_cmpr}


def to_argb1555(img):
    r = (img[:, :, 0].astype(np.uint16) >> 3)
    g = (img[:, :, 1].astype(np.uint16) >> 3)
    b = (img[:, :, 2].astype(np.uint16) >> 3)
    a = (img[:, :, 3].astype(np.uint16) >= 128).astype(np.uint16)
    return (a << 15) | (r << 10) | (g << 5) | b


def unpack1555(t):
    t = t.astype(np.int32)
    return np.stack([(t >> 10 & 31) << 3, (t >> 5 & 31) << 3,
                     (t & 31) << 3, (t >> 15) * 255], axis=-1).astype(np.float32)


def pack1555(v):
    v = np.clip(np.round(v), 0, 255).astype(np.uint16)
    a = (v[:, :, 3] >= 128).astype(np.uint16)
    return (a << 15) | ((v[:, :, 0] >> 3) << 10) | ((v[:, :, 1] >> 3) << 5) \
           | (v[:, :, 2] >> 3)


# Byte offset of each level's index plane (after the 2048-byte codebook),
# smallest level first: dims 1,2,4,...,1024.
VQ_MIP_OFS = [0, 1, 2, 6, 22, 86, 342, 1366, 5462, 21846, 87382]


def blocks_of(tex16, w, h):
    """2x2 blocks in twiddle order, texel order TL,BL,TR,BR (uint16)."""
    nb = max(1, (w * h) // 4)
    blocks16 = np.zeros((nb, 4), np.uint16)
    if w == 1:
        blocks16[0] = (tex16[0, 0],) * 4
        return blocks16
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            bi = twiddle(int(x), int(y), w, h) >> 2
            blocks16[bi] = (tex16[y, x], tex16[y + 1, x],
                            tex16[y, x + 1], tex16[y + 1, x + 1])
    return blocks16


def assign_blocks(vecs, cb):
    n = vecs.shape[0]
    assign = np.empty(n, np.int64)
    for st in range(0, n, 8192):
        en = min(st + 8192, n)
        d = ((vecs[st:en, None, :] - cb[None, :, :]) ** 2).sum(axis=2)
        assign[st:en] = d.argmin(axis=1)
    return assign


def kmeans_vq(tex16, w, h):
    """tex16: (h, w) uint16 ARGB1555. Returns the full PVR VQ+mip blob:
    2048-byte codebook + index planes for every level, 1x1 first."""
    nb = (w * h) // 4
    # blocks in twiddle order, texel order TL,BL,TR,BR
    xs = np.arange(0, w, 2)
    ys = np.arange(0, h, 2)
    order = np.zeros(nb, np.int64)
    blocks16 = np.zeros((nb, 4), np.uint16)
    for y in ys:
        for x in xs:
            bi = twiddle(int(x), int(y), w, h) >> 2
            order[bi] = 1
            blocks16[bi] = (tex16[y, x], tex16[y + 1, x],
                            tex16[y, x + 1], tex16[y + 1, x + 1])
    vecs = unpack1555(blocks16).reshape(nb, 16)  # 4 texels * RGBA

    k = min(CB_SIZE, nb)
    # init: sample evenly across the brightness-sorted set
    bright = vecs.sum(axis=1)
    srt = np.argsort(bright, kind='stable')
    seeds = srt[np.linspace(0, nb - 1, k).astype(np.int64)]
    cb = vecs[seeds].copy()

    for _ in range(KMEANS_ITERS):
        # nearest centroid per block (chunked to bound memory)
        assign = np.empty(nb, np.int64)
        for s in range(0, nb, 8192):
            e = min(s + 8192, nb)
            d = ((vecs[s:e, None, :] - cb[None, :, :]) ** 2).sum(axis=2)
            assign[s:e] = d.argmin(axis=1)
        newcb = cb.copy()
        counts = np.bincount(assign, minlength=k)
        for c in range(16):
            sums = np.bincount(assign, weights=vecs[:, c], minlength=k)
            nzm = counts > 0
            newcb[nzm, c] = sums[nzm] / counts[nzm]
        # respawn empty clusters on the worst-represented blocks
        empty = np.where(counts == 0)[0]
        if len(empty):
            derr = ((vecs - newcb[assign]) ** 2).sum(axis=1)
            worst = np.argsort(derr)[::-1][:len(empty)]
            newcb[empty] = vecs[worst]
        if np.allclose(newcb, cb):
            cb = newcb
            break
        cb = newcb

    first = CB_SIZE - k
    cb16 = pack1555(cb.reshape(k, 4, 4)[None, :, :, :].reshape(1, k * 4, 4)) \
        .reshape(k, 4)

    # index planes for the whole mip chain, smallest level first, all
    # assigned against the shared base-level codebook
    K = int(w).bit_length() - 1
    total = 2048 + VQ_MIP_OFS[K] + max(1, nb)
    out = bytearray(total)
    for e in range(k):
        struct.pack_into('<4H', out, (first + e) * 8, *cb16[e])

    lvl16 = tex16
    dim = w
    while True:
        lb = blocks_of(lvl16, dim, dim)
        lv = unpack1555(lb).reshape(lb.shape[0], 16)
        la = assign_blocks(lv, cb)
        lk = int(dim).bit_length() - 1
        o0 = 2048 + VQ_MIP_OFS[lk]
        out[o0:o0 + lb.shape[0]] = np.asarray(first + la, np.uint8).tobytes()
        if dim == 1:
            break
        # alpha-aware box halve in ARGB1555 space (avoid dark speckles)
        v = unpack1555(lvl16)
        q = (v[0::2, 0::2] + v[0::2, 1::2] + v[1::2, 0::2] + v[1::2, 1::2])
        aq = (v[0::2, 0::2, 3:] > 0).astype(np.float32) \
           + (v[0::2, 1::2, 3:] > 0) + (v[1::2, 0::2, 3:] > 0) \
           + (v[1::2, 1::2, 3:] > 0)
        rgb = np.divide(q[:, :, :3], np.maximum(aq, 1),
                        where=np.maximum(aq, 1) > 0)
        alpha = np.where(aq >= 2, 255.0, 0.0)
        nxt = np.concatenate([rgb, alpha], axis=2)
        lvl16 = pack1555(nxt)
        dim >>= 1
    return bytes(out)


def halve(img):
    h, w = img.shape[0] // 2, img.shape[1] // 2
    return ((img[0::2, 0::2].astype(np.uint16) + img[0::2, 1::2] +
             img[1::2, 0::2] + img[1::2, 1::2]) // 4).astype(np.uint8)


def encode_tpl(path_in, path_out):
    d = open(path_in, 'rb').read()
    n = struct.unpack_from('>I', d, 0)[0]
    entries = []
    blobs = []
    for i in range(n):
        o = 4 + i * 0x10
        fmt, off = struct.unpack_from('>II', d, o)
        w, h = struct.unpack_from('>HH', d, o + 8)
        blob = None
        if fmt in DECODERS and w == h and w >= MIN_DIM \
                and (w & (w - 1)) == 0:
            img = DECODERS[fmt](d, off, w, h)
            while img.shape[0] > MAX_DIM:
                img = halve(img)
            t16 = to_argb1555(img)
            blob = kmeans_vq(t16, img.shape[1], img.shape[0])
            entries.append((len(blob), img.shape[1], img.shape[0]))
        else:
            entries.append((0, 0, 0))
        blobs.append(blob)
    out = bytearray()
    out += struct.pack('<II', 0x32515653, n)  # 'SVQ2'
    hdr_off = len(out)
    out += b'\0' * (16 * n)
    for i, blob in enumerate(blobs):
        if blob is None:
            continue
        sz, w, h = entries[i]
        out += b'\0' * ((-len(out)) % 32)  # SH4 SQ copy needs aligned src
        struct.pack_into('<IIHHI', out, hdr_off + 16 * i,
                         len(out), len(blob), w, h, 1)  # flags bit0 = mips
        out += blob
    with open(path_out, 'wb') as f:
        f.write(out)
    done = sum(1 for b in blobs if b is not None)
    print(f'{os.path.basename(path_in)}: {done}/{n} textures vq, '
          f'{len(out) // 1024}k')
    return done


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == '--batch':
        src, dst = sys.argv[2], sys.argv[3]
        os.makedirs(dst, exist_ok=True)
        jobs = []
        for root, _, files in os.walk(src):
            base = os.path.basename(root)
            # v1 scope: stage + background sets only. common/chara/preview
            # TPLs are drawn by sites that do not bind the vq flag arrays.
            if not (base.startswith('st') or base == 'bg'):
                continue
            for f in sorted(files):
                if f.endswith('.tpl'):
                    jobs.append(os.path.join(root, f))
        for p in jobs:
            base = os.path.splitext(os.path.basename(p))[0]
            outp = os.path.join(dst, base + '.vqt')
            if os.path.exists(outp) and \
                    os.path.getmtime(outp) > os.path.getmtime(p):
                continue
            try:
                encode_tpl(p, outp)
            except Exception as ex:
                print(f'{p}: FAILED ({ex})', file=sys.stderr)
    elif len(sys.argv) == 3:
        encode_tpl(sys.argv[1], sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
