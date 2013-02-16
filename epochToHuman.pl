#!/usr/bin/perl -w
use strict;

die "Usage: $0  epoch\n" unless @ARGV == 1;
use Time::localtime;
my $tm = localtime($ARGV[0]);
printf("Dateline: %02d:%02d:%02d-%04d/%02d/%02d\n",
    $tm->hour, $tm->min, $tm->sec, $tm->year+1900,
    $tm->mon+1, $tm->mday);
