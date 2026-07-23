# offline-manager

The Steam Deck library manager — a gamepad-driven GUI plus the plumbing behind it:
which games are kept **offline** on the Deck, which **show in Steam**, save sync to the NAS,
and (for PC) automated installs.

## The GUI — `offline-manager.py`
1280×800, fully drivable from the pad. Per-console tabs plus **PC Games**, **Collections**
(whole-console ROM sets) and **Saves**. Two per-game toggles:

- **A — Offline**: copy the game local (playable offline, writable) or free the local copy
  (the NAS copy is never touched).
- **X — Show in Steam**: add/remove the title as a Steam shortcut. **Only** a Steam-toggle
  change triggers the Steam stop/restart + SRM re-run at Apply — an offline-only change copies
  quietly. Only titles you enable are added.
- **Start — Disk** (only when an SD card is present): choose per game whether an offline copy
  lands on **SD** or **Internal**. The **Where** column shows the pick (`→ SD` / `→ Internal`)
  before Apply, and the disk a game already lives on after. Freeing removes it from wherever it
  actually is.

Only **playable** games are listed — installers (un-installed PC repacks) are hidden.
Rescan = **⧉ View**, Apply = **Y**, Close = **B**, tabs = **L1/R1** or D-pad, disk = **Start**
(keyboard: `d`).

## Overlays — `mount-setup.sh`
A mergerfs union at `~/Emulation/roms` across up to three tiers: **Internal** (RW) → **SD card**
(RW, optional) → a read-only rclone mount of the **NAS**. New downloads appear automatically;
anything not held locally streams. The SD card is **auto-detected** (the first Deck mount holding
an `Emulation/roms(-local)` tree); set `rom_sd` in the config to force a path or `"off"` to skip
it. All tier paths come from the same `config.json` the GUI reads, so setup and manager always
agree. No SD is fine (Internal + NAS); no NAS is fine too (local-only union — see below).

## SRM automation — `srm-refresh.sh`, `fix_collections.py`, `offline-sync.sh`
Rebuild the Steam ROM Manager shortcuts + per-console collections without leaving Gaming Mode
(works around SRM needing an X server while silently skipping categories when Steam is up).
`offline-sync.sh` is a flag-watched systemd path unit that runs the refresh on Apply.

## Saves — `deck-saves.sh`, `deck-saves-daemon.sh`, `steam-account.py`
Emulator saves synced to the NAS under the **signed-in Steam account**, so a profile resumes on
whichever Deck you pick up. The daemon pushes on game exit, pulls on idle when the NAS is newer,
and hands the save tree over on a profile switch — never mid-game, never over unsynced progress.

## Wizard PC installs — `wizard/`
Headless install of FitGirl/Inno "wizard" PC repacks under Wine: GUI-drive + a redist
interception proxy, emitting a Proton-wrapped launcher for the installed Windows game.

## Deploy
Copy the scripts to `~` on each Deck and the `systemd/` units to `~/.config/systemd/user/`.
See `mount-setup.sh` / `ps3-esde-setup.sh` for the one-time host setup.

## Install (shippable)

```bash
./install.sh              # scripts + systemd --user units + a default config
```

Then:
1. `mount-setup.sh` — provision the mergerfs/rclone union once (edit it for your NAS/remote).
2. Add `offline-manager.py` to Steam as a non-Steam game (or launch it however you like).

### Configuration
All paths live in `~/.config/offline-manager/config.json` (see `config.example.json`);
`$OFFLINE_MANAGER_CONFIG` overrides the location. Defaults target a standard EmuDeck +
rclone-union layout. The save sync's rclone remote is set with `DECK_SAVES_REMOTE` /
`DECK_SAVES_BASE` (default `games` / `games/Saves`); the ROM NAS remote for `mount-setup.sh` is
`ROM_RCLONE_REMOTE` (default `games:roms`, `"off"` for local-only).

### With an SD card
Two config keys govern the SD tier. `rom_sd`: `""` auto-detects the Deck SD, an explicit path
forces it, `"off"` disables it. `default_target` (`"sd"` / `"internal"`): the disk a newly
pulled-offline game defaults to when an SD exists — and you can flip any individual game with
**Start** (or `d`) in the GUI. Games already on the SD (e.g. an existing EmuDeck library) show
as local and playable. PC games stay on internal storage.

### Without a NAS
The manager degrades gracefully: with no rclone mount it simply shows what's local and the
"NAS" side is empty — nothing crashes, nothing is lost (the NAS copy is never touched). Likewise
with no SD card it's a plain Internal + NAS setup and the disk control is inert.
