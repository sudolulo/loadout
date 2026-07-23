# Loadout

The Steam Deck library manager — a gamepad-driven GUI plus the plumbing behind it:
which games are kept **offline** on the Deck, which **show in Steam**, save sync to the NAS,
and (for PC) automated installs.

## The GUI — `loadout.py`
1280×800, fully drivable from the pad. A left **sidebar** groups navigation into **LIBRARY**
(PC Games, Collections, and a section per console) and **SYSTEM** (Saves, and **Storage** —
the union tiers, a rebuild action, and NAS setup). **D-pad Left** focuses the sidebar (Up/Down
walk the sections, with a live preview); **Right** or **A** drops into the list; the **L1/R1**
bumpers jump straight between sections from anywhere. Two per-game toggles:

- **A — Offline**: copy the game local (playable offline, writable) or free the local copy
  (the NAS copy is never touched).
- **X — Show in Steam**: add/remove the title as a Steam shortcut. **Only** a Steam-toggle
  change triggers the Steam stop/restart + native refresh at Apply — an offline-only change
  copies quietly. Only titles you enable are added.
- **Start — Disk** (only when an SD card is present): choose per game whether an offline copy
  lands on **SD** or **Internal**. The **Where** column shows the pick (`→ SD` / `→ Internal`)
  before Apply, and the disk a game already lives on after. Freeing removes it from wherever it
  actually is.

Only **playable** games are listed — installers (un-installed PC repacks) are hidden.
Rescan = **⧉ View**, Apply = **Y**, Close = **B**, sidebar = **D-pad ←/→** (bumpers **L1/R1**
jump sections), disk = **Start** (keyboard: `d`).

## Overlays — `mount-setup.sh`
A mergerfs union at `~/Emulation/roms` across up to three tiers: **Internal** (RW) → **SD card**
(RW, optional) → a read-only rclone mount of the **NAS**. New downloads appear automatically;
anything not held locally streams. The SD card is **auto-detected** and mirrors the Deck's own
layout — `<card>/Emulation/ROMs` for ROMs (beside the bios/saves/tools they belong with) and
`<card>/Games/PC` for PC games — with the older EmuDeck folder names honoured so an existing card
keeps working; set `rom_sd` in the config to force a path or `"off"` to skip it. All tier paths
come from the same `config.json` the GUI reads, so setup and manager always agree. No SD is fine (Internal + NAS); no NAS is fine too (local-only union — see below). The
**NAS itself is set up from inside the app** — see *NAS setup* below.

## Steam shortcuts — `steam-refresh.sh`, `fix_collections.py`
Loadout manages your Steam shortcuts **natively — no Steam ROM Manager needed, ever**. For ROMs it
learns each system's launch template from your existing shortcuts and writes matching ones
itself (with built-in EmuDeck templates so a fresh device works too), so games launch
identically. PC games get a generated launcher (Proton-wrapped for Windows titles) pointed at
**through the union**, so moving a game between disks never breaks its shortcut. On exit, a flag-watched systemd path unit runs `Loadout.AppImage --refresh`
(`steam-refresh.sh` from inside the AppImage) which — with Steam briefly stopped, guarded
against a live game — reconciles Steam shortcuts with what you've enabled, drops any stale
`offline-manager` shortcut, fetches cover art, writes per-console collections, clears its flag,
and returns you to Game Mode (or restarts Steam on the desktop) exactly once.

## Saves — `deck-saves.sh`, `deck-saves-daemon.sh`, `steam-account.py`
Emulator saves synced to the NAS under the **signed-in Steam account**, so a profile resumes on
whichever Deck you pick up. The daemon pushes on game exit, pulls on idle when the NAS is newer,
and hands the save tree over on a profile switch — never mid-game, never over unsynced progress.

## Wizard PC installs — `wizard/`
Headless install of FitGirl/Inno "wizard" PC repacks under Wine: GUI-drive + a redist
interception proxy, emitting a Proton-wrapped launcher for the installed Windows game.

## Install — the AppImage is a self-contained container
Loadout ships as a **self-updating AppImage** (`Loadout-x86_64.AppImage`). Drop it in
`~/Applications/` and run it. On every launch it installs/refreshes its own systemd `--user`
units — which only ever invoke **the AppImage itself** (`--worker`, `--refresh`,
`--saves-daemon`) — writes a default config, and adds a desktop entry. **Nothing is copied into
your home directory and no script in `~` is ever run**; all logic lives inside the AppImage, so
what runs is always the code in the AppImage you're running. It updates itself: on launch it
checks the releases API and, with your OK (**U**), sha256-verifies and replaces itself in place.

Build it with `packaging/build-appimage.sh` (needs `appimagetool`). Subcommands:
`--worker | --refresh | --saves-daemon | --update | --sync-steam | --mount-setup | --install`.

Then, once: open **Storage → Set up NAS share…** to point Loadout at your NAS, and add
`Loadout.AppImage` to Steam if you want it in Game Mode.

### NAS setup
On the **Storage** page, **Set up NAS share…** takes your SMB **Host**, **Share/path**, and login,
**Test**s the connection, and on **Save** writes an *obscured* rclone remote to
`~/.config/rclone/rclone.conf` (0600) plus the non-secret `remote:path` into `rom_rclone_remote`
in the config — **your password never lands in Loadout's config** — then rebuilds the union.

### Configuration
All paths live in `~/.config/loadout/config.json` (see `config.example.json`);
`$LOADOUT_CONFIG` overrides the location. Defaults target a standard EmuDeck + rclone-union
layout. The save sync's rclone remote is set with `DECK_SAVES_REMOTE` / `DECK_SAVES_BASE`
(default `games` / `games/Saves`). The ROM NAS remote is normally set for you by *NAS setup*
(`rom_rclone_remote`); when that's empty the legacy `$ROM_RCLONE_REMOTE` env var still applies
(default `games:roms`, `"off"` for local-only).

### With an SD card
Two config keys govern the SD tier. `rom_sd`: `""` auto-detects the Deck SD, an explicit path
forces it, `"off"` disables it. `default_target` (`"sd"` / `"internal"`): the disk a newly
pulled-offline game defaults to when an SD exists — and you can flip any individual game with
**Start** (or `d`) in the GUI. Games already on the SD (e.g. an existing EmuDeck library) show
as local and playable — the card's existing folder is used as-is rather than moved. `pc_sd` does
the same for the PC union: **PC games get the same per-game disk choice as ROMs.**

### Cover art (SteamGridDB)
Drop your SteamGridDB API key in `~/.config/loadout/steamgriddb.key` (or set `$LOADOUT_SGDB_KEY`)
and each game shows its cover thumbnail in the list. Covers load lazily per section, in the
background, and are cached under `~/.cache/loadout/covers/`, so a big library is fetched only
once. No key → no covers, and the list looks exactly as before.

### Without a NAS
The manager degrades gracefully: with no rclone mount it simply shows what's local and the
"NAS" side is empty — nothing crashes, nothing is lost (the NAS copy is never touched). Likewise
with no SD card it's a plain Internal + NAS setup and the disk control is inert.
