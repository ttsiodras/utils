#!/usr/bin/perl -w
#
# After wget-ing a link, if I want to dump the image refs,
# I use this, and usually pipe it to a bash loop of wgets.
#
use strict;
while(<>) {
    my $line=$_;
    while($line =~ /^.*?src\s*=\s*(['"])([^\1]*?)\1(.*$)/i) {
	print $2."\n";
	$line = $3;
    }
}
