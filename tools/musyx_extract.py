#!/usr/bin/env python3
# Extract all samples from a GameCube MusyX sample bank (.sdir + .samp)
# into numbered WAV files for listening and naming.
#
# Usage:
#   python3 tools/musyx_extract.py smb1_content/test/snd/mkb/allse.sdir \
#           smb1_content/test/snd/mkb/allse.samp /tmp/allse_wavs
#
# Then listen through the output, find the sounds the game needs (see
# src/sound.h), and copy/rename them to smb1_content/audio/sfx/<name>.wav
# for tools/convert_audio.sh.
#
# SDIR format (observed in allse.sdir, matches MusyX GC docs):
#   0x20-byte entries until id == 0xFFFF:
#     +0x00 u16 sample id      +0x04 u32 offset into .samp
#     +0x0E u16 sample rate    +0x10 u32 sample count
#     +0x1C u32 offset of the 0x28-byte coefficient record (in .sdir)
#   coefficient record: +0x08? 16 x s16 DSP-ADPCM coefficients (last 32 bytes)
#
# Samples are standard GC DSP-ADPCM: 8-byte frames = 1 header byte
# (high nibble: shift, low nibble: coefficient pair index) + 14 nibbles.

import struct
import sys
import wave
import os

def clamp16(v):
    return -32768 if v < -32768 else (32767 if v > 32767 else v)

def decode_dsp(data, nsamples, coefs):
    out = []
    h1 = h2 = 0
    pos = 0
    while len(out) < nsamples and pos + 1 <= len(data):
        header = data[pos]; pos += 1
        shift = header & 0x0F
        cidx  = (header >> 4) & 0x0F
        c1 = coefs[cidx * 2] if cidx * 2 < len(coefs) else 0
        c2 = coefs[cidx * 2 + 1] if cidx * 2 + 1 < len(coefs) else 0
        frame = data[pos:pos + 7]; pos += 7
        for byte in frame:
            for nib in ((byte >> 4) & 0xF, byte & 0xF):
                if len(out) >= nsamples:
                    break
                s = nib - 16 if nib > 7 else nib
                sample = (((s << shift) << 11) + 1024 + c1 * h1 + c2 * h2) >> 11
                sample = clamp16(sample)
                out.append(sample)
                h2 = h1
                h1 = sample
    return out

def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    sdir = open(sys.argv[1], 'rb').read()
    samp = open(sys.argv[2], 'rb').read()
    outdir = sys.argv[3]
    os.makedirs(outdir, exist_ok=True)

    entries = []
    pos = 0
    while pos + 0x20 <= len(sdir):
        sid = struct.unpack_from('>H', sdir, pos)[0]
        if sid == 0xFFFF:
            break
        offset = struct.unpack_from('>I', sdir, pos + 0x04)[0]
        rate   = struct.unpack_from('>H', sdir, pos + 0x0E)[0]
        count  = struct.unpack_from('>I', sdir, pos + 0x10)[0]
        coefo  = struct.unpack_from('>I', sdir, pos + 0x1C)[0]
        entries.append((sid, offset, rate, count, coefo))
        pos += 0x20

    print("%d samples" % len(entries))
    for sid, offset, rate, count, coefo in entries:
        # the 0x28-byte coef record: the 16 coefficients are its last 32 bytes
        rec = sdir[coefo:coefo + 0x28]
        if len(rec) < 0x28:
            print("  id %04x: coef record out of range, skipped" % sid)
            continue
        coefs = struct.unpack('>16h', rec[0x08:0x28])
        nbytes = (count + 13) // 14 * 8
        data = samp[offset:offset + nbytes]
        pcm = decode_dsp(data, count, coefs)
        if not pcm:
            continue
        name = os.path.join(outdir, "%04x.wav" % sid)
        with wave.open(name, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate if 4000 <= rate <= 48000 else 32000)
            w.writeframes(struct.pack('<%dh' % len(pcm), *pcm))
        print("  id %04x: %6d samples @ %5d Hz -> %s"
              % (sid, count, rate, os.path.basename(name)))

if __name__ == '__main__':
    main()
