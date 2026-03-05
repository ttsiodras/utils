#!/usr/bin/env python3
"""
File Scanner Script - Scans folders, tracks files in SQLite, supports parallel MD5 computation,
duplicate-copy limits, and validation reporting.
"""

import argparse
import hashlib
import os
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


def compute_md5(filepath: bytes) -> str:
    """Compute MD5 hash of a file, reading in chunks."""
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (IOError, OSError):
        return ""


def compute_md5_wrapper(args):
    """Wrapper for multiprocessing."""
    filepath_bytes, _ = args
    return compute_md5(filepath_bytes)


def get_file_stat(filepath: bytes):
    """Get mtime and filesize for a file path."""
    try:
        stat = os.stat(filepath)
        return stat.st_mtime, stat.st_size
    except (IOError, OSError):
        return None, None


def scan_folder(top_folder: str):
    """
    Recursively scan a folder and yield file metadata.
    Returns a list of dicts with: filename, full_path (relative to top_folder), top_folder, mtime, filesize.
    All paths are stored as bytes to handle non-UTF8 filenames.
    """
    results = []
    top_normalized = os.path.normpath(top_folder)
    top_bytes = top_normalized.encode(errors='surrogateescape')

    # Use os.walk to traverse the directory tree
    for dirpath, dirnames, filenames in os.walk(top_folder, followlinks=False):
        for filename in filenames:
            full_path_abs = os.path.join(dirpath, filename)
            # Compute relative path from top_folder
            rel_path = os.path.relpath(full_path_abs, top_normalized)
            try:
                stat = os.stat(full_path_abs)
                mtime = stat.st_mtime
                filesize = stat.st_size
            except (IOError, OSError):
                continue

            # Convert to bytes if needed, handling non-UTF8 filenames
            if isinstance(filename, str):
                filename_bytes = filename.encode(errors='surrogateescape')
            else:
                filename_bytes = filename

            if isinstance(rel_path, str):
                rel_path_bytes = rel_path.encode(errors='surrogateescape')
            else:
                rel_path_bytes = rel_path

            results.append({
                'filename': filename_bytes,
                'full_path': rel_path_bytes,
                'top_folder': top_bytes,
                'mtime': mtime,
                'filesize': filesize,
            })

    return results


class FileDB:
    """Handles SQLite database operations for file tracking."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.ensure_table()

    def ensure_table(self):
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

    def load_all(self) -> dict:
        """Load all rows from the database, keyed by (top_folder, full_path)."""
        cursor = self.conn.execute(
            'SELECT filename, full_path, top_folder, mtime, md5, filesize FROM files'
        )
        result = {}
        for row in cursor:
            filename, full_path, top_folder, mtime, md5, filesize = row
            key = (top_folder, full_path)
            result[key] = {
                'filename': filename,
                'full_path': full_path,
                'top_folder': top_folder,
                'mtime': mtime,
                'md5': md5,
                'filesize': filesize,
            }
        return result

    def insert_rows(self, rows: list):
        """Insert multiple rows into the database."""
        for row in rows:
            self.conn.execute(
                '''INSERT INTO files (filename, full_path, top_folder, mtime, md5, filesize)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(top_folder, full_path) DO UPDATE SET
                       filename=excluded.filename,
                       top_folder=excluded.top_folder,
                       mtime=excluded.mtime,
                       md5=excluded.md5,
                       filesize=excluded.filesize''',
                (row['filename'], row['full_path'], row['top_folder'],
                 row['mtime'], row.get('md5'), row['filesize'])
            )
        self.conn.commit()

    def update_rows(self, rows: list):
        """Update multiple rows in the database."""
        for row in rows:
            self.conn.execute(
                '''UPDATE files SET filename=?, mtime=?, md5=?, filesize=?
                   WHERE top_folder=? AND full_path=?''',
                (row['filename'], row['mtime'],
                 row.get('md5'), row['filesize'], row['top_folder'], row['full_path'])
            )
        self.conn.commit()

    def delete_paths(self, paths: list):
        """Delete rows by (top_folder, full_path) tuples."""
        for top_folder, full_path in paths:
            self.conn.execute('DELETE FROM files WHERE top_folder = ? AND full_path = ?', (top_folder, full_path))
        self.conn.commit()

    def query_limit(self, limit: int) -> list:
        """
        Find (full_path, md5) pairs that appear in fewer than `limit` distinct top_folders.
        Returns list of (full_path, md5, copy_count).
        """
        cursor = self.conn.execute('''
            SELECT full_path, md5, COUNT(DISTINCT top_folder) AS copies
            FROM files
            GROUP BY full_path, md5
            HAVING copies < ?
        ''', (limit,))
        return cursor.fetchall()

    def get_rows_for_validation(self, top_folder: str = None) -> list:
        """Get rows to validate, optionally filtered by top_folder."""
        if top_folder is None:
            cursor = self.conn.execute(
                'SELECT filename, full_path, top_folder, mtime, md5, filesize FROM files'
            )
        elif top_folder == 'all':
            cursor = self.conn.execute(
                'SELECT filename, full_path, top_folder, mtime, md5, filesize FROM files'
            )
        else:
            top_normalized = os.path.normpath(top_folder)
            top_bytes = top_normalized.encode(errors='surrogateescape')
            cursor = self.conn.execute(
                'SELECT filename, full_path, top_folder, mtime, md5, filesize FROM files WHERE top_folder = ?',
                (top_bytes,)
            )
        return cursor.fetchall()

    def close(self):
        self.conn.close()


def to_printable(data: bytes) -> str:
    """Convert bytes to a printable string, replacing non-printable chars."""
    if isinstance(data, str):
        return data
    return data.decode(errors='surrogateescape')


def perform_sync(db: FileDB, top_folder: str, ncores: int):
    """
    Perform synchronization between filesystem and database.
    - Insert new files
    - Update changed files (mtime or filesize changed)
    - Delete missing files
    """
    top_normalized = os.path.normpath(top_folder)
    top_bytes = top_normalized.encode(errors='surrogateescape')

    # Load existing DB data
    db_data = db.load_all()

    # Scan filesystem
    fs_data = scan_folder(top_folder)
    fs_paths = {item['full_path']: item for item in fs_data}

    to_insert = []
    to_update = []
    to_delete = []

    # Find new and changed files
    for item in fs_data:
        full_path = item['full_path']
        key = (top_bytes, full_path)
        if key not in db_data:
            to_insert.append(item)
        else:
            db_row = db_data[key]
            if db_row['mtime'] != item['mtime'] or db_row['filesize'] != item['filesize']:
                to_update.append(item)

    # Find deleted files - only for this top_folder
    for (tf, full_path) in db_data:
        if tf == top_bytes and full_path not in fs_paths:
            to_delete.append((tf, full_path))

    # Compute MD5s for inserts - need absolute paths
    if to_insert:
        # Build absolute paths for MD5 computation, keyed by relative path
        paths_to_hash = []
        abs_to_rel = {}
        for item in to_insert:
            rel_path_bytes = item['full_path']
            rel_path_str = to_printable(rel_path_bytes)
            abs_path = os.path.join(top_normalized, rel_path_str)
            abs_path_bytes = abs_path.encode(errors='surrogateescape')
            paths_to_hash.append((abs_path_bytes, None))
            abs_to_rel[abs_path_bytes] = rel_path_bytes
        md5s_abs = compute_md5_parallel(paths_to_hash, ncores)
        # Map back to relative paths and print progress
        for item in to_insert:
            rel_key = item['full_path']
            # Find the absolute path that maps to this relative path
            abs_key = None
            for ak, rv in abs_to_rel.items():
                if rv == rel_key:
                    abs_key = ak
                    break
            item['md5'] = md5s_abs.get(abs_key, '') if abs_key else ''
            print(f"[-] Computed MD5 for {to_printable(rel_key)}")
        db.insert_rows(to_insert)

    # Compute MD5s for updates - need absolute paths
    if to_update:
        paths_to_hash = []
        abs_to_rel = {}
        for item in to_update:
            rel_path_bytes = item['full_path']
            rel_path_str = to_printable(rel_path_bytes)
            abs_path = os.path.join(top_normalized, rel_path_str)
            abs_path_bytes = abs_path.encode(errors='surrogateescape')
            paths_to_hash.append((abs_path_bytes, None))
            abs_to_rel[abs_path_bytes] = rel_path_bytes
        md5s_abs = compute_md5_parallel(paths_to_hash, ncores)
        for item in to_update:
            rel_key = item['full_path']
            abs_key = None
            for ak, rv in abs_to_rel.items():
                if rv == rel_key:
                    abs_key = ak
                    break
            item['md5'] = md5s_abs.get(abs_key, '') if abs_key else ''
            print(f"[-] Computed MD5 for {to_printable(rel_key)}")
        db.update_rows(to_update)

    # Delete missing files
    if to_delete:
        for top_folder_bytes, full_path_bytes in to_delete:
            print(f"[-] Deleted (missing): {to_printable(full_path_bytes)}")
        db.delete_paths(to_delete)

    # Print summary
    print(f"[-] Sync complete: {len(to_insert)} inserted, {len(to_update)} updated, {len(to_delete)} deleted")


def compute_md5_parallel(paths_with_dummy: list, ncores: int) -> dict:
    """
    Compute MD5 hashes for multiple files in parallel.
    Args: list of (filepath_bytes, dummy) tuples.
    Returns: dict mapping filepath_bytes -> md5 string.
    """
    if not paths_with_dummy:
        return {}

    with ProcessPoolExecutor(max_workers=ncores) as executor:
        results = list(executor.map(compute_md5_wrapper, paths_with_dummy))

    return {path: md5 for (path, _), md5 in zip(paths_with_dummy, results)}


def run_limit_check(db: FileDB, limit: int, report_path: str):
    """
    Run the limit check and write results to report.log.
    Each line: <full_path>#@#<existing_copy_count>
    """
    results = db.query_limit(limit)

    with open(report_path, 'w', encoding='utf-8', errors='surrogateescape') as f:
        for full_path, md5, copies in results:
            path_str = to_printable(full_path)
            f.write(f"{path_str}#@#{copies}\n")


def run_validation(db: FileDB, target: str, report_path: str, ncores: int):
    """
    Validate DB rows against filesystem.
    Generate report.log with MATCH, MISMATCH, MISSING, NEW sections.
    """
    rows = db.get_rows_for_validation(target)

    # Build set of DB paths keyed by (top_folder, full_path) with expected MD5s
    db_data = {}
    for row in rows:
        filename, full_path, top_folder, mtime, expected_md5, filesize = row
        key = (top_folder, full_path)
        db_data[key] = expected_md5

    # Scan filesystem for the target folder(s)
    if target == 'all':
        # Scan all folders - get unique top_folders from DB rows
        top_folders = set(row[2] for row in rows)
        fs_data = []
        for tf in top_folders:
            fs_data.extend(scan_folder(to_printable(tf)))
    else:
        fs_data = scan_folder(target)

    # Build filesystem lookup by (top_folder, full_path)
    fs_data_lookup = {}
    for item in fs_data:
        key = (item['top_folder'], item['full_path'])
        fs_data_lookup[key] = item

    # Compute MD5s for existing files in parallel - need absolute paths
    paths_to_hash = []
    rel_path_mapping = {}  # abs_path_bytes -> rel_path_bytes
    for item in fs_data:
        key = (item['top_folder'], item['full_path'])
        if key in db_data:
            top_folder_bytes = item['top_folder']
            rel_path_bytes = item['full_path']
            top_folder_str = to_printable(top_folder_bytes)
            rel_path_str = to_printable(rel_path_bytes)
            abs_path = os.path.join(top_folder_str, rel_path_str)
            abs_path_bytes = abs_path.encode(errors='surrogateescape')
            paths_to_hash.append((abs_path_bytes, None))
            rel_path_mapping[abs_path_bytes] = rel_path_bytes

    computed_md5s_abs = compute_md5_parallel(paths_to_hash, ncores)
    # Convert to relative path keys
    computed_md5s = {rel_path_mapping[abs_key]: md5 for abs_key, md5 in computed_md5s_abs.items()}

    match = []
    mismatch = []
    missing = []
    new_files = []

    # Check DB rows
    for key, expected_md5 in db_data.items():
        top_folder, full_path = key
        if key not in fs_data_lookup:
            missing.append((top_folder, full_path, expected_md5))
        else:
            actual_md5 = computed_md5s.get(full_path, '')
            if actual_md5 == expected_md5:
                match.append((top_folder, full_path, expected_md5))
            else:
                mismatch.append((top_folder, full_path, expected_md5, actual_md5))

    # Find new files (in FS but not in DB)
    for key in fs_data_lookup:
        if key not in db_data:
            top_folder, full_path = key
            new_files.append((top_folder, full_path))

    # Write report
    with open(report_path, 'w', encoding='utf-8', errors='surrogateescape') as f:
        f.write("=== MATCH ===\n")
        for top_folder, path, md5 in match:
            f.write(f"MATCH: {to_printable(top_folder)}/{to_printable(path)} (md5={md5})\n")

        f.write("\n=== MISMATCH ===\n")
        for top_folder, path, expected, actual in mismatch:
            f.write(f"MISMATCH: {to_printable(top_folder)}/{to_printable(path)} (expected={expected}, actual={actual})\n")

        f.write("\n=== MISSING ===\n")
        for top_folder, path, expected in missing:
            f.write(f"MISSING: {to_printable(top_folder)}/{to_printable(path)} (expected_md5={expected})\n")

        f.write("\n=== NEW ===\n")
        for top_folder, path in new_files:
            f.write(f"NEW: {to_printable(top_folder)}/{to_printable(path)}\n")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='File scanner with SQLite tracking, parallel MD5, and validation.'
    )
    parser.add_argument('top_folder', nargs='?', help='Top folder to scan')
    parser.add_argument('-n', '--ncores', type=int, default=None,
                        help='Number of cores for parallel MD5 computation (default: all available)')
    parser.add_argument('-l', '--limit', type=int, default=None,
                        help='Check that each (full_path, md5) appears in at least N distinct top_folders')
    parser.add_argument('-v', '--validate', nargs='?', const='all', default=None,
                        help='Validate DB rows against filesystem. Optional arg: top_folder or "all"')
    parser.add_argument('--db', type=str, default='files.db',
                        help='Path to SQLite database (default: files.db in current directory)')
    parser.add_argument('--report', type=str, default='report.log',
                        help='Path to report file (default: report.log in current directory)')

    return parser, parser.parse_args()


def main():
    parser, args = parse_args()

    # Determine number of cores
    if args.ncores is not None and args.ncores > 0:
        ncores = args.ncores
    else:
        ncores = os.cpu_count() or 1

    # Create/open database
    db = FileDB(args.db)

    try:
        if args.validate is not None:
            # Validation mode
            run_validation(db, args.validate, args.report, ncores)
            print(f"[-] Validation complete. Report written to {args.report}")
        elif args.limit is not None:
            # If top_folder provided, perform sync first
            if args.top_folder:
                perform_sync(db, args.top_folder, ncores)
            # Then run limit check
            run_limit_check(db, args.limit, args.report)
            print(f"[-] Limit check complete. Report written to {args.report}")
        elif args.top_folder:
            # Normal sync mode
            perform_sync(db, args.top_folder, ncores)
            print(f"[-] DB sync complete for {args.top_folder}")
        else:
            parser.print_help()
            sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()
