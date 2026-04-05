#!/usr/bin/env python3
import os
import sys
import sqlite3
import subprocess
import tempfile
import hashlib
from PIL import Image
import imagehash
from itertools import combinations
from concurrent.futures import ProcessPoolExecutor, as_completed

DB_NAME = "video_index.db"
MIN_SIZE_BYTES = 5 * 1024 * 1024
THRESHOLD_IN_SECONDS = 3
BLACK_THRESHOLD = 10
FAST_HASH_BYTES = 1024 * 1024  # 1MB


# ---------- fast checksum ----------
def fast_checksum(path):
    print(f"[-] csum-ing {path}")
    try:
        with open(path, "rb") as f:
            data = f.read(FAST_HASH_BYTES)
            return hashlib.md5(data).hexdigest()
    except Exception:
        return None


# ---------- ffprobe ----------
def run_ffprobe(filepath):
    print(f"[-] ffprobe-ing {filepath}")
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                filepath,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return filepath, float(result.stdout.strip())
    except Exception:
        return filepath, None


# ---------- frame extraction ----------
def extract_frame(filepath, timestamp, outpath):
    print(f"[-] frame-extracting {filepath}")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", filepath,
            "-frames:v", "1",
            "-q:v", "2",
            "-threads", "1",
            outpath,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def is_black_image(image_path):
    print(f"[-] black-frame-checking {image_path}")
    try:
        with Image.open(image_path) as img:
            grayscale = img.convert("L")
            pixels = list(grayscale.getdata())
            return (sum(pixels) / len(pixels)) < BLACK_THRESHOLD
    except Exception:
        return True


def compute_phash_worker(args):
    filepath, duration = args

    with tempfile.TemporaryDirectory() as tmpdir:
        timestamp = duration * 0.1
        frame_path = os.path.join(tmpdir, "frame.jpg")

        # for offset in range(0, int(duration)):
        for offset in range(0, min(int(duration), 60)):
            extract_frame(filepath, timestamp + offset, frame_path)

            if os.path.exists(frame_path) and not is_black_image(frame_path):
                try:
                    with Image.open(frame_path) as img:
                        return filepath, str(imagehash.phash(img))
                except Exception:
                    return filepath, None

    return filepath, None


# ---------- DB ----------
def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            path TEXT PRIMARY KEY,
            duration REAL,
            phash TEXT,
            size INTEGER,
            mtime REAL,
            checksum TEXT
        )
    """)
    conn.commit()


# ---------- file collection ----------
def collect_files(folder):
    files = []
    for root, _, filenames in os.walk(folder):
        for f in filenames:
            fullpath = os.path.join(root, f)
            if os.path.islink(fullpath):
                continue
            try:
                size = os.path.getsize(fullpath)
                if size < MIN_SIZE_BYTES:
                    continue
                mtime = os.path.getmtime(fullpath)
                files.append((fullpath, size, mtime))
            except Exception:
                pass
    return files


# ---------- cleanup ----------
def cleanup_deleted(conn, files):
    current_paths = set(p for p, _, _ in files)
    db_paths = set(row[0] for row in conn.execute("SELECT path FROM videos"))

    for p in db_paths - current_paths:
        conn.execute("DELETE FROM videos WHERE path = ?", (p,))

    conn.commit()


# ---------- parallel ffprobe with change detection ----------
def parallel_ffprobe(files, conn):
    existing = {
        row[0]: (row[1], row[2], row[3])  # path -> (size, mtime, checksum)
        for row in conn.execute("SELECT path, size, mtime, checksum FROM videos")
    }

    to_process = []

    for path, size, mtime in files:
        checksum = fast_checksum(path)
        if path not in existing or existing[path] != (size, mtime, checksum):
            to_process.append((path, size, mtime, checksum))

    with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
        futures = {
            executor.submit(run_ffprobe, p): (p, size, mtime, checksum)
            for p, size, mtime, checksum in to_process
        }

        for f in as_completed(futures):
            path, size, mtime, checksum = futures[f]
            _, duration = f.result()

            if duration:
                conn.execute("""
                    INSERT OR REPLACE INTO videos
                    (path, duration, phash, size, mtime, checksum)
                    VALUES (?, ?, NULL, ?, ?, ?)
                """, (path, duration, size, mtime, checksum))

    conn.commit()


# ---------- candidate selection ----------
def find_candidates(conn):
    rows = conn.execute("SELECT path, duration FROM videos").fetchall()

    return [
        (p1, d1, p2, d2)
        for (p1, d1), (p2, d2) in combinations(rows, 2)
        if abs(d1 - d2) <= THRESHOLD_IN_SECONDS
    ]


# ---------- parallel hashing ----------
def compute_hashes(conn, candidates):
    needed = {}
    for p1, d1, p2, d2 in candidates:
        needed[p1] = d1
        needed[p2] = d2

    existing = {
        row[0]: row[1]
        for row in conn.execute("SELECT path, phash FROM videos")
    }

    tasks = [(p, d) for p, d in needed.items() if not existing.get(p)]

    with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
        futures = [executor.submit(compute_phash_worker, t) for t in tasks]

        for f in as_completed(futures):
            path, phash = f.result()
            if phash:
                conn.execute(
                    "UPDATE videos SET phash = ? WHERE path = ?",
                    (phash, path),
                )

    conn.commit()


# ---------- matching ----------
def find_matches(conn, candidates):
    matches = []

    for p1, _, p2, _ in candidates:
        h1 = conn.execute(
            "SELECT phash FROM videos WHERE path = ?", (p1,)
        ).fetchone()[0]
        h2 = conn.execute(
            "SELECT phash FROM videos WHERE path = ?", (p2,)
        ).fetchone()[0]

        # if h1 and h2 and h1 == h2:
        if h1 and h2 and (imagehash.hex_to_hash(h1) - imagehash.hex_to_hash(h2)) <= 10:
            matches.append((p1, p2))

    return matches


# ---------- main ----------
def main():
    if len(sys.argv) != 2:
        print("Usage: python script.py <folder>")
        sys.exit(1)

    folder = sys.argv[1]
    conn = sqlite3.connect(DB_NAME)

    init_db(conn)

    files = collect_files(folder)
    cleanup_deleted(conn, files)

    parallel_ffprobe(files, conn)

    candidates = find_candidates(conn)

    compute_hashes(conn, candidates)

    matches = find_matches(conn, candidates)

    for p1, p2 in matches:
        print(f"{p1}@#@{p2}")

    conn.close()


if __name__ == "__main__":
    main()
