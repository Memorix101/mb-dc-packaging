#!/usr/bin/env python3
"""PCM16 WAV -> AICA ADPCM, a drop-in replacement for the KOS wav2adpcm tool.

Exists so the packaging kit needs no Dreamcast toolchain at all: the music
converter (tools/convert_audio.sh) only ever calls wav2adpcm with "-t -i -n"
(to-adpcm, interleaved stereo, headerless), and that is what this implements.

The encoder is a straight port of KOS utils/wav2adpcm/wav2adpcm.c (AICA ADPCM
== YMZ280B ADPCM with swapped nibbles; codec by superctr, public domain) and
produces byte-identical output for that flag combination. Mono input is
encoded as a single stream; stereo is deinterleaved, encoded per channel and
re-interleaved nibble-wise, which is the layout src/sound.c streams.

Usage:
    wav2adpcm.py -t -i -n in.wav out.adp
    wav2adpcm.py in.wav out.adp          (same thing, flags are the default)

Only 16-bit PCM input is accepted. Pure Python, so a full soundtrack takes a
couple of minutes; set WAV2ADPCM to the compiled KOS tool to skip that.
"""
import array
import struct
import sys

STEP_TABLE = (230, 230, 230, 230, 307, 409, 512, 614)


def pcm2adpcm(pcm, start, count):
    """Encode count 16-bit samples from pcm[start:] into a bytearray."""
    out = bytearray((count + 1) // 2)
    step_size = 127
    history = 0
    buf_sample = 0
    nibble = 0
    o = 0
    for i in range(start, start + count):
        # dropping the low 3 bits of the input takes some noise out
        step = (pcm[i] & -8) - history
        # abs(step) << 16 overflows 32-bit int in the C original for very
        # loud transients; the wrapped negative then reads back as a huge
        # unsigned and saturates the code. Reproduced here so the output
        # stays byte-identical.
        num = abs(step) << 16
        if num >= 0x80000000:
            code = 7
        else:
            code = num // (step_size << 14)
            if code > 7:
                code = 7
        if step < 0:
            code |= 8
        # even samples go in the low nibble, odd ones in the high nibble:
        # the AICA decodes the low nibble of a byte first
        if not nibble:
            buf_sample = code & 0x0F
        else:
            out[o] = buf_sample | (code << 4)
            o += 1
        nibble ^= 1

        # ymz_step: advance history/step_size exactly as the decoder will
        delta = code & 7
        diff = ((1 + (delta << 1)) * step_size) >> 3
        if diff > 32767:
            diff = 32767
        nstep = (STEP_TABLE[delta] * step_size) >> 8
        if code & 8:
            history -= diff
        else:
            history += diff
        step_size = 127 if nstep < 127 else (24576 if nstep > 24576 else nstep)
        history = -32768 if history < -32768 else (32767 if history > 32767 else history)
    return out


def interleave_adpcm(body, half):
    """Merge the two channel halves of body nibble-wise (left = high nibble).

    Reads exactly like the C original, which keeps both channels in one
    buffer: the left half starts at 0, the right at half. With an odd byte
    count the tail indices run past the right half; those reads land on the
    (zeroed) slack byte, so they are clamped to 0 here.
    """
    n = len(body)
    out = bytearray(n)
    for i in range(n):
        sh = (i % 2) * 4
        j = i // 2
        lo = body[j] if j < n else 0
        hi = body[half + j] if half + j < n else 0
        out[i] = ((hi >> sh) & 0xF) | (((lo >> sh) & 0xF) << 4)
    return out


def read_wav(path):
    """Return (channels, rate, samples) for a 16-bit PCM WAV file."""
    with open(path, 'rb') as f:
        data = f.read()
    if data[0:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError('%s: not a RIFF/WAVE file' % path)
    fmt = None
    pcm = None
    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack_from('<I', data, pos + 4)[0]
        body = pos + 8
        if cid == b'fmt ':
            fmt = struct.unpack_from('<HHIIHH', data, body)
        elif cid == b'data':
            pcm = data[body:body + size]
            break
        pos = body + size + (size & 1)
    if fmt is None or pcm is None:
        raise ValueError('%s: missing fmt or data chunk' % path)
    tag, channels, rate, _bps, _align, bits = fmt
    if tag != 1 or bits != 16:
        raise ValueError('%s: need 16-bit PCM (got format %#x, %d bits)'
                         % (path, tag, bits))
    if channels not in (1, 2):
        raise ValueError('%s: need mono or stereo (got %d channels)'
                         % (path, channels))
    samples = array.array('h')
    samples.frombytes(pcm[:len(pcm) & ~1])
    if sys.byteorder == 'big':
        samples.byteswap()
    return channels, rate, samples


def convert(infile, outfile):
    channels, _rate, pcm = read_wav(infile)
    # output size is derived from the PCM byte count, rounded up like the C
    # tool does, so a stream with an odd sample count keeps its trailing byte
    pcmsize = len(pcm) * 2
    adpcmsize = ((pcmsize + 3) & ~3) // 4
    body = bytearray(adpcmsize)
    if channels == 1:
        enc = pcm2adpcm(pcm, 0, len(pcm))
        body[:min(len(enc), adpcmsize)] = enc[:adpcmsize]
    else:
        half = adpcmsize // 2
        per_ch = pcmsize // 4
        for ch, base in ((0, 0), (1, half)):
            enc = pcm2adpcm(pcm[ch::2], 0, per_ch)
            body[base:base + min(len(enc), half)] = enc[:half]
        body = interleave_adpcm(body, half)
    with open(outfile, 'wb') as f:
        f.write(body)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith('-')]
    flags = [a for a in argv[1:] if a.startswith('-')]
    for f in flags:
        if f not in ('-t', '-i', '-n'):
            print('%s: unsupported flag %s (only -t -i -n)' % (argv[0], f),
                  file=sys.stderr)
            return 1
    if len(args) != 2:
        print(__doc__)
        return 1
    # This writes a headerless stream and, for stereo, the interleaved
    # layout. Refuse rather than quietly hand back a different format than
    # the flags ask for.
    if '-n' not in flags:
        print('%s: only headerless output (-n) is implemented' % argv[0],
              file=sys.stderr)
        return 1
    if '-i' not in flags and read_wav(args[0])[0] > 1:
        print('%s: stereo output is always interleaved, pass -i' % argv[0],
              file=sys.stderr)
        return 1
    convert(args[0], args[1])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
