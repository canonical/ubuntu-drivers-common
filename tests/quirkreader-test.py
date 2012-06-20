#!/usr/bin/python3
# -*- coding: utf-8 -*-
# (c) 2012 Canonical Ltd.
#
# Authors: Alberto Milone <alberto.milone@canonical.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

from Quirks import quirkreader, quirkapplier
from xkit import xorgparser
from xkit.xorgparser import *
import sys
import unittest
import os
import logging
import settings
import tempfile
import copy


source = settings.inputFile
destination = settings.inputDir
destinationFile = os.path.join(settings.outputDir, 'quirksreader_test.txt')
tempFile = os.path.join(destination, 'tmp')

def get_quirks_from_file(quirk_file):
    '''check all the files in a directory looking for quirks'''
    # read other blacklist files (which we will not touch, but evaluate)
    quirk_file = quirkreader.ReadQuirk(quirk_file)
    return quirk_file.get_quirks()

class QuirkReaderTestCase(unittest.TestCase):
    
    #def setUp(self):
        #self.quirk_file = quirkreader.ReadQuirk(quirk_file)
        #self.quirks = self.quirk_file.get_quirks()
    
    def tearDown(self):
        #self.parser.comments.insert(0, '\n-----' + self.this_function_name + '-----\n')
        #self.parser.write(destinationFile, test=True)
        try:
            os.remove(tempFile)
        except(OSError, IOError):
            pass

    def test_read_quirk1(self):
        '''1 Matching config file'''
        self.this_function_name = sys._getframe().f_code.co_name
        section = 'Screen'
        identifier = 'Display'
        option = 'Depth'
        
        with open(tempFile, 'w') as confFile:
            confFile.write('''
Section "Quirk"
    Identifier "Test Latitude E6530"
    Handler "nvidia-current|nvidia-current-updates"
    Match "sys_vendor" "Dell Inc."
    Match "product_name" "Latitude E6530"
    XorgSnippet
        Section "Device"
            Identifier "My Card"
            Driver "nvidia"
            Option "NoLogo" "True"
        EndSection

        Section "Screen"
            Identifier "My Screen"
            Option "RegistryDwords" "EnableBrightnessControl=1"
        EndSection
    EndXorgSnippet
EndSection
''')
        #os.system('cat %s' % tempFile)
        #loglevel = logging.DEBUG
    #else:
        #loglevel = logging.INFO

        #logging.basicConfig(format='%(levelname)s:%(message)s', level=loglevel)
        a = quirkapplier.QuirkChecker('nvidia-current', path=destination)

        # Override DMI
        a._system_info = {'sys_vendor': 'Dell Inc.',
                          'bios_vendor': 'American Megatrends Inc.',
                          'product_version': 'System Version',
                          'board_name': 'P6T SE',
                          'bios_date': '01/19/2009',
                          'bios_version': '0106',
                          'product_name': 'Latitude E6530',
                          'board_vendor': 'ASUSTeK Computer INC.'}
        quirk_found = False
        quirk_matches = False

        for quirk in a._quirks:
            if a._handler.lower() in [x.lower().strip() for x in quirk.handler]:
                quirk_found = True

                logging.debug('Processing quirk %s' % quirk.id)
                #self.assertTrue(a.matches_tags(quirk))
                if a.matches_tags(quirk):
                    # Do something here
                    logging.debug('Quirk matches')
                    quirk_matches = True
                else:
                    logging.debug('Quirk doesn\'t match')

        self.assertTrue(quirk_found)
        self.assertTrue(quirk_matches)

    def test_read_quirk2(self):
        '''2 Not matching config file''' 
        self.this_function_name = sys._getframe().f_code.co_name
        section = 'Screen'
        identifier = 'Display'
        option = 'Depth'
        
        with open(tempFile, 'w') as confFile:
            confFile.write('''
Section "Quirk"
    Identifier "Test Latitude E6530"
    Handler "nvidia-current|nvidia-current-updates"
    Match "sys_vendor" "Dell Inc."
    Match "product_name" "Latitude E6530"
    XorgSnippet
        Section "Device"
            Identifier "My Card"
            Driver "nvidia"
            Option "NoLogo" "True"
        EndSection

        Section "Screen"
            Identifier "My Screen"
            Option "RegistryDwords" "EnableBrightnessControl=1"
        EndSection
    EndXorgSnippet
EndSection


''')
        #os.system('cat %s' % tempFile)
        #loglevel = logging.DEBUG
    #else:
        #loglevel = logging.INFO

        #logging.basicConfig(format='%(levelname)s:%(message)s', level=loglevel)
        a = quirkapplier.QuirkChecker('nvidia-current', path=destination)

        # Override DMI
        a._system_info = {'sys_vendor': 'Fake',
                          'bios_vendor': 'American Megatrends Inc.',
                          'product_version': 'System Version',
                          'board_name': 'P6T SE',
                          'bios_date': '01/19/2009',
                          'bios_version': '0106',
                          'product_name': 'Fake product',
                          'board_vendor': 'ASUSTeK Computer INC.'}
        quirk_found = False
        quirk_matches = True

        for quirk in a._quirks:
            if a._handler.lower() in [x.lower().strip() for x in quirk.handler]:
                quirk_found = True

                logging.debug('Processing quirk %s' % quirk.id)
                # It doesn't have to match
                self.assertTrue(not a.matches_tags(quirk))
                if a.matches_tags(quirk):
                    # Do something here
                    logging.debug('Quirk matches')
                else:
                    logging.debug('Quirk doesn\'t match')
                    quirk_matches = False

        self.assertTrue(quirk_found)
        self.assertTrue((quirk_matches == False))

    def test_read_quirk3(self):
        '''3 Matching quirk aimed at multiple products'''
        self.this_function_name = sys._getframe().f_code.co_name
        section = 'Screen'
        identifier = 'Display'
        option = 'Depth'
        
        with open(tempFile, 'w') as confFile:
            confFile.write('''
Section "Quirk"
    Identifier "Test Latitude E6530"
    Handler "nvidia-current|nvidia-current-updates"
    Match "sys_vendor" "Dell Inc."
    Match "product_name" "Latitude E6530|Latitude E6535"
    XorgSnippet
        Section "Device"
            Identifier "My Card"
            Driver "nvidia"
            Option "NoLogo" "True"
        EndSection

        Section "Screen"
            Identifier "My Screen"
            Option "RegistryDwords" "EnableBrightnessControl=1"
        EndSection
    EndXorgSnippet
EndSection


''')
        #os.system('cat %s' % tempFile)
        #loglevel = logging.DEBUG
    #else:
        #loglevel = logging.INFO

        #logging.basicConfig(format='%(levelname)s:%(message)s', level=loglevel)
        a = quirkapplier.QuirkChecker('nvidia-current', path=destination)

        # Override DMI
        a._system_info = {'sys_vendor': 'Dell Inc.',
                          'bios_vendor': 'American Megatrends Inc.',
                          'product_version': 'System Version',
                          'board_name': 'P6T SE',
                          'bios_date': '01/19/2009',
                          'bios_version': '0106',
                          'product_name': 'Latitude E6535',
                          'board_vendor': 'ASUSTeK Computer INC.'}
        quirk_found = False
        quirk_matches = False

        for quirk in a._quirks:
            if a._handler.lower() in [x.lower().strip() for x in quirk.handler]:
                quirk_found = True

                logging.debug('Processing quirk %s' % quirk.id)
                # Let's test only the quirk that matters
                if quirk.id == "Test Latitude E6530":
                    self.assertTrue(a.matches_tags(quirk))
                    if a.matches_tags(quirk):
                        # Do something here
                        logging.debug('Quirk matches')
                        quirk_matches = True
                    else:
                        logging.debug('Quirk doesn\'t match')

        self.assertTrue(quirk_found)
        self.assertTrue(quirk_matches)


    def test_read_quirk4(self):
        '''3 Matching quirk aimed at multiple products only one should match'''
        self.this_function_name = sys._getframe().f_code.co_name
        section = 'Screen'
        identifier = 'Display'
        option = 'Depth'
        
        with open(tempFile, 'w') as confFile:
            confFile.write('''
Section "Quirk"
    Identifier "Test Latitude E6530"
    Handler "nvidia-current|nvidia-current-updates"
    Match "sys_vendor" "Dell Inc."
    Match "product_name" "Latitude E6530|Latitude E6535"
    XorgSnippet
        Section "Device"
            Identifier "My Card"
            Driver "nvidia"
            Option "NoLogo" "True"
        EndSection

        Section "Screen"
            Identifier "My Screen"
            Option "RegistryDwords" "EnableBrightnessControl=1"
        EndSection
    EndXorgSnippet
EndSection


''')
        #os.system('cat %s' % tempFile)
        #loglevel = logging.DEBUG
    #else:
        #loglevel = logging.INFO

        #logging.basicConfig(format='%(levelname)s:%(message)s', level=loglevel)
        a = quirkapplier.QuirkChecker('nvidia-current', path=destination)

        # Override DMI
        a._system_info = {'sys_vendor': 'Dell Inc.',
                          'bios_vendor': 'American Megatrends Inc.',
                          'product_version': 'System Version',
                          'board_name': 'P6T SE',
                          'bios_date': '01/19/2009',
                          'bios_version': '0106',
                          'product_name': 'Latitude E6535',
                          'board_vendor': 'ASUSTeK Computer INC.'}
        quirk_found = False
        quirk_matches = False
        matches_number = 0

        for quirk in a._quirks:
            if a._handler.lower() in [x.lower().strip() for x in quirk.handler]:
                quirk_found = True

                logging.debug('Processing quirk %s' % quirk.id)
                # Let's test only the quirk that matters
                if quirk.id == "Test Latitude E6530":
                    self.assertTrue(a.matches_tags(quirk))
                    if a.matches_tags(quirk):
                        # Do something here
                        logging.debug('Quirk matches')
                        quirk_matches = True
                        matches_number += 1
                    else:
                        logging.debug('Quirk doesn\'t match')

        self.assertTrue(quirk_found)
        self.assertTrue(quirk_matches)
        self.assertTrue(matches_number == 1)


def main():
    return 0

if __name__ == '__main__':
    main()

