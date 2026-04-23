#!/usr/bin/env bash
#
# Uses firejail to sandbox applications with:
#   - Network isolation (no network, or allowlisted IPs/CIDRs/hostnames)
#   - Filesystem isolation:
#       * Everything is READABLE (no whitelist hiding)
#       * $HOME is READ-ONLY by default
#       * Only explicitly --rw paths are writable (files or directories)
#       * --hide paths are completely invisible
#       * /tmp is always private and empty
#
# Requirements:  firejail, ip, getent
#
# Kernel: unprivileged user namespaces must be enabled (default on most
#         kernels as of 2026; check /proc/sys/kernel/unprivileged_userns_clone).
#
# For network allowlisting (--servers), /etc/firejail/firejail.config must have:
#   restricted-network no
#
set -Eeuo pipefail

usage() {
    cat >&2 <<'EOF'
Usage:
  isolate.sh [OPTIONS] [--] app [args...]

Filesystem options:
  --rw PATH     Make PATH writable (file or directory). Repeatable.
                Everything else in $HOME is readable but read-only.
                /tmp is always private and empty.
  --hide PATH   Make PATH completely invisible. Repeatable.

Network options:
  --servers FILE        Allow loopback + only the listed IPs/CIDRs/hostnames.
                        Without this flag the app gets NO network at all.
  --iface IFACE         Network interface (auto-detected if omitted).
  --dns IP[,IP,...]     DNS resolvers reachable at runtime.

Examples:
  # VIM: ~/.vimrc and ~/.vim visible (ro), only listed paths writable:
  isolate.sh --rw ~/bin --rw ~/.viminfo -- vim ~/bin/pi.sh

  # Same, hide SSH keys entirely, allow one server:
  isolate.sh --rw ~/bin --rw ~/.viminfo --hide ~/.ssh \
             --servers servers.txt --dns 1.1.1.1 -- vim ~/bin/pi.sh

Servers file format:
  One entry per line. Blank lines and # comments are ignored.
  Accepted forms:
    203.0.113.10            203.0.113.10:443
    203.0.113.0/24          203.0.113.0/24:443
    2001:db8::10            2001:db8:abcd::/48
    [2001:db8::10]:443      example.com       example.com:443

Isolation model:
  $HOME is mounted read-only. --rw re-mounts specific paths read-write on
  top (works for both files and directories). Everything outside $HOME is
  accessible under normal Unix permissions. /tmp is a fresh private tmpfs.
  Network traffic is blocked unless whitelisted via --servers.
EOF
    exit 2
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die()      { echo "error: $*" >&2; exit 1; }
have_cmd() { command -v "$1" >/dev/null 2>&1; }

trim() {
    local s="$1"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "$s"
}

validate_iface() {
    [[ "$1" =~ ^[A-Za-z0-9._-]{1,15}$ ]] || die "invalid interface name: '$1'"
}

detect_default_iface() {
    local iface
    iface="$(ip route show default 2>/dev/null | awk '/default/{print $5; exit}')"
    [[ -n "${iface:-}" ]] || die "could not detect default network interface; pass --iface"
    validate_iface "$iface"
    printf '%s\n' "$iface"
}

is_ipv4_cidr() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$ ]]; }

is_ipv6_cidr() {
    local bare="${1%/*}"
    [[ "$bare" =~ ^[0-9A-Fa-f:]+$ && "$bare" == *:* ]]
}

safe_tmpdir() {
    local candidate="${XDG_RUNTIME_DIR:-}"
    if [[ -n "$candidate" && "$candidate" == /* && -d "$candidate" && -w "$candidate" ]]; then
        local owner
        owner="$(stat -c '%u' "$candidate" 2>/dev/null || echo "")"
        [[ "$owner" == "$(id -u)" ]] && printf '%s' "$candidate" && return
    fi
    printf '/tmp'
}

# ---------------------------------------------------------------------------
# iptables rule builders
# ---------------------------------------------------------------------------

append_v4_rule() {
    local addr="$1" port="${2:-}"
    if [[ -n "$port" ]]; then
        printf -- "-A OUTPUT -p tcp -d %s --dport %s -j ACCEPT\n" "$addr" "$port" >> "$NFT4"
        printf -- "-A OUTPUT -p udp -d %s --dport %s -j ACCEPT\n" "$addr" "$port" >> "$NFT4"
    else
        printf -- "-A OUTPUT -d %s -j ACCEPT\n" "$addr" >> "$NFT4"
    fi
}

append_v6_rule() {
    local addr="$1" port="${2:-}"
    if [[ -n "$port" ]]; then
        printf -- "-A OUTPUT -p tcp -d %s --dport %s -j ACCEPT\n" "$addr" "$port" >> "$NFT6"
        printf -- "-A OUTPUT -p udp -d %s --dport %s -j ACCEPT\n" "$addr" "$port" >> "$NFT6"
    else
        printf -- "-A OUTPUT -d %s -j ACCEPT\n" "$addr" >> "$NFT6"
    fi
}

validate_and_add_destination() {
    local addr="$1" port="${2:-}"
    if   is_ipv4_cidr "$addr"; then append_v4_rule "$addr" "$port"
    elif is_ipv6_cidr "$addr"; then append_v6_rule "$addr" "$port"
    else die "resolved address is not a valid IP: '$addr'"
    fi
}

resolve_hostname() {
    local host="$1" out ip
    local -a addrs=()
    if out="$(getent ahostsv4 "$host" 2>/dev/null)"; then
        while read -r ip _; do [[ -n "${ip:-}" ]] && addrs+=("$ip"); done <<< "$out"
    fi
    if out="$(getent ahostsv6 "$host" 2>/dev/null)"; then
        while read -r ip _; do [[ -n "${ip:-}" ]] && addrs+=("$ip"); done <<< "$out"
    fi
    [[ ${#addrs[@]} -gt 0 ]] || die "failed to resolve hostname: $host"
    printf '%s\n' "${addrs[@]}" | awk '!seen[$0]++'
}

parse_server_line() {
    local line="$1" target="" port="" resolved

    if   [[ "$line" =~ ^\[([0-9A-Fa-f:]+)\]:([0-9]{1,5})$ ]]; then
        target="${BASH_REMATCH[1]}"; port="${BASH_REMATCH[2]}"
    elif [[ "$line" =~ ^(([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?)(:([0-9]{1,5}))?$ ]]; then
        target="${BASH_REMATCH[1]}"; port="${BASH_REMATCH[5]:-}"
    elif [[ "$line" =~ ^([A-Za-z0-9._-]+):([0-9]{1,5})$ ]]; then
        target="${BASH_REMATCH[1]}"; port="${BASH_REMATCH[2]}"
    else
        target="$line"; port=""
    fi

    if [[ -n "$port" ]]; then
        [[ "$port" =~ ^[0-9]{1,5}$ ]]   || die "invalid port in: '$line'"
        (( port >= 1 && port <= 65535 )) || die "port out of range in: '$line'"
    fi

    if is_ipv4_cidr "$target" || is_ipv6_cidr "$target"; then
        validate_and_add_destination "$target" "$port"; return
    fi

    while IFS= read -r resolved; do
        [[ -n "$resolved" ]] && validate_and_add_destination "$resolved" "$port"
    done < <(resolve_hostname "$target")
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

SERVERS_FILE="" IFACE="" DNS_CSV=""
RW_PATHS=() HIDE_PATHS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --servers)   [[ $# -ge 2 ]] || usage; SERVERS_FILE="$2"; shift 2 ;;
        --servers=*) SERVERS_FILE="${1#*=}"; shift ;;
        --iface)     [[ $# -ge 2 ]] || usage; IFACE="$2"; shift 2 ;;
        --iface=*)   IFACE="${1#*=}"; shift ;;
        --dns)       [[ $# -ge 2 ]] || usage; DNS_CSV="$2"; shift 2 ;;
        --dns=*)     DNS_CSV="${1#*=}"; shift ;;
        --rw)        [[ $# -ge 2 ]] || usage; RW_PATHS+=("$2"); shift 2 ;;
        --rw=*)      RW_PATHS+=("${1#*=}"); shift ;;
        --hide)      [[ $# -ge 2 ]] || usage; HIDE_PATHS+=("$2"); shift 2 ;;
        --hide=*)    HIDE_PATHS+=("${1#*=}"); shift ;;
        --help|-h)   usage ;;
        --)          shift; break ;;
        -*)          die "unknown option: $1" ;;
        *)           break ;;
    esac
done

[[ $# -ge 1 ]] || usage
APP=("$@")

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------

have_cmd firejail || die "firejail not found"
have_cmd ip       || die "'ip' command not found"
have_cmd getent   || die "'getent' not found"

[[ -n "$IFACE" ]] && validate_iface "$IFACE"

# ---------------------------------------------------------------------------
# Inner script: kills sibling processes after the app exits
# ---------------------------------------------------------------------------

_ISOLATE_PID=$$
_ISOLATE_PPID=$PPID

INNER_SCRIPT='
set +e
_INNER_PID=$$
"$@"
rc=$?
for round in TERM KILL; do
    for proc in /proc/[0-9]*; do
        pid=${proc#/proc/}; pid=${pid%%/*}
        case "$pid" in
            ""|1|"$_ISOLATE_PID"|"$_ISOLATE_PPID"|"$_INNER_PID") continue ;;
        esac
        kill -s "$round" "$pid" 2>/dev/null || true
    done
    [ "$round" = TERM ] && sleep 0.2
done
exit "$rc"
'

# ---------------------------------------------------------------------------
# Working directory
# ---------------------------------------------------------------------------

WORKDIR="$(mktemp -d "$(safe_tmpdir)/isolate-firejail.XXXXXX")"
chmod 700 "$WORKDIR"
NFT4="$WORKDIR/allowlist.net"
NFT6="$WORKDIR/allowlist6.net"

cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

# Slurp process substitutions (e.g. --servers <(echo 1.1.1.1)) into a real
# file immediately, while the fd is still open in the parent shell.
if [[ -n "$SERVERS_FILE" ]]; then
    [[ -r "$SERVERS_FILE" ]] || die "cannot read servers file: $SERVERS_FILE"
    case "$SERVERS_FILE" in
        /dev/fd/*|/proc/self/fd/*|/proc/"$$"/fd/*)
            cat "$SERVERS_FILE" > "$WORKDIR/servers.txt"
            SERVERS_FILE="$WORKDIR/servers.txt" ;;
    esac
fi

# ---------------------------------------------------------------------------
# Build firejail filesystem arguments
# ---------------------------------------------------------------------------
#
# --private-dev   provides minimal /dev (null, tty, pts, random, etc.) and
#                 is required to trigger the private mount namespace that
#                 makes --read-only=$HOME actually take effect.
# --private-tmp   fresh empty /tmp; also helps anchor the private namespace.
# --read-only=$HOME   makes entire home ro as the base.
# --read-write=P  re-mounts P rw on top (works for files and directories).
# --blacklist=P   makes P completely invisible.

REAL_HOME="$(realpath "$HOME")"

FJ_FS_ARGS=(
    --private-dev
    --private-tmp
    --read-only="$REAL_HOME"
)

for p in "${RW_PATHS[@]+"${RW_PATHS[@]}"}"; do
    p="$(realpath -m "$p")"
    [[ -e "$p" ]] || die "--rw path does not exist: $p"
    FJ_FS_ARGS+=(--read-write="$p")
done

for p in "${HIDE_PATHS[@]+"${HIDE_PATHS[@]}"}"; do
    p="$(realpath -m "$p")"
    FJ_FS_ARGS+=(--blacklist="$p")
done

# ---------------------------------------------------------------------------
# Launch helper
# ---------------------------------------------------------------------------

run_firejail() {
    exec firejail \
        --quiet --noprofile \
        "${FJ_FS_ARGS[@]}" \
        "$@" \
        -- \
        env _ISOLATE_PID="$_ISOLATE_PID" _ISOLATE_PPID="$_ISOLATE_PPID" \
        bash -c "$INNER_SCRIPT" isolate-inner "${APP[@]}"
}

# ---------------------------------------------------------------------------
# Network: no-network case
# ---------------------------------------------------------------------------

if [[ -z "$SERVERS_FILE" && -z "$DNS_CSV" ]]; then
    run_firejail --net=none
fi

# ---------------------------------------------------------------------------
# Network: allowlist case
# ---------------------------------------------------------------------------

[[ -z "$IFACE" ]] && IFACE="$(detect_default_iface)"

cat > "$NFT4" <<'EOF'
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT DROP [0:0]
-A INPUT  -i lo -j ACCEPT
-A OUTPUT -o lo -j ACCEPT
-A INPUT  -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
-A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
EOF

cat > "$NFT6" <<'EOF'
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT DROP [0:0]
-A INPUT  -i lo -j ACCEPT
-A OUTPUT -o lo -j ACCEPT
-A INPUT  -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
-A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
EOF

if [[ -n "$DNS_CSV" ]]; then
    IFS=',' read -r -a DNS_ARR <<< "$DNS_CSV"
    for dns in "${DNS_ARR[@]}"; do
        dns="$(trim "$dns")"; [[ -n "$dns" ]] || continue
        if   is_ipv4_cidr "$dns"; then
            printf -- "-A OUTPUT -p udp -d %s --dport 53 -j ACCEPT\n" "$dns" >> "$NFT4"
            printf -- "-A OUTPUT -p tcp -d %s --dport 53 -j ACCEPT\n" "$dns" >> "$NFT4"
        elif is_ipv6_cidr "$dns"; then
            printf -- "-A OUTPUT -p udp -d %s --dport 53 -j ACCEPT\n" "$dns" >> "$NFT6"
            printf -- "-A OUTPUT -p tcp -d %s --dport 53 -j ACCEPT\n" "$dns" >> "$NFT6"
        else
            die "invalid DNS IP: '$dns' (must be numeric)"
        fi
    done
fi

if [[ -n "$SERVERS_FILE" ]]; then
    while IFS= read -r raw || [[ -n "$raw" ]]; do
        line="${raw%%#*}"; line="$(trim "$line")"
        [[ -n "$line" ]] && parse_server_line "$line"
    done < "$SERVERS_FILE"
fi

printf 'COMMIT\n' >> "$NFT4"
printf 'COMMIT\n' >> "$NFT6"

FJ_NET_ARGS=(--net="$IFACE" --netfilter="$NFT4" --netfilter6="$NFT6")

if [[ -n "$DNS_CSV" ]]; then
    IFS=',' read -r -a DNS_ARR <<< "$DNS_CSV"
    for dns in "${DNS_ARR[@]}"; do
        dns="$(trim "$dns")"; [[ -n "$dns" ]] && FJ_NET_ARGS+=(--dns="$dns")
    done
fi

run_firejail "${FJ_NET_ARGS[@]}"
