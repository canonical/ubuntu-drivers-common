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

from subprocess import Popen


class KernelDetection(object):

    def __init__(self, cache=None):
        if cache:
            self.apt_cache = cache
            self.apt_depcache = apt_pkg.DepCache(cache)
        else:
            apt_pkg.init_config()
            apt_pkg.init_system()
            self.apt_cache = apt_pkg.Cache(None)
            self.apt_depcache = apt_pkg.DepCache(cache)

    def _is_greater_than(self, term1, term2):
        # We don't want to take into account
        # the flavour
        pattern = re.compile('(.+)-([0-9]+)-(.+)')
        match1 = pattern.match(term1)
        match2 = pattern.match(term2)
        if match1:
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

    def _get_linux_flavour(self, candidates, image):
        pattern = re.compile(r'linux-image-([0-9]+\.[0-9]+\.[0-9]+)-([0-9]+)-(.+)')
        match = pattern.match(image)
        flavour = ''
        if match:
            flavour = match.group(3)

        return flavour

    def _filter_cache(self, pkg):
        package_name = pkg.name
        if (package_name.startswith('linux-image') and
            'extra' not in package_name and (pkg.current_ver or
                                             self.apt_depcache.marked_install(pkg))):
            return package_name
        else:
            return None

    def _get_linux_metapackage(self, target):
        '''Get the linux headers, linux-image or linux metapackage'''
        metapackage = ''
        image_package = ''
        version = ''
        prefix = 'linux-%s' % ('headers' if target == 'headers' else 'image')

        pattern = re.compile('linux-image-(.+)-([0-9]+)-(.+)')

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
                                    .rev_depends_list if dep.parent_pkg.name.startswith(prefix)]

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
                                            .rev_depends_list if dep.parent_pkg.name.startswith('linux-')]
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

    def get_linux_headers_metapackage(self):
        '''Get the linux headers for the newest_kernel installed'''
        return self._get_linux_metapackage('headers')

    def get_linux_image_metapackage(self):
        '''Get the linux headers for the newest_kernel installed'''
        return self._get_linux_metapackage('image')

    def get_linux_metapackage(self):
        '''Get the linux metapackage for the newest_kernel installed'''
        return self._get_linux_metapackage('meta')

    def get_linux_version(self):
        linux_image_meta = self.get_linux_image_metapackage()
        linux_version = ''
        try:
            # dependencies = self.apt_cache[linux_image_meta].candidate.\
            #                  record['Depends']
            candidate = self.apt_depcache.get_candidate_ver(self.apt_cache[linux_image_meta])
            for dep_list in candidate.depends_list_str.get('Depends'):
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
