#!/usr/bin/env python3
# Stop dumping ROM shortcuts into Steam's built-in "Favorites" collection.
# SRM maps the category name "Favorites" onto Steam's real favourites collection key,
# which pollutes it. Give each parser its own per-console collection instead.
import json, os, shutil

P = os.path.expanduser("~/.config/steam-rom-manager/userData/userConfigurations.json")
CAT = {"N64": "Nintendo 64", "GC": "GameCube", "SNES": "Super Nintendo",
       "SWITCH": "Nintendo Switch", "WII": "Wii"}

shutil.copy(P, P + ".bak")
data = json.load(open(P))
changed = 0
for c in data:
    title = c.get("configTitle") or ""
    if not title.startswith("Favorites - "):
        continue                      # leave the Netplay parsers alone
    key = title.split("- ", 1)[1].strip().upper()
    cat = CAT.get(key)
    if not cat:
        continue
    new_title = "ROMs - " + key
    c["configTitle"] = new_title
    c["steamCategories"] = [cat]
    print("  %-20s -> %-14s category=%s" % (title, new_title, cat))
    changed += 1

json.dump(data, open(P, "w"), indent=2)
print("updated %d parser(s); backup: userConfigurations.json.bak" % changed)
