#!/usr/bin/env python3
# Deck-side: read the shared Switch manifest -> write Ryujinx updates.json/dlc.json per base game.
# Idempotent, path-translated to this Deck. Same script runs on every Deck.
# Change-gated: hashes the manifest and no-ops instantly when nothing changed.
# On change: rewrites the JSONs AND pokes the local rclone RC (vfs/refresh) so the new
# game file is visible in the union instantly instead of waiting on the dir-cache timer.
import os, json, collections, subprocess, tempfile, hashlib, urllib.request
ROMS=os.path.expanduser("~/Emulation/roms")
RYUGAMES=os.path.expanduser("~/.config/Ryujinx/games")
NAS_PREFIX="/mnt/Tank/media/Games/ROMs"
RCLONE=os.path.expanduser("~/bin/rclone")
HASHFILE=os.path.expanduser("~/.cache/register-manifest.hash")
RC_URL="http://127.0.0.1:5573"
def deckpath(p): return p.replace(NAS_PREFIX, ROMS)

# fetch the manifest fresh via rclone (bypasses the VFS dir-cache); fall back to the mount
MANIFEST=tempfile.mktemp()
try:
    with open(MANIFEST,"wb") as o:
        subprocess.run([RCLONE,"cat","games:roms/.switch-manifest.tsv"],stdout=o,timeout=30,check=True)
    if os.path.getsize(MANIFEST)==0: raise Exception("empty")
except Exception:
    MANIFEST=os.path.join(ROMS,".switch-manifest.tsv")
if not os.path.exists(MANIFEST) or os.path.getsize(MANIFEST)==0:
    print("manifest not available"); raise SystemExit(1)

# --- change gate: skip all work (and the vfs refresh) when the manifest is unchanged ---
data=open(MANIFEST,"rb").read()
cur=hashlib.sha256(data).hexdigest()
try: prev=open(HASHFILE).read().strip()
except Exception: prev=None
if cur==prev:
    print("manifest unchanged - no-op"); raise SystemExit(0)

updates=collections.defaultdict(list); dlcs=collections.defaultdict(list)
for line in data.decode("utf-8","replace").splitlines():
    p=line.rstrip("\n").split("\t")
    if len(p)<6: continue
    path,tid,typ,base,ver,dncas=p[:6]
    if not base or base=="": continue
    dp=deckpath(path); t=typ.lower()
    if t.startswith("patch"):
        try: v=int(ver)
        except: v=0
        updates[base].append((v,dp))
    elif "addon" in t:
        ncas=[n for n in dncas.split(",") if n]
        lst=[{"path":"/"+n+".nca","title_id":int(tid,16),"is_enabled":True} for n in ncas]
        if lst: dlcs[base].append({"path":dp,"dlc_nca_list":lst})

nu=nd=0
for base,ups in updates.items():
    ups.sort()                                   # ascending version; highest last
    sel=ups[-1][1]; paths=[p for _,p in ups]
    d=os.path.join(RYUGAMES,base); os.makedirs(d,exist_ok=True)
    json.dump({"selected":sel,"paths":paths}, open(os.path.join(d,"updates.json"),"w"), indent=2)
    nu+=1
for base,dl in dlcs.items():
    d=os.path.join(RYUGAMES,base); os.makedirs(d,exist_ok=True)
    json.dump(dl, open(os.path.join(d,"dlc.json"),"w"), indent=2)
    nd+=1

# record the new hash only after a clean write
os.makedirs(os.path.dirname(HASHFILE),exist_ok=True)
open(HASHFILE,"w").write(cur)

# something changed -> force the union to see new game files NOW (free; RC already runs)
try:
    req=urllib.request.Request(RC_URL+"/vfs/refresh",data=b'{"recursive":"true"}',
                               headers={"Content-Type":"application/json"})
    urllib.request.urlopen(req,timeout=20).read()
    refreshed="vfs refreshed"
except Exception as e:
    refreshed=f"vfs refresh skipped ({e})"
print(f"registered: updates for {nu} games, DLC for {nd} games; {refreshed}")
