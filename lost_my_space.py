#!/usr/bin/env python3
"""
Keep track of used storage in my filesystem.
Launch this once, with "-u" - and it will create a zstd-compressed
snapshot of the files in your current filesystem (and their sizes).

Launch it again, and it will show you the difference between the
previous snapshot and your current state.
"""
import os
import sys
import pickle
import subprocess
from stat import S_ISDIR


def visit_fs(action):
    """
    Used for both storing a snapshot and comparing against one.
    Calls action with each and every filename in your filesystem.
    """
    try:
        exclusions = {
            x.strip()
            for x in open(
                os.path.dirname(os.path.abspath(__file__)) +
                os.sep +
                "lost_my_space.exceptions")
        }
    except:
        exclusions = {}
    # Never report our own snapshot: it changes every run and would show up
    # as a permanent [N] entry.
    exclusions.add(state_dir())
    for pth, dirlist, filelist in os.walk("/"):
        if any(pth.startswith(x) for x in exclusions):
            continue
        dirlist[:] = [
            x for x in dirlist
            if not os.path.ismount(pth + os.sep + x)]
        for file in filelist:
            action(pth + os.sep + file)


def state_dir() -> str:
    """
    Where the snapshot lives. The admin case runs as root and keeps it in
    /var/lib/lost_my_space (mode 0700); anyone else gets their own data dir.
    The DB must NOT live next to the code: the repo is public, and a snapshot
    is historical data that cannot be regenerated (so not a cache either).
    """
    if os.geteuid() == 0:
        return "/var/lib/lost_my_space"
    return os.path.expanduser("~/.local/share/lost_my_space")


def main():
    """
    Store - or compare against - a filesystem snapshot.
    """
    state = state_dir()
    os.makedirs(state, mode=0o700, exist_ok=True)
    db = os.path.join(state, "all_files.pickle")
    if os.geteuid() != 0:
        print("[-] warning: not running as root - large parts of / will be"
              " unreadable and the diff will be incomplete", file=sys.stderr)
    if "-u" in sys.argv:
        all_files, cnt = {}, [0]
        print("[-] Files indexed:            ", flush=True, end='',
              file=sys.stderr)

        def action_store(fullpath):
            try:
                statdata = os.lstat(fullpath)
                if not S_ISDIR(statdata.st_mode):
                    size = statdata.st_size
                    all_files[fullpath] = size
                    cnt[0] += 1
                    if cnt[0] & 0xFFFF == 0:
                        print("\b\b\b\b\b\b\b\b\b\b\b%11d" % cnt[0],
                              flush=True, end='', file=sys.stderr)
            except Exception:
                pass
        visit_fs(action_store)
        print("\b\b\b\b\b\b\b\b\b\b\b%11d" % cnt[0], flush=True,
              file=sys.stderr)
        pickle.dump(all_files, open(db, "wb"))
        print("[-] Compressing DB via zstd...", file=sys.stderr)
        subprocess.run(["zstd", "--rm", "-f", "-9", db], check=False)
    else:
        print("[-] Reading previous filesystem snapshot...",
              file=sys.stderr)
        cmd = ['zstdcat', db + '.zst']
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, _ = proc.communicate()
        all_files = pickle.loads(stdout)
        changes = [0, 0]

        def action_compare(fullpath):
            try:
                statdata = os.lstat(fullpath)
                if not S_ISDIR(statdata.st_mode):
                    size = statdata.st_size
                    try:
                        if size == all_files[fullpath]:
                            return
                        delta = size-all_files[fullpath]
                        print("%11d [C] (%d) %s" % (size, delta, fullpath))
                        changes[0] += delta
                    except KeyError:
                        print("%11d [N] %s" % (size, fullpath))
                        changes[1] += size
            except Exception:
                pass
        print("[-] Comparing with current...", file=sys.stderr)
        visit_fs(action_compare)
        print("[-] Due to new files:      %d" % changes[1], file=sys.stderr)
        print("[-] Due to modified files: %d" % changes[0], file=sys.stderr)

if __name__ == "__main__":
    main()
