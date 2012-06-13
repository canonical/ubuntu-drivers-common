'''PackageKit WhatProvides() plugin for type MODALIAS and HARDWARE_DRIVER

With this you can ask PackageKit about "which package do I need to install to
provide a driver for the device pci:v00001234...?" (MODALIAS), or "which
driver packages apply to the current system?" (HARDWARE_DRIVER), for example:

 $ pkcon what-provides "pci:v000010DEd000007E3sv00sd00bc03sc00i00"
 Available     nvidia-current-295.49-0ubuntu1.amd64        NVIDIA binary Xorg driver, kernel module and VDPAU library
 Available     nvidia-current-updates-295.49-0ubuntu1.amd64    NVIDIA binary Xorg driver, kernel module and VDPAU library

 $ pkcon what-provides "drivers_for_attached_hardware"
 Available      open-vm-dkms-2011.12.20-562307-0ubuntu1.all     Source for VMware guest systems driver (DKMS)
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

import re

try:
    from packagekit import enums
except ImportError:
    # try the one from aptdaemon
    import aptdaemon.pkenums as enums
from gi.repository import PackageKitGlib

import UbuntuDrivers.detect

valid_modalias_re = re.compile('^[a-z0-9]+:')

def what_provides(apt_cache, provides_type, search):
    '''WhatProvides plugin for type MODALIAS and HARDWARE_DRIVER

    MODALIAS: Get driver packages which match the given modalias in the search.

    HARDWARE_DRIVER: Get driver packages that are available for the system. The
    only allowed search query for this is "drivers_for_attached_hardware".
    '''
    if provides_type not in (enums.PROVIDES_MODALIAS,
            enums.PROVIDES_HARDWARE_DRIVER, enums.PROVIDES_ANY):
        raise NotImplementedError('cannot handle type ' + str(provides_type))

    # MODALIAS
    if provides_type in (enums.PROVIDES_MODALIAS, enums.PROVIDES_ANY) and \
       valid_modalias_re.match(search):
        return UbuntuDrivers.detect.packages_for_modalias(apt_cache, search)

    # HARDWARE_DRIVER
    if provides_type in (enums.PROVIDES_HARDWARE_DRIVER, enums.PROVIDES_ANY) and \
       search == 'drivers_for_attached_hardware':
        pkgs = UbuntuDrivers.detect.system_driver_packages(apt_cache)
        return [apt_cache[p] for p in pkgs]

    if provides_type == enums.PROVIDES_ANY:
        return []
    else:
        raise ValueError('The search term is invalid: %s' % search)
