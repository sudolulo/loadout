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

Only **playable** games are listed — installers (un-installed PC repacks) are hidden.
Rescan = **⧉ View**, Apply = **Y**, Close = **B**, tabs = **L1/R1** or D-pad.

## Overlays — `mount-setup.sh`
A mergerfs union at `~/Emulation/roms`: local RW branch → SD → a read-only rclone mount of the
NAS. New downloads appear automatically; anything not held locally streams.

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
