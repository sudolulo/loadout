#!/usr/bin/env python3
# Add a GBA parser by cloning the SNES one (same RetroArch plumbing), swapping the
# libretro core, ROM glob, category and parser id. Needed because the DKC favorite moved
# snes -> gba under the "prefer newest console" rule and had no parser to pick it up.
import json, os, copy, random

P = os.path.expanduser("~/.config/steam-rom-manager/userData/userConfigurations.json")
data = json.load(open(P))

if any((c.get("configTitle") or "") == "ROMs - GBA" for c in data):
    print("GBA parser already present"); raise SystemExit(0)

src = next(c for c in data if (c.get("configTitle") or "") == "ROMs - SNES")
gba = copy.deepcopy(src)
gba["configTitle"] = "ROMs - GBA"
gba["romDirectory"] = "${romsdirglobal}/.steam-favorites/gba"
gba["steamCategories"] = ["Game Boy Advance"]
gba["executableArgs"] = src["executableArgs"].replace("snes9x_libretro", "mgba_libretro")
gba["parserInputs"] = {"glob": "**/${title}@(.gba|.GBA|.zip|.ZIP|.7z|.7Z)"}
gba["parserId"] = str(random.randint(10**17, 10**18 - 1))
data.append(gba)
json.dump(data, open(P, "w"), indent=2)
print("added parser 'ROMs - GBA' (mgba_libretro, category 'Game Boy Advance')")
print("  romDirectory:", gba["romDirectory"])
