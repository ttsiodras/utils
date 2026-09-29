#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

if [ $# -lt 1 ] || [ $# -gt 2 ] ; then
    echo "Usage: $0 ~/.pi/agent/sessions/file.jsonl [out.md]"
    exit 1
fi

if [ ! -f "$1" ] ; then
    echo "[-] no such file: $1"
    exit 1
fi

# An explicit output file means "write it out", no pager involved.
if [ $# -eq 2 ] ; then
    exec "${SCRIPT_DIR}"/pilog.py "$1" "$2"
fi

mdview() {
    if [ "$#" -ne 1 ]; then
        printf 'usage: mdview FILE.md\n' >&2
        return 2
    fi

    local html
    html=$(pandoc -f markdown -t html "$1" |
        sed 's/<table\([^>]*\)>/<table border="1"\1>/g')

    if type links >/dev/null 2>&1 || type links2 >/dev/null 2>&1 || type w3m >/dev/null 2>&1 ; then
        # links/links2 can't read stdin, so use a temp file
        local browser tmp
        type links2 >/dev/null 2>&1 && browser=links2 || type links >/dev/null 2>&1 && browser=links || browser=w3m
        tmp=$(mktemp --suffix=.html) || return 1
        printf '%s' "$html" >"$tmp"
        "$browser" "$tmp"
        rm -f "$tmp"
    else
        printf 'mdview: need links, or links2 installed\n' >&2
        return 1
    fi
}

temp_file=$(mktemp)
"${SCRIPT_DIR}"/pilog.py "$1" > "$temp_file"
rc=$?
if [ $rc -eq 0 ] ; then
    mdview "$temp_file"
    rc=$?
fi
rm -f "$temp_file"
exit $rc
