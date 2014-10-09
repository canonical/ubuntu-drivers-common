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
import subprocess
import functools

import apt

from UbuntuDrivers import kerneldetection

system_architecture = apt.apt_pkg.get_architectures()[0]

def system_modaliases():
    '''Get modaliases present in the system.

    This ignores devices whose drivers are statically built into the kernel, as
    you cannot replace them with other driver packages anyway.

    Return a modalias → sysfs path map. The keys of the returned map are
    suitable for a PackageKit WhatProvides(MODALIAS) call.
    '''
    aliases = {}
    for path, dirs, files in os.walk('/sys/devices'):
        modalias = None

        # most devices have modalias files
        if 'modalias' in files:
            try:
                with open(os.path.join(path, 'modalias')) as f:
                    modalias = f.read().strip()
            except IOError as e:
                logging.debug('system_modaliases(): Cannot read %s/modalias: %s',
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

        aliases[modalias] = path

    return aliases

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
    if 'xorg-video-abi-' in deps and xorg_video_abi not in deps:
        logging.debug('Driver package %s is incompatible with current X.org server ABI %s', 
                record['Package'], xorg_video_abi)
        return False
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
        except (KeyError, AttributeError, UnicodeDecodeError):
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

def _is_package_free(pkg):
    assert pkg.candidate is not None
    # it would be better to check the actual license, as we do not have
    # the component for third-party packages; but this is the best we can do
    # at the moment
    if pkg.candidate.section.startswith('restricted') or \
            pkg.candidate.section.startswith('multiverse'):
        return False
    return True

def _is_package_from_distro(pkg):
    if pkg.candidate is None:
        return False

    for o in pkg.candidate.origins:
        if o.origin == 'Ubuntu':
            return True
    return False

def _pkg_get_module(pkg):
    '''Determine module name from apt Package object'''

    try:
        m = pkg.candidate.record['Modaliases']
    except (KeyError, AttributeError):
        logging.debug('_pkg_get_module %s: package has no Modaliases header, cannot determine module', pkg.name)
        return None

    paren = m.find('(')
    if paren <= 0:
        logging.warning('_pkg_get_module %s: package has invalid Modaliases header, cannot determine module', pkg.name)
        return None

    module = m[:paren]
    return module

def _is_manual_install(pkg):
    '''Determine if the kernel module from an apt.Package is manually installed.'''

    if pkg.installed:
        return False

    # special case, as our packages suffix the kmod with _version
    if pkg.name.startswith('nvidia'):
        module = 'nvidia'
    elif pkg.name.startswith('fglrx'):
        module = 'fglrx'
    else:
        module = _pkg_get_module(pkg)

    if not module:
        return False

    modinfo = subprocess.Popen(['modinfo', module], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    modinfo.communicate()
    if modinfo.returncode == 0:
        logging.debug('_is_manual_install %s: builds module %s which is available, manual install',
                      pkg.name, module)
        return True

    logging.debug('_is_manual_install %s: builds module %s which is not available, no manual install',
                  pkg.name, module)
    return False

def _get_db_name(syspath, alias):
    '''Return (vendor, model) names for given device.

    Values are None if unknown.
    '''
    try:
        out = subprocess.check_output(['udevadm', 'hwdb', '--test=' + alias],
                                      universal_newlines=True)
    except (OSError, subprocess.CalledProcessError) as e:
        logging.debug('_get_db_name(%s, %s): udevadm hwdb failed: %s', syspath, alias, str(e))
        return (None, None)

    logging.debug('_get_db_name: output\n%s\n', out)

    vendor = None
    model = None
    for line in out.splitlines():
        (k, v) = line.split('=', 1)
        if '_VENDOR' in k:
            vendor = v
        if '_MODEL' in k:
            model = v

    logging.debug('_get_db_name(%s, %s): vendor "%s", model "%s"', syspath,
                  alias, vendor, model)
    return (vendor, model)

def system_driver_packages(apt_cache=None):
    '''Get driver packages that are available for the system.
    
    This calls system_modaliases() to determine the system's hardware and then
    queries apt about which packages provide drivers for those. It also adds
    available packages from detect_plugin_packages().

    If you already have an apt.Cache() object, you should pass it as an
    argument for efficiency. If not given, this function creates a temporary
    one by itself.

    Return a dictionary which maps package names to information about them:

      driver_package → {'modalias': 'pci:...', ...}

    Available information keys are:
      'modalias':    Modalias for the device that needs this driver (not for
                     drivers from detect plugins)
      'syspath':     sysfs directory for the device that needs this driver
                     (not for drivers from detect plugins)
      'plugin':      Name of plugin that detected this package (only for
                     drivers from detect plugins)
      'free':        Boolean flag whether driver is free, i. e. in the "main"
                     or "universe" component.
      'from_distro': Boolean flag whether the driver is shipped by the distro;
                     if not, it comes from a (potentially less tested/trusted)
                     third party source.
      'vendor':      Human readable vendor name, if available.
      'model':       Human readable product name, if available.
      'recommended': Some drivers (nvidia, fglrx) come in multiple variants and
                     versions; these have this flag, where exactly one has
                     recommended == True, and all others False.
    '''
    modaliases = system_modaliases()

    if not apt_cache:
        apt_cache = apt.Cache()

    packages = {}
    for alias, syspath in modaliases.items():
        for p in packages_for_modalias(apt_cache, alias):
            packages[p.name] = {
                    'modalias': alias,
                    'syspath': syspath,
                    'free': _is_package_free(p),
                    'from_distro': _is_package_from_distro(p),
                }
            (vendor, model) = _get_db_name(syspath, alias)
            if vendor is not None:
                packages[p.name]['vendor'] = vendor
            if model is not None:
                packages[p.name]['model'] = model

    # Add "recommended" flags for NVidia alternatives
    nvidia_packages = [p for p in packages if p.startswith('nvidia-')]
    if nvidia_packages:
        nvidia_packages.sort(key=functools.cmp_to_key(_cmp_gfx_alternatives))
        recommended = nvidia_packages[-1]
        for p in nvidia_packages:
            packages[p]['recommended'] = (p == recommended)

    # Add "recommended" flags for fglrx alternatives
    fglrx_packages = [p for p in packages if p.startswith('fglrx-')]
    if fglrx_packages:
        fglrx_packages.sort(key=functools.cmp_to_key(_cmp_gfx_alternatives))
        recommended = fglrx_packages[-1]
        for p in fglrx_packages:
            packages[p]['recommended'] = (p == recommended)

    # add available packages which need custom detection code
    for plugin, pkgs in detect_plugin_packages(apt_cache).items():
        for p in pkgs:
            apt_p = apt_cache[p]
            packages[p] = {
                    'free': _is_package_free(apt_p),
                    'from_distro': _is_package_from_distro(apt_p),
                    'plugin': plugin,
                }

    return packages

def system_device_drivers(apt_cache=None):
    '''Get by-device driver packages that are available for the system.
    
    This calls system_modaliases() to determine the system's hardware and then
    queries apt about which packages provide drivers for each of those. It also
    adds available packages from detect_plugin_packages(), using the name of
    the detction plugin as device name.

    If you already have an apt.Cache() object, you should pass it as an
    argument for efficiency. If not given, this function creates a temporary
    one by itself.

    Return a dictionary which maps devices to available drivers:

      device_name →  {'modalias': 'pci:...', <device info>, 
                      'drivers': {'pkgname': {<driver package info>}}

    A key (device name) is either the sysfs path (for drivers detected through
    modaliases) or the detect plugin name (without the full path).

    Available keys in <device info>:
      'modalias':    Modalias for the device that needs this driver (not for
                     drivers from detect plugins)
      'vendor':      Human readable vendor name, if available.
      'model':       Human readable product name, if available.
      'drivers':     Driver package map for this device, see below. Installing any
                     of the drivers in that map will make this particular
                     device work. The keys are the package names of the driver
                     packages; note that this can be an already installed
                     default package such as xserver-xorg-video-nouveau which
                     provides a free alternative to the proprietary NVidia
                     driver; these will have the 'builtin' flag set.
      'manual_install':
                     None of the driver packages are installed, but the kernel
                     module that it provides is available; this usually means
                     that the user manually installed the driver from upstream.

    Aavailable keys in <driver package info>:
      'builtin':     The package is shipped by default in Ubuntu and MUST
                     NOT be uninstalled. This usually applies to free
                     drivers like xserver-xorg-video-nouveau.
      'free':        Boolean flag whether driver is free, i. e. in the "main"
                     or "universe" component.
      'from_distro': Boolean flag whether the driver is shipped by the distro;
                     if not, it comes from a (potentially less tested/trusted)
                     third party source.
      'recommended': Some drivers (nvidia, fglrx) come in multiple variants and
                     versions; these have this flag, where exactly one has
                     recommended == True, and all others False.
    '''
    result = {}
    if not apt_cache:
        apt_cache = apt.Cache()

    # copy the system_driver_packages() structure into the by-device structure
    for pkg, pkginfo in system_driver_packages(apt_cache).items():
        if 'syspath' in pkginfo:
            device_name = pkginfo['syspath']
        else:
            device_name = pkginfo['plugin']
        result.setdefault(device_name, {})
        for opt_key in ('modalias', 'vendor', 'model'):
            if opt_key in pkginfo:
                result[device_name][opt_key] = pkginfo[opt_key]
        drivers = result[device_name].setdefault('drivers', {})
        drivers[pkg] = {'free': pkginfo['free'], 'from_distro': pkginfo['from_distro']}
        if 'recommended' in pkginfo:
            drivers[pkg]['recommended'] = pkginfo['recommended']

    # now determine the manual_install device flag: this is true iff all driver
    # packages are "manually installed"
    for driver, info in result.items():
        for pkg in info['drivers']:
            if not _is_manual_install(apt_cache[pkg]):
                break
        else:
            info['manual_install'] = True
 
    # add OS builtin free alternatives to proprietary drivers
    _add_builtins(result)
 
    return result

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
    allow = []
    for pattern in whitelist:
        allow.extend(fnmatch.filter(packages, pattern))

    result = {}
    for p in allow:
        if 'recommended' not in packages[p] or packages[p]['recommended']:
            result[p] = packages[p]
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

    Return pluginname -> [package, ...] map.
    '''
    packages = {}
    plugindir = os.environ.get('UBUNTU_DRIVERS_DETECT_DIR',
            '/usr/share/ubuntu-drivers-common/detect/')
    if not os.path.isdir(plugindir):
        logging.debug('Custom detection plugin directory %s does not exist', plugindir)
        return packages

    if apt_cache is None:
        apt_cache = apt.Cache()

    for fname in os.listdir(plugindir):
        if not fname.endswith('.py'):
            continue
        plugin = os.path.join(plugindir, fname)
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
                        packages.setdefault(fname, []).append(pkg)
                else:
                    logging.debug('Ignoring unavailable package %s from plugin %s', pkg, plugin)

    return packages

def _cmp_gfx_alternatives(x, y):
    '''Compare two graphics driver names in terms of preference.

    -updates always sort after non-updates, as we prefer the stable driver and
    only want to offer -updates when the one from release does not support the
    card. We never want to recommend -experimental unless it's the only one
    available, so sort this last.
    '''
    if x.endswith('-updates') and not y.endswith('-updates'):
        return -1
    if not x.endswith('-updates') and y.endswith('-updates'):
        return 1
    if 'experiment' in x and 'experiment' not in y:
        return -1
    if 'experiment' not in x and 'experiment' in y:
        return 1
    if x < y:
        return -1
    if x > y:
        return 1
    assert x == y
    return 0

def _add_builtins(drivers):
    '''Add builtin driver alternatives'''

    for device, info in drivers.items():
        for pkg in info['drivers']:
            # Nouveau is still not good enough, keep recommending the
            # proprietary driver
            if pkg.startswith('nvidia'):
                info['drivers']['xserver-xorg-video-nouveau'] = {
                    'free': True, 'builtin': True, 'from_distro': True, 'recommended': False}
                break

            # These days the free driver is working well enough, so recommend
            # it
            if pkg.startswith('fglrx'):
                for d in info['drivers']:
                    info['drivers'][d]['recommended'] = False
                info['drivers']['xserver-xorg-video-ati'] = {
                    'free': True, 'builtin': True, 'from_distro': True, 'recommended': True}
                break

def get_linux_headers(apt_cache):
    '''Return the linux headers for the system's kernel'''
    kernel_detection = kerneldetection.KernelDetection(apt_cache)
    return kernel_detection.get_linux_headers_metapackage()

def get_linux(apt_cache):
    '''Return the linux metapackage for the system's kernel'''
    kernel_detection = kerneldetection.KernelDetection(apt_cache)
    return kernel_detection.get_linux_metapackage()
