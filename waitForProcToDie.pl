#!/usr/bin/perl -w
use strict;

#
# When I want to wait for a process to die, and then execute
# something, I use this script - e.g.
#
#    $ waitForProcToDie.pl wget ; sudo /sbin/poweroff
#

die "Usage: $0 pattern\n" unless @ARGV == 1;
my $pattern=$ARGV[0];
while(1) {
    my $found = 0;
    open DATA, "ps -ef | grep -v grep |";
    while (<DATA>) {
	if (/perl.*$pattern/) {
	    next;
	} elsif (/$pattern/) {
	    $found = 1;
	    last;
	}
    }
    close DATA;
    if ($found eq 0) {
	system("mplayer /usr/local/src/ttsiod/dev/perl/gong.wav");
	last;
    }
    sleep(10);
}
