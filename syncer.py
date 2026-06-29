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
ScanRow = Tuple[AbsPath, bytes, int, float]  # (abs_path, filename, sz, mtime)


# ---------------------------------------------------------------------------
# MD5 helpers (same pattern as indexer.py)
# ---------------------------------------------------------------------------

def compute_md5(filepath: AbsPath) -> HashResult:
    """Return the MD5 hex digest of *filepath*, or None on I/O error."""
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
    """Yield (abs_path, md5_or_None) as each worker finishes."""
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
    """Return the edit distance between strings *a* and *b*."""
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
        """Insert *word* into the tree (duplicates are ignored)."""
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
    """Open syncer.db, creating the files table and md5 index if needed."""
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
    row: ScanRow,
    md5: HashResult,
) -> None:
    """Insert or update one (abs_path, filename, size, mtime) row + md5."""
    full_path, filename, filesize, mtime = row
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

def scan_new_folder(top_folder: AbsPath) -> List[ScanRow]:
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

def select_rows_to_hash(
    fs_files: List[ScanRow],
    db_rows: Dict[AbsPath, Tuple[bytes, int, float, HashResult]],
) -> List[ScanRow]:
    """Return scan rows that are new, changed (size/mtime), or unhashed."""
    to_hash: List[ScanRow] = []
    for row in fs_files:
        abs_path, _filename, filesize, mtime = row
        existing = db_rows.get(abs_path)
        if existing is None:
            to_hash.append(row)
        elif existing[2] != mtime or existing[1] != filesize \
                or existing[3] is None:
            to_hash.append(row)
    return to_hash


def delete_stale_rows(
    conn: sqlite3.Connection,
    fs_files: List[ScanRow],
    db_rows: Dict[AbsPath, Tuple[bytes, int, float, HashResult]],
) -> None:
    """Drop syncer.db rows whose files no longer exist on disk."""
    fs_paths: Set[AbsPath] = {row[0] for row in fs_files}
    deleted = [p for p in db_rows if p not in fs_paths]
    if deleted:
        conn.executemany('DELETE FROM files WHERE full_path = ?',
                         [(p,) for p in deleted])
        conn.commit()
        print(f"[-] Removed {len(deleted)} stale entries from syncer.db")


def update_syncer_db(
    conn: sqlite3.Connection,
    top_folder: AbsPath,
    ncores: int,
) -> None:
    """Idempotently refresh syncer.db: hash new/changed files, drop stale."""
    fs_files = scan_new_folder(top_folder)
    db_rows = load_syncer_db(conn)

    to_hash = select_rows_to_hash(fs_files, db_rows)
    delete_stale_rows(conn, fs_files, db_rows)

    if not to_hash:
        print("[-] syncer.db is already up to date")
        return

    by_path: Dict[AbsPath, ScanRow] = {row[0]: row for row in to_hash}
    total = len(by_path)
    count = 0
    for abs_path, md5 in stream_md5s(list(by_path), ncores):
        count += 1
        if md5 is None:
            print(f"[!] Could not read: {abs_path.decode('utf-8', 'replace')}")
        else:
            print(f"[-] {count}/{total} "
                  f"{abs_path.decode('utf-8', 'replace')}")
        upsert_syncer(conn, by_path[abs_path], md5)
        conn.commit()

    print(f"[-] syncer.db updated: {count} files hashed")


# ---------------------------------------------------------------------------
# Phase 2: cross-reference against indexer.db
# ---------------------------------------------------------------------------

OldRow = Tuple[bytes, bytes, bytes, int, HashResult]
NewRow = Tuple[AbsPath, bytes, int, str]


def to_str(data: object) -> str:
    """Decode bytes to a printable str; pass through anything already str."""
    if isinstance(data, bytes):
        return data.decode('utf-8', 'replace')
    return str(data)


def load_indexer_db(indexer_db_path: str) -> List[OldRow]:
    """Return list of (top_folder, full_path, filename, filesize, md5)."""
    conn = sqlite3.connect(f"file:{indexer_db_path}?mode=ro", uri=True)
    try:
        cursor = conn.execute(
            'SELECT top_folder, full_path, filename, filesize, md5 FROM files'
        )
        return list(cursor)
    finally:
        conn.close()


def load_new_files(conn: sqlite3.Connection) -> List[NewRow]:
    """Return new-folder rows with a non-NULL md5 from syncer.db."""
    cursor = conn.execute(
        'SELECT full_path, filename, filesize, md5 FROM files '
        'WHERE md5 IS NOT NULL'
    )
    return list(cursor)


def write_already_existing(
    new_files: List[NewRow],
    old_rows: List[OldRow],
    already_existing_path: str,
) -> Set[AbsPath]:
    """Write new files whose (filesize, md5) match an indexer.db entry.

    Returns the set of new abs paths that were matched, so the similar
    pass can skip them.
    """
    old_by_size_md5: Dict[Tuple[int, str], Tuple[bytes, bytes]] = {}
    for top_folder, full_path, _filename, filesize, md5 in old_rows:
        if md5 is None:
            continue
        old_by_size_md5.setdefault((filesize, md5), (top_folder, full_path))

    already_existing: Set[AbsPath] = set()
    with open(already_existing_path, 'w',
              encoding='utf-8', errors='replace') as fout:
        for full_path, _filename, filesize, md5 in new_files:
            match = old_by_size_md5.get((filesize, md5))
            if match is not None:
                already_existing.add(full_path)
                old_abs = os.path.join(to_str(match[0]), to_str(match[1]))
                fout.write(f"{to_str(full_path)}###{old_abs}\n")

    print(f"[-] already_existing.txt: {len(already_existing)} files")
    return already_existing


StemIndex = Dict[str, List[Tuple[bytes, bytes, int]]]


def index_old_by_stem(old_rows: List[OldRow]) -> StemIndex:
    """Map lowercased filename stem -> [(top_folder, full_path, size), ...]."""
    old_by_stem: StemIndex = {}
    for top_folder, full_path, filename, filesize, _md5 in old_rows:
        stem = os.path.splitext(to_str(filename))[0].lower()
        old_by_stem.setdefault(stem, []).append(
            (top_folder, full_path, filesize))
    return old_by_stem


def build_bktree(stems: List[str]) -> BKTree:
    """Build a BK-tree over *stems*."""
    print(f"[-] Building BK-tree over {len(stems)} unique stems ...")
    bk = BKTree()
    for stem in stems:
        bk.add(stem)
    print("[-] BK-tree ready")
    return bk


def similar_lines_for(
    new_row: NewRow,
    bk: BKTree,
    old_by_stem: StemIndex,
    max_distance: int,
) -> List[str]:
    """Return similar.txt lines pairing one new file with close old names."""
    new_abs = to_str(new_row[0])
    filesize = new_row[2]
    new_stem = os.path.splitext(to_str(new_row[1]))[0].lower()
    threshold = max(1, int(len(new_stem) * max_distance / 100))
    lines: List[str] = []
    for matched_stem, _dist in bk.search(new_stem, threshold):
        for old_top, old_rel, old_size in old_by_stem[matched_stem]:
            if max(old_size, filesize) > 10 * max(1, min(old_size, filesize)):
                continue
            old_abs = os.path.join(to_str(old_top), to_str(old_rel))
            lines.append(f"{old_abs}####{new_abs}####{old_size}:{filesize}\n")
    return lines


def write_similar(
    new_files: List[NewRow],
    old_rows: List[OldRow],
    already_existing: Set[AbsPath],
    similar_path: str,
    max_distance: int,
) -> None:
    """Write Levenshtein-close filename pairs not already matched by md5."""
    old_by_stem = index_old_by_stem(old_rows)
    bk = build_bktree(list(old_by_stem))

    similar_count = 0
    with open(similar_path, 'w', encoding='utf-8', errors='replace') as fout:
        for new_row in new_files:
            if new_row[0] in already_existing:
                continue
            for line in similar_lines_for(
                    new_row, bk, old_by_stem, max_distance):
                fout.write(line)
                similar_count += 1

    print(f"[-] similar.txt: {similar_count} candidate pairs")


def cross_reference(
    conn: sqlite3.Connection,
    indexer_db_path: str,
    already_existing_path: str,
    similar_path: str,
    max_distance: int,
) -> None:
    """Cross-reference syncer.db against indexer.db into the two reports."""
    new_files = load_new_files(conn)
    print(f"[-] Loaded {len(new_files)} new-folder entries from syncer.db")

    print(f"[-] Loading indexer.db from {indexer_db_path} ...")
    old_rows = load_indexer_db(indexer_db_path)
    print(f"[-] Loaded {len(old_rows)} entries from indexer.db")

    already_existing = write_already_existing(
        new_files, old_rows, already_existing_path)
    write_similar(
        new_files, old_rows, already_existing, similar_path, max_distance)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command line arguments for the syncer."""
    parser = argparse.ArgumentParser(
        description='Sync new folder MD5s and cross-reference indexer.db'
    )
    parser.add_argument('new_folder', help='New folder to scan')
    parser.add_argument(
        'indexer_db', help='Path to existing indexer.db (files.db)')
    parser.add_argument(
        '--syncer-db', default='syncer.db',
        help='Path to syncer.db (default: syncer.db in current folder)',
    )
    parser.add_argument(
        '--already-existing', default='already_existing.txt',
        help='Output for already-existing files (default: %(default)s)',
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
        help='Max Levenshtein distance as %% of stem length (default: 20)',
    )
    parser.add_argument(
        '--skip-scan', action='store_true',
        help='Skip MD5 scan phase, go straight to cross-reference',
    )
    return parser.parse_args()


def main() -> None:
    """Entry point: run Phase 1 (scan) then Phase 2 (cross-reference)."""
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
            args.already_existing,
            args.similar,
            args.max_distance,
        )
    finally:
        conn.close()

    print(f"[-] Done. Results in {args.already_existing} and {args.similar}")


if __name__ == '__main__':
    main()
