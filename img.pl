#!/usr/bin/perl -w
use strict;
while(<>) {
    my $line=$_;
    while($line =~ /^.*?src\s*=\s*(['"])([^\1]*?)\1(.*$)/i) {
	print $2."\n";
	$line = $3;
    }
}
