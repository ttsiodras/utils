#!/bin/bash
# 
# Spawn this with the parent folder of your Music collection.
# It will sync it to your Android Music folder, creating .m3u
# files for symlinks to folders ( so your phone's VLC can play them)
#
cd "$1" || exit 1
[ ! -d "Music" ] && {
    echo "[x] Input folder is supposed to have a Music subfolder..."
    exit 1
}
echo "[-] Removing stale old snapshot..."
rm -rf Music.phone || exit 1
echo "[-] Creating new snapshot..."
cp -al Music Music.phone || exit 1
echo "[-] Generating playlists for symlinked dirs, then removing them..."
cd Music.phone || exit 1
# Find all symlinks that point to directories
find . -type l | while read -r LINK; do
    TARGET=$(readlink -f "$LINK")
    # Only process if the symlink points to a directory
    if [ -d "$TARGET" ]; then
        PLAYLIST="${LINK}.m3u"
        # Write an M3U pointing to the real files (relative paths from playlist location)
        echo "#EXTM3U" > "$PLAYLIST"
        find "$TARGET" -type f \( -iname "*.mp3" -o -iname "*.ogg" \
            -o -iname "*.aac" -o -iname "*.m4a" -o -iname "*.opus" \
            -o -iname "*.wav" \) | sort | while read -r TRACK; do
            # Make path relative to the playlist's directory
            REAL_REL=$(realpath --relative-to="$(dirname "$PLAYLIST")" "$TRACK" \
                       2>/dev/null || python3 -c \
                       "import os,sys; print(os.path.relpath(sys.argv[1],sys.argv[2]))" \
                       "$TRACK" "$(dirname "$PLAYLIST")")
            echo "$REAL_REL" >> "$PLAYLIST"
        done
        echo "  [playlist] $PLAYLIST"
        rm -rf "$LINK"
    fi
done

find . -type l -delete
find . -type f | grep -iE '.py$|.txt$|.sh$|.BAT$|.exe$|.flv$|.mkv$|.mp4$|.flac$|flac/|wmv$|Healing|432 Hz|Database|jpg$|DS_Store|asf$|cue$|log$|pl$|srt$|webm$|webp$|settings$|pls$|find$|ini$|mht$|nfo$|sfv$' \
    | while read -r ANS; do rm -f "$ANS"; done || exit 1

echo "[-] Syncing snapshot to phone..."
adb-sync -L ./ /storage/emulated/0/Music/ | pv -l > /dev/null
cd .. || exit 1
echo "[-] Final cleanup of snapshot."
rm -rf Music.phone/
