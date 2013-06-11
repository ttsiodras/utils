#!/bin/sh
#
# To read an HTML file, I just 'c /path/to/file'
#
exec /usr/bin/google-chrome --incognito "$@"
