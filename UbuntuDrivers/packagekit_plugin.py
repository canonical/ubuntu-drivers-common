'''PackageKit plugin for WhatProvides() call for type MODALIAS

 With this you can ask PackageKit about "which package do I need to install to
 provide a driver for the device pci:v00001234...?", for example:

 $ pkcon what-provides "pci:v000010DEd000007E3sv00sd00bc03sc00i00"
 Available     nvidia-current-295.49-0ubuntu1.amd64        NVIDIA binary Xorg driver, kernel module and VDPAU library
 Available     nvidia-current-updates-295.49-0ubuntu1.amd64    NVIDIA binary Xorg driver, kernel module and VDPAU library
'''

# Note that this does not work with PackageKit's "aptcc" backend as that does
# not support plugins. You need to use PackageKit's "apt" backend or
# python-aptdaemon.pkcompat on Debian/Ubuntu (preferred).
#
# (C) 2012 Canonical Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import logging
import fnmatch
import re

from packagekit import enums
import apt

valid_modalias_re = re.compile('^[a-z0-9]+:\S+$')
system_architecture = apt.apt_pkg.get_architectures()[0]

def what_provides_modalias(apt_cache, provides_type, search):
    if provides_type not in (enums.PROVIDES_MODALIAS, enums.PROVIDES_ANY):
        raise NotImplementedError('cannot handle type ' + str(provides_type))

    if not valid_modalias_re.match(search):
        if provides_type != enums.PROVIDES_ANY:
            raise ValueError('The search term is invalid: %s' % search)
        else:
            return []

    result = []
    for package in apt_cache:
        # skip foreign architectures, we usually only want native
        # driver packages
        if (not package.candidate or
            package.candidate.architecture not in ('all', system_architecture)):
            continue

        try:
            m = package.candidate.record['Modaliases']
        except (KeyError, AttributeError):
            continue

        try:
            pkg_matches = False
            for part in m.split(')'):
                part = part.strip(', ')
                if not part:
                    continue
                module, lst = part.split('(')
                for alias in lst.split(','):
                    alias = alias.strip()
                    if fnmatch.fnmatch(search, alias):
                        result.append(package)
                        pkg_matches = True
                        break
                if pkg_matches:
                    break
        except ValueError:
            logging.error('Package %s has invalid modalias header: %s' % (
                package.name, m))

    return result
