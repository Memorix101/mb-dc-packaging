#!/usr/bin/env bash
#
# Convert the game audio into Dreamcast formats (mb_data/).
#
# Input:  custom_assets/audio/sfx/*.wav       (effects, from musyx_extract.py
#                                              output renamed to sound.h names
#                                              by tools/name_sfx.py)
#         smb1_content/test/snd/adp/*.adp     (ORIGINAL GC music, DTK ADPCM)
# Output: mb_data/<name>.wav          AICA-ADPCM WAV, 22050 Hz mono (sfx)
#         mb_data/mus_<track>_intro.adp / mus_<track>_loop.adp
#                                      raw interleaved AICA ADPCM, 32 kHz stereo
#
# Only the sounds the game actually uses are converted (see src/sound.h and
# the SMB1_BG_MUSIC map). Needs ffmpeg; the music encoder is tools/
# wav2adpcm.py, so no Dreamcast toolchain is required. Point WAV2ADPCM at the
# compiled KOS wav2adpcm to use that instead - it produces the same bytes and
# is a lot faster.
# Run once (or whenever the source audio changes); make_cdi.sh then packs
# mb_data/ onto the disc automatically. NOTE: single-dot filenames only
# (ISO9660), which the names below already are.

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
src="$root/custom_assets/audio"
out="$root/mb_data"

command -v ffmpeg >/dev/null || { echo "ffmpeg missing (sudo apt install ffmpeg)"; exit 1; }
if [ -n "${WAV2ADPCM:-}" ]; then
    [ -x "$WAV2ADPCM" ] || { echo "WAV2ADPCM=$WAV2ADPCM is not executable"; exit 1; }
    wav2adpcm() { "$WAV2ADPCM" "$@"; }
else
    wav2adpcm() { python3 "$here/wav2adpcm.py" "$@"; }
fi
mkdir -p "$out"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Re-encoding the whole soundtrack costs minutes with the Python encoder, so
# outputs that are newer than their source are left alone. FORCE=1 redoes all.
uptodate() {  # uptodate <output> <source>
    [ "${FORCE:-0}" != "1" ] && [ -f "$1" ] && [ "$1" -nt "$2" ]
}

# --- sound effects: 22050 Hz mono AICA-ADPCM WAV -------------------------
SFX="goal_enter banana_collect banana_bunch_collect fallout ball_woosh \
     ball_hit_soft ball_hit_med ball_hit_hard bumper_hit ball_roll \
     an_ready an_go_1 an_go_2 an_goal an_hurryup an_timeover an_perfect \
     an_fallout an_gameover timer_beep \
     an_count_0 an_count_1 an_count_2 an_count_3 an_count_4 \
     an_count_5 an_count_6 an_count_7 an_count_8 an_count_9 \
     vo_banana vo_banana_bunch vo_land_soft vo_land_med vo_land_hard \
     vo_goal vo_1up menu_pause menu_cursor menu_select \
     vo_tumble1 vo_tumble2 vo_tumble3 vo_tumble4 vo_tumble5 \
     vo_tumble6 vo_tumble7 \
     an_sel_course an_sel_beginner an_sel_advanced an_sel_expert \
     an_sel_master"

# Per-character voice sets: sound.c looks for vo_<cue>_g/_k/_o (MeeMee,
# Baby, GonGon) beside the AiAi base files and falls back to the base when
# a variant is absent. Same cue list, three suffixes.
VOICES="vo_banana vo_banana_bunch vo_land_soft vo_land_med vo_land_hard \
        vo_goal vo_1up vo_tumble1 vo_tumble2 vo_tumble3 vo_tumble4 \
        vo_tumble5 vo_tumble6 vo_tumble7"
for v in $VOICES; do
    for c in g k o; do
        SFX="$SFX ${v}_${c}"
    done
done

for name in $SFX; do
    [ -d "$src/sfx" ] || break
    in=""
    for ext in wav mp3 ogg flac; do
        [ -f "$src/sfx/$name.$ext" ] && { in="$src/sfx/$name.$ext"; break; }
    done
    if [ -z "$in" ]; then
        # Some cues (the rolling loop, the whoosh, the tumble voices) have no
        # entry in name_sfx.py's mapping, so nothing extracts them from the
        # dump. The game runs without them - see README.
        if [ -f "$out/$name.wav" ]; then
            echo "sfx: $name (kept, no source)"
        else
            echo "skip (unmapped): $name"
        fi
        continue
    fi
    # AICA ADPCM (4x smaller than PCM16 - the full PCM bank starved the
    # 2MB sound RAM next to the music stream buffers and the music
    # stuttered). ffmpeg's adpcm_yamaha IS the AICA format and writes the
    # WAV tag KOS expects; the KOS wav2adpcm tool crashed on these files.
    ffmpeg -loglevel error -y -i "$in" -map_metadata -1 -fflags +bitexact \
        -ar 22050 -ac 1 -c:a adpcm_yamaha "$out/$name.wav"
    echo "sfx: $name"
done

# --- music from the ORIGINAL GC dump (snd/adp, DTK ADPCM) ----------------
# stage themes stX -> web-reference track names; _int = intro, _lp = loop,
# plain .adp = one-shot/loop-only, _all = full take (intro running into the
# loop; used as the intro when no _int exists - its tail IS the loop, so
# all -> lp -> lp chains seamlessly). ffmpeg decodes DTK (.adp) natively.
#
# Stream numbering is the DISC's, not the background order. Source of
# truth: smb-decomp src/background.h BACKGROUND_LIST song ids x the
# sound.c stream table (20/21=ST1 ... 38/39=STM):
#   jun=20->st1  wat=22->st2  nig=24->st3  sun=26->st4  spa=28->st5
#   snd=30->st6  ice=32->st7  stm=34->st8  bns=36->stb  mst=38->stm
# The old list here assumed st2=sky/st5=desert/...; that played the water
# theme on every sunset floor (beginner 6-8) and shifted desert/arctic/
# storm/extra by one.
gcadp="$root/smb1_content/test/snd/adp"
# Seamless loop pipeline (the old per-file resample clicked at every seam:
# each 48->32 kHz run has filter warm-up/flush transients at the file
# edges, and the intro->loop and loop->loop joins landed exactly on those
# edges - the "loops a bit disjointed" report). Now the segments are
# decoded to raw PCM, CONCATENATED, resampled as ONE continuous stream and
# split byte-exactly afterwards: every seam the player ever crosses is
# interior to a single resampler run. For the wrap seam the loop is taken
# as the MIDDLE window of lp+lp(+lp), so both of its edges have real
# musical context instead of a filter flush.
mus() {  # mus <track> <gcbase>
    local t="$1" b="$2"
    local in="" lp=""
    if   [ -f "$gcadp/${b}_int.adp" ]; then in="$gcadp/${b}_int.adp"
    elif [ -f "$gcadp/${b}_all.adp" ]; then in="$gcadp/${b}_all.adp"
    fi
    if   [ -f "$gcadp/${b}_lp.adp" ]; then lp="$gcadp/${b}_lp.adp"
    elif [ -f "$gcadp/${b}.adp"    ]; then lp="$gcadp/${b}.adp"
    fi
    [ -z "$in" ] && [ -z "$lp" ] && return
    # The loop's cut offsets depend on the intro length, so intro and loop
    # re-encode together: only skip when every output is newer than every
    # source.
    local stale=0 s
    for s in "$in" "$lp"; do
        [ -n "$s" ] || continue
        if [ -n "$in" ] && ! uptodate "$out/mus_${t}_intro.adp" "$s"; then stale=1; fi
        if [ -n "$lp" ] && ! uptodate "$out/mus_${t}_loop.adp"  "$s"; then stale=1; fi
    done
    [ "$stale" = "0" ] && return
    # decode to raw 48 kHz stereo s16 (sample counts = bytes/4)
    local n_int48=0 n_lp48=0
    : > "$tmp/cat.raw"
    if [ -n "$in" ]; then
        ffmpeg -loglevel error -y -i "$in" -map_metadata -1 -f s16le \
            -ar 48000 -ac 2 "$tmp/int.raw"
        n_int48=$(( $(stat -c %s "$tmp/int.raw") / 4 ))
        cat "$tmp/int.raw" >> "$tmp/cat.raw"
    fi
    if [ -n "$lp" ]; then
        ffmpeg -loglevel error -y -i "$lp" -map_metadata -1 -f s16le \
            -ar 48000 -ac 2 "$tmp/lp.raw"
        n_lp48=$(( $(stat -c %s "$tmp/lp.raw") / 4 ))
        # two copies: [0] = the one we cut, [1] = tail context (no flush
        # edge at the loop end). Loop-only tracks get a third at the front
        # so the loop start has warm-up context too.
        [ -z "$in" ] && cat "$tmp/lp.raw" >> "$tmp/cat.raw"
        cat "$tmp/lp.raw" "$tmp/lp.raw" >> "$tmp/cat.raw"
    fi
    # one continuous 48->32 kHz resample over the whole chain
    ffmpeg -loglevel error -y -f s16le -ar 48000 -ac 2 -i "$tmp/cat.raw" \
        -f s16le -ar 32000 -ac 2 "$tmp/full.raw"
    # output-side sample counts (x2/3, rounded, kept even)
    local n_int32=$(( (n_int48 * 2 + 1) / 3 & ~1 ))
    local n_lp32=$((  (n_lp48  * 2 + 1) / 3 & ~1 ))
    local pre32=$n_int32
    [ -z "$in" ] && pre32=$n_lp32   # loop-only: skip the warm-up copy
    if [ -n "$in" ]; then
        head -c $(( n_int32 * 4 )) "$tmp/full.raw" > "$tmp/seg.raw"
        ffmpeg -loglevel error -y -f s16le -ar 32000 -ac 2 -i "$tmp/seg.raw" \
            -fflags +bitexact "$tmp/m.wav"
        wav2adpcm -n -i -t "$tmp/m.wav" "$out/mus_${t}_intro.adp"
        echo "music: ${t}_intro ($(basename "$in" .adp), seamless)"
    fi
    if [ -n "$lp" ]; then
        dd if="$tmp/full.raw" of="$tmp/seg.raw" bs=1M status=none \
           iflag=skip_bytes,count_bytes \
           skip=$(( pre32 * 4 )) count=$(( n_lp32 * 4 ))
        ffmpeg -loglevel error -y -f s16le -ar 32000 -ac 2 -i "$tmp/seg.raw" \
            -fflags +bitexact "$tmp/m.wav"
        wav2adpcm -n -i -t "$tmp/m.wav" "$out/mus_${t}_loop.adp"
        echo "music: ${t}_loop (seamless)"
    fi
}
if [ -d "$gcadp" ]; then
    mus jungle st1
    mus water  st2
    mus mall   st3
    mus sky    st4
    mus extra  st5
    mus desert st6
    mus arctic st7
    mus storm  st8
    mus bonus  stb
    mus master stm
    mus theme  theme   # STRM_THEME (main theme, loop-only)
    mus adv    adv     # STRM_ADV (attract / title, intro+loop)
    mus sel    sel     # STRM_SEL (course/character select, intro+loop)
else
    echo "GC adp dir not found ($gcadp), skipping music"
fi

echo "done -> $out"
