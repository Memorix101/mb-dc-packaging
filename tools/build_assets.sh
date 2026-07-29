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
#   4. custom images custom_assets/*.png  -> mb_data/*.raw
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
        # same scope as vqenc.py --batch: stage dirs and the bg dir only
        case "$(basename "$(dirname "$p")")" in
            st*|bg) ;;
            *) continue ;;
        esac
        o="$out/$(basename "$p" .tpl).vqt"
        if [ "${FORCE:-0}" != "1" ] && [ -f "$o" ] && [ "$o" -nt "$p" ]; then
            continue
        fi
        jobs_list+=("$p")
    done < <(find "$gcsrc" -mindepth 2 -maxdepth 2 -type f -name '*.tpl' -print0)

    if [ "${#jobs_list[@]}" -eq 0 ]; then
        echo "[1/4] VQ textures: up to date"
    else
        echo "[1/4] VQ textures: encoding ${#jobs_list[@]} TPLs on $JOBS cores (this takes a while)"
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
    echo "[1/4] VQ textures: skipped (SKIP_VQ=1)"
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
            echo "[2/4] sfx: $bank bank not in the dump, skipped"
            continue
        fi
        if [ "${FORCE:-0}" != "1" ] && [ -d "$dst" ] && [ -n "$(ls -A "$dst" 2>/dev/null)" ]; then
            continue
        fi
        banks_done=0
        echo "[2/4] sfx: extracting $bank bank"
        python3 "$here/musyx_extract.py" "$sdir" "$samp" "$dst" >/dev/null
    done
    [ "$banks_done" = "1" ] && echo "[2/4] sfx: banks already extracted"
    python3 "$here/name_sfx.py" >/dev/null || true
    echo "[2/4] sfx: $(ls "$custom/audio/sfx" 2>/dev/null | wc -l) named effects in custom_assets/audio/sfx"
else
    echo "[2/4] sfx: skipped (SKIP_SFX=1)"
fi

# --- audio ------------------------------------------------------------
if [ "${SKIP_AUDIO:-0}" != "1" ]; then
    echo "[3/4] audio: converting effects and music"
    "$here/convert_audio.sh"
else
    echo "[3/4] audio: skipped (SKIP_AUDIO=1)"
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
    # bootlogo.raw is not regenerated here: the shipped one does not come
    # from any PNG in custom_assets/. Replace it by hand with
    # tools/png2logo.py <your.png> mb_data/bootlogo.raw
    echo "[4/4] images: done"
else
    echo "[4/4] images: skipped (SKIP_PNG=1)"
fi

echo "Assets ready in $out ($(ls "$out" | wc -l) files)"
