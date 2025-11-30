#!/usr/bin/perl -w
#
# So you want to subtract a list of strings from another one?
# (ignoring order, etc) - use this little script.
#
use strict;
use Getopt::Std;

my %opts;
getopts('s', \%opts);

die "Usage: $0 [-s] bigSet smallSet\n" unless @ARGV == 2;

my %a;
open DATA1, $ARGV[0] or die "Cannot open $ARGV[0]: $!\n";
while(<DATA1>) {
        chomp;
        $a{$_}=1;
}
close DATA1;

open DATA2, $ARGV[1] or die "Cannot open $ARGV[1]: $!\n";
while(<DATA2>) {
        chomp;
        delete $a{$_};
}
close DATA2;

my @keys = $opts{s} ? sort keys %a : keys %a;
foreach my $key (@keys) {
        print $key."\n";
}
