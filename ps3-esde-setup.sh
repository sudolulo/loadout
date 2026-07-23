set -u
# 1) rpcs3 launcher for a .ps3 disc folder (boot the EBOOT via the flatpak)
mkdir -p ~/Emulation/tools/launchers
cat > ~/Emulation/tools/launchers/rpcs3-ps3.sh <<'LAUNCH'
#!/bin/bash
# Boot a decrypted PS3 disc folder (.ps3) in RPCS3, headless (renders the game directly).
GAME="$1"
EBOOT="$GAME/PS3_GAME/USRDIR/EBOOT.BIN"
[ -f "$EBOOT" ] || EBOOT="$GAME"
exec flatpak run net.rpcs3.RPCS3 --no-gui "$EBOOT"
LAUNCH
chmod +x ~/Emulation/tools/launchers/rpcs3-ps3.sh

# 2) RPCS3 find-rule
F=~/ES-DE/custom_systems/es_find_rules.xml
if ! grep -q 'name="RPCS3"' "$F" 2>/dev/null; then
  python3 - "$F" <<'PY'
import sys
f=sys.argv[1]; s=open(f).read()
rule='''  <emulator name="RPCS3">
    <rule type="staticpath">
      <entry>~/.local/share/flatpak/exports/bin/net.rpcs3.RPCS3</entry>
      <entry>/var/lib/flatpak/exports/bin/net.rpcs3.RPCS3</entry>
      <entry>~/Applications/rpcs3.AppImage</entry>
    </rule>
  </emulator>
</ruleList>'''
s=s.replace("</ruleList>", rule, 1)
open(f,"w").write(s)
print("  RPCS3 find-rule added")
PY
else echo "  RPCS3 find-rule already present"; fi

# 3) ps3 system
S=~/ES-DE/custom_systems/es_systems.xml
if ! grep -q "<name>ps3</name>" "$S" 2>/dev/null; then
  python3 - "$S" <<'PY'
import sys
f=sys.argv[1]; s=open(f).read()
sysentry='''  <system>
    <name>ps3</name>
    <fullname>Sony PlayStation 3</fullname>
    <path>%ROMPATH%/ps3</path>
    <extension>.ps3 .PS3</extension>
    <command label="RPCS3 (Standalone)">/bin/bash ~/Emulation/tools/launchers/rpcs3-ps3.sh %ROM%</command>
    <platform>ps3</platform>
    <theme>ps3</theme>
  </system>
</systemList>'''
s=s.replace("</systemList>", sysentry, 1)
open(f,"w").write(s)
print("  ps3 system added")
PY
else echo "  ps3 system already present"; fi

echo "=== verify ==="
grep -c "<name>ps3</name>" "$S"; grep -c 'name="RPCS3"' "$F"
ls -l ~/Emulation/tools/launchers/rpcs3-ps3.sh | awk '{print "  launcher: "$NF}'
echo "  game visible: $(ls -d ~/Emulation/roms/ps3/*.ps3 2>/dev/null | xargs -n1 basename 2>/dev/null)"
