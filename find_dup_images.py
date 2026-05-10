#!/usr/bin/env python3
"""
find_dup_images.py - Use perceptual hashing for similar image identification.

Usage:
  python find_dup_images.py scan <folder> [--db PATH] [--ncores N]
      Recursively scan <folder>, compute perceptual hashes, store in SQLite DB.
      Re-runs only process changed/new files and prune deleted ones.
      Any change to the image table invalidates the similarity cache.
      Uses parallel processing for hash computation.

  python find_dup_images.py dupes [--db PATH] [--threshold N] [--rescan]
      Find similar images (hamming distance <= threshold, default: 10),
      group them into streaks, and open each group in feh for review.
      Results are cached in the DB and reused on subsequent runs unless the
      image data changed or --rescan is given.

      Inside feh, you can easily remove the duplicates until one is left;
      (feh shows the group size - e.g. 1/5). I recommend you set your
      ~/.config/feh/keys to this:

      $ cat ~/.config/feh/keys
      delete d

      ...and then you just hit key 'd' and the current image is removed.

Options:
  --db PATH         Path to SQLite database (default: imagescan.db)
  --threshold N     Max hamming distance for images similarity (default: 10)
  --rescan          Ignore cached similarity results and recompute
  --ncores N        Number of CPU cores for parallel hashing (default: all)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import cpu_count
from pathlib import Path
from typing import TypedDict

try:
    from PIL import Image
except ImportError:
    sys.exit("Missing dependency: pip install Pillow")

try:
    import imagehash
except ImportError:
    sys.exit("Missing dependency: pip install imagehash")

try:
    import pybktree
except ImportError:
    sys.exit("Missing dependency: pip install pybktree")

try:
    from tqdm import tqdm
except ImportError:
    sys.exit("Missing dependency: pip install tqdm")

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".tiff", ".tif", ".webp", ".heic", ".heif",
    ".avif", ".ico", ".ppm", ".pgm", ".pbm",
})


@dataclass(frozen=True, slots=True)
class ImageRecord:
    """
    All data computed for a single image file.

    Example — /home/user/photos/beach.jpg, ~400 kB

        ImageRecord(
            file_path=Path("/home/user/photos/beach.jpg"),
            phash="a1b2c3d4e5f67890",
            file_size=409600, mtime=1700000000.5,  # bytes / Unix time
    """

    file_path:  Path    # e.g. Path("/home/user/photos/beach.jpg")
    phash:      str     # e.g. "a1b2c3d4e5f67890" — perceptual hash
    file_size:  int     # e.g. 409600 — file size in bytes
    mtime:      float   # e.g. 1700000000.5 — Unix mtime


# A similarity group is a list of file paths, all mutually similar.
# Stored as Path internally; converted to str only at DB/JSON/subprocess
# boundaries.

SimilarityGroups = list[list[Path]]


class ImageRow(TypedDict):
    """
    Shape of a row returned by:
    SELECT full_path, file_size, mtime FROM images
    """
    full_path:  str
    file_size:  int
    mtime:      float


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS images (
    full_path   TEXT    NOT NULL PRIMARY KEY,
    phash       TEXT    NOT NULL,
    file_size   INTEGER NOT NULL,
    mtime       REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_phash ON images (phash);

CREATE TABLE IF NOT EXISTS similarity_edges (
    path_a      TEXT NOT NULL,
    path_b      TEXT NOT NULL,
    threshold   INTEGER NOT NULL,
    PRIMARY KEY (path_a, path_b)
);
CREATE INDEX IF NOT EXISTS idx_edges_a ON similarity_edges (path_a);
CREATE INDEX IF NOT EXISTS idx_edges_b ON similarity_edges (path_b);
"""


def open_db(db_path: str) -> sqlite3.Connection:
    """Open the SQLite DB, run DDL to create/upgrade tables => connection."""
    conn = sqlite3.connect(db_path)
    conn.executescript(DDL)
    conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------

def compute_record(file_path: Path) -> ImageRecord | None:
    """Open image, compute perceptual hash. Returns None on failure."""
    try:
        with Image.open(file_path) as img:
            img.load()
            phash = str(imagehash.phash(img))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # intentionally broad - any decode error must be silent
        print(f"[!] Could not process {file_path}: {exc}", file=sys.stderr)
        return None

    stat = file_path.stat()
    return ImageRecord(
        file_path=file_path.resolve(),
        phash=phash,
        file_size=stat.st_size,
        mtime=stat.st_mtime)


# ---------------------------------------------------------------------------
# Scan mode
# ---------------------------------------------------------------------------

# pylint: disable=too-many-branches,too-many-locals,too-many-statements
def scan(folder: str, db_path: str, ncores: int, threshold: int = 10) -> None:
    """
    Recursively scan `folder`, hash every image, and upsert records in DB.

    Skips unchanged files (size+mtime match the DB entry); idempotent re-runs.
    Removes DB entries for files that no longer exist on disk.
    Updates similarity edges incrementally.
    """
    root = Path(folder).resolve()
    if not root.is_dir():
        sys.exit(f"Not a directory: {root}")

    indexed: dict[str, ImageRow] = {}

    conn = open_db(db_path)
    for row in conn.execute("SELECT full_path, file_size, mtime FROM images"):
        indexed[row["full_path"]] = row

    # All image paths found on disk during this scan
    scanned_paths: set[str] = set()
    tasks: list[Path] = []

    inserted = updated = skipped = removed = errors = 0

    # python local var lookups are faster than globals
    image_extensions = IMAGE_EXTENSIONS

    print(f"[-] Scanning {root} ...")

    # Count files for progress bar (one quick pass)
    file_count = sum(
        1
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in image_extensions
        and not p.is_symlink()
    )
    scan_pbar = tqdm(
        total=file_count, desc="Collecting", unit="file", leave=False)

    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() not in image_extensions:
                continue

            file_path = str(fpath.resolve())
            scanned_paths.add(file_path)
            scan_pbar.update(1)

            try:
                stat = fpath.stat()
            except OSError:
                continue

            # Skip if the file hasn't changed since the last scan
            existing_row = indexed.get(file_path)
            if (
                existing_row
                and existing_row["file_size"] == stat.st_size
            ):
                old_mtime = existing_row["mtime"]
                assert old_mtime is not None
                if abs(old_mtime - stat.st_mtime) < 0.01:
                    skipped += 1
                    continue

            tasks.append(Path(file_path))

    scan_pbar.close()

    # Parallel hash computation
    records: dict[Path, ImageRecord] = {}
    total = len(tasks)

    if ncores > 1:
        with ProcessPoolExecutor(max_workers=ncores) as pool:
            futures = [pool.submit(compute_record, t) for t in tasks]
            iterator = tqdm(
                futures, desc="[-] Hashing images", unit="img", total=total)
            for future in iterator:
                rec = future.result()
                if rec:
                    records[rec.file_path] = rec
    else:
        iterator = tqdm(tasks, desc="Hashing images", unit="img", total=total)
        for task in iterator:
            rec = compute_record(task)
            if rec:
                records[rec.file_path] = rec

    # Tracking changes for incremental similarity updates
    changed_paths: set[str] = set()

    # Write results to DB
    for file_path in sorted(scanned_paths):
        existing_row = indexed.get(file_path)
        img_record = records.get(Path(file_path))

        # In DB and unchanged → nothing to do
        if existing_row and not img_record:
            continue

        if not img_record:
            errors += 1
            continue

        try:
            stat = Path(file_path).stat()
        except OSError:
            continue

        if existing_row:
            conn.execute(
                "UPDATE images SET phash=:phash, file_size=:file_size, "
                "mtime=:mtime WHERE full_path=:file_path",
                {
                    "phash":     img_record.phash,
                    "file_size": img_record.file_size,
                    "mtime":     img_record.mtime,
                    "file_path": str(img_record.file_path),
                },
            )
            updated += 1
            changed_paths.add(str(img_record.file_path))
            print(f"[-] Updated: {file_path}")
        else:
            conn.execute(
                "INSERT INTO images (full_path, phash, file_size, mtime) "
                "VALUES (:file_path, :phash, :file_size, :mtime)",
                {
                    "file_path": str(img_record.file_path),
                    "phash":     img_record.phash,
                    "file_size": img_record.file_size,
                    "mtime":     img_record.mtime,
                },
            )
            inserted += 1
            changed_paths.add(str(img_record.file_path))
            print(f"[-] Inserted: {file_path}")

    # Prune paths that disappeared from disk
    removed_paths: set[str] = set()
    for file_path in indexed:
        if file_path.startswith(str(root)) and file_path not in scanned_paths:
            conn.execute(
                "DELETE FROM images WHERE full_path = ?", (file_path,))
            removed += 1
            removed_paths.add(file_path)
            print(f"[-] Removed: {file_path}")

    conn.commit()

    # Incremental Similarity Update
    if changed_paths or removed_paths:
        print(f"[-] Updating similarity edges incrementally...")
        # 1. Remove edges for removed or updated images
        all_changed = changed_paths | removed_paths
        if all_changed:
            placeholder = ",".join(["?"] * len(all_changed))
            query = (
                f"DELETE FROM similarity_edges "
                f"WHERE path_a IN ({placeholder}) OR path_b IN ({placeholder})"
            )
            conn.execute(query, list(all_changed) + list(all_changed))
        
        # 2. Build a temporary BK-tree of all current images to find new edges
        all_images = conn.execute("SELECT full_path, phash FROM images").fetchall()
        if not all_images:
            conn.commit()
            return

        hash_and_path_list = []
        for row in all_images:
            try:
                hash_and_path_list.append(
                    (imagehash.hex_to_hash(row["phash"]), row["full_path"])
                )
            except Exception:
                continue
        
        def hamming_distance(a, b):
            """Distance function for BK-tree."""
            return a[0] - b[0]
            
        tree = pybktree.BKTree(hamming_distance, hash_and_path_list)
        
        # 3. Only check distances for the images that actually changed
        changed_rows = conn.execute(
            "SELECT phash, full_path FROM images WHERE full_path IN (" +
            ",".join(["?"] * len(changed_paths)) + ")",
            list(changed_paths)
        )
        
        for row in tqdm(
            changed_rows, desc="[-] Computing new similarity edges", unit="img"
        ):
            img_hash = imagehash.hex_to_hash(row["phash"])
            img_path = row["full_path"]
            
            for _, (__, matched_path) in tree.find((img_hash, img_path), threshold):
                if matched_path != img_path:
                    # Store edges symmetrically or consistently (sorted)
                    edge = tuple(sorted([img_path, matched_path]))
                    conn.execute(
                        "INSERT OR IGNORE INTO similarity_edges "
                        "(path_a, path_b, threshold) VALUES (?, ?, ?)",
                        (edge[0], edge[1], threshold)
                    )
        
        conn.commit()
        print("[-] Similarity edges updated.")

    conn.close()
    print(
        f"[-] Done. "
        f"inserted:{inserted} "
        f"updated:{updated} "
        f"skipped:{skipped} "
        f"removed:{removed} "
        f"errors:{errors}"
    )


# ---------------------------------------------------------------------------
# Similarity (dupes) mode
# ---------------------------------------------------------------------------

@dataclass
class _UnionFind:
    """
    Union-Find (Disjoint Set Union) data structure.

    Tracks connected components built from similarity edges.
    Each element starts as its own singleton set; union() merges two sets.
    find() returns the canonical representative (leader) of the set.
    Path compression keeps future lookups O(α(n)) ≈ O(1).
    """
    elements: dict[str, str] = field(default_factory=dict)

    def add(self, item: str) -> None:
        """Register a new element as a singleton set."""
        self.elements[item] = item

    def find(self, item: str) -> str:
        """Return the leader of item's set. Compresses the path."""
        leader = item
        while self.elements[leader] != leader:
            self.elements[leader] = self.elements[self.elements[leader]]
            leader = self.elements[leader]
        return leader

    def union(self, a: str, b: str) -> None:
        """Merge the sets containing elements a and b."""
        leader_a = self.find(a)
        leader_b = self.find(b)
        if leader_a != leader_b:
            self.elements[leader_a] = leader_b


def find_similar_groups(
    conn:      sqlite3.Connection,
    threshold: int,
) -> SimilarityGroups:
    """
    Return a list of similarity groups.
    
    Algorithm:
    1. Load all cached similarity edges for the given threshold.
    2. If no edges exist, compute them using a BK-tree.
    3. Use Union-Find to build connected components from the edges.
    """
    # Load existing edges for this threshold
    edges = conn.execute(
        "SELECT path_a, path_b FROM similarity_edges WHERE threshold = ?",
        (threshold,)
    ).fetchall()

    if not edges:
        print(f"[-] No cached edges found for threshold {threshold}. Computing...")
        # Full computation
        rows = conn.execute(
            "SELECT full_path, phash FROM images WHERE phash IS NOT NULL"
        ).fetchall()

        hash_and_path_list: list[tuple[imagehash.ImageHash, str]] = []
        for row in rows:
            try:
                hash_and_path_list.append(
                    (imagehash.hex_to_hash(row["phash"]), row["full_path"])
                )
            except Exception:
                pass

        if not hash_and_path_list:
            return []

        def hamming_distance(a, b):
            """Distance function for BK-tree."""
            return a[0] - b[0]

        tree = pybktree.BKTree(hamming_distance, hash_and_path_list)
        
        # Compute all pairs and save them
        for img_hash, img_path in tqdm(
                hash_and_path_list, desc="[-] Computing all similarity edges",
                unit="img"):
            for _, (__, matched_path) in tree.find((img_hash, img_path), threshold):
                if matched_path != img_path:
                    edge = tuple(sorted([img_path, matched_path]))
                    conn.execute(
                        "INSERT OR IGNORE INTO similarity_edges "
                        "(path_a, path_b, threshold) VALUES (?, ?, ?)",
                        (edge[0], edge[1], threshold)
                    )
        conn.commit()
        
        # Refresh edges from DB
        edges = conn.execute(
            "SELECT path_a, path_b FROM similarity_edges WHERE threshold = ?",
            (threshold,)
        ).fetchall()

    # Union-Find: group images based on edges
    uf = _UnionFind()
    all_paths = set()
    for path_a, path_b in edges:
        uf.add(path_a)
        uf.add(path_b)
        uf.union(path_a, path_b)
        all_paths.add(path_a)
        all_paths.add(path_b)

    image_groups: dict[str, list[Path]] = {}
    for path in all_paths:
        leader = uf.find(path)
        image_groups.setdefault(leader, []).append(Path(path))

    not_solo_groups: SimilarityGroups = [
        sorted(paths)
        for paths in image_groups.values()
        if len(paths) >= 2
    ]
    not_solo_groups.sort(key=len, reverse=True)
    return not_solo_groups


def open_in_feh(file_paths: list[Path]) -> None:
    """Write a temp filelist and invoke feh."""
    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False) as fh:
        fh.write("\n".join(str(p) for p in file_paths) + "\n")
        listfile = fh.name
    # I recommend you set your ~/.config/feh/keys to this:
    #
    # $ cat ~/.config/feh/keys
    # delete d
    #
    # ...and then you just hit key 'd' and the image shown is removed.
    try:
        subprocess.run(
            ["feh", "-f", listfile, "-d"], check=False)
    except FileNotFoundError:
        print("[x] 'feh' not found -- install it", file=sys.stderr)
    finally:
        os.unlink(listfile)


def dupes(db_path: str, threshold: int, rescan: bool) -> None:
    """
    Find all similarity groups in the DB and open each group in feh.

    Uses the on-disk similarity edges cache.
    Skips groups where only one file still exists on disk.
    """
    if not Path(db_path).exists():
        sys.exit(f"Database not found: {db_path}  -- run 'scan' first.")

    conn = open_db(db_path)

    if rescan:
        print("[-] --rescan requested, clearing similarity edges.")
        conn.execute("DELETE FROM similarity_edges WHERE threshold = ?", (threshold,))
        conn.commit()

    groups = find_similar_groups(conn, threshold)
    conn.close()

    if not groups:
        print("[-] No similar images found.")
        return

    total_images = sum(len(g) for g in groups)
    print(f"\n[-] Found {len(groups)} similarity group(s) covering "
          f"{total_images} images.\n")

    for group_idx, paths_in_group in enumerate(groups, 1):
        print(f"--- Group {group_idx}/{len(groups)}  ({len(paths_in_group)} "
              "images) ---")
        for p in paths_in_group:
            print(f"   {p}")

        # Filter to paths that still exist on disk, largest first
        still_on_disk = sorted(
            (p for p in paths_in_group if p.exists()),
            key=lambda p: p.stat().st_size,
            reverse=True)
        gone_count = len(paths_in_group) - len(still_on_disk)
        if gone_count:
            print(f"  ({gone_count} path(s) no longer on disk, skipping them)")

        if not still_on_disk:
            print("  Skipping -- no files exist.\n")
            continue
        if len(still_on_disk) == 1:
            continue

        print("  Opening in feh ...")
        open_in_feh(still_on_disk)
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level ArgumentParser with all subcommands."""
    p = argparse.ArgumentParser(
        description="Use perceptual hashing for similar image identification.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--db", default="imagescan.db", metavar="PATH",
        help="SQLite database path (default: imagescan.db)",
    )

    sub = p.add_subparsers(dest="command", required=True)

    # scan
    sp = sub.add_parser("scan", help="Scan a folder tree and hash images")
    sp.add_argument("folder", help="Root folder to scan")
    sp.add_argument(
        "--ncores", type=int, default=None,
        help="Number of CPU cores for hashing (default: all available)",
    )

    # dupes
    dp = sub.add_parser("dupes", help="Find similar image groups, view in feh")
    dp.add_argument(
        "--threshold", type=int, default=10,
        help="Max hamming distance for similarity (default: 10)",
    )
    dp.add_argument(
        "--rescan", action="store_true",
        help="Ignore cached similarity results and recompute",
    )

    return p


def main() -> None:
    """Parse CLI args and dispatch to the appropriate subcommand."""
    args = build_parser().parse_args()

    if args.command == "scan":
        ncores = args.ncores if args.ncores and args.ncores > 0 \
                             else cpu_count()
        scan(args.folder, args.db, ncores)
    elif args.command == "dupes":
        dupes(args.db, args.threshold, args.rescan)


if __name__ == "__main__":
    main()
