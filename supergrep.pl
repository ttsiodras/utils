#!/usr/bin/perl

use Getopt::Long;
use FileHandle;
STDOUT->autoflush;
STDERR->autoflush;

GetOptions (
   'n' => \$n,
   'v' => \$v,
   'i' => \$i
);

my $searchfor = shift;
while (<>) {
    $line_number++;
    if ($i) {
	if ($v) {
	    next unless !(/$searchfor/i);
	} else {
	    next unless (/$searchfor/i);
	}
    } else {
	if ($v) {
	    next unless !(/$searchfor/);
	} else {
	    next unless (/$searchfor/);
	}
    }
    $line = $_;
    if ($n) {
	print "$line_number: ";
    }
    print $line;
}
