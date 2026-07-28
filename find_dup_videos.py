#!/usr/bin/env python3
"""
Detect duplicate videos, via duration-checking and perceptual hash matching.

Supports two modes:
  - Normal mode (default): filters candidates by similar duration, uses only
    front perceptual hash.
  - Deep mode  (--deep):  ignores durations entirely; computes both front and
    back phashes for every video; compares front-front and back-back to catch
    duplicates even when one video is cropped at the beginning (or end).  For
    the back phash, specifically, instead of seeking to a relative percentage
    of the video (which would land at different absolute content when durations
    differ), it uses an absolute offset from the end. This means two videos
    that end with the same content will produce the same back phash even if one
    has additional footage at the beginning.

Quickstart:

    # Use your package manager to install the ffmpeg suite.
    # Then...
    python3 -m venv .venv
    . .venv/bin/activate
    python3 -m pip install ImageHash pillow
    ./find_dup_videos.py /path/to/videos/          # normal (duration-filtered)
    ./find_dup_videos.py --deep /path/to/videos/   # deep (no duration filter)

Database note:
    Uses video_index.db to cache metadata and both phashes across runs.
"""

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
from typing import List, Dict, Optional, NamedTuple, Tuple
import imagehash
from PIL import Image, ImageStat


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
CLEAR_TO_EOL = "\x1b[K"  # ANSI escape: clear from cursor to end of line

DB_NAME = "video_index.db"
MIN_SIZE_BYTES = 5 * 1024 * 1024
DURATION_TOLERANCE = 3.0          # seconds (normal mode only)
HASH_DISTANCE_TOLERANCE = 10
BLACK_PIXEL_THRESHOLD = 10
FAST_HASH_BYTES = 1 * 1024 * 1024
MAX_OFFSET_SECONDS = 20
BACK_OFFSET_FROM_END = 30         # seconds before end to start back-phash scan
CPU_COUNT = os.cpu_count() or 1


# ----------------------------------------------------------------------
# Helper utilities
# ----------------------------------------------------------------------


def truncate_path(path: Path, max_len: int) -> str:
    """
    Truncate path for display, showing the end (filename) with '...' prefix.
    """
    path_str = str(path)
    if len(path_str) <= max_len:
        return path_str
    return "..." + path_str[-(max_len - 3):]


def fast_checksum(path: Path) -> Optional[str]:
    """Return the MD5 of the first ``FAST_HASH_BYTES`` of a file."""
    try:
        with path.open("rb") as f:
            data = f.read(FAST_HASH_BYTES)
        return hashlib.md5(data).hexdigest()
    except OSError as e:
        print(f"\n[!] Checksum failed for {path}: {e}")
        return None


def run_ffprobe(filepath: Path) -> Optional[float]:
    """Probe a video file to extract its duration using ``ffprobe``."""
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
    """Extract a single frame from a video at a specific timestamp."""
    cmd = [
        "ffmpeg", "-y",
        "-nostdin",
        "-loglevel", "error",
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


def _extract_phash_from_frame(frame_path: Path) -> Optional[str]:
    """Open a frame image and return its perceptual hash hex string."""
    try:
        with Image.open(frame_path) as img:
            return str(imagehash.phash(img))
    except Exception:  # pylint: disable=broad-exception-caught
        return None


# ----------------------------------------------------------------------
# Perceptual hash computation — front and back
# ----------------------------------------------------------------------


def compute_phash_front(video: Path, duration: float) -> Optional[str]:
    """Compute a perceptual hash from near the beginning of a video.

    Starts at ``duration * 0.2`` and steps forward looking for the first
    non-black frame, up to ``MAX_OFFSET_SECONDS`` (20s) of searching.

    Returns the phash hex string, or ``None`` on failure.
    """
    with tempfile.TemporaryDirectory() as td:
        frame_path = Path(td) / "frame.jpg"
        base_ts = duration * 0.2
        limit = min(int(duration), MAX_OFFSET_SECONDS)
        for offset in range(limit):
            ts = base_ts + offset
            if ts >= duration:
                break
            if not extract_frame(video, ts, frame_path):
                continue
            if not is_black_image(frame_path):
                ph = _extract_phash_from_frame(frame_path)
                if ph:
                    return ph
    print(f"\n[!] Failed to compute front phash for\n[!]\n[!]\t"
          f"{video}\n[!]\n[!] All frames up to MAX_OFFSET_SECONDS "
          f"({MAX_OFFSET_SECONDS}) are black or unreadable.\n[!]")
    return None


def compute_phash_back(video: Path, duration: float) -> Optional[str]:
    """Compute a perceptual hash from near the end of a video.

    Uses an **absolute offset from the end** (``BACK_OFFSET_FROM_END`` = 30s),
    NOT a relative percentage. This ensures that two videos which end with the
    same content produce the same back phash even if one has extra footage at
    the beginning.

    Starts at ``max(0, duration - BACK_OFFSET_FROM_END)`` and steps forward
    looking for the first non-black frame, up to ``MAX_OFFSET_SECONDS`` (20s)
    of searching.

    Returns the phash hex string, or ``None`` on failure.
    """
    with tempfile.TemporaryDirectory() as td:
        frame_path = Path(td) / "frame.jpg"
        base_ts = max(0.0, duration - BACK_OFFSET_FROM_END)
        max_steps = min(int(duration - base_ts), MAX_OFFSET_SECONDS)
        for offset in range(max_steps):
            ts = base_ts + offset
            if ts >= duration:
                break
            if not extract_frame(video, ts, frame_path):
                continue
            if not is_black_image(frame_path):
                ph = _extract_phash_from_frame(frame_path)
                if ph:
                    return ph
    print(f"\n[!] Failed to compute back phash for\n[!]\n[!]\t"
          f"{video}\n[!]\n[!] All frames near the end (last "
          f"{BACK_OFFSET_FROM_END}s) are black or unreadable.\n[!]")
    return None


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
# Database helpers
# ----------------------------------------------------------------------


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize the database, creating tables if they don't exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            path TEXT PRIMARY KEY,
            duration REAL,
            phash TEXT,
            phash_back TEXT,
            size INTEGER,
            mtime REAL,
            checksum TEXT
        )
        """
    )
    conn.commit()

    # Migrate: add phash_back column if missing (for DBs created by older
    # versions of this script, or carried over from the original script).
    try:
        conn.execute("ALTER TABLE videos ADD COLUMN phash_back TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists


def collect_files(root: Path) -> List[VideoFile]:
    """Recursively collect candidate video files from a directory tree."""
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
        sys.stdout.write(f"\r[-] Collecting files: {len(files)} found")
        sys.stdout.flush()
    if processed:
        sys.stdout.write("\n")
    return files


def cleanup_deleted(
    conn: sqlite3.Connection, present: List[VideoFile]
) -> None:
    """Remove database entries for files that no longer exist on disk."""
    present_set = {str(vf.path) for vf in present}
    cur = conn.execute("SELECT path FROM videos")
    for (path,) in cur:
        if path not in present_set:
            conn.execute("DELETE FROM videos WHERE path = ?", (path,))
    conn.commit()


# ----------------------------------------------------------------------
# Parallel ffprobe (shared between normal and deep mode)
# ----------------------------------------------------------------------


def parallel_ffprobe(  # pylint: disable=too-many-locals
    files: List[VideoFile],
    conn: sqlite3.Connection,
) -> None:
    """Probe video durations using parallel ``ffprobe`` execution.

    Only probes files whose (size, mtime, checksum) has changed.
    Stores results in the database with phash and phash_back set to NULL
    (they are filled in later by the hash computation step).
    """
    cached: Dict[str, CachedVideoData] = {
        row[0]: CachedVideoData(row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT path, size, mtime, checksum FROM videos"
        )
    }

    to_probe: List[VideoProbeResult] = []
    for vf in files:
        old = cached.get(str(vf.path))
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
                    (path, duration, phash, phash_back, size, mtime, checksum)
                    VALUES (?, ?, NULL, NULL, ?, ?, ?)
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


# ----------------------------------------------------------------------
# Candidate & hash logic — Normal mode
# ----------------------------------------------------------------------


def find_candidates(conn: sqlite3.Connection) -> List[VideoPair]:
    """Find pairs of videos with similar durations (normal mode only)."""
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


def compute_phash_front_for_videos(  # pylint: disable=too-many-locals
    conn: sqlite3.Connection,
    needed: Dict[Path, float],
    label: str,
) -> None:
    """Compute front phashes for videos that lack them.

    Args:
        conn: Database connection.
        needed: Dict mapping video path -> duration for videos needing phashes.
        label: Progress label (e.g., "front" or "back").
    """
    existing: Dict[str, Optional[str]] = {
        row[0]: row[1]
        for row in conn.execute("SELECT path, phash FROM videos")
    }

    tasks = [
        (p, d)
        for p, d in needed.items()
        if not existing.get(str(p))
    ]
    total = len(tasks)
    processed = 0
    terminal_width = shutil.get_terminal_size().columns

    with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
        futures = {
            executor.submit(compute_phash_front, path, dur): (path, dur)
            for path, dur in tasks
        }
        for fut in as_completed(futures):
            processed += 1
            path, _ = futures[fut]
            phash = fut.result()
            if phash:
                conn.execute(
                    "UPDATE videos SET phash = ? WHERE path = ?",
                    (phash, str(path)),
                )
            prefix = f"\r[-] {label}: {processed}/{total} "
            max_path_len = terminal_width - len(prefix) - 10
            path_str = truncate_path(path, max_path_len)
            print(f"{prefix}{path_str}{CLEAR_TO_EOL}", end="", flush=True)
    if total:
        print(f"\r[-] {label}: "
              f"{total}/{total}{CLEAR_TO_EOL}", flush=True)
    print()
    conn.commit()


def compute_hashes_normal(
    conn: sqlite3.Connection,
    candidates: List[VideoPair],
) -> None:
    """Compute front phashes for all candidate-list videos (normal mode)."""
    needed: Dict[Path, float] = {
        p: d
        for vp in candidates
        for p, d in [(vp.path1, vp.duration1), (vp.path2, vp.duration2)]
    }
    compute_phash_front_for_videos(
        conn, needed, "Perceptual-hashing candidate videos"
    )


def find_matches_normal(
    conn: sqlite3.Connection,
    candidates: List[VideoPair],
) -> List[VideoMatch]:
    """Find matches by comparing front phashes for each candidate pair.
    Checks each candidate pair (videos with similar durations) to see if their
    perceptual hashes are within ``HASH_DISTANCE_TOLERANCE`` (currently 10).
    Returns pairs that are likely visual duplicates.
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
# Hash & match logic — Deep mode
# ----------------------------------------------------------------------


def compute_hashes_deep(
    conn: sqlite3.Connection,
) -> None:
    """Compute both front AND back phashes for ALL videos that lack them.

    In deep mode, every video needs both hashes so we can compare both
    F-F and B-B combinations without any duration pre-filtering.
    """
    rows = list(conn.execute(
        "SELECT path, duration, phash, phash_back FROM videos"
    ))

    # Separate out which videos need front and/or back hashes
    front_needed: Dict[Path, float] = {}
    back_needed: Dict[Path, float] = {}

    for path_str, duration, phash, phash_back in rows:
        p = Path(path_str)
        if not phash:
            front_needed[p] = duration
        if not phash_back:
            back_needed[p] = duration

    if front_needed:
        compute_phash_front_for_videos(
            conn, front_needed, "Hashing front (deep)"
        )
    else:
        print("[-] All front phashes already cached (deep mode).")

    if back_needed:
        _compute_phash_back_for_videos(
            conn, back_needed, "Hashing back (deep)"
        )
    else:
        print("[-] All back phashes already cached (deep mode).")


def _compute_phash_back_for_videos(
    conn: sqlite3.Connection,
    needed: Dict[Path, float],
    label: str,
) -> None:
    """Compute back phashes for videos that lack them (helper for deep mode).

    Runs in parallel, updating the ``phash_back`` column in the database.
    """
    total = len(needed)
    processed = 0
    terminal_width = shutil.get_terminal_size().columns

    with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
        futures = {
            executor.submit(compute_phash_back, path, dur): (path, dur)
            for path, dur in needed.items()
        }
        for fut in as_completed(futures):
            processed += 1
            path, _ = futures[fut]
            phash = fut.result()
            if phash:
                conn.execute(
                    "UPDATE videos SET phash_back = ? WHERE path = ?",
                    (phash, str(path)),
                )
            prefix = f"\r[-] {label}: {processed}/{total} "
            max_path_len = terminal_width - len(prefix) - 10
            path_str = truncate_path(path, max_path_len)
            print(f"{prefix}{path_str}{CLEAR_TO_EOL}", end="", flush=True)
    if total:
        print(f"\r[-] {label}: "
              f"{total}/{total}{CLEAR_TO_EOL}", flush=True)
    print()
    conn.commit()


def find_matches_deep(conn: sqlite3.Connection) -> List[VideoMatch]:
    # pylint: disable=too-many-locals
    """Find duplicate pairs by comparing front-front and back-back phashes,
    with NO duration pre-filtering.

    For every pair of videos, two comparisons are made:
        A.front - B.front     catches same beginning (extra footage at end)
        A.back  - B.back      catches same ending (extra footage at start)

    If EITHER distance is <= HASH_DISTANCE_TOLERANCE, the pair is reported as
    a match.
    """
    print("[-] Comparing all video pairs (deep mode, no duration filter)...")

    rows = list(conn.execute(
        "SELECT path, phash, phash_back FROM videos"
    ))

    # Build a lookup: path -> (front_hash, back_hash)
    # Skip videos missing both hashes
    video_hashes: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    for path_str, ph, ph_back in rows:
        if ph or ph_back:
            video_hashes[path_str] = (ph, ph_back)

    paths = list(video_hashes.keys())
    total_pairs = len(paths) * (len(paths) - 1) // 2
    checked = 0
    matches: List[VideoMatch] = []

    for p1_str, p2_str in combinations(paths, 2):
        checked += 1
        if checked % 500 == 0 or checked == total_pairs:
            print(f"\r[-] Compared {checked}/{total_pairs} pairs"
                  f"{CLEAR_TO_EOL}", end="", flush=True)

        h1_front, h1_back = video_hashes[p1_str]
        h2_front, h2_back = video_hashes[p2_str]

        is_match = False

        # F - F  — same beginning (catches extra footage at end)
        if h1_front and h2_front:
            d = (imagehash.hex_to_hash(h1_front) -
                 imagehash.hex_to_hash(h2_front))
            if d <= HASH_DISTANCE_TOLERANCE:
                is_match = True

        # B - B  — same ending (catches extra footage at start)
        if not is_match and h1_back and h2_back:
            d = (imagehash.hex_to_hash(h1_back) -
                 imagehash.hex_to_hash(h2_back))
            if d <= HASH_DISTANCE_TOLERANCE:
                is_match = True

        if is_match:
            matches.append(VideoMatch(Path(p1_str), Path(p2_str)))

    if total_pairs:
        print(f"\r[-] Compared {total_pairs}/{total_pairs} pairs"
              f"{CLEAR_TO_EOL}", flush=True)
    print()
    return matches


# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------


def main() -> None:
    """Main entry point.

    Two modes:
      - Normal (default): same as the original find_dup_videos.py
      - Deep (--deep):   ignores durations; uses front+back phash on all videos
    """

    def parse_args():
        parser = argparse.ArgumentParser(
            description="Find duplicate videos (with optional deep mode)"
        )
        parser.add_argument("folder", help="Folder to scan")
        parser.add_argument(
            "--deep", action="store_true",
            help="Deep mode: ignore video durations, use both front and back "
                 "perceptual hashes to find duplicates even when one video is "
                 "cropped at the beginning or end.",
        )
        parser.add_argument(
            "--report", metavar="FILE",
            help="Write the duplicate list to FILE (plain text, paths only).",
        )
        return parser.parse_args()

    args = parse_args()

    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        sys.stderr.write(f"Error: {folder} is not a directory\n")
        sys.exit(1)

    with sqlite3.connect(DB_NAME) as conn:
        init_db(conn)

        # -- Step 1: collect files
        files = collect_files(folder)
        cleanup_deleted(conn, files)

        # -- Step 2: probe durations (always needed, even in deep mode,
        #    because duration is used for frame-offset calculations)
        parallel_ffprobe(files, conn)

        if args.deep:
            # ----------------------------------------------------------------
            # DEEP MODE: no duration filtering
            # ----------------------------------------------------------------
            print("[-] Deep mode enabled — ignoring video durations.")

            # Step 3: compute front AND back phashes for ALL videos
            compute_hashes_deep(conn)

            # Step 4: compare all pairs using F-F and B-B comparisons
            matches = find_matches_deep(conn)

        else:
            # ----------------------------------------------------------------
            # NORMAL MODE: duration-based candidate filtering
            # (original behaviour)
            # ----------------------------------------------------------------
            candidates = find_candidates(conn)
            compute_hashes_normal(conn, candidates)
            matches = find_matches_normal(conn, candidates)

    # -- Output results
    if matches:
        print("[-] Duplicates detected:\n")
        for vm in matches:
            print(f"\n{vm.path1}\n\t{vm.path2}")

        if args.report:
            report_path = Path(args.report)
            try:
                with report_path.open("w", encoding="utf-8") as f:
                    for vm in matches:
                        f.write(f"{vm.path1}\n\t{vm.path2}\n\n")
                print(f"[-] Report written to {report_path}\n")
            except OSError as e:
                sys.stderr.write(f"[!] Failed to write report: {e}\n")
    else:
        print("[-] No duplicates detected.\n")
        if args.report:
            report_path = Path(args.report)
            try:
                with report_path.open("w", encoding="utf-8") as f:
                    f.write("# No duplicates detected.\n")
                print(f"[-] Report written to {report_path}\n")
            except OSError as e:
                sys.stderr.write(f"[!] Failed to write report: {e}\n")


if __name__ == "__main__":
    main()
