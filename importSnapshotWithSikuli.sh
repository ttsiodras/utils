#!/bin/sh
# 
# Easy screenshot of a range of the screen
#
if [ $# -ne 1 ] ; then
    echo Usage: $0 /path/to/filename.png
    exit 1
fi
FILE="$1"
echo "import shutil ; shutil.copy(Screen().capture(), \"$FILE\")" | java -jar /opt/Sikuli/Sikuli-IDE/sikuli-script.jar  -i
