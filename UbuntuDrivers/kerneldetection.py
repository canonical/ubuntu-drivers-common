#
#       kerneldetection.py
#
#       Copyright 2013 Canonical Ltd.
#
#       Author: Alberto Milone <alberto.milone@canonical.com>
#
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.

import apt_pkg
import logging
import re
from typing import Optional, Tuple, List

from subprocess import Popen, PIPE
import os


class KernelDetection(object):

    def __init__(self, cache: Optional[apt_pkg.Cache] = None) -> None:
        if cache:
            self.apt_cache = cache
            self.apt_depcache = apt_pkg.DepCache(cache)
        else:
            apt_pkg.init_config()
            apt_pkg.init_system()
            self.apt_cache = apt_pkg.Cache(None)
            self.apt_depcache = apt_pkg.DepCache(self.apt_cache)

    def _is_greater_than(self, term1: str, term2: str) -> bool:
        # We don't want to take into account
        # the flavour
        pattern = re.compile('(.+)-([0-9]+)-(.+)')
        match1 = pattern.match(term1)
        match2 = pattern.match(term2)
        if match1 and match2:
            term1 = '%s-%s' % (match1.group(1),
                               match1.group(2))
            term2 = '%s-%s' % (match2.group(1),
                               match2.group(2))

        logging.debug('Comparing %s with %s' % (term1, term2))
        command = 'dpkg --compare-versions %s gt %s' % \
                  (term1, term2)
        process = Popen(command.split(' '))
        process.communicate()
        return not process.returncode

    def _get_linux_flavour(self, candidates: List[str], image: str) -> str:
        pattern = re.compile(r'linux-image-([0-9]+\.[0-9]+\.[0-9]+)-([0-9]+)-(.+)')
        match = pattern.match(image)
        flavour = ''
        if match:
            flavour = match.group(3)

        return flavour

    def _filter_cache(self, pkg: apt_pkg.Package) -> Optional[str]:
        package_name = pkg.name
        if (package_name.startswith('linux-image') and
            'extra' not in package_name and (pkg.current_ver or
                                             self.apt_depcache.marked_install(pkg))):
            return package_name
        else:
            return None

    def _get_linux_metapackage(self, target: str) -> str:
        '''Get the linux headers, linux-image or linux metapackage'''
        metapackage = ''
        image_package = ''
        version = ''
        prefix = 'linux-%s' % ('headers' if target == 'headers' else 'image')

        pattern = re.compile('linux-image-(?:unsigned-)?(.+)-([0-9]+)-(.+)')

        for package_name in map(self._filter_cache, self.apt_cache.packages):
            if package_name:
                match = pattern.match(package_name)
                # Here we filter out packages other than
                # the actual image or header packages
                if match:
                    current_package = match.group(0)
                    current_version = '%s-%s' % (match.group(1),
                                                 match.group(2))
                    # See if the current version is greater than
                    # the greatest that we've found so far
                    if self._is_greater_than(current_version,
                                             version):
                        version = current_version
                        image_package = current_package

        if version:
            if target == 'headers':
                target_package = image_package.replace('image', 'headers')
            else:
                target_package = image_package

            reverse_dependencies = [dep.parent_pkg.name for dep in self.apt_cache[target_package]
                                    .rev_depends_list if dep.parent_pkg.name.startswith(prefix)]  # type: ignore[attr-defined]

            if reverse_dependencies:
                # This should be something like linux-image-$flavour
                # or linux-headers-$flavour
                metapackage = ''
                for candidate in reverse_dependencies:
                    try:
                        candidate_pkg = self.apt_cache[candidate]
                        if (candidate.startswith(prefix) and (candidate_pkg and
                           (candidate_pkg.current_ver or self.apt_depcache.marked_install(candidate_pkg))) and
                           candidate.replace(prefix, '') > metapackage.replace(prefix, '')):
                            metapackage = candidate
                    except KeyError:
                        continue
                # if we are looking for headers, then we are good
                if target == 'meta':
                    # Let's get the metapackage
                    reverse_dependencies = [dep.parent_pkg.name for dep in self.apt_cache[metapackage]
                                            .rev_depends_list if dep.parent_pkg.name.startswith('linux-')]  # type: ignore[attr-defined]
                    if reverse_dependencies:
                        flavour = self._get_linux_flavour(reverse_dependencies, target_package)
                        linux_meta = ''
                        for meta in reverse_dependencies:
                            # For example linux-generic-hwe-20.04
                            if meta.startswith('linux-%s-' % (flavour)):
                                linux_meta = meta
                                break
                        # This should be something like linux-$flavour
                        if not linux_meta:
                            # Try the 1st reverse dependency
                            metapackage = reverse_dependencies[0]
                        else:
                            metapackage = linux_meta
        return metapackage

    def get_linux_headers_metapackage(self) -> str:
        '''Get the linux headers for the newest_kernel installed'''
        return self._get_linux_metapackage('headers')

    def get_linux_image_metapackage(self) -> str:
        '''Get the linux headers for the newest_kernel installed'''
        return self._get_linux_metapackage('image')

    def get_linux_metapackage(self) -> str:
        '''Get the linux metapackage for the newest_kernel installed'''
        return self._get_linux_metapackage('meta')

    def get_linux_version(self) -> Optional[str]:
        linux_image_meta = self.get_linux_image_metapackage()
        linux_version = None
        try:
            # dependencies = self.apt_cache[linux_image_meta].candidate.\
            #                  record['Depends']
            candidate = self.apt_depcache.get_candidate_ver(self.apt_cache[linux_image_meta])
            if candidate:
                for dep_list in candidate.depends_list_str.get('Depends'):  # type: ignore[attr-defined]
                    for dep_name, dep_ver, dep_op in dep_list:
                        if dep_name.startswith('linux-image'):
                            linux_version = dep_name.strip().replace('linux-image-', '')
                            break
        except KeyError:
            logging.error('No dependencies can be found for %s' % (linux_image_meta))
            return None

        # if ', ' in dependencies:
        #     deps = dependencies.split(', ')
        #     for dep in deps:
        #         if dep.startswith('linux-image'):
        #             linux_version = dep.replace('linux-image-', '')
        # else:
        #     if dependencies.strip().startswith('linux-image'):
        #         linux_version = dependencies.strip().replace('linux-image-', '')

        return linux_version

    def is_running_kernel_outdated(self) -> Tuple[bool, str, Optional[str], bool]:
        '''Check if running kernel is outdated.

        Returns a tuple (is_outdated, running_version, latest_version, requires_dkms):
            is_outdated: True if the kernel is outdated
            running_version: version string of the running kernel
            latest_version: version string of the latest available kernel
            requires_dkms: True if DKMS modules are required
        '''
        logging.debug('Checking if running kernel is outdated')

        # Get running kernel version
        running_version = os.uname().release
        logging.debug('Running kernel version: %s', running_version)

        # Check if running kernel matches expected format (if not, DKMS required)
        # We make an assumption that a system on a non-ubuntu kernel version format
        # is not on an Ubuntu prebuilt kernel upgrade path, and thus cannot benefit from prebuilt modules.
        if not re.match(r'\d+\.\d+\.\d+-\d+', running_version):
            logging.debug('Running kernel version does not match expected format - DKMS required')
            return False, running_version, None, True

        # Get list of installed kernel metapackages. If any are upgradable, we should warn the
        # user to upgrade before proceeding.
        # We make an assumption that any of the installed kernels could be the next default boot
        # option (not necessarily just the currently running one) - and thus we should advise that
        # any update candidates are applied before proceeding.
        meta_pkgs = []
        for pkg in self.apt_cache.packages:
            if not pkg.current_ver:
                continue
            if not pkg.name.startswith('linux-image-'):
                continue
            # Skip actual kernel image packages
            if re.match(r'linux-image-(\d+\.\d+\.\d+-\d+|\w*unsigned-\d+\.\d+\.\d+-\d+)', pkg.name):
                continue
            meta_pkgs.append(pkg)
            logging.debug('Found installed kernel metapackage: %s', pkg.name)

        for meta_pkg in meta_pkgs:
            logging.debug('Checking metapackage %s for updates', meta_pkg.name)

            # Check if this metapackage has an update available
            candidate = self.apt_depcache.get_candidate_ver(meta_pkg)
            if not candidate:
                logging.debug('No candidate version for %s', meta_pkg.name)
                continue

            if not self.apt_depcache.is_upgradable(meta_pkg):
                logging.debug('No update available for %s', meta_pkg.name)
                continue

            # Check candidate dependencies for new kernel version
            for dep in candidate.depends_list.get('Depends', []):
                for dep_or in dep:
                    if not dep_or.target_pkg.name.startswith('linux-image-'):
                        continue
                    if not re.match(r'linux-image-\d+\.\d+\.\d+-\d+', dep_or.target_pkg.name):
                        continue

                    latest_version = dep_or.target_pkg.name.split('linux-image-')[1]
                    logging.debug('Found new kernel version %s from %s', latest_version, meta_pkg.name)

                    return True, running_version, latest_version, False

        logging.debug('No kernel updates found')
        return False, running_version, None, False

    def get_kernel_update_warning(self, include_dkms: bool = False) -> bool:
        '''Print a warning message if the kernel needs updating.

        Returns:
            should_exit: True if the caller should exit (e.g. DKMS required but not included)
        '''
        is_outdated, running, latest, requires_dkms = self.is_running_kernel_outdated()

        if requires_dkms:
            if not include_dkms:
                # Check Secure Boot state using mokutil
                try:
                    process = Popen(['mokutil', '--sb-state'], stdout=PIPE, stderr=PIPE)
                    output_bytes, err_bytes = process.communicate()
                    output: str = output_bytes.decode('utf-8').lower()
                    err: str = err_bytes.decode('utf-8').lower()
                    if 'secureboot enabled' in output or 'secure boot enabled' in output:
                        print(
                            "Your running kernel (%s) requires DKMS modules, and you have Secure Boot enabled. "
                            "To proceed, ensure you have access to your machine’s UEFI menu and have the rights "
                            "to enroll a Machine Owner Key (MOK), "
                            "then re-run ubuntu-drivers with --include-dkms. This will install the DKMS modules, "
                            "then prompt you to enroll the new MOK and reboot."
                            % running
                        )
                        return True
                    elif 'secureboot disabled' in output or 'secure boot disabled' in output:
                        print(
                            "Your running kernel (%s) requires DKMS modules. You have Secure Boot disabled, but if "
                            "you enable it in the future, you will need to sign or reinstall these DKMS modules for "
                            "them to work. "
                            "If you would like to continue, please re-run ubuntu-drivers with --include-dkms."
                            % running
                        )
                        return True
                    elif 'this system doesn\'t support secure boot' in err:
                        print(
                            "Your running kernel (%s) requires DKMS modules. Please use --include-dkms if you want"
                            " to proceed."
                            % running
                        )
                        return True
                    # else: fall through to generic response
                except Exception as e:
                    logging.warning('Could not determine Secure Boot state: %s', str(e))
                    # fall through to generic response

                # fallback generic response - n
                print(
                    "Your running kernel (%s) requires DKMS modules, and ubuntu-drivers was unable to determine if"
                    " Secure Boot is enabled. If you have SB enabled, you will need to enroll a MOK to proceed, "
                    "which will require access to your UEFI menu and administrative privileges. Please use "
                    "--include-dkms if you want to proceed."
                    % running
                )
                return True
            else:
                # DKMS is allowed via --include-dkms, so no exit needed
                return False

        if is_outdated and latest:
            print(
                f"Warning: Your running kernel ({running}) is outdated. "
                f"A newer kernel ({latest}) is available in the Ubuntu archives. "
                f"Please run 'sudo apt update && sudo apt upgrade' to update your system."
            )
        # Outdated kernel is only a warning, not a blocker
        return False
