#!/usr/bin/env python3
"""
Detect duplicate videos in a directory based on duration and perceptual hash.

Quickstart:

    python3 -m venv .venv
    . .venv/bin/activate
    python3 -m pip install ImageHash pillow
    /path/to/find_dup_videos.py /path/to/videos/

"""
# pylint: disable=import-error

import os
import sys
import argparse
import sqlite3
import subprocess
import hashlib
import shutil
import tempfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import combinations
from typing import List, Dict, Optional, NamedTuple
import imagehash  # type: ignore
# pylint: disable=import-error
from PIL import Image, ImageStat  # type: ignore
# pylint: disable=import-error


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
CLEAR_TO_EOL = "\x1b[K"  # ANSI escape: clear from cursor to end of line


def truncate_path(path: Path, max_len: int) -> str:
    """Truncate path for display, showing the end (filename) with '...' prefix.

    Args:
        path: Path to truncate.
        max_len: Maximum display length in characters.

    Returns:
        Truncated path string, or full path if it fits.
    """
    path_str = str(path)
    if len(path_str) <= max_len:
        return path_str
    return "..." + path_str[-(max_len - 3):]


# ----------------------------------------------------------------------
# Named tuples for structured data
# ----------------------------------------------------------------------
class VideoFile(NamedTuple):
    """Video file metadata: path, size in bytes, and modification time."""
    path: Path
    size: int
    mtime: float


class VideoProbeResult(NamedTuple):
    """Result of probing a video file."""
    path: Path
    size: int
    mtime: float
    checksum: Optional[str]


class VideoPair(NamedTuple):
    """Pair of videos with similar durations."""
    path1: Path
    duration1: float
    path2: Path
    duration2: float


class VideoMatch(NamedTuple):
    """Pair of videos that appear to be duplicates."""
    path1: Path
    path2: Path


class HashTask(NamedTuple):
    """Task for computing a video hash."""
    path: Path
    duration: float


class CachedVideoData(NamedTuple):
    """Cached video metadata from the database."""
    size: int
    mtime: float
    checksum: Optional[str]


class VideoDuration(NamedTuple):
    """Video path and duration from database."""
    path: Path
    duration: float


# ----------------------------------------------------------------------
# Configuration constants
# ----------------------------------------------------------------------
DB_NAME = "video_index.db"
MIN_SIZE_BYTES = 5 * 1024 * 1024
DURATION_TOLERANCE = 3.0          # seconds
HASH_DISTANCE_TOLERANCE = 10
BLACK_PIXEL_THRESHOLD = 10
FAST_HASH_BYTES = 1 * 1024 * 1024
MAX_OFFSET_SECONDS = 20
CPU_COUNT = os.cpu_count() or 1

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
        print(f"\n[!] Checksum failed for {path}: {e}")
        return None


def run_ffprobe(filepath: Path) -> Optional[float]:
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
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"\n[!] ffprobe error for {filepath}: "
              f"{result.stderr.strip()}")
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        print(f"\n[!] Unable to parse duration for {filepath}: "
              f"{result.stdout!r}")
        return None


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
        "-nostdin",
        "-loglevel", "error",  # or "quiet"
        "-ss", f"{timestamp}",
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", "2",
        "-threads", "1",
        str(out_path),
    ]
    result = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
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
    iterates with 1-second offsets up to ``MAX_OFFSET_SECONDS`` (20s). Returns
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
                except Exception:  # pylint: disable=broad-exception-caught
                    pass  # fall through to error message
    print(f"\n[!] Failed to compute perceptual hash for\n[!]\n[!]\t"
          f"{video}\n[!]\n[!] I/O error, decoding error, or all frames up"
          f"to MAX_OFFSET_SECONDS ({MAX_OFFSET_SECONDS}) are black.\n[!]")
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


def collect_files(root: Path) -> List[VideoFile]:
    """Recursively collect candidate video files from a directory tree.

    Scans the directory tree for files that meet the minimum size threshold
    (``MIN_SIZE_BYTES`` = 5MB). Skips symbolic links and known library folder.

    Args:
        root: Root directory to scan for video files.

    Returns:
        List of ``VideoFile`` named tuples with path, size, and mtime.

    Filters:
        - Files smaller than ``MIN_SIZE_BYTES`` (5MB) are ignored
        - Symbolic links are skipped
        - Paths containing ``/library/`` or ``audio.HEVC.mp4`` are excluded

    Progress:
        Displays "Collecting files: N found" during scanning.
    """

    video_extensions = {
        "mp4", "m4v", "mkv", "webm", "avi", "mov", "wmv", "flv",
        "f4v", "f4p", "f4a", "f4b", "3gp", "3g2", "mpg", "mpeg",
        "mpe", "mpv", "m2v", "mts", "m2ts", "ts", "vob", "ogv",
        "ogg", "rm", "rmvb", "asf", "amv", "divx", "xvid", "dv",
        "dat", "nsv", "yuv", "h264", "h265", "hevc", "vp8", "vp9",
        "av1", "mxf", "roq", "bik", "smk", "drc", "gifv", "wtv",
        "dvr-ms", "viv", "pva", "evo", "264", "265",
    }

    files: List[VideoFile] = []
    processed = 0
    for p in root.rglob("*"):
        processed += 1
        if not p.is_file() or p.is_symlink():
            continue

        if p.suffix.lower().lstrip(".") not in video_extensions:
            continue

        # Simple heuristics to ignore library folders
        # or known non-video files
        if "/library/" in str(p) or "audio.HEVC.mp4" in str(p):
            continue
        try:
            st = p.stat()
            if st.st_size >= MIN_SIZE_BYTES:
                files.append(VideoFile(p, st.st_size, st.st_mtime))
        except OSError:
            continue
        # progress update
        sys.stdout.write(f"\r[-] Collecting files: {len(files)} found")
        sys.stdout.flush()
    if processed:
        sys.stdout.write("\n")
    return files


def cleanup_deleted(
    conn: sqlite3.Connection,
    present: List[VideoFile],
) -> None:
    """Remove database entries for files that no longer exist on disk.

    Compares the list of currently present files against the database and
    deletes any records for files that have been removed.

    Args:
        conn: Active SQLite database connection.
        present: List of ``VideoFile`` named tuples.

    Note:
        This ensures the database stays in sync with the filesystem state.
    """
    present_set = {str(vf.path) for vf in present}
    cur = conn.execute("SELECT path FROM videos")
    for (path,) in cur:
        if path not in present_set:
            conn.execute("DELETE FROM videos WHERE path = ?", (path,))
    conn.commit()


def parallel_ffprobe(  # pylint: disable=too-many-locals
    files: List[VideoFile],
    conn: sqlite3.Connection,
) -> None:
    """Probe video durations using parallel ``ffprobe`` execution.

    For each file, checks if metadata has changed (size, mtime, or checksum).
    If changed, runs ``ffprobe`` in parallel to get the duration and updates
    the database. Uses a process pool with ``CPU_COUNT`` workers.

    Args:
        files: List of ``VideoFile`` named tuples.
        conn: Active SQLite database connection.

    Optimization:
        - Skips files with unchanged metadata (uses cached values)
        - Only recomputes checksum if size or mtime changed
        - Parallel processing for I/O bound ffprobe operations

    Progress:
        Displays "Reading video metadata: N/M" during execution.
    """
    # Load cached metadata from the DB
    cached: Dict[str, CachedVideoData] = {
        row[0]: CachedVideoData(row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT path, size, mtime, checksum FROM videos"
        )
    }

    to_probe: List[VideoProbeResult] = []
    for vf in files:
        old = cached.get(str(vf.path))
        # Re-compute checksum only if size or mtime changed
        checksum = (
            fast_checksum(vf.path)
            if not old or (vf.size, vf.mtime) != (old.size, old.mtime)
            else old.checksum
        )
        if not old or (vf.size, vf.mtime, checksum) != (
            old.size, old.mtime, old.checksum
        ):
            to_probe.append(
                VideoProbeResult(vf.path, vf.size, vf.mtime, checksum)
            )

    total = len(to_probe)
    processed = 0
    terminal_width = shutil.get_terminal_size().columns
    with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
        futures = {
            executor.submit(run_ffprobe, pr.path): pr
            for pr in to_probe
        }
        for fut in as_completed(futures):
            processed += 1
            result = futures[fut]
            duration = fut.result()
            if duration is not None:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO videos
                    (path, duration, phash, size, mtime, checksum)
                    VALUES (?, ?, NULL, ?, ?, ?)
                    """,
                    (str(result.path), duration,
                     result.size, result.mtime, result.checksum),
                )
            prefix = f"\r[-] Reading video metadata: {processed}/{total} "
            max_path_len = terminal_width - len(prefix) - 10
            path_str = truncate_path(result.path, max_path_len)
            print(f"{prefix}{path_str}{CLEAR_TO_EOL}", end="", flush=True)
    if processed:
        print(f"\r[-] Reading video metadata: "
              f"{total}/{total}{CLEAR_TO_EOL}", flush=True)
    conn.commit()


def find_candidates(
    conn: sqlite3.Connection,
) -> List[VideoPair]:
    """Find pairs of videos with similar durations.

    Compares all video pairs and returns those whose durations differ by
    at most ``DURATION_TOLERANCE`` (3.0 seconds). Videos with similar
    durations are candidates for being duplicates.

    Args:
        conn: Active SQLite database connection.

    Returns:
        List of ``VideoPair`` named tuples where
        ``abs(duration1 - duration2) <= DURATION_TOLERANCE``.

    Note:
        Uses a self-join pattern in Python. For very large collections,
        consider implementing this as a SQL self-join for better performance.

    Complexity:
        O(n²) where n is the number of videos in the database.
    """
    print("[-] Computing candidate videos based on durations...")
    rows = [
        VideoDuration(Path(row[0]), row[1])
        for row in conn.execute("SELECT path, duration FROM videos")
    ]
    return [
        VideoPair(vd1.path, vd1.duration, vd2.path, vd2.duration)
        for vd1, vd2 in combinations(rows, 2)
        if abs(vd1.duration - vd2.duration) <= DURATION_TOLERANCE
    ]


def compute_hashes(  # pylint: disable=too-many-locals
    conn: sqlite3.Connection,
    candidates: List[VideoPair],
) -> None:
    """Compute perceptual hashes for videos that lack them.

    Processes all videos appearing in the candidate list. Only computes hashes
    for videos that don't already have them in the database. Uses parallel
    processing with ``CPU_COUNT`` workers for CPU-intensive phash computation.

    Args:
        conn: Active SQLite database connection.
        candidates: List of ``VideoPair`` named tuples.

    Algorithm:
        1. Collect all unique videos from candidates that lack phashes
        2. Submit phash computation tasks to process pool
        3. Store results in database as they complete

    Progress:
        Displays "Perceptual-hashing candidate videos: N/M" during execution.

    Note:
        Uses dict mapping to ensure correct path-hash pairing despite
        parallel execution order.
    """
    needed: Dict[Path, float] = {
        p: d
        for vp in candidates
        for p, d in [(vp.path1, vp.duration1), (vp.path2, vp.duration2)]
    }
    existing: Dict[str, str] = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT path, phash FROM videos"
        )
    }

    tasks = [
        HashTask(p, d)
        for p, d in needed.items()
        if not existing.get(str(p))
    ]
    total = len(tasks)
    processed = 0
    terminal_width = shutil.get_terminal_size().columns
    with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
        futures = {
            executor.submit(compute_phash, t.path, t.duration): t
            for t in tasks
        }
        for fut in as_completed(futures):
            processed += 1
            task = futures[fut]
            phash = fut.result()
            if phash:
                conn.execute(
                    "UPDATE videos SET phash = ? WHERE path = ?",
                    (phash, str(task.path)),
                )
            prefix = "\r[-] Perceptual-hashing candidate videos: "
            prefix += f"{processed}/{total} "
            max_path_len = terminal_width - len(prefix) - 10
            path_str = truncate_path(task.path, max_path_len)
            print(f"{prefix}{path_str}{CLEAR_TO_EOL}", end="", flush=True)
    if total:
        print(f"\r[-] Perceptual-hashing candidate videos: "
              f"{total}/{total}{CLEAR_TO_EOL}", end="", flush=True)
    print()
    conn.commit()


def find_matches(
    conn: sqlite3.Connection,
    candidates: List[VideoPair],
) -> List[VideoMatch]:
    """Find pairs of videos with similar perceptual hashes.

    Checks each candidate pair (videos with similar durations) to see if their
    perceptual hashes are within ``HASH_DISTANCE_TOLERANCE`` (10). Returns
    pairs that are likely visual duplicates.

    Args:
        conn: Active SQLite database connection.
        candidates: List of ``VideoPair`` named tuples.

    Returns:
        List of ``VideoMatch`` named tuples where both videos have perceptual
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
    matches: List[VideoMatch] = []
    for vp in candidates:
        h1 = hash_map.get(str(vp.path1))
        h2 = hash_map.get(str(vp.path2))
        if h1 and h2:
            if (
                imagehash.hex_to_hash(h1) - imagehash.hex_to_hash(h2)
            ) <= HASH_DISTANCE_TOLERANCE:
                matches.append(VideoMatch(vp.path1, vp.path2))
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
        Usage: find_dup_videos.py <folder>

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
        $ python3 find_dup_videos.py /home/user/videos
        [-] Collecting files: 1779 found
        [-] Reading video metadata: 1779/1779
        [-] Computing candidate videos based on durations...
        [-] Perceptual-hashing candidate videos: 1495/1495

        [-] Duplicates detected:

        /home/user/videos/Xmas-2019/baby.mp4
            /home/user/videos/backup/Xmas-2019/baby.mp4

        ...

    """

    def parse_args():
        parser = argparse.ArgumentParser(
            description="Find duplicate videos"
        )
        parser.add_argument("folder", help="Folder to scan")
        return parser.parse_args()

    args = parse_args()

    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        sys.stderr.write(f"Error: {folder} is not a directory\n")
        sys.exit(1)

    with sqlite3.connect(DB_NAME) as conn:
        init_db(conn)

        files = collect_files(folder)
        cleanup_deleted(conn, files)

        parallel_ffprobe(files, conn)

        candidates = find_candidates(conn)
        compute_hashes(conn, candidates)

        matches = find_matches(conn, candidates)

    if matches:
        print("[-] Duplicates detected:\n")
        for vm in matches:
            print(f"\n{vm.path1}\n\t{vm.path2}")
    else:
        print("[-] No duplicates detected.\n")


if __name__ == "__main__":
    main()
