"""Tell Steam to run a non-Steam shortcut under Proton, the normal way.

A Windows game added as a non-Steam shortcut only runs under Proton if it has a compatibility
tool set for it. Steam keeps that in `config/config.vdf` under
`InstallConfigStore/Software/Valve/Steam/CompatToolMapping/<appid>` — the same thing the
"Compatibility" checkbox in a game's properties writes. Setting it means **Steam** creates and
owns the Wine prefix at `steamapps/compatdata/<appid>`, so the game's saves land exactly where
every other Deck game's saves live, and the Proton version can be changed from Steam's own UI.

The alternative — a generated launcher that invokes Proton itself with its own
`STEAM_COMPAT_DATA_PATH` — is what Loadout used to do, and it put saves somewhere nothing else
knows to look.

This is a SURGICAL text edit of Steam's global config: it inserts or updates one block, backs the
file up first, writes atomically, and refuses any edit that would change the file's brace balance.
Steam must be stopped, or it will write its in-memory copy back over the change.
"""
import os
import re
import shutil

_PATH = ("installconfigstore", "software", "valve", "steam", "compattoolmapping")


def config_path(home=None):
    """Steam's global config.vdf, or None if this device has no Steam install."""
    home = home or os.path.expanduser("~")
    for base in (".local/share/Steam", ".steam/steam"):
        p = os.path.join(home, base, "config", "config.vdf")
        if os.path.isfile(p):
            return p
    return None


def _find_section(txt, path):
    """Walk the nested VDF key-path by braces. Returns (pos_just_after_opening_brace, indent) for
    the section, or None. Matching the path (not just the last key) matters: `config.vdf` has
    several sections that share a name at different depths."""
    stack, pending, pos = [], None, 0
    want = [k.lower() for k in path]
    for ln in txt.splitlines(keepends=True):
        s = ln.strip()
        if re.match(r'"[^"]*"\s*$', s):
            pending = s.strip('"')
        elif s == "{":
            stack.append(pending)
            indent = ln[:len(ln) - len(ln.lstrip())]
            if [x.lower() if x else "" for x in stack[-len(want):]] == want:
                return pos + len(ln), indent
            pending = None
        elif s.startswith("}"):
            if stack:
                stack.pop()
            pending = None
        else:
            pending = None
        pos += len(ln)
    return None


def _section_span(txt, path):
    """(start, end) of a section's INTERIOR, by brace-counting from its opening brace. Needed
    because a plain regex for `"<appid>" {` would also match blocks in other sections, and
    position comparisons against the section start are off by the newline the regex consumes."""
    found = _find_section(txt, path)
    if not found:
        return None
    at, _indent = found
    depth, i = 1, at
    while i < len(txt) and depth:
        c = txt[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if not depth:
                return at, i
        i += 1
    return None


def _block(txt, span, appid):
    """The `"<appid>" { ... }` match inside the section span, or None."""
    if not span:
        return None
    start, end = span
    return re.search(r'\n([ \t]*)"%s"\n\1\{\n(.*?)\n\1\}'
                     % re.escape(str(appid)), txt[start - 1:end], re.S)


def _set_text(txt, appid, tool):
    """Return (new_text, changed). Updates the tool name if the appid already has a mapping,
    otherwise inserts a mapping; creates the CompatToolMapping section if it is missing."""
    appid = str(appid)
    span = _section_span(txt, _PATH)
    blk = _block(txt, span, appid)
    if blk:
        off = span[0] - 1                     # _block searched a slice; map back to the file
        body = blk.group(2)
        if re.search(r'"name"\s+"[^"]*"', body):
            new_body = re.sub(r'("name"\s+")[^"]*(")', r'\g<1>%s\g<2>' % tool, body, count=1)
        else:
            new_body = body + '\n%s\t"name"\t\t"%s"' % (blk.group(1), tool)
        if new_body == body:
            return txt, False
        return txt[:off + blk.start(2)] + new_body + txt[off + blk.end(2):], True

    found = _find_section(txt, _PATH)
    if not found:
        # no CompatToolMapping yet: create it inside .../Valve/Steam
        parent = _find_section(txt, _PATH[:-1])
        if not parent:
            return txt, False
        at, indent = parent
        inner = indent + "\t"
        block = ('%s"CompatToolMapping"\n%s{\n%s"%s"\n%s{\n%s"name"\t\t"%s"\n%s"config"\t\t""\n'
                 '%s"priority"\t\t"250"\n%s}\n%s}\n'
                 % (inner, inner, inner + "\t", appid, inner + "\t", inner + "\t\t", tool,
                    inner + "\t\t", inner + "\t\t", inner + "\t", inner))
        return txt[:at] + block + txt[at:], True

    at, indent = found
    inner = indent + "\t"
    block = ('%s"%s"\n%s{\n%s"name"\t\t"%s"\n%s"config"\t\t""\n%s"priority"\t\t"250"\n%s}\n'
             % (inner, appid, inner, inner + "\t", tool, inner + "\t", inner + "\t", inner))
    return txt[:at] + block + txt[at:], True


def get_tool(appid, home=None):
    """The compatibility tool currently set for `appid`, or "" if none."""
    p = config_path(home)
    if not p:
        return ""
    try:
        txt = open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    blk = _block(txt, _section_span(txt, _PATH), appid)
    if not blk:
        return ""
    m = re.search(r'"name"\s+"([^"]*)"', blk.group(2))
    return m.group(1) if m else ""


def set_tool(appid, tool, home=None):
    """Point `appid` at Proton build `tool`. Returns True when the file changed.

    Refuses to write if the edit would unbalance the file's braces — a corrupted config.vdf
    costs the user their whole Steam configuration, so a bad edit must never reach disk.
    """
    p = config_path(home)
    if not p:
        return False
    try:
        txt = open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    new, changed = _set_text(txt, appid, tool)
    if not changed:
        return False
    if new.count("{") - new.count("}") != txt.count("{") - txt.count("}"):
        raise RuntimeError("compat edit would unbalance config.vdf — refusing to write")
    shutil.copy2(p, p + ".loadout-bak")
    tmp = p + ".loadout-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, p)
    return True


def newest_proton(home=None):
    """The Proton build to default a Windows game to: the highest-numbered stable one installed,
    falling back to Experimental. Runtimes (BattlEye/EasyAntiCheat) are not Proton builds."""
    home = home or os.path.expanduser("~")
    base = os.path.join(home, ".local/share/Steam/steamapps/common")
    try:
        names = os.listdir(base)
    except OSError:
        names = []
    stable, beta = [], []
    for n in names:
        if not n.startswith("Proton") or "Runtime" in n:
            continue
        m = re.search(r'(\d+)\.(\d+)', n)
        if not m:
            continue                                   # "Proton - Experimental" has no version
        v = (int(m.group(1)), int(m.group(2)))
        (beta if "beta" in n.lower() else stable).append(v)
    pick = max(stable or beta or [], default=None)
    if pick is None:
        return "proton_experimental"
    # Steam keys the mapping on the tool's internal id, not its folder name: "Proton 9.0" is
    # "proton_9" and "Proton 10.0" is "proton_10" (verified against a Deck's own config.vdf).
    return "proton_%d" % pick[0] if pick[1] == 0 else "proton_%d.%d" % pick
