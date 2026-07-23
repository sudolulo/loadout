"""Moving a game between disks must be copy -> verify -> delete, and must NEVER delete the
original unless the destination is provably complete."""
import importlib.util, os, shutil, sys, tempfile

spec = importlib.util.spec_from_file_location("w", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "loadout-worker.py"))
W = importlib.util.module_from_spec(spec); spec.loader.exec_module(W)

root = tempfile.mkdtemp(prefix="move-")
A, B = root + "/internal", root + "/sd"
os.makedirs(A + "/Game/sub"); os.makedirs(B)
open(A + "/Game/big.bin", "wb").write(b"x" * (3 * 1024 * 1024))
open(A + "/Game/sub/small.txt", "w").write("hello")
before_b, before_n = W.tree_size(A + "/Game")
fails = []
noop = lambda *a, **k: None

# 1. a clean move relocates everything and removes the original
ok, detail = W.do_move({"name": "Game", "from": A + "/Game", "to": B + "/Game",
                        "size": before_b}, noop)
after_b, after_n = W.tree_size(B + "/Game")
print("  move: ok=%s (%s)" % (ok, detail))
print("  dest %d bytes/%d files (source had %d/%d)" % (after_b, after_n, before_b, before_n))
print("  source removed: %s   no .part left: %s"
      % (not os.path.exists(A + "/Game"), not os.path.exists(B + "/Game.part")))
if not ok: fails.append("clean move failed")
if (after_b, after_n) != (before_b, before_n): fails.append("content changed in transit")
if os.path.exists(A + "/Game"): fails.append("original not reclaimed")
if os.path.exists(B + "/Game.part"): fails.append(".part left behind")

# 2. a move whose copy comes up short must KEEP the original
os.makedirs(A + "/Game2"); open(A + "/Game2/f.bin", "wb").write(b"y" * 4096)
real_tree_size = W.tree_size
def lying_tree_size(p):                       # simulate a truncated/failed copy
    b, n = real_tree_size(p)
    return (b - 1, n) if p.endswith(".part") else (b, n)
W.tree_size = lying_tree_size
ok2, detail2 = W.do_move({"name": "Game2", "from": A + "/Game2", "to": B + "/Game2",
                          "size": 4096}, noop)
W.tree_size = real_tree_size
print("  short copy: ok=%s (%s)" % (ok2, detail2))
print("  original still there: %s   destination NOT published: %s"
      % (os.path.exists(A + "/Game2/f.bin"), not os.path.exists(B + "/Game2")))
if ok2: fails.append("a short copy reported success")
if not os.path.exists(A + "/Game2/f.bin"): fails.append("DATA LOSS: original deleted after a bad copy")
if os.path.exists(B + "/Game2"): fails.append("incomplete copy published under the real name")

# 3. refuses to overwrite something already at the destination
os.makedirs(B + "/Clash"); open(B + "/Clash/keep.txt", "w").write("precious")
os.makedirs(A + "/Clash"); open(A + "/Clash/new.txt", "w").write("new")
ok3, detail3 = W.do_move({"name": "Clash", "from": A + "/Clash", "to": B + "/Clash",
                          "size": 3}, noop)
print("  clash: ok=%s (%s)  existing file intact: %s"
      % (ok3, detail3, open(B + "/Clash/keep.txt").read() == "precious"))
if ok3: fails.append("overwrote an existing destination")
if open(B + "/Clash/keep.txt").read() != "precious": fails.append("DATA LOSS: clobbered destination")
if not os.path.exists(A + "/Clash/new.txt"): fails.append("deleted source on a refused move")

# 4. a missing source is a no-op, not a crash
ok4, detail4 = W.do_move({"name": "Ghost", "from": A + "/Ghost", "to": B + "/Ghost", "size": 0}, noop)
print("  missing source: ok=%s (%s)" % (ok4, detail4))
if ok4: fails.append("claimed success moving a nonexistent game")

# 5. a single-file game moves too
open(A + "/solo.iso", "wb").write(b"z" * 2048)
ok5, _ = W.do_move({"name": "solo", "from": A + "/solo.iso", "to": B + "/solo.iso", "size": 2048}, noop)
print("  single file: ok=%s  landed=%s  source gone=%s"
      % (ok5, os.path.exists(B + "/solo.iso"), not os.path.exists(A + "/solo.iso")))
if not (ok5 and os.path.exists(B + "/solo.iso") and not os.path.exists(A + "/solo.iso")):
    fails.append("single-file move broken")

shutil.rmtree(root, ignore_errors=True)
print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
