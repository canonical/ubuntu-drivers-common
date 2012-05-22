'''Hardware and driver package detection functionality for Ubuntu systems.'''

# (C) 2012 Canonical Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os

from gi.repository import PackageKitGlib

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

def system_driver_packages():
    '''Get driver packages that are available for the system.
    
    This calls system_modaliases() to determine the system's hardware and then
    queries PackageKit about which packages provide drivers for those.

    Raise a SystemError if the PackageKit query fails.

    Return a list of PackageKitGLib.Package objects.
    '''
    modaliases = system_modaliases()
    packagekit = PackageKitGlib.Client()

    res = packagekit.what_provides(PackageKitGlib.FilterEnum.NONE,
            PackageKitGlib.ProvidesEnum.MODALIAS, modaliases, None,
            lambda p, t, d: True, None)
    if res.get_exit_code() != PackageKitGlib.ExitEnum.SUCCESS:
        raise SystemError('PackageKit query failed with %s' % str(res.get_exit_code()))
    return res.get_package_array()

