#!/usr/bin/env python3
"""Self-update for the Loadout AppImage.

Checks the PUBLIC Gitea releases for a newer version and, on request, downloads the new
AppImage, verifies its sha256, and atomically replaces the running one ($APPIMAGE). No token
needed (the repo is public). Safe no-op when not running as an AppImage or when offline.
"""
import hashlib
import json
import os
import tempfile
import urllib.request

VERSION = "0.19.0"
REPO = "flan/loadout"
LATEST = "https://git.onetick.ninja/api/v1/repos/%s/releases/latest" % REPO
_UA = {"User-Agent": "loadout-updater/%s" % VERSION}


def _fetch(url, binary=False, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
        return r.read() if binary else r.read().decode()


def _semver(s):
    s = (s or "").lstrip("vV").split("-")[0]
    parts = (s.split(".") + ["0", "0", "0"])[:3]
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (0, 0, 0)


def check():
    """Return {version, url, sha256} for a newer release, or None (up to date / unreachable)."""
    try:
        rel = json.loads(_fetch(LATEST))
    except Exception:
        return None
    tag = rel.get("tag_name", "")
    if _semver(tag) <= _semver(VERSION):
        return None
    app = sha = None
    for a in rel.get("assets", []):
        name = a.get("name", "")
        if name.endswith(".AppImage"):
            app = a.get("browser_download_url")
        elif name.endswith((".sha256", ".sha256sum")):
            sha = a.get("browser_download_url")
    if not app:
        return None
    return {"version": tag.lstrip("vV"), "url": app, "sha256": sha}


def apply(info):
    """Download, sha256-verify, and atomically replace the running AppImage.

    Returns (ok, message). Requires $APPIMAGE (set by the AppImage runtime)."""
    target = os.environ.get("APPIMAGE")
    if not target:
        return False, "not running as an AppImage — nothing to replace"
    try:
        blob = _fetch(info["url"], binary=True, timeout=180)
        if info.get("sha256"):
            want = _fetch(info["sha256"]).split()[0].strip().lower()
            if want and hashlib.sha256(blob).hexdigest() != want:
                return False, "checksum mismatch — update aborted"
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target) or ".", suffix=".new")
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)          # atomic on the same filesystem
        return True, "updated to %s — restart Loadout to finish" % info["version"]
    except Exception as e:
        return False, "update failed: %s" % e


if __name__ == "__main__":
    info = check()
    if not info:
        print("Loadout %s is up to date." % VERSION)
        raise SystemExit(0)
    ok, msg = apply(info)
    print(msg)
    raise SystemExit(0 if ok else 1)
