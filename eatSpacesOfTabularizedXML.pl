#!/usr/bin/perl -w
use strict;

while(<>) {
    s,(\w+)(\s*) =\s*(["'])((?:(?!\3).)*)\3,$1$2=$3$4$3,g;
    print;
}
