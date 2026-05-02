#!/usr/bin/env python3
"""
imagescan.py — Recursive image scanner with perceptual hashing and similarity viewer.

Usage:
  python imagescan.py scan <folder> [--db PATH] [--ncores N]
      Recursively scan <folder>, compute perceptual hashes, store in SQLite DB.
      Re-runs only process changed/new files and prune deleted ones.
      Any change to the image table automatically invalidates the similarity cache.
      Uses parallel processing for hash computation.

  python imagescan.py dupes [--db PATH] [--threshold N] [--dry-run] [--rescan]
      Find similar images (hamming distance <= threshold, default 10),
      group them into streaks, and open each group in feh for review.
      Results are cached in the DB and reused on subsequent runs unless the
      image data changed or --rescan is given.

Options:
  --db PATH         Path to SQLite database (default: imagescan.db)
  --threshold N     Max hamming distance to consider images similar (default: 10)
  --dry-run         Print groups without launching feh
  --rescan          Ignore cached similarity results and recompute
  --ncores N        Number of CPU cores for parallel hashing (default: all available)
"""

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Missing dependency: pip install Pillow")

try:
    import imagehash
except ImportError:
    sys.exit("Missing dependency: pip install imagehash")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    top_folder  TEXT    NOT NULL,
    filename    TEXT    NOT NULL,
    full_path   TEXT    NOT NULL UNIQUE,
    width       INTEGER,
    height      INTEGER,
    phash       TEXT,
    file_size   INTEGER,
    mtime       REAL
);
CREATE INDEX IF NOT EXISTS idx_phash     ON images (phash);
CREATE INDEX IF NOT EXISTS idx_full_path ON images (full_path);

-- Cached similarity groups.
-- Each row is one group; paths are stored as a JSON array.
-- cache_key is a hash of (sorted phash list + threshold) so it
-- auto-invalidates when images are added/removed/changed.
CREATE TABLE IF NOT EXISTS similarity_cache (
    cache_key   TEXT PRIMARY KEY,
    threshold   INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    groups_json TEXT NOT NULL        -- JSON: [[path, ...], ...]
);
"""

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".tiff", ".tif", ".webp", ".heic", ".heif",
    ".avif", ".ico", ".ppm", ".pgm", ".pbm",
}


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(DDL)
    conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


def fetch_indexed(conn: sqlite3.Connection) -> dict:
    """Return {full_path: row} for every record in the DB."""
    cur = conn.execute("SELECT * FROM images")
    return {row["full_path"]: row for row in cur.fetchall()}


def compute_cache_key(conn: sqlite3.Connection, threshold: int) -> str:
    """
    Stable hash over (sorted list of all phashes in the DB, threshold).
    Changing any image's phash, adding, or removing images changes this key,
    which invalidates the cache automatically.
    """
    rows = conn.execute(
        "SELECT phash FROM images WHERE phash IS NOT NULL ORDER BY phash"
    ).fetchall()
    digest_input = json.dumps([r["phash"] for r in rows] + [threshold])
    return hashlib.sha256(digest_input.encode()).hexdigest()


def load_cache(conn: sqlite3.Connection, cache_key: str) -> list | None:
    """Return cached groups if the key matches, else None."""
    row = conn.execute(
        "SELECT groups_json, computed_at FROM similarity_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if row:
        print(f"Using cached similarity results (computed {row['computed_at']}).")
        return json.loads(row["groups_json"])
    return None


def save_cache(
    conn: sqlite3.Connection,
    cache_key: str,
    threshold: int,
    groups: list,
) -> None:
    """Persist groups to the cache, replacing any previous entry."""
    import datetime
    conn.execute("DELETE FROM similarity_cache WHERE 1")   # only ever keep one entry
    conn.execute(
        """INSERT INTO similarity_cache (cache_key, threshold, computed_at, groups_json)
           VALUES (?, ?, ?, ?)""",
        (
            cache_key,
            threshold,
            datetime.datetime.now().isoformat(timespec="seconds"),
            json.dumps(groups),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Scan mode
# ---------------------------------------------------------------------------

def compute_record(path: Path, top_folder: str) -> dict | None:
    """Open image, compute hash and dimensions. Returns None on failure."""
    try:
        with Image.open(path) as img:
            img.load()
            width, height = img.size
            phash = str(imagehash.phash(img))
    except Exception as exc:
        print(f"  [WARN] Could not process {path}: {exc}", file=sys.stderr)
        return None

    stat = path.stat()
    return {
        "top_folder": top_folder,
        "filename":   path.name,
        "full_path":  str(path.resolve()),
        "width":      width,
        "height":     height,
        "phash":      phash,
        "file_size":  stat.st_size,
        "mtime":      stat.st_mtime,
    }


def compute_record_worker(args):
    """Worker function for parallel processing. Takes (path_str, top_folder, size, mtime) tuple.
    
    Note: size and mtime are passed for compatibility but not used in computation.
    """
    path_str, top_folder = args[0], args[1]
    path = Path(path_str)
    return compute_record(path, top_folder)


def scan(folder: str, db_path: str, ncores: int) -> None:
    root = Path(folder).resolve()
    if not root.is_dir():
        sys.exit(f"Not a directory: {folder}")

    conn = open_db(db_path)
    indexed = fetch_indexed(conn)

    found_paths: set[str] = set()
    inserted = updated = skipped = removed = errors = 0

    # Collect all image paths first
    image_tasks: list[tuple[str, str, int, float]] = []  # [(path_str, top_folder, size, mtime), ...]
    print(f"Scanning {root} ...")

    try:
        from tqdm import tqdm
        # First pass: count files for progress bar
        file_count = sum(
            1 for _ in root.rglob("*")
            if _.is_file() and _.suffix.lower() in IMAGE_EXTENSIONS and not _.is_symlink()
        )
        scan_pbar = tqdm(total=file_count, desc="Collecting", unit="file", leave=False)
    except ImportError:
        scan_pbar = None

    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            abs_path = str(fpath.resolve())
            found_paths.add(abs_path)

            if scan_pbar:
                scan_pbar.update(1)

            try:
                stat = fpath.stat()
            except OSError:
                continue

            # Determine top_folder (immediate child of root that contains this file)
            try:
                rel = fpath.relative_to(root)
                top_folder = rel.parts[0] if len(rel.parts) > 1 else "."
            except ValueError:
                top_folder = "."

            # Check if file is unchanged from indexed version
            existing = indexed.get(abs_path)
            if (
                existing
                and existing["file_size"] == stat.st_size
                and abs(existing["mtime"] - stat.st_mtime) < 0.01
            ):
                skipped += 1
                continue

            image_tasks.append((abs_path, top_folder, stat.st_size, stat.st_mtime))

    if scan_pbar:
        scan_pbar.close()

    # Process images in parallel
    records: dict[str, dict] = {}
    total = len(image_tasks)

    if ncores > 1:
        with ProcessPoolExecutor(max_workers=ncores) as executor:
            futures = [executor.submit(compute_record_worker, task) for task in image_tasks]
            try:
                from tqdm import tqdm
                iterator = tqdm(futures, desc="Hashing images", unit="img", total=total)
            except ImportError:
                iterator = futures
                print(f"Hashing {total} images...")
            
            for future in iterator:
                record = future.result()
                if record:
                    records[record["full_path"]] = record
    else:
        # Sequential processing
        try:
            from tqdm import tqdm
            iterator = tqdm(image_tasks, desc="Hashing images", unit="img", total=total)
        except ImportError:
            iterator = image_tasks
            print(f"Hashing {total} images...")
        
        for task in iterator:
            record = compute_record_worker(task)
            if record:
                records[record["full_path"]] = record

    # Write results to database
    for abs_path in sorted(found_paths):
        existing = indexed.get(abs_path)
        record = records.get(abs_path)

        # If file is already indexed and unchanged (no new record), skip it
        if existing and not record:
            continue

        if not record:
            errors += 1
            continue

        try:
            stat = Path(abs_path).stat()
        except OSError:
            continue

        if existing:
            conn.execute(
                """UPDATE images SET top_folder=:top_folder, filename=:filename,
                   width=:width, height=:height, phash=:phash,
                   file_size=:file_size, mtime=:mtime
                   WHERE full_path=:full_path""",
                record,
            )
            updated += 1
            print(f"  updated  {abs_path}")
        else:
            conn.execute(
                """INSERT INTO images
                   (top_folder, filename, full_path, width, height, phash, file_size, mtime)
                   VALUES (:top_folder, :filename, :full_path, :width, :height, :phash, :file_size, :mtime)""",
                record,
            )
            inserted += 1
            print(f"  inserted {abs_path}")

    # Prune deleted entries that lived under the scanned root
    for abs_path, row in indexed.items():
        if abs_path.startswith(str(root)) and abs_path not in found_paths:
            conn.execute("DELETE FROM images WHERE full_path = ?", (abs_path,))
            removed += 1
            print(f"  removed  {abs_path}")

    conn.commit()

    # Invalidate similarity cache if anything changed
    if inserted or updated or removed:
        conn.execute("DELETE FROM similarity_cache WHERE 1")
        conn.commit()
        print("  (similarity cache invalidated)")

    conn.close()

    print(
        f"\nDone. inserted={inserted} updated={updated} "
        f"skipped={skipped} removed={removed} errors={errors}"
    )


# ---------------------------------------------------------------------------
# Dupes / similarity mode
# ---------------------------------------------------------------------------

def find_similar_groups(conn: sqlite3.Connection, threshold: int) -> list:
    """
    Return a list of groups, each group being a list of full_paths that are
    mutually within `threshold` hamming distance of at least one other member.

    Algorithm: BK-tree for O(n log n) nearest-neighbour lookup + union-find
    grouping.  Results are cached in the DB and reused on re-runs.
    Requires: pip install pybktree
    """
    try:
        import pybktree
    except ImportError:
        sys.exit("Missing dependency: pip install pybktree")

    rows = conn.execute(
        "SELECT full_path, phash FROM images WHERE phash IS NOT NULL"
    ).fetchall()

    # Pre-convert hex strings to imagehash objects once
    hashes = []
    for r in rows:
        try:
            hashes.append((imagehash.hex_to_hash(r["phash"]), r["full_path"]))
        except Exception:
            pass

    n = len(hashes)
    print(f"Building BK-tree over {n} images (threshold={threshold}) ...")

    def bk_distance(a, b):
        return a[0] - b[0]   # imagehash subtraction = hamming distance

    tree = pybktree.BKTree(bk_distance, hashes)

    # Union-Find
    parent: dict[str, str] = {path: path for _, path in hashes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    try:
        from tqdm import tqdm
        iterator = tqdm(hashes, desc="Querying", unit="img")
    except ImportError:
        iterator = hashes

    for h, path in iterator:
        for _dist, (_mh, match_path) in tree.find((h, path), threshold):
            if match_path != path:
                union(path, match_path)

    # Collect groups
    groups: dict[str, list[str]] = {}
    for _, path in hashes:
        root_key = find(path)
        groups.setdefault(root_key, []).append(path)

    # Only return groups with 2+ members, sorted largest-group first
    result = [sorted(g) for g in groups.values() if len(g) >= 2]
    result.sort(key=len, reverse=True)
    return result


def open_in_feh(paths: list) -> None:
    """Write a temp filelist and invoke feh."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
        fh.write("\n".join(paths) + "\n")
        listfile = fh.name

    try:
        subprocess.run(["feh", "-f", listfile, "-d", "--action1", "rm -fv \"%f\""], check=False)
    except FileNotFoundError:
        print("  [ERROR] 'feh' not found -- install it or use --dry-run", file=sys.stderr)
    finally:
        os.unlink(listfile)


def dupes(db_path: str, threshold: int, dry_run: bool, rescan: bool) -> None:
    if not Path(db_path).exists():
        sys.exit(f"Database not found: {db_path}  -- run 'scan' first.")

    conn = open_db(db_path)

    cache_key = compute_cache_key(conn, threshold)

    if rescan:
        print("--rescan requested, ignoring cache.")
        groups = None
    else:
        groups = load_cache(conn, cache_key)

    if groups is None:
        groups = find_similar_groups(conn, threshold)
        save_cache(conn, cache_key, threshold, groups)
        print(f"Similarity results cached ({len(groups)} group(s)).")

    conn.close()

    if not groups:
        print("No similar images found.")
        return

    total = sum(len(g) for g in groups)
    print(f"\nFound {len(groups)} similarity group(s) covering {total} images.\n")

    for idx, group in enumerate(groups, 1):
        print(f"--- Group {idx}/{len(groups)}  ({len(group)} images) ---")
        for p in group:
            print(f"   {p}")

        # Filter to paths that still exist on disk, largest file first
        existing = sorted(
            (p for p in group if Path(p).exists()),
            key=lambda p: Path(p).stat().st_size,
            reverse=True,
        )
        missing = len(group) - len(existing)
        if missing:
            print(f"  ({missing} path(s) no longer on disk, skipping them)")

        if not existing:
            print("  Skipping -- no files exist.\n")
            continue
        if len(existing) == 1:
            continue

        if dry_run:
            print("  [dry-run] would open in feh\n")
        else:
            print("  Opening in feh ...")
            open_in_feh(existing)
            print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Recursive image scanner with perceptual hashing and similarity viewer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--db", default="imagescan.db", metavar="PATH",
                   help="SQLite database path (default: imagescan.db)")

    sub = p.add_subparsers(dest="command", required=True)

    # scan
    sp = sub.add_parser("scan", help="Scan a folder tree and hash images")
    sp.add_argument("folder", help="Root folder to scan")
    sp.add_argument("--ncores", type=int, default=None,
                    help="Number of CPU cores to use for hashing (default: all available)")

    # dupes
    dp = sub.add_parser("dupes", help="Find similar images and view groups in feh")
    dp.add_argument("--threshold", type=int, default=10,
                    help="Max hamming distance for similarity (default: 10)")
    dp.add_argument("--dry-run", action="store_true",
                    help="Print groups without launching feh")
    dp.add_argument("--rescan", action="store_true",
                    help="Ignore cached similarity results and recompute")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "scan":
        ncores = args.ncores if args.ncores and args.ncores > 0 else cpu_count()
        scan(args.folder, args.db, ncores)
    elif args.command == "dupes":
        dupes(args.db, args.threshold, args.dry_run, args.rescan)


if __name__ == "__main__":
    main()
