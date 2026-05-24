#!/usr/bin/env python3
"""
sub_auto_fixer.py — generic subtitle-to-video matcher

Uses a combined score:
  - Dice coefficient for token overlap (content match)
  - LCS (longest common subsequence) for word order

Final score = 0.6 * dice + 0.4 * lcs_normalized
"""
import os
import re
import sys

# common extensions for video and subtitle files
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.wmv', '.mov', '.flv', '.m4v', '.mpeg', '.mpg')
SUBTITLE_EXTENSIONS = ('.srt', '.sub', '.txt', '.ass', '.ssa', '.smi', '.idx')

# Dice coefficient theory
#
#   Dice(A,B) = 2 * O / (W1 + W2)
#
#   where:
#
#     W1  = sum_{tok in A} wt(tok) * cnt_A(tok)
#     W2  = sum_{tok in B} wt(tok) * cnt_B(tok)
#     O   = sum_{tok in A n B} wt(tok) * min(cnt_A(tok), cnt_B(tok))
#
#     wt(tok) = 2 if tok is numeric else 1
#     cnt_X(tok) = count of tok in multiset X
#
# Example: "Lesson 01" vs "Lesson 01 - jtag":
#
#   A = ["lesson","01"]           B = ["lesson","01","jtag"]
#
#                A n B = ["lesson","01"]
#
#   W1 = 1(lesson)*1 + 2(01)*1               = 3
#   W2 = 1(lesson)*1 + 2(01)*1 + 1(jtag)*1   = 4
#   O  = 1(lesson)*min(1,1) + 2(01)*min(1,1) = 3
#
#          Dice(A,B) = 2 * O / (W1 + W2)
#      =>  Dice = 2 * 3 / (3+4) = 6/7 = 0.857 (well above 0.3)
#
#
# The problem with Dice alone - it ignores order of tokens.
# We need to take order into account, and create a combined score (Dice, LCS)
#
# Minimum combined score for a match to be accepted.
MIN_SCORE = 0.30


def tokenize(text: str) -> list[str]:
    """Split text into lower-case alphanumeric tokens on any non-alphanumeric
    boundary.  Ignores empty fragments."""
    tokens = re.split(r'[^a-zA-Z0-9]+', text)
    return [t.lower() for t in tokens if t]


def _is_numeric(t: str) -> bool:
    """Return True if the token looks like a number (possibly with leading
    zeros).  Lesson numbers (01, 02, 101 etc.) are the key identity
    markers in filenames, so we give them double weight."""
    t_clean = t.lower()
    if t_clean.startswith('s') and 'e' in t_clean:
        return True
    if 'x' in t_clean:
        return True
    return t.replace('.', '').isdigit()


def lcs_length(t1: list[str], t2: list[str]) -> int:
    """Return length of the longest common subsequence of two token lists.
    Uses simple dynamic programming - fine for short filenames."""
    n, m = len(t1), len(t2)
    if n == 0 or m == 0:
        return 0
    # Space-optimized version (filenames are short)
    prev = [0] * (m + 1)
    curr = [0] * (m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if t1[i-1] == t2[j-1]:
                curr[j] = prev[j-1] + 1
            else:
                curr[j] = max(prev[j], curr[j-1])
        prev, curr = curr, prev
    return prev[m]


def dice_coefficient(t1: list[str], t2: list[str]) -> float:
    """Sorensen–Dice coefficient, weighted so numeric tokens (likely lesson
    numbers) count double.  Returns a float in [0.0, 1.0].

    Example with "Lesson 01" vs "Lesson 01 - jtag":
      t1=["lesson","01"], t2=["lesson","01","jtag"]
      w1 = 1(lesson) + 2(01) = 3
      w2 = 1(lesson) + 2(01) + 1(jtag) = 4
      overlap = min(1,1)*1(lesson) + min(1,1)*2(01) = 3
      dice = 2*3/(3+4) = 0.857
    """
    from collections import Counter
    c1, c2 = Counter(t1), Counter(t2)
    w1 = sum(2 if _is_numeric(t) else 1 for t in t1)
    w2 = sum(2 if _is_numeric(t) else 1 for t in t2)
    if not w1 or not w2:
        return 0.0
    overlap_weight = 0
    common = set(c1) & set(c2)
    for tok in common:
        w_tok = 2 if _is_numeric(tok) else 1
        overlap_weight += w_tok * min(c1[tok], c2[tok])
    return 2.0 * overlap_weight / (w1 + w2)


def combined_score(t1: list[str], t2: list[str]) -> float:
    """Combined similarity score using Dice + LCS.

    score = alpha * dice + (1-alpha) * lcs_normalized
    """
    ALPHA = 0.6  # weight for Dice vs LCS
    dice = dice_coefficient(t1, t2)
    lcs = lcs_length(t1, t2)
    if not t1 or not t2:
        return 0.0
    lcs_norm = 2.0 * lcs / (len(t1) + len(t2))
    return ALPHA * dice + (1 - ALPHA) * lcs_norm


def find_files(directory: str, extensions: tuple) -> list[str]:
    """Return regular files in `directory` whose lowercase name ends with any
    of the given extensions."""
    found = []
    try:
        for filename in os.listdir(directory):
            if filename.lower().endswith(extensions):
                full = os.path.join(directory, filename)
                if os.path.exists(full) and not os.path.isdir(full):
                    found.append(filename)
    except FileNotFoundError:
        print(f"[!] Error: No folder found at {directory}", file=sys.stderr)
        sys.exit(1)
    return found


def auto_sub_fixer(directory: str = '.', debug: bool = False) -> None:
    print(f"[*] Working in: {os.path.abspath(directory)}\n", file=sys.stderr)

    video_files = find_files(directory, VIDEO_EXTENSIONS)
    sub_files   = find_files(directory, SUBTITLE_EXTENSIONS)

    if not video_files:
        print("[!] No video files found.  Exiting.", file=sys.stderr)
        return
    if not sub_files:
        print("[!] No subtitle files found.  Exiting.", file=sys.stderr)
        return

    print(f"[*] Found {len(video_files)} videos and {len(sub_files)} subs.\n",
          file=sys.stderr)

    # ---- Pre-tokenize all subtitle basenames --------------------------------
    #  key = original subtitle basename, value = token list
    sub_basename_tokens = {}
    for sf in sub_files:
        bn = os.path.splitext(sf)[0]
        sub_basename_tokens[bn] = tokenize(bn)

    # ---- Match each video --------------------------------------------------
    script_path = "/dev/shm/rename.sh"
    # Clear the script file
    with open(script_path, "w"):
        pass

    used_subs = set()
    matches_found = 0

    for video_file in video_files:
        video_basename = os.path.splitext(video_file)[0]
        video_tokens   = tokenize(video_basename)

        best_bn  = None        # subtitle basename that won
        best_sf  = None        # original subtitle filename
        best_score = MIN_SCORE - 0.001   # start below threshold

        for sf in sub_files:
            bn = os.path.splitext(sf)[0]
            # Skip already-used subtitles
            if bn in used_subs:
                continue

            tokens = sub_basename_tokens[bn]
            score  = combined_score(video_tokens, tokens)
            if score > best_score:
                best_score = score
                best_bn    = bn
                best_sf    = sf

        if best_sf is None or best_score < MIN_SCORE:
            print(f"[!] Video '{video_file}' — no matching sub within "
                  f"threshold ({best_score:.2f} < {MIN_SCORE}).", file=sys.stderr)
            continue

        # Debug: show all candidate scores
        if debug:
            print(f"    Video: {video_file}", file=sys.stderr)
            for sf in sub_files:
                bn = os.path.splitext(sf)[0]
                if bn in used_subs:
                    continue
                tokens = sub_basename_tokens[bn]
                d = dice_coefficient(video_tokens, tokens)
                l = lcs_length(video_tokens, tokens)
                lnorm = 2.0*l/(len(video_tokens)+len(tokens)) if (len(video_tokens)+len(tokens)) > 0 else 0
                c = combined_score(video_tokens, tokens)
                print(f"      sub={sf:45s} dice={d:.3f} lcs={lnorm:.3f} comb={c:.3f}", file=sys.stderr)
            print(f"    -> Best: {best_sf} (comb={best_score:.3f})\n", file=sys.stderr)

        original_sub_ext = os.path.splitext(best_sf)[1]
        target_name = video_basename + original_sub_ext

        if best_sf == target_name:
            print(f"[*] Video '{video_file}' — sub already in place.",
                  file=sys.stderr)
        else:
            print(f"[*] Video '{video_file}' matches '{best_sf}' (comb={best_score:.3f})",
                  file=sys.stderr)
            with open(script_path, "a") as out:
                out.write(f"mv -iv \"{best_sf}\" \"{target_name}\"\n")
            matches_found += 1

        # Mark used so the same sub isn't re-assigned to a different video
        used_subs.add(best_bn)

    # ---- Final report ------------------------------------------------------
    if matches_found == 0:
        print(f"\n[!] No subtitle renames needed.\n", file=sys.stderr)
        if os.path.exists(script_path):
            os.unlink(script_path)
    else:
        print(f"\n[*] {matches_found} rename(s) written to {script_path}.\n",
              file=sys.stderr)
        print("Run:\n\t. /dev/shm/rename.sh", file=sys.stderr)


if __name__ == "__main__":
    debug = '--debug' in sys.argv or '-d' in sys.argv
    if debug:
        sys.argv = [a for a in sys.argv if a not in ('--debug', '-d')]
    if len(sys.argv) == 2:
        auto_sub_fixer(sys.argv[1], debug=debug)
    elif len(sys.argv) == 1:
        auto_sub_fixer('.', debug=debug)
    else:
        print("Usage:")
        print(f"\t{sys.argv[0]} folder [--debug]")
        print("\n...or work on current folder:\n")
        print(f"\t{sys.argv[0]} [--debug]")
