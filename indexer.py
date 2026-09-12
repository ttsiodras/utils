#!/usr/bin/env python3
"""
File scanner: tracks files in a SQLite database, computes MD5s in parallel,
and supports duplicate-copy limits (-l) and integrity validation (-v).

    https://github.com/ttsiodras/FileIndexer

See the repository README for usage, and the AI.prompts/ folder for the
prompts used during development. This codebase was built with the help of
local AI models, as a hands-on use case for applying AI the way I want it
(local, private). But don't hold this against it; I did review the result
and honestly believe this to be a good Python codebase.

Models used so far in building/debugging/improving this code:

- Qwen 3.5 122B
- GPT OSS 120B
- Deepseek v4 Flash 0731
- GLM 5.3 Flash
- Qwen 3.8 Flash Next

"""
import argparse
import hashlib
import os
import sqlite3
import sys
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from itertools import chain, islice
from typing import (Dict, Generator, Iterable, List, NamedTuple, Optional,
                    Set, Tuple)


# --- Type aliases ---
HashResult = Optional[str]
SafeFilename = bytes  # bare filename, e.g. b"photo.jpg"
SafeRelPath = bytes  # relative path from top_folder, e.g. b"subdir/photo.jpg"
SafeTopFolder = bytes  # absolute path to the root of a scan, e.g. b"/mnt/data"
AbsPath = bytes  # absolute path to a specific file
TopFolderAndFullPath = Tuple[SafeTopFolder, SafeRelPath]

# List of directories that could not be scanned, as ``(top_folder, rel_path)``
# an empty ``rel_path`` means "the top folder itself", i.e. its whole subtree
# is unknown (see :func:`is_under_failed_dir`). Qualified per folder because
# ``-v all`` merges folders, whose relative paths must not protect each other.
FailedDirs = List[TopFolderAndFullPath]


# --- NamedTuples ---
class FileMetadata(NamedTuple):
    """File metadata from filesystem scan."""
    filename: SafeFilename
    full_path: SafeRelPath
    top_folder: SafeTopFolder
    mtime: float
    filesize: int


class FileRecord(NamedTuple):
    """File record from database."""
    filename: SafeFilename
    full_path: SafeRelPath
    top_folder: SafeTopFolder
    mtime: float
    md5: HashResult
    filesize: int


class LimitCheckResult(NamedTuple):
    """Result of a limit check query."""
    full_path: SafeRelPath
    md5: HashResult
    copies: int


# --- Composite type aliases (depend on NamedTuples above) ---
Insertions = List[FileMetadata]
Updates = List[FileMetadata]
Deletions = List[TopFolderAndFullPath]

# --- Results for report
MatchEntry = Tuple[SafeTopFolder, SafeRelPath, HashResult]
MismatchEntry = Tuple[SafeTopFolder, SafeRelPath, HashResult, HashResult]
NewEntry = TopFolderAndFullPath


class ValidationResult(NamedTuple):
    """Outcome of comparing the DB rows against the filesystem. ``unverified``
    holds the rows whose directory could not be read: they were never checked,
    so they must not be reported as ``missing``.
    """
    match: List[MatchEntry]
    mismatch: List[MismatchEntry]
    missing: List[MatchEntry]
    unverified: List[MatchEntry]
    new_files: List[NewEntry]


def compute_md5(filepath: AbsPath) -> HashResult:
    """Compute MD5 hash of a file, reading in chunks.

    Returns ``None`` on I/O errors so callers can distinguish unreadable
    files from legitimate results (including empty files).
    """
    # Initialize the hasher. usedforsecurity=False avoids warnings on systems
    # where MD5 is flagged as insecure for cryptographic use.
    hasher = hashlib.md5(usedforsecurity=False)
    try:
        with open(filepath, "rb") as f:
            # Read in 4MB chunks to balance memory usage and I/O throughput.
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        # Return None to indicate a failure to read the file (e.g. permissions)
        return None


def stream_md5s(
    items: Iterable[FileMetadata],
    ncores: int,
    batch: Optional[int] = None,
) -> Generator[Tuple[FileMetadata, HashResult, bool], None, None]:
    """Yield ``(item, md5_or_None, degraded)`` as each worker finishes.

    *items* is any iterable of :class:`FileMetadata`; it is consumed
    lazily, so callers may pass a generator (e.g. ``itertools.chain``)
    without materializing the whole list. Results arrive in completion
    order, not submission order, so callers can act on each hash
    immediately without waiting for the full batch.

    ``degraded`` is True only when ``md5`` is ``None`` *because the hashing
    pool broke* (a worker was killed / OOM'd), as opposed to a normal
    per-file I/O error. Callers can use it to avoid treating a mass pool
    failure as a per-file read error.

    Only a bounded window (``batch``) of files is submitted to the pool at
    a time; as one completes it is yielded and a replacement is submitted.
    This keeps the number of in-flight futures (and thus parent-process
    memory) proportional to ``batch`` rather than to the total file count,
    without changing the per-file commit cadence expected by callers.
    """
    if batch is None or batch <= 0:
        batch = ncores * 8  # default window: a small multiple of workers
    with ProcessPoolExecutor(max_workers=ncores) as executor:
        it = iter(items)
        # Submit an initial bounded window of work. Keep an explicit
        # future->item map (bounded by ``batch``) to associate each result
        # with its item; the full input list is never materialized here.
        future_to_item = {
            executor.submit(
                compute_md5, os.path.join(item.top_folder, item.full_path)
            ): item
            for item in islice(it, batch)
        }
        pending = set(future_to_item)
        pool_dead = False
        while pending:
            # Yield results in true completion order, refilling one-for-one.
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                item = future_to_item.pop(future)
                try:
                    md5: HashResult = future.result()
                except BrokenProcessPool:
                    # A worker was killed (OOM / crash): the pool fails the
                    # *in-flight* futures, and the parent's next submit() may
                    # never be reached -- so this, not the submit guard below,
                    # is what flags a dead pool in practice. Flag it BEFORE
                    # yielding: these files then take the degraded ("a worker
                    # died") path instead of being falsely logged as per-file
                    # "could not read" errors. No refill happens below.
                    md5 = None
                    pool_dead = True
                except Exception:  # pylint: disable=broad-exception-caught
                    # Some other failure in the worker (e.g. MemoryError on a
                    # huge file). Rather than abort the sync, degrade to the
                    # "could not read" path: md5=None (a NULL row) makes
                    # find_changes re-hash it on the next run.
                    md5 = None
                yield item, md5, pool_dead
                if pool_dead:
                    # The pool broke during a refill below; already-submitted
                    # futures are handled above (result() raises BrokenProcessPool
                    # md5 -> None), for both the rest of this `done` batch, and
                    # any still sitting in `pending` (they error out in later
                    # while iterations). Just stop refilling it.
                    continue
                # Refill the window with the next unreached file, if any.
                nxt = next(it, None)
                if nxt is None:
                    continue
                try:
                    f = executor.submit(
                        compute_md5,
                        os.path.join(nxt.top_folder, nxt.full_path),
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    # The pool is broken (e.g. a worker was killed or OOM'd), so
                    # submitting any further work raises immediately. Stop
                    # submitting to the dead pool; degrade this file and every
                    # remaining one to md5=None (a NULL row) so find_changes
                    # re-hashes them all on the next run, instead of aborting
                    # the sync with an unhandled traceback. Note the split of
                    # labour: `it` (the never-submitted remainder of the input)
                    # is drained inline right here, while `done`/`pending` (the
                    # already-submitted but now-broken futures) are drained by
                    # the future.result() -> None path above -- so no item is
                    # dropped and none is drained twice.
                    pool_dead = True
                    yield nxt, None, True
                    for remaining in it:
                        yield remaining, None, True
                    continue
                future_to_item[f] = nxt
                pending.add(f)
    # The loop can stop refilling as soon as the pool is broken, leaving the
    # never-submitted tail of `it` undrained when the death was seen on a
    # future. Drain it here, so every item yields exactly once as md5=None.
    if pool_dead:
        for remaining in it:
            yield remaining, None, True


# User customization: directories we never want indexed. Any directory whose
# path contains one of these tokens as a substring is skipped (both its files
# and its subtree). Kept as bytes to match the byte paths used in the scan.
#
# Add a distinctive path fragment for anything you'd rather not index (e.g.
# large files you can cheaply re-download, such as model weights or offline
# wikipedia mirrors). An empty list disables the filter.
#
_DROP_DIR_TOKENS: List[bytes] = [
    # b'Deepseek', b'aard',
]


def scan_folder(  # pylint: disable=too-many-branches
    top_folder: SafeTopFolder,
) -> Tuple[List[FileMetadata], List[SafeRelPath]]:
    """Recursively scan a folder and return file metadata.

    *top_folder* must be an absolute path as bytes. Returns a tuple of
    ``(results, failed_dirs)`` where ``results`` is a list of ``FileMetadata``
    (filename, full_path relative to top_folder, top_folder, mtime, filesize)
    and ``failed_dirs`` is a list of relative paths to directories that could
    not be entered (permission denied, transient I/O error, ...) and were
    therefore skipped. Rows under such directories must NOT be treated as
    'deleted' by callers. An external USB drive can have a transient cable
    related fault; we dont want to lose 1000s of MD5 checksums because of
    such an issue!

    Uses ``os.scandir`` directly (rather than ``os.walk``) so each entry
    already carries its symlink/stat info, avoiding an extra ``islink`` +\
    ``stat`` syscall per file -- significant when scanning millions of files.

    Raises FileNotFoundError if the folder does not exist.
    """
    if not os.path.isdir(top_folder):
        raise FileNotFoundError(
            f"Folder does not exist: {to_printable(top_folder)}")
    results: List[FileMetadata] = []
    failed_dirs: List[SafeRelPath] = []
    count = 0

    # Explicit stack (iterative, to avoid hitting the recursion limit on very
    # deep trees) for a depth-first, followlinks=False traversal.
    stack = [top_folder]
    while stack:
        dirpath = stack.pop()
        # User customization: skip any directory whose path contains a token
        # we do not want indexed (also applies to the top folder itself).
        if any(token in dirpath for token in _DROP_DIR_TOKENS):
            continue
        try:
            entries = list(os.scandir(dirpath))
        except OSError as error:
            # Could not enter this directory (EACCES, transient EIO, ...).
            # Record it so its rows are not treated as deleted, and warn.
            try:
                rel = os.path.relpath(dirpath, top_folder)
            except (ValueError, OSError):
                rel = None
            if rel is not None:
                failed_dirs.append(rel)
            location = getattr(error, 'filename', None) or dirpath
            print(f"[!] Unreadable directory, skipping: "
                  f"{to_printable(location)}")
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    # Skip symbolic links (to files or dirs): prevents infinite
                    # loops and scanning outside top_folder (followlinks=False).
                    continue
                if entry.is_dir():
                    # Descend into real subdirectories only.
                    stack.append(entry.path)
                    continue
            except OSError:
                # Could not stat this entry; skip it rather than aborting.
                continue
            # A regular file: use the entry's cached stat (no extra syscall).
            try:
                st = entry.stat()
            except OSError:
                continue
            results.append(FileMetadata(
                filename=entry.name,
                full_path=os.path.relpath(entry.path, top_folder),
                top_folder=top_folder,
                mtime=st.st_mtime,
                filesize=st.st_size,
            ))
            count += 1
            if count % 1000 == 0:
                print(f"\r[.] {to_printable(top_folder)}: {count} files...",
                      end="", flush=True)
    print(f"\r[.] {to_printable(top_folder)}: {count} files...",
          end="\n", flush=True)
    return results, failed_dirs


_IFS_SEP: bytes = os.fsencode(os.sep)  # bytes form of the path separator


def _qualify_failed_dirs(
    top_folder: SafeTopFolder, failed_dirs: List[SafeRelPath]
) -> FailedDirs:
    """Bind scan_folder()'s relative failed dirs to their *top_folder*.

    ``b''``/``b'.'`` (the top folder itself was unenterable) becomes the
    "whole tree is unknown" marker of :func:`is_under_failed_dir`.
    """
    return [(top_folder, b'' if rel in (b'', b'.') else rel)
            for rel in failed_dirs]


def is_under_failed_dir(
    top_folder: SafeTopFolder, full_path: SafeRelPath, failed_dirs: FailedDirs
) -> bool:
    """True if *full_path* (relative to *top_folder*) is under a failed dir.

    Entries of other top folders are ignored: only a scan failure of *its own*
    folder protects a path. A directory fails *as a whole*, so a relative path
    is protected when it equals a failed dir or lies below it.
    """
    for fd_folder, fd_rel in failed_dirs:
        if fd_folder != top_folder:
            continue
        if fd_rel in (b'', b'.'):
            # The top folder itself could not be scanned, so its whole subtree
            # is unknown: an unscanned area must never be treated as "deleted"
            # (sync) or "missing" (validate).
            return True
        if full_path == fd_rel or full_path.startswith(fd_rel + _IFS_SEP):
            return True
    return False


class FileDB:
    """Handles SQLite database operations for file tracking."""

    # How long SQLite waits for a write lock before giving up (the sqlite3
    # busy_timeout). Overlapping instances are legitimate, so opening a DB
    # another process holds must wait instead of dying with "database
    # is locked". Set at connect() time, i.e. before the WAL PRAGMA below,
    # which needs the write lock on a first conversion and would otherwise
    # raise at once.
    BUSY_TIMEOUT_SECONDS: float = 30.0

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        # Every failure here is an environment problem the user can fix (parent
        # directory missing, unwritable disk, file that is not a database).
        try:
            self.conn = sqlite3.connect(
                db_path, timeout=self.BUSY_TIMEOUT_SECONDS)
        except sqlite3.Error as err:
            print(f"Error: cannot open database {db_path}: {err}")
            sys.exit(1)
        try:
            mode = self.conn.execute("PRAGMA journal_mode=WAL").fetchone()
        except sqlite3.OperationalError as err:
            # e.g. another instance is still setting up the DB and the busy
            # timeout expired. WAL is an optimisation: warn and carry on with
            # the journal mode already in use.
            print(f"[!] Could not switch {db_path} to WAL mode: {err} "
                  f"(continuing with the journal mode currently in use).")
            mode = None
        except sqlite3.Error as err:
            # e.g. "file is not a database": whatever sits at --db is unusable.
            print(f"Error: cannot use database {db_path}: {err}")
            sys.exit(1)
        # On filesystems without WAL support (FAT/exFAT, some network
        # shares) the PRAGMA silently keeps another journal mode; warn so
        # the user knows the DB isn't behaving as configured.
        if mode and mode[0] != 'wal':
            print(f"[!] Journal mode is {mode[0]}, not WAL, on {db_path}"
                  f" (WAL unsupported on this filesystem).")
        try:
            self.conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error as err:
            # Not fatal: SQLite simply keeps its (more durable) default.
            print(f"[!] Could not set synchronous mode on {db_path}: {err} "
                  f"(keeping SQLite's default).")
        try:
            self._ensure_table()
        except sqlite3.Error as err:
            # e.g. "file is not a database", or an unwritable DB.
            print(f"Error: cannot initialise the schema of {db_path}: {err}")
            sys.exit(1)

    def __enter__(self) -> "FileDB":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _ensure_table(self) -> None:
        """Create the files table and indexes if they don't exist."""
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS files (
                filename BLOB NOT NULL,
                full_path BLOB NOT NULL,
                top_folder BLOB NOT NULL,
                mtime REAL NOT NULL,
                md5 TEXT,
                filesize INTEGER NOT NULL,
                PRIMARY KEY (top_folder, full_path)
            )
        ''')
        # Index on md5 speeds up duplicate detection in query_limit()
        self.conn.execute('CREATE INDEX IF NOT EXISTS idx_md5 ON files(md5)')
        self.conn.commit()

    def load_folder(
        self, top_folder_bytes: SafeTopFolder
    ) -> Dict[TopFolderAndFullPath, FileRecord]:
        """Return rows for top_folder, keyed by (top_folder, full_path)."""
        cursor = self.conn.execute(
            'SELECT filename, full_path, top_folder, mtime, md5, filesize '
            'FROM files WHERE top_folder = ?',
            (top_folder_bytes,)
        )
        result: Dict[TopFolderAndFullPath, FileRecord] = {}
        for row in cursor:
            record = FileRecord(*row)
            result[(record.top_folder, record.full_path)] = record
        return result

    def upsert_with_md5(self, item: FileMetadata, md5: HashResult) -> None:
        """Insert or update a file row including its MD5."""
        # filename/top_folder are deliberately not updated: they are the
        # conflict key (top_folder, full_path) or its basename, so they can
        # never differ on conflict.
        self.conn.execute(
            '''INSERT INTO files (filename, full_path, top_folder,
               mtime, md5, filesize) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(top_folder, full_path) DO UPDATE SET
                   mtime=excluded.mtime,
                   md5=excluded.md5,
                   filesize=excluded.filesize''',
            (item.filename, item.full_path, item.top_folder,
             item.mtime, md5, item.filesize),
        )

    def commit(self) -> None:
        """Commit the current transaction."""
        self.conn.commit()

    def delete_paths(self, paths: List[TopFolderAndFullPath]) -> None:
        """Delete rows by (top_folder, full_path) tuples. Caller commits."""
        self.conn.executemany(
            'DELETE FROM files WHERE top_folder = ? AND full_path = ?',
            paths,
        )

    def query_limit(
        self, limit: int,
        top_folders: Optional[Iterable[SafeTopFolder]] = None,
    ) -> List[LimitCheckResult]:
        """Find (full_path, md5) pairs that appear in fewer than ``limit``
        distinct top_folders.

        If *top_folders* is given, only copies within those folders count
        (the check is scoped to exactly the folders the user asked about);
        otherwise every top_folder in the database is considered.
        """
        if top_folders:
            scope = list(top_folders)
            placeholders = ','.join('?' * len(scope))
            cursor = self.conn.execute(f'''
                SELECT full_path, md5, COUNT(DISTINCT top_folder) AS copies
                FROM files
                WHERE md5 IS NOT NULL AND top_folder IN ({placeholders})
                GROUP BY full_path, md5
                HAVING copies < ?''', (*scope, limit))
        else:
            cursor = self.conn.execute('''
                SELECT full_path, md5, COUNT(DISTINCT top_folder) AS copies
                FROM files
                WHERE md5 IS NOT NULL
                GROUP BY full_path, md5
                HAVING copies < ?''', (limit,))
        return [LimitCheckResult(*row) for row in cursor]

    def get_rows_for_validation(
        self, top_folder: Optional[SafeTopFolder] = None
    ) -> List[FileRecord]:
        """Get rows to validate, optionally filtered by top_folder.

        Passing ``None`` (the default) returns every row.
        """
        if top_folder is None:
            cursor = self.conn.execute(
                'SELECT filename, full_path, top_folder, mtime, md5, '
                'filesize FROM files')
        else:
            cursor = self.conn.execute(
                'SELECT filename, full_path, top_folder, mtime, md5, '
                'filesize FROM files WHERE top_folder = ?',
                (top_folder,))
        return [FileRecord(*row) for row in cursor]

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()


def to_printable(data: bytes) -> str:
    """Convert a path to a printable string, never raising.

    ``os.fsdecode`` (surrogateescape) rather than ``decode('utf-8',
    errors='replace')``: the latter is *lossy* -- two distinct byte paths can
    collapse onto one string, and the '?' it inserts hides the name the
    operator needs. Reports use errors='surrogateescape', so a path
    rendered here round-trips to its original bytes.
    """
    return os.fsdecode(data)


def sync_files_with_md5(
    db: FileDB,
    files: Iterable[FileMetadata],
    ncores: int,
    total: int,
    quiet: bool = False,
) -> None:
    """Compute MD5s for *files*, printing and committing as results arrive.

    *files* may be any iterable (e.g. an ``itertools.chain`` or generator)
    and is consumed lazily by the hashing pool, so callers do not need to
    build a full list or a path-to-item reverse map. *total* is the number
    of files to be hashed, used for the progress display.

    *quiet* drops the one-line-per-hashed-file progress line: on a first sync
    of a large library that is millions of lines once stdout goes to a log.
    Warnings (``[!]``) and the summaries always print, whatever *quiet* says.
    """
    count = 0
    degraded = 0
    for item, md5, died in stream_md5s(files, ncores):
        count += 1
        abs_bytes: AbsPath = os.path.join(item.top_folder, item.full_path)
        if md5 is None and not died:
            print(f"[!] MD5 ERROR, could not read: {to_printable(abs_bytes)}")
        elif md5 is not None:
            if not quiet:
                print(f"[-] MD5: {count}/{total} files, "
                      f"computed MD5 for {to_printable(abs_bytes)}")
        else:
            # md5 is None because the hashing pool broke (a worker died);
            # avoid flooding the log with a per-file error for every file that
            # was in flight. They are stored as NULL and retried next run.
            degraded += 1
        # Update the database immediately for this file.
        # Frequent commits ensure data is saved on crash.
        db.upsert_with_md5(item, md5)
        db.commit()
    if degraded:
        print(f"[!] A hashing worker died; {degraded} file(s) left unhashed "
              f"(md5=NULL) and will be retried on the next run.")


def find_changes(
    db: FileDB, top_folder_bytes: SafeTopFolder
) -> Tuple[Insertions, Updates, Deletions]:
    """Compare filesystem state with database, return categorised changes."""
    fs_data, scanned_failed = scan_folder(top_folder_bytes)
    failed_dirs = _qualify_failed_dirs(top_folder_bytes, scanned_failed)
    db_data = db.load_folder(top_folder_bytes)
    fs_paths = {item.full_path for item in fs_data}

    to_insert: Insertions = []
    to_update: Updates = []

    for item in fs_data:
        key = (top_folder_bytes, item.full_path)
        if key not in db_data:
            # File exists on disk but not in DB.
            to_insert.append(item)
        elif (db_data[key].mtime != item.mtime
              or db_data[key].filesize != item.filesize
              or db_data[key].md5 is None):
            # File metadata (mtime or size) changed, or previous MD5
            # computation failed (md5 is None); requires re-hashing.
            to_update.append(item)

    # Identify files in DB that are no longer present on the filesystem -- but
    # NOT files under a directory that could not be scanned (they are not really
    # missing; deleting them on a transient EIO/permission error would silently
    # discard live index rows). The worst case becomes "rows survive, re-check
    # on the next run" instead of "rows vanish".
    to_delete: Deletions = [
        (tf, fp) for (tf, fp) in db_data
        if fp not in fs_paths
        and not is_under_failed_dir(tf, fp, failed_dirs)
    ]
    return to_insert, to_update, to_delete


def perform_sync(
    db: FileDB, top_folder: str, ncores: int, quiet: bool = False
) -> bool:
    """Synchronise a folder against the database.

    Inserts new files, updates rows whose mtime or filesize changed,
    and removes rows for files that no longer exist on disk.

    Returns True on success, or False if *top_folder* no longer exists (in
    which case a warning is printed and the folder is skipped) so callers can
    keep going with the remaining folders but still exit non-zero.

    *quiet* is passed through to :func:`sync_files_with_md5`.
    """
    # Resolve symlinks and use os.fsencode() for correct POSIX byte encoding.
    top_bytes: SafeTopFolder = os.fsencode(
        os.path.realpath(top_folder)
    )
    try:
        to_insert, to_update, to_delete = find_changes(db, top_bytes)
    except FileNotFoundError:
        print(f"[!] Skipping missing (or non-folder): {top_folder}")
        return False
    # Combine lazily (chain) instead of building a new list, and pass the
    # known count separately for the progress display.
    sync_files_with_md5(
        db,
        chain(to_insert, to_update),
        ncores,
        total=len(to_insert) + len(to_update),
        quiet=quiet,
    )
    if to_delete:
        for _, full_path_bytes in to_delete:
            print(f"[-] Deleted (missing): {to_printable(full_path_bytes)}")
        db.delete_paths(to_delete)
        db.commit()
    print(
        f"[-] Sync complete: {len(to_insert)} inserted, "
        f"{len(to_update)} updated, {len(to_delete)} deleted"
    )
    return True


def run_limit_check(
    db: FileDB, limit: int, report_path: str,
    top_folders: Optional[Iterable[SafeTopFolder]] = None,
) -> None:
    """Run the limit check and write results to *report_path*.

    Each line has the form: ``<full_path>#@#<existing_copy_count> <md5>``.
    *top_folders* scopes the check to those folders (when given); otherwise
    every folder in the database is considered.

    ``#@#`` is a convention, not an escaping-aware protocol: a name containing
    it is indistinguishable from the separator, so parsers should match the
    trailing ``<copies> <md5>`` fields rather than trust the first ``#@#``.
    """
    results = db.query_limit(limit, top_folders)
    with open(report_path, 'w', encoding='utf-8',
              errors='surrogateescape') as f:
        for full_path, md5, copies in results:
            path_str = to_printable(full_path)
            f.write(f"{path_str}#@#{copies} {md5}\n")


def scan_target(
    top_folder: Optional[SafeTopFolder], rows: List[FileRecord]
) -> Tuple[List[FileMetadata], FailedDirs]:
    """Scan filesystem for *top_folder* or all top_folders found in *rows*.

    If a top_folder from the DB no longer exists on disk, a warning is
    printed and that folder is skipped instead of crashing the whole run.
    Returns ``(results, failed_dirs)``; the latter are qualified per folder
    (see :func:`is_under_failed_dir`), so one folder's scan failure cannot
    hide problems in another.
    """
    if top_folder is not None:
        res, fds = scan_folder(top_folder)
        return res, _qualify_failed_dirs(top_folder, fds)

    top_folders: Set[SafeTopFolder] = {row.top_folder for row in rows}
    results: List[FileMetadata] = []
    failed_dirs: FailedDirs = []
    for tf in top_folders:
        try:
            res, fds = scan_folder(tf)
            results.extend(res)
            failed_dirs.extend(_qualify_failed_dirs(tf, fds))
        except FileNotFoundError:
            print(f"[!] Top folder missing, skipping: {to_printable(tf)}")
    return results, failed_dirs


def compute_md5s_for_matches(
    fs_data: List[FileMetadata],
    db_data: Dict[TopFolderAndFullPath, HashResult],
    ncores: int,
) -> Dict[TopFolderAndFullPath, HashResult]:
    """Compute MD5s by (top_folder, full_path) for FS items that exist in DB.

    Streams results as workers finish, printing each one immediately.
    The matched items are passed to the hashing pool as a lazy generator.
    """
    # One pass: collect the items we must hash (they exist in the DB).
    matched = [
        item for item in fs_data
        if (item.top_folder, item.full_path) in db_data
    ]
    total = len(matched)
    count = 0
    result: Dict[TopFolderAndFullPath, HashResult] = {}
    last_percent = -1.0
    for item, md5, _died in stream_md5s(matched, ncores):
        count += 1
        percent = (count / total) * 100 if total else 0
        if percent >= last_percent + 1 or count == total:
            print(f"\r[-] Validation: {percent:.2f}% ({count}/{total})",
                  end="", flush=True)
            last_percent = percent
        result[(item.top_folder, item.full_path)] = md5
    print()
    return result


def classify_entries(
    db_data: Dict[TopFolderAndFullPath, HashResult],
    fs_lookup: Dict[TopFolderAndFullPath, FileMetadata],
    computed_md5s: Dict[TopFolderAndFullPath, HashResult],
    failed_dirs: FailedDirs,
) -> ValidationResult:
    """Split DB rows / filesystem entries into the report's categories.

    *failed_dirs* (from :func:`scan_target`) marks the areas the scan could not
    enter: a DB row under one of them is ``unverified``, **not** ``missing`` --
    the scan never looked, so nothing proves the file is gone. Same reasoning
    sync mode applies via :func:`is_under_failed_dir` before deleting rows;
    without it one transient EACCES/EIO becomes thousands of false "your data
    is gone" alarms.
    """
    match: List[MatchEntry] = []
    mismatch: List[MismatchEntry] = []
    missing: List[MatchEntry] = []
    unverified: List[MatchEntry] = []
    for key, expected_md5 in db_data.items():
        top_folder, full_path = key
        if key not in fs_lookup:
            if is_under_failed_dir(top_folder, full_path, failed_dirs):
                # Not scanned (unreadable directory): unknown, not missing.
                unverified.append((*key, expected_md5))
            else:
                missing.append((*key, expected_md5))
        else:
            actual = computed_md5s.get(key)
            if actual == expected_md5:
                match.append((*key, expected_md5))
            else:
                mismatch.append((*key, expected_md5, actual))
    new_files = [
        key for key in fs_lookup if key not in db_data
    ]
    return ValidationResult(match, mismatch, missing, unverified, new_files)


def write_report(report_path: str, result: ValidationResult) -> None:
    """Write a categorised validation report, omitting empty sections."""
    # 'surrogateescape' (see to_printable) keeps non-UTF-8 names byte-exact.
    with open(report_path, 'w', encoding='utf-8', errors='surrogateescape') as f:
        if result.match:
            f.write("=== MATCH ===\n")
            for tf, p, md5 in result.match:
                f.write(f"MATCH: {to_printable(tf)}/{to_printable(p)} "
                        f"(md5={md5})\n")
            f.write("\n")
        if result.mismatch:
            f.write("=== MISMATCH ===\n")
            for tf, p, exp, act in result.mismatch:
                exp_str = "UNREADABLE" if exp is None else exp
                actual_str = "UNREADABLE" if act is None else act
                line = (f"MISMATCH: {to_printable(tf)}/{to_printable(p)} "
                        f"(expected={exp_str}, actual={actual_str})")
                print(f"[!] {line}")
                f.write(f"{line}\n")
            f.write("\n")
        if result.missing:
            f.write("=== MISSING ===\n")
            for tf, p, exp in result.missing:
                line = f"MISSING: {to_printable(tf)}/{to_printable(p)} " + \
                       f"(expected_md5={exp})"
                print(f"[!] {line}")
                f.write(f"{line}\n")
            f.write("\n")
        if result.unverified:
            f.write("=== UNVERIFIED (unreadable dir) ===\n")
            for tf, p, exp in result.unverified:
                f.write(f"UNVERIFIED: {to_printable(tf)}/{to_printable(p)} "
                        f"(expected_md5={exp}; directory unreadable -- NOT "
                        f"verified, NOT missing)\n")
            f.write("\n")
        if result.new_files:
            f.write("=== NEW ===\n")
            for tf, p in result.new_files:
                line = f"NEW: {to_printable(tf)}/{to_printable(p)}"
                print(f"[-] {line}")
                f.write(f"{line}\n")


def run_validation(
    db: FileDB, target: str, report_path: str, ncores: int
) -> bool:
    """Validate DB rows against the filesystem.

    Generates a report with MATCH, MISMATCH, MISSING, UNVERIFIED, and NEW
    sections. Returns True on success, or False if *target* (a specific folder)
    no longer exists -- in which case a warning is printed and nothing is
    written. ``target == 'all'`` already skips any missing DB top_folder with
    a warning inside :func:`scan_target`.
    """
    top_bytes: Optional[SafeTopFolder] = (
        None if target == 'all'
        else os.fsencode(os.path.realpath(target)))
    rows = db.get_rows_for_validation(top_bytes)
    db_data: Dict[TopFolderAndFullPath, HashResult] = {
        (row.top_folder, row.full_path): row.md5 for row in rows
    }
    try:
        fs_data, failed_dirs = scan_target(top_bytes, rows)
    except FileNotFoundError:
        print(f"[!] Skipping missing (or non-folder): {target}")
        return False
    fs_lookup = {(item.top_folder, item.full_path): item for item in fs_data}
    computed_md5s = compute_md5s_for_matches(fs_data, db_data, ncores)
    result = classify_entries(
        db_data, fs_lookup, computed_md5s, failed_dirs)
    write_report(report_path, result)
    if result.unverified:
        print(f"[!] {len(result.unverified)} row(s) NOT verified (unreadable "
              f"directory, see the UNVERIFIED section of {report_path}); "
              f"they are not reported as MISSING.")
    return True


def _db_inside_top_folder(folder: str, db_path: str) -> bool:
    """True if *db_path* is inside (or equal to) *folder*, both resolved.

    Used to reject storing the database inside a folder that is about to be
    scanned: the tool would otherwise index its own DB file (and live
    -wal/-shm sidecars).
    """
    folder_canon = os.path.realpath(folder)
    db_canon = os.path.realpath(db_path)
    try:
        return (os.path.commonpath([db_canon, folder_canon])
                == folder_canon)
    except ValueError:
        # e.g. paths on different drives share no common prefix -> not inside.
        return False


def parse_args() -> argparse.Namespace:
    """Parse and return command line arguments, otherwise exit with help."""
    parser = argparse.ArgumentParser(
        description=(
            'File scanner with SQLite tracking, parallel MD5, and validation.'
        )
    )
    parser.add_argument('top_folder', nargs='*', help='Top folder(s) to scan')
    parser.add_argument(
        '-n', '--ncores', type=int, default=None,
        help='Number of cores for parallel MD5 computation (default: all)',
    )
    parser.add_argument(
        '-l', '--limit', type=int, default=None,
        help='Verify each (full_path, md5) appears in at least N top_folders',
    )
    parser.add_argument(
        '-v', '--validate', nargs='?', const='all', default=None,
        help='Validate DB against filesystem. arg: top_folder or "all"',
    )
    parser.add_argument(
        '--db', type=str, default='files.db',
        help='Path to SQLite database (default: files.db in current folder)',
    )
    parser.add_argument(
        '--report', type=str, default='report.log',
        help='Path to report file (default: report.log in current folder)',
    )
    parser.add_argument(
        '-q', '--quiet', action='store_true',
        help='Do not print one progress line per hashed file (warnings and '
             'summaries still print); good when piping a big sync to a log.',
    )
    args = parser.parse_args()
    if args.validate is not None and args.limit is not None:
        parser.error(
            "--validate (-v) and --limit (-l) are mutually exclusive; "
            "run them as separate commands.")
    if args.validate is None and args.limit is None and not args.top_folder:
        parser.print_help()
        sys.exit(1)
    return args


def _make_streams_error_tolerant() -> None:
    """Make sure an odd file name can never abort the run while printing it.

    to_printable() renders paths losslessly, which can hand ``print()``
    surrogates a strict stdout/stderr refuses to encode.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # not a reconfigurable text stream (e.g. replaced)
        try:
            reconfigure(errors='backslashreplace')
        except (AttributeError, ValueError, OSError):
            pass


def main() -> None:
    """Entry point: parse arguments and dispatch to the appropriate mode."""
    _make_streams_error_tolerant()
    args = parse_args()

    # Fail fast if the database is stored inside a folder we are about to scan.
    # Doing so would make the tool index its own DB file (and live -wal/-shm
    # sidecars), which churns every run and reads a transiently inconsistent
    # file. That is an anti-pattern, so abort before any walk or write happens.
    for folder in args.top_folder:
        if _db_inside_top_folder(folder, args.db):
            print(f"Error: database {args.db} is inside folder being scanned: "
                  f"{folder}. Store it outside the scanned tree.")
            sys.exit(1)

    # Determine number of worker processes.
    ncores: int = (
        args.ncores if (args.ncores is not None and args.ncores > 0)
        else (os.cpu_count() or 1)
    )

    with FileDB(args.db) as db:
        if args.validate is not None:
            # Mode 1: Validate existing DB against current filesystem state.
            if not run_validation(db, args.validate, args.report, ncores):
                sys.exit(1)
            print(f"[-] Validation complete. Report written to {args.report}")
        elif args.limit is not None:
            # Mode 2: Sync the provided folders (if any), then run the
            # redundancy check. With no folders the check covers every indexed
            # folder; with folders it is scoped to exactly those.
            all_present = True
            for folder in args.top_folder:
                if not perform_sync(db, folder, ncores, quiet=args.quiet):
                    all_present = False
            if not all_present:
                # A folder we were asked to scope to is missing, so -l would
                # count its stale rows as present copies (false redundancy
                # pass). Refuse and exit non-zero instead.
                print("Error: one or more top folders are missing; skipping the"
                      " limit check (stale rows would give a false redundancy "
                      "pass).")
                sys.exit(1)
            # top_folders for the query must be in the same bytes form as the
            # rows' top_folder column (matching perform_sync's top_bytes).
            scope = (
                [os.fsencode(os.path.realpath(f)) for f in args.top_folder]
                if args.top_folder else None
            )
            run_limit_check(db, args.limit, args.report, scope)
            print(f"[-] Limit check complete. Report written to {args.report}")
        else:
            # Mode 3: Standard synchronization - all provided folders.
            all_present = True
            for folder in args.top_folder:
                if not perform_sync(db, folder, ncores, quiet=args.quiet):
                    all_present = False
                    continue
                print(f"[-] DB sync complete for {folder}")
            # If a top folder was missing (warned + skipped above), signal the
            # partial failure with a non-zero exit code so scripts/automation
            # can tell the run didn't fully succeed -- even though the present
            # folders were still synced.
            if not all_present:
                sys.exit(1)


if __name__ == '__main__':
    main()
