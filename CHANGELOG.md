# Changelog

Notable changes (Keep a Changelog format, SemVer).

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
