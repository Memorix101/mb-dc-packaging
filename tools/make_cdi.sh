#!/usr/bin/env bash
#
# Pack the pre-built smbdc ELF plus your own game data into a Dreamcast
# bootable .cdi (and, if mksdiso is installed, an SD-loader .iso).
#
# There is NO compiler and no Dreamcast toolchain involved: smbdc.elf ships
# with this kit. The script converts your GameCube dump into the Dreamcast
# asset formats (tools/build_assets.sh) and packs everything with mkdcdisc.
#
# The ELF carries no embedded data - the game reads everything from
# /cd/mb_data on the disc, which is what gets staged here:
#
#   smb1_content/test/   your extracted GC disc  -> models, textures, music
#   mb_data/             converted + custom data -> overlaid last, wins
#
# Usage:
#   tools/make_cdi.sh [output.cdi]
#
# Env overrides:
#   ELF=path        use another ELF (default: smbdc.elf next to this kit)
#   PAD=0           skip the ~700MB CD-R padding (SD/emulator images only)
#   SKIP_ASSETS=1   pack what is already in mb_data/, run no conversion
#   SKIP_SDISO=1    write only the .cdi, no DreamShell _sd.iso
#   MKDCDISC=path   alternate mkdcdisc binary
#   JOBS, SKIP_VQ, SKIP_AUDIO, FORCE, ...   passed through to build_assets.sh
#
# Run the result in Flycast with, for example:
#   ~/flycast-x86_64.AppImage smbdc.cdi

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
mkdcdisc="${MKDCDISC:-$here/mkdcdisc}"
elf="${ELF:-$root/smbdc.elf}"
out="${1:-$root/smbdc.cdi}"
gcsrc="$root/smb1_content/test"
cdi_name="smbdc"

# --- preflight -----------------------------------------------------------
[ -f "$elf" ] || { echo "ERROR: no game binary at $elf (set ELF=...)" >&2; exit 1; }
[ -x "$mkdcdisc" ] || { echo "ERROR: mkdcdisc not executable at $mkdcdisc" >&2; exit 1; }
command -v python3 >/dev/null || { echo "ERROR: python3 missing (sudo apt install python3)" >&2; exit 1; }
if [ ! -d "$gcsrc" ]; then
    echo "ERROR: no GameCube data at $gcsrc" >&2
    echo "       Extract your own Super Monkey Ball (GMBE8P) disc and copy" >&2
    echo "       its 'test' folder there - see README.md." >&2
    exit 1
fi

# --- assets --------------------------------------------------------------
# Everything the disc needs that is not shipped ready-made: VQ textures,
# sound effects, music, custom images. Incremental, so later runs are quick.
if [ "${SKIP_ASSETS:-0}" = "1" ]; then
    echo "NOTE: SKIP_ASSETS=1 - packing mb_data/ as it is."
else
    "$here/build_assets.sh"
fi

# --- stage the disc data directory: /cd/mb_data --------------------------
# ISO9660 allows only ONE dot per filename; anything like x.gma.lz would be
# silently renamed (x_gma.lz) on the disc and the game would then miss it.
# The three archives the game loads compressed are therefore copied under
# single-dot names here.
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/mb_data"

need() {  # need <source file> [destination name]
    if [ ! -f "$1" ]; then
        echo "ERROR: missing from your dump: ${1#$gcsrc/}" >&2
        exit 1
    fi
    cp "$1" "$stage/mb_data/${2:-$(basename "$1")}"
}

# shared models, animation data and the HUD sprite sheets
for f in init/common.gma init/common.tpl init/common_p.lz \
         motdat.lz motinfo.lz motlabel.bin motskl.bin \
         bmp/bmp_com.tpl bmp/bmp_nml.tpl bmp/bmp_adv.tpl bmp/bmp_sel.tpl; do
    need "$gcsrc/$f"
done

# compressed archives, renamed for ISO9660 (see above)
need "$gcsrc/ape/boy_l.gma.lz" boy_l_gma.lz
need "$gcsrc/ape/boy_l.tpl.lz" boy_l_tpl.lz
need "$gcsrc/init/common.lz"   common_nl.lz

# the other playable characters, plain single-dot names already
for chara in gal_l kid_l gor_l; do
    need "$gcsrc/$chara/$chara.gma"
    need "$gcsrc/$chara/$chara.tpl"
done

# every background and every stage, so nothing the game may ask for is
# missing (some stage dirs in the dump are empty, e.g. st000: find skips them)
cp "$gcsrc"/bg/bg_*.gma "$gcsrc"/bg/bg_*.tpl "$stage/mb_data/"
find "$gcsrc"/st[0-9]* -maxdepth 1 -type f -exec cp {} "$stage/mb_data/" \;

# converted + custom data wins on collisions
if [ -d "$root/mb_data" ]; then
    cp -r "$root"/mb_data/* "$stage/mb_data/"
fi

# Windows/WSL leaves ":Zone.Identifier" companion files next to downloaded
# files; they would take up disc directory entries for nothing.
find "$stage/mb_data" -name '*:Zone.Identifier' -delete

# guard against a half-converted mb_data: without music or VQ textures the
# game boots but plays silent and shows white surfaces
vq=$(find "$stage/mb_data" -name '*.vqt' | wc -l)
mus=$(find "$stage/mb_data" -name 'mus_*.adp' | wc -l)
[ "$vq" -gt 0 ] || echo "WARNING: no .vqt textures staged - stage surfaces will be untextured" >&2
[ "$mus" -gt 0 ] || echo "WARNING: no mus_*.adp staged - the game will have no music" >&2
echo "Staged $(ls "$stage/mb_data" | wc -l) files ($vq VQ textures, $mus music streams)"

# --- pack ----------------------------------------------------------------
# mkdcdisc's default data-track padding is REQUIRED for burned CD-Rs (real
# drives read the last track sectors unreliably) but wastes ~700MB of image
# for SD/emulator testing. PAD=0 skips it (-N).
PAD="${PAD:-1}"
padflag=()
if [ "$PAD" = "0" ]; then
    padflag=(-N)
    echo "NOTE: PAD=0 - this image is for SD/emulator use, do NOT burn it."
fi
"$mkdcdisc" \
    -e "$elf" \
    -D "$stage" \
    -o "$out" \
    -n "$cdi_name" \
    "${padflag[@]}"

echo "Wrote $out"

# --- optional: SD-iso for the DreamShell ISO Loader ----------------------
# mksdiso can fail silently if the output already exists, so remove it first
# and FAIL LOUDLY otherwise (a stale _sd.iso with an old binary costs a debug
# round on hardware). isofix (inside mksdiso) drops bootfile.bin/header.iso
# into the cwd; clean those up.
if [ "${SKIP_SDISO:-0}" = "1" ]; then
    echo "NOTE: SKIP_SDISO=1 - .cdi only, no console _sd.iso written."
elif command -v mksdiso >/dev/null 2>&1; then
    # Pass mksdiso an EXPLICIT output path (its optional 3rd arg, used
    # verbatim). Without it, mksdiso auto-derives the name from
    # basename("$out") through a [^a-zA-Z0-9./] filter that STRIPS
    # underscores and drops the file in the cwd.
    sdiso="${out%.cdi}_sd.iso"
    rm -f "$sdiso"
    if mksdiso -h "$out" "$sdiso"; then
        echo "Wrote $sdiso (mksdiso)"
    else
        echo "ERROR: mksdiso failed, $sdiso NOT written" >&2
        exit 1
    fi
    rm -f bootfile.bin header.iso
else
    echo "NOTE: mksdiso not installed - .cdi only. Install it if you boot"
    echo "      from an SD card through the DreamShell ISO loader."
fi

echo "Done."
