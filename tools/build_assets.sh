#!/usr/bin/env bash
#
# Turn a GameCube Super Monkey Ball dump into the Dreamcast asset set in
# mb_data/. No Dreamcast toolchain needed - everything here is Python/ffmpeg.
#
# Input:  smb1_content/test/          the extracted GC disc (see README.md)
#         custom_assets/              optional own images/sounds
# Output: mb_data/                    what make_cdi.sh puts on the disc
#
# The steps are independent and each one skips files that are already newer
# than their source, so re-running after a partial pass is cheap.
#
#   1. VQ textures   stage/background TPLs -> stNNN.vqt / bg_*.vqt
#   2. sound effects GC MusyX banks       -> custom_assets/audio/sfx/*.wav
#   3. audio         sfx + GC music       -> mb_data/*.wav, mus_*.adp
#   4. custom images custom_assets/*.png  -> mb_data/*.raw, *.vq
#   5. attract video custom_assets/attract_intro.mp4 -> mb_data/attract.roq,
#                                            mus_logo_intro.adp
#
# Usage:
#   tools/build_assets.sh
#
# Env overrides:
#   JOBS=n        parallel VQ encoders (default: number of CPUs)
#   SKIP_VQ=1     skip step 1 (the slow one)
#   SKIP_SFX=1    skip step 2
#   SKIP_AUDIO=1  skip step 3
#   SKIP_PNG=1    skip step 4
#   SKIP_VIDEO=1  skip step 5
#   FORCE=1       re-encode everything, ignore up-to-date outputs

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
gcsrc="$root/smb1_content/test"
out="$root/mb_data"
custom="$root/custom_assets"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"

if [ ! -d "$gcsrc" ]; then
    echo "ERROR: no GameCube data at $gcsrc" >&2
    echo "       Extract your Super Monkey Ball (GMBE8P) disc and copy its" >&2
    echo "       'test' folder to smb1_content/test - see README.md." >&2
    exit 1
fi
mkdir -p "$out"

have_py_mod() { python3 -c "import $1" >/dev/null 2>&1; }

# --- VQ textures ------------------------------------------------------
# The PVR cannot read GameCube textures directly, so every stage and
# background TPL is re-encoded offline into a .vqt sidecar (see vqenc.py).
# This is by far the longest step: ~10 s per stage on one core, which is why
# it runs JOBS files at a time. Outputs are deterministic and incremental.
if [ "${SKIP_VQ:-0}" != "1" ]; then
    if ! have_py_mod numpy; then
        echo "ERROR: python3 numpy missing (sudo apt install python3-numpy)" >&2
        exit 1
    fi
    jobs_list=()
    while IFS= read -r -d '' p; do
        # same scope as vqenc.py --batch: stage dirs and the bg dir, plus
        # the one sprite sheet that is drawn VQ-compressed (ranking screen,
        # src/rankscr.c). The other bmp_*.tpl sheets must NOT get a sidecar:
        # their callers draw plain 16 bpp tiles.
        case "$(basename "$(dirname "$p")")/$(basename "$p")" in
            st*/*|bg/*|bmp/bmp_rnk.tpl) ;;
            *) continue ;;
        esac
        o="$out/$(basename "$p" .tpl).vqt"
        if [ "${FORCE:-0}" != "1" ] && [ -f "$o" ] && [ "$o" -nt "$p" ]; then
            continue
        fi
        jobs_list+=("$p")
    done < <(find "$gcsrc" -mindepth 2 -maxdepth 2 -type f -name '*.tpl' -print0)

    if [ "${#jobs_list[@]}" -eq 0 ]; then
        echo "[1/5] VQ textures: up to date"
    else
        echo "[1/5] VQ textures: encoding ${#jobs_list[@]} TPLs on $JOBS cores (this takes a while)"
        export VQENC="$here/vqenc.py" VQOUT="$out"
        printf '%s\0' "${jobs_list[@]}" | xargs -0 -r -P "$JOBS" -n1 sh -c '
            b=$(basename "$1" .tpl)
            if python3 -W ignore "$VQENC" "$1" "$VQOUT/$b.vqt" >/dev/null; then
                echo "  vq $b"
            else
                echo "  vq FAILED: $1" >&2
            fi
        ' sh
    fi
else
    echo "[1/5] VQ textures: skipped (SKIP_VQ=1)"
fi

# --- sound effects out of the GC MusyX banks --------------------------
# musyx_extract.py dumps a whole bank to numbered wavs, name_sfx.py copies
# the ones the game asks for (src/sound.h) to their names. Sounds that are
# not in that mapping (looping macros such as ball_roll) simply stay absent
# and the next step skips them.
if [ "${SKIP_SFX:-0}" != "1" ]; then
    banks_done=1
    for bank in allse comn; do
        sdir="$gcsrc/snd/mkb/$bank.sdir"
        samp="$gcsrc/snd/mkb/$bank.samp"
        case "$bank" in
            allse) dst="$custom/audio/extracted" ;;
            comn)  dst="$custom/audio/extracted_comn" ;;
        esac
        if [ ! -f "$sdir" ] || [ ! -f "$samp" ]; then
            echo "[2/5] sfx: $bank bank not in the dump, skipped"
            continue
        fi
        if [ "${FORCE:-0}" != "1" ] && [ -d "$dst" ] && [ -n "$(ls -A "$dst" 2>/dev/null)" ]; then
            continue
        fi
        banks_done=0
        echo "[2/5] sfx: extracting $bank bank"
        python3 "$here/musyx_extract.py" "$sdir" "$samp" "$dst" >/dev/null
    done
    [ "$banks_done" = "1" ] && echo "[2/5] sfx: banks already extracted"
    python3 "$here/name_sfx.py" >/dev/null || true
    echo "[2/5] sfx: $(ls "$custom/audio/sfx" 2>/dev/null | wc -l) named effects in custom_assets/audio/sfx"
else
    echo "[2/5] sfx: skipped (SKIP_SFX=1)"
fi

# --- audio ------------------------------------------------------------
if [ "${SKIP_AUDIO:-0}" != "1" ]; then
    echo "[3/5] audio: converting effects and music"
    "$here/convert_audio.sh"
else
    echo "[3/5] audio: skipped (SKIP_AUDIO=1)"
fi

# --- custom images ----------------------------------------------------
# Loose .raw textures the game loads instead of GC art. Every one is
# optional: mb_data/ already ships the converted defaults, and dropping your
# own PNG into custom_assets/ replaces it on the next run.
if [ "${SKIP_PNG:-0}" != "1" ]; then
    conv() {  # conv <converter> <source png> <output raw>
        [ -f "$custom/$2" ] || return 0
        if ! have_py_mod PIL; then
            echo "WARNING: python3 Pillow missing, keeping the shipped $3" >&2
            echo "         (sudo apt install python3-pil)" >&2
            return 0
        fi
        if python3 "$here/$1" "$custom/$2" "$out/$3"; then
            echo "  $3 <- custom_assets/$2"
        else
            echo "WARNING: $1 failed, keeping the previous $3" >&2
        fi
    }
    conv png2star.py beautifulstar.png     star.raw
    conv png2star.py sparkle_starring.png  sparkle_ring.raw
    conv png2icon.py goal.png              goalicon.raw
    conv png2bg.py   title_bg.png          title_bg.raw
    conv png2logo.py boot_logo.png         bootlogo.raw
    # How-to-play controller diagram (pause menu). Offline k-means VQ keeps
    # the coloured pad buttons that the runtime encoder washed out; needs
    # numpy on top of Pillow (same package as the texture step).
    conv png2vq.py   dc_controller.png     dc_controller.vq
    echo "[4/5] images: done"
else
    echo "[4/5] images: skipped (SKIP_PNG=1)"
fi

# --- attract video -----------------------------------------------------
# The boot attract film (custom_assets/attract_intro.mp4, ships with the
# kit) becomes a silent RoQ plus the logo audio as a one-shot music track.
# Incremental like the rest; without ffmpeg's roqvideo encoder the game
# simply boots straight to the title (attract.c probes for the file).
if [ "${SKIP_VIDEO:-0}" != "1" ]; then
    vsrc="$custom/attract_intro.mp4"
    if [ ! -f "$vsrc" ]; then
        echo "[5/5] video: no custom_assets/attract_intro.mp4, skipped"
    elif [ "${FORCE:-0}" != "1" ] && [ -f "$out/attract.roq" ] \
         && [ "$out/attract.roq" -nt "$vsrc" ] \
         && [ -f "$out/mus_logo_intro.adp" ] \
         && [ "$out/mus_logo_intro.adp" -nt "$vsrc" ] \
         && [ "$out/mus_logo_intro.adp" -nt "$custom/attract.wav" ]; then
        echo "[5/5] video: up to date"
    else
        echo "[5/5] video: encoding the attract film"
        "$here/convert_video.sh" "$vsrc"
    fi
else
    echo "[5/5] video: skipped (SKIP_VIDEO=1)"
fi

echo "Assets ready in $out ($(ls "$out" | wc -l) files)"
