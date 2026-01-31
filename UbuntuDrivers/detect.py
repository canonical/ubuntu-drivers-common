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
import json

import apt_pkg

from UbuntuDrivers import kerneldetection
from functools import cmp_to_key

system_architecture = ''
lookup_cache = {}
custom_supported_gpus_json = '/etc/custom_supported_gpus.json'


class NvidiaPkgNameInfo(object):
    '''Class to process NVIDIA package names'''
    def __init__(self, pkg_name):
        self._pkg_name = pkg_name
        self._obsolete_name_scheme = False
        self._server = False
        self._open = False
        self._major_ver = -1
        self._flavour = ''
        self.is_valid = False
        self._process_name(self._pkg_name)

    def _process_name(self, name):
        if 'nvidia' not in name:
            logging.debug('NvidiaPkgNameInfo: %s is not an NVIDIA package. Skipping', name)
            return

        pattern = re.compile('nvidia-([0-9]+)')
        match = pattern.match(name)

        # Obsolete naming such as nvidia-340
        if match:
            self._obsolete_name_scheme = True
            self._major_ver = int(match.group(1))
            self._flavour = self._major_ver
            self.is_valid = True
            return

        # Recent naming such as nvidia-driver-525
        pattern = re.compile('nvidia-driver-([0-9]+)(.*)')
        match = pattern.match(name)

        if match:
            self._server = match.group(0).find('-server') != -1
            self._open = match.group(0).find('-open') != -1
            self._flavour = '%s%s%s' % (match.group(1),
                                        '-server' if self._server else '',
                                        '-open' if self._open else '')
            self._major_ver = int(match.group(1))
            self.is_valid = True

        # Recent naming such as nvidia-headless[-no-dkms]-525 for gpgpu
        pattern = re.compile('nvidia-headless(.*)-([0-9]+)(.*)')
        match = pattern.match(name)

        if match:
            self._server = match.group(0).find('-server') != -1
            self._open = match.group(0).find('-open') != -1
            self._flavour = '%s%s%s' % (match.group(2),
                                        '-server' if self._server else '',
                                        '-open' if self._open else '')
            self._major_ver = match.group(2)
            self.is_valid = True

    def has_obsolete_name_scheme(self):
        return self._obsolete_name_scheme

    def is_server(self):
        return self._server

    def is_open(self):
        return self._open

    def get_major_version(self):
        return self._major_ver

    def get_flavour(self):
        return self._flavour


def get_apt_arch():
    '''Cache system architecture'''
    global system_architecture
    if not system_architecture:
        system_architecture = apt_pkg.get_architectures()[0]
    return system_architecture


def system_modaliases(sys_path=None):
    '''Get modaliases present in the system.

    This ignores devices whose drivers are statically built into the kernel, as
    you cannot replace them with other driver packages anyway.

    Return a modalias → sysfs path map.
    '''
    aliases = {}
    devices = f"{sys_path}/devices" if sys_path else "/sys/devices"
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


def _check_video_abi_compat(apt_cache, package):
    xorg_video_abi = None

    if package.name.startswith('nvidia-driver-'):
        xorg_driver_name = package.name.replace('nvidia-driver-', 'xserver-xorg-video-nvidia-')
        try:
            package = apt_cache[xorg_driver_name]
        except KeyError:
            logging.debug('Cannot find %s package in the cache. Cannot check ABI' % (xorg_driver_name))
            return True

    depcache = apt_pkg.DepCache(apt_cache)
    candidate = depcache.get_candidate_ver(package)

    needs_video_abi = False
    try:
        for dep_list in candidate.depends_list_str.get('Depends'):
            for dep_name, dep_ver, dep_op in dep_list:
                if dep_name.startswith('xorg-video-abi-'):
                    needs_video_abi = True
                    break
    except (KeyError, TypeError):
        logging.debug('The %s package seems to have no dependencies. Skipping ABI check' % (package))
        needs_video_abi = False

    if not needs_video_abi:
        logging.debug('Skipping check for %s since it does not depend on video abi' % package.name)
        return True

    # determine current X.org video driver ABI
    try:
        xorg_core = apt_cache['xserver-xorg-core']
    except KeyError:
        logging.debug('xserver-xorg-core not available, cannot check ABI')
        return True

    candidate = depcache.get_candidate_ver(xorg_core)

    for provides_name, provides_ver, p_version in candidate.provides_list:
        if provides_name.startswith('xorg-video-abi-'):
            xorg_video_abi = provides_name

    if xorg_video_abi:
        abi_pkg = apt_cache[xorg_video_abi]
        for dep in abi_pkg.rev_depends_list:
            if dep.parent_pkg.name == package.name:
                return True

        logging.debug('Driver package %s is incompatible with current X.org server ABI %s',
                      package.name, xorg_video_abi)
        logging.debug('%s is not in %s' % (package, [x.parent_pkg for x in abi_pkg.rev_depends_list]))
        return False

    return True


def apt_cache_modalias_map(apt_cache):
    '''Build a modalias map from an apt_pkg.Cache object.

    This filters out uninstallable video drivers (i. e. which depend on a video
    ABI that xserver-xorg-core does not provide).

    Return a map bus -> modalias -> [package, ...], where "bus" is the prefix of
    the modalias up to the first ':' (e. g. "pci" or "usb").
    '''
    depcache = apt_pkg.DepCache(apt_cache)
    records = apt_pkg.PackageRecords(apt_cache)

    result = {}
    for package in apt_cache.packages:
        # skip packages without a modalias field
        try:
            candidate = depcache.get_candidate_ver(package)
            records.lookup(candidate.file_list[0])
            m = records['Modaliases']
            if not m:
                continue
        except (KeyError, AttributeError, UnicodeDecodeError):
            continue

        # skip foreign architectures, we usually only want native
        # driver packages
        if (package.architecture not in ('all', get_apt_arch())):
            continue

        if not _check_video_abi_compat(apt_cache, package):
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

    result2 = {}
    for bus, alias_map in result.items():
        pat = re.compile(
            '|'.join([fnmatch.translate(pat) for pat in alias_map.keys()]),
            re.IGNORECASE)
        result2[bus] = (pat, alias_map)

    return result2


def path_get_custom_supported_gpus():
    return custom_supported_gpus_json


def package_get_nv_allowing_driver(did):
    '''Get nvidia allowing driver for specific devices.

    did: 0x1234
    Return the situable nvidia driver version for it.
    '''
    path = path_get_custom_supported_gpus()
    version = None
    try:
        with open(path, "r") as stream:
            try:
                gpus = list(json.load(stream)['chips'])
                for gpu in gpus:
                    if gpu['devid'] == did:
                        version = gpu['branch'].split('.')[0]
                        logging.info("Found a specific nv driver version %s for %s(%s)" %
                                     (version, gpu['name'], did))
                        break
            except Exception:
                logging.debug('package_get_nv_allowing_driver(): unexpected json detected.')
                pass
    except Exception:
        logging.debug('package_get_nv_allowing_driver(): unable to read %s' % path)
        pass
    return version


def packages_for_modalias(apt_cache, modalias, modalias_map=None):
    '''Search packages which match the given modalias.

    Return a list of apt.Package objects.
    '''
    pkgs = set()

    if modalias_map is None:
        modalias_map = apt_cache_modalias_map(apt_cache)

    pat, bus_map = modalias_map.get(modalias.split(':', 1)[0], (None, {}))
    vid, did = _get_vendor_model_from_alias(modalias)
    nvamd = None
    found = 0
    if vid == "10DE":
        nvamd = package_get_nv_allowing_driver("0x" + did)
        nvamdn = "nvidia-driver-%s" % nvamd
        nvamda = "pci:v000010DEd0000%s*" % did
        for p in apt_cache.packages:
            if p.get_fullname().split(':')[0] == nvamdn:
                bus_map[nvamda] = set([nvamdn])
                found = 1
        if nvamd is not None and not found:
            logging.debug('%s is not in the package pool.' % nvamdn)

    if found:
        logging.info('Found custom %s in the package pool.' % nvamdn)
        return [apt_cache[nvamdn]]

    if pat is None or not pat.match(modalias):
        return []

    for alias in bus_map:
        if fnmatch.fnmatchcase(modalias.lower(), alias.lower()):
            for p in bus_map[alias]:
                pkgs.add(p)

    return [apt_cache[p] for p in pkgs]


def _is_package_free(apt_cache, pkg):
    depcache = apt_pkg.DepCache(apt_cache)
    candidate = depcache.get_candidate_ver(pkg)
    assert candidate is not None
    # it would be better to check the actual license, as we do not have
    # the component for third-party packages; but this is the best we can do
    # at the moment
    #
    # We can assume the NVIDIA packages to be non-free
    if pkg.name.startswith('nvidia'):
        return False

    records = apt_pkg.PackageRecords(apt_cache)
    records.lookup(candidate.file_list[0])

    for pfile, _ in pkg.version_list[0].file_list:
        if not pfile.component:
            # This is probably from the test suite
            try:
                component = records['Component']
                return (component not in ('restricted', 'multiverse'))
            except KeyError:
                return False
        else:
            if pfile.component in ('restricted', 'multiverse'):
                return False
    return True


def _is_package_from_distro(apt_cache, pkg):
    depcache = apt_pkg.DepCache(apt_cache)
    candidate = depcache.get_candidate_ver(pkg)
    if candidate is None:
        return False

    try:
        return (candidate.file_list[0][0].origin == 'Ubuntu')
    except KeyError:
        return False


def _pkg_get_open_preference(apt_cache, pkg):
    '''Determine if -open package is prefered from apt Package object'''
    depcache = apt_pkg.DepCache(apt_cache)
    candidate = depcache.get_candidate_ver(pkg)
    records = apt_pkg.PackageRecords(apt_cache)
    records.lookup(candidate.file_list[0])

    try:
        preference = records['Prefer-Variant']
    except (KeyError, AttributeError):
        logging.debug('_pkg_get_open_preference %s: package has Prefer-Open header, cannot determine', pkg.name)
        return False

    if preference not in ('Open', 'Closed'):
        logging.debug('_pkg_get_open_preference %s: package has invalid Prefer-Open %s'
                      'header, cannot determine preference', pkg.name, preference)
        return None

    return preference


def _pkg_get_module(apt_cache, pkg):
    '''Determine module name from apt Package object'''
    depcache = apt_pkg.DepCache(apt_cache)
    candidate = depcache.get_candidate_ver(pkg)
    records = apt_pkg.PackageRecords(apt_cache)
    records.lookup(candidate.file_list[0])

    try:
        m = records['Modaliases']
    except (KeyError, AttributeError):
        logging.debug('_pkg_get_module %s: package has no Modaliases header, cannot determine module', pkg.name)
        return None

    paren = m.find('(')
    if paren <= 0:
        logging.debug('_pkg_get_module %s: package has invalid Modaliases header, cannot determine module', pkg.name)
        return None

    module = m[:paren]
    return module


def _pkg_get_support(apt_cache, pkg):
    '''Determine support level from apt Package object'''

    depcache = apt_pkg.DepCache(apt_cache)
    candidate = depcache.get_candidate_ver(pkg)
    records = apt_pkg.PackageRecords(apt_cache)
    records.lookup(candidate.file_list[0])

    try:
        support = records['Support']
    except (KeyError, AttributeError):
        logging.debug('_pkg_get_support %s: package has no Support header, cannot determine support level', pkg.name)
        return None

    if support not in ('PB', 'NFB', 'LTSB', 'Legacy'):
        logging.debug('_pkg_get_support %s: package has invalid Support %s'
                      'header, cannot determine support level', pkg.name, support)
        return None

    return support


def _is_nv_allowing_runtimepm_supported(alias, ver):
    '''alias: e.g. pci:v000010DEd000024BAsv0000103Csd000089C6bc03sc00i00'''
    result = re.search('pci:v0000(.*)d0000(.*)sv(.*)', alias)
    vid = result.group(1)
    did = result.group(2)
    if vid != "10DE":
        return False
    did = "0x%s" % did
    path = path_get_custom_supported_gpus()
    try:
        with open(path, "r") as stream:
            try:
                gpus = list(json.load(stream)['chips'])
                for gpu in gpus:
                    if gpu['devid'] == did and 'runtimepm' in gpu['features']:
                        if ver in gpu['branch'].split('.')[0]:
                            logging.info("Found runtimepm supports on %s." % did)
                            return True
                logging.debug('%s has no matched driver to support runtimepm' % did)
            except Exception:
                logging.debug('_is_nv_allowing_runtimepm_supported(): unexpected json detected')
                pass
    except Exception:
        logging.debug('_is_nv_allowing_runtimepm_supported(): unable to read %s' % path)
        pass
    return False


def _is_runtimepm_supported(apt_cache, pkg, alias):
    '''Check if the package supports runtimepm for the given modalias'''
    try:
        depcache = apt_pkg.DepCache(apt_cache)
        candidate = depcache.get_candidate_ver(pkg)
        records = apt_pkg.PackageRecords(apt_cache)
        records.lookup(candidate.file_list[0])
        section = apt_pkg.TagSection(records.record)
        ver = candidate.ver_str.split('.')[0]
        m = section['PmAliases']
    except (KeyError, AttributeError, UnicodeDecodeError):
        return False
    else:
        if m.find('nvidia(') != 0:
            return False

        n = m[m.find('(')+1: m.find(')')]
        modaliases = n.split(', ')
        if _is_nv_allowing_runtimepm_supported(alias, ver):
            return True
        return any(fnmatch.fnmatch(alias.lower(), regex.lower()) for regex in modaliases)


def is_wayland_session():
    '''Check if the current session in on Wayland'''
    return os.environ.get('WAYLAND_DISPLAY') is not None


def _is_manual_install(apt_cache, pkg):
    '''Determine if the kernel module from an apt.Package is manually installed.'''

    if pkg.current_ver:
        return False

    # special case, as our packages suffix the kmod with _version
    if pkg.name.startswith('nvidia'):
        module = 'nvidia'
    elif pkg.name.startswith('fglrx'):
        module = 'fglrx'
    else:
        module = _pkg_get_module(apt_cache, pkg)

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
        out = subprocess.check_output(['systemd-hwdb', 'query', alias],
                                      universal_newlines=True)
    except (OSError, subprocess.CalledProcessError) as e:
        logging.debug('_get_db_name(%s, %s): systemd-hwdb failed: %s', syspath, alias, str(e))
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


def _is_open_prefered(apt_cache, pkg):
    if not pkg.name.startswith('nvidia-'):
        return False

    preference = _pkg_get_open_preference(apt_cache, pkg)
    if preference is None:
        nvidia_info = NvidiaPkgNameInfo(pkg.name)
        if nvidia_info.get_major_version() >= 560:
            logging.debug('_is_open_prefered(%s): True', pkg.name)
            return True
    elif preference == 'Open':
        logging.debug('_is_open_prefered(%s): True', pkg.name)
        return True

    logging.debug('_is_open_prefered(%s): False', pkg.name)
    return False


def set_nvidia_kms(value):
    '''Set KMS on or off for NVIDIA'''
    nvidia_kms_file = '/lib/modprobe.d/nvidia-kms.conf'
    kms_text = '''# This file was generated by ubuntu-drivers
# Set value to 1 to enable modesetting, 0 to disable it
options nvidia-drm modeset=%d\n''' % (value)
    kms_fd = open(nvidia_kms_file, 'w')
    kms_fd.write(kms_text)
    kms_fd.close()


def system_driver_packages(apt_cache=None, sys_path=None, freeonly=False, include_oem=True):
    '''Get driver packages that are available for the system.

    This calls system_modaliases() to determine the system's hardware and then
    queries apt about which packages provide drivers for those. It also adds
    available packages from detect_plugin_packages().

    If you already have an apt_pkg.Cache() object, you should pass it as an
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
            apt_cache = apt_pkg.Cache(None)
        except Exception as ex:
            logging.error(ex)
            return {}

    packages = {}
    modalias_map = apt_cache_modalias_map(apt_cache)
    for alias, syspath in modaliases.items():
        for p in packages_for_modalias(apt_cache, alias, modalias_map=modalias_map):
            if freeonly and not _is_package_free(apt_cache, p):
                continue
            if not include_oem and fnmatch.fnmatch(p.name, 'oem-*-meta'):
                continue
            packages[p.name] = {
                    'modalias': alias,
                    'syspath': syspath,
                    'free': _is_package_free(apt_cache, p),
                    'from_distro': _is_package_from_distro(apt_cache, p),
                    'support': _pkg_get_support(apt_cache, p),
                    'runtimepm': _is_runtimepm_supported(apt_cache, p, alias),
                    'open_preferred': _is_open_prefered(apt_cache, p)
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
            try:
                apt_p = apt_cache[p]
                packages[p] = {
                        'free': _is_package_free(apt_cache, apt_p),
                        'from_distro': _is_package_from_distro(apt_cache, apt_p),
                        'plugin': plugin,
                    }
            except KeyError:
                logging.debug('Package %s plugin not available. Skipping.' % p)

    return packages


def _get_vendor_model_from_alias(alias):
    modalias_pattern = re.compile('(.+):v(.+)d(.+)sv(.+)sd(.+)bc(.+)i.*')

    details = modalias_pattern.match(alias)

    if details:
        return (details.group(2)[4:], details.group(3)[4:])

    return (None, None)


def get_userspace_lrm_meta(apt_cache, pkg_name):
    assert pkg_name is not None
    metapackage = None
    '''Return nvidia-driver-lrm-$flavour metapackage from the main metapackage.

    This is useful to see whether any such package is available.
    '''
    depcache = apt_pkg.DepCache(apt_cache)

    nvidia_info = NvidiaPkgNameInfo(pkg_name)
    if not nvidia_info.is_valid:
        logging.debug('Unsupported driver detected: %s. Skipping' % pkg_name)
        return metapackage

    if nvidia_info.has_obsolete_name_scheme():
        logging.debug('Legacy driver detected: %s. Skipping.' % pkg_name)
        return metapackage

    candidate_flavour = nvidia_info.get_flavour()
    candidate = 'nvidia-driver-lrm-%s' % (candidate_flavour)

    try:
        package = apt_cache[candidate]
        # skip foreign architectures, we usually only want native
        # driver packages
        package_candidate = depcache.get_candidate_ver(package)
        if (candidate and
                package_candidate.arch in ('all', get_apt_arch())):
            metapackage = candidate
    except KeyError:
        pass

    return metapackage


def _get_headless_no_dkms_metapackage(pkg, apt_cache):
    assert pkg is not None
    metapackage = None
    '''Return headless-no-dkms metapackage from the main metapackage.

    This is useful when dealing with packages such as nvidia-driver-$flavour
    whose headless-no-dkms metapackage would be nvidia-headless-no-dkms-$flavour
    '''
    depcache = apt_pkg.DepCache(apt_cache)
    name = pkg.name

    nvidia_info = NvidiaPkgNameInfo(name)
    if not nvidia_info.is_valid:
        logging.debug('Unsupported driver detected: %s. Skipping' % name)
        return metapackage

    if nvidia_info.has_obsolete_name_scheme():
        logging.debug('Legacy driver detected: %s. Skipping.' % name)
        return metapackage

    candidate_flavour = nvidia_info.get_flavour()
    candidate = 'nvidia-headless-no-dkms-%s' % (candidate_flavour)

    try:
        package = apt_cache[candidate]
        # skip foreign architectures, we usually only want native
        # driver packages
        package_candidate = depcache.get_candidate_ver(package)
        if (candidate and
                package_candidate.arch in ('all', get_apt_arch())):
            metapackage = candidate
    except KeyError:
        pass

    return metapackage


def system_device_specific_metapackages(apt_cache=None, sys_path=None, include_oem=True):
    '''Get device specific metapackages for this system

    This calls system_modaliases() to determine the system's hardware and then
    queries apt about which packages provide hardware enablement support for
    those.

    If you already have an apt_pkg.Cache() object, you should pass it as an
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
            apt_cache = apt_pkg.Cache(None)
        except Exception as ex:
            logging.error(ex)
            return {}

    packages = {}
    modalias_map = apt_cache_modalias_map(apt_cache)
    for alias, syspath in modaliases.items():
        for p in packages_for_modalias(apt_cache, alias, modalias_map=modalias_map):
            if not fnmatch.fnmatch(p.name, 'oem-*-meta'):
                continue
            packages[p.name] = {
                    'modalias': alias,
                    'syspath': syspath,
                    'free': _is_package_free(apt_cache, p),
                    'from_distro': _is_package_from_distro(apt_cache, p),
                    'recommended': True,
                    'support': _pkg_get_support(apt_cache, p),
                    'open_preferred': _is_open_prefered(apt_cache, p),
                }

    return packages


def system_gpgpu_driver_packages(apt_cache=None, sys_path=None):
    '''Get driver packages, for gpgpu purposes, that are available for the system.

    This calls system_modaliases() to determine the system's hardware and then
    queries apt about which packages provide drivers for those. Finally, it looks
    for the correct metapackage, by calling _get_headless_no_dkms_metapackage().

    If you already have an apt_pkg.Cache() object, you should pass it as an
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
            apt_cache = apt_pkg.Cache(None)
        except Exception as ex:
            logging.error(ex)
            return {}

    packages = {}
    modalias_map = apt_cache_modalias_map(apt_cache)
    for alias, syspath in modaliases.items():
        for p in packages_for_modalias(apt_cache, alias, modalias_map=modalias_map):
            (vendor, model) = _get_db_name(syspath, alias)
            vendor_id, model_id = _get_vendor_model_from_alias(alias)
            if (vendor_id is not None) and (vendor_id.lower() in vendors_whitelist):
                packages[p.name] = {
                        'modalias': alias,
                        'syspath': syspath,
                        'free': _is_package_free(apt_cache, p),
                        'from_distro': _is_package_from_distro(apt_cache, p),
                        'support': _pkg_get_support(apt_cache, p),
                        'open_preferred': _is_open_prefered(apt_cache, p),
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

    If you already have an apt_pkg.Cache() object, you should pass it as an
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
            apt_cache = apt_pkg.Cache(None)
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
            if not _is_manual_install(apt_cache, apt_cache[pkg]):
                break
        else:
            info['manual_install'] = True

    # add OS builtin free alternatives to proprietary drivers
    _add_builtins(result)

    return result


def get_installed_packages_by_glob(apt_cache, glob_pattern):
    '''Query apt-cache for installed packages matching a specific glob pattern.

    Args:
        apt_cache: The apt cache object
        glob_pattern: Glob pattern to match package names (e.g., "nvidia-driver-*")

    Returns:
        List of strings containing the names of all installed packages that match the pattern
    '''
    installed_packages = []

    for package in apt_cache.packages:
        package_name = package.name
        if package.current_ver and fnmatch.fnmatch(package_name, glob_pattern):
            installed_packages.append(package_name)

    return sorted(installed_packages)


def get_desktop_package_list(
        apt_cache, sys_path=None, free_only=False, include_oem=True,
        driver_string='', include_dkms=False):
    '''Return the list of packages that should be installed'''
    packages = system_driver_packages(
        apt_cache, sys_path, freeonly=free_only,
        include_oem=include_oem)
    packages = auto_install_filter(packages, driver_string, get_recommended=False)
    if not packages:
        logging.debug('No drivers found for installation.')
        return packages

    depcache = apt_pkg.DepCache(apt_cache)
    records = apt_pkg.PackageRecords(apt_cache)

    # ignore packages which are already installed
    to_install = []
    for p, _ in sorted(packages.items(),
                       key=cmp_to_key(lambda left, right: _cmp_gfx_alternatives(left[0], right[0])),
                       reverse=True):
        package_obj = apt_cache[p]
        if not package_obj.current_ver:

            candidate = depcache.get_candidate_ver(package_obj)
            records.lookup(candidate.file_list[0])

            # Do not add more than one nvidia-driver-* (or associated packages) to to_install
            if p.startswith("nvidia-driver-"):
                if any(pkg.startswith("nvidia-driver-") for pkg in to_install):
                    continue

            to_install.append(p)

            # See if runtimepm is supported
            if records['runtimepm']:
                # Create a file for nvidia-prime
                try:
                    pm_fd = open('/run/nvidia_runtimepm_supported', 'w')
                    pm_fd.write('\n')
                    pm_fd.close()
                except PermissionError:
                    # No need to error out here, since package
                    # installation will fail
                    pass
            # Add the matching linux modules package when available
            try:
                modules_package = get_linux_modules_metapackage(apt_cache, p)
                if modules_package and not apt_cache[modules_package].current_ver:
                    if not include_dkms and "dkms" in modules_package:
                        to_install.remove(p)
                        continue
                    to_install.append(modules_package)

                    lrm_meta = get_userspace_lrm_meta(apt_cache, p)
                    if lrm_meta and not apt_cache[lrm_meta].current_ver:
                        # Add the lrm meta and drop the non lrm one
                        to_install.append(lrm_meta)
                        to_install.remove(p)
                    break
            except KeyError:
                pass

    return to_install


def nvidia_desktop_pre_installation_hook(to_install):
    '''Applies changes that need to happen before installing the NVIDIA drivers'''

    # Enable KMS if nvidia >= 470
    for package_name in to_install:
        nvidia_info = NvidiaPkgNameInfo(package_name)
        if nvidia_info.get_major_version() >= 470:
            set_nvidia_kms(1)
            return


def nvidia_desktop_post_installation_hook():
    # If we are dealing with NVIDIA PRIME, and runtimepm
    # is supported, enable it
    if os.path.isfile('/run/nvidia_runtimepm_supported'):
        logging.debug('Trying to select the on-demand PRIME profile')
        try:
            subprocess.call(['/usr/bin/prime-select', 'on-demand'])
        except FileNotFoundError:
            pass

        # Create the override file for gpu-manager
        with open('/etc/u-d-c-nvidia-runtimepm-override', 'w') as f:
            f.write('# File created by ubuntu-drivers\n')


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

    # Check for metapackage-style names like nvidia-driver-535, nvidia-driver-535-server, etc.
    metapackage_pattern = re.compile('nvidia-driver-([0-9]+)(.*)')
    metapackage_match = metapackage_pattern.match(string)

    if metapackage_match:
        driver.vendor = 'nvidia'
        driver.flavour = '%s%s' % (metapackage_match.group(1), metapackage_match.group(2))
        return driver

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


def gpgpu_install_filter(packages, drivers_str, get_recommended=True):
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
        #      --gpgpu nvidia-driver-535-server
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
                    if get_recommended:
                        if packages[p].get('recommended'):
                            result[p] = packages[p]
                    else:
                        result[p] = packages[p]
                        # print('Found "recommended" flavour in %s' % (packages[p]))
                break
    return result


def auto_install_filter(packages, drivers_str='', get_recommended=True):
    '''Get packages which are appropriate for automatic installation.

    Return the subset of the given list of packages which are appropriate for
    automatic installation by the installer. This applies to e. g. the Broadcom
    Wifi driver (as there is no alternative), but not to the FGLRX proprietary
    graphics driver (as the free driver works well and FGLRX does not provide
    KMS).
    '''
    # any package which matches any of those globs will be accepted
    whitelist = ['bcmwl*', 'pvr-omap*', 'virtualbox-guest*', 'nvidia-*',
                 'open-vm-tools*', 'hwe-*-meta', 'oem-*-meta', 'broadcom-sta-dkms']

    # If users specify a driver, use gpgpu_install_filter()
    if drivers_str:
        results = gpgpu_install_filter(packages, drivers_str)
        return results

    allow = []
    for pattern in whitelist:
        allow.extend(fnmatch.filter(packages, pattern))

    result = {}
    for p in allow:
        if get_recommended:
            if 'recommended' not in packages[p] or packages[p]['recommended']:
                result[p] = packages[p]
        else:
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

    If you already have an existing apt_pkg.Cache() object, you can pass it as an
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
            apt_cache = apt_pkg.Cache(None)
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
                try:
                    package = apt_cache[pkg]
                    if _check_video_abi_compat(apt_cache, package):
                        packages.setdefault(fname, []).append(pkg)
                except KeyError:
                    logging.debug('Ignoring unavailable package %s from plugin %s', pkg, plugin)

    return packages


def _pkg_support_from_cache(x):
    '''Look up driver package and return their support level'''
    if lookup_cache.get(x):
        return lookup_cache.get(x).get('support')
    return None


def _pkg_open_preferred_from_cache(x):
    '''Look up driver and return if open package is preferred'''
    if lookup_cache.get(x):
        return lookup_cache.get(x).get('open_preferred')
    return False


def _get_fit_level(x):
    '''decide how well the package fits desktop environment'''

    # for desktop non-server packages are prefered to -server ones
    # if a package preferes open variants, these come on top

    if _pkg_open_preferred_from_cache(x):
        if re.search(r'(\d{3})-open$', x):
            return 3

        if re.search(r'(\d{3})$', x):
            return 2

        if re.search(r'(\d{3})-server-open$', x):
            return 1

        if re.search(r'(\d{3})-server$', x):
            return 0
    else:
        if re.search(r'(\d{3})$', x):
            return 3

        if re.search(r'(\d{3})-server$', x):
            return 2

        if re.search(r'(\d{3})-open$', x):
            return 1

        if re.search(r'(\d{3})-server-open$', x):
            return 0
    return 0


def _get_fit_level_gpgpu(x):
    '''decide how well the package fits server environment'''

    # for server environment -server packages are prefered to non-server ones
    # if a package preferes open variants, these come on top

    if _pkg_open_preferred_from_cache(x):
        if re.search(r'(\d{3})-server-open$', x):
            return 3

        if re.search(r'(\d{3})-server$', x):
            return 2

        if re.search(r'(\d{3})-open$', x):
            return 1

        if re.search(r'(\d{3})$', x):
            return 0
    else:
        if re.search(r'(\d{3})-server$', x):
            return 3

        if re.search(r'(\d{3})$', x):
            return 2

        if re.search(r'(\d{3})-server-open$', x):
            return 1

        if re.search(r'(\d{3})-open$', x):
            return 0
    return 0


def _cmp_gfx_alternatives(x, y):
    '''Compare two graphics driver names in terms of preference. (desktop)

    -open by default sorts after non-open, unless a driver preferes open variant
    -server always sorts after non-server.
    LTSB (Long Term Support Branch) always sorts before NFB (New Feature Branch).
    Legacy always sorts before Beta.
    '''

    if x.startswith('nvidia-') and y.startswith('nvidia-'):
        if _get_fit_level(x) > _get_fit_level(y):
            return 1
        if _get_fit_level(x) < _get_fit_level(y):
            return -1

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
        if _pkg_support_from_cache(x) == 'NFB' and _pkg_support_from_cache(y) != 'NFB':
            return -1
        if _pkg_support_from_cache(x) != 'NFB' and _pkg_support_from_cache(y) == 'NFB':
            return 1
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

    -open by default sorts after non-open, unless a driver preferes open variant
    -server always sorts before non-server.
    non server package always sorts after server package
    LTSB (Long Term Support Branch) always sorts before NFB (New Feature Branch).
    Legacy always sorts before Beta.
    '''

    if x.startswith('nvidia-') and y.startswith('nvidia-'):
        if _get_fit_level_gpgpu(x) > _get_fit_level_gpgpu(y):
            return 1
        if _get_fit_level_gpgpu(x) < _get_fit_level_gpgpu(y):
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
        if _pkg_support_from_cache(x) == 'NFB' and _pkg_support_from_cache(y) != 'NFB':
            return -1
        if _pkg_support_from_cache(x) != 'NFB' and _pkg_support_from_cache(y) == 'NFB':
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


def get_linux_image_from_meta(apt_cache, pkg):
    depcache = apt_pkg.DepCache(apt_cache)

    try:
        candidate = depcache.get_candidate_ver(apt_cache[pkg])
    except KeyError:
        logging.debug('No candidate for %s found' % pkg)
        return None

    try:
        for dep_list in candidate.depends_list_str.get('Depends'):
            for dep_name, dep_ver, dep_op in dep_list:
                if dep_name.startswith('linux-image-'):
                    return dep_name
    except (KeyError, TypeError):
        logging.debug('Could not check dependencies for %s package' % (pkg))
    # if apt_cache[pkg].candidate:
    #     record = apt_cache[pkg].candidate.record

    # try:
    #     deps = record['Depends']
    # except KeyError:
    #     return None

    # deps_list = deps.strip().split(', ')
    # for dep in deps_list:
    #     if dep.startswith('linux-image-'):
    #         return dep

    return None


def get_linux_modules_metapackage(apt_cache, candidate):
    '''Return the linux-modules-$driver metapackage for the system's kernel'''
    assert candidate is not None
    metapackage = None
    linux_flavour = ''
    linux_modules_match = ''

    depcache = apt_pkg.DepCache(apt_cache)

    nvidia_info = NvidiaPkgNameInfo(candidate)
    if not nvidia_info.is_valid:
        logging.debug('Non NVIDIA linux-modules packages are not supported at this time: %s. Skipping' % candidate)
        return metapackage

    if nvidia_info.has_obsolete_name_scheme():
        logging.debug('Legacy driver detected: %s. Skipping.' % candidate)
        return metapackage

    linux_image_meta = get_linux_image(apt_cache)
    # Check the actual image package, and find the flavour from there
    linux_image = get_linux_image_from_meta(apt_cache, linux_image_meta)

    if linux_image:
        linux_flavour = linux_image.replace('linux-image-', '')
    else:
        logging.debug('No linux-image can be found for %s. Skipping.' % candidate)
        return metapackage

    candidate_flavour = nvidia_info.get_flavour()
    linux_modules_candidate = 'linux-modules-nvidia-%s-%s' % (candidate_flavour, linux_flavour)

    try:
        package = apt_cache[linux_modules_candidate]
        # skip foreign architectures, we usually only want native
        package_candidate = depcache.get_candidate_ver(package)

        if (package_candidate and package_candidate.arch in ('all', get_apt_arch())):
            linux_version = get_linux_version(apt_cache)
            linux_modules_abi_candidate = 'linux-modules-nvidia-%s-%s' % (candidate_flavour, linux_version)
            logging.debug('linux_modules_abi_candidate: %s' % (linux_modules_abi_candidate))

            # Let's check if there is a candidate that is specific to
            # our kernel ABI. If not, things will fail.
            abi_specific = apt_cache[linux_modules_abi_candidate]
            # skip foreign architectures, we usually only want native
            abi_specific_candidate = depcache.get_candidate_ver(abi_specific)
            if (abi_specific_candidate and
                    abi_specific_candidate.arch in ('all', get_apt_arch())):
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
        reverse_deps = [dep.parent_pkg.name for dep in apt_cache[linux_modules_match].rev_depends_list
                        if dep.parent_pkg.name.startswith('linux-modules-nvidia-')]

        pick = ''
        candidate_suffix = get_linux_image(apt_cache).replace('linux-image-', '')
        if candidate_suffix == "virtual":
            candidate_suffix = "generic"
        modules_candidate = 'linux-modules-nvidia-%s-%s' % (candidate_flavour, candidate_suffix)

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
        package = apt_cache[dkms_package]
        package_candidate = depcache.get_candidate_ver(package)

        # skip foreign architectures, we usually only want native
        if (package_candidate and
                package_candidate.arch in ('all', get_apt_arch())):
            metapackage = dkms_package
    except KeyError:
        logging.error('No "%s" can be found.', dkms_package)
        pass

    return metapackage


def _load_grub_cfg(grub_cfg_path='/boot/grub/grub.cfg'):
    '''Load grub configuration file content.

    Args:
        grub_cfg_path: Path to grub.cfg file (default: /boot/grub/grub.cfg)

    Returns:
        String content of grub.cfg, or None if file doesn't exist or can't be read
    '''
    try:
        if not os.path.exists(grub_cfg_path):
            logging.debug('Could not read %s in _load_grub_cfg()', grub_cfg_path)
            return None

        with open(grub_cfg_path, 'r') as f:
            return f.read()
    except (OSError, IOError) as e:
        logging.debug(f"Error loading grub.cfg: ${e}")
        return None


def _parse_grub_cfg_for_kernel(grub_content, entry_num):
    '''Parse grub configuration content to find kernel version for given entry.

    Args:
        grub_content: Content of grub.cfg file as string
        entry_num: Entry identifier - either numeric index (as string) or entry ID

    Returns:
        Kernel version string, or None if not found
    '''
    if not grub_content:
        return None

    vmlinuz_entry_regex = r'linux\s+.*vmlinuz-([^\s]+)'
    try:
        lines = grub_content.split('\n')
        current_entry = None

        # According to
        # https://www.gnu.org/software/grub/manual/grub/html_node/Simple-configuration.html,
        # grub.cfg may also query off the "id" parameter (a string key).
        # Based off this doc (not using quotes, just space-delimited)
        # and Ubuntu's default (using variable expansion for "--id" and single-quotes),
        # we will parse for space, ', or " as delimiters.
        if not entry_num.isdigit():
            matches = []
            for line in lines:
                if line.strip().startswith('menuentry') and \
                    ((" " + entry_num + " ") in line.strip() or
                     ("'" + entry_num + "'") in line.strip() or
                     ("\"" + entry_num + "\"") in line.strip()):
                    current_entry = line.strip()
                elif line.strip().startswith('linux') and current_entry:
                    # Extract kernel version from linux line
                    match = re.search(vmlinuz_entry_regex, line)
                    if match:
                        matches.append(match.group(1))
                    current_entry = None
            # If there are != 1 matches, we should stop attempting to parse.
            # (unlikely w/ standard Ubuntu configs, since typical menuentry IDs
            # have distinct UUIDs, but theoretically possible if user tinkered
            # enough, which is really out of u-d-c's scope.)
            if len(matches) == 1:
                return matches[0]
            elif len(matches) > 1:
                print("Could not determine which of the following kernels will boot next: " + str(matches))
                return None
            else:
                print("Could not determine which kernel will boot next from /boot/grub/grub.cfg")
                return None

        # Walk through each line of grub.cfg and set current_entry when
        # we reach a line starting with "menuentry" to indicate that we are
        # in a menuentry stanza. Once a "linux" line is reached in the stanza,
        # strip the kernel version, append to menu_entries, then reset
        # current_entry to None to denote that we've parsed all relevant data
        # for this menuentry.
        # We make assumptions here that the user hasn't made any esoteric
        # manual modifications to their kernel image names, and that
        # they haven't modified their grub menu in ways that aren't visible to
        # /boot/grub/grub.cfg.
        menu_entries = []
        for line in lines:
            if line.strip().startswith('menuentry'):
                current_entry = line.strip()
            elif line.strip().startswith('linux') and current_entry:
                # Extract kernel version from linux line
                match = re.search(vmlinuz_entry_regex, line)
                if match:
                    menu_entries.append(match.group(1))
                current_entry = None

        # Return the kernel version for the requested entry
        entry_idx = int(entry_num)
        if 0 <= entry_idx < len(menu_entries):
            return menu_entries[entry_idx]

        logging.debug('Could not determine kernel in _parse_grub_cfg_for_kernel()')
        return None
    except (ValueError, IndexError) as e:
        logging.debug(f"Error in _parse_grub_cfg_for_kernel() ${e}")
        return None


def _get_kernel_from_grub_entry(entry_num):
    '''Convert grub entry number to kernel version by parsing grub.cfg.

    Args:
        entry_num: Entry identifier - either numeric index (as string) or entry ID

    Returns:
        Kernel version string, or None if not found
    '''
    grub_content = _load_grub_cfg()
    if grub_content is None:
        return None
    return _parse_grub_cfg_for_kernel(grub_content, entry_num)


def _get_actual_grub_default():
    '''Get the actual grub default entry by checking grub configuration'''
    try:
        # Check if GRUB_DEFAULT is set to a specific value
        grub_default_path = '/etc/default/grub'
        if not os.path.exists(grub_default_path):
            logging.debug('Could not read /etc/default/grub in _get_actual_grub_default()')
            return None

        with open(grub_default_path, 'r') as f:
            for line in f:
                if line.startswith('GRUB_DEFAULT='):
                    default_val = line.split('=', 1)[1].strip().strip('"\'')

                    if default_val.isdigit():
                        # Numeric entry
                        return _get_kernel_from_grub_entry(default_val)
                    elif default_val == 'saved':
                        # Check grubenv for saved entry
                        grubenv_path = '/boot/grub/grubenv'
                        if os.path.exists(grubenv_path):
                            with open(grubenv_path, 'r') as f2:
                                for env_line in f2:
                                    if env_line.startswith('saved_entry='):
                                        entry_num = env_line.split('=', 1)[1].strip()
                                        # Handle expandable menus, such as "Advanced options"
                                        # which have the form [menu_id]>[submenu_item_id]
                                        if '>' in entry_num:
                                            entry_num = env_line.split('>', 1)[1].strip()
                                        return _get_kernel_from_grub_entry(entry_num)
                    elif 'vmlinuz-' in default_val:
                        # Direct kernel path
                        match = re.search(r'vmlinuz-([^\s]+)', default_val)
                        if match:
                            return match.group(1)
                    else:
                        # String entry
                        return _get_kernel_from_grub_entry(default_val)
                    break

        logging.debug('Could not read /etc/default/grub in _get_actual_grub_default()')
        return None

    except (OSError, IOError) as e:
        logging.debug(f"Error in _get_actual_grub_default() ${e}")
        return None


def _resolve_nvidia_module_path_for_kernel(kernel_version):
    """Return the path to the NVIDIA kernel module for a given kernel version, if present.

    Uses find to search for nvidia.ko* files in the kernel modules directory.
    """

    if not kernel_version:
        logging.debug("Kernel not known, giving up on _resolve_nvidia_module_path_for_kernel()")
        return None

    modules_dir = f'/lib/modules/{kernel_version}'
    if not os.path.exists(modules_dir):
        logging.debug(f"Module directory {modules_dir} does not exist")
        return None

    # Use find to locate nvidia.ko* files (including compressed variants)
    result = subprocess.check_output(
        ['find', modules_dir, '-name', 'nvidia.ko*', '-type', 'f'],
        universal_newlines=True,
        stderr=subprocess.DEVNULL
    )

    # Get the first match if any
    matches = result.strip().split('\n')
    if matches and matches[0]:
        return matches[0]

    logging.debug("_resolve_nvidia_module_path_for_kernel() returned None")
    return None


def check_nvidia_module_status():
    '''Check NVIDIA module status and kernel compatibility.

    Returns:
        dict: Contains information about NVIDIA module status:
            - 'loaded': bool - Whether nvidia module is currently loaded
            - 'current_module_path': str or None - Path to current nvidia module
            - 'next_boot_kernel': str or None - Next boot kernel version
            - 'next_boot_module_path': str or None - Path to nvidia module for next boot kernel
            - 'needs_reboot': bool - Whether a reboot is needed
            - 'module_missing': bool - Whether nvidia module is missing for next boot kernel
    '''

    result = {
        'loaded': False,
        'current_module_path': None,
        'next_boot_kernel': None,
        'next_boot_module_path': None,
        'needs_reboot': False,
        'module_missing': False
    }

    # Check if nvidia module is loaded
    try:
        lsmod_output = subprocess.check_output(
            ['lsmod'], universal_newlines=True)
        # Check for exact module name match (first column in lsmod output)
        result['loaded'] = False
        for line in lsmod_output.splitlines():
            # lsmod format: module_name size used_by
            # Split and check first field for exact match
            parts = line.split()
            if parts and parts[0] == 'nvidia':
                result['loaded'] = True
                break
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logging.debug(f"Exception in loaded module check: ${e}")
        pass

    # Get current nvidia module info if loaded
    if result['loaded']:
        try:
            modinfo_output = subprocess.check_output(['modinfo', 'nvidia'], universal_newlines=True)
            for line in modinfo_output.splitlines():
                if line.startswith('filename:'):
                    result['current_module_path'] = line.split(':', 1)[1].strip()
                    break
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.debug(f"Exception in module path check: ${e}")
            pass

    result['next_boot_kernel'] = _get_actual_grub_default()

    # If we cannot determine the next boot kernel definitively,
    # don't make any assumptions about module / system state.
    if not result['next_boot_kernel']:
        result['needs_reboot'] = False
        result['module_missing'] = False
        result['next_boot_module_path'] = None
        return result

    current_kernel = os.uname().release
    result['needs_reboot'] = bool(result['next_boot_kernel'] and result['next_boot_kernel'] != current_kernel)

    # Always try to resolve the next boot module path (even if kernels match)
    next_path = _resolve_nvidia_module_path_for_kernel(result['next_boot_kernel'])
    if next_path:
        result['next_boot_module_path'] = next_path
    else:
        result['module_missing'] = True
        # Optional: provide debug context
        result['debug_info'] = {
            'checked_kernel': result['next_boot_kernel']
        }

    return result


def gather_welcome_page_data():
    '''Gather data for the welcome page.

    Returns:
        dict: A dictionary containing:
            - cache_error: Error message if cache couldn't be loaded, or None
            - nvidia_drivers: List of installed NVIDIA driver packages
            - oem_packages: List of installed OEM packages
            - nvidia_status: NVIDIA module status dict, or None if not applicable
            - nvidia_status_error: Error message if status check failed, or None
    '''
    data = {
        'cache_error': None,
        'nvidia_drivers': [],
        'oem_packages': [],
        'nvidia_status': None,
        'nvidia_status_error': None
    }

    # Initialize apt cache
    apt_pkg.init_config()
    apt_pkg.init_system()

    try:
        cache = apt_pkg.Cache(None)
    except Exception as ex:
        data['cache_error'] = str(ex)
        return data

    # Get installed NVIDIA drivers
    data['nvidia_drivers'] = get_installed_packages_by_glob(
        cache, "nvidia-driver-*") or \
        get_installed_packages_by_glob(cache, "linux-modules-nvidia-*")

    # Get installed OEM meta packages
    data['oem_packages'] = get_installed_packages_by_glob(
        cache, "oem-*-meta")

    # Check NVIDIA module status if NVIDIA drivers are installed
    if data['nvidia_drivers']:
        try:
            data['nvidia_status'] = check_nvidia_module_status()
        except Exception as e:
            data['nvidia_status_error'] = str(e)

    return data
