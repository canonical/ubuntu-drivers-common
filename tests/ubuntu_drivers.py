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
import tempfile
import shutil
import logging

from gi.repository import GLib
from gi.repository import PackageKitGlib
from gi.repository import UMockdev
import apt
import aptdaemon.test
import aptdaemon.pkcompat

import UbuntuDrivers.detect
import UbuntuDrivers.PackageKit
import UbuntuDrivers.kerneldetection

import testarchive

TEST_DIR = os.path.abspath(os.path.dirname(__file__))
ROOT_DIR = os.path.dirname(TEST_DIR)

# show aptdaemon log in test output?
APTDAEMON_LOG = False
# show aptdaemon debug level messages?
APTDAEMON_DEBUG = False

dbus_address = None


# modalias of an nvidia card covered by our nvidia-* packages
modalias_nv = 'pci:v000010DEd000010C3sv00003842sd00002670bc03sc03i00'

def gen_fakehw():
    '''Generate an UMockdev.Testbed object for testing'''

    t = UMockdev.Testbed.new()
    # covered by vanilla.deb
    t.add_device('pci', 'white', None, ['modalias', 'pci:v00001234d00sv00000001sd00bc00sc00i00'], [])
    # covered by chocolate.deb
    t.add_device('usb', 'black', None, ['modalias', 'usb:v9876dABCDsv01sd02bc00sc01i05'], [])
    # covered by nvidia-*.deb
    t.add_device('pci', 'graphics', None, ['modalias', modalias_nv], [])
    # not covered by any driver package
    t.add_device('pci', 'grey', None, ['modalias', 'pci:vDEADBEEFd00'], [])
    t.add_device('ssb', 'yellow', None, [], ['MODALIAS', 'pci:vDEADBEEFd00'])

    return t

def gen_fakearchive():
    '''Generate a fake archive for testing'''

    a = testarchive.Archive()
    a.create_deb('vanilla', extra_tags={'Modaliases': 
        'vanilla(pci:v00001234d*sv*sd*bc*sc*i*, pci:v0000BEEFd*sv*sd*bc*sc*i*)'}) 
    a.create_deb('chocolate', dependencies={'Depends': 'xserver-xorg-core'},
        extra_tags={'Modaliases': 
            'chocolate(usb:v9876dABCDsv*sd*bc00sc*i*, pci:v0000BEEFd*sv*sd*bc*sc*i00)'}) 

    # packages for testing X.org driver ABI installability
    a.create_deb('xserver-xorg-core', version='99:1',  # higher than system installed one
            dependencies={'Provides': 'xorg-video-abi-4'})
    a.create_deb('nvidia-current', dependencies={'Depends': 'xorg-video-abi-4'},
                 extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*, pci:v000010DEd000010C4sv*sd*bc03sc*i*,)'})
    a.create_deb('nvidia-old', dependencies={'Depends': 'xorg-video-abi-3'},
                 extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*, pci:v000010DEd000010C2sv*sd*bc03sc*i*,)'})

    # packages not covered by modalises, for testing detection plugins
    a.create_deb('special')
    a.create_deb('picky')
    a.create_deb('special-uninst', dependencies={'Depends': 'xorg-video-abi-3'})

    return a

class PackageKitTest(aptdaemon.test.AptDaemonTestCase):
    '''Test the PackageKit plugin and API'''

    @classmethod
    def setUpClass(klass):
        klass.umockdev = gen_fakehw()

        # find plugin in our source tree
        os.environ['PYTHONPATH'] = '%s:%s' % (os.getcwd(), os.environ.get('PYTHONPATH', ''))

        # start a local fake system D-BUS
        klass.dbus = subprocess.Popen(['dbus-daemon', '--nofork', '--print-address',
            '--config-file', 
            os.path.join(aptdaemon.test.get_tests_dir(), 'dbus.conf')],
            stdout=subprocess.PIPE, universal_newlines=True)
        klass.dbus_address = klass.dbus.stdout.readline().strip()
        os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = klass.dbus_address

        klass.archive = gen_fakearchive()

        # set up a test chroot
        klass.chroot = aptdaemon.test.Chroot()
        klass.chroot.setup()
        klass.chroot.add_test_repository()
        klass.chroot.add_repository(klass.archive.path, True, False)
        # initialize apt to the chroot, so that functions which instantiate an
        # apt.Cache() object get the chroot instead of the system
        apt.Cache(rootdir=klass.chroot.path)

        # no custom detection plugins by default
        klass.plugin_dir = os.path.join(klass.chroot.path, 'detect')
        os.environ['UBUNTU_DRIVERS_DETECT_DIR'] = klass.plugin_dir

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
        klass.aptdaemon = subprocess.Popen(argv, stderr=out, universal_newlines=True)
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

    def test_modalias(self):
        '''what-provides MODALIAS'''

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

    def test_modalias_multi(self):
        '''multiple MODALIAS queries in one what-provides call'''

        res = self._call(PackageKitGlib.ProvidesEnum.MODALIAS,
                         ['pci:v00001234d00000001sv00sd01bc02sc03i04',
                          'usb:v9876dABCDsv00sd00bc00sc01i01'])
        self.assertEqual(res, ['chocolate', 'vanilla'])

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

    def test_modalias_error(self):
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

    def test_modalias_performance_single(self):
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

    def test_hardware_driver(self):
        '''what-provides HARDWARE_DRIVER'''

        self.assertEqual(self._call(PackageKitGlib.ProvidesEnum.HARDWARE_DRIVER,
                                    ['drivers_for_attached_hardware']),
            ['chocolate', 'nvidia-current', 'vanilla'])

        self.assertEqual(self._call(PackageKitGlib.ProvidesEnum.ANY,
                                    ['drivers_for_attached_hardware']),
            ['chocolate', 'nvidia-current', 'vanilla'])

    def test_hardware_driver_detect_plugins(self):
        '''what-provides HARDWARE_DRIVER includes custom detection plugins'''

        try:
            os.mkdir(self.plugin_dir)
            with open(os.path.join(self.plugin_dir, 'special.py'), 'w') as f:
                f.write('def detect(apt): return ["special", "special-uninst", "special-unavail", "picky"]\n')

            self.assertEqual(self._call(PackageKitGlib.ProvidesEnum.HARDWARE_DRIVER,
                                        ['drivers_for_attached_hardware']),
                ['chocolate', 'nvidia-current', 'picky', 'special', 'vanilla'])
        finally:
            shutil.rmtree(self.plugin_dir)

    def test_hardware_driver_error(self):
        '''invalid what-provides HARDWARE_DRIVER query'''

        # checks format for HARDWARE_DRIVER type
        try:
            self._call(PackageKitGlib.ProvidesEnum.HARDWARE_DRIVER, ['?'])
            self.fail('unexpectedly succeeded with invalid query format')
        except GLib.GError as e:
            self.assertTrue('search term is invalid' in e.message, e.message)

        # for ANY it should just ignore invalid/unknown formats
        self.assertEqual(self._call(PackageKitGlib.ProvidesEnum.ANY, ['?']), [])

    def _call(self, provides_type,  query, expected_res=PackageKitGlib.ExitEnum.SUCCESS):
        '''Call what_provides() with given query.
        
        Return the resulting package list.
        '''
        # PackageKitGlib has a very low activation timeout, which
        # is too short for slow architectures; loop for a bit until service is
        # activated.
        tries = 5
        while tries > 0:
            try:
                res = self.pk.what_provides(PackageKitGlib.FilterEnum.NONE,
                        provides_type, query,
                        None, lambda p, t, d: True, None)
                break
            except GLib.GError as e:
                if 'org.freedesktop.DBus.Error.ServiceUnknown' in str(e):
                    tries -= 1
                    time.sleep(1)
                else:
                    raise
        else:
            self.fail('timed out waiting for PackageKit')

        self.assertEqual(res.get_exit_code(), expected_res)
        if res.get_exit_code() == PackageKitGlib.ExitEnum.SUCCESS:
            return sorted([p.get_id().split(';')[0] for p in res.get_package_array()])
        else:
            return None


class DetectTest(unittest.TestCase):
    '''Test UbuntuDrivers.detect'''

    def setUp(self):
        '''Create a fake sysfs'''

        self.umockdev = gen_fakehw()

        # no custom detection plugins by default
        self.plugin_dir = tempfile.mkdtemp()
        os.environ['UBUNTU_DRIVERS_DETECT_DIR'] = self.plugin_dir

    def tearDown(self):
        shutil.rmtree(self.plugin_dir)

        # most test cases switch the apt root, so the apt.Cache() cache becomes
        # unreliable; reset it
        UbuntuDrivers.detect.packages_for_modalias.cache_maps = {}

    @unittest.skipUnless(os.path.isdir('/sys/devices'), 'no /sys dir on this system')
    def test_system_modaliases_system(self):
        '''system_modaliases() for current system'''

        del self.umockdev
        res = UbuntuDrivers.detect.system_modaliases()
        self.assertGreater(len(res), 3)
        self.assertTrue(':' in list(res)[0])

    def test_system_modalises_fake(self):
        '''system_modaliases() for fake sysfs'''

        res = UbuntuDrivers.detect.system_modaliases()
        self.assertEqual(set(res), set(['pci:v00001234d00sv00000001sd00bc00sc00i00',
            'pci:vDEADBEEFd00', 'usb:v9876dABCDsv01sd02bc00sc01i05',
            modalias_nv]))
        self.assertEqual(res['pci:vDEADBEEFd00'], '/sys/devices/grey')

    def test_system_driver_packages_performance(self):
        '''system_driver_packages() performance for a lot of modaliases'''

        # add lots of fake devices/modalises
        for i in range(30):
            self.umockdev.add_device('pci', 'pcidev%i' % i, None, ['modalias', 'pci:s%04X' % i], [])
            self.umockdev.add_device('usb', 'usbdev%i' % i, None, ['modalias', 'usb:s%04X' % i], [])

        start = resource.getrusage(resource.RUSAGE_SELF)
        UbuntuDrivers.detect.system_driver_packages()
        stop = resource.getrusage(resource.RUSAGE_SELF)

        sec = (stop.ru_utime + stop.ru_stime) - (start.ru_utime + start.ru_stime)
        sys.stderr.write('[%.2f s] ' % sec)
        if 'arm' in os.uname().machine:
            self.assertLess(sec, 90.0)
        else:
            self.assertLess(sec, 30.0)

    def test_system_driver_packages_chroot(self):
        '''system_driver_packages() for test package repository'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            # older applicable driver which is not the recommended one
            archive.create_deb('nvidia-123', dependencies={'Depends': 'xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            # -updates driver which also should not be recommended
            archive.create_deb('nvidia-current-updates', dependencies={'Depends': 'xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            # driver package which supports multiple ABIs
            archive.create_deb('nvidia-34',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            chroot.add_repository(archive.path, True, False)
            cache = apt.Cache(rootdir=chroot.path)
            res = UbuntuDrivers.detect.system_driver_packages(cache)
        finally:
            chroot.remove()
        self.assertEqual(set(res), set(['chocolate', 'vanilla', 'nvidia-current',
                                        'nvidia-current-updates', 'nvidia-123',
                                        'nvidia-34']))
        self.assertEqual(res['vanilla']['modalias'], 'pci:v00001234d00sv00000001sd00bc00sc00i00')
        self.assertTrue(res['vanilla']['syspath'].endswith('/devices/white'))
        self.assertFalse(res['vanilla']['from_distro'])
        self.assertTrue(res['vanilla']['free'])
        self.assertFalse('vendor' in res['vanilla'])
        self.assertFalse('model' in res['vanilla'])
        self.assertFalse('recommended' in res['vanilla'])

        self.assertTrue(res['chocolate']['syspath'].endswith('/devices/black'))
        self.assertFalse('vendor' in res['chocolate'])
        self.assertFalse('model' in res['chocolate'])
        self.assertFalse('recommended' in res['chocolate'])

        self.assertEqual(res['nvidia-current']['modalias'], modalias_nv)
        self.assertTrue('nvidia' in res['nvidia-current']['vendor'].lower(),
                        res['nvidia-current']['vendor'])
        self.assertTrue('GeForce' in res['nvidia-current']['model'],
                        res['nvidia-current']['model'])
        self.assertEqual(res['nvidia-current']['recommended'], True)

        self.assertEqual(res['nvidia-123']['modalias'], modalias_nv)
        self.assertTrue('nvidia' in res['nvidia-123']['vendor'].lower(),
                        res['nvidia-123']['vendor'])
        self.assertTrue('GeForce' in res['nvidia-123']['model'],
                        res['nvidia-123']['model'])
        self.assertEqual(res['nvidia-123']['recommended'], False)

        self.assertEqual(res['nvidia-current-updates']['modalias'], modalias_nv)
        self.assertEqual(res['nvidia-current-updates']['recommended'], False)

        self.assertEqual(res['nvidia-34']['modalias'], modalias_nv)
        self.assertEqual(res['nvidia-34']['recommended'], False)

    def test_system_driver_packages_bad_encoding(self):
        '''system_driver_packages() with badly encoded Packages index'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()

            # add a package entry with a broken encoding
            with open(os.path.join(archive.path, 'Packages'), 'ab') as f:
                f.write(b'''
Package: broken
Architecture: all
Priority: optional
Version: 1
Maintainer: Test A\xEBB User <test@example.com>
Filename: ./vanilla_1_all.deb
Description: broken \xEB encoding
''')
            chroot.add_repository(archive.path, True, False)
            cache = apt.Cache(rootdir=chroot.path)
            res = UbuntuDrivers.detect.system_driver_packages(cache)
        finally:
            chroot.remove()

        self.assertEqual(set(res), set(['chocolate', 'vanilla', 'nvidia-current']))

    def test_system_driver_packages_detect_plugins(self):
        '''system_driver_packages() includes custom detection plugins'''

        with open(os.path.join(self.plugin_dir, 'extra.py'), 'w') as f:
            f.write('def detect(apt): return ["coreutils", "no_such_package"]\n')

        res = UbuntuDrivers.detect.system_driver_packages() 
        self.assertTrue('coreutils' in res, list(res.keys()))
        self.assertEqual(res['coreutils'], {'free': True, 'from_distro': True, 'plugin': 'extra.py'})

    def test_system_device_drivers_chroot(self):
        '''system_device_drivers() for test package repository'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            # older applicable driver which is not the recommended one
            archive.create_deb('nvidia-123', dependencies={'Depends': 'xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            # -updates driver which also should not be recommended
            archive.create_deb('nvidia-current-updates', dependencies={'Depends': 'xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})

            # -experimental driver which also should not be recommended
            archive.create_deb('nvidia-experimental', dependencies={'Depends': 'xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            chroot.add_repository(archive.path, True, False)
            cache = apt.Cache(rootdir=chroot.path)
            res = UbuntuDrivers.detect.system_device_drivers(cache)
        finally:
            chroot.remove()

        white = '/sys/devices/white'
        black = '/sys/devices/black'
        graphics = '/sys/devices/graphics'
        self.assertEqual(len(res), 3)  # the three devices above

        self.assertEqual(res[white], 
                         {'modalias': 'pci:v00001234d00sv00000001sd00bc00sc00i00',
                          'drivers': {'vanilla': {'free': True, 'from_distro': False}}
                         })

        self.assertEqual(res[black], 
                         {'modalias': 'usb:v9876dABCDsv01sd02bc00sc01i05',
                          'drivers': {'chocolate': {'free': True, 'from_distro': False}}
                         })

        self.assertEqual(res[graphics]['modalias'], modalias_nv)
        self.assertTrue('nvidia' in res[graphics]['vendor'].lower())
        self.assertTrue('GeForce' in res[graphics]['model'])

        # should contain nouveau driver; note that free is True here because
        # these come from the fake archive
        self.assertEqual(res[graphics]['drivers']['nvidia-current'],
                         {'free': True, 'from_distro': False, 'recommended': True})
        self.assertEqual(res[graphics]['drivers']['nvidia-current-updates'],
                         {'free': True, 'from_distro': False, 'recommended': False})
        self.assertEqual(res[graphics]['drivers']['nvidia-123'],
                          {'free': True, 'from_distro': False, 'recommended': False})
        self.assertEqual(res[graphics]['drivers']['nvidia-experimental'],
                         {'free': True, 'from_distro': False, 'recommended': False})
        self.assertEqual(res[graphics]['drivers']['xserver-xorg-video-nouveau'],
                         {'free': True, 'from_distro': True, 'recommended': False, 'builtin': True})
        self.assertEqual(len(res[graphics]['drivers']), 5, list(res[graphics]['drivers'].keys()))

    def test_system_device_drivers_detect_plugins(self):
        '''system_device_drivers() includes custom detection plugins'''

        with open(os.path.join(self.plugin_dir, 'extra.py'), 'w') as f:
            f.write('def detect(apt): return ["coreutils", "no_such_package"]\n')

        res = UbuntuDrivers.detect.system_device_drivers()
        self.assertTrue('extra.py' in res, list(res.keys()))
        self.assertEqual(res['extra.py'],
                         {'drivers': {'coreutils': {'free': True, 'from_distro': True}}})

    def test_system_device_drivers_manual_install(self):
        '''system_device_drivers() for a manually installed nvidia driver'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            chroot.add_repository(archive.path, True, False)
            cache = apt.Cache(rootdir=chroot.path)

            # add a wrapper modinfo binary
            with open(os.path.join(chroot.path, 'modinfo'), 'w') as f:
                f.write('''#!/bin/sh -e
if [ "$1" = nvidia ]; then
    echo "filename:  /some/path/nvidia.ko"
    exit 0
fi
exec /sbin/modinfo "$@"
''')
            os.chmod(os.path.join(chroot.path, 'modinfo'), 0o755)
            orig_path = os.environ['PATH']
            os.environ['PATH'] = '%s:%s' % (chroot.path, os.environ['PATH'])

            res = UbuntuDrivers.detect.system_device_drivers(cache)
        finally:
            chroot.remove()
            os.environ['PATH'] = orig_path

        graphics = '/sys/devices/graphics'
        self.assertEqual(res[graphics]['modalias'], modalias_nv)
        self.assertTrue(res[graphics]['manual_install'])

        # should still show the drivers
        self.assertGreater(len(res[graphics]['drivers']), 1)

    def test_auto_install_filter(self):
        '''auto_install_filter()'''

        self.assertEqual(UbuntuDrivers.detect.auto_install_filter({}), {})

        pkgs = {'bcmwl-kernel-source': {}, 
                'nvidia-current': {},
                'fglrx-updates': {},
                'pvr-omap4-egl': {}}

        self.assertEqual(set(UbuntuDrivers.detect.auto_install_filter(pkgs)),
            set(['bcmwl-kernel-source', 'pvr-omap4-egl', 'nvidia-current']))

        # should not include non-recommended variants
        pkgs = {'bcmwl-kernel-source': {}, 
                'nvidia-current': {'recommended': False},
                'nvidia-173': {'recommended': True}}
        self.assertEqual(set(UbuntuDrivers.detect.auto_install_filter(pkgs)),
                         set(['bcmwl-kernel-source', 'nvidia-173']))

    def test_detect_plugin_packages(self):
        '''detect_plugin_packages()'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            self.assertEqual(UbuntuDrivers.detect.detect_plugin_packages(cache), {})

            self._gen_detect_plugins()
            # suppress logging the deliberate errors in our test plugins to
            # stderr
            logging.getLogger().setLevel(logging.CRITICAL)
            self.assertEqual(UbuntuDrivers.detect.detect_plugin_packages(cache), 
                             {'special.py': ['special']})

            os.mkdir(os.path.join(self.umockdev.get_sys_dir(), 'pickyon'))
            self.assertEqual(UbuntuDrivers.detect.detect_plugin_packages(cache), 
                             {'special.py': ['special'], 'picky.py': ['picky']})
        finally:
            logging.getLogger().setLevel(logging.INFO)
            chroot.remove()

    def _gen_detect_plugins(self):
        '''Generate some custom detection plugins in self.plugin_dir.'''

        with open(os.path.join(self.plugin_dir, 'special.py'), 'w') as f:
            f.write('def detect(apt): return ["special", "special-uninst", "special-unavail"]\n')
        with open(os.path.join(self.plugin_dir, 'syntax.py'), 'w') as f:
            f.write('def detect(apt): a = =\n')
        with open(os.path.join(self.plugin_dir, 'empty.py'), 'w') as f:
            f.write('def detect(apt): return []\n')
        with open(os.path.join(self.plugin_dir, 'badreturn.py'), 'w') as f:
            f.write('def detect(apt): return "strawberry"\n')
        with open(os.path.join(self.plugin_dir, 'badreturn2.py'), 'w') as f:
            f.write('def detect(apt): return 1\n')
        with open(os.path.join(self.plugin_dir, 'except.py'), 'w') as f:
            f.write('def detect(apt): 1/0\n')
        with open(os.path.join(self.plugin_dir, 'nodetect.py'), 'w') as f:
            f.write('def foo(): assert False\n')
        with open(os.path.join(self.plugin_dir, 'bogus'), 'w') as f:
            f.write('I am not a plugin')
        with open(os.path.join(self.plugin_dir, 'picky.py'), 'w') as f:
            f.write('''import os, os.path
            
def detect(apt): 
    if os.path.exists("/sys/pickyon"):
        return ["picky"]
''')

    def test_get_linux_headers_chroot(self):
        '''get_linux_headers() for test package repository'''
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-3.2.0-23-generic',
                                extra_tags={'Source': 'linux'})
            archive.create_deb('linux-image-3.2.0-33-generic',
                                extra_tags={'Source': 'linux'})
            archive.create_deb('linux-image-3.5.0-18-generic',
                                extra_tags={'Source':
                                            'linux-lts-quantal'})
            archive.create_deb('linux-image-3.5.0-19-generic',
                                extra_tags={'Source':
                                             'linux-lts-quantal'})
            archive.create_deb('linux-image-generic',
                                extra_tags={'Source':
                                            'linux-meta'})
            archive.create_deb('linux-image-generic-lts-quantal',
                                extra_tags={'Source':
                                            'linux-meta-lts-quantal'})
            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            linux_headers = UbuntuDrivers.detect.get_linux_headers(cache)
            self.assertEqual(linux_headers, '')

            # Install kernel packages
            for pkg in ('linux-image-3.2.0-23-generic',
                        'linux-image-3.2.0-33-generic',
                        'linux-image-3.5.0-18-generic',
                        'linux-image-3.5.0-19-generic',
                        'linux-image-generic',
                        'linux-image-generic-lts-quantal'):
                cache[pkg].mark_install()

            linux_headers = UbuntuDrivers.detect.get_linux_headers(cache)
            self.assertEqual(linux_headers, 'linux-headers-generic-lts-quantal')
        finally:
            chroot.remove()

    def test_get_linux_chroot(self):
        '''get_linux() for test package repository'''
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-3.2.0-23-generic',
                                extra_tags={'Source': 'linux'})
            archive.create_deb('linux-image-3.2.0-33-generic',
                                extra_tags={'Source': 'linux'})
            archive.create_deb('linux-image-3.5.0-18-generic',
                                extra_tags={'Source':
                                            'linux-lts-quantal'})
            archive.create_deb('linux-image-3.5.0-19-generic',
                                extra_tags={'Source':
                                             'linux-lts-quantal'})
            archive.create_deb('linux-image-generic',
                                extra_tags={'Source':
                                            'linux-meta'})
            archive.create_deb('linux-image-generic-lts-quantal',
                                extra_tags={'Source':
                                            'linux-meta-lts-quantal'})
            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            linux = UbuntuDrivers.detect.get_linux(cache)
            self.assertEqual(linux, '')

            # Install kernel packages
            for pkg in ('linux-image-3.2.0-23-generic',
                        'linux-image-3.2.0-33-generic',
                        'linux-image-3.5.0-18-generic',
                        'linux-image-3.5.0-19-generic',
                        'linux-image-generic',
                        'linux-image-generic-lts-quantal'):
                cache[pkg].mark_install()

            linux = UbuntuDrivers.detect.get_linux(cache)
            self.assertEqual(linux, 'linux-generic-lts-quantal')
        finally:
            chroot.remove()

class ToolTest(unittest.TestCase):
    '''Test ubuntu-drivers tool'''

    @classmethod
    def setUpClass(klass):
        klass.archive = gen_fakearchive()
        klass.archive.create_deb('noalias')
        klass.archive.create_deb('bcmwl-kernel-source', extra_tags={'Modaliases': 
            'wl(usb:v9876dABCDsv*sd*bc00sc*i*, pci:v0000BEEFd*sv*sd*bc*sc*i00)'}) 

        # set up a test chroot
        klass.chroot = aptdaemon.test.Chroot()
        klass.chroot.setup()
        klass.chroot.add_test_repository()
        klass.chroot.add_repository(klass.archive.path, True, False)
        klass.chroot_apt_conf = os.path.join(klass.chroot.path, 'aptconfig')
        with open(klass.chroot_apt_conf, 'w') as f:
            f.write('''Dir "%(root)s";
Dir::State::status "%(root)s/var/lib/dpkg/status";
Debug::NoLocking "true";
DPKG::options:: "--root=%(root)s --log=%(root)s/var/log/dpkg.log";
APT::Get::AllowUnauthenticated "true";
''' % {'root': klass.chroot.path})
        os.environ['APT_CONFIG'] = klass.chroot_apt_conf

        klass.tool_path = os.path.join(ROOT_DIR, 'ubuntu-drivers')

        # no custom detection plugins by default
        klass.plugin_dir = os.path.join(klass.chroot.path, 'detect')
        os.environ['UBUNTU_DRIVERS_DETECT_DIR'] = klass.plugin_dir

        # avoid failures due to unexpected udevadm debug messages if kernel is
        # booted with "debug"
        os.environ['SYSTEMD_LOG_LEVEL'] = 'warning'

    @classmethod
    def tearDownClass(klass):
        klass.chroot.remove()

    def setUp(self):
        '''Create a fake sysfs'''

        self.umockdev = gen_fakehw()

    def tearDown(self):
        # some tests install this package
        apt = subprocess.Popen(['apt-get', 'purge', '-y', 'bcmwl-kernel-source'],
                stdout=subprocess.PIPE)
        apt.communicate()
        self.assertEqual(apt.returncode, 0)

    def test_list_chroot(self):
        '''ubuntu-drivers list for fake sysfs and chroot'''

        ud = subprocess.Popen([self.tool_path, 'list'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertEqual(set(out.splitlines()), 
                set(['vanilla', 'chocolate', 'bcmwl-kernel-source', 'nvidia-current']))
        self.assertEqual(ud.returncode, 0)

    def test_list_detect_plugins(self):
        '''ubuntu-drivers list includes custom detection plugins'''

        os.mkdir(self.plugin_dir)
        self.addCleanup(shutil.rmtree, self.plugin_dir)

        with open(os.path.join(self.plugin_dir, 'special.py'), 'w') as f:
            f.write('def detect(apt): return ["special", "special-uninst", "special-unavail", "picky"]\n')

        ud = subprocess.Popen([self.tool_path, 'list'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertEqual(set(out.splitlines()), 
                set(['vanilla', 'chocolate', 'bcmwl-kernel-source',
                     'nvidia-current', 'special', 'picky']))
        self.assertEqual(ud.returncode, 0)

    def test_list_system(self):
        '''ubuntu-drivers list for fake sysfs and system apt'''

        env = os.environ.copy()
        del env['APT_CONFIG']

        ud = subprocess.Popen([self.tool_path, 'list'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env)
        out, err = ud.communicate()
        # real system packages should not match our fake modalises
        self.assertEqual(err, '')
        self.assertEqual(out, '\n')
        self.assertEqual(ud.returncode, 0)

    def test_devices_chroot(self):
        '''ubuntu-drivers devices for fake sysfs and chroot'''

        ud = subprocess.Popen([self.tool_path, 'devices'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertTrue('/devices/white ==' in out)
        self.assertTrue('modalias : pci:v00001234d00sv00000001sd00bc00sc00i00' in out)
        self.assertTrue('driver   : vanilla - third-party free' in out)
        self.assertTrue('/devices/black ==' in out)
        self.assertTrue('/devices/graphics ==' in out)
        self.assertTrue('xserver-xorg-video-nouveau - distro free builtin' in out)
        self.assertTrue('nvidia-current - third-party free recommended' in out)
        self.assertEqual(ud.returncode, 0)

    def test_devices_detect_plugins(self):
        '''ubuntu-drivers devices includes custom detection plugins'''

        os.mkdir(self.plugin_dir)
        self.addCleanup(shutil.rmtree, self.plugin_dir)

        with open(os.path.join(self.plugin_dir, 'special.py'), 'w') as f:
            f.write('def detect(apt): return ["special", "special-uninst", "special-unavail", "picky"]\n')

        ud = subprocess.Popen([self.tool_path, 'devices'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '')

        # only look at the part after special.py
        special_off = out.find('== special.py ==')
        self.assertGreaterEqual(special_off, 0, out)
        out = out[special_off:]
        self.assertTrue('picky - third-party free' in out, out)
        self.assertTrue('special - third-party free' in out, out)
        self.assertEqual(ud.returncode, 0)

    def test_devices_system(self):
        '''ubuntu-drivers devices for fake sysfs and system apt'''

        env = os.environ.copy()
        del env['APT_CONFIG']

        ud = subprocess.Popen([self.tool_path, 'devices'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env)
        out, err = ud.communicate()
        # real system packages should not match our fake modalises
        self.assertEqual(err, '')
        self.assertEqual(out, '')
        self.assertEqual(ud.returncode, 0)

    def test_auto_install_chroot(self):
        '''ubuntu-drivers autoinstall for fake sysfs and chroot'''

        ud = subprocess.Popen([self.tool_path, 'autoinstall'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertTrue('bcmwl-kernel-source' in out, out)
        self.assertFalse('vanilla' in out, out)
        self.assertFalse('noalias' in out, out)
        self.assertEqual(ud.returncode, 0)

        # now all packages should be installed, so it should not do anything
        ud = subprocess.Popen([self.tool_path, 'autoinstall'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertFalse('bcmwl-kernel-source' in out, out)
        self.assertEqual(ud.returncode, 0)

    def test_auto_install_packagelist(self):
        '''ubuntu-drivers autoinstall package list creation'''

        listfile = os.path.join(self.chroot.path, 'pkgs')
        self.addCleanup(os.unlink, listfile)

        ud = subprocess.Popen([self.tool_path, 'autoinstall', '--package-list', listfile],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertEqual(ud.returncode, 0)

        with open(listfile) as f:
            self.assertEqual(f.read(), 'bcmwl-kernel-source\n')

    def test_auto_install_system(self):
        '''ubuntu-drivers autoinstall for fake sysfs and system apt'''

        env = os.environ.copy()
        del env['APT_CONFIG']

        ud = subprocess.Popen([self.tool_path, 'autoinstall'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        # real system packages should not match our fake modalises
        self.assertTrue('No drivers found' in out)
        self.assertEqual(ud.returncode, 0)

    def test_debug(self):
        '''ubuntu-drivers debug'''

        os.mkdir(self.plugin_dir)
        self.addCleanup(shutil.rmtree, self.plugin_dir)

        with open(os.path.join(self.plugin_dir, 'special.py'), 'w') as f:
            f.write('def detect(apt): return ["special", "special-uninst", "special-unavail"]\n')

        ud = subprocess.Popen([self.tool_path, 'debug'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '', err)
        self.assertEqual(ud.returncode, 0)
        # shows messages from detection/plugins
        self.assertTrue('special-uninst is incompatible' in out, out)
        self.assertTrue('unavailable package special-unavail' in out, out)
        # shows modaliases
        self.assertTrue(modalias_nv in out, out)
        # driver packages
        self.assertTrue('available: 1 (auto-install)  [third party]  free  modalias:' in out, out)

class PluginsTest(unittest.TestCase):
    '''Test detect-plugins/*'''

    def test_plugin_errors(self):
        '''shipped plugins work without errors or crashes'''

        env = os.environ.copy()
        env['UBUNTU_DRIVERS_DETECT_DIR'] = os.path.join(ROOT_DIR, 'detect-plugins')

        ud = subprocess.Popen([os.path.join(ROOT_DIR, 'ubuntu-drivers'), 'debug'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        # real system packages should not match our fake modalises
        self.assertFalse('ERROR' in out, out)
        self.assertFalse('Traceback' in out, out)
        self.assertEqual(ud.returncode, 0)

class KernelDectionTest(unittest.TestCase):
    '''Test UbuntuDrivers.kerneldetection'''

    def setUp(self):
        '''Create a fake sysfs'''

        self.umockdev = gen_fakehw()

        # no custom detection plugins by default
        self.plugin_dir = tempfile.mkdtemp()
        os.environ['UBUNTU_DRIVERS_DETECT_DIR'] = self.plugin_dir

    def tearDown(self):
        shutil.rmtree(self.plugin_dir)

    def test_linux_headers_detection_chroot(self):
        '''get_linux_headers_metapackage() for test package repository'''
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-3.2.0-23-generic',
                                extra_tags={'Source': 'linux'})
            archive.create_deb('linux-image-3.2.0-33-generic',
                                extra_tags={'Source': 'linux'})
            archive.create_deb('linux-image-3.5.0-18-generic',
                                extra_tags={'Source':
                                            'linux-lts-quantal'})
            archive.create_deb('linux-image-3.5.0-19-generic',
                                extra_tags={'Source':
                                             'linux-lts-quantal'})
            archive.create_deb('linux-image-generic',
                                extra_tags={'Source':
                                            'linux-meta'})
            archive.create_deb('linux-image-generic-lts-quantal',
                                extra_tags={'Source':
                                            'linux-meta-lts-quantal'})
            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, '')

            # Install kernel packages
            for pkg in ('linux-image-3.2.0-23-generic',
                        'linux-image-3.2.0-33-generic',
                        'linux-image-3.5.0-18-generic',
                        'linux-image-3.5.0-19-generic',
                        'linux-image-generic',
                        'linux-image-generic-lts-quantal'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, 'linux-headers-generic-lts-quantal')
        finally:
            chroot.remove()

    def test_linux_headers_detection_names_chroot1(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-nexus7',
                                extra_tags={'Source': 'linux-meta-nexus7'})
            archive.create_deb('linux-image-3.1.10-9-nexus7',
                                extra_tags={'Source': 'linux-nexus7'})
            archive.create_deb('linux-image-omap4',
                                extra_tags={'Source':
                                            'linux-meta-ti-omap4'})
            archive.create_deb('linux-image-3.2.0-1419-omap4',
                                extra_tags={'Source':
                                            'linux-ti-omap4'})
            archive.create_deb('linux-image-3.5.0-17-highbank',
                                extra_tags={'Source':
                                             'linux'})
            archive.create_deb('linux-image-highbank',
                                extra_tags={'Source':
                                             'linux-meta-highbank'})
            archive.create_deb('linux-image-powerpc-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc-smp'})
            archive.create_deb('linux-image-3.5.0-18-powerpc-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc64-smp'})
            archive.create_deb('linux-image-3.5.0-17-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-ac100',
                                extra_tags={'Source':
                                            'linux-meta-ac100'})
            archive.create_deb('linux-image-3.0.27-1-ac100',
                                extra_tags={'Source':
                                            'linux-ac100'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, '')

            # Install kernel packages
            for pkg in ('linux-image-nexus7',
                        'linux-image-3.1.10-9-nexus7',
                        'linux-image-omap4',
                        'linux-image-3.2.0-1419-omap4',
                        'linux-image-highbank',
                        'linux-image-3.5.0-17-highbank',
                        'linux-image-powerpc-smp',
                        'linux-image-3.5.0-18-powerpc-smp',
                        'linux-image-powerpc64-smp',
                        'linux-image-3.5.0-17-powerpc64-smp',
                        'linux-image-ac100',
                        'linux-image-3.0.27-1-ac100'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, 'linux-headers-powerpc-smp')
        finally:
            chroot.remove()

    def test_linux_headers_detection_names_chroot2(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-nexus7',
                                extra_tags={'Source': 'linux-meta-nexus7'})
            archive.create_deb('linux-image-3.1.10-9-nexus7',
                                extra_tags={'Source': 'linux-nexus7'})
            archive.create_deb('linux-image-omap4',
                                extra_tags={'Source':
                                            'linux-meta-ti-omap4'})
            archive.create_deb('linux-image-3.2.0-1419-omap4',
                                extra_tags={'Source':
                                            'linux-ti-omap4'})
            archive.create_deb('linux-image-3.5.0-17-highbank',
                                extra_tags={'Source':
                                             'linux'})
            archive.create_deb('linux-image-highbank',
                                extra_tags={'Source':
                                             'linux-meta-highbank'})
            archive.create_deb('linux-image-powerpc-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc-smp'})
            archive.create_deb('linux-image-3.5.0-18-powerpc-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc64-smp'})
            archive.create_deb('linux-image-3.5.0-19-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-ac100',
                                extra_tags={'Source':
                                            'linux-meta-ac100'})
            archive.create_deb('linux-image-3.0.27-1-ac100',
                                extra_tags={'Source':
                                            'linux-ac100'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, '')

            # Install kernel packages
            for pkg in ('linux-image-nexus7',
                        'linux-image-3.1.10-9-nexus7',
                        'linux-image-omap4',
                        'linux-image-3.2.0-1419-omap4',
                        'linux-image-highbank',
                        'linux-image-3.5.0-17-highbank',
                        'linux-image-powerpc-smp',
                        'linux-image-3.5.0-18-powerpc-smp',
                        'linux-image-powerpc64-smp',
                        'linux-image-3.5.0-19-powerpc64-smp',
                        'linux-image-ac100',
                        'linux-image-3.0.27-1-ac100'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, 'linux-headers-powerpc64-smp')
        finally:
            chroot.remove()

    def test_linux_headers_detection_names_chroot3(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-nexus7',
                                extra_tags={'Source': 'linux-meta-nexus7'})
            archive.create_deb('linux-image-3.1.10-9-nexus7',
                                extra_tags={'Source': 'linux-nexus7'})
            archive.create_deb('linux-image-omap4',
                                extra_tags={'Source':
                                            'linux-meta-ti-omap4'})
            archive.create_deb('linux-image-3.8.0-1419-omap4',
                                extra_tags={'Source':
                                            'linux-ti-omap4'})
            archive.create_deb('linux-image-3.5.0-17-highbank',
                                extra_tags={'Source':
                                             'linux'})
            archive.create_deb('linux-image-highbank',
                                extra_tags={'Source':
                                             'linux-meta-highbank'})
            archive.create_deb('linux-image-powerpc-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc-smp'})
            archive.create_deb('linux-image-3.5.0-18-powerpc-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc64-smp'})
            archive.create_deb('linux-image-3.5.0-19-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-ac100',
                                extra_tags={'Source':
                                            'linux-meta-ac100'})
            archive.create_deb('linux-image-3.0.27-1-ac100',
                                extra_tags={'Source':
                                            'linux-ac100'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, '')

            # Install kernel packages
            for pkg in ('linux-image-nexus7',
                        'linux-image-3.1.10-9-nexus7',
                        'linux-image-omap4',
                        'linux-image-3.8.0-1419-omap4',
                        'linux-image-highbank',
                        'linux-image-3.5.0-17-highbank',
                        'linux-image-powerpc-smp',
                        'linux-image-3.5.0-18-powerpc-smp',
                        'linux-image-powerpc64-smp',
                        'linux-image-3.5.0-19-powerpc64-smp',
                        'linux-image-ac100',
                        'linux-image-3.0.27-1-ac100'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, 'linux-headers-omap4')
        finally:
            chroot.remove()

    def test_linux_headers_detection_names_chroot4(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-powerpc-smp',
                                extra_tags={'Source':
                                            'linux-ppc'})
            archive.create_deb('linux-image-3.8.0-3-powerpc-e500',
                                extra_tags={'Source':
                                            'linux-ppc'})
            archive.create_deb('linux-image-3.8.0-1-powerpc-smp',
                                extra_tags={'Source':
                                            'linux-ppc'})
            archive.create_deb('linux-image-3.5.0-19-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux-ppc'})
            archive.create_deb('linux-image-3.8.0-2-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux-ppc'})
            archive.create_deb('linux-image-3.0.27-1-ac100',
                                extra_tags={'Source':
                                            'linux-ac100'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, '')

            # Install kernel packages
            for pkg in ('linux-image-powerpc-smp',
                        'linux-image-3.8.0-3-powerpc-e500',
                        'linux-image-3.8.0-1-powerpc-smp',
                        'linux-image-3.5.0-19-powerpc64-smp',
                        'linux-image-3.8.0-2-powerpc64-smp',
                        'linux-image-3.0.27-1-ac100'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, 'linux-headers-powerpc-e500')
        finally:
            chroot.remove()

    def test_linux_headers_detection_names_chroot5(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-3.2.0-36-lowlatency-pae',
                                extra_tags={'Source': 'linux-lowlatency'})
            archive.create_deb('linux-image-3.8.0-0-lowlatency',
                                extra_tags={'Source': 'linux-lowlatency'})
            archive.create_deb('linux-image-3.5.0-18-generic',
                                extra_tags={'Source':
                                            'linux-lts-quantal'})
            archive.create_deb('linux-image-3.5.0-19-generic',
                                extra_tags={'Source':
                                             'linux-lts-quantal'})
            archive.create_deb('linux-image-generic',
                                extra_tags={'Source':
                                            'linux-meta'})
            archive.create_deb('linux-image-generic-lts-quantal',
                                extra_tags={'Source':
                                            'linux-meta-lts-quantal'})
            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, '')

            # Install kernel packages
            for pkg in ('linux-image-3.2.0-36-lowlatency-pae',
                        'linux-image-3.8.0-0-lowlatency',
                        'linux-image-3.5.0-18-generic',
                        'linux-image-3.5.0-19-generic',
                        'linux-image-generic',
                        'linux-image-generic-lts-quantal'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, 'linux-headers-lowlatency')
        finally:
            chroot.remove()

    def test_linux_detection_chroot(self):
        '''get_linux_metapackage() for test package repository'''
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-3.2.0-23-generic',
                                extra_tags={'Source': 'linux'})
            archive.create_deb('linux-image-3.2.0-33-generic',
                                extra_tags={'Source': 'linux'})
            archive.create_deb('linux-image-3.5.0-18-generic',
                                extra_tags={'Source':
                                            'linux-lts-quantal'})
            archive.create_deb('linux-image-3.5.0-19-generic',
                                extra_tags={'Source':
                                             'linux-lts-quantal'})
            archive.create_deb('linux-image-generic',
                                extra_tags={'Source':
                                            'linux-meta'})
            archive.create_deb('linux-image-generic-lts-quantal',
                                extra_tags={'Source':
                                            'linux-meta-lts-quantal'})
            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, '')

            # Install kernel packages
            for pkg in ('linux-image-3.2.0-23-generic',
                        'linux-image-3.2.0-33-generic',
                        'linux-image-3.5.0-18-generic',
                        'linux-image-3.5.0-19-generic',
                        'linux-image-generic',
                        'linux-image-generic-lts-quantal'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, 'linux-generic-lts-quantal')
        finally:
            chroot.remove()

    def test_linux_detection_names_chroot1(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-nexus7',
                                extra_tags={'Source': 'linux-meta-nexus7'})
            archive.create_deb('linux-image-3.1.10-9-nexus7',
                                extra_tags={'Source': 'linux-nexus7'})
            archive.create_deb('linux-image-omap4',
                                extra_tags={'Source':
                                            'linux-meta-ti-omap4'})
            archive.create_deb('linux-image-3.2.0-1419-omap4',
                                extra_tags={'Source':
                                            'linux-ti-omap4'})
            archive.create_deb('linux-image-3.5.0-17-highbank',
                                extra_tags={'Source':
                                             'linux'})
            archive.create_deb('linux-image-highbank',
                                extra_tags={'Source':
                                             'linux-meta-highbank'})
            archive.create_deb('linux-image-powerpc-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc-smp'})
            archive.create_deb('linux-image-3.5.0-18-powerpc-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc64-smp'})
            archive.create_deb('linux-image-3.5.0-17-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-ac100',
                                extra_tags={'Source':
                                            'linux-meta-ac100'})
            archive.create_deb('linux-image-3.0.27-1-ac100',
                                extra_tags={'Source':
                                            'linux-ac100'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, '')

            # Install kernel packages
            for pkg in ('linux-image-nexus7',
                        'linux-image-3.1.10-9-nexus7',
                        'linux-image-omap4',
                        'linux-image-3.2.0-1419-omap4',
                        'linux-image-highbank',
                        'linux-image-3.5.0-17-highbank',
                        'linux-image-powerpc-smp',
                        'linux-image-3.5.0-18-powerpc-smp',
                        'linux-image-powerpc64-smp',
                        'linux-image-3.5.0-17-powerpc64-smp',
                        'linux-image-ac100',
                        'linux-image-3.0.27-1-ac100'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, 'linux-powerpc-smp')
        finally:
            chroot.remove()

    def test_linux_detection_names_chroot2(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-nexus7',
                                extra_tags={'Source': 'linux-meta-nexus7'})
            archive.create_deb('linux-image-3.1.10-9-nexus7',
                                extra_tags={'Source': 'linux-nexus7'})
            archive.create_deb('linux-image-omap4',
                                extra_tags={'Source':
                                            'linux-meta-ti-omap4'})
            archive.create_deb('linux-image-3.2.0-1419-omap4',
                                extra_tags={'Source':
                                            'linux-ti-omap4'})
            archive.create_deb('linux-image-3.5.0-17-highbank',
                                extra_tags={'Source':
                                             'linux'})
            archive.create_deb('linux-image-highbank',
                                extra_tags={'Source':
                                             'linux-meta-highbank'})
            archive.create_deb('linux-image-powerpc-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc-smp'})
            archive.create_deb('linux-image-3.5.0-18-powerpc-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc64-smp'})
            archive.create_deb('linux-image-3.5.0-19-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-ac100',
                                extra_tags={'Source':
                                            'linux-meta-ac100'})
            archive.create_deb('linux-image-3.0.27-1-ac100',
                                extra_tags={'Source':
                                            'linux-ac100'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, '')

            # Install kernel packages
            for pkg in ('linux-image-nexus7',
                        'linux-image-3.1.10-9-nexus7',
                        'linux-image-omap4',
                        'linux-image-3.2.0-1419-omap4',
                        'linux-image-highbank',
                        'linux-image-3.5.0-17-highbank',
                        'linux-image-powerpc-smp',
                        'linux-image-3.5.0-18-powerpc-smp',
                        'linux-image-powerpc64-smp',
                        'linux-image-3.5.0-19-powerpc64-smp',
                        'linux-image-ac100',
                        'linux-image-3.0.27-1-ac100'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, 'linux-powerpc64-smp')
        finally:
            chroot.remove()

    def test_linux_detection_names_chroot3(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-nexus7',
                                extra_tags={'Source': 'linux-meta-nexus7'})
            archive.create_deb('linux-image-3.1.10-9-nexus7',
                                extra_tags={'Source': 'linux-nexus7'})
            archive.create_deb('linux-image-omap4',
                                extra_tags={'Source':
                                            'linux-meta-ti-omap4'})
            archive.create_deb('linux-image-3.8.0-1419-omap4',
                                extra_tags={'Source':
                                            'linux-ti-omap4'})
            archive.create_deb('linux-image-3.5.0-17-highbank',
                                extra_tags={'Source':
                                             'linux'})
            archive.create_deb('linux-image-highbank',
                                extra_tags={'Source':
                                             'linux-meta-highbank'})
            archive.create_deb('linux-image-powerpc-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc-smp'})
            archive.create_deb('linux-image-3.5.0-18-powerpc-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux-meta-powerpc64-smp'})
            archive.create_deb('linux-image-3.5.0-19-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux'})
            archive.create_deb('linux-image-ac100',
                                extra_tags={'Source':
                                            'linux-meta-ac100'})
            archive.create_deb('linux-image-3.0.27-1-ac100',
                                extra_tags={'Source':
                                            'linux-ac100'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, '')

            # Install kernel packages
            for pkg in ('linux-image-nexus7',
                        'linux-image-3.1.10-9-nexus7',
                        'linux-image-omap4',
                        'linux-image-3.8.0-1419-omap4',
                        'linux-image-highbank',
                        'linux-image-3.5.0-17-highbank',
                        'linux-image-powerpc-smp',
                        'linux-image-3.5.0-18-powerpc-smp',
                        'linux-image-powerpc64-smp',
                        'linux-image-3.5.0-19-powerpc64-smp',
                        'linux-image-ac100',
                        'linux-image-3.0.27-1-ac100'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, 'linux-omap4')
        finally:
            chroot.remove()

    def test_linux_detection_names_chroot4(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-powerpc-smp',
                                extra_tags={'Source':
                                            'linux-ppc'})
            archive.create_deb('linux-image-3.8.0-3-powerpc-e500',
                                extra_tags={'Source':
                                            'linux-ppc'})
            archive.create_deb('linux-image-3.8.0-1-powerpc-smp',
                                extra_tags={'Source':
                                            'linux-ppc'})
            archive.create_deb('linux-image-3.5.0-19-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux-ppc'})
            archive.create_deb('linux-image-3.8.0-2-powerpc64-smp',
                                extra_tags={'Source':
                                            'linux-ppc'})
            archive.create_deb('linux-image-3.0.27-1-ac100',
                                extra_tags={'Source':
                                            'linux-ac100'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, '')

            # Install kernel packages
            for pkg in ('linux-image-powerpc-smp',
                        'linux-image-3.8.0-3-powerpc-e500',
                        'linux-image-3.8.0-1-powerpc-smp',
                        'linux-image-3.5.0-19-powerpc64-smp',
                        'linux-image-3.8.0-2-powerpc64-smp',
                        'linux-image-3.0.27-1-ac100'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, 'linux-powerpc-e500')
        finally:
            chroot.remove()

    def test_linux_detection_names_chroot5(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-3.2.0-36-lowlatency-pae',
                                extra_tags={'Source': 'linux-lowlatency'})
            archive.create_deb('linux-image-3.8.0-0-lowlatency',
                                extra_tags={'Source': 'linux-lowlatency'})
            archive.create_deb('linux-image-3.5.0-18-generic',
                                extra_tags={'Source':
                                            'linux-lts-quantal'})
            archive.create_deb('linux-image-3.5.0-19-generic',
                                extra_tags={'Source':
                                             'linux-lts-quantal'})
            archive.create_deb('linux-image-generic',
                                extra_tags={'Source':
                                            'linux-meta'})
            archive.create_deb('linux-image-generic-lts-quantal',
                                extra_tags={'Source':
                                            'linux-meta-lts-quantal'})
            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, '')

            # Install kernel packages
            for pkg in ('linux-image-3.2.0-36-lowlatency-pae',
                        'linux-image-3.8.0-0-lowlatency',
                        'linux-image-3.5.0-18-generic',
                        'linux-image-3.5.0-19-generic',
                        'linux-image-generic',
                        'linux-image-generic-lts-quantal'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, 'linux-lowlatency')
        finally:
            chroot.remove()

if __name__ == '__main__':
    if 'umockdev' not in os.environ.get('LD_PRELOAD', ''):
        sys.stderr.write('This test suite needs to be run under umockdev-wrapper\n')
        sys.exit(1)

    unittest.main()
