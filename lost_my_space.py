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
    for pth, dirlist, filelist in os.walk("/"):
        dirlist[:] = [
            x for x in dirlist
            if not os.path.ismount(pth + os.sep + x)]
        for file in filelist:
            action(pth + os.sep + file)


def main():
    """
    Store - or compare against - a filesystem snapshot.
    """
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
        pickle.dump(all_files, open("all_files.pickle", "wb"))
        print("[-] Compressing DB via zstd...", file=sys.stderr)
        os.system("zstd --rm -f -9 all_files.pickle")
    else:
        print("[-] Reading previous filesystem snapshot...",
              file=sys.stderr)
        cmd = ['zstdcat', 'all_files.pickle.zst']
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, _ = proc.communicate()
        all_files = pickle.loads(stdout)

        def action_compare(fullpath):
            try:
                statdata = os.lstat(fullpath)
                if not S_ISDIR(statdata.st_mode):
                    size = statdata.st_size
                    try:
                        if size == all_files[fullpath]:
                            return
                        print("%11d [C] (%d) %s" % (
                            size, size-all_files[fullpath], fullpath))
                    except KeyError:
                        print("%11d [N] %s" % (size, fullpath))
            except Exception:
                pass
        print("[-] Comparing with current...", file=sys.stderr)
        visit_fs(action_compare)


if __name__ == "__main__":
    main()
