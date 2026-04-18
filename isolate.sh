#!/usr/bin/env bash
#
# Uses firejail to network-isolate applications.
#
# IMPORTANT: This script provides NETWORK isolation only.
# The sandboxed app can still read/write your home directory,
# SSH keys, GPG keys, and all files accessible to your user.
# Use firejail profiles (--profile=) if you also need filesystem isolation.
#
# If your kernel supports unprivileged user namespaces (default for most kernels as of 2026),
# then this will allow simple (non-root) users to completely isolate their app.
#
# It also allows selective servers to pass through; but for that to work, firejail config
# at /etc/firejail/firejail.config must change the default for restricted-network to: no
#
#    $ grep -v ^# /etc/firejail/firejail.config
#    restricted-network no
#
# Since firejail will keep the namespace open until all binaries inside die, the script
# runs your app from a "superscript"; that kills everything in the process namespace after
# your app dies.
#
set -Eeuo pipefail

usage() {
    cat >&2 <<'EOF'
Usage:
  isolate.sh [--servers FILE] [--iface IFACE] [--dns IP[,IP...]] [--] app [args...]

Examples:
  isolate.sh vim src/renderer.cc
  isolate.sh --servers list_of_servers.txt -- vim src/renderer.cc
  isolate.sh --servers=list_of_servers.txt --dns=1.1.1.1,9.9.9.9 -- curl https://example.com/

Behavior:
  - Without --servers:
      run app with localhost only
  - With --servers:
      allow loopback plus only the listed remote IPs/CIDRs/hostnames
      optionally restricted by port

Servers file format:
  One entry per line. Blank lines and # comments are ignored.

  Accepted forms:
    203.0.113.10
    203.0.113.10:443
    203.0.113.0/24
    203.0.113.0/24:443
    2001:db8::10
    2001:db8:abcd::/48
    [2001:db8::10]:443
    example.com
    example.com:443

Notes:
  - Hostnames are resolved before entering the sandbox.
  - Port is optional. If omitted, all ports to that destination are allowed.
  - If the app itself needs DNS at runtime, pass resolver IPs with --dns.

WARNING: Only network traffic is isolated. The sandboxed process retains full
  filesystem access as your user. Do not rely on this script to protect sensitive
  files from a malicious application.
EOF
    exit 2
}

die() {
    echo "error: $*" >&2
    exit 1
}

have_cmd() {
    command -v "$1" >/dev/null 2>&1
}

trim() {
    local s="$1"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "$s"
}

# : Validate interface name against kernel naming rules
validate_iface() {
    local iface="$1"
    # Linux interface names: max 15 chars, alphanumeric plus . _ -
    [[ "$iface" =~ ^[A-Za-z0-9._-]{1,15}$ ]] || \
        die "invalid interface name: '$iface' (must match [A-Za-z0-9._-], max 15 chars)"
}

detect_default_iface() {
    local iface
    iface="$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')"
    [[ -n "${iface:-}" ]] || die "could not detect default network interface; pass --iface"
    validate_iface "$iface"
    printf '%s\n' "$iface"
}

is_ipv4_cidr() {
    [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$ ]]
}

# RFC-4291 IPv6 regex
is_ipv6_cidr() {
    local addr="$1"
    # Strip optional prefix length (e.g. /48)
    local bare="${addr%/*}"
    # Must contain at least one colon and consist only of hex digits and colons
    # Allows compressed notation (::) and full 8-group notation
    [[ "$bare" =~ ^[0-9A-Fa-f:]+$ && "$bare" == *:* ]]
}

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

# : Validate that resolved addresses are actually IPs before writing rules
validate_and_add_destination() {
    local addr="$1" port="${2:-}"
    if is_ipv4_cidr "$addr"; then
        append_v4_rule "$addr" "$port"
    elif is_ipv6_cidr "$addr"; then
        append_v6_rule "$addr" "$port"
    else
        die "resolved address is not a valid IP: '$addr'"
    fi
}

resolve_hostname() {
    local host="$1"
    local out
    local -a addrs=()

    if out="$(getent ahostsv4 "$host" 2>/dev/null)"; then
        while read -r ip _; do
            [[ -n "${ip:-}" ]] || continue
            addrs+=("$ip")
        done <<< "$out"
    fi

    if out="$(getent ahostsv6 "$host" 2>/dev/null)"; then
        while read -r ip _; do
            [[ -n "${ip:-}" ]] || continue
            addrs+=("$ip")
        done <<< "$out"
    fi

    if [[ ${#addrs[@]} -eq 0 ]]; then
        die "failed to resolve hostname: $host"
    fi

    printf '%s\n' "${addrs[@]}" | awk '!seen[$0]++'
}

parse_server_line() {
    local line="$1"
    local target=""
    local port=""
    local resolved

    if [[ "$line" =~ ^\[([0-9A-Fa-f:]+)\]:([0-9]{1,5})$ ]]; then
        target="${BASH_REMATCH[1]}"
        port="${BASH_REMATCH[2]}"
    elif [[ "$line" =~ ^(([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?)(:([0-9]{1,5}))?$ ]]; then
        target="${BASH_REMATCH[1]}"
        port="${BASH_REMATCH[5]:-}"
    elif [[ "$line" =~ ^([A-Za-z0-9._-]+):([0-9]{1,5})$ ]]; then
        target="${BASH_REMATCH[1]}"
        port="${BASH_REMATCH[2]}"
    else
        target="$line"
        port=""
    fi

    if [[ -n "$port" ]]; then
        [[ "$port" =~ ^[0-9]{1,5}$ ]] || die "invalid port in entry: '$line'"
        (( port >= 1 && port <= 65535 )) || die "port out of range in entry: '$line'"
    fi

    if is_ipv4_cidr "$target" || is_ipv6_cidr "$target"; then
        validate_and_add_destination "$target" "$port"
        return
    fi

    while IFS= read -r resolved; do
        [[ -n "$resolved" ]] || continue
        validate_and_add_destination "$resolved" "$port"
    done < <(resolve_hostname "$target")
}

SERVERS_FILE=""
IFACE=""
DNS_CSV=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --servers)
            [[ $# -ge 2 ]] || usage
            SERVERS_FILE="$2"
            shift 2
            ;;
        --servers=*)
            SERVERS_FILE="${1#*=}"
            shift
            ;;
        --iface)
            [[ $# -ge 2 ]] || usage
            IFACE="$2"
            shift 2
            ;;
        --iface=*)
            IFACE="${1#*=}"
            shift
            ;;
        --dns)
            [[ $# -ge 2 ]] || usage
            DNS_CSV="$2"
            shift 2
            ;;
        --dns=*)
            DNS_CSV="${1#*=}"
            shift
            ;;
        --help|-h)
            usage
            ;;
        --)
            shift
            break
            ;;
        -*)
            die "unknown option: $1"
            ;;
        *)
            break
            ;;
    esac
done

[[ $# -ge 1 ]] || usage

have_cmd firejail || die "firejail not found"
have_cmd ip       || die "'ip' command not found"
have_cmd getent   || die "'getent' not found"

if [[ -n "$IFACE" ]]; then
    validate_iface "$IFACE"
fi

APP=( "$@" )

_ISOLATE_PID=$$
_ISOLATE_PPID=$PPID

INNER_SCRIPT='
set +e
"$@"
rc=$?

for round in TERM KILL; do
    for proc in /proc/[0-9]*; do
        pid=${proc#/proc/}
        pid=${pid%%/*}
        case "$pid" in
            ""|1|"$_ISOLATE_PID"|"$_ISOLATE_PPID") continue ;;
        esac
        kill -s "$round" "$pid" 2>/dev/null || true
    done
    [ "$round" = TERM ] && sleep 0.2
done

exit "$rc"
'

run_firejail() {
    exec firejail "$@" -- \
        env _ISOLATE_PID="$_ISOLATE_PID" _ISOLATE_PPID="$_ISOLATE_PPID" \
        bash -c "$INNER_SCRIPT" isolate-inner "${APP[@]}"
}

if [[ -z "$SERVERS_FILE" ]]; then
    run_firejail --quiet --noprofile --net=none
fi

[[ -r "$SERVERS_FILE" ]] || die "cannot read servers file: $SERVERS_FILE"

if [[ -z "$IFACE" ]]; then
    IFACE="$(detect_default_iface)"
fi

# Validate XDG_RUNTIME_DIR before using it as a tempdir parent.
# It must be an absolute path owned by the current user;
# fall back to /tmp otherwise.
_safe_tmpdir() {
    local candidate="${XDG_RUNTIME_DIR:-}"
    if [[ -n "$candidate" && "$candidate" == /* ]]; then
        local owner
        owner="$(stat -c '%u' "$candidate" 2>/dev/null || echo "")"
        if [[ "$owner" == "$(id -u)" ]]; then
            printf '%s' "$candidate"
            return
        fi
    fi
    printf '/tmp'
}

TMPDIR_PARENT="$(_safe_tmpdir)"
WORKDIR="$(mktemp -d "$TMPDIR_PARENT/isolate-firejail.XXXXXX")"
NFT4="$WORKDIR/allowlist.net"
NFT6="$WORKDIR/allowlist6.net"

cleanup() {
    rm -rf "$WORKDIR"
}
trap cleanup EXIT

cat > "$NFT4" <<'EOF'
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT DROP [0:0]
-A INPUT -i lo -j ACCEPT
-A OUTPUT -o lo -j ACCEPT
-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
-A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
EOF

cat > "$NFT6" <<'EOF'
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT DROP [0:0]
-A INPUT -i lo -j ACCEPT
-A OUTPUT -o lo -j ACCEPT
-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
-A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
EOF

if [[ -n "$DNS_CSV" ]]; then
    IFS=',' read -r -a DNS_ARR <<< "$DNS_CSV"
    for dns in "${DNS_ARR[@]}"; do
        dns="$(trim "$dns")"
        [[ -n "$dns" ]] || continue
        if is_ipv4_cidr "$dns"; then
            printf -- "-A OUTPUT -p udp -d %s --dport 53 -j ACCEPT\n" "$dns" >> "$NFT4"
            printf -- "-A OUTPUT -p tcp -d %s --dport 53 -j ACCEPT\n" "$dns" >> "$NFT4"
        elif is_ipv6_cidr "$dns"; then
            printf -- "-A OUTPUT -p udp -d %s --dport 53 -j ACCEPT\n" "$dns" >> "$NFT6"
            printf -- "-A OUTPUT -p tcp -d %s --dport 53 -j ACCEPT\n" "$dns" >> "$NFT6"
        else
            die "invalid DNS IP: $dns"
        fi
    done
fi

while IFS= read -r raw || [[ -n "$raw" ]]; do
    line="${raw%%#*}"
    line="$(trim "$line")"
    [[ -n "$line" ]] || continue
    parse_server_line "$line"
done < "$SERVERS_FILE"

printf 'COMMIT\n' >> "$NFT4"
printf 'COMMIT\n' >> "$NFT6"

FJ_ARGS=(
    --quiet
    --noprofile
)

if [[ -n "$DNS_CSV" ]]; then
    IFS=',' read -r -a DNS_ARR <<< "$DNS_CSV"
    for dns in "${DNS_ARR[@]}"; do
        dns="$(trim "$dns")"
        [[ -n "$dns" ]] || continue
        FJ_ARGS+=(--dns="$dns")
    done
fi

FJ_ARGS+=(
    --net="$IFACE"
    --netfilter="$NFT4"
    --netfilter6="$NFT6"
)

run_firejail "${FJ_ARGS[@]}"
