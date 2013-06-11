#!/usr/bin/perl -w
# 
# To escape stuff I write that will end up as HTML,
# I just mark them in VIM, and :!htmlEntities.pl
#
use HTML::Entities;
while(<>) {
	print encode_entities($_);
}
