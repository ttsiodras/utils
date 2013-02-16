#!/usr/bin/perl -w
use HTML::Entities;
while(<>) {
	print encode_entities($_);
}
