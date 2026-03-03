#!/usr/bin/env python3
import os
import sys
import sqlite3
import hashlib
import multiprocessing
import queue
from multiprocessing import Process

# Configuration
DB_NAME = "file_index.db"

def create_table(conn):
    """Create the files table if it doesn't exist."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            full_path BLOB PRIMARY KEY,
            filename BLOB,
            top_folder BLOB,
            mtime INTEGER,
            md5 TEXT,
            filesize INTEGER
        )
    """)
    conn.commit()

def get_existing_records(conn):
    """
    Fetch all existing records from the database.
    Returns a dictionary keyed by full_path (as bytes).
    """
    cursor = conn.cursor()
    cursor.execute("SELECT full_path, filename, top_folder, mtime, md5, filesize FROM files")
    records = {}
    for row in cursor.fetchall():
        path, fname, t_folder, m_time, m_hash, f_size = row
        records[path] = {
            'filename': fname,
            'top_folder': t_folder,
            'mtime': m_time,
            'md5': m_hash,
            'filesize': f_size
        }
    return records

def path_to_bytes(path):
    """
    Convert a path string to bytes using surrogateescape for round-trip safety.
    This ensures files with invalid UTF-8 are stored consistently.
    """
    if isinstance(path, bytes):
        return path
    return path.encode('utf-8', errors='surrogateescape')

def bytes_to_path(b):
    """
    Convert bytes back to a path string for display.
    """
    if isinstance(b, str):
        return b
    return b.decode('utf-8', errors='surrogateescape')

def safe_print(msg, **kwargs):
    """
    Safely print messages, handling any encoding issues.
    """
    try:
        print(msg, **kwargs)
    except UnicodeEncodeError:
        try:
            msg = bytes_to_path(msg.encode(sys.stdout.encoding, errors='replace'))
        except:
            msg = str(msg)
        print(msg, **kwargs)

def compute_md5(args):
    """
    Worker function for multiprocessing.
    Input: (file_path_bytes, top_folder_bytes, fs_metadata)
    Output: (file_path_bytes, md5_hash, success_flag, fs_metadata)
    """
    file_path_bytes, top_folder_bytes, fs_metadata = args
    try:
        file_path = bytes_to_path(file_path_bytes)
        if not os.path.isfile(file_path):
            return (file_path_bytes, None, 0, fs_metadata)
        
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hash_md5.update(chunk)
        return (file_path_bytes, hash_md5.hexdigest(), 1, fs_metadata)
    except Exception:
        return (file_path_bytes, None, 0, fs_metadata)

def scan_filesystem(root_path):
    """
    Recursively scan the folder.
    Returns a list of dictionaries with metadata (no MD5 yet).
    Paths stored as bytes for consistency.
    """
    files_data = []
    top_folder_bytes = path_to_bytes(os.path.abspath(root_path))
    
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        dirpath_bytes = path_to_bytes(dirpath)
        for filename in filenames:
            filename_bytes = path_to_bytes(filename)
            full_path_bytes = path_to_bytes(os.path.join(dirpath, filename))
            try:
                stat = os.stat(bytes_to_path(full_path_bytes))
                files_data.append({
                    'full_path': full_path_bytes,
                    'filename': filename_bytes,
                    'top_folder': top_folder_bytes,
                    'mtime': int(stat.st_mtime),
                    'filesize': stat.st_size
                })
            except OSError:
                continue
    return files_data

def db_writer_process(result_queue, db_path):
    """
    Separate process that consumes results from queue and writes to DB.
    All paths stored as BLOB for consistency.
    """
    conn = sqlite3.connect(db_path)
    create_table(conn)
    
    safe_print("   [DB Writer] Ready")
    
    while True:
        try:
            result = result_queue.get(timeout=1)
            if result is None:  # Poison pill to stop
                safe_print("   [DB Writer] Received stop signal")
                break
            
            action, path_data, md5 = result
            try:
                if action == 'insert':
                    conn.execute(
                        "INSERT INTO files (full_path, filename, top_folder, mtime, md5, filesize) VALUES (?, ?, ?, ?, ?, ?)",
                        (path_data['full_path'],
                         path_data['filename'],
                         path_data['top_folder'],
                         path_data['mtime'],
                         md5,
                         path_data['filesize'])
                    )
                elif action == 'update':
                    conn.execute(
                        "UPDATE files SET md5 = ?, mtime = ?, filesize = ? WHERE full_path = ?",
                        (md5, path_data['mtime'], path_data['filesize'], path_data['full_path'])
                    )
                conn.commit()
                safe_print(f"   [{action.upper()}] {bytes_to_path(path_data['full_path'][:60])}...")
            except Exception as e:
                conn.rollback()
                safe_print(f"   Error writing {bytes_to_path(path_data['full_path']):60}: {e}")
        except queue.Empty:
            continue
    
    conn.close()
    safe_print("   [DB Writer] Closed")

def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <folder_path>")
        sys.exit(1)

    root_folder = sys.argv[1]
    
    if not os.path.isdir(root_folder):
        print(f"Error: '{root_folder}' is not a valid directory.")
        sys.exit(1)

    print(f"Initializing database: {DB_NAME}")
    conn = sqlite3.connect(DB_NAME)
    create_table(conn)
    conn.close()

    print("Step 1: Loading existing database records...")
    conn = sqlite3.connect(DB_NAME)
    db_records = get_existing_records(conn)
    conn.close()
    safe_print(f"   Found {len(db_records)} existing records.")

    print("Step 2: Scanning filesystem...")
    fs_records = scan_filesystem(root_folder)
    safe_print(f"   Found {len(fs_records)} files on disk.")

    # --- Diff Logic (using bytes for comparison) ---
    db_paths = set(db_records.keys())
    fs_paths = set([f['full_path'] for f in fs_records])

    to_insert_paths = fs_paths - db_paths
    to_delete_paths = db_paths - fs_paths
    common_paths = fs_paths & db_paths

    # Identify files that need updating (Size or Time changed)
    to_update_paths = []
    for path in common_paths:
        fs_file = next(f for f in fs_records if f['full_path'] == path)
        db_file = db_records[path]
        
        if fs_file['filesize'] != db_file['filesize'] or fs_file['mtime'] != db_file['mtime']:
            to_update_paths.append(path)

    safe_print(f"   Action Plan: Insert {len(to_insert_paths)}, Update {len(to_update_paths)}, Delete {len(to_delete_paths)}")

    # --- Delete Missing Files (Do this first, no MD5 needed) ---
    if to_delete_paths:
        safe_print("Step 3: Deleting orphaned records...")
        conn = sqlite3.connect(DB_NAME)
        try:
            # Paths are already bytes, ready for SQL
            placeholders = ','.join(['?' for _ in to_delete_paths])
            conn.execute(f"DELETE FROM files WHERE full_path IN ({placeholders})", list(to_delete_paths))
            conn.commit()
            safe_print(f"   Deleted {len(to_delete_paths)} orphaned rows.")
        except Exception as e:
            conn.rollback()
            safe_print(f"   Error deleting: {e}")
        conn.close()

    # --- Parallel MD5 Computation with Immediate DB Writes ---
    files_needing_hash = list(to_insert_paths) + list(to_update_paths)
    
    if files_needing_hash:
        safe_print(f"Step 4: Computing MD5 checksums using {multiprocessing.cpu_count()} cores...")
        
        # Create result queue
        result_queue = multiprocessing.Queue()
        
        # Start database writer process
        db_writer = Process(
            target=db_writer_process,
            args=(result_queue, DB_NAME)
        )
        db_writer.start()
        
        # Prepare args for workers
        hash_args = []
        for path in files_needing_hash:
            fs_file = next(f for f in fs_records if f['full_path'] == path)
            hash_args.append((path, fs_file['top_folder'], fs_file))
        
        # Create worker pool
        with multiprocessing.Pool(processes=None) as pool:
            # Submit all tasks
            async_result = pool.map_async(compute_md5, hash_args)
            
            # Wait for completion
            async_result.wait()
            
            # Get results
            results = async_result.get()
            
            # Send results to writer process
            for path, md5, success, fs_metadata in results:
                if success == 1:
                    action = 'insert' if path in to_insert_paths else 'update'
                    result_queue.put((action, fs_metadata, md5))
                else:
                    safe_print(f"   Warning: Could not compute MD5 for {bytes_to_path(path)}")
        
        # Signal writer to stop
        result_queue.put(None)
        db_writer.join()
        
        safe_print(f"   Processed {len(files_needing_hash)} files with MD5.")
    else:
        safe_print("   No files need MD5 computation.")

    safe_print("Scan complete.")

if __name__ == '__main__':
    multiprocessing.set_start_method('spawn', force=True)
    main()
