# Changelog

Notable changes (Keep a Changelog format, SemVer).

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
