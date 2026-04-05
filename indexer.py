#!/usr/bin/env python3
"""
File Scanner Script - Scans folders, tracks files in SQLite, supports
parallel MD5 computation, duplicate-copy limits, and validation reporting.

Vibe-coded; standalone repo with prompts and test suite at:

    https://github.com/ttsiodras/FileIndexer

"""
import argparse
import hashlib
import os
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, Generator, List, NamedTuple, Optional, Set, Tuple


# --- Type aliases ---
HashResult = Optional[str]
SafeFilename = bytes  # bare filename, e.g. b"photo.jpg"
SafeRelPath = bytes  # relative path from top_folder, e.g. b"subdir/photo.jpg"
SafeTopFolder = bytes  # absolute path to the root of a scan, e.g. b"/mnt/data"
AbsPath = bytes  # absolute path to a specific file
TopFolderAndFullPath = Tuple[SafeTopFolder, SafeRelPath]


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


def compute_md5(filepath: AbsPath) -> HashResult:
    """Compute MD5 hash of a file, reading in chunks.

    Returns ``None`` on I/O errors so callers can distinguish unreadable
    files from legitimate results (including empty files).
    """
    hasher = hashlib.md5(usedforsecurity=False)
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return None


def stream_md5s(
    paths: List[AbsPath], ncores: int
) -> Generator[Tuple[AbsPath, HashResult], None, None]:
    """Yield ``(abs_path, md5_or_None)`` as each worker finishes.

    Results arrive in completion order, not submission order, so callers
    can act on each hash immediately without waiting for the full batch.
    """
    if not paths:
        return
    with ProcessPoolExecutor(max_workers=ncores) as executor:
        future_to_path = {executor.submit(compute_md5, p): p for p in paths}
        for future in as_completed(future_to_path):
            yield future_to_path[future], future.result()


def scan_folder(top_folder: SafeTopFolder) -> List[FileMetadata]:
    """Recursively scan a folder and return file metadata.

    *top_folder* must be an absolute path as bytes. Returns a list of
    ``FileMetadata`` with filename, full_path (relative to top_folder),
    top_folder, mtime, and filesize.
    """
    results: List[FileMetadata] = []
    for dirpath, _, filenames in os.walk(top_folder, followlinks=False):
        for filename in filenames:
            full_path_abs = os.path.join(dirpath, filename)
            if os.path.islink(full_path_abs):
                continue
            rel_path = os.path.relpath(full_path_abs, top_folder)
            try:
                stat = os.stat(full_path_abs)
                mtime = stat.st_mtime
                filesize = stat.st_size
            except OSError:
                continue
            results.append(FileMetadata(
                filename=filename,
                full_path=rel_path,
                top_folder=top_folder,
                mtime=mtime,
                filesize=filesize,
            ))
    return results


class FileDB:
    """Handles SQLite database operations for file tracking."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_table()

    def __enter__(self) -> "FileDB":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _ensure_table(self) -> None:
        """Create the files table if it doesn't exist."""
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
        self.conn.commit()

    def load_folder(
        self, top_folder_bytes: SafeTopFolder
    ) -> Dict[TopFolderAndFullPath, FileRecord]:
        """Load rows for a single top_folder, keyed by (top_folder, full_path)."""
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
        self.conn.execute(
            '''INSERT INTO files (filename, full_path, top_folder,
               mtime, md5, filesize) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(top_folder, full_path) DO UPDATE SET
                   filename=excluded.filename,
                   top_folder=excluded.top_folder,
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
        """Delete rows by (top_folder, full_path) tuples. Caller must commit."""
        for top_folder, full_path in paths:
            self.conn.execute(
                'DELETE FROM files WHERE top_folder = ? AND full_path = ?',
                (top_folder, full_path))

    def query_limit(self, limit: int) -> List[LimitCheckResult]:
        """Find (full_path, md5) pairs that appear in fewer than ``limit``
        distinct top_folders.
        """
        cursor = self.conn.execute('''
            SELECT full_path, md5, COUNT(DISTINCT top_folder) AS copies
            FROM files
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
    """Convert bytes to a printable string, replacing non-decodable bytes."""
    return data.decode('utf-8', errors='replace')


def sync_files_with_md5(
    db: FileDB,
    files: List[FileMetadata],
    ncores: int,
) -> None:
    """Compute MD5s for *files*, printing and committing each result as it arrives."""
    if not files:
        return
    path_to_item: Dict[AbsPath, FileMetadata] = {
        os.path.join(item.top_folder, item.full_path): item for item in files
    }
    for abs_bytes, md5 in stream_md5s(list(path_to_item), ncores):
        item = path_to_item[abs_bytes]
        if md5 is None:
            print(f"[!] Could not read: {to_printable(abs_bytes)}")
        else:
            print(f"[-] Computed MD5 for {to_printable(abs_bytes)}")
        db.upsert_with_md5(item, md5)
        db.commit()


def find_changes(
    db: FileDB, top_folder_bytes: SafeTopFolder
) -> Tuple[Insertions, Updates, Deletions]:
    """Compare filesystem state with database and return categorised changes."""
    fs_data = scan_folder(top_folder_bytes)
    db_data = db.load_folder(top_folder_bytes)
    fs_paths = {item.full_path for item in fs_data}
    to_insert: Insertions = []
    to_update: Updates = []
    for item in fs_data:
        key = (top_folder_bytes, item.full_path)
        if key not in db_data:
            to_insert.append(item)
        elif db_data[key].mtime != item.mtime or db_data[key].filesize != item.filesize:
            to_update.append(item)
    to_delete: Deletions = [
        (tf, fp) for (tf, fp) in db_data if fp not in fs_paths
    ]
    return to_insert, to_update, to_delete


def perform_sync(db: FileDB, top_folder: str, ncores: int) -> None:
    """Synchronise a folder against the database.

    Inserts new files, updates rows whose mtime or filesize changed,
    and removes rows for files that no longer exist on disk.
    """
    top_bytes: SafeTopFolder = os.path.normpath(top_folder).encode()
    to_insert, to_update, to_delete = find_changes(db, top_bytes)
    sync_files_with_md5(db, to_insert + to_update, ncores)
    if to_delete:
        for _, full_path_bytes in to_delete:
            print(f"[-] Deleted (missing): {to_printable(full_path_bytes)}")
        db.delete_paths(to_delete)
        db.commit()
    print(
        f"[-] Sync complete: {len(to_insert)} inserted, "
        f"{len(to_update)} updated, {len(to_delete)} deleted"
    )


def run_limit_check(db: FileDB, limit: int, report_path: str) -> None:
    """Run the limit check and write results to *report_path*.

    Each line has the form: ``<full_path>#@#<existing_copy_count>``
    """
    results = db.query_limit(limit)
    with open(report_path, 'w', encoding='utf-8', errors='replace') as f:
        for full_path, md5, copies in results:
            path_str = to_printable(full_path)
            f.write(f"{path_str}#@#{copies} {md5}\n")


def scan_target(
    top_folder: Optional[SafeTopFolder], rows: List[FileRecord]
) -> List[FileMetadata]:
    """Scan filesystem for *top_folder* or all top_folders found in *rows*."""
    if top_folder is None:
        top_folders: Set[SafeTopFolder] = {row.top_folder for row in rows}
        return [entry for tf in top_folders for entry in scan_folder(tf)]
    return scan_folder(top_folder)


def compute_md5s_for_matches(
    fs_data: List[FileMetadata],
    db_data: Dict[TopFolderAndFullPath, HashResult],
    ncores: int,
) -> Dict[TopFolderAndFullPath, HashResult]:
    """Compute MD5s (keyed by (top_folder, full_path)) for FS items that exist in DB.

    Streams results as workers finish, printing each one immediately.
    """
    abs_to_key: Dict[AbsPath, TopFolderAndFullPath] = {}
    for item in fs_data:
        if (item.top_folder, item.full_path) not in db_data:
            continue
        abs_bytes: AbsPath = os.path.join(item.top_folder, item.full_path)
        abs_to_key[abs_bytes] = (item.top_folder, item.full_path)
    result: Dict[TopFolderAndFullPath, HashResult] = {}
    for abs_bytes, md5 in stream_md5s(list(abs_to_key), ncores):
        print(f"[-] Computed MD5 for {to_printable(abs_bytes)}")
        result[abs_to_key[abs_bytes]] = md5
    return result


def classify_entries(
    db_data: Dict[TopFolderAndFullPath, HashResult],
    fs_lookup: Dict[TopFolderAndFullPath, FileMetadata],
    computed_md5s: Dict[TopFolderAndFullPath, HashResult],
) -> Tuple[List[MatchEntry], List[MismatchEntry], List[MatchEntry], List[NewEntry]]:
    """Return (match, mismatch, missing, new_files) lists."""
    match: List[MatchEntry] = []
    mismatch: List[MismatchEntry] = []
    missing: List[MatchEntry] = []
    for key, expected_md5 in db_data.items():
        if key not in fs_lookup:
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
    return match, mismatch, missing, new_files


def write_report(
    report_path: str,
    match: List[MatchEntry],
    mismatch: List[MismatchEntry],
    missing: List[MatchEntry],
    new_files: List[NewEntry],
) -> None:
    """Write a categorised validation report, omitting empty sections."""
    with open(report_path, 'w', encoding='utf-8', errors='replace') as f:
        if match:
            f.write("=== MATCH ===\n")
            for tf, p, md5 in match:
                f.write(f"MATCH: {to_printable(tf)}/{to_printable(p)} (md5={md5})\n")
            f.write("\n")
        if mismatch:
            f.write("=== MISMATCH ===\n")
            for tf, p, exp, act in mismatch:
                line = (f"MISMATCH: {to_printable(tf)}/{to_printable(p)} "
                        f"(expected={exp}, actual={act})")
                print(f"[!] {line}")
                f.write(f"{line}\n")
            f.write("\n")
        if missing:
            f.write("=== MISSING ===\n")
            for tf, p, exp in missing:
                line = f"MISSING: {to_printable(tf)}/{to_printable(p)} (expected_md5={exp})"
                print(f"[!] {line}")
                f.write(f"{line}\n")
            f.write("\n")
        if new_files:
            f.write("=== NEW ===\n")
            for tf, p in new_files:
                line = f"NEW: {to_printable(tf)}/{to_printable(p)}"
                print(f"[-] {line}")
                f.write(f"{line}\n")


def run_validation(
    db: FileDB, target: str, report_path: str, ncores: int
) -> None:
    """Validate DB rows against the filesystem.

    Generates a report with MATCH, MISMATCH, MISSING, and NEW sections.
    """
    top_bytes: Optional[SafeTopFolder] = (
        None if target == 'all' else os.path.normpath(target).encode()
    )
    rows = db.get_rows_for_validation(top_bytes)
    db_data: Dict[TopFolderAndFullPath, HashResult] = {
        (row.top_folder, row.full_path): row.md5 for row in rows
    }
    fs_data = scan_target(top_bytes, rows)
    fs_lookup = {(item.top_folder, item.full_path): item for item in fs_data}
    computed_md5s = compute_md5s_for_matches(fs_data, db_data, ncores)
    match, mismatch, missing, new_files = classify_entries(
        db_data, fs_lookup, computed_md5s)
    write_report(report_path, match, mismatch, missing, new_files)


def parse_args() -> argparse.Namespace:
    """Parse and return command line arguments, exiting with help if none given."""
    parser = argparse.ArgumentParser(
        description=(
            'File scanner with SQLite tracking, parallel MD5, and validation.'
        )
    )
    parser.add_argument('top_folder', nargs='*', help='Top folder(s) to scan')
    parser.add_argument(
        '-n', '--ncores', type=int, default=None,
        help='Number of cores for parallel MD5 computation (default: all available)',
    )
    parser.add_argument(
        '-l', '--limit', type=int, default=None,
        help='Check that each (full_path, md5) appears in at least N distinct top_folders',
    )
    parser.add_argument(
        '-v', '--validate', nargs='?', const='all', default=None,
        help='Validate DB rows against filesystem. Optional arg: top_folder or "all"',
    )
    parser.add_argument(
        '--db', type=str, default='files.db',
        help='Path to SQLite database (default: files.db in current directory)',
    )
    parser.add_argument(
        '--report', type=str, default='report.log',
        help='Path to report file (default: report.log in current directory)',
    )
    args = parser.parse_args()
    if args.validate is None and args.limit is None and not args.top_folder:
        parser.print_help()
        sys.exit(1)
    return args


def main() -> None:
    """Entry point: parse arguments and dispatch to the appropriate mode."""
    args = parse_args()
    ncores: int = (
        args.ncores if (args.ncores is not None and args.ncores > 0)
        else (os.cpu_count() or 1)
    )
    with FileDB(args.db) as db:
        if args.validate is not None:
            run_validation(db, args.validate, args.report, ncores)
            print(f"[-] Validation complete. Report written to {args.report}")
        elif args.limit is not None:
            for folder in args.top_folder:
                perform_sync(db, folder, ncores)
            run_limit_check(db, args.limit, args.report)
            print(f"[-] Limit check complete. Report written to {args.report}")
        else:
            perform_sync(db, args.top_folder[0], ncores)
            print(f"[-] DB sync complete for {args.top_folder[0]}")


if __name__ == '__main__':
    main()
