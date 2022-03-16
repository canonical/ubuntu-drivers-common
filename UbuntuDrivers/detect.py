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
import re

import apt

from UbuntuDrivers import kerneldetection

system_architecture = apt.apt_pkg.get_architectures()[0]
lookup_cache = {}


def system_modaliases(sys_path=None):
    '''Get modaliases present in the system.

    This ignores devices whose drivers are statically built into the kernel, as
    you cannot replace them with other driver packages anyway.

    Return a modalias → sysfs path map.
    '''
    aliases = {}
    devices = sys_path and '%s/devices' % (sys_path) or '/sys/devices'
    for path, dirs, files in os.walk(devices):
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
            with open(os.path.join(path, 'uevent')) as fd:
                for line in fd:
                    if line.startswith('MODALIAS='):
                        modalias = line.split('=', 1)[1].strip()
                        break

        if not modalias:
            continue

        # ignore drivers which are statically built into the kernel
        driverlink = os.path.join(path, 'driver')
        modlink = os.path.join(driverlink, 'module')
        if os.path.islink(driverlink) and not os.path.islink(modlink):
            # logging.debug('system_modaliases(): ignoring device %s which has no module (built into kernel)', path)
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
                # logging.debug('_check_video_abi_compat(): Current X.org video abi: %s', xorg_video_abi)
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
        # skip packages without a modalias field
        try:
            m = package.candidate.record['Modaliases']
        except (KeyError, AttributeError, UnicodeDecodeError):
            continue

        # skip foreign architectures, we usually only want native
        # driver packages
        if (not package.candidate or
                package.candidate.architecture not in ('all', system_architecture)):
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
        if fnmatch.fnmatch(modalias.lower(), alias.lower()):
            for p in bus_map[alias]:
                pkgs.add(p)

    return [apt_cache[p] for p in pkgs]


packages_for_modalias.cache_maps = {}


def _is_package_free(pkg):
    assert pkg.candidate is not None
    # it would be better to check the actual license, as we do not have
    # the component for third-party packages; but this is the best we can do
    # at the moment
    #
    # We can assume the NVIDIA packages to be non-free
    if pkg.name.startswith('nvidia'):
        return False
    for o in pkg.candidate.origins:
        if o.component in ('restricted', 'multiverse'):
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


def _pkg_get_support(pkg):
    '''Determine support level from apt Package object'''

    try:
        support = pkg.candidate.record['Support']
    except (KeyError, AttributeError):
        logging.debug('_pkg_get_support %s: package has no Support header, cannot determine support level', pkg.name)
        return None

    if support not in ('PB', 'NFB', 'LTSB', 'Legacy'):
        logging.warning('_pkg_get_support %s: package has invalid Support %s'
                        'header, cannot determine support level', pkg.name, support)
        return None

    return support


def _is_runtimepm_supported(pkg, alias):
    '''Check if the package supports runtimepm for the given modalias'''
    try:
        m = pkg.candidate.record['PmAliases']
    except (KeyError, AttributeError, UnicodeDecodeError):
        return False
    else:
        if m.find('nvidia(') != 0:
            return False

        n = m[m.find('(')+1: m.find(')')]
        modaliases = n.split(', ')
        return any(fnmatch.fnmatch(alias.lower(), regex.lower()) for regex in modaliases)


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

    try:
        modinfo = subprocess.Popen(['modinfo', module], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        modinfo.communicate()
    except (OSError, FileNotFoundError, subprocess.CalledProcessError) as e:
        logging.debug('_is_manual_install failed: %s', str(e))
        return False
    else:
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


def system_driver_packages(apt_cache=None, sys_path=None, freeonly=False, include_oem=True):
    '''Get driver packages that are available for the system.

    This calls system_modaliases() to determine the system's hardware and then
    queries apt about which packages provide drivers for those. It also adds
    available packages from detect_plugin_packages().

    If you already have an apt.Cache() object, you should pass it as an
    argument for efficiency. If not given, this function creates a temporary
    one by itself.

    If freeonly is set to True, only free packages (from main and universe) are
    considered

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
    global lookup_cache
    modaliases = system_modaliases(sys_path)

    if not apt_cache:
        try:
            apt_cache = apt.Cache()
        except Exception as ex:
            logging.error(ex)
            return {}

    packages = {}
    for alias, syspath in modaliases.items():
        for p in packages_for_modalias(apt_cache, alias):
            if freeonly and not _is_package_free(p):
                continue
            if not include_oem and fnmatch.fnmatch(p.name, 'oem-*-meta'):
                continue
            packages[p.name] = {
                    'modalias': alias,
                    'syspath': syspath,
                    'free': _is_package_free(p),
                    'from_distro': _is_package_from_distro(p),
                    'support': _pkg_get_support(p),
                    'runtimepm': _is_runtimepm_supported(p, alias)
                }
            (vendor, model) = _get_db_name(syspath, alias)
            if vendor is not None:
                packages[p.name]['vendor'] = vendor
            if model is not None:
                packages[p.name]['model'] = model

    # Add "recommended" flags for NVidia alternatives
    nvidia_packages = [p for p in packages if p.startswith('nvidia-')]
    if nvidia_packages:
        # Create a cache for looking up drivers to pick the best
        # candidate
        for key, value in packages.items():
            if key.startswith('nvidia-'):
                lookup_cache[key] = value
        nvidia_packages.sort(key=functools.cmp_to_key(_cmp_gfx_alternatives))
        recommended = nvidia_packages[-1]
        for p in nvidia_packages:
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


def _get_vendor_model_from_alias(alias):
    modalias_pattern = re.compile('(.+):v(.+)d(.+)sv(.+)sd(.+)bc(.+)i.*')

    details = modalias_pattern.match(alias)

    if details:
        return (details.group(2)[4:], details.group(3)[4:])

    return (None, None)


def _get_headless_no_dkms_metapackage(pkg, apt_cache):
    assert pkg.candidate is not None
    metapackage = None
    '''Return headless-no-dkms metapackage from the main metapackage.

    This is useful when dealing with packages such as nvidia-driver-$flavour
    whose headless-no-dkms metapackage would be nvidia-headless-no-dkms-$flavour
    '''
    name = pkg.shortname

    pattern = re.compile('nvidia-([0-9]+)')
    match = pattern.match(name)
    if match:
        logging.debug('Legacy driver detected: %s. Skipping.', name)
        return metapackage

    pattern = re.compile('nvidia-driver-([0-9]+)(.*)')
    match = pattern.match(name)
    if not match:
        logging.debug('No flavour can be found in %s. Skipping.', name)
        return metapackage

    candidate_flavour = '%s%s' % (match.group(1), match.group(2))
    candidate = 'nvidia-headless-no-dkms-%s' % (candidate_flavour)

    try:
        package = apt_cache.__getitem__(candidate)
        # skip foreign architectures, we usually only want native
        # driver packages
        if (package.candidate and
                package.candidate.architecture in ('all', system_architecture)):
            metapackage = candidate
    except KeyError:
        pass

    return metapackage


def system_device_specific_metapackages(apt_cache=None, sys_path=None, include_oem=True):
    '''Get device specific metapackages for this system

    This calls system_modaliases() to determine the system's hardware and then
    queries apt about which packages provide hardware enablement support for
    those.

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
      'recommended': Always True; we always recommend you install these
                     packages.
    '''
    if not include_oem:
        return {}

    modaliases = system_modaliases(sys_path)

    if not apt_cache:
        try:
            apt_cache = apt.Cache()
        except Exception as ex:
            logging.error(ex)
            return {}

    packages = {}
    for alias, syspath in modaliases.items():
        for p in packages_for_modalias(apt_cache, alias):
            if not fnmatch.fnmatch(p.name, 'oem-*-meta'):
                continue
            packages[p.name] = {
                    'modalias': alias,
                    'syspath': syspath,
                    'free': _is_package_free(p),
                    'from_distro': _is_package_from_distro(p),
                    'recommended': True,
                    'support': _pkg_get_support(p),
                }

    return packages


def system_gpgpu_driver_packages(apt_cache=None, sys_path=None):
    '''Get driver packages, for gpgpu purposes, that are available for the system.

    This calls system_modaliases() to determine the system's hardware and then
    queries apt about which packages provide drivers for those. Finally, it looks
    for the correct metapackage, by calling _get_headless_no_dkms_metapackage().

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
    global lookup_cache
    vendors_whitelist = ['10de']
    modaliases = system_modaliases(sys_path)

    if not apt_cache:
        try:
            apt_cache = apt.Cache()
        except Exception as ex:
            logging.error(ex)
            return {}

    packages = {}
    for alias, syspath in modaliases.items():
        for p in packages_for_modalias(apt_cache, alias):
            (vendor, model) = _get_db_name(syspath, alias)
            vendor_id, model_id = _get_vendor_model_from_alias(alias)
            if (vendor_id is not None) and (vendor_id.lower() in vendors_whitelist):
                packages[p.name] = {
                        'modalias': alias,
                        'syspath': syspath,
                        'free': _is_package_free(p),
                        'from_distro': _is_package_from_distro(p),
                        'support': _pkg_get_support(p),
                    }
                if vendor is not None:
                    packages[p.name]['vendor'] = vendor
                if model is not None:
                    packages[p.name]['model'] = model
                metapackage = _get_headless_no_dkms_metapackage(p, apt_cache)

                if metapackage is not None:
                    packages[p.name]['metapackage'] = metapackage

    # Add "recommended" flags for NVidia alternatives
    nvidia_packages = [p for p in packages if p.startswith('nvidia-')]
    if nvidia_packages:
        # Create a cache for looking up drivers to pick the best
        # candidate
        for key, value in packages.items():
            if key.startswith('nvidia-'):
                lookup_cache[key] = value
        nvidia_packages.sort(key=functools.cmp_to_key(_cmp_gfx_alternatives_gpgpu))
        recommended = nvidia_packages[-1]
        for p in nvidia_packages:
            packages[p]['recommended'] = (p == recommended)

    return packages


def system_device_drivers(apt_cache=None, sys_path=None, freeonly=False):
    '''Get by-device driver packages that are available for the system.

    This calls system_modaliases() to determine the system's hardware and then
    queries apt about which packages provide drivers for each of those. It also
    adds available packages from detect_plugin_packages(), using the name of
    the detction plugin as device name.

    If you already have an apt.Cache() object, you should pass it as an
    argument for efficiency. If not given, this function creates a temporary
    one by itself.

    If freeonly is set to True, only free packages (from main and universe) are
    considered

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
        try:
            apt_cache = apt.Cache()
        except Exception as ex:
            logging.error(ex)
            return {}

    # copy the system_driver_packages() structure into the by-device structure
    for pkg, pkginfo in system_driver_packages(apt_cache, sys_path,
                                               freeonly=freeonly).items():
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


class _GpgpuDriver(object):

    def __init__(self, vendor=None, flavour=None):
        self._vendors_whitelist = ('nvidia',)
        self.vendor = vendor
        self.flavour = flavour

    def is_valid(self):
        if self.vendor:
            # Filter the allowed vendors
            if not fnmatch.filter(self._vendors_whitelist, self.vendor):
                return False
        return not (not self.vendor and not self.flavour)


def _process_driver_string(string):
    '''Returns a _GpgpuDriver object'''
    driver = _GpgpuDriver()

    full_pattern = re.compile('(.+):([0-9]+)(.*)')
    vendor_only_pattern = re.compile('([a-z]+)')
    series_only_pattern = re.compile('([0-9]+)(.*)')

    full_match = full_pattern.match(string)
    vendor_match = vendor_only_pattern.match(string)
    series_match = series_only_pattern.match(string)

    if full_match:
        driver.vendor = full_match.group(1)
        driver.flavour = '%s%s' % (full_match.group(2), full_match.group(3))
    elif vendor_match:
        driver.vendor = string
    elif series_match:
        driver.flavour = '%s%s' % (series_match.group(1), series_match.group(2))

    return driver


def gpgpu_install_filter(packages, drivers_str):
    drivers = []
    allow = []
    result = {}
    '''Filter the Ubuntu packages according to the parameters the users passed

    Ubuntu-drivers syntax

    ubuntu-drivers autoinstall --gpgpu [[driver:]version]
    ubuntu-drivers autoinstall --gpgpu driver[:version][,driver[:version]]

    If no version is specified, gives the “current” supported version for the GPU in question.

    Examples:
    ubuntu-drivers autoinstall --gpgpu
    ubuntu-drivers autoinstall --gpgpu 390
    ubuntu-drivers autoinstall --gpgpu nvidia:390

    Today this is only nvidia.  In the future there may be amdgpu-pro.
    Possible syntax, to be confirmed only once there are driver packages that could use it:
    ubuntu-drivers autoinstall --gpgpu nvidia:390,amdgpu
    ubuntu-drivers autoinstall --gpgpu amdgpu:version
    '''
    if not packages:
        return result

    if drivers_str:
        # Just one driver
        # e.g. --gpgpu 390
        #      --gpgpu nvidia:390
        #
        # Or Multiple drivers
        # e.g. --gpgpu nvidia:390,amdgpu
        for item in drivers_str.split(','):
            driver = _process_driver_string(item)
            if driver and driver.is_valid():
                drivers.append(driver)
    else:
        # No args, just --gpgpu
        driver = _GpgpuDriver()
        drivers.append(driver)

    if len(drivers) < 1:
        return result

    # If the vendor is not specified, we assume it's nvidia
    it = 0
    for driver in drivers:
        if not driver.vendor:
            drivers[it].vendor = 'nvidia'
        it += 1

    # Do not allow installing multiple versions of the nvidia driver
    it = 0
    vendors_temp = []
    for driver in drivers:
        vendor = driver.vendor
        if vendors_temp.__contains__(vendor):
            # TODO: raise error here
            logging.debug('Multiple nvidia versions passed at the same time')
            return result
        vendors_temp.append(vendor)
        it += 1

    # If the flavour is not specified, we assume it's nvidia,
    # and we install the newest driver
    it = 0
    for driver in drivers:
        if not driver.flavour and not driver.vendor:
            drivers[it].vendor = 'nvidia'
        it += 1

    # Filter the packages
    # any package which matches any of those globs will be accepted
    for driver in drivers:
        if driver.flavour:
            pattern = '%s*%s' % (driver.vendor, driver.flavour)
        else:
            pattern = '%s*' % (driver.vendor)
        allow.extend(fnmatch.filter(packages, pattern))
        # print(allow)

    # FIXME: if no flavour is specified, pick the recommended driver ?
    # print('packages: %s' % packages)
    for p in allow:
        # If the version was specified, we override the recommended attribute
        for driver in drivers:
            if p.__contains__(driver.vendor):
                if driver.flavour:
                    # print('Found "%s" flavour in %s' % (driver.flavour, packages[p]))
                    result[p] = packages[p]
                else:
                    # print('before recommended: %s' % packages[p])
                    if packages[p].get('recommended'):
                        result[p] = packages[p]
                        # print('Found "recommended" flavour in %s' % (packages[p]))
                break
    return result


def auto_install_filter(packages, drivers_str=''):
    '''Get packages which are appropriate for automatic installation.

    Return the subset of the given list of packages which are appropriate for
    automatic installation by the installer. This applies to e. g. the Broadcom
    Wifi driver (as there is no alternative), but not to the FGLRX proprietary
    graphics driver (as the free driver works well and FGLRX does not provide
    KMS).
    '''
    # any package which matches any of those globs will be accepted
    whitelist = ['bcmwl*', 'pvr-omap*', 'virtualbox-guest*', 'nvidia-*',
                 'open-vm-tools*', 'oem-*-meta']

    # If users specify a driver, use gpgpu_install_filter()
    if drivers_str:
        results = gpgpu_install_filter(packages, drivers_str)
        return results

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
        try:
            apt_cache = apt.Cache()
        except Exception as ex:
            logging.error(ex)
            return {}

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
            except Exception:
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


def _pkg_support_from_cache(x):
    '''Look up driver package and return their support level'''
    if lookup_cache.get(x):
        return lookup_cache.get(x).get('support')
    return None


def _cmp_gfx_alternatives(x, y):
    '''Compare two graphics driver names in terms of preference. (desktop)

    -server always sorts after non-server.
    LTSB (Long Term Support Branch) always sorts before NFB (New Feature Branch).
    Legacy always sorts before Beta.
    '''
    if x.endswith('-server') and not y.endswith('-server'):
        return -1
    if not x.endswith('-server') and y.endswith('-server'):
        return 1

    preferred_support = ['PB', 'LTSB']

    x_score = 0
    y_score = 0

    x_support = _pkg_support_from_cache(x)
    y_support = _pkg_support_from_cache(y)

    if x_support in preferred_support:
        x_score += 100

    if y_support in preferred_support:
        y_score += 100

    if x > y:
        x_score += 1
    elif x < y:
        y_score += 1

    if ((x_score >= 100) or (y_score >= 100)):
        if x_score > y_score:
            return 1
        elif x_score < y_score:
            return -1

    if _pkg_support_from_cache(x) == 'PB' and _pkg_support_from_cache(y) != 'PB':
        return 1
    if _pkg_support_from_cache(x) != 'PB' and _pkg_support_from_cache(y) == 'PB':
        return -1
    if _pkg_support_from_cache(x) == 'LTSB' and _pkg_support_from_cache(y) != 'LTSB':
        return 1
    if _pkg_support_from_cache(x) != 'LTSB' and _pkg_support_from_cache(y) == 'LTSB':
        return -1
    if _pkg_support_from_cache(x) == 'Legacy' and _pkg_support_from_cache(y) != 'Legacy':
        return -1
    if _pkg_support_from_cache(x) != 'Legacy' and _pkg_support_from_cache(y) == 'Legacy':
        return 1
    if _pkg_support_from_cache(x) == 'Beta' and _pkg_support_from_cache(y) != 'Beta':
        return -1
    if _pkg_support_from_cache(x) != 'Beta' and _pkg_support_from_cache(y) == 'Beta':
        return 1
    if x < y:
        return -1
    if x > y:
        return 1
    assert x == y
    return 0


def _cmp_gfx_alternatives_gpgpu(x, y):
    '''Compare two graphics driver names in terms of preference. (server)

    -server always sorts before non-server.
    LTSB (Long Term Support Branch) always sorts before NFB (New Feature Branch).
    Legacy always sorts before Beta.
    '''
    if x.endswith('-server') and not y.endswith('-server'):
        return 1
    if not x.endswith('-server') and y.endswith('-server'):
        return -1

    if _pkg_support_from_cache(x) == 'PB' and _pkg_support_from_cache(y) != 'PB':
        return 1
    if _pkg_support_from_cache(x) != 'PB' and _pkg_support_from_cache(y) == 'PB':
        return -1
    if _pkg_support_from_cache(x) == 'LTSB' and _pkg_support_from_cache(y) != 'LTSB':
        return 1
    if _pkg_support_from_cache(x) != 'LTSB' and _pkg_support_from_cache(y) == 'LTSB':
        return -1
    if _pkg_support_from_cache(x) == 'Legacy' and _pkg_support_from_cache(y) != 'Legacy':
        return -1
    if _pkg_support_from_cache(x) != 'Legacy' and _pkg_support_from_cache(y) == 'Legacy':
        return 1
    if _pkg_support_from_cache(x) == 'Beta' and _pkg_support_from_cache(y) != 'Beta':
        return -1
    if _pkg_support_from_cache(x) != 'Beta' and _pkg_support_from_cache(y) == 'Beta':
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


def get_linux_image(apt_cache):
    '''Return the linux image for the system's kernel'''
    kernel_detection = kerneldetection.KernelDetection(apt_cache)
    return kernel_detection.get_linux_image_metapackage()


def get_linux_version(apt_cache):
    '''Return the linux image for the system's kernel'''
    kernel_detection = kerneldetection.KernelDetection(apt_cache)
    return kernel_detection.get_linux_version()


def get_linux(apt_cache):
    '''Return the linux metapackage for the system's kernel'''
    kernel_detection = kerneldetection.KernelDetection(apt_cache)
    return kernel_detection.get_linux_metapackage()


def find_reverse_dependencies(apt_cache, package, prefix):
    '''Return the reverse dependencies for a package'''
    # prefix to restrict the searching
    # package we want reverse dependencies for
    deps = set()
    for pkg in apt_cache:
        if pkg.name.startswith(prefix):
            dependencies = []
            if pkg.candidate:
                dependencies.extend(pkg.candidate.dependencies)
            if pkg.installed:
                dependencies.extend(pkg.installed.dependencies)

            for ordep in dependencies:
                for dep in ordep:
                    if dep.rawtype != 'Depends':
                        continue
                    if dep.name == package:
                        deps.add(pkg.name)
    return list(deps)


def get_linux_image_from_meta(apt_cache, pkg):
    if apt_cache[pkg].candidate:
        record = apt_cache[pkg].candidate.record

    try:
        deps = record['Depends']
    except KeyError:
        return None

    deps_list = deps.strip().split(', ')
    for dep in deps_list:
        if dep.startswith('linux-image-'):
            return dep

    return None


def get_linux_modules_metapackage(apt_cache, candidate):
    '''Return the linux-modules-$driver metapackage for the system's kernel'''
    assert candidate is not None
    metapackage = None
    linux_flavour = ''
    linux_modules_match = ''

    if 'nvidia' not in candidate:
        logging.debug('Non NVIDIA linux-modules packages are not supported at this time: %s. Skipping', candidate)
        return metapackage

    pattern = re.compile('nvidia-([0-9]+)')
    match = pattern.match(candidate)
    if match:
        logging.debug('Legacy driver detected: %s. Skipping.', candidate)
        return metapackage

    linux_image_meta = get_linux_image(apt_cache)
    # Check the actual image package, and find the flavour from there
    linux_image = get_linux_image_from_meta(apt_cache, linux_image_meta)

    if linux_image:
        linux_flavour = linux_image.replace('linux-image-', '')
    else:
        logging.debug('No linux-image can be found for %s. Skipping.', candidate)
        return metapackage

    pattern = re.compile('nvidia-.*-([0-9]+)(.*)')
    match = pattern.match(candidate)
    if not match:
        logging.debug('No flavour can be found in %s. Skipping.', candidate)
        return metapackage

    candidate_flavour = '%s%s' % (match.group(1), match.group(2))
    linux_modules_candidate = 'linux-modules-nvidia-%s-%s' % (candidate_flavour, linux_flavour)

    try:
        package = apt_cache.__getitem__(linux_modules_candidate)
        # skip foreign architectures, we usually only want native
        if (package.candidate and
                package.candidate.architecture in ('all', system_architecture)):
            linux_version = get_linux_version(apt_cache)
            linux_modules_abi_candidate = 'linux-modules-nvidia-%s-%s' % (candidate_flavour, linux_version)
            logging.debug('linux_modules_abi_candidate: %s' % (linux_modules_abi_candidate))

            # Let's check if there is a candidate that is specific to
            # our kernel ABI. If not, things will fail.
            abi_specific = apt_cache.__getitem__(linux_modules_abi_candidate)
            # skip foreign architectures, we usually only want native
            if (abi_specific.candidate and
                    abi_specific.candidate.architecture in ('all', system_architecture)):
                logging.debug('Found ABI compatible %s' % (linux_modules_abi_candidate))
                linux_modules_match = linux_modules_candidate
    except KeyError:
        logging.debug('No "%s" can be found.', linux_modules_candidate)
        pass

    # Add an extra layer of paranoia, and check the availability
    # of modules with the correct ABI
    if linux_modules_match:
        # Look for the metapackage in the reverse
        # dependencies
        reverse_deps = find_reverse_dependencies(apt_cache, linux_modules_match, 'linux-modules-nvidia-')
        pick = ''
        modules_candidate = 'linux-modules-nvidia-%s-%s' % (candidate_flavour,
                                                            get_linux_image(apt_cache).replace('linux-image-', ''))
        for dep in reverse_deps:
            if dep == modules_candidate:
                pick = dep
        if pick:
            metapackage = pick
            return metapackage

    # If no linux-modules-nvidia package is available for the current kernel
    # we should install the relevant DKMS package
    dkms_package = 'nvidia-dkms-%s' % candidate_flavour
    logging.debug('Falling back to %s' % (dkms_package))

    try:
        package = apt_cache.__getitem__(dkms_package)
        # skip foreign architectures, we usually only want native
        if (package.candidate and
                package.candidate.architecture in ('all', system_architecture)):
            metapackage = dkms_package
    except KeyError:
        logging.error('No "%s" can be found.', dkms_package)
        pass

    return metapackage
