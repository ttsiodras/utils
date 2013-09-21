#!/usr/bin/env perl
use HTML::Entities;
while(<>) {
	s/%(..)/chr hex($1)/eg;
	print decode_entities($_);
}
