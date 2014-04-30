#!/bin/bash
#
# Ignores both casing and whitespace (used by git and svn)
diff -u -i -b "$@"
