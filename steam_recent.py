"""Make freshly-added games appear on the Deck's home-screen "Recent games" shelf.

Steam drives that shelf from a per-game `LastPlayed` timestamp it keeps in localconfig.vdf, under
`Software/Valve/Steam/apps/<appid>`. A brand-new non-Steam shortcut has no timestamp, so it never
surfaces. This stamps `LastPlayed` (a recent time) for given shortcut appids so they show up right
after Loadout adds them — done in the same Steam-stopped window as the shortcuts.vdf write.

Edits are SURGICAL text insert/update only (never a full reserialize of Steam's 300 KB config):
each localconfig.vdf is backed up, written atomically, and a write that would change the file's
brace balance is refused outright.
"""
import glob
import os
import re
import shutil
import time


def steam_users(home=None):
    home = home or os.path.expanduser("~")
    base = os.path.join(home, ".local/share/Steam/userdata")
    if not os.path.isdir(base):
        base = os.path.join(home, ".steam/steam/userdata")
    return [d for d in glob.glob(os.path.join(base, "*"))
            if os.path.isdir(d) and os.path.basename(d).isdigit() and os.path.basename(d) != "0"]


def _find_apps(txt):
    """Locate Software/Valve/Steam/apps by walking the nested VDF key-path via braces. There are
    several `apps` sections in localconfig.vdf; only this one holds per-game LastPlayed. Returns
    (interior_position_just_after_the_opening_brace, apps_indent_string) or None."""
    stack, pending, pos = [], None, 0
    for ln in txt.splitlines(keepends=True):
        s = ln.strip()
        if re.match(r'"[^"]*"\s*$', s):                 # a section name on its own line
            pending = s.strip('"')
        elif s == "{":
            stack.append(pending)
            indent = ln[:len(ln) - len(ln.lstrip())]
            if [x.lower() for x in stack[-4:]] == ["software", "valve", "steam", "apps"]:
                return pos + len(ln), indent
            pending = None
        elif s.startswith("}"):
            if stack:
                stack.pop()
            pending = None
        else:                                           # a "key" "value" line
            pending = None
        pos += len(ln)
    return None


def _stamp_text(txt, appids, ts):
    """Return (new_text, changed_count). For each appid: update its LastPlayed if the block exists,
    add LastPlayed if the block exists without one, else insert a fresh block into the apps section."""
    changed = 0
    for appid in appids:
        appid = str(appid)
        blk = re.search(r'\n([ \t]*)"%s"\n\1\{\n' % re.escape(appid), txt)
        if blk:
            interior, indent = blk.end(), blk.group(1) + "\t"
            close = re.search(r'\n%s\}' % re.escape(blk.group(1)), txt[interior:])
            body = txt[interior:interior + close.start()] if close else ""
            if '"LastPlayed"' in body:
                seg = re.sub(r'("LastPlayed"\s*")\d+(")', r'\g<1>%s\g<2>' % ts, body, count=1)
                txt = txt[:interior] + seg + txt[interior + close.start():]
            else:
                ins = '%s"LastPlayed"\t\t"%s"\n%s"playtime"\t\t"1"\n' % (indent, ts, indent)
                txt = txt[:interior] + ins + txt[interior:]
            changed += 1
        else:
            found = _find_apps(txt)
            if not found:
                continue                                # no apps section -> skip (non-fatal)
            interior, ai = found
            block = ('%s\t"%s"\n%s\t{\n%s\t\t"LastPlayed"\t\t"%s"\n%s\t\t"playtime"\t\t"1"\n%s\t}\n'
                     % (ai, appid, ai, ai, ts, ai, ai))
            txt = txt[:interior] + block + txt[interior:]
            changed += 1
    return txt, changed


def stamp_recent(appids, home=None, ts=None):
    """Stamp LastPlayed=ts for each appid across every Steam user on this box. Steam MUST be stopped
    (localconfig.vdf is rewritten by a running client). Returns the number of blocks changed."""
    appids = [a for a in dict.fromkeys(appids)]         # de-dupe, keep order
    if not appids:
        return 0
    home = home or os.path.expanduser("~")
    ts = str(ts if ts is not None else int(time.time()))
    total = 0
    for u in steam_users(home):
        lc = os.path.join(u, "config", "localconfig.vdf")
        if not os.path.exists(lc):
            continue
        txt = open(lc, encoding="utf-8", errors="surrogateescape").read()
        b_open, b_close = txt.count("{"), txt.count("}")
        new, changed = _stamp_text(txt, appids, ts)
        if not changed or new == txt:
            continue
        # a valid edit only ever adds balanced pairs (a whole block) or brace-free key lines, so the
        # count of "{" and "}" added must match and the file must stay overall balanced. Refuse else.
        if (new.count("{") - b_open) != (new.count("}") - b_close) or new.count("{") != new.count("}"):
            continue                                    # malformed -> never write
        shutil.copy2(lc, lc + ".loadout-bak")
        tmp = lc + ".tmp"
        with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write(new)
        os.replace(tmp, lc)
        total += changed
    return total
