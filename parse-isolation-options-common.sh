# shellcheck source=parse-isolation-options-common.sh
# Shared isolate.sh argument parser.
#
# Requires the caller to define:
#   die()    - print error and exit
#   usage()  - print usage and exit
#
# Populates (in the caller's scope):
#   IFACE, DNS_CSV, PRIVATE_DEV,
#   SERVERS_FILES, RW_PATHS, HIDE_PATHS,
#   APP (remaining non-option arguments)

# Guard against direct execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "error: ${BASH_SOURCE[0]} must be sourced, not executed" >&2
    exit 1
fi

IFACE=""
DNS_CSV=""
PRIVATE_DEV=1
SERVERS_FILES=()
RW_PATHS=()
HIDE_PATHS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --servers)   [[ $# -ge 2 ]] || usage; SERVERS_FILES+=("$2"); shift 2 ;;
        --servers=*) SERVERS_FILES+=("${1#*=}"); shift ;;
        --iface)     [[ $# -ge 2 ]] || usage; IFACE="$2"; shift 2 ;;
        --iface=*)   IFACE="${1#*=}"; shift ;;
        --dns)       [[ $# -ge 2 ]] || usage; DNS_CSV="$2"; shift 2 ;;
        --dns=*)     DNS_CSV="${1#*=}"; shift ;;
        --rw)        [[ $# -ge 2 ]] || usage; RW_PATHS+=("$2"); shift 2 ;;
        --rw=*)      RW_PATHS+=("${1#*=}"); shift ;;
        --hide)      [[ $# -ge 2 ]] || usage; HIDE_PATHS+=("$2"); shift 2 ;;
        --hide=*)    HIDE_PATHS+=("${1#*=}"); shift ;;
        --host-dev)  PRIVATE_DEV=0; shift ;;
        --help|-h)   usage ;;
        --)          shift; break ;;
        -*)          die "unknown option: $1" ;;
        *)           break ;;
    esac
done

APP=("$@")
