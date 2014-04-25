#!/bin/bash
#pdftotext "$1" /dev/stdout | grep '' | wc -l
pdfinfo "$1" | grep ^Pages
