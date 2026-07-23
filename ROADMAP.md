# Loadout — Roadmap

**Rename of `offline-manager`.** Loadout is a self-contained Steam Deck app that decides which
games live **on the Deck** (offline, per-disk) vs **stream from the NAS**, syncs **saves**, and
puts games in **Steam with artwork** — shipped as a **self-updating AppImage**, needing no other
tooling.

> "Set your Deck's loadout."

## Decisions locked
| Area | Decision |
|---|---|
| Name | **Loadout** (`flan/loadout`, `~/.config/loadout`, `Loadout.AppImage`) |
| Packaging | **Self-updating AppImage** (not Flatpak — a host tool can't live in a sandbox / Flathub) |
| Updates | **Prompt in the GUI** (launch check + daily `--user` timer → sha256-verified atomic self-replace) |
| Storage tiers | Internal + SD (optional) + NAS union, **per-game SD/Internal** destination *(shipped v0.3)* |
| NAS setup | **In-app SMB fields** (Host/Share/User/Password → obscured rclone remote); secrets never in `config.json` |
| Steam shortcuts | **Native `shortcuts.vdf`** — SRM drops from dependency to optional polish |
| Artwork | **SteamGridDB, fetched by us** — cover thumbnail per row in-app + Steam grid/hero/logo/icon |
| Nav | **Left sidebar** (LIBRARY + SYSTEM groups) + `Gtk.Stack` |

## Already done this session (v0.3, on `code`, not yet redeployed)
- 3-tier union + per-game disk destination; `mount-setup.sh` config-driven + optional SD/NAS.
- **Updates/DLC hidden** (`is_update_dlc`), `switch-updates` removed, **`_unsorted` hidden**
  (any `_`-prefixed sorter bucket).
- Deployed build on the Decks is the earlier v0.3 (pre these last edits) — redeploy pending.

---

## Milestones (sequenced, each deployable + Deck-testable)

### M0 — Rename to Loadout `(0.4)`
Touches everything, so it goes first.
- **Repo**: `flan/offline-manager` → `flan/loadout` (Gitea rename; re-point `origin`). *Verify the
  name is free first.*
- **Paths**: `~/.config/offline-manager` → `~/.config/loadout`; env `$OFFLINE_MANAGER_CONFIG` →
  `$LOADOUT_CONFIG`. **Migration**: on first run, if the old dir exists and the new doesn't, move it.
- **systemd units**: `offline-manager-worker` → `loadout-worker`, etc. `install.sh` disables the old
  units and enables the new ones (the two existing Deck installs already have the old ones).
- **Files/strings**: `offline-manager.py` → `loadout.py`; queue/progress dotfiles; README, NOTICE,
  CHANGELOG title, in-app title.
- *Deck test*: install over an existing `offline-manager` install and confirm config + units migrate.

### M1 — Sidebar nav + Storage page (info) `(0.5)`
- Replace `Gtk.Notebook` with a **left sidebar** (`Gtk.ListBox` + group headers) + `Gtk.Stack`:
  - **LIBRARY**: PC Games, Collections, consoles (condensed vertical list).
  - **SYSTEM** (separated): Saves, Storage.
- Reroute nav: L1/R1 + D-pad-left/right move the sidebar selection (same model as tabs today);
  D-pad up/down navigates the list. Keep focus on the content view, drive the sidebar programmatically.
- **Storage page** (info only this milestone): union path + mounted state; per-tier rows
  (Internal/SD/NAS — path, RW/RO, mounted?, free space); **Rebuild union** action.
- *Gaps*: `is_panel` flag generalizes SavesPage/StoragePage (button panels vs list pages) in
  `_grab`/`pad_move`/`update_focus_hint`. `self.pages` = all nav pages; `page()` reads the stack.
- *Deck test*: GTK render at 1280×800, gamepad focus flow, sidebar grouping.

### M2 — In-app SMB setup + transparent provisioning `(0.6)`
- **Storage/Setup**: Host / Share / User / Password fields (Steam on-screen keyboard). Save →
  obscure the password via `rclone` (stdin, no argv exposure) → write the SMB remote to
  `rclone.conf` → store non-secrets (`nas_remote`, `nas_host`, `nas_share`, `nas_user`) in
  `config.json` → rebuild union.
- **`mount-setup.sh`**: derive the rclone remote from config (not hardcoded `games:roms`);
  make it **idempotent** (skip the remount if the union already matches the desired branches) and
  **game-gated** (`pgrep [r]eaper SteamLaunch AppId=` → skip remount if a game is running).
- **Transparent provisioning**: `install.sh` runs `mount-setup.sh` (game-gated); the GUI
  **self-heals** — if the union isn't mounted at launch it provisions in the background; **first-run**
  with no share configured routes the user to the Setup page.
- **PC union gap**: today only the ROM union is provisioned; `~/Games` (PC) union + `.manifest.json`
  are not — hence the empty PC tab on the Decks. Decide: provision a PC union in `mount-setup.sh`,
  or keep PC as install-only and document. (Recommended: provision it the same way, optional.)
- *Deck test*: configure SMB from the GUI → verify obscured remote + NAS mount; on-screen keyboard.

### M3 — Decouple from Steam ROM Manager `(0.7)`
- **Native `shortcuts.vdf` writer** (pure-Python binary VDF): add/remove non-Steam shortcuts for
  enabled ROMs/PC games; detect the Steam user (`~/.local/share/Steam/userdata/<id>/config/`);
  set **categories** via each shortcut's `tags`.
- Keep the **Steam stop → write → start** dance (Steam owns the file; same constraint SRM has).
- **Tag Loadout's own shortcuts** (a marker in LaunchOptions / a dedicated collection) so it only
  ever touches its own entries — never clobbers SRM-made ones.
- **SRM optional**: detect it; offer a "Polish with SRM" action (artwork + SRM categories) when
  present. Remove the hard dependency; `srm-*` scripts become optional.
- *Deck test*: shortcuts appear + launch, categories set, SRM coexistence (no clobber).

### M4 — SteamGridDB artwork `(0.8)`
- **API key**: user enters their SteamGridDB key in Setup; stored `chmod 600` in the config dir
  (a keyfile — **not** plaintext `config.json`).
- **Matching**: game name → SGDB search → gameID → grid/hero/logo/icon; **cache** the name→id map
  and images under `~/.cache/loadout/art/`; fuzzy match (manual override is a later nicety).
- **In-app**: **cover thumbnail per row** (a `CellRendererPixbuf` column), loaded **async** with a
  placeholder so the list never blocks on the network.
- **Steam shortcuts**: populate `userdata/<id>/config/grid/` with the four art types on add.
- **Graceful**: no key / no network → no art, plain capsule; nothing breaks.
- *Deck test*: art fetch + thumbnail render + Steam grid art.

### M5 — AppImage packaging, self-update, release CI `(0.9 → 1.0)`
- **Build**: bundle python3 + GTK3/`gi` + `mergerfs` + `rclone` + the app (linuxdeploy +
  appimagetool). Ship a `.desktop` + icon and a one-line installer that registers them (app grid +
  add-to-Steam helper). Verify on SteamOS (FUSE / `--appimage-extract-and-run`).
- **Self-update**: check the **Gitea releases API** on launch + a daily `--user` timer; **prompt in
  the GUI**; download → **sha256 verify** (+ optional cosign) → **atomic self-replace** (`$APPIMAGE`)
  → relaunch prompt.
- **Release CI**: **Gitea Actions** on a version tag (runner already on `code`) → build AppImage +
  `sha256sum` (+ cosign) → publish a **Gitea Release**. Cutting a release = pushing a tag.
- *Deck test*: AppImage runs on SteamOS; self-update round-trip; `.desktop` in the app grid.
- **1.0** = AppImage + self-update + all of the above shipped and verified on a Deck.

---

## Cross-cutting concerns (fleshed out)
- **Config schema (consolidated)** — non-secret in `config.json`: `rom_local/rom_sd/rom_nas/
  rom_union`, `pc_local/pc_nas/pc_union/pc_manifest`, `default_target`, `nas_remote/nas_host/
  nas_share/nas_user`, `srm_appimage` (optional), `saves_script`, `steamgriddb` (id-cache only).
  **Secrets NOT in config.json**: SMB password → `rclone.conf` (obscured); SGDB key → 600 keyfile.
- **Migration** — `offline-manager` → `loadout`: config dir, env var, unit names, on existing Deck
  installs (M0 + install.sh).
- **Security** — obscured SMB creds; 600 SGDB keyfile; sha256-verified update downloads; no secrets
  in `config.json` or commits; AI attribution stays **NOTICE-only**.
- **Testing split** — static on `code` (py_compile, VDF unit tests, config-resolver tests); live on a
  Deck for everything GUI/mount/Steam/art (gated on `pgrep` — never disrupt a live game; reach the
  Decks at their **garden LAN IPs** via `deck_key` on truenas).

## Non-goals / later
Flathub (host tool, won't be accepted) · PC games on the SD · zsync **delta** updates (add if full
downloads get annoying) · manual per-game art override UI · multi-user.

## Sequencing rationale
M0 first (rename touches all). M1 (UI) is independent and shippable alone. M2 makes it work for a
fresh user (share + provisioning). M3 removes the SRM dependency. M4 is polish. M5 ships it as a
self-updating AppImage. Every milestone is independently deployable and Deck-testable.
