'''Hardware and driver package detection functionality for Ubuntu systems.'''

# (C) 2012 Canonical Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import logging
import fnmatch

import apt

system_architecture = apt.apt_pkg.get_architectures()[0]

def system_modaliases():
    '''Return list of modaliases present in the system.

    This ignores devices whose drivers are statically built into the kernel, as
    you cannot replace them with other driver packages anyway.

    The returned list is suitable for a PackageKit WhatProvides(MODALIAS) call.
    '''
    aliases = set()
    # $SYSFS is compatible with libudev
    sysfs_dir = os.environ.get('SYSFS', '/sys')
    for path, dirs, files in os.walk(os.path.join(sysfs_dir, 'devices')):
        modalias = None

        # most devices have modalias files
        if 'modalias' in files:
            with open(os.path.join(path, 'modalias')) as f:
                modalias = f.read().strip()
        # devices on SSB bus only mention the modalias in the uevent file (as
        # of 2.6.24)
        elif 'ssb' in path and 'uevent' in files:
            info = {}
            with open(os.path.join(path, 'uevent')) as f:
                for l in f:
                    if l.startswith('MODALIAS='):
                        modalias = l.split('=', 1)[1].strip()
                        break

        if not modalias:
            continue

        # ignore drivers which are statically built into the kernel
        driverlink =  os.path.join(path, 'driver')
        modlink = os.path.join(driverlink, 'module')
        if os.path.islink(driverlink) and not os.path.islink(modlink):
            continue

        aliases.add(modalias)

    # Convert result to a list, to make the result compatible with a PackageKit
    # WhatProvides() call.
    return list(aliases)

def packages_for_modalias(apt_cache, modalias):
    '''Search packages which match the given modalias.
    
    Return a list of apt.Package objects.
    '''
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
                    if fnmatch.fnmatch(modalias, alias):
                        result.append(package)
                        pkg_matches = True
                        break
                if pkg_matches:
                    break
        except ValueError:
            logging.error('Package %s has invalid modalias header: %s' % (
                package.name, m))

    return result

def system_driver_packages(apt_cache=None):
    '''Get driver packages that are available for the system.
    
    This calls system_modaliases() to determine the system's hardware and then
    queries apt about which packages provide drivers for those.

    If you already have an apt.Cache() object, you should pass it as an
    argument for efficiency. If not given, this function creates a temporary
    one by itself.

    Return a list of package names.
    '''
    modaliases = system_modaliases()

    if not apt_cache:
        apt_cache = apt.Cache()

    packages = []
    for alias in modaliases:
        packages.extend([p.name for p in packages_for_modalias(apt_cache, alias)])
    return packages

