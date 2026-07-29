#!/usr/bin/env python3
"""OBJ -> baked stage geometry (BKG1) for the LOD replacement test.

Converts a Wavefront OBJ (e.g. a tri-reduced stage exported from Blender)
into the renderer's baked-shape format: welded indexed vertices
(x,y,z,u,v), a greedy triangle-strip stream matching bk_strips
([len, idx...]*), plus the plain triangle list for the clip path.

The game probes mb_data/stNNN_lod.bin at floor load and, when present,
draws it INSTEAD of the STATIC stage GMA models (anim group 0; collision
is untouched, it comes from the stagedef). Delete the file to get the
original back.

Export contract: the OBJ must contain only the static opaque world.
 - Animated stage models (moving platforms etc.) keep rendering through
   the GMA path with their group transform - leave them out of the OBJ
   or they appear twice (once baked static, once animated).
 - Translucent stage shapes also keep rendering from the GMA; exporting
   those faces into the OBJ would double them (BKG1 draws opaque only).

Texture binding: each OBJ material maps to a stage TPL index parsed from
the digits in its map_Kd filename ("Tex_0014_1.dds" -> 14, "7.png" -> 7).
Materials without a usable number are drawn flat.

Output layout (little-endian, DC native):
  u32 magic 'BKG1'   u32 mesh_count
  per mesh:
    s32 tpl_index (-1 flat)   u32 vcount   u32 striplen   u32 tcount
    f32 bs[4] (cx,cy,cz,r)
    f32 verts[vcount*5]   u16 strips[striplen]   u16 tris[tcount*3]
    (u16 pad to 4-byte alignment when needed)

Usage: obj2bk.py in.obj out.bin [--flip-x] [--no-flip-v]
"""
import re
import struct
import sys


def parse_mtl_tpl_indices(path):
    """map material name -> TPL index from the digits in its map_Kd name."""
    tpl = {}
    cur = None
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                t = line.split()
                if not t:
                    continue
                if t[0] == "newmtl":
                    cur = t[1]
                elif t[0] == "map_Kd" and cur:
                    base = t[-1].replace("\\", "/").rsplit("/", 1)[-1]
                    m = re.search(r"(\d+)", base)
                    if m:
                        tpl[cur] = int(m.group(1))
    except OSError:
        pass
    return tpl


def load_obj(path, flip_x, flip_v):
    vs, vts = [], []
    # meshes keyed by (object, material): {key: [(vidx,vtidx)x3 ...]}
    meshes = {}
    order = []
    obj_name, mtl_name = "obj", ""
    mtllib = None
    with open(path, "r", errors="replace") as f:
        for line in f:
            t = line.split()
            if not t:
                continue
            if t[0] == "v":
                x, y, z = float(t[1]), float(t[2]), float(t[3])
                if flip_x:
                    x = -x
                vs.append((x, y, z))
            elif t[0] == "vt":
                u, v = float(t[1]), float(t[2])
                vts.append((u, 1.0 - v if flip_v else v))
            elif t[0] == "o" or t[0] == "g":
                obj_name = t[1] if len(t) > 1 else "obj"
            elif t[0] == "usemtl":
                mtl_name = t[1] if len(t) > 1 else ""
            elif t[0] == "mtllib":
                mtllib = t[1]
            elif t[0] == "f":
                corner = []
                for w in t[1:]:
                    p = w.split("/")
                    vi = int(p[0])
                    ti = int(p[1]) if len(p) > 1 and p[1] else 0
                    vi = vi - 1 if vi > 0 else len(vs) + vi
                    ti = ti - 1 if ti > 0 else (len(vts) + ti if ti else -1)
                    corner.append((vi, ti))
                key = (obj_name, mtl_name)
                if key not in meshes:
                    meshes[key] = []
                    order.append(key)
                fan = meshes[key]
                # fan-triangulate. Mirroring one axis (--flip-x) reverses the
                # triangle winding, so swap two corners to keep front faces
                # front-facing: the stage draws run with the hardware backface
                # cull from STAGE_BACKFACE_CULL (main.c) - off by default, but
                # the baked output must stay correct when it is enabled.
                for k in range(1, len(corner) - 1):
                    if flip_x:
                        fan.append((corner[0], corner[k + 1], corner[k]))
                    else:
                        fan.append((corner[0], corner[k], corner[k + 1]))
    return vs, vts, meshes, order, mtllib


def weld(vs, vts, tris_raw):
    """(vidx,vtidx) corners -> unique indexed verts (x,y,z,u,v) + u16 tris."""
    idx_of = {}
    verts = []
    tris = []
    for tri in tris_raw:
        out = []
        for (vi, ti) in tri:
            key = (vi, ti)
            i = idx_of.get(key)
            if i is None:
                x, y, z = vs[vi]
                u, v = vts[ti] if 0 <= ti < len(vts) else (0.0, 0.0)
                i = len(verts)
                idx_of[key] = i
                verts.append((x, y, z, u, v))
            out.append(i)
        a, b, c = out
        if a == b or b == c or a == c:
            continue                     # degenerate after weld
        tris.append((a, b, c))
    return verts, tris


def stripify(tris):
    """Greedy strips over shared edges, emitted as [len, idx...]* (u16).

    Strips keep the hardware's alternating-parity winding convention: a
    triangle is only appended when its stored winding matches the parity of
    its strip position, so the stream stays consistent under the optional
    backface cull (STAGE_BACKFACE_CULL). The earlier greedy version flipped
    parity freely and only looked right because that cull defaults to off.
    """
    edge_map = {}
    for tidx, (a, b, c) in enumerate(tris):
        for e in ((a, b), (b, c), (c, a)):
            k = (min(e), max(e))
            edge_map.setdefault(k, []).append(tidx)

    def third_after(tri, x, y):
        """Third vertex if (x, y, .) is a rotation of tri, else None.

        Rotations preserve winding, so a hit means the triangle can sit at
        a strip position whose effective draw order starts with x, y."""
        a, b, c = tri
        if (a, b) == (x, y):
            return c
        if (b, c) == (x, y):
            return a
        if (c, a) == (x, y):
            return b
        return None

    used = [False] * len(tris)
    stream = []
    total_strip_verts = 0
    for start in range(len(tris)):
        if used[start]:
            continue
        used[start] = True
        a, b, c = tris[start]
        strip = [a, b, c]
        # extend forward: last edge = (strip[-2], strip[-1]). The triangle at
        # 0-based strip position i draws as (v[i], v[i+1], v[i+2]) for even i
        # and (v[i+1], v[i], v[i+2]) for odd i (hardware parity flip).
        while True:
            odd = (len(strip) - 2) & 1
            va, vb = strip[-2], strip[-1]
            e = (min(va, vb), max(va, vb))
            nxt = None
            nxt_v = None
            for cand in edge_map.get(e, ()):
                if used[cand]:
                    continue
                v = (third_after(tris[cand], vb, va) if odd
                     else third_after(tris[cand], va, vb))
                if v is not None:
                    nxt = cand
                    nxt_v = v
                    break
            if nxt is None:
                break
            used[nxt] = True
            strip.append(nxt_v)
        stream.append(len(strip))
        stream.extend(strip)
        total_strip_verts += len(strip)
    return stream, total_strip_verts


def bsphere(verts):
    if not verts:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    cx = (min(xs) + max(xs)) * 0.5
    cy = (min(ys) + max(ys)) * 0.5
    cz = (min(zs) + max(zs)) * 0.5
    r = max(((v[0] - cx) ** 2 + (v[1] - cy) ** 2 + (v[2] - cz) ** 2) ** 0.5
            for v in verts)
    return (cx, cy, cz, r)


# Spatial split, mirroring the engine's chunk_shape: material meshes span the
# whole stage, so the camera always sits inside them - some vertex lands
# behind the near plane, the strip fast path bails and every triangle takes
# the per-tri clip path (measured: the unsplit stage cost MORE than the
# original geometry). Small XZ cells keep chunks either fully in front
# (strip path) or sphere-cullable.
CELL = 10.0


def split_cells(verts, tris):
    """[(verts,tris)] per occupied XZ cell, verts re-indexed per cell."""
    cells = {}
    for tri in tris:
        cx = sum(verts[i][0] for i in tri) / 3.0
        cz = sum(verts[i][2] for i in tri) / 3.0
        key = (int(cx // CELL), int(cz // CELL))
        cells.setdefault(key, []).append(tri)
    out = []
    for key in sorted(cells.keys()):
        remap = {}
        cv, ct = [], []
        for tri in cells[key]:
            ni = []
            for i in tri:
                j = remap.get(i)
                if j is None:
                    j = len(cv)
                    remap[i] = j
                    cv.append(verts[i])
                ni.append(j)
            ct.append(tuple(ni))
        out.append((cv, ct))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flip_x = "--flip-x" in sys.argv
    flip_v = "--no-flip-v" not in sys.argv
    if len(args) != 2:
        sys.exit(__doc__)
    src, dst = args

    vs, vts, meshes, order, mtllib = load_obj(src, flip_x, flip_v)
    tpl_map = {}
    if mtllib:
        base = src.replace("\\", "/").rsplit("/", 1)[0]
        # mtllib casing on disk may differ from the OBJ line (Windows export)
        import os
        for cand in (mtllib, mtllib.lower(), mtllib.upper()):
            p = base + "/" + cand
            if os.path.exists(p):
                tpl_map = parse_mtl_tpl_indices(p)
                break

    # Merge across objects AND materials by TPL index: the per-mesh draw has
    # a fixed cost (matrix fold, XMTRX load, poly header), so fewer, fatter
    # meshes win. All meshes share one transform, so merging is free; the
    # cell split below restores spatial granularity for culling.
    by_tpl = {}
    tpl_order = []
    for key in order:
        tpl = tpl_map.get(key[1], -1)
        if tpl not in by_tpl:
            by_tpl[tpl] = []
            tpl_order.append(tpl)
        by_tpl[tpl].extend(meshes[key])

    payload = bytearray()
    tot_tris = tot_verts = tot_sverts = 0
    n_out = 0
    for tpl in tpl_order:
        verts, tris = weld(vs, vts, by_tpl[tpl])
        chunks = split_cells(verts, tris)
        for (cv, ct) in chunks:
            if len(cv) > 65535:
                sys.exit(f"mesh {key}: {len(cv)} verts > u16 index space")
            stream, sverts = stripify(ct)
            bs = bsphere(cv)
            payload += struct.pack("<iIII", tpl, len(cv), len(stream), len(ct))
            payload += struct.pack("<4f", *bs)
            for v in cv:
                payload += struct.pack("<5f", *v)
            payload += struct.pack(f"<{len(stream)}H", *stream)
            for tri in ct:
                payload += struct.pack("<3H", *tri)
            if (len(payload) + 8) & 2:
                payload += b"\0\0"        # realign to 4 for the next mesh
            tot_sverts += sverts
            n_out += 1
        tot_tris += len(tris)
        tot_verts += len(verts)
        print(f"  tpl={tpl:3d} v={len(verts):5d} tris={len(tris):5d} "
              f"cells={len(chunks)}")

    blob = struct.pack("<4sI", b"BKG1", n_out) + payload
    with open(dst, "wb") as f:
        f.write(blob)
    print(f"{dst}: {n_out} meshes (cell-split), {tot_verts} verts, "
          f"{tot_tris} tris, {tot_sverts} strip-verts "
          f"({tot_sverts / max(tot_tris,1):.2f}/tri), {len(blob)} bytes")


if __name__ == "__main__":
    main()
