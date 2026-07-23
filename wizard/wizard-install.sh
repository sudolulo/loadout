#!/bin/bash
# wizard-install.sh <repack_dir> <game_label> [install_root]
#
# Headless, unattended install of a FitGirl/Inno "wizard" PC repack under Wine.
# Proven method (see project memory): GUI-drive with a fixed-coordinate click loop, a
# redist-interception proxy for the redist downloads, and /DIR= to pre-set the path.
#
# In an Inno wizard the primary button (Next -> Next -> Install -> Finish) is always in the
# same bottom-right position, so clicking one coordinate repeatedly walks every page. We
# stop the moment decompression starts (CLS-srep / ISDone / arc), then wait it out.
#
# The installed game is Windows -> it runs via Proton on the Deck, not here.
set -u
REPACK="${1:?usage: wizard-install.sh <repack_dir> <label> [install_root]}"
LABEL="${2:?need a label}"
INSTALL_ROOT="${3:-$HOME/pc-installs}"
TOOLS="$(cd "$(dirname "$0")" && pwd)"
DISP="${WIZ_DISPLAY:-:99}"
PORT="${REDIST_PORT:-8899}"
PREFIX="$HOME/.wizard-prefix"                 # shared throwaway install prefix
CACHE="$HOME/wizard-test/redist-cache"
LOG="$INSTALL_ROOT/$LABEL.install.log"
export WINEPREFIX="$PREFIX" WINEARCH=win64 WINEDEBUG=-all DISPLAY="$DISP" REDIST_CACHE="$CACHE" REDIST_PORT="$PORT"
mkdir -p "$INSTALL_ROOT"
log(){ echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

# --- 0) the genuine MS vcredist the proxy hands out (fetched once, cached) ---
mkdir -p "$CACHE"
if [ ! -s "$CACHE/vcredist_2008_x86.exe" ]; then
  log "fetching vcredist stand-in from Microsoft"
  curl -sL --max-time 120 -o "$CACHE/vcredist_2008_x86.exe" \
    "https://download.microsoft.com/download/5/D/8/5D8C65CB-C849-4025-8E95-C3966CAFD8AE/vcredist_x86.exe"
fi

# --- 1) virtual display + window manager (WM required or focus/keys fail) ---
pgrep -f "Xvfb $DISP" >/dev/null || { Xvfb "$DISP" -screen 0 1280x1024x24 >/dev/null 2>&1 & sleep 2; }
pgrep -f "openbox" >/dev/null || { openbox --sm-disable >/dev/null 2>&1 & sleep 1; }

# --- 2) redist interception server ---
pgrep -f "redist-server.py" >/dev/null || { python3 "$TOOLS/redist-server.py" 2>>"$LOG" & sleep 1; }

# --- 3) prefix + point WinINet at the local server (self-contained; no system change) ---
[ -d "$PREFIX" ] || { log "init wine prefix"; wineboot --init >/dev/null 2>&1; sleep 3; }
wine reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v ProxyEnable /t REG_DWORD /d 1 /f >/dev/null 2>&1
wine reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v ProxyServer /t REG_SZ /d "127.0.0.1:$PORT" /f >/dev/null 2>&1

# --- 4) launch the installer, destination pre-set via /DIR (Z: maps to /) ---
SETUP=$(ls "$REPACK"/setup.exe "$REPACK"/*.exe 2>/dev/null | head -1)
[ -n "$SETUP" ] || { log "ERR no setup.exe in $REPACK"; exit 1; }
TARGET="$INSTALL_ROOT/$LABEL"
WINPATH="Z:${TARGET//\//\\}"
rm -rf "$TARGET"; mkdir -p "$TARGET"
log "installing '$LABEL' from $(basename "$SETUP") -> $TARGET"
( cd "$REPACK" && setsid wine setup.exe /DIR="$WINPATH" >>"$LOG" 2>&1 < /dev/null & )

decomp_running(){ pgrep -f "CLS-srep|ISDone|isdone|precomp|freearc|arc.exe|unarc" >/dev/null 2>&1; }
click(){ xdotool mousemove "$1" "$2" click 1 2>/dev/null; }

# --- 5) drive the wizard deterministically ---
# wait for the language dialog, click OK
for i in $(seq 1 20); do
  xdotool search --name "Select Setup Language" >/dev/null 2>&1 && break; sleep 2
done
sleep 2
click 664 566          # language OK
sleep 3
# walk Next/Next/.../Install by clicking the fixed primary-button spot until unpack starts
for i in $(seq 1 9); do
  decomp_running && { log "decompression started after $i page-advances"; break; }
  click 773 683        # Next / Install (same position every page)
  sleep 3
done
if ! decomp_running; then
  # one more explicit Install press, in case the last page needed it
  click 773 683; sleep 5
fi
decomp_running || { log "ERR never reached decompression -- see $LOG and a screenshot"; import -window root "$INSTALL_ROOT/$LABEL.stuck.png" 2>/dev/null; exit 2; }

# --- 6) wait out the decompression ---
log "unpacking (this is the long part)"
last=0; stall=0
while pgrep -f "setup.tmp|CLS-srep|ISDone|precomp|freearc|arc.exe" >/dev/null 2>&1; do
  sz=$(du -sm "$TARGET" 2>/dev/null | cut -f1)
  if [ "${sz:-0}" -gt "$last" ]; then last=$sz; stall=0; else stall=$((stall+1)); fi
  [ "$stall" -ge 20 ] && { log "WARN no growth for ~10min at ${sz}MB"; break; }   # 20*30s
  sleep 30
done
sleep 5
# Finish page (if any) -- click the same button spot
click 773 683 2>/dev/null; sleep 3
pkill -f "setup.tmp" 2>/dev/null; pkill -f "\.exe" 2>/dev/null

# --- 7) find the main game exe ---
log "installed $(du -sh "$TARGET" 2>/dev/null | cut -f1) to $TARGET"
mapfile -t EXES < <(find "$TARGET" -iname "*.exe" \
  ! -iname "*unins*" ! -iname "*setup*" ! -iname "*vcredist*" ! -iname "*dxsetup*" \
  ! -iname "*redist*" ! -iname "*crashreport*" ! -iname "*launcher_installer*" \
  -printf '%s\t%p\n' 2>/dev/null | sort -rn)
log "game exes found: ${#EXES[@]}"
[ "${#EXES[@]}" -eq 0 ] && { log "ERR no game exe -- install likely incomplete"; exit 3; }
# heuristic: the largest exe is usually the game binary
MAIN=$(printf '%s\n' "${EXES[0]}" | cut -f2)
log "main exe (largest): ${MAIN#$TARGET/}"
printf '%s\n' "${EXES[@]}" | cut -f2 | sed "s#$TARGET/##" | sed 's/^/    /' | tee -a "$LOG"

# --- 8) emit a Proton launcher so the Deck can run this Windows game ---
# Windows games need Proton, not a bare exec. This launcher runs the exe through the
# Deck's newest Proton in a per-game prefix; SRM globs it into a Steam shortcut.
LAUNCHER="$TARGET/.play-$LABEL.sh"
cat > "$LAUNCHER" <<PROTON
#!/bin/bash
# generated by wizard-install.sh -- run this Windows game through Proton
GAME=${MAIN@Q}
export STEAM_COMPAT_CLIENT_INSTALL_PATH="\$HOME/.steam/steam"
export STEAM_COMPAT_DATA_PATH="\$HOME/.proton-prefixes/$LABEL"
mkdir -p "\$STEAM_COMPAT_DATA_PATH"
PROTON=\$(ls -d "\$HOME"/.steam/steam/steamapps/common/Proton*/proton 2>/dev/null | sort -V | tail -1)
[ -n "\$PROTON" ] || { echo "no Proton found"; exit 1; }
cd "\$(dirname "\$GAME")" || exit 1
exec "\$PROTON" run "\$GAME" "\$@"
PROTON
chmod +x "$LAUNCHER"
log "wrote Proton launcher: $(basename "$LAUNCHER")"
echo "MAIN_EXE=$MAIN"
echo "LAUNCHER=$LAUNCHER"
