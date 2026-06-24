#!/usr/bin/env bash
set -u
set -o pipefail

usage() {
    cat >&2 <<'EOF'
Usage:
  timestamped_logger.sh LOGFILE -- PROGRAM [ARG...]

Example:
  timestamped_logger.sh log.txt -- /path/to/program arg1 arg2

Creates:
  LOGFILE          merged timestamped stdout/stderr log
  LOGFILE.stdout   timestamped stdout log
  LOGFILE.stderr   timestamped stderr log

Requires:
  moreutils  for ts
  expect     for unbuffer
EOF
}

die() {
    printf 'timestamped_logger.sh: %s\n' "$*" >&2
    exit 2
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

if [ "$#" -lt 3 ]; then
    usage
    exit 2
fi

logfile=$1
shift

if [ "${1-}" != "--" ]; then
    usage
    die "expected -- after logfile"
fi
shift

if [ "$#" -lt 1 ]; then
    usage
    die "missing program"
fi

need_cmd ts
need_cmd unbuffer
need_cmd tee
need_cmd sort
need_cmd mktemp

stdout_log=$logfile.stdout
stderr_log=$logfile.stderr

tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/timestamped_logger.XXXXXXXXXX") ||
    die "could not create temporary directory"

tmp_stdout=$tmpdir/stdout
tmp_stderr=$tmpdir/stderr

cleanup() {
    rm -rf "$tmpdir"
}
trap cleanup EXIT

: > "$stdout_log" || die "cannot write $stdout_log"
: > "$stderr_log" || die "cannot write $stderr_log"
: > "$logfile"    || die "cannot write $logfile"
: > "$tmp_stdout" || die "cannot write temporary stdout log"
: > "$tmp_stderr" || die "cannot write temporary stderr log"

unbuffer "$@" \
    > >(ts '%Y-%m-%d %H:%M:%S.%.S stdout' | tee "$stdout_log" "$tmp_stdout") \
    2> >(ts '%Y-%m-%d %H:%M:%S.%.S stderr' | tee "$stderr_log" "$tmp_stderr" >&2)

status=$?

wait 2>/dev/null || true

sort -s "$tmp_stdout" "$tmp_stderr" > "$logfile" ||
    die "could not write merged logfile: $logfile"

exit "$status"
