# Changelog

Notable changes (Keep a Changelog format, SemVer).

## [0.8.3] - 2026-07-23
### Fixed
- **Controls work when Game Mode feeds input as the analog stick.** On the Deck, Steam often sends
  navigation to a non-Steam app as the *left-stick axes* rather than the D-pad, and Loadout only
  read the hat (and with too high a stick deadzone). It now reads the sticks too — both axes, with
  a real deadzone/hysteresis and auto-repeat while held — as well as the D-pad (hat or buttons) and
  the face buttons. The detected controller is shown at the bottom of the window.
### Changed
- **Simpler navigation.** Left/Right switches section (console/list), Up/Down moves the highlight;
  the L1/R1 bumpers still jump sections and A/X/Y/Start act on the highlighted game. (The earlier
  two-pane "focus" mode is gone.)

## [0.8.2] - 2026-07-23
### Added
- **Newly-added games show up in "Recent games" on the Deck home screen.** When Loadout adds a
  game to Steam it now stamps it with a just-played timestamp in `localconfig.vdf` (surgically —
  backed up, atomic, with a brace-balance guard, never a full rewrite), so it lands on the front
  page instead of being buried in the library. Set `"recent_on_add": false` to leave play history
  untouched.
### Fixed
- **Controller input works in Game Mode.** The gamepad reader now keeps scanning for the
  controller — Steam creates its *virtual* pad after the app launches, and pads hotplug — instead
  of enumerating once at startup; it detects the pad by its gamepad buttons rather than by name,
  and also understands a D-pad reported as buttons. Previously the pad could come up dead in Game
  Mode. The detected controller is shown at the bottom of the window (`gamepad: …`).

## [0.8.1] - 2026-07-23
### Fixed
- **The Steam refresh no longer races SteamOS's auto-relaunch.** On the desktop, killing Steam
  makes SteamOS relaunch it immediately — sometimes *before* the refresh had rewritten
  `shortcuts.vdf` — so the relaunched client held the old shortcuts in memory and clobbered the
  fresh file on exit (a stale `offline-manager` shortcut reappeared and Loadout's art detached).
  The refresh now waits longer for a clean shutdown and, after writing, hard-kills any Steam that
  came back so the next launch loads the fresh file.
- **Loadout's own Steam card gains its wide (landscape) capsule.** `brand.py` now also generates
  the horizontal `grid/<appid>.png` capsule, so Loadout shows a proper wide title card in the
  recent-games shelf, not just the vertical cover.

## [0.8.0] - 2026-07-23
### Added
- **In-app NAS setup (SMB).** The Storage page has a **Set up NAS share…** button: enter your
  server's Host, Share/path, and login, press **Test** to check the connection, then **Save**.
  Loadout writes an **obscured** rclone SMB remote to `~/.config/rclone/rclone.conf` (0600) and
  records only the non-secret `remote:path` in its config — **your password is never stored in
  Loadout's config**. Saving rebuilds the union so the NAS tier mounts right away. Leaving the
  password blank keeps the one already saved. `mount-setup.sh` now reads the NAS remote from the
  config key `rom_rclone_remote`, so the whole three-tier union is set up from inside the app;
  the legacy `$ROM_RCLONE_REMOTE` env var and `games:roms` default still apply when it's empty.

## [0.7.3] - 2026-07-23
### Fixed
- The stale `offline-manager` / `Offline Manager` shortcut is now removed on the next refresh
  **even when nothing else changed**. In 0.7.2 the removal only happened alongside a ROM
  add/remove (the no-change early-return ran first), so on a library with no pending ROM
  changes the old shortcut lingered. The refresh now writes whenever a stale shortcut is present.

## [0.7.2] - 2026-07-23
### Changed
- **Loadout is now a true self-contained container.** Every helper script (the Steam refresh,
  the copy worker, save sync, mount setup) runs from *inside* the AppImage — nothing is ever
  copied into your home directory and no script in `~` is ever executed. The systemd `--user`
  units it installs only *invoke the AppImage itself* (`Loadout.AppImage --refresh` / `--worker`
  / `--saves-daemon`), so the logic that runs is always exactly the code in the AppImage you're
  running, even after a self-update or a move.
- **The Steam refresh never falls back to Steam ROM Manager.** The old
  `dirty-flag → loadout-sync.sh → srm-refresh.sh` chain is gone; the native refresh is the only
  path. On launch Loadout tears down any earlier script-based install (the units *and* the copied
  scripts) — this is what removes the regression where a leftover SRM refresh re-added the old
  `offline-manager` shortcut and dropped Loadout's own artwork.
### Fixed
- Steam now restarts **exactly once** after Apply: the pending-refresh flag is cleared *before*
  the Game-Mode/desktop restart, so the path unit can't re-fire and loop.
- The stale `offline-manager` shortcut is removed automatically on the next refresh.

## [0.7.1] - 2026-07-23
### Added
- **Built-in launch templates** for the standard EmuDeck layout, so Loadout works on a **fresh
  device with no existing shortcuts** (nothing to learn from). Templates learned from a device's
  own shortcuts still override the built-ins, so a customized emulator/core setup is matched exactly.

## [0.7.0] - 2026-07-23
### Added
- **Native Steam ROM shortcuts — Steam ROM Manager is no longer required.** Loadout learns each
  system's launch template from the existing shortcuts and writes matching ones itself, so games
  launch identically. On exit it runs a native refresh (`steam-refresh.sh`) that reconciles Steam
  shortcuts with what you've enabled + fetches SteamGridDB art, all with Steam briefly stopped —
  no SRM. `srm-refresh.sh` stays available if you still want SRM's extra scraping.
  (Validated on a 223-entry library: template regeneration 205/205 exact; the sync is idempotent
  and never duplicates, clobbers, or drops an entry — it dedups by rom path, skips broken symlinks.)
### Changed
- Loadout opens on the first section that actually has games (skips an empty PC Games).

## [0.6.0] - 2026-07-23
### Added
- **Game cover art** (SteamGridDB). With an API key set (`~/.config/loadout/steamgriddb.key`,
  or `$LOADOUT_SGDB_KEY`) each game shows its cover thumbnail in the list. Covers load lazily
  per section as you browse, on a background thread, and are cached (name→id map + images +
  "no art" markers) so a library is fetched at most once. No key → no covers, list unchanged.

## [0.5.0] - 2026-07-23
### Added
- **Left sidebar navigation** replacing the tab strip: a **LIBRARY** group (PC Games,
  Collections, one section per console with games) and a separated **SYSTEM** group (Saves,
  and a new **Storage** page). L1/R1 or the D-pad move between sections.
- **Storage page**: shows the union mount state and each tier (Internal / SD / NAS) with its
  path, RW/RO mode, mount state and free space, plus a **Rebuild union** action.
### Changed
- The many per-console tabs are condensed into the sidebar's LIBRARY list; Saves is no longer
  a game tab but a SYSTEM entry alongside Storage.

## [0.4.1] - 2026-07-23
### Changed
- Faster startup. The library is scanned once at launch instead of twice, and the Saves
  status (which hits the NAS over rclone and was the slowest, most variable startup cost)
  now loads in the background instead of blocking the window.

## [0.4.0] - 2026-07-23
### Changed
- **Renamed the project from `offline-manager` to Loadout.** Config lives at
  `~/.config/loadout/config.json` (env `$LOADOUT_CONFIG`); systemd units are `loadout-worker.*`
  and `loadout-srm.*`; scripts are `loadout.py` / `loadout-worker.py` / `loadout-sync.sh`.
  `install.sh` migrates an existing `offline-manager` install (moves the config, removes the old
  units and scripts). The *offline/local* game concept is unchanged — only the app name moved.
- See `ROADMAP.md` for the path to a self-updating AppImage (M0–M5).

## [0.3.0] - 2026-07-23
### Added
- Three-tier union: an optional **SD-card** branch between Internal and the NAS. The SD is
  auto-detected (`rom_sd` in the config forces a path or `"off"` disables it) and treated as a
  first-class writable, offline-playable tier.
- **Per-game disk choice**: when pulling a game offline, pick **SD** or **Internal** per title
  (**Start** on the pad / `d` on the keyboard). The "Where" column shows the chosen destination
  before Apply and the disk a game lives on after. `default_target` sets the sticky initial pick.
- `mount-setup.sh` now provisions the 3-tier union from the shared `config.json` (no more
  hardcoded paths), builds the branch list from whatever tiers exist, and makes the NAS branch
  optional (`ROM_RCLONE_REMOTE=off` for a local-only union).
### Changed
- Local-detection, free-space accounting, and the free/copy paths are now multi-branch: a game
  counts as local when it's on Internal **or** SD, the space check is per destination filesystem,
  and freeing removes a title from whichever branch(es) actually hold it.
- Updates/DLC systems and the sorter's `_unsorted` bucket are no longer listed as managed
  systems — updates/DLC follow their base game's local/NAS state, and `_unsorted` (any
  `_`-prefixed sorter bucket) is a NAS-side catch-all, not a console.

## [0.2.0] - 2026-07-23
### Added
- Shippable: `install.sh` (user-level install of scripts + systemd units + default config)
  and `config.example.json`. All manager paths are now read from
  `~/.config/offline-manager/config.json` (env `$OFFLINE_MANAGER_CONFIG`) with sane defaults
  instead of being hardcoded. Save sync's rclone remote is env-configurable
  (`DECK_SAVES_REMOTE`/`DECK_SAVES_BASE`). Documented graceful no-NAS behaviour.

## [0.1.0] - 2026-07-23
### Added
- Split out of `flan/steamdeck-roms` into its own project: the offline-manager GUI plus the
  overlays (mergerfs/rclone), SRM automation, NAS save sync, and wizard PC-install tooling it
  drives. See that repo's history for prior development.
