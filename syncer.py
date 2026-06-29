#!/usr/bin/env python3
"""
Syncer - Scans a new folder, stores MD5s in syncer.db, then cross-references
against an existing indexer.db to find:
  1. Files already present (same size + MD5) → already_existing.txt
  2. Files with similar filenames (Levenshtein) but not identical → similar.txt

Usage:
    syncer.py <new_folder> <indexer_db> [options]
"""
import argparse
import os
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, Generator, List, Optional, Set, Tuple
import hashlib

AbsPath = bytes
HashResult = Optional[str]


# ---------------------------------------------------------------------------
# MD5 helpers (same pattern as indexer.py)
# ---------------------------------------------------------------------------

def compute_md5(filepath: AbsPath) -> HashResult:
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
    if not paths:
        return
    with ProcessPoolExecutor(max_workers=ncores) as executor:
        future_to_path = {executor.submit(compute_md5, p): p for p in paths}
        for future in as_completed(future_to_path):
            yield future_to_path[future], future.result()


# ---------------------------------------------------------------------------
# Levenshtein + BK-tree for fast fuzzy index
# ---------------------------------------------------------------------------

def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1,
                            prev[j - 1] + (0 if ca == cb else 1)))
        prev = curr
    return prev[len(b)]


class BKTree:
    """BK-tree for fast bounded Levenshtein search.

    Build once over a corpus; query with a threshold to get all words
    within that edit distance. Typical query touches O(log N) nodes
    instead of O(N), thanks to the triangle inequality.
    """

    def __init__(self) -> None:
        # Each node: (word, {distance: child_index})
        self._words: List[str] = []
        self._children: List[Dict[int, int]] = []

    def add(self, word: str) -> None:
        if not self._words:
            self._words.append(word)
            self._children.append({})
            return
        idx = 0
        while True:
            d = levenshtein(word, self._words[idx])
            if d == 0:
                return  # duplicate
            if d not in self._children[idx]:
                new_idx = len(self._words)
                self._words.append(word)
                self._children.append({})
                self._children[idx][d] = new_idx
                return
            idx = self._children[idx][d]

    def search(self, word: str, threshold: int) -> List[Tuple[str, int]]:
        """Return [(matched_word, distance), ...] for dist <= threshold."""
        results: List[Tuple[str, int]] = []
        stack = [0]
        while stack:
            idx = stack.pop()
            d = levenshtein(word, self._words[idx])
            if d <= threshold:
                results.append((self._words[idx], d))
            lo, hi = d - threshold, d + threshold
            for edge_d, child_idx in self._children[idx].items():
                if lo <= edge_d <= hi:
                    stack.append(child_idx)
        return results


# ---------------------------------------------------------------------------
# syncer.db management
# ---------------------------------------------------------------------------

def open_syncer_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute('''
        CREATE TABLE IF NOT EXISTS files (
            full_path BLOB NOT NULL PRIMARY KEY,
            filename  BLOB NOT NULL,
            filesize  INTEGER NOT NULL,
            mtime     REAL NOT NULL,
            md5       TEXT
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_md5 ON files(md5)')
    conn.commit()
    return conn


def load_syncer_db(
    conn: sqlite3.Connection,
) -> Dict[AbsPath, Tuple[bytes, int, float, HashResult]]:
    """Return {full_path: (filename, filesize, mtime, md5)}."""
    cursor = conn.execute(
        'SELECT full_path, filename, filesize, mtime, md5 FROM files'
    )
    return {
        row[0]: (row[1], row[2], row[3], row[4])
        for row in cursor
    }


def upsert_syncer(
    conn: sqlite3.Connection,
    full_path: AbsPath,
    filename: bytes,
    filesize: int,
    mtime: float,
    md5: HashResult,
) -> None:
    conn.execute(
        '''INSERT INTO files (full_path, filename, filesize, mtime, md5)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(full_path) DO UPDATE SET
               filename=excluded.filename,
               filesize=excluded.filesize,
               mtime=excluded.mtime,
               md5=excluded.md5''',
        (full_path, filename, filesize, mtime, md5),
    )


# ---------------------------------------------------------------------------
# Scan new folder
# ---------------------------------------------------------------------------

def scan_new_folder(
    top_folder: AbsPath,
) -> List[Tuple[AbsPath, bytes, int, float]]:
    """Return list of (abs_path, filename, filesize, mtime)."""
    results = []
    count = 0
    for dirpath, _, filenames in os.walk(top_folder, followlinks=False):
        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            if os.path.islink(abs_path):
                continue
            try:
                st = os.stat(abs_path)
            except OSError:
                continue
            results.append((abs_path, filename, st.st_size, st.st_mtime))
            count += 1
            if count % 1000 == 0:
                print(f"\r[.] Scanning: {count} files...", end="", flush=True)
    print(f"\r[.] Scanning: {count} files total", flush=True)
    return results


# ---------------------------------------------------------------------------
# Phase 1: idempotent MD5 update of syncer.db
# ---------------------------------------------------------------------------

def update_syncer_db(
    conn: sqlite3.Connection,
    top_folder: AbsPath,
    ncores: int,
) -> None:
    fs_files = scan_new_folder(top_folder)
    db_rows = load_syncer_db(conn)

    to_hash: List[Tuple[AbsPath, bytes, int, float]] = []
    for abs_path, filename, filesize, mtime in fs_files:
        existing = db_rows.get(abs_path)
        if existing is None:
            to_hash.append((abs_path, filename, filesize, mtime))
        else:
            _fn, _sz, db_mtime, db_md5 = existing
            if db_mtime != mtime or filesize != _sz or db_md5 is None:
                to_hash.append((abs_path, filename, filesize, mtime))

    # Remove DB rows for files no longer on disk
    fs_paths: Set[AbsPath] = {r[0] for r in fs_files}
    deleted = [p for p in db_rows if p not in fs_paths]
    if deleted:
        conn.executemany('DELETE FROM files WHERE full_path = ?',
                         [(p,) for p in deleted])
        conn.commit()
        print(f"[-] Removed {len(deleted)} stale entries from syncer.db")

    if not to_hash:
        print("[-] syncer.db is already up to date")
        return

    path_meta: Dict[AbsPath, Tuple[bytes, int, float]] = {
        r[0]: (r[1], r[2], r[3]) for r in to_hash
    }
    total = len(path_meta)
    count = 0
    for abs_path, md5 in stream_md5s(list(path_meta), ncores):
        count += 1
        filename, filesize, mtime = path_meta[abs_path]
        if md5 is None:
            print(f"[!] Could not read: {abs_path.decode('utf-8', 'replace')}")
        else:
            print(f"[-] {count}/{total} "
                  f"{abs_path.decode('utf-8', 'replace')}")
        upsert_syncer(conn, abs_path, filename, filesize, mtime, md5)
        conn.commit()

    print(f"[-] syncer.db updated: {count} files hashed")


# ---------------------------------------------------------------------------
# Phase 2: cross-reference against indexer.db
# ---------------------------------------------------------------------------

def load_indexer_db(
    indexer_db_path: str,
) -> List[Tuple[bytes, bytes, bytes, int, HashResult]]:
    """Return list of (top_folder, full_path, filename, filesize, md5)."""
    conn = sqlite3.connect(f"file:{indexer_db_path}?mode=ro", uri=True)
    try:
        cursor = conn.execute(
            'SELECT top_folder, full_path, filename, filesize, md5 FROM files'
        )
        return list(cursor)
    finally:
        conn.close()


def cross_reference(
    conn: sqlite3.Connection,
    indexer_db_path: str,
    new_top_folder: AbsPath,
    already_existing_path: str,
    similar_path: str,
    max_distance: int,
) -> None:
    # Load syncer.db entries (new folder)
    cursor = conn.execute(
        'SELECT full_path, filename, filesize, md5 FROM files WHERE md5 IS NOT NULL'
    )
    new_files: List[Tuple[AbsPath, bytes, int, str]] = list(cursor)

    # Build lookup: (filesize, md5) -> list of new file abs_paths
    new_by_size_md5: Dict[Tuple[int, str], List[AbsPath]] = {}
    for full_path, filename, filesize, md5 in new_files:
        key = (filesize, md5)
        new_by_size_md5.setdefault(key, []).append(full_path)

    print(f"[-] Loaded {len(new_files)} new-folder entries from syncer.db")

    # Load indexer.db
    print(f"[-] Loading indexer.db from {indexer_db_path} ...")
    old_rows = load_indexer_db(indexer_db_path)
    print(f"[-] Loaded {len(old_rows)} entries from indexer.db")

    # Build lookup: (filesize, md5) -> list of old (top_folder, full_path)
    old_by_size_md5: Dict[Tuple[int, str], List[Tuple[bytes, bytes]]] = {}
    for top_folder, full_path, filename, filesize, md5 in old_rows:
        if md5 is None:
            continue
        key = (filesize, md5)
        old_by_size_md5.setdefault(key, []).append((top_folder, full_path))

    # --- already_existing: new files whose (size, md5) appear in indexer.db ---
    already_existing: Set[AbsPath] = set()
    with open(already_existing_path, 'w', encoding='utf-8', errors='replace') as fout:
        for full_path, filename, filesize, md5 in new_files:
            key = (filesize, md5)
            if key in old_by_size_md5:
                already_existing.add(full_path)
                old_top, old_rel = old_by_size_md5[key][0]
                old_top_s = old_top.decode('utf-8', 'replace') if isinstance(old_top, bytes) else old_top
                old_rel_s = old_rel.decode('utf-8', 'replace') if isinstance(old_rel, bytes) else old_rel
                old_abs = os.path.join(old_top_s, old_rel_s)
                fout.write(f"{full_path.decode('utf-8', 'replace')}###{old_abs}\n")

    print(f"[-] already_existing.txt: {len(already_existing)} files")

    # --- similar: Levenshtein-close filenames, not already existing ---
    # Build old filename stem -> list of (top_folder, full_path, filesize, original_fname)
    old_by_stem: Dict[str, List[Tuple[bytes, bytes, int, str]]] = {}
    for top_folder, full_path, filename, filesize, md5 in old_rows:
        fname_str = filename.decode('utf-8', 'replace') if isinstance(filename, bytes) else filename
        stem = os.path.splitext(fname_str)[0].lower()
        old_by_stem.setdefault(stem, []).append((top_folder, full_path, filesize, fname_str))

    # Build BK-tree over lowercased stems (built once, queried per new file)
    print(f"[-] Building BK-tree over {len(old_by_stem)} unique stems ...")
    bk: BKTree = BKTree()
    for stem in old_by_stem:
        bk.add(stem)
    print("[-] BK-tree ready")

    similar_count = 0
    with open(similar_path, 'w', encoding='utf-8', errors='replace') as fout:
        for full_path, filename, filesize, md5 in new_files:
            if full_path in already_existing:
                continue
            new_fname = filename.decode('utf-8', 'replace') if isinstance(filename, bytes) else filename
            new_stem = os.path.splitext(new_fname)[0].lower()
            threshold = max(1, int(len(new_stem) * max_distance / 100))
            new_abs = full_path.decode('utf-8', 'replace')
            for matched_stem, _dist in bk.search(new_stem, threshold):
                for old_top, old_rel, old_size, _orig in old_by_stem[matched_stem]:
                    old_top_s = old_top.decode('utf-8', 'replace') if isinstance(old_top, bytes) else old_top
                    old_rel_s = old_rel.decode('utf-8', 'replace') if isinstance(old_rel, bytes) else old_rel
                    old_abs = os.path.join(old_top_s, old_rel_s)
                    if max(old_size, filesize) <= 10 * max(1, min(old_size, filesize)):
                        fout.write(f"{old_abs}####{new_abs}####{old_size}:{filesize}\n")
                        similar_count += 1

    print(f"[-] similar.txt: {similar_count} candidate pairs")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Sync new folder MD5s and cross-reference against indexer.db'
    )
    parser.add_argument('new_folder', help='New folder to scan')
    parser.add_argument('indexer_db', help='Path to existing indexer.db (files.db)')
    parser.add_argument(
        '--syncer-db', default='syncer.db',
        help='Path to syncer.db (default: syncer.db in current folder)',
    )
    parser.add_argument(
        '--already-existing', default='already_existing.txt',
        help='Output file for already-existing files (default: already_existing.txt)',
    )
    parser.add_argument(
        '--similar', default='similar.txt',
        help='Output file for similar-filename pairs (default: similar.txt)',
    )
    parser.add_argument(
        '-n', '--ncores', type=int, default=None,
        help='Number of cores for parallel MD5 (default: all)',
    )
    parser.add_argument(
        '-d', '--max-distance', type=int, default=20,
        help='Max Levenshtein distance as %% of filename stem length (default: 20)',
    )
    parser.add_argument(
        '--skip-scan', action='store_true',
        help='Skip MD5 scan phase, go straight to cross-reference',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ncores = args.ncores if (args.ncores is not None and args.ncores > 0) \
        else (os.cpu_count() or 1)

    new_top = os.fsencode(os.path.realpath(os.path.normpath(args.new_folder)))
    if not os.path.isdir(new_top):
        print(f"[!] Not a directory: {args.new_folder}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(args.indexer_db):
        print(f"[!] indexer.db not found: {args.indexer_db}", file=sys.stderr)
        sys.exit(1)

    conn = open_syncer_db(args.syncer_db)
    try:
        if not args.skip_scan:
            print(f"[=] Phase 1: updating syncer.db for {args.new_folder}")
            update_syncer_db(conn, new_top, ncores)

        print(f"[=] Phase 2: cross-referencing against {args.indexer_db}")
        cross_reference(
            conn,
            args.indexer_db,
            new_top,
            args.already_existing,
            args.similar,
            args.max_distance,
        )
    finally:
        conn.close()

    print(f"[-] Done. Results in {args.already_existing} and {args.similar}")


if __name__ == '__main__':
    main()
