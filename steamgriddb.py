#!/usr/bin/env python3
"""SteamGridDB cover art for Loadout.

Given a game name, return a locally-cached 600x900 portrait cover (for the in-app thumbnail
and, later, Steam library art). Best-effort and defensive: no key / offline / rate-limited /
no match all just return None and the UI shows no cover. Everything is cached (name→id map,
downloaded images, and negative "no grid" markers) so a library is fetched at most once.

The API key is read from $LOADOUT_SGDB_KEY or ~/.config/loadout/steamgriddb.key (chmod 600).
"""
import json
import os
import re
import urllib.parse
import urllib.request

API = "https://www.steamgriddb.com/api/v2"
CACHE = os.path.expanduser("~/.cache/loadout/covers")
_IDS = os.path.join(CACHE, "_ids.json")


def key():
    v = os.environ.get("LOADOUT_SGDB_KEY", "").strip()
    if v:
        return v
    try:
        return open(os.path.expanduser("~/.config/loadout/steamgriddb.key")).read().strip()
    except Exception:
        return ""


def enabled():
    return bool(key())


def _clean(name):
    """Strip extensions, (USA)/(Rev 2)/[RODE01] tags and disc markers for a better search."""
    n = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", name)
    n = re.sub(r"[\(\[][^\)\]]*[\)\]]", "", n)
    n = re.sub(r"\bdisc\s*\d+\b", "", n, flags=re.I)
    return re.sub(r"\s+", " ", n).strip(" -_")


def _get(url, binary=False):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key(),
                                               "User-Agent": "loadout"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read() if binary else json.loads(r.read().decode())


def _load_ids():
    try:
        return json.load(open(_IDS))
    except Exception:
        return {}


def _save_ids(m):
    try:
        os.makedirs(CACHE, exist_ok=True)
        tmp = _IDS + ".part"
        json.dump(m, open(tmp, "w"))
        os.replace(tmp, _IDS)
    except Exception:
        pass


def cover(name):
    """Path to a cached 600x900 cover for `name`, or None. Never raises."""
    if not enabled():
        return None
    q = _clean(name)
    if not q:
        return None
    os.makedirs(CACHE, exist_ok=True)
    ids = _load_ids()
    gid = ids.get(q)
    if gid is None:                                   # unknown -> search once, cache the result
        try:
            d = _get("%s/search/autocomplete/%s" % (API, urllib.parse.quote(q)))
            gid = d["data"][0]["id"] if d.get("data") else 0
        except Exception:
            return None                                # transient: don't poison the cache
        ids[q] = gid
        _save_ids(ids)
    if not gid:
        return None                                    # cached "no game"
    png = os.path.join(CACHE, "%d.png" % gid)
    if os.path.exists(png):
        return png
    if os.path.exists(png + ".none"):
        return None                                    # cached "game but no grid"
    try:
        d = _get("%s/grids/game/%d?dimensions=600x900&types=static&nsfw=false&limit=1" % (API, gid))
        items = d.get("data") or []
        if not items:
            open(png + ".none", "w").close()
            return None
        url = items[0].get("thumb") or items[0].get("url")
        blob = _get(url, binary=True)
        tmp = png + ".part"
        open(tmp, "wb").write(blob)
        os.replace(tmp, png)
        return png
    except Exception:
        return None


if __name__ == "__main__":                            # quick manual check
    import sys
    for n in sys.argv[1:]:
        print("%-40s -> %s" % (n, cover(n)))
