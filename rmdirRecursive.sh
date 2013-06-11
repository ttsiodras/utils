#!/bin/sh
# After invoking cmpDir1andDir2andRemoveIdenticalFromDir1, 
# I usually need to clean up empty folders - this is how I do it.
find . -depth -type d -exec rmdir '{}' ';'
