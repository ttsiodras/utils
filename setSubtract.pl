#!/usr/bin/perl -w
#
# So you want to subtract a list of strings from another one?
# (ignoring order, etc) - use this little script.
#
use strict;
die "Usage: $0 bigSet smallSet\n" unless @ARGV == 2;
my %a;
open DATA1, $ARGV[0];
while(<DATA1>) {
	chomp;
	$a{$_}=1;
}
close DATA1;
open DATA2, $ARGV[1];
while(<DATA2>) {
	chomp;
	delete $a{$_};
}
foreach my $key (keys %a) {
	print $key."\n";
}
