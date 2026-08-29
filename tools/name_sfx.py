#!/usr/bin/env python3
# Copy extracted MusyX samples (musyx_extract.py output) to the named sfx
# files the game loads (see src/sound.h), based on the SoundReq-id ->
# MusyX-define -> sample-id chain recovered from allse.proj/pool and the
# smb-decomp call sites:
#
#   hud.c:1567  READY banner   -> id 4      game.c:363  hurry up -> id 7
#   hud.c:1600  GO banner      -> id 5      game.c:417  time over-> 0x128
#   ball.c:1667 goal enter     -> id 0x1E   ball.c:1710 goal announcer 0x126
#   item_coin.c banana single/bunch -> 0x281F/0x2820 (low word 0x1F/0x20)
#   ball.c ~2033 impact family -> 0x13/0x14/0x15 (soft/med/hard, consecutive)
#
# The ids below come from tools/musyx_map.py, which resolves the FULL chain
# automatically (game id -> g_soundDesc -> proj define -> pool macro
# startSample -> sdir sample) and matches every ear-verified id from
# 2026-07-03 (ready/go/hurry/timeover/countdown digits). No more listening
# through 185 wavs: run `python3 tools/musyx_map.py <game ids...>` for any
# new call site found in the decomp.
#
# Usage: python3 tools/name_sfx.py
# Then:  tools/convert_audio.sh && PAD=0 tools/make_cdi.sh

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BANKS = {
    'allse': os.path.join(ROOT, 'custom_assets/audio/extracted'),
    'comn':  os.path.join(ROOT, 'custom_assets/audio/extracted_comn'),
}
OUT = os.path.join(ROOT, 'custom_assets/audio/sfx')

# name -> (bank, sample id). LISTENING RESULT (user, via the tSR player /
# extracted wavs): announcer voices live in the COMN bank, gameplay effects
# in ALLSE. Fill ids as they get identified; unknown = None.
# Identified by ear (user, 2026-07-03, via the tSR allse sheet):
#   ready 0x01D5, go 0x0196, goal 0x018D, hurry-up 0x019D,
#   time over 0x022E, game over 0x016D, fallout voice 0x0159,
#   fallout sound 0x0158, countdown digits 0x013A ("0") .. 0x0143 ("9"),
#   per-second timer beep 0x01B2. Multiple go/goal variations exist.
MAPPING = {
    'goal_enter':           ('allse', 0x0001),  # 2.2s jingle (verify)
    'goal_tape':            ('allse', 0x0203),  # goal tape break
    'name_ok':              ('allse', 0x0204),  # name entry commit
    'title_start':          ('allse', 0x0201),  # START on the title: GC id
                                                # 0x162 = SEB_SE_JGL_SEPCM_3
    # gameplay SE (musyx_map: item_coin.c ids 3/0x39, ball.c 0x12/13/14,
    # stobj.c bumper 0x5011 -> low bits 0x11)
    'banana_collect':       ('allse', 0x0201),  # JGL_SEPCM_3
    'banana_bunch_collect': ('allse', 0x0202),  # JGL_SE034UP_1
    'ball_hit_soft':        ('allse', 0x01FC),  # id 0x12, BALL_SEPCM_8
    'ball_hit_med':         ('allse', 0x01F8),  # id 0x13, BALL_SEPCM_4
    'ball_hit_hard':        ('allse', 0x01FD),  # id 0x14, BALL_SEPCM_9
    'bumper_hit':           ('allse', 0x01BF),  # id 0x11 (via 0x5011)
    'ball_roll':            ('allse', 0x00E3),  # rolling loop
    'ball_woosh':           ('comn',  0x0051),  # air whoosh, only comn entry
    'fallout':              ('allse', 0x0158),  # falling sfx (0x0159 = voice)
    'an_ready':             ('allse', 0x01D5),
    'an_go_1':              ('allse', 0x0196),
    'an_go_2':              ('allse', 0x0196),  # variations exist; same for now
    'an_goal':              ('allse', 0x018D),
    'an_hurryup':           ('allse', 0x019D),
    'an_timeover':          ('allse', 0x022E),
    'an_perfect':           ('allse', 0x01C5),  # id 0x48, NAR_PERFECT
    'an_fallout':           ('allse', 0x0159),  # "Fall out!" voice
    'an_gameover':          ('allse', 0x016D),  # ear-verified
    # countdown announcer digits (game.c countdownSounds 0x23.. -> nar)
    'an_count_0':           ('allse', 0x013A),
    'an_count_1':           ('allse', 0x013B),
    'an_count_2':           ('allse', 0x013C),
    'an_count_3':           ('allse', 0x013D),
    'an_count_4':           ('allse', 0x013E),
    'an_count_5':           ('allse', 0x013F),
    'an_count_6':           ('allse', 0x0140),
    'an_count_7':           ('allse', 0x0141),
    'an_count_8':           ('allse', 0x0142),
    'an_count_9':           ('allse', 0x0143),
    'timer_beep':           ('allse', 0x01B2),  # per-second beep
    # course-select announcer (menu), all from the comn bank
    'an_sel_course':        ('comn',  0x0219),
    'an_sel_beginner':      ('comn',  0x0107),
    'an_sel_advanced':      ('comn',  0x00E4),
    'an_sel_expert':        ('comn',  0x0156),
    'an_sel_master':        ('comn',  0x01A7),
    'an_sel_mode':          ('comn',  0x021C),  # "select mode"
    'an_sel_players':       ('comn',  0x019C),  # "select number of players"
    'an_sel_stage':         ('comn',  0x021D),  # "select stage" (practice)
    'an_thanks':            ('comn',  0x022B),  # "thank you for playing"
    # AiAi (boy group) voice set - musyx_map on the voice call sites,
    # charaId 0 picks the boy entry (VO1_*)
    'vo_banana':            ('allse', 0x0125),  # 0x281F single banana
    'vo_banana_bunch':      ('allse', 0x011A),  # 0x2820 bunch
    'vo_land_soft':         ('allse', 0x011E),  # id 0x17, COLI5
    'vo_land_med':          ('allse', 0x011C),  # id 0x18, COLI3
    'vo_land_hard':         ('allse', 0x011F),  # id 0x1A, COLI7
    'vo_start':             ('allse', 0x0118),  # id 0x1E, "let's go" when the
                                                # ball becomes playable
                                                # (BOYH_START1)
    'vo_cheer':             ('allse', 0x010D),  # id 0x59, goal / name entry
                                                # cheer (BOYH_GOAL1)
    'vo_1up':               ('allse', 0x0110),  # id 0x52, LAUGH2
    # free-tumble panic voices: BOYH_OCHISOU 1,2,3,5,7,8,9, the random
    # table ball_sound picks from while the ball falls (sound.h)
    'vo_tumble1':           ('allse', 0x0111),
    'vo_tumble2':           ('allse', 0x0112),
    'vo_tumble3':           ('allse', 0x0113),
    'vo_tumble4':           ('allse', 0x0114),
    'vo_tumble5':           ('allse', 0x0115),
    'vo_tumble6':           ('allse', 0x0116),
    'vo_tumble7':           ('allse', 0x0117),
    # Per-character voice sets: MeeMee (_g, VO2 girl), Baby (_k, VO3) and
    # GonGon (_o, goli). sound.c loads vo_<cue>_g/_k/_o next to the AiAi
    # base files and swaps the set with the chara; a missing variant falls
    # back to AiAi at play time.
    # Some groups have fewer distinct takes than AiAi, so entries repeat:
    # Baby reuses its land-med sample for land-hard, and the GonGon and
    # MeeMee tumble sets cycle through their shorter shock/panic sets.
    'vo_banana_g':          ('allse', 0x017A),
    'vo_banana_k':          ('allse', 0x00F9),
    'vo_banana_o':          ('allse', 0x0070),
    'vo_banana_bunch_g':    ('allse', 0x0178),
    'vo_banana_bunch_k':    ('allse', 0x00F7),
    'vo_banana_bunch_o':    ('allse', 0x0075),
    'vo_land_soft_g':       ('allse', 0x017D),
    'vo_land_soft_k':       ('allse', 0x00FA),
    'vo_land_soft_o':       ('allse', 0x0077),
    'vo_land_med_g':        ('allse', 0x017F),
    'vo_land_med_k':        ('allse', 0x00FB),
    'vo_land_med_o':        ('allse', 0x0078),
    'vo_land_hard_g':       ('allse', 0x0180),
    'vo_land_hard_k':       ('allse', 0x00FB),
    'vo_land_hard_o':       ('allse', 0x0079),
    'vo_start_g':           ('allse', 0x0184),
    'vo_start_k':           ('allse', 0x00FE),
    'vo_start_o':           ('allse', 0x0071),
    'vo_cheer_g':           ('allse', 0x0184),  # MeeMee has one take for both
    'vo_cheer_k':           ('allse', 0x00ED),
    'vo_cheer_o':           ('allse', 0x0073),
    'vo_1up_g':             ('allse', 0x0185),
    'vo_1up_k':             ('allse', 0x00FF),
    'vo_1up_o':             ('allse', 0x0065),
    'vo_tumble1_g':         ('allse', 0x016F),
    'vo_tumble1_k':         ('allse', 0x00EE),
    'vo_tumble1_o':         ('allse', 0x0077),
    'vo_tumble2_g':         ('allse', 0x0170),
    'vo_tumble2_k':         ('allse', 0x00EF),
    'vo_tumble2_o':         ('allse', 0x0078),
    'vo_tumble3_g':         ('allse', 0x0171),
    'vo_tumble3_k':         ('allse', 0x00F0),
    'vo_tumble3_o':         ('allse', 0x0079),
    'vo_tumble4_g':         ('allse', 0x0172),
    'vo_tumble4_k':         ('allse', 0x00F1),
    'vo_tumble4_o':         ('allse', 0x007A),
    'vo_tumble5_g':         ('allse', 0x0173),
    'vo_tumble5_k':         ('allse', 0x00F2),
    'vo_tumble5_o':         ('allse', 0x0077),
    'vo_tumble6_g':         ('allse', 0x016F),
    'vo_tumble6_k':         ('allse', 0x00F3),
    'vo_tumble6_o':         ('allse', 0x0078),
    'vo_tumble7_g':         ('allse', 0x0170),
    'vo_tumble7_k':         ('allse', 0x00EE),
    'vo_tumble7_o':         ('allse', 0x0079),
    # pause menu (pause_menu.c 0x70 open / 0x6F cursor / 0x6E select;
    # DMY_CODE aliases resolved by the walk-back in musyx_map.py)
    'menu_pause':           ('allse', 0x020E),
    'menu_cursor':          ('allse', 0x0206),
    'menu_select':          ('allse', 0x020F),
}
TODO = []

def main():
    os.makedirs(OUT, exist_ok=True)
    todo = []
    for name, (bank, sid) in sorted(MAPPING.items()):
        if sid is None:
            todo.append('%s (bank %s)' % (name, bank))
            continue
        src = os.path.join(BANKS[bank], '%04x.wav' % sid)
        if not os.path.isfile(src):
            print('MISSING %s %04x for %s' % (bank, sid, name),
                  file=sys.stderr)
            continue
        shutil.copyfile(src, os.path.join(OUT, name + '.wav'))
        print('%-22s <- %s/%04x.wav' % (name, bank, sid))
    if todo:
        print('\nstill unmapped (identify by ear, then fill MAPPING):')
        for t in todo:
            print('  ' + t)

if __name__ == '__main__':
    main()
