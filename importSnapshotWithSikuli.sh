#!/bin/sh
echo 'import shutil ; shutil.copy(Screen().capture(), "/var/tmp/snap.png")' | java -jar /opt/Sikuli/Sikuli-IDE/sikuli-script.jar  -i
