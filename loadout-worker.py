#!/usr/bin/env python3
"""Background copier for the Loadout.

The manager used to copy on a thread inside itself, so closing it killed the transfer
and you had to sit and watch a 15GB game finish. This runs as a systemd user service
instead: the manager writes a queue and exits, this does the work, and when it is done
it raises the Steam-sync flag so shortcuts update.

Progress is written to a JSON file so the manager can show the live state whenever it
is reopened.
"""
import json, os, shutil, sys, time

HOME = os.path.expanduser("~")
QUEUE = os.path.join(HOME, ".loadout-queue.json")
PROGRESS = os.path.join(HOME, ".loadout-progress.json")
DIRTY = os.path.join(HOME, ".loadout-dirty")
LOG = os.path.join(HOME, "loadout-worker.log")


def log(msg):
    with open(LOG, "a") as f:
        f.write("%s  %s\n" % (time.strftime("%F %T"), msg))


def write_progress(**kw):
    kw["updated"] = time.time()
    try:
        tmp = PROGRESS + ".tmp"
        json.dump(kw, open(tmp, "w"))
        os.replace(tmp, PROGRESS)
    except Exception:
        pass


CHUNK = 8 * 1024 * 1024


def copy_file(src, dst, base_done, on_bytes):
    """Copy one file in chunks, reporting as it goes.

    shutil.copy2 is a single blocking call, so a game that is one big 768MB AppImage
    showed no movement at all until it finished. Chunked copying gives real progress
    for large single-file games."""
    done = base_done
    last = 0.0
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            buf = fi.read(CHUNK)
            if not buf:
                break
            fo.write(buf)
            done += len(buf)
            now = time.time()
            if now - last > 0.4:
                last = now
                on_bytes(done)
    shutil.copystat(src, dst)
    return done


def copy_tree(src, dst, on_bytes):
    """Copy src -> dst, RESUMING if dst already holds part of it.

    A file is skipped when the destination already has the same size, so an interrupted
    transfer picks up where it stopped instead of starting over. The partially-written
    file at the point of interruption has the wrong size, so it is recopied."""
    files, total = [], 0
    for r, _, fs in os.walk(src):
        for f in fs:
            p = os.path.join(r, f)
            try:
                sz = os.path.getsize(p)
            except OSError:
                sz = 0
            files.append((p, sz))
            total += sz
    done, last, skipped = 0, 0.0, 0
    os.makedirs(dst, exist_ok=True)
    for p, sz in files:
        rel = os.path.relpath(p, src)
        out = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            if os.path.exists(out) and os.path.getsize(out) == sz and sz > 0:
                done += sz
                skipped += sz
                continue                      # already transferred
        except OSError:
            pass
        if sz > CHUNK:
            done = copy_file(p, out, done, lambda d: on_bytes(d, total))
        else:
            shutil.copy2(p, out)
            done += sz
        now = time.time()
        if now - last > 0.5:
            last = now
            on_bytes(done, total)
    on_bytes(done, total)
    if skipped:
        log("resumed: %.1f MB already present, skipped" % (skipped / 1048576.0))
    return total


def tree_size(path):
    """(bytes, file_count) under path — used to prove a move arrived intact."""
    if os.path.isfile(path):
        try:
            return os.path.getsize(path), 1
        except OSError:
            return 0, 0
    total, n = 0, 0
    for r, _, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(r, f))
                n += 1
            except OSError:
                pass
    return total, n


def do_move(m, on_bytes):
    """Relocate one game between disks, COPY -> VERIFY -> delete.

    The original is deleted only after the copy is on the destination disk and measures the
    same (bytes and file count). Anything short of that leaves both copies in place: wasting
    disk is recoverable, a half-moved game is not. The copy lands on a `.part` name first, so
    an interrupted move never looks like a finished game.
    """
    src, dst = m["from"], m["to"]
    if not os.path.exists(src):
        return False, "source is gone"
    if os.path.exists(dst):
        return False, "destination already exists"
    want_b, want_n = tree_size(src)
    tmp = dst + ".part"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src):
        copy_tree(src, tmp, on_bytes)
    else:
        copy_file(src, tmp, 0, lambda d: on_bytes(d, want_b))
    got_b, got_n = tree_size(tmp)
    if got_b != want_b or got_n != want_n:
        return False, ("copy mismatch: %d bytes/%d files vs %d/%d — original kept"
                       % (got_b, got_n, want_b, want_n))
    os.rename(tmp, dst)
    # verified present at the destination; only now is it safe to reclaim the old copy
    if os.path.isdir(src):
        shutil.rmtree(src)
    else:
        os.remove(src)
    return True, "%.1f MB" % (want_b / 1048576.0)


def main():
    if not os.path.exists(QUEUE):
        return 0
    try:
        job = json.load(open(QUEUE))
    except Exception as e:
        log("bad queue file: %s" % e)
        os.remove(QUEUE)
        return 1
    pulls, drops = job.get("pulls", []), job.get("drops", [])
    moves = job.get("moves", [])
    log("start: %d pull(s), %d drop(s), %d move(s)" % (len(pulls), len(drops), len(moves)))
    grand = max(sum(p.get("size", 0) for p in pulls) + sum(m.get("size", 0) for m in moves), 1)
    moved = 0

    # Moves go first: they free space on the disk a pull may be about to land on.
    for m in moves:
        started = time.time()
        write_progress(state="moving", name=m["name"], done=moved, total=grand)

        def on_b(b, t=m.get("size", 1) or 1, _n=m["name"], _m=moved, _s=started):
            el = max(time.time() - _s, 0.001)
            write_progress(state="moving", name=_n, done=_m + b, total=grand,
                           item_done=b, item_total=t, rate=b / el)
        try:
            ok, detail = do_move(m, on_b)
        except Exception as e:
            ok, detail = False, str(e)
        log(("moved %s to %s (%s)" if ok else "move FAILED %s -> %s: %s")
            % (m["name"], m.get("disk", m["to"]), detail))
        moved += m.get("size", 0)

    for d in drops:
        write_progress(state="freeing", name=d["name"], done=moved, total=grand)
        try:
            if d.get("kind") == "game":
                # a game's files can span the internal and SD branches; remove each and
                # tidy up every system dir it leaves empty.
                sysdirs = set()
                for fp in d.get("files", []):
                    sysdirs.add(os.path.dirname(fp))
                    if os.path.exists(fp):
                        os.remove(fp)
                for sd in sysdirs:
                    if os.path.isdir(sd) and not os.listdir(sd):
                        os.rmdir(sd)          # system dir emptied -> remove it
            else:
                # `local` is a list of the branch dirs (internal/SD) that hold this title;
                # accept a bare string too for older queues.
                loc = d["local"]
                for path in (loc if isinstance(loc, list) else [loc]):
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    elif os.path.exists(path):
                        os.remove(path)
            log("freed %s" % d["name"])
        except Exception as e:
            log("free FAILED %s: %s" % (d["name"], e))

    for p in pulls:
        name = p["name"]
        started = time.time()

        if p.get("kind") == "game":
            files = p.get("files", [])
            gtot = p.get("size", 0) or 1
            gdone = 0
            ok = True
            for fjob in files:
                fn_nas, fn_loc = fjob["nas"], fjob["local"]
                write_progress(state="copying", name=name, done=moved + gdone, total=grand,
                               item_done=gdone, item_total=gtot)
                try:
                    os.makedirs(os.path.dirname(fn_loc), exist_ok=True)
                    fsz = os.path.getsize(fn_nas)
                    # resume: skip a file already fully copied
                    if os.path.exists(fn_loc) and os.path.getsize(fn_loc) == fsz and fsz:
                        gdone += fsz
                        continue
                    tmp = fn_loc + ".part"

                    def on_b(b, _m=moved, _g=gdone, _gt=gtot, _n=name, _s=started):
                        el = max(time.time() - _s, 0.001)
                        write_progress(state="copying", name=_n, done=moved + _g + b,
                                       total=grand, item_done=_g + b, item_total=_gt,
                                       rate=(_g + b) / el)

                    copy_file(fn_nas, tmp, 0, on_b)
                    os.replace(tmp, fn_loc)
                    gdone += fsz
                except Exception as e:
                    log("copy INTERRUPTED %s: %s (will resume)" % (name, e))
                    write_progress(state="interrupted", name=name, done=moved, total=grand)
                    return 1
            if files:
                # the read-only NAS mount strips the execute bit; restore it on what launches
                os.system(r'find %s \( -iname "*.sh" -o -iname "*.AppImage" \) '
                          r'-exec chmod +x {} + 2>/dev/null'
                          % repr(os.path.dirname(files[0]["local"])))
            log("copied game %s (%.1f MB, %d file(s))" % (name, gtot / 1048576.0, len(files)))
            moved += p.get("size", 0)
            remaining = [q for q in pulls if q["name"] != name]
            try:
                json.dump({"pulls": remaining, "drops": [], "moves": []}, open(QUEUE + ".tmp", "w"))
                os.replace(QUEUE + ".tmp", QUEUE)
            except Exception:
                pass
            continue

        src, dst = p["nas"], p["local"]
        write_progress(state="copying", name=name, done=moved, total=grand,
                       item_done=0, item_total=p.get("size", 0))
        tmp = dst + ".part"
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)   # keep .part: resume into it

            def on_bytes(b, t, _n=name, _m=moved, _s=started):
                el = max(time.time() - _s, 0.001)
                write_progress(state="copying", name=_n, done=_m + b, total=grand,
                               item_done=b, item_total=t, rate=b / el)

            if os.path.isdir(src):
                copy_tree(src, tmp, on_bytes)
                os.rename(tmp, dst)
            else:
                copy_file(src, tmp, 0, lambda d: on_bytes(d, p.get("size", 1)))
                os.replace(tmp, dst)
            # the read-only NAS mount strips the execute bit; restore it
            os.system('find %s -type d -exec chmod u+rwx {} + 2>/dev/null' % repr(dst))
            os.system('find %s \\( -iname "*.exe" -o -iname "*.sh" -o -iname "*.AppImage" '
                      '-o -iname "*.x86_64" \\) -exec chmod +x {} + 2>/dev/null' % repr(dst))
            log("copied %s (%.1f MB)" % (name, p.get("size", 0) / 1048576.0))
        except Exception as e:
            # leave the .part in place -- the next run resumes from it
            log("copy INTERRUPTED %s: %s (will resume)" % (name, e))
            write_progress(state="interrupted", name=name, done=moved, total=grand)
            return 1                          # queue is kept, path unit retriggers
        moved += p.get("size", 0)
        # shrink the queue so a restart does not redo finished games
        remaining = [q for q in pulls if q["name"] != name]
        try:
            json.dump({"pulls": remaining, "drops": [], "moves": []}, open(QUEUE + ".tmp", "w"))
            os.replace(QUEUE + ".tmp", QUEUE)
        except Exception:
            pass

    os.remove(QUEUE)
    write_progress(state="idle", done=grand, total=grand)
    # No Steam refresh here on purpose: the manager already refreshed at Apply time, so
    # the restart is predictable. Raising the flag again would bounce Steam a second
    # time, possibly mid-game.
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
