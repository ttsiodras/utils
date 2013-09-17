#!/usr/bin/perl -w
#
# If you are downloading a file via youtube-dl or FTP or SCP or
# any other fancy protocol, this script can ack as a progress
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
    print sprintf("Size: %12u bytes,    speed: %12u bytes/sec    (avg: %12u bytes/sec)\n", -s $ARGV[0], $newSize-$oldSize, int($total/$cnt));
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
