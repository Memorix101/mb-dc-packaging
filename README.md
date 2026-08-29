# mb-dc-packaging

Monkey Ball Remake for SEGA Dreamcast using libmkb - Super Monkey Ball
NTSC-U (GMBE8P)

This kit ships the **pre-built game binary**. You bring the
game data from your own legally acquired GameCube copy and the scripts here
convert it into the Dreamcast formats and pack everything into a `.cdi`
(emulator / CD-R) and an `_sd.iso` (DreamShell SD loader).

No Dreamcast toolchain, no KallistiOS, no compiler needed. (Only some patients on the first run. hehe)

> [!IMPORTANT]  
> This is for alpha testing </br>
> The game is unfinished (work-in-progress) and will crash </br>
> If you find bugs or crash, please open an issue and describe how to reproduce the issue. In some cases, error messages are shown; please take a picture then.

---

## Requirements (Ubuntu / Debian)

```bash
sudo apt install python3 python3-numpy python3-pil ffmpeg
```

| Tool | Needed for |
|---|---|
| `python3` | all converters |
| `python3-numpy` | VQ texture encoder (`tools/vqenc.py`) |
| `ffmpeg` | decoding GameCube music, encoding sound effects and the attract film (RoQ) |
| `mkdcdisc` | bundled in `tools/`, nothing to install |
| `mksdiso` | optional, only for the DreamShell SD-loader `.iso` |

`mksdiso` can be found [here](https://github.com/Nold360/mksdiso)

## Add your game data

Extract your Super Monkey Ball (NTSC-U, GMBE8P) GameCube disc, e.g. with
GCRebuilder or Dolphin ("Extract Entire Disc"), and copy the **`test`
folder** out of it so the layout looks like this:

```
mb-dc-packaging/
  smb1_content/
    test/
    ...
```

Nothing from the GameCube disc is contained in this repository and nothing
you generate from it should be committed.

## Build the image

```bash
tools/make_cdi.sh            # padded image, for burning to CD-R
PAD=0 tools/make_cdi.sh      # smaller image, for emulator / SD card only
```

That is the whole build. It converts the assets (see below) and then
writes:

* `smbdc.cdi` - boot it in Flycast: `flycast smbdc.cdi`
* `smbdc_sd.iso` - for the DreamShell ISO loader, if `mksdiso` is installed

The first run takes a while: **around 40 minutes on an 8-core machine**,
and nearly all of it is the texture encoder chewing through ~170 stage and
background texture sets. It uses every core (`JOBS=n` to limit that). The
audio conversion adds about half a minute, the packing itself seconds.

Every later run reuses what is already converted, so rebuilding after an
asset change is a matter of seconds.

> `PAD=0` images are **not** safe to burn: the padding exists because real
> CD drives read the last sectors of a data track unreliably.

## Options

`tools/make_cdi.sh`:

| Variable | Default | Effect |
|---|---|---|
| `PAD` | `1` | Pad the image for CD-R burning. `PAD=0` = small image, SD/emulator only |
| `ELF` | `smbdc-release.elf` | Use a different game binary |
| `SKIP_ASSETS` | `0` | `1` packs `mb_data/` as it is and runs no conversion |
| `SKIP_SDISO` | `0` | `1` writes only the `.cdi` |
| `MKDCDISC` | bundled | Path to another `mkdcdisc` |

`tools/build_assets.sh` (also accepted by `make_cdi.sh`, it passes them on):

| Variable | Default | Effect |
|---|---|---|
| `JOBS` | CPU count | Parallel texture encoders |
| `FORCE` | `0` | Re-convert everything, ignore up-to-date outputs |
| `SKIP_VQ` | `0` | Skip texture encoding |
| `SKIP_SFX` | `0` | Skip unpacking the sound bank |
| `SKIP_AUDIO` | `0` | Skip audio conversion |
| `SKIP_PNG` | `0` | Skip the custom images |
| `SKIP_VIDEO` | `0` | Skip the attract film |
| `WAV2ADPCM` | unset | Path to the compiled KOS `wav2adpcm`. Faster than the bundled Python encoder and produces the same bytes |

Example, a quick image without re-encoding textures:

```bash
PAD=0 SKIP_VQ=1 tools/make_cdi.sh
```

## Troubleshooting

**"no GameCube data at .../smb1_content/test"** - the dump is missing or one
level too deep. `smb1_content/test/init/common.gma` must exist.

**"missing from your dump: ..."** - the extraction is incomplete. Extract the
whole disc, not a selection.

**No music, or silent effects** - `ffmpeg` is not installed, or the dump has
no `snd/` folder. Re-run `tools/build_assets.sh` and watch the audio lines.

**No attract film, the game boots straight to the title** - `mb_data/attract.roq`
is missing. Your `ffmpeg` has to have the `roqvideo` encoder
(`ffmpeg -encoders | grep roq`); re-run `tools/build_assets.sh`.

**Updated the kit and the music loops click at the seam** - the audio step
re-encodes automatically when `tools/convert_audio.sh` is newer than the
outputs; if in doubt, `FORCE=1 SKIP_VQ=1 tools/build_assets.sh`.

**White or untextured surfaces in game** - the texture step did not run.
Check that `python3-numpy` is installed and that `mb_data/` contains `.vqt`
files.

**"skip (unmapped): <name>"** - that cue has no entry in `name_sfx.py`'s
sample table, so nothing extracts it from the dump. The game runs without
it. All cues the port currently uses are mapped, including the per-character
voice sets, so this should not appear.

**mkdcdisc fails or the disk fills up** - with `PAD=1` the image is around
700 MB; make sure there is enough free space.

---

Super Monkey Ball and all related assets belong to SEGA / Amusement Vision.
This is a fan reimplementation and ships no game data.
