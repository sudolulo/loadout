#!/usr/bin/env python3
"""Print the Steam account ID that is actually signed in on this Deck.

A Deck can hold several accounts under userdata/, so picking the first directory is a
coin flip. Steam records the real answer in config/loginusers.vdf: the account with
MostRecent set (newest Timestamp breaks a tie), cross-checked against AutoLoginUser in
registry.vdf. Exits non-zero if it cannot tell, so callers can refuse rather than guess.
"""
import os, re, sys

HOME = os.path.expanduser("~")
LOGIN = os.path.join(HOME, ".local/share/Steam/config/loginusers.vdf")
REG = os.path.join(HOME, ".steam/registry.vdf")
USERDATA = os.path.join(HOME, ".local/share/Steam/userdata")
BASE = 76561197960265728          # steamID64 -> account ID offset


def parse_loginusers(path):
    """[(accountid, name, mostrecent, timestamp)] -- flat enough not to need a vdf lib."""
    try:
        txt = open(path, errors="replace").read()
    except OSError:
        return []
    out = []
    for m in re.finditer(r'"(7656\d{13})"\s*\{(.*?)\n\t\}', txt, re.S):
        sid, body = m.group(1), m.group(2)
        def field(k, default=""):
            f = re.search(r'"%s"\s+"([^"]*)"' % k, body, re.I)
            return f.group(1) if f else default
        out.append((int(sid) - BASE, field("AccountName"),
                    field("MostRecent", "0") == "1", int(field("Timestamp", "0") or 0)))
    return out


def autologin_name():
    try:
        m = re.search(r'"AutoLoginUser"\s+"([^"]*)"', open(REG, errors="replace").read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def main():
    users = parse_loginusers(LOGIN)
    have = set()
    if os.path.isdir(USERDATA):
        have = {d for d in os.listdir(USERDATA) if d.isdigit()}

    # 1) whoever Steam marks as most recent (newest timestamp wins a tie)
    recent = sorted([u for u in users if u[2]], key=lambda u: -u[3])
    # 2) fall back to the auto-login account name
    auto = autologin_name().lower()
    byname = [u for u in users if u[1].lower() == auto and auto]
    # 3) last resort: the only userdata dir, if there is exactly one
    for pick in (recent, byname, sorted(users, key=lambda u: -u[3])):
        for acct, name, _, _ in pick:
            if not have or str(acct) in have:
                print(acct)
                return 0
    if len(have) == 1:
        print(have.pop())
        return 0
    sys.exit("ERR cannot determine the signed-in Steam account")


if __name__ == "__main__":
    sys.exit(main())
