#!/bin/bash
#
# I asked a question on stackoverflow about getting the currently
# executing (long!) cmdline inside a long-running screen-ed bash.
#
#   http://unix.stackexchange.com/questions/159010/how-can-i-see-the-exact-command-line-being-executed-inside-some-bash-instance#159010
#
# ...and got nowhere - the guys there gave me suggestions that simply don't work.
#
# So after a bit of hacking, I completed this script - I use GDB
# to save the bash history, and tail -1 on it :-)
#
if [ $# -ne 1 ] ; then
    echo Usage: $0 BASH_PID
    exit 1
fi
if [ ! -d /proc/$1 ] ; then
    echo There is no such PID
    exit 1
fi
if [ $(realpath /proc/$1/exe) != "/bin/bash" -a \
     $(realpath /proc/$1/exe) != "/usr/bin/bash" -a \
     $(realpath /proc/$1/exe) != "/usr/local/bin/bash" ] ; then
    echo This is not a bash PID
    exit 1
fi
gdb --pid $1 >/dev/null 2>&1 <<OEF
call write_history("/tmp/bash_history_recover")
detach
q
OEF
tail -1 /tmp/bash_history_recover
rm -f /tmp/bash_history_recover
