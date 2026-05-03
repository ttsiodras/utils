#!/usr/bin/env python3
"""
Detect duplicate videos in a directory based on duration and perceptual hash.
"""
# pylint: disable=import-error

import os
import sys
import argparse
import sqlite3
import subprocess
import hashlib
import logging
import tempfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import combinations
from typing import List, Tuple, Dict, Optional
import imagehash  # type: ignore
# pylint: disable=import-error
from PIL import Image, ImageStat  # type: ignore
# pylint: disable=import-error


# ----------------------------------------------------------------------
# Configuration constants
# ----------------------------------------------------------------------
DB_NAME = "video_index.db"
MIN_SIZE_BYTES = 5 * 1024 * 1024
DURATION_TOLERANCE = 3.0          # seconds
HASH_DISTANCE_TOLERANCE = 10
BLACK_PIXEL_THRESHOLD = 10
FAST_HASH_BYTES = 1 * 1024 * 1024
MAX_OFFSET_SECONDS = 10
CPU_COUNT = os.cpu_count() or 1

# ----------------------------------------------------------------------
# Verbose mode
# ----------------------------------------------------------------------
g_verbose = False

# ----------------------------------------------------------------------
# Helper utilities
# ----------------------------------------------------------------------


def fast_checksum(path: Path) -> Optional[str]:
    """Return the MD5 of the first ``FAST_HASH_BYTES`` of a file.

    This provides a quick id for the content without reading the entire file.

    Args:
        path: Path to the file to checksum.

    Returns:
        Hexadecimal MD5 hash string of the first 1MB of the file,
        or ``None`` on I/O error.

    Example:
        >>> fast_checksum(Path("video.mp4"))
        'deadc0de0badbeefdeadc0de0badbeef'
    """
    try:
        with path.open("rb") as f:
            data = f.read(FAST_HASH_BYTES)
        return hashlib.md5(data).hexdigest()
    except OSError as e:
        log.debug("Checksum failed for %s: %s", path, e)
        return None


def run_ffprobe(filepath: Path) -> Tuple[Path, Optional[float]]:
    """Probe a video file to extract its duration using ``ffprobe``.

    Args:
        filepath: Path to the video file to probe.

    Returns:
        A tuple of ``(filepath, duration)`` where duration is in seconds.
        Returns ``(filepath, None)`` if the file cannot be probed or parsed.

    Note:
        Uses ``ffprobe``:

        -v error — sets log level to only show errors, suppressing the usual
                   ffprobe banner/info noise
        -show_entries format=duration — tells ffprobe to extract only
                   the duration field from the format section (as opposed to
                   stream-level metadata)
        -of default=noprint_wrappers=1:nokey=1 — controls output formatting:

            default = use the default (key=value) output format
            noprint_wrappers=1 = don't print headers like [FORMAT] / [/FORMAT]
            nokey=1 = don't print key name (duration=), just the bare value
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(filepath),
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        log.debug("ffprobe error for %s: %s", filepath, result.stderr.strip())
        return filepath, None
    try:
        return filepath, float(result.stdout.strip())
    except ValueError:
        log.debug(
            "Unable to parse duration for %s: %r",
            filepath,
            result.stdout,
        )
        return filepath, None


def extract_frame(video: Path, timestamp: float, out_path: Path) -> bool:
    """Extract a single frame from a video at a specific timestamp.

    Uses ``ffmpeg`` to extract one high-quality JPEG frame
    at the given timestamp.

    Args:
        video: Path to the source video file.
        timestamp: Time in seconds where the frame should be extracted.
        out_path: Path where the extracted frame will be saved.

    Returns:
        ``True`` if extraction succeeded, ``False`` otherwise.

    Note:
        The output image is saved as a high-quality JPEG (``-q:v 2``).
    """
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{timestamp}",
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", "2",
        "-threads", "1",
        str(out_path),
    ]
    result = subprocess.run(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    return result.returncode == 0


def is_black_image(image_path: Path) -> bool:
    """Check if an image is predominantly black (low luminance).

    Calculates the average luminance of the image and compares it against
    ``BLACK_PIXEL_THRESHOLD``. Useful for filtering out black/blank frames
    during perceptual hash computation.

    Args:
        image_path: Path to the image file to check.

    Returns:
        ``True`` if the average luminance is below ``BLACK_PIXEL_THRESHOLD``
        (10), or if the image cannot be read (treated as black).

    Note:
        Any read errors are silently treated as black images to avoid
        breaking the frame selection process.
    """
    try:
        with Image.open(image_path) as img:
            avg = ImageStat.Stat(img.convert("L")).mean[0]
        return avg < BLACK_PIXEL_THRESHOLD
    except OSError:
        return True


def compute_phash(video: Path, duration: float) -> Optional[str]:
    """Compute a perceptual hash (phash) for a video file.

    Extracts frames starting at ``duration * 0.2`` (20% into the video) and
    iterates with 1-second offsets up to ``MAX_OFFSET_SECONDS`` (10s). Returns
    the phash of the first non-black frame found.

    Perceptual hashes allow comparison of visual similarity between videos
    regardless of exact pixel content.

    Args:
        video: Path to the video file to hash.
        duration: Duration of the video in seconds
                  (used to calculate starting offset).

    Returns:
        Hexadecimal perceptual hash string (e.g., ``'d3adc0de0badbeef'``),
        or ``None`` if no suitable frame was found.

    Algorithm:
        1. Start at timestamp = duration * 0.2
        2. Extract frame and check if it's black (luminance < 10)
        3. If not black, compute and return phash
        4. If black, try next offset (timestamp + 1 second)
        5. Repeat until MAX_OFFSET_SECONDS or end of video

    Example:
        >>> compute_phash(Path("video.mp4"), 31.4159)
        'd3adc0de0badbeef'
    """
    if g_verbose:
        (f"\n[-] Computing hash for {video}")
    with tempfile.TemporaryDirectory() as td:
        frame_path = Path(td) / "frame.jpg"
        base_ts = duration * 0.2
        for offset in range(min(int(duration), MAX_OFFSET_SECONDS)):
            ts = base_ts + offset
            if ts >= duration:
                break
            if not extract_frame(video, ts, frame_path):
                continue
            if not is_black_image(frame_path):
                try:
                    with Image.open(frame_path) as img:
                        return str(imagehash.phash(img))
                finally:
                    pass
    return None


# ----------------------------------------------------------------------
# Database helpers
# ----------------------------------------------------------------------
def init_db(conn: sqlite3.Connection) -> None:
    """Initialize the database by creating the ``videos`` table
       if it doesn't exist.

    Creates a table to store video metadata including path, duration,
    perceptual hash, file size, modification time, and checksum.

    Args:
        conn: Active SQLite database connection.

    Table Schema:
        - ``path`` (TEXT PRIMARY KEY): Absolute path to the video file
        - ``duration`` (REAL): Video duration in seconds
        - ``phash`` (TEXT): Perceptual hash for similarity detection
        - ``size`` (INTEGER): File size in bytes
        - ``mtime`` (REAL): File modification timestamp
        - ``checksum`` (TEXT): MD5 of first 1MB of file content
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            path TEXT PRIMARY KEY,
            duration REAL,
            phash TEXT,
            size INTEGER,
            mtime REAL,
            checksum TEXT
        )
        """
    )
    conn.commit()


def collect_files(root: Path) -> List[Tuple[Path, int, float]]:
    """Recursively collect candidate video files from a directory tree.

    Scans the directory tree for files that meet the minimum size threshold
    (``MIN_SIZE_BYTES`` = 5MB). Skips symbolic links and known library folder.

    Args:
        root: Root directory to scan for video files.

    Returns:
        List of tuples ``(path, size, mtime)`` where:
            - ``path``: Absolute path to the video file
            - ``size``: File size in bytes
            - ``mtime``: Modification timestamp (Unix epoch)

    Filters:
        - Files smaller than ``MIN_SIZE_BYTES`` (5MB) are ignored
        - Symbolic links are skipped
        - Paths containing ``/library/`` or ``audio.HEVC.mp4`` are excluded

    Progress:
        Displays "Collecting files: N found" during scanning.
    """
    files: List[Tuple[Path, int, float]] = []
    processed = 0
    for p in root.rglob("*"):
        processed += 1
        if not p.is_file() or p.is_symlink():
            continue
        # Simple heuristics to ignore library folders
        # or known non-video files
        if "/library/" in str(p) or "audio.HEVC.mp4" in str(p):
            continue
        try:
            st = p.stat()
            if st.st_size >= MIN_SIZE_BYTES:
                files.append((p, st.st_size, st.st_mtime))
        except OSError:
            continue
        # progress update
        sys.stdout.write(f"\rCollecting files: {len(files)} found")
        sys.stdout.flush()
    sys.stdout.write("\n")
    return files


def cleanup_deleted(
    conn: sqlite3.Connection,
    present: List[Tuple[Path, int, float]],
) -> None:
    """Remove database entries for files that no longer exist on disk.

    Compares the list of currently present files against the database and
    deletes any records for files that have been removed.

    Args:
        conn: Active SQLite database connection.
        present: List of existing files as ``(path, size, mtime)`` tuples.

    Note:
        This ensures the database stays in sync with the filesystem state.
    """
    present_set = {str(p) for p, _, _ in present}
    cur = conn.execute("SELECT path FROM videos")
    for (path,) in cur:
        if path not in present_set:
            conn.execute("DELETE FROM videos WHERE path = ?", (path,))
    conn.commit()


def parallel_ffprobe(
    files: List[Tuple[Path, int, float]],
    conn: sqlite3.Connection,
) -> None:
    """Probe video durations using parallel ``ffprobe`` execution.

    For each file, checks if metadata has changed (size, mtime, or checksum).
    If changed, runs ``ffprobe`` in parallel to get the duration and updates
    the database. Uses a process pool with ``CPU_COUNT`` workers.

    Args:
        files: List of video files as ``(path, size, mtime)`` tuples.
        conn: Active SQLite database connection.

    Optimization:
        - Skips files with unchanged metadata (uses cached values)
        - Only recomputes checksum if size or mtime changed
        - Parallel processing for I/O bound ffprobe operations

    Progress:
        Displays "Probing files: N/M" during execution.
    """
    # Load cached metadata from the DB
    cached = {
        row[0]: (row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT path, size, mtime, checksum FROM videos"
        )
    }

    to_probe: List[Tuple[Path, int, float, Optional[str]]] = []
    for path, size, mtime in files:
        old = cached.get(str(path))
        # Re-compute checksum only if size or mtime changed
        checksum = (
            fast_checksum(path)
            if not old or (size, mtime) != old[:2]
            else old[2]
        )
        if not old or (size, mtime, checksum) != old:
            to_probe.append((path, size, mtime, checksum))

    total = len(to_probe)
    processed = 0
    with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
        futures = {
            executor.submit(run_ffprobe, p): (p, size, mtime, checksum)
            for p, size, mtime, checksum in to_probe
        }
        for fut in as_completed(futures):
            processed += 1
            sys.stdout.write(f"\rProbing files: {processed}/{total}")
            sys.stdout.flush()
            path, size, mtime, checksum = futures[fut]
            _, duration = fut.result()
            if duration is not None:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO videos
                    (path, duration, phash, size, mtime, checksum)
                    VALUES (?, ?, NULL, ?, ?, ?)
                    """,
                    (str(path), duration, size, mtime, checksum),
                )
    sys.stdout.write("\n")
    conn.commit()


def find_candidates(
    conn: sqlite3.Connection,
) -> List[Tuple[Path, float, Path, float]]:
    """Find pairs of videos with similar durations.

    Compares all video pairs and returns those whose durations differ by
    at most ``DURATION_TOLERANCE`` (3.0 seconds). Videos with similar
    durations are candidates for being duplicates.

    Args:
        conn: Active SQLite database connection.

    Returns:
        List of tuples ``(path1, duration1, path2, duration2)`` where
        ``abs(duration1 - duration2) <= DURATION_TOLERANCE``.

    Note:
        Uses a self-join pattern in Python. For very large collections,
        consider implementing this as a SQL self-join for better performance.

    Complexity:
        O(n²) where n is the number of videos in the database.
    """
    rows = conn.execute("SELECT path, duration FROM videos").fetchall()
    return [
        (Path(p1), d1, Path(p2), d2)
        for (p1, d1), (p2, d2) in combinations(rows, 2)
        if abs(d1 - d2) <= DURATION_TOLERANCE
    ]


def compute_hashes(
    conn: sqlite3.Connection,
    candidates: List[Tuple[Path, float, Path, float]],
) -> None:
    """Compute perceptual hashes for videos that lack them.

    Processes all videos appearing in the candidate list. Only computes hashes
    for videos that don't already have them in the database. Uses parallel
    processing with ``CPU_COUNT`` workers for CPU-intensive phash computation.

    Args:
        conn: Active SQLite database connection.
        candidates: List of video pairs with similar durations as
                    ``(path1, duration1, path2, duration2)`` tuples.

    Algorithm:
        1. Collect all unique videos from candidates that lack phashes
        2. Submit phash computation tasks to process pool
        3. Store results in database as they complete

    Progress:
        Displays "Hashing videos: N/M" during execution.

    Note:
        Uses dict mapping to ensure correct path-hash pairing despite
        parallel execution order.
    """
    needed: Dict[Path, float] = {
        p: d for p1, d1, p2, d2 in candidates for p, d in [(p1, d1), (p2, d2)]
    }
    existing = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT path, phash FROM videos"
        )
    }

    tasks = [(p, d) for p, d in needed.items() if not existing.get(str(p))]
    total = len(tasks)
    processed = 0
    with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
        futures = {
            executor.submit(compute_phash, p, d): (p, d)
            for p, d in tasks
        }
        for fut in as_completed(futures):
            processed += 1
            sys.stdout.write(f"\rHashing videos: {processed}/{total}")
            sys.stdout.flush()
            p, _ = futures[fut]
            phash = fut.result()
            if phash:
                conn.execute(
                    "UPDATE videos SET phash = ? WHERE path = ?",
                    (phash, str(p)),
                )
    sys.stdout.write("\n")
    conn.commit()


def find_matches(
    conn: sqlite3.Connection,
    candidates: List[Tuple[Path, float, Path, float]],
) -> List[Tuple[Path, Path]]:
    """Find pairs of videos with similar perceptual hashes.

    Checks each candidate pair (videos with similar durations) to see if their
    perceptual hashes are within ``HASH_DISTANCE_TOLERANCE`` (10). Returns
    pairs that are likely visual duplicates.

    Args:
        conn: Active SQLite database connection.
        candidates: List of video pairs with similar durations as
                    ``(path1, duration1, path2, duration2)`` tuples.

    Returns:
        List of tuples ``(path1, path2)`` where both videos have perceptual
        hashes within ``HASH_DISTANCE_TOLERANCE`` of each other.

    Algorithm:
        1. Load all video hashes from database into memory
        2. For each candidate pair, compare their phashes
        3. Return pairs where hamming distance <= ``HASH_DISTANCE_TOLERANCE``

    Note:
        The perceptual hash comparison uses imagehash's built-in distance
        calculation (hamming distance between hash bit patterns).
    """
    hash_map = {
        row[0]: row[1]
        for row in conn.execute("SELECT path, phash FROM videos")
    }
    matches: List[Tuple[Path, Path]] = []
    for p1, _, p2, _ in candidates:
        h1 = hash_map.get(str(p1))
        h2 = hash_map.get(str(p2))
        if h1 and h2:
            if (
                imagehash.hex_to_hash(h1) - imagehash.hex_to_hash(h2)
            ) <= HASH_DISTANCE_TOLERANCE:
                matches.append((p1, p2))
    return matches


# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------
def main() -> None:
    """Main entry point for the duplicate video detection script.

    Orchestrates the full duplicate detection pipeline:
        1. Parse command-line arguments
        2. Initialize database
        3. Collect video files from target directory
        4. Clean up entries for deleted files
        5. Probe video durations (parallel)
        6. Find duration-based candidates
        7. Compute perceptual hashes (parallel)
        8. Find matching duplicates
        9. Output duplicate pairs

    Command Line:
        Usage: find_dup_videos_refactored.py <folder>

        Arguments:
            folder: Path to the directory tree to scan for duplicate videos.

    Output:
        Prints duplicate video pairs in the format:
        ``<path1>\n\t<path2>``

    Database:
        Uses ``video_index.db`` in the current working directory.
        The database is created if it doesn't exist and persists
        metadata across runs for incremental updates.

    Example:
        $ python3 find_dup_videos_refactored.py /home/user/videos
        /home/user/videos/movie1.mp4\n\t/home/user/videos/movie1_copy.mp4
        /home/user/videos/clip.mp4\n\t/home/user/videos/clip_renders.mp4
    """
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: find_dup_videos_refactored.py <folder>\n")
        sys.exit(1)

    def parse_args():
        parser = argparse.ArgumentParser(
            description="Find duplicate videos"
        )
        parser.add_argument("folder", help="Folder to scan")
        parser.add_argument("-v", "--verbose", action="store_true",
                            help="Enable verbose output")
        return parser.parse_args()

    args = parse_args()

    global g_verbose
    g_verbose = args.verbose

    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        sys.stderr.write(f"Error: {folder} is not a directory\n")
        sys.exit(1)

    try:
        with sqlite3.connect(DB_NAME) as conn:
            init_db(conn)

            files = collect_files(folder)
            cleanup_deleted(conn, files)

            parallel_ffprobe(files, conn)

            candidates = find_candidates(conn)
            compute_hashes(conn, candidates)

            matches = find_matches(conn, candidates)

        for p1, p2 in matches:
            print(f"\n{p1}\n\t{p2}")
    finally:
        # Ensure terminal is left in a clean state
        sys.stdout.write("\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
