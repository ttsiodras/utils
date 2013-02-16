#!/bin/sh
find . -depth -type d -exec rmdir '{}' ';'
