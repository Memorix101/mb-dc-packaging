#!/usr/bin/env python3
# Map game sound ids (u_play_sound_* call sites) to MusyX sample ids,
# fully automatically, replacing the by-ear hunt through 185 wavs.
#
# Chain (all verified against the ear-confirmed ids from 2026-07-03):
#   game id --(smb-decomp sound.c g_soundDesc, unkC == id & 0x7FF)--> desc
#   desc.unk0 = SFX define id in the group's .proj
#   .proj sfx record {defineId, objectId, prio, maxVoices, vel, pan, key}
#   .pool SoundMacro object --(startSample cmd, opcode 0x10)--> sample id
#   sample id = %04x.wav in smb1_content/audio/extracted/
#
# Voice variants: desc entries with unk8 >= 15 repeat per character
# (nar/boy/girl/baby voice groups); the game picks by charaId. We list
# every variant with its group name so AiAi (boy) is easy to grab.
#
# Usage:
#   python3 tools/musyx_map.py                # dump the whole table
#   python3 tools/musyx_map.py 4 5 7 0x128    # only these game ids
#
# Formats (GC, big-endian), reverse-engineered from allse + amuse docs:
#   .proj group: u32 endOff, u16 groupId, u16 type(1=sfx),
#     u32 offs x5 (macro/sample/table/keymap/layer id lists, 0xFFFF-term),
#     sfx table: u16 count, u16 pad, then count * 10-byte records
#     {u16 defineId, u16 objectId, u8 prio, u8 maxVox, u8 vel, u8 pan,
#      u8 key, u8 pad}.
#   .pool: u32 sectionOff x4 (macros/tables/keymaps/layers; 0 = absent).
#     Macro section: objects {u32 size, u16 objectId, u16 pad, body...},
#     next object at +size; terminated by 0xFFFFFFFF.
#     Macro body: 8-byte commands, OPCODE AT BYTE 3 (BE u32 low byte);
#     startSample = 0x10 with the sdir sample id in bytes 1-2.
#     (The old name_sfx.py read a fixed row - wrong for most macros.)

import re
import struct
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SND = os.path.join(ROOT, "smb1_content/test/snd/mkb")
DECOMP_SOUND_C = os.path.join(ROOT, "reference/smb-decomp/src/sound.c")

OP_END = 0x00
OP_GOTO = 0x06
OP_PLAYMACRO = 0x08
OP_STARTSAMPLE = 0x10
OP_SPLITKEY = 0x02
OP_SPLITVEL = 0x03
OP_SPLITRND = 0x13


def parse_proj(path):
    """defineId -> (objectId, vel, pan, key) for the first sfx group."""
    d = open(path, "rb").read()
    sfx = {}
    pos = 0
    while pos + 4 <= len(d):
        (end,) = struct.unpack_from(">I", d, pos)
        if end == 0xFFFFFFFF or end <= pos:
            break
        gid, gtype = struct.unpack_from(">HH", d, pos + 4)
        if gtype == 1:  # sfx group: 5 id-list offsets, then the sfx table
            offs = struct.unpack_from(">5I", d, pos + 8)
            tab = pos + 0x1C
            # the sfx table follows the last id list; scan for the count
            # right after the layer list terminator
            tab = offs[4]
            # comn.proj pads with a 0x0000 word between the id-list
            # terminators and the record count (allse does not) - skip
            # both; an empty table would read count 0 either way.
            while struct.unpack_from(">H", d, tab)[0] in (0xFFFF, 0x0000):
                tab += 2
            count = struct.unpack_from(">H", d, tab)[0]
            rec = tab + 4
            for _ in range(count):
                did, oid, prio, mvox, vel, pan, key, _p = struct.unpack_from(
                    ">HHBBBBBB", d, rec)
                sfx[did] = (oid, vel, pan, key)
                rec += 10
        pos = end
    return sfx


def parse_pool(path):
    """objectId -> list of 8-byte command rows."""
    d = open(path, "rb").read()
    (macro_off,) = struct.unpack_from(">I", d, 0)
    macros = {}
    pos = macro_off
    while pos + 8 <= len(d):
        (size,) = struct.unpack_from(">I", d, pos)
        if size == 0xFFFFFFFF or size < 8:
            break
        (oid,) = struct.unpack_from(">H", d, pos + 4)
        body = d[pos + 8:pos + size]
        rows = [body[i:i + 8] for i in range(0, len(body) - 7, 8)]
        macros[oid] = rows
        pos += size
    return macros


def macro_samples(macros, oid, depth=0):
    """All sdir sample ids reachable from a macro (follows sub-macros)."""
    out = []
    if depth > 4 or oid not in macros:
        return out
    for row in macros[oid]:
        op = row[3]
        if op == OP_STARTSAMPLE:
            out.append(struct.unpack(">H", row[1:3])[0])
        elif op in (OP_PLAYMACRO, OP_GOTO, OP_SPLITKEY, OP_SPLITVEL,
                    OP_SPLITRND):
            # referenced macro id is a u16 somewhere in the args; try the
            # common slots and follow ids that exist in the pool
            for at in (0, 4, 5):
                if at + 2 <= len(row):
                    ref = struct.unpack(">H", row[at:at + 2])[0]
                    if ref != oid and ref in macros:
                        out.extend(macro_samples(macros, ref, depth + 1))
                        break
    return out


def parse_sound_desc(path):
    """[(unk0/define, name, unk8, unkA, unkC/game id), ...] from sound.c."""
    src = open(path, errors="replace").read()
    m = re.search(r"g_soundDesc\[\]\s*=\s*\{(.*?)\n\};", src, re.S)
    if not m:
        raise SystemExit("g_soundDesc not found in " + path)
    rows = []
    pat = re.compile(
        r'\{\s*(-?\w+)\s*,\s*"([^"]*)"\s*,\s*(-?\w+)\s*,\s*(-?\w+)\s*,'
        r'\s*(-?\w+)\s*\}')
    for mm in pat.finditer(m.group(1)):
        unk0, name, unk8, unkA, unkC = mm.groups()
        rows.append((int(unk0, 0), name, int(unk8, 0), int(unkA, 0),
                     int(unkC, 0)))
    return rows


# desc index ranges -> voice/sfx group names (g_soundGroupDesc, allse only)
GROUPS = [(0, "se04"), (4, "se01"), (85, "se02"), (114, "se03"),
          (126, "nar"), (178, "boy"), (243, "girl"), (310, "baby"),
          (370, "goli"), (411, "-nonallse-")]


def group_of(idx):
    name = "?"
    for start, gname in GROUPS:
        if idx >= start:
            name = gname
    return name


def main():
    # --bank NAME reads another bank's .proj/.pool (e.g. comn = the menu
    # announcer bank: select_course/beginner/advanced/expert/...). The
    # g_soundDesc walk still covers allse indices only, so with a foreign
    # bank pass DEFINE ids (from sound.c unk0) instead of game ids.
    bank = "allse"
    args = sys.argv[1:]
    if "--bank" in args:
        i = args.index("--bank")
        bank = args[i + 1]
        del args[i:i + 2]
    want = set()
    for a in args:
        want.add(int(a, 0))
    sfx = parse_proj(os.path.join(SND, bank + ".proj"))
    macros = parse_pool(os.path.join(SND, bank + ".pool"))
    if bank != "allse":
        print("bank %s: define -> object -> samples" % bank)
        for did in sorted(want if want else sfx.keys()):
            if did not in sfx:
                print("0x%03X  (nicht in %s.proj)" % (did, bank))
                continue
            oid = sfx[did][0]
            smp = macro_samples(macros, oid)
            print("0x%03X  object=0x%03X  samples=%s"
                  % (did, oid, ",".join("0x%04X" % s for s in smp)))
        return
    descs = parse_sound_desc(DECOMP_SOUND_C)

    # ear-verified ground truth (user, 2026-07-03): game id -> sample id
    truth = {4: 0x01D5, 5: 0x0196, 7: 0x019D, 0x128: 0x022E}

    print("game_id  desc_idx grp   define  object  samples           name")
    hits = misses = 0
    for idx, (unk0, name, unk8, unkA, unkC) in enumerate(descs):
        if idx >= 411:          # non-allse groups (bil/bowl/...) end here
            break
        if unkC < 0:
            continue
        if unk0 < 0:
            # DMY_CODE alias: SoundReqID walks BACK to the previous entry
            # with unk0 != -1 and plays that one (menu sounds 0x6E/6F/70)
            j = idx
            while j >= 0 and descs[j][0] < 0:
                j -= 1
            if j < 0:
                continue
            unk0 = descs[j][0]
            name = name + " -> " + descs[j][1]
        if want and unkC not in want:
            continue
        define = unk0
        if define not in sfx:
            print("0x%04X   %4d   %-5s 0x%03X   -       (define not in proj)"
                  "  %s" % (unkC, idx, group_of(idx), define, name))
            continue
        oid = sfx[define][0]
        smp = macro_samples(macros, oid)
        smps = ",".join("0x%04X" % s for s in smp) if smp else "(none)"
        mark = ""
        if unkC in truth and not want:
            ok = truth[unkC] in smp
            mark = "  <== TRUTH 0x%04X %s" % (truth[unkC],
                                              "OK" if ok else "MISMATCH")
            hits += ok
            misses += not ok
        print("0x%04X   %4d   %-5s 0x%03X   0x%03X   %-16s  %s%s"
              % (unkC, idx, group_of(idx), define, oid, smps, name, mark))
    if not want:
        print("\nground truth: %d ok, %d mismatch" % (hits, misses))


if __name__ == "__main__":
    main()
