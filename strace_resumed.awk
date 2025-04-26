/<unfinished ...>/ {
    unfinished[$2] = $0
    next
}
/<\.\.\. .* resumed>/ {
    pid = $2
    sub(/^.*resumed>\s*/, "", $0)
    if (pid in unfinished) {
        print unfinished[pid] " resumed " $0
        delete unfinished[pid]
    } else {
        print
    }
    next
}
{ print }
