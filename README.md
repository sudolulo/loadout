# Loadout

The Steam Deck library manager — a gamepad-driven GUI plus the plumbing behind it:
which games are kept **offline** on the Deck, which **show in Steam**, save sync to the NAS,
and (for PC) automated installs.

## The GUI — `loadout.py`
1280×800, fully drivable from the pad. A left **sidebar** groups navigation into **LIBRARY**
(PC Games, Collections, and a section per console) and **SYSTEM** (Saves, **Storage** — union
tiers, rebuild, prune, diagnostics — and **Settings** — the SMB share, SteamGridDB key, default
disk and SD-card toggle). **D-pad Left** focuses the sidebar (Up/Down
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
  actually is. Pressing it on a game **already on the Deck** relocates it (`Internal → SD`): the
  copy is verified on the new disk before the old one is reclaimed, so an interrupted move never
  loses the game. Shortcuts point through the union, so moving disks never breaks them.

Only **playable** games are listed. Loadout works out what a PC game runs by **looking in its
folder** (native Linux binary first, else the largest non-installer `.exe`), so a manifest is
optional — and an un-installed repack, whose only executables are `setup.exe` and archive tools,
stays hidden until it is installed.
Rescan = **⧉ View**, Apply = **Y**, Close = **B**, sidebar = **D-pad ←/→** (bumpers **L1/R1**
jump sections), disk = **Start** (keyboard: `d`), **L2/R2** jump to the next starting letter.
A copy running in the background shows live in the header.

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
identically. A PC game is added the normal way — the shortcut runs the game's own executable
(through the union, so moving it between disks never breaks the shortcut), and a Windows title
gets a Steam **compatibility tool** so Steam owns its Proton prefix and its saves land in
`steamapps/compatdata` like every other game's. On exit, a flag-watched systemd path unit runs `Loadout.AppImage --refresh`
(`steam-refresh.sh` from inside the AppImage) which — with Steam briefly stopped, guarded
against a live game — reconciles Steam shortcuts with what you've enabled, drops any stale
`offline-manager` shortcut, fetches cover art, writes per-console collections, clears its flag,
and returns you to Game Mode (or restarts Steam on the desktop) exactly once.

## Saves — `deck-saves.sh`, `deck-saves-daemon.sh`, `steam-account.py`
Game saves synced to the NAS under the **signed-in Steam account**, so a profile resumes on
whichever Deck you pick up. Emulator saves (`~/Emulation/{saves,storage}`) plus Windows-game saves
from the Proton prefixes Steam keeps for **non-Steam shortcuts** in `steamapps/compatdata` —
filtered to the user profile, so the ~1 GB Windows install in each prefix is never uploaded and
ordinary prefix churn never reads as unsynced progress. Real Steam games are Steam Cloud's job. The daemon pushes on game exit, pulls on idle when the NAS is newer,
and hands the save tree over on a profile switch — never mid-game, never over unsynced progress.

## PC installs are the game farm's job — not Loadout's
Turning a FitGirl/Inno repack into a playable game happens **upstream, on the NAS**
(`flan/game-farm`, `code/wizard`), where the release already lives and the CPU is. A Deck would
otherwise pull tens of GB of archives over WiFi, decompress them on a handheld, and repeat the
whole thing per Deck for a byte-identical result. Loadout **consumes** installed games: it decides
which live on this Deck, puts them in Steam, and syncs their saves. An un-installed repack is
shown as **not installed** rather than hidden, so you can tell "missing" from "not built yet".

## Install — the AppImage is a self-contained container
Loadout ships as a **self-updating AppImage** (`Loadout-x86_64.AppImage`). Drop it in
`~/Applications/` and run it. On every launch it installs/refreshes its own systemd `--user`
units — which only ever invoke **the AppImage itself** (`--worker`, `--refresh`,
`--saves-daemon`) — writes a default config, and adds a desktop entry. **Nothing is copied into
your home directory and no script in `~` is ever run**; all logic lives inside the AppImage, so
what runs is always the code in the AppImage you're running. It updates itself: on launch it
checks the releases API and, with your OK (**U**), sha256-verifies and replaces itself in place.

Build it with `packaging/build-appimage.sh` (needs `appimagetool`), release it with
`packaging/release.sh`, and run the suite with `tests/run.sh`. Subcommands:
`--worker | --refresh | --saves-daemon | --update | --sync-steam | --mount-setup | --install`.

Then, once: open **Storage → Set up NAS share…** to point Loadout at your NAS, and add
`Loadout.AppImage` to Steam if you want it in Game Mode.

### NAS setup
On the **Storage** page the SMB form takes **Host**, **ROM path**, **PC path**, **Saves path**, login,
and (optionally) your **SteamGridDB key** — the key is written to a `0600` keyfile, never the config.
The same page carries **Default disk**, **SD card on/off**, **Rebuild union**, **Prune empty** and
**Diagnostics**, so nothing needs a terminal. Historically it took your SMB **Host**, **Share/path**, and login,
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

### Console badges
Each Steam capsule gets a small badge in its corner naming the console, tinted to that console's
family colour — so a NES game and a PS2 game are not identical tiles in your library. It is burned
into Steam's artwork only; ES-DE is untouched. Rendered with cairo on the Deck itself, always from
the original cover so badges never stack. Set `console_badge` to `false` to disable.
A normal sync badges only art it already has cached (so it never turns into hundreds of lookups);
**Storage → Refresh artwork** is the explicit pass that fetches covers for everything already in
Steam — use it once on a Deck whose artwork came from another tool.

### Cover art (SteamGridDB)
Drop your SteamGridDB API key in `~/.config/loadout/steamgriddb.key` (or set `$LOADOUT_SGDB_KEY`)
and each game shows its cover thumbnail in the list. Covers load lazily per section, in the
background, and are cached under `~/.cache/loadout/covers/`, so a big library is fetched only
once. No key → no covers, and the list looks exactly as before.

### Without a NAS
The manager degrades gracefully: with no rclone mount it simply shows what's local and the
"NAS" side is empty — nothing crashes, nothing is lost (the NAS copy is never touched). Likewise
with no SD card it's a plain Internal + NAS setup and the disk control is inert.
