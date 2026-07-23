import os
import struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import steam_shortcuts as S

tmpl = {"exe": '"/home/deck/Emulation/tools/launchers/retroarch.sh" -L /core.so "{ROM}"',
        "lo": "", "start_dir": "/home/deck/Emulation/tools/launchers", "tag": "SNES"}
rom = "/home/deck/Emulation/roms/.steam-shortcuts/snes/Zelda.sfc"
now = int(time.time())

aid0, p0 = S.game_entry("Zelda", tmpl, rom)                    # default: unstamped
aid1, p1 = S.game_entry("Zelda", tmpl, rom, last_play=now)     # stamped
d0, d1 = dict(p0), dict(p1)
assert d0["LastPlayTime"] == 0, d0["LastPlayTime"]
assert d1["LastPlayTime"] == now, d1["LastPlayTime"]
assert aid0 == aid1, "appid must not depend on the play stamp (it keys the art files)"
print("  LastPlayTime: default=%d stamped=%d  appid stable=%s" % (d0["LastPlayTime"], d1["LastPlayTime"], aid0 == aid1))

# the stamped entry must survive a real binary round-trip unchanged
root = [("shortcuts", [("0", p1)])]
raw = S.dumps(root)
back = S.loads(raw)
assert S.dumps(back) == raw, "round-trip mismatch"
got = dict(S._entries(back)[0][1])
assert got["LastPlayTime"] == now, got["LastPlayTime"]
assert S.dumps(S.loads(raw)) == raw
print("  round-trip: byte-exact, LastPlayTime survives as %d" % got["LastPlayTime"])

# it must serialise as a 32-bit int field (type 0x02), the way Steam reads it
assert b"\x02LastPlayTime\x00" + struct.pack("<I", now) in raw
print("  wire format: 0x02 int32 field, matches Steam's encoding")
print("PASS")
