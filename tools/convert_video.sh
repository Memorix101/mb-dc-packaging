#!/usr/bin/env bash
#
# Convert the boot attract video into the RoQ file the game plays.
#
# Input:  custom_assets/attract_intro.mp4   (any resolution/codec ffmpeg reads)
#         custom_assets/attract.wav         optional: the logo audio, cut by hand
# Output: mb_data/attract.roq           silent video, decoded in-game by dreamroq
#         mb_data/mus_logo_intro.adp    the logo audio as a one-shot music track
#
# The source has audio only in its first seconds (the SEGA and Amusement
# Vision logos) and is silent afterwards (measured with ffmpeg silencedetect:
# sound 3.17 s .. 14.29 s, then nothing). The video ships silent; the logo
# audio becomes a normal one-shot music track, and the title theme takes over
# the moment that track ends (attract.c hand-over).
#
# build_assets.sh runs this when the source is newer than the outputs;
# make_cdi.sh packs mb_data/ onto the disc. NOTE: ISO9660 single-dot names.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
src="${1:-$root/custom_assets/attract_intro.mp4}"
out="$root/mb_data"

command -v ffmpeg >/dev/null || { echo "ffmpeg missing (sudo apt install ffmpeg)"; exit 1; }
if [ ! -f "$src" ]; then
    echo "no attract video at $src, skipping"
    exit 0
fi
mkdir -p "$out"

# Seam in seconds: where the source's own audio ends. Re-measure with
#   ffmpeg -i in.mp4 -af silencedetect=noise=-40dB:d=0.3 -f null -
CUT="${CUT:-14.29}"
SIZE="${SIZE:-320:240}"

# --- RoQ, the format we actually ship ------------------------------------
# Dreamroq's decoder hands finished frames and PCM to callbacks, so the game
# draws them itself and keeps control every frame. The video goes out
# SILENT; its original audio becomes a normal one-shot music track below.
ffmpeg -v error -y -i "$src" -vf "scale=$SIZE" -r 30 -c:v roqvideo -an \
    "$out/attract.roq" 2>&1 | grep -v "not power of two" || true
d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out/attract.roq" 2>/dev/null || echo 0)
printf 'video: attract.roq  %s s  %d KB\n' "$d" "$(( $(stat -c%s "$out/attract.roq") / 1024 ))"

# --- the logo sound as our own music track -------------------------------
# Same pipeline the music uses (32 kHz stereo AICA ADPCM, raw interleaved):
# an intro with no loop file, played through snd_dc_music_play_once.
# The bundled Python encoder is the default; WAV2ADPCM= points at the
# compiled KOS tool (same bytes, faster), as in convert_audio.sh.
if [ -n "${WAV2ADPCM:-}" ]; then
    [ -x "$WAV2ADPCM" ] || { echo "WAV2ADPCM=$WAV2ADPCM is not executable"; exit 1; }
    wav2adpcm() { "$WAV2ADPCM" "$@"; }
else
    wav2adpcm() { python3 "$here/wav2adpcm.py" "$@"; }
fi
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
# A separate audio file wins if it is there: custom_assets/attract.wav is
# taken WHOLE (it is cut by hand), otherwise the first $CUT seconds of the
# video's own track are used.
asrc="$root/custom_assets/attract.wav"
if [ -f "$asrc" ]; then
    ffmpeg -v error -y -i "$asrc" -map_metadata -1 -fflags +bitexact \
        -ar 32000 -ac 2 "$tmp/logo.wav"
    echo "audio: from custom_assets/attract.wav"
else
    ffmpeg -v error -y -i "$src" -t "$CUT" -map_metadata -1 -fflags +bitexact \
        -ar 32000 -ac 2 "$tmp/logo.wav"
fi
wav2adpcm -n -i -t "$tmp/logo.wav" "$out/mus_logo_intro.adp"
b=$(stat -c%s "$out/mus_logo_intro.adp")
printf 'audio: mus_logo_intro.adp  %d KB, %.2f s\n' \
    "$(( b / 1024 ))" "$(python3 -c "print($b/32000.0)")"

# The game hands over when the logo track RUNS OUT, so its length decides
# the seam. This frame number is only the fallback for a missing track.
printf 'seam fallback: frame %d (%s s at 30 fps)\n' \
    "$(python3 -c "print(int(round(float('$CUT')*30)))")" "$CUT"
echo "done -> $out"
