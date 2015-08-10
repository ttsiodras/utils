#!/usr/bin/perl -w
#
# If you are downloading a file via youtube-dl or FTP or SCP or
# any other fancy protocol, this script can act as a progress
# and speed indicator - just 
#
#     speed.pl filename
#
# ...and you'll see.
#
use strict;

die "Usage: $0 filename\n" unless @ARGV == 1;

die "$ARGV[0] is not a file!\n" unless -f $ARGV[0];

my $oldSize = -s $ARGV[0];
my $noData = 0;
my $cnt = 0;
my $total = 0;
while (1) {
    sleep(1);
    $cnt++;
    my $newSize = -s $ARGV[0];
    $total += $newSize - $oldSize;
    print sprintf("Size: %9u KB,    speed: %9u KB/sec    (avg: %9u KB/sec)\n", ( -s $ARGV[0])/1024, ($newSize-$oldSize)/1024, int($total/$cnt/1024));
    if ($newSize == $oldSize) {
	$noData++;
	print "Stalling... Waiting for $noData seconds...\n";
	sleep($noData);
	if ($noData == 10) {
	    die "No data received for 55 seconds...\n";
	}
    } else {
	$noData = 0;
    }
    $oldSize = $newSize;
}
