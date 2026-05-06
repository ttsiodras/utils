#!/bin/bash
#
# vim launcher: intercepts isolate.sh options, auto-deduces --rw paths
# from file/dir arguments, then launches the real vim under isolate.sh.
#
# Auto --rw logic for each file/dir argument passed to vim:
#   - Resolve the real path (following symlinks) -> add --rw on its parent dir
#   - If the argument itself lives in a different directory (i.e. it was a
#     symlink somewhere else), also add --rw on the symlink's own directory
#   - If the argument is a directory, add --rw on the directory itself
#   - Duplicate paths are collapsed
#
# Typical setup for a launcher of this:
#
# $ export PATH=$HOME/bin.local:$PATH
# $ cat ~/bin.local/vim
#
# #!/bin/bash
# export PATH="/usr/local/packages/node-v16.19.0-linux-x64/bin:/usr/local/packages/vim-9.1.0113/bin:$PATH"
# vimisolated.sh --host-dev --servers=<(echo internal.company.server) "$@"


export PATH="/usr/local/packages/node-v16.19.0-linux-x64/bin:$PATH"

ISOLATE="$HOME/bin/isolate.sh"

ISO_ARGS=(--rw ~/.vim/backup/ --rw ~/.vim/viminfo/ --rw /tmp/.X11-unix/ --rw "$PWD")
VIM_ARGS=()

# Split: consume known isolate.sh flags, pass everything else to vim.
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host-dev)
            ISO_ARGS+=("$1")
            shift
            ;;
        --rw|--hide|--servers|--iface|--dns)
            [[ $# -ge 2 ]] || { echo "vim-launcher: $1 requires an argument" >&2; exit 1; }
            ISO_ARGS+=("$1" "$2")
            shift 2
            ;;
        --rw=*|--hide=*|--servers=*|--iface=*|--dns=*)
            ISO_ARGS+=("$1")
            shift
            ;;
        --)
            shift
            VIM_ARGS+=("$@")
            break
            ;;
        *)
            VIM_ARGS+=("$1")
            shift
            ;;
    esac
done

# Deduplicate and accumulate --rw paths.
declare -A _rw_seen
add_rw() {
    local p="$1"
    if [[ -z "${_rw_seen[$p]+set}" ]]; then
        _rw_seen["$p"]=1
        ISO_ARGS+=(--rw "$p")
    fi
}

# Find git root starting from a given directory and walk up.
# If a .git folder is found, add its parent directory to R/W list.
add_rw_git_root() {
    local start="$1"
    local current="$start"
    while [[ "$current" != "/" ]]; do
        if [[ -d "$current/.git" ]]; then
            add_rw "$current"
            return 0
        fi
        current="$(dirname "$current")"
    done
    return 1
}

# Add git root from $PWD if found
add_rw_git_root "$PWD"

# Make a path absolute without resolving any symlinks.
abs_no_resolve() {
    local p="$1"
    if [[ "$p" == /* ]]; then
        printf '%s' "$p"
    else
        printf '%s/%s' "$PWD" "$p"
    fi
}

for arg in "${VIM_ARGS[@]+"${VIM_ARGS[@]}"}"; do
    # Skip vim options and +cmd arguments
    [[ "$arg" == -* || "$arg" == +* ]] && continue
    # Skip anything that doesn't exist on disk
    [[ -e "$arg" ]] || continue

    if [[ -d "$arg" ]]; then
        # Directory: make it writable directly
        add_rw "$(realpath "$arg")"
    else
        # File: find both where the symlink lives and where the real file is.

        # Directory containing the argument as written (no symlink resolution)
        link_dir="$(dirname "$(abs_no_resolve "$arg")")"

        # Real file after fully resolving symlinks
        real_file="$(realpath "$arg")"
        real_dir="$(dirname "$real_file")"

        # Always need the real file's directory writable (vim writes here)
        add_rw "$real_dir"

        # If the symlink lives somewhere else, need that dir writable too
        # (so vim can rewrite/rename the symlink entry if needed)
        if [[ "$link_dir" != "$real_dir" ]]; then
            add_rw "$link_dir"
        fi
    fi
done

# Pick the next `vim` on PATH that isn't this script (so a symlink named
# `vim` pointing here doesn't cause infinite recursion).
SELF="$(realpath "$0")"
REAL_VIM=""
IFS=':' read -r -a _path_dirs <<< "$PATH"
for d in "${_path_dirs[@]}"; do
    [[ -z "$d" ]] && continue
    cand="$d/vim"
    [[ -x "$cand" ]] || continue
    [[ "$(realpath "$cand")" == "$SELF" ]] && continue
    REAL_VIM="$cand"
    break
done
[[ -n "$REAL_VIM" ]] || { echo "vim-launcher: no real vim found on PATH" >&2; exit 1; }

exec "$ISOLATE" "${ISO_ARGS[@]}" -- "$REAL_VIM" "${VIM_ARGS[@]+"${VIM_ARGS[@]}"}"
