"""In-app SMB/NAS provisioning for Loadout.

Turns the four things a person actually knows about their share — Host, Share, User, Password —
into (a) an OBSCURED rclone SMB remote in ~/.config/rclone/rclone.conf and (b) a non-secret
`remote:path` string for config.json's `rom_rclone_remote`, which mount-setup.sh mounts read-only
as the NAS tier of the union.

Security: the plaintext password is fed to `rclone obscure` over STDIN (never on argv, so it can't
leak via ps) and only its obscured form is written, to a 0600 file. It is NEVER put in config.json.
Loadout stores no plaintext credential anywhere.
"""
import configparser
import os
import subprocess

RCLONE_CONF = os.path.expanduser("~/.config/rclone/rclone.conf")


def rclone_bin():
    """The rclone Loadout should use: the Deck's ~/bin/rclone if present, else PATH."""
    cand = os.path.expanduser("~/bin/rclone")
    if os.path.exists(cand):
        return cand
    from shutil import which
    return which("rclone") or "rclone"


def obscure(password, rclone=None):
    """rclone's reversible obfuscation, exactly as `rclone obscure` produces. Password in via
    STDIN so it never appears on a command line. Empty password -> empty string (anonymous)."""
    if not password:
        return ""
    r = subprocess.run([rclone or rclone_bin(), "obscure", "-"],
                       input=password, capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise RuntimeError("rclone obscure failed: " + (r.stderr or "").strip())
    return r.stdout.strip()


def read_remote(name):
    """Pre-fill helper: return {host,user} for an existing remote (never the password)."""
    cp = configparser.ConfigParser()
    if os.path.exists(RCLONE_CONF):
        cp.read(RCLONE_CONF)
    if name in cp:
        return {"host": cp[name].get("host", ""), "user": cp[name].get("user", "")}
    return {"host": "", "user": ""}


def write_remote(name, host, user, password, rclone=None, _obscure=None,
                 keep_existing_pass=False):
    """Create/replace the SMB remote [name] in rclone.conf with an OBSCURED password. Preserves
    every other remote already in the file. rclone.conf is (re)written 0600. Returns the section
    dict written (pass shown only as '<obscured>' for logging). `_obscure` is injectable for tests.

    If `password` is blank and `keep_existing_pass` is set, the remote's current obscured password
    is kept (so re-saving host/user without re-typing the password doesn't wipe it)."""
    os.makedirs(os.path.dirname(RCLONE_CONF), exist_ok=True)
    cp = configparser.ConfigParser()
    if os.path.exists(RCLONE_CONF):
        cp.read(RCLONE_CONF)
    prior = cp.get(name, "pass", fallback="") if cp.has_section(name) else ""
    if password:
        obsc = (_obscure or obscure)(password, rclone)
    elif keep_existing_pass:
        obsc = prior
    else:
        obsc = ""
    if cp.has_section(name):
        cp.remove_section(name)
    cp.add_section(name)
    cp.set(name, "type", "smb")
    cp.set(name, "host", host)
    if user:
        cp.set(name, "user", user)
    if obsc:
        cp.set(name, "pass", obsc)
    # write 0600 from the start (never a world-readable window)
    fd = os.open(RCLONE_CONF, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        cp.write(f)
    os.chmod(RCLONE_CONF, 0o600)
    return {"type": "smb", "host": host, "user": user, "pass": "<obscured>" if obsc else ""}


def remote_path(name, share, subpath=""):
    """The non-secret `remote:path` string for config.json's rom_rclone_remote."""
    p = share.strip().strip("/")
    sub = subpath.strip().strip("/")
    if sub:
        p = p + "/" + sub
    return "%s:%s" % (name, p)


def test_remote(remote, rclone=None, timeout=30):
    """`rclone lsd remote:path` with short network timeouts. Returns (ok, message)."""
    try:
        r = subprocess.run([rclone or rclone_bin(), "lsd", remote,
                            "--contimeout", "8s", "--timeout", "12s", "--low-level-retries", "1"],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timed out reaching %s" % remote
    except FileNotFoundError:
        return False, "rclone not found on this device"
    if r.returncode == 0:
        n = len([l for l in r.stdout.splitlines() if l.strip()])
        return True, "connected — %d folder(s) visible under %s" % (n, remote)
    last = (r.stderr or r.stdout or "connection failed").strip().splitlines()
    return False, (last[-1] if last else "connection failed")[:140]
