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
            try:
                with open(os.path.join(path, 'modalias')) as f:
                    modalias = f.read().strip()
            except IOError as e:
                logging.warning('system_modaliases(): Cannot read %s/modalias: %s',
                        path, e)
                continue

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
            #logging.debug('system_modaliases(): ignoring device %s which has no module (built into kernel)', path)
            continue

        aliases.add(modalias)

    # Convert result to a list, to make the result compatible with a PackageKit
    # WhatProvides() call.
    return list(aliases)

def _check_video_abi_compat(apt_cache, record):
    xorg_video_abi = None

    # determine current X.org video driver ABI
    try:
        for p in apt_cache['xserver-xorg-core'].candidate.provides:
            if p.startswith('xorg-video-abi-'):
                xorg_video_abi = p
                #logging.debug('_check_video_abi_compat(): Current X.org video abi: %s', xorg_video_abi)
                break
    except (AttributeError, KeyError):
        logging.debug('_check_video_abi_compat(): xserver-xorg-core not available, cannot check ABI')
        return True
    if not xorg_video_abi:
        return False

    try:
        deps = record['Depends']
    except KeyError:
        return True
    try:
        i = deps.index('xorg-video-abi-')
    except ValueError:
        # no video driver package
        return True
    if not deps[i:].startswith(xorg_video_abi):
        logging.debug('Driver package %s is incompatible with current X.org server ABI %s', 
                record['Package'], xorg_video_abi)
        return False

    # Current X.org/nvidia proprietary drivers do not work on hybrid
    # Intel/NVidia systems; disable the driver for now
    if 'nvidia' in record['Package']:
        xorg_log = os.environ.get('UBUNTU_DRIVERS_XORG_LOG', '/var/log/Xorg.0.log')
        try:
            with open(xorg_log) as f:
                if 'drivers/intel_drv.so' in f.read():
                    logging.debug('X.org log reports loaded intel driver, disabling driver %s for hybrid system', 
                            record['Package'])
                    return False
        except IOError:
            logging.debug('Cannot open X.org log %s, cannot determine hybrid state', xorg_log)

    return True

def _apt_cache_modalias_map(apt_cache):
    '''Build a modalias map from an apt.Cache object.

    This filters out uninstallable video drivers (i. e. which depend on a video
    ABI that xserver-xorg-core does not provide).

    Return a map bus -> modalias -> [package, ...], where "bus" is the prefix of
    the modalias up to the first ':' (e. g. "pci" or "usb").
    '''
    result = {}
    for package in apt_cache:
        # skip foreign architectures, we usually only want native
        # driver packages
        if (not package.candidate or
            package.candidate.architecture not in ('all', system_architecture)):
            continue

        # skip packages without a modalias field
        try:
            m = package.candidate.record['Modaliases']
        except (KeyError, AttributeError):
            continue

        # skip incompatible video drivers
        if not _check_video_abi_compat(apt_cache, package.candidate.record):
            continue

        try:
            for part in m.split(')'):
                part = part.strip(', ')
                if not part:
                    continue
                module, lst = part.split('(')
                for alias in lst.split(','):
                    alias = alias.strip()
                    bus = alias.split(':', 1)[0]
                    result.setdefault(bus, {}).setdefault(alias, set()).add(package.name)
        except ValueError:
            logging.error('Package %s has invalid modalias header: %s' % (
                package.name, m))

    return result

def packages_for_modalias(apt_cache, modalias):
    '''Search packages which match the given modalias.
    
    Return a list of apt.Package objects.
    '''
    pkgs = set()

    apt_cache_hash = hash(apt_cache)
    try:
        cache_map = packages_for_modalias.cache_maps[apt_cache_hash]
    except KeyError:
        cache_map = _apt_cache_modalias_map(apt_cache)
        packages_for_modalias.cache_maps[apt_cache_hash] = cache_map

    bus_map = cache_map.get(modalias.split(':', 1)[0], {})
    for alias in bus_map:
        if fnmatch.fnmatch(modalias, alias):
            for p in bus_map[alias]:
                pkgs.add(p)

    return [apt_cache[p] for p in pkgs]

packages_for_modalias.cache_maps = {}

def system_driver_packages(apt_cache=None):
    '''Get driver packages that are available for the system.
    
    This calls system_modaliases() to determine the system's hardware and then
    queries apt about which packages provide drivers for those. It also adds
    available packages from detect_plugin_packages().

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
    
    # add available packages which need custom detection code
    packages.extend(detect_plugin_packages(apt_cache))

    return packages

def auto_install_filter(packages):
    '''Get packages which are appropriate for automatic installation.

    Return the subset of the given list of packages which are appropriate for
    automatic installation by the installer. This applies to e. g. the Broadcom
    Wifi driver (as there is no alternative), but not to the FGLRX proprietary
    graphics driver (as the free driver works well and FGLRX does not provide
    KMS).
    '''
    # any package which matches any of those globs will be accepted
    whitelist = ['bcmwl*', 'pvr-omap*', 'virtualbox-guest*', 'nvidia-*']
    result = []
    for pattern in whitelist:
        result.extend(fnmatch.filter(packages, pattern))
    return result

def detect_plugin_packages(apt_cache=None):
    '''Get driver packages from custom detection plugins.

    Some driver packages cannot be identified by modaliases, but need some
    custom code for determining whether they apply to the system. Read all *.py
    files in /usr/share/ubuntu-drivers-common/detect/ or
    $UBUNTU_DRIVERS_DETECT_DIR and call detect(apt_cache) on them. Filter the
    returned lists for packages which are available for installation, and
    return the joined results.

    If you already have an existing apt.Cache() object, you can pass it as an
    argument for efficiency.
    '''
    plugindir = os.environ.get('UBUNTU_DRIVERS_DETECT_DIR',
            '/usr/share/ubuntu-drivers-common/detect/')
    if not os.path.isdir(plugindir):
        logging.debug('Custom detection plugin directory %s does not exist', plugindir)
        return []

    packages = []

    if apt_cache is None:
        apt_cache = apt.Cache()

    for f in os.listdir(plugindir):
        if not f.endswith('.py'):
            continue
        plugin = os.path.join(plugindir, f)
        logging.debug('Loading custom detection plugin %s', plugin)

        symb = {}
        with open(plugin) as f:
            try:
                exec(compile(f.read(), plugin, 'exec'), symb)
                result = symb['detect'](apt_cache)
                logging.debug('plugin %s return value: %s', plugin, result)
            except Exception as e:
                logging.exception('plugin %s failed:', plugin)
                continue

            if result is None:
                continue
            if type(result) not in (list, set):
                logging.error('plugin %s returned a bad type %s (must be list or set)', plugin, type(result))
                continue

            for pkg in result:
                if pkg in apt_cache and apt_cache[pkg].candidate:
                    if _check_video_abi_compat(apt_cache, apt_cache[pkg].candidate.record):
                        packages.append(pkg)
                else:
                    logging.debug('Ignoring unavailable package %s from plugin %s', pkg, plugin)

    return packages

