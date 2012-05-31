#!/usr/bin/perl
# debhelper sequence file for dh_modaliases

use warnings;
use strict;
use Debian::Debhelper::Dh_Lib;

insert_after("dh_install", "dh_modaliases");

1;

