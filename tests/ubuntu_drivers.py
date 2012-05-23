# (C) 2012 Canonical Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import time
import unittest
import subprocess
import resource
import sys

from gi.repository import GLib
from gi.repository import PackageKitGlib
import apt
import aptdaemon.test
import aptdaemon.pkcompat

import UbuntuDrivers.detect
import UbuntuDrivers.PackageKit

import fakesysfs

TEST_DIR = os.path.abspath(os.path.dirname(__file__))

# show aptdaemon log in test output?
APTDAEMON_LOG = False
# show aptdaemon debug level messages?
APTDAEMON_DEBUG = False

dbus_address = None


def gen_fakesys():
    '''Generate a fake SysFS object for testing'''
    s = fakesysfs.SysFS()
    # covered by vanilla.deb
    s.add('pci', 'white', {'modalias': 'pci:v00001234d00sv00000001sd00bc00sc00i00'})
    # covered by chocolate.deb
    s.add('usb', 'black', {'modalias': 'usb:v9876dABCDsv01sd02bc00sc01i05'})
    # not covered by any driver package
    s.add('pci', 'grey', {'modalias': 'pci:vDEADBEEFd00'})
    s.add('ssb', 'yellow', {}, {'MODALIAS': 'pci:vDEADBEEFd00'})

    return s

class PackageKitTest(aptdaemon.test.AptDaemonTestCase):
    '''Test the PackageKit plugin and API'''

    @classmethod
    def setUpClass(klass):
        # find plugin in our source tree
        os.environ['PYTHONPATH'] = '%s:%s' % (os.getcwd(), os.environ.get('PYTHONPATH', ''))

        # start a local fake system D-BUS
        klass.dbus = subprocess.Popen(['dbus-daemon', '--nofork', '--print-address',
            '--config-file', 
            os.path.join(aptdaemon.test.get_tests_dir(), 'dbus.conf')],
            stdout=subprocess.PIPE)
        klass.dbus_address = klass.dbus.stdout.readline().strip()
        os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = klass.dbus_address

        # set up a test chroot
        klass.chroot = aptdaemon.test.Chroot()
        klass.chroot.setup()
        klass.chroot.add_test_repository()
        klass.chroot.add_repository(os.path.join(TEST_DIR, 'archive'), True, False)

        # start aptdaemon on fake system D-BUS; this works better than
        # self.start_session_aptd() as the latter starts/stops aptadaemon on
        # each test case, which currently fails with the PK compat layer
        if APTDAEMON_LOG:
            out = None
        else:
            out = subprocess.PIPE
        argv = ['aptd', '--disable-plugins', '--chroot', klass.chroot.path]
        if APTDAEMON_DEBUG:
            argv.insert(1, '--debug')
        klass.aptdaemon = subprocess.Popen(argv, stderr=out)
        time.sleep(0.5)

    @classmethod
    def tearDownClass(klass):
        klass.aptdaemon.terminate()
        klass.aptdaemon.wait()
        klass.dbus.terminate()
        klass.dbus.wait()
        klass.chroot.remove()

    def setUp(self):
        self.start_fake_polkitd()
        time.sleep(0.5)
        self.pk = PackageKitGlib.Client()

    def test_query(self):
        '''modalias query'''

        # type ANY
        self.assertEqual(self._call(PackageKitGlib.ProvidesEnum.ANY,
                                    ['pci:v00001234d00000001sv00sd01bc02sc03i04']),
                         ['vanilla'])

        # type MODALIAS
        self.assertEqual(self._call(PackageKitGlib.ProvidesEnum.MODALIAS,
                                    ['pci:v00001234d00000001sv00sd01bc02sc03i04']),
                         ['vanilla'])
        self.assertEqual(self._call(PackageKitGlib.ProvidesEnum.MODALIAS,
                                    ['usb:v9876dABCDsv00sd00bc00sc01i01']),
                         ['chocolate'])

        # chocolate does not match interface type != 00, just vanilla does
        self.assertEqual(self._call(PackageKitGlib.ProvidesEnum.MODALIAS,
                                    ['pci:v0000BEEFd0sv00sd00bc00sc00i01']),
                         ['vanilla'])

        # no such device
        self.assertEqual(self._call(PackageKitGlib.ProvidesEnum.MODALIAS,
                                    ['fake:DEADBEEF']),
                         [])

    def test_multi(self):
        '''multiple modalias queries in one call'''

        res = self._call(PackageKitGlib.ProvidesEnum.MODALIAS,
                         ['pci:v00001234d00000001sv00sd01bc02sc03i04',
                          'usb:v9876dABCDsv00sd00bc00sc01i01'])
        self.assertEqual(set(res), set(['vanilla', 'chocolate']))

        self.assertEqual(self._call(PackageKitGlib.ProvidesEnum.MODALIAS,
                                    ['pci:v00001234d00000001sv00sd01bc02sc03i04',
                                     'usb:v9876d0000sv00sd00bc00sc01i01']),
                         ['vanilla'])

    def test_othertype(self):
        '''does not break query for a different type'''

        try:
            self._call(PackageKitGlib.ProvidesEnum.LANGUAGE_SUPPORT,
                             ['language(de)'])
        except GLib.GError as e:
            self.assertEqual(e.message, "Query type 'language-support' is not supported")

        res = self._call(PackageKitGlib.ProvidesEnum.ANY, ['language(de)'])
        self.assertTrue('vanilla' not in res, res)
        self.assertTrue('chocolate' not in res, res)

    def test_error(self):
        '''invalid modalias query'''

        # checks format for MODALIAS type
        try:
            self._call(PackageKitGlib.ProvidesEnum.MODALIAS, ['pci 1'])
            self.fail('unexpectedly succeeded with invalid query format')
        except GLib.GError as e:
            self.assertTrue('search term is invalid' in e.message, e.message)

        try:
            self._call(PackageKitGlib.ProvidesEnum.MODALIAS, ['usb:1', 'pci 1'])
            self.fail('unexpectedly succeeded with invalid query format')
        except GLib.GError as e:
            self.assertTrue('search term is invalid' in e.message, e.message)

        # for ANY it should just ignore invalid/unknown formats
        self.assertEqual(self._call(PackageKitGlib.ProvidesEnum.ANY, ['pci 1']), [])

    def test_performance_single(self):
        '''performance of 1000 lookups in a single query'''

        query = []
        for i in range(1000):
            query.append('usb:v%04Xd0000sv00sd00bc00sc00i99' % i)

        start = resource.getrusage(resource.RUSAGE_SELF)
        self._call(PackageKitGlib.ProvidesEnum.MODALIAS, query)
        stop = resource.getrusage(resource.RUSAGE_SELF)

        sec = (stop.ru_utime + stop.ru_stime) - (start.ru_utime + start.ru_stime)
        sys.stderr.write('[%i ms] ' % int(sec * 1000 + 0.5))
        self.assertLess(sec, 1.0)

    @unittest.skipUnless(os.path.isdir('/sys'), 'no /sys dir on this system')
    def test_system_driver_packages_system(self):
        '''system_driver_packages() for current system'''

        # nothing should match the fake vanilla/chocolate debs
        self.assertEqual(UbuntuDrivers.PackageKit.system_driver_packages(), [])

    def test_system_driver_packages_fakesys(self):
        '''system_driver_packages() for fake sysfs'''

        s = gen_fakesys()
        os.environ['SYSFS'] = s.sysfs

        try:
            res = UbuntuDrivers.PackageKit.system_driver_packages()
            self.assertEqual(set([p.get_id().split(';')[0] for p in res]),
                             set(['vanilla', 'chocolate']))
            for p in res:
                self.assertEqual(p.props.info, PackageKitGlib.InfoEnum.AVAILABLE)
        finally:
            del os.environ['SYSFS']

    def _call(self, provides_type,  query, expected_res=PackageKitGlib.ExitEnum.SUCCESS):
        '''Call what_provides() with given query.
        
        Return the resulting package list.
        '''
        res = self.pk.what_provides(PackageKitGlib.FilterEnum.NONE,
                provides_type, query,
                None, lambda p, t, d: True, None)
        self.assertEqual(res.get_exit_code(), expected_res)
        if res.get_exit_code() == PackageKitGlib.ExitEnum.SUCCESS:
            return [p.get_id().split(';')[0] for p in res.get_package_array()]
        else:
            return None

class DetectTest(unittest.TestCase):
    '''Test UbuntuDrivers.detect'''

    def setUp(self):
        '''Create a fake sysfs'''

        self.sys = gen_fakesys()
        os.environ['SYSFS'] = self.sys.sysfs

    def tearDown(self):
        try:
            del os.environ['SYSFS']
        except KeyError:
            pass

    @unittest.skipUnless(os.path.isdir('/sys'), 'no /sys dir on this system')
    def test_system_modaliases_system(self):
        '''system_modaliases() for current system'''

        del os.environ['SYSFS']
        res = UbuntuDrivers.detect.system_modaliases()
        self.assertGreater(len(res), 5)
        self.assertTrue(':' in res[0])

    def test_system_modalises_fake(self):
        '''system_modaliases() for fake sysfs'''

        res = set(UbuntuDrivers.detect.system_modaliases())
        self.assertEqual(res, set(['pci:v00001234d00sv00000001sd00bc00sc00i00',
            'pci:vDEADBEEFd00', 'usb:v9876dABCDsv01sd02bc00sc01i05']))

    def test_system_driver_packages_system(self):
        '''system_driver_packages() for current system'''

        # nothing should match the devices in our fake sysfs
        self.assertEqual(UbuntuDrivers.detect.system_driver_packages(), [])

    def test_system_driver_packages_performance(self):
        '''system_driver_packages() performance for a lot of modaliases'''

        # add lots of fake devices/modalises
        for i in range(30):
            self.sys.add('pci', 'pcidev%i' % i, {'modalias': 'pci:s%04X' % i})
            self.sys.add('usb', 'usbdev%i' % i, {'modalias': 'usb:s%04X' % i})

        start = resource.getrusage(resource.RUSAGE_SELF)
        UbuntuDrivers.detect.system_driver_packages()
        stop = resource.getrusage(resource.RUSAGE_SELF)

        sec = (stop.ru_utime + stop.ru_stime) - (start.ru_utime + start.ru_stime)
        sys.stderr.write('[%.2f s] ' % sec)
        self.assertLess(sec, 30.0)

    def test_system_driver_packages_chroot(self):
        '''system_driver_packages() for test package repository'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            chroot.add_repository(os.path.join(TEST_DIR, 'archive'), True, False)
            cache = apt.Cache(rootdir=chroot.path)
            self.assertEqual(set(UbuntuDrivers.detect.system_driver_packages(cache)),
                             set(['chocolate', 'vanilla']))
        finally:
            chroot.remove()

    def test_auto_install_filter(self):
        '''auto_install_filter()'''

        self.assertEqual(UbuntuDrivers.detect.auto_install_filter([]), [])
        self.assertEqual(set(UbuntuDrivers.detect.auto_install_filter([
            'nvidia-current', 'bcmwl-kernel-source', 'fglrx-updates',
            'pvr-omap4-egl'])), 
            set(['bcmwl-kernel-source', 'pvr-omap4-egl']))

if __name__ == '__main__':
    unittest.main()
