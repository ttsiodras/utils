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

export PATH="/usr/local/packages/node-v16.19.0-linux-x64/bin:$PATH"

ISOLATE="$HOME/bin/isolate.sh"

ISO_ARGS=(--rw ~/.vim/backup/ --rw ~/.vim/viminfo/ --rw /tmp/.X11-unix/ --rw "$PWD")
VIM_ARGS=()

# Split: consume known isolate.sh flags, pass everything else to vim.
while [[ $# -gt 0 ]]; do
    case "$1" in
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

exec "$ISOLATE" "${ISO_ARGS[@]}" -- /usr/bin/vim "${VIM_ARGS[@]+"${VIM_ARGS[@]}"}"
