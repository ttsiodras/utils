#!/usr/bin/env python3
import os
import sys

# common extensions for video and subtitle files
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.wmv', '.mov', '.flv')
SUBTITLE_EXTENSIONS = ('.srt', '.sub', '.txt', '.ass')

# Maximum allowed Levenshtein distance for a match
# You may need to adjust the threshold based on how noisy the filenames are.
DISTANCE_THRESHOLD = 15


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculates the Levenshtein distance between two strings, s1 and s2.

    The Levenshtein distance (or edit distance) quantifies the minimum number
    of single-character edits (insertions, deletions, or substitutions)
    required to change one word into the other. This algorithm uses a
    classic dynamic programming approach, which is highly effective for
    this type of string comparison problem.

    Detailed Algorithm Explanation:
    ---------------------------

    1. Initialization:
        The core of the algorithm involves constructing and filling a matrix,
        typically denoted as D, where D[i][j] represents the edit distance
        between the prefix s1[1...i] and the prefix s2[1...j].
        The matrix is initialized such that the first row D[0][j] and
        the first column D[i][0] are sequentially filled with 0, 1, 2, 3...
        up to the length of the respective string. This represents the cost of
        transforming an empty string into a non-empty prefix (pure insertions
        or deletions).

    2. Iteration and Recurrence Relation:
        We iterate through the rest of the matrix. For each cell D[i][j],
        the value is calculated based on the minimum cost derived from three
        possible preceding operations:

        a. Deletion: The cost of deleting s1[i] from s1. This cost comes from
           the cell D[i-1][j] plus 1.
        b. Insertion: The cost of inserting s2[j] into s1. This cost comes
           from the cell D[i][j-1] plus 1.
        c. Substitution/Match: The cost of transforming s1[i] to s2[j]. This
           cost comes from the cell D[i-1][j-1]. If s1[i] equals s2[j], the
           cost is 0 (a match); otherwise, the cost is 1 (a substitution).

        The recurrence relation is:
        D[i][j] = min(
            D[i-1][j] + 1,             # Deletion
            D[i][j-1] + 1,             # Insertion
            D[i-1][j-1] + cost_of_sub    # Substitution/Match
        )

    3. Optimization (Space Efficiency):
        Although the concept is described using a full matrix D (size m x n),
        this specific implementation optimizes space by only storing two rows
        (the 'previous_row' and the 'current_row') instead of the whole matrix.
        This reduces the space complexity from O(m*n) to O(min(m, n)).

    4. Time and Space Complexity:
        The time complexity remains O(m*n), where m and n are the lengths of
        the two strings. The space complexity is optimized to O(min(m, n)).

    Parameters:
        s1 (str): The first string.
        s2 (str): The second string.

    Returns:
        int: The minimum Levenshtein distance between s1 and s2.

    Examples:
        >>> levenshtein_distance("kitten", "sitting")  # k/s, e/i, add 'g'
        3
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    # Initialize the matrix
    previous_row = range(len(s2) + 1)

    for i, char1 in enumerate(s1):
        current_row = [i + 1]
        for j, char2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (0 if char1 == char2 else 1)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def find_files(directory: str, extensions: tuple) -> list[str]:
    """Scans the directory for files matching the given extensions."""
    found_files = []
    try:
        for filename in os.listdir(directory):
            if filename.lower().endswith(extensions):
                full_path = os.path.join(directory, filename)
                if os.path.exists(full_path) and not os.path.isdir(full_path):
                    found_files.append(filename)
    except FileNotFoundError:
        print(f"[!] Error: No folder found at {directory}", file=sys.stderr)
        sys.exit(1)
    return found_files


def auto_sub_fixer(directory: str = '.') -> None:
    """
    Finds videos and subtitles, compares their basenames using Levenshtein
    distance, and emits the necessary mv commands for the best match per video.
    """
    print(f"[*] Working in: {os.path.abspath(directory)} ---", file=sys.stderr)
    print(f"[*] Levenshtein dist <= {DISTANCE_THRESHOLD}\n", file=sys.stderr)

    # 1. Find all relevant files
    video_files = find_files(directory, VIDEO_EXTENSIONS)
    sub_files = find_files(directory, SUBTITLE_EXTENSIONS)

    if not video_files or not sub_files:
        print("[!] No videos or subtitles found. Exiting.")
        return

    print(f"[*] Found {len(video_files)} videos and {len(sub_files)} subs.\n",
          file=sys.stderr)

    matches_found = 0
    _ = open("/dev/shm/rename.sh", "w")

    # 2. Iterate through all videos and find the best matching subtitle
    for video_file in video_files:
        # Extract the base name of the video (e.g., "movie" from "movie.mp4")
        video_basename = os.path.splitext(video_file)[0]

        print(f"[*] Video: {video_file} (Basename: '{video_basename}')",
              file=sys.stderr)

        best_match_sub_file = None
        # Initialize higher than the threshold
        min_distance = DISTANCE_THRESHOLD + 1

        for sub_file in sub_files:
            # Extract the base name of the subtitle (e.g., "movie_v2"
            # from "movie_v2.srt")
            sub_basename = os.path.splitext(sub_file)[0]

            # Calculate distance
            distance = levenshtein_distance(video_basename, sub_basename)

            if distance < min_distance:
                min_distance = distance
                best_match_sub_file = sub_file

        # 3. Print the best match command
        if best_match_sub_file:

            # Determine the target filename for the subtitle.
            # The goal is to match the video basename but keep the original
            # subtitle extension.
            original_sub_ext = os.path.splitext(best_match_sub_file)[1]
            trgt_sub_file = video_basename + original_sub_ext

            if best_match_sub_file == trgt_sub_file:
                print("[*] Best match already there.", file=sys.stderr)
                print(f"[*] ====> {best_match_sub_file} {trgt_sub_file}",
                      file=sys.stderr)
            else:
                # Print the required command, include distance for reference
                print(f"[*] Best match found, distance: {min_distance}",
                      file=sys.stderr)
                open("/dev/shm/rename.sh", "a").write(
                    f"mv -iv \"{best_match_sub_file}\" \"{trgt_sub_file}\"\n")
                matches_found += 1
        else:
            print("[!] No subs found within threshold.", file=sys.stderr)

    if matches_found == 0:
        print("\n[!] Did not detect any subtitle fixups.", file=sys.stderr)
        os.unlink("/dev/shm/rename.sh")
    else:
        print(f"\n[*] Found {matches_found} renames.\n", file=sys.stderr)
        print("Run:\n\t. /dev/shm/rename.sh", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) == 2:
        auto_sub_fixer(sys.argv[1])
    elif len(sys.argv) == 1:
        auto_sub_fixer('.')
    else:
        print("Usage:")
        print(f"\t{sys.argv[0]} folder")
        print("\n...or work on current folder:\n")
        print(f"\t{sys.argv[0]}")
