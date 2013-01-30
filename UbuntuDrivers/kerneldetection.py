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

import apt
import logging
import re

from subprocess import Popen


class KernelDetection(object):

    def __init__(self, cache=None):
        if cache:
            self.apt_cache = cache
        else:
            self.apt_cache = apt.Cache()

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

    def _get_linux_metapackage(self, headers):
        '''Get the linux headers or linux metapackage'''
        suffix = headers and '-headers' or ''
        pattern = re.compile('linux-image-(.+)-([0-9]+)-(.+)')
        source_pattern = re.compile('linux-(.+)')

        metapackage = ''
        version = ''
        for pkg in self.apt_cache:
            if ('linux-image' in pkg.name and
                'extra' not in pkg.name and
                self.apt_cache[pkg.name].is_installed or
                self.apt_cache[pkg.name].marked_install):
                match = pattern.match(pkg.name)
                # Here we filter out packages such as
                # linux-generic-lts-quantal
                if match:
                    source = self.apt_cache[pkg.name].candidate.\
                             record['Source']
                    current_version = '%s-%s' % (match.group(1),
                                                 match.group(2))
                    # See if the current version is greater than
                    # the greatest that we've found so far
                    if self._is_greater_than(current_version,
                                             version):
                        version = current_version
                        match_source = source_pattern.match(source)
                        # Set the linux-headers metapackage
                        if '-lts-' in source and match_source:
                            # This is the case of packages such as
                            # linux-image-3.5.0-18-generic which
                            # comes from linux-lts-quantal.
                            # Therefore the linux-headers-generic
                            # metapackage would be wrong here and
                            # we should use
                            # linux-headers-generic-lts-quantal
                            # instead
                            metapackage = 'linux%s-%s-%s' % (
                                           suffix,
                                           match.group(3),
                                           match_source.group(1))
                        else:
                            # The scheme linux-headers-$flavour works
                            # well here
                            metapackage = 'linux%s-%s' % (
                                           suffix,
                                           match.group(3))
        return metapackage

    def get_linux_headers_metapackage(self):
        '''Get the linux headers for the newest_kernel installed'''
        return self._get_linux_metapackage(True)

    def get_linux_metapackage(self):
        '''Get the linux metapackage for the newest_kernel installed'''
        return self._get_linux_metapackage(False)
