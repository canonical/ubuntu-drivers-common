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

from gi.repository import GLib
from gi.repository import PackageKitGlib
import apt
import aptdaemon.test
import aptdaemon.pkcompat

import UbuntuDrivers.detect
import UbuntuDrivers.PackageKit

import fakesysfs
import testarchive
import logging

TEST_DIR = os.path.abspath(os.path.dirname(__file__))
ROOT_DIR = os.path.dirname(TEST_DIR)

# show aptdaemon log in test output?
APTDAEMON_LOG = False
# show aptdaemon debug level messages?
APTDAEMON_DEBUG = False

dbus_address = None

# Do not look at /var/log/Xorg.0.log for the hybrid checks
os.environ['UBUNTU_DRIVERS_XORG_LOG'] = '/nonexisting'

def gen_fakesys():
    '''Generate a fake SysFS object for testing'''

    s = fakesysfs.SysFS()
    # covered by vanilla.deb
    s.add('pci', 'white', {'modalias': 'pci:v00001234d00sv00000001sd00bc00sc00i00'})
    # covered by chocolate.deb
    s.add('usb', 'black', {'modalias': 'usb:v9876dABCDsv01sd02bc00sc01i05'})
    # covered by nvidia-{current,old}.deb
    s.add('pci', 'grey', {'modalias': 'pci:vDEADBEEFd00'})
    # not covered by any driver package
    s.add('pci', 'graphics', {'modalias': 'pci:nvidia'})
    s.add('ssb', 'yellow', {}, {'MODALIAS': 'pci:vDEADBEEFd00'})

    return s

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
            extra_tags={'Modaliases': 'nv(pci:nvidia)'})
    a.create_deb('nvidia-old', dependencies={'Depends': 'xorg-video-abi-3'},
            extra_tags={'Modaliases': 'nv(pci:nvidia)'})

    # packages not covered by modalises, for testing detection plugins
    a.create_deb('special')
    a.create_deb('picky')
    a.create_deb('special-uninst', dependencies={'Depends': 'xorg-video-abi-3'})

    return a

class PackageKitTest(aptdaemon.test.AptDaemonTestCase):
    '''Test the PackageKit plugin and API'''

    @classmethod
    def setUpClass(klass):
        klass.sys = gen_fakesys()
        os.environ['SYSFS'] = klass.sys.sysfs

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
        res = self.pk.what_provides(PackageKitGlib.FilterEnum.NONE,
                provides_type, query,
                None, lambda p, t, d: True, None)
        self.assertEqual(res.get_exit_code(), expected_res)
        if res.get_exit_code() == PackageKitGlib.ExitEnum.SUCCESS:
            return sorted([p.get_id().split(';')[0] for p in res.get_package_array()])
        else:
            return None


class DetectTest(unittest.TestCase):
    '''Test UbuntuDrivers.detect'''

    def setUp(self):
        '''Create a fake sysfs'''

        self.sys = gen_fakesys()
        os.environ['SYSFS'] = self.sys.sysfs

        # no custom detection plugins by default
        self.plugin_dir = tempfile.mkdtemp()
        os.environ['UBUNTU_DRIVERS_DETECT_DIR'] = self.plugin_dir

    def tearDown(self):
        try:
            del os.environ['SYSFS']
        except KeyError:
            pass
        shutil.rmtree(self.plugin_dir)

    @unittest.skipUnless(os.path.isdir('/sys/devices'), 'no /sys dir on this system')
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
            'pci:vDEADBEEFd00', 'usb:v9876dABCDsv01sd02bc00sc01i05',
            'pci:nvidia']))

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
            archive = gen_fakearchive()
            chroot.add_repository(archive.path, True, False)
            cache = apt.Cache(rootdir=chroot.path)
            self.assertEqual(set(UbuntuDrivers.detect.system_driver_packages(cache)),
                             set(['chocolate', 'vanilla', 'nvidia-current']))
        finally:
            chroot.remove()

    def test_system_driver_packages_detect_plugins(self):
        '''system_driver_packages() includes custom detection plugins'''

        with open(os.path.join(self.plugin_dir, 'extra.py'), 'w') as f:
            f.write('def detect(apt): return ["coreutils", "no_such_package"]\n')

        self.assertEqual(UbuntuDrivers.detect.system_driver_packages(), ['coreutils'])

    def test_system_driver_packages_hybrid(self):
        '''system_driver_packages() on hybrid Intel/NVidia systems'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            chroot.add_repository(archive.path, True, False)
            cache = apt.Cache(rootdir=chroot.path)

            xorg_log = os.path.join(chroot.path, 'Xorg.0.log')
            os.environ['UBUNTU_DRIVERS_XORG_LOG'] = xorg_log

            with open(xorg_log, 'w') as f:
                f.write('X.Org X Server 1.11.3\n[     5.547] (II) LoadModule: "extmod"\n[     5.560] (II) Loading /usr/lib/xorg/modules/drivers/intel_drv.so\n')

            self.assertEqual(set(UbuntuDrivers.detect.system_driver_packages(cache)),
                             set(['chocolate', 'vanilla']))
        finally:
            os.environ['UBUNTU_DRIVERS_XORG_LOG'] = '/nonexisting'
            chroot.remove()

    def test_auto_install_filter(self):
        '''auto_install_filter()'''

        self.assertEqual(UbuntuDrivers.detect.auto_install_filter([]), [])
        self.assertEqual(set(UbuntuDrivers.detect.auto_install_filter([
            'nvidia-current', 'bcmwl-kernel-source', 'fglrx-updates',
            'pvr-omap4-egl'])), 
            set(['bcmwl-kernel-source', 'pvr-omap4-egl']))

    def test_detect_plugin_packages(self):
        '''detect_plugin_packages()'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            self.assertEqual(UbuntuDrivers.detect.detect_plugin_packages(cache), [])

            self._gen_detect_plugins()
            # suppress logging the deliberatey errors in our test plugins to
            # stderr
            logging.getLogger().setLevel(logging.CRITICAL)
            self.assertEqual(UbuntuDrivers.detect.detect_plugin_packages(cache), 
                             ['special'])

            os.mkdir(os.path.join(self.sys.sysfs, 'pickyon'))
            self.assertEqual(set(UbuntuDrivers.detect.detect_plugin_packages(cache)), 
                             set(['special', 'picky']))
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
    if os.path.exists(os.path.join(os.environ.get("SYSFS", "/sys"), "pickyon")):
        return ["picky"]
''')


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

    @classmethod
    def tearDownClass(klass):
        klass.chroot.remove()

    def setUp(self):
        '''Create a fake sysfs'''

        self.sys = gen_fakesys()
        os.environ['SYSFS'] = self.sys.sysfs

    def tearDown(self):
        try:
            del os.environ['SYSFS']
        except KeyError:
            pass

        # some tests install this package
        subprocess.check_call(['apt-get', 'purge', '-y', 'bcmwl-kernel-source'],
                stdout=subprocess.PIPE)

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
        self.assertFalse('nvidia' in out, out)
        self.assertEqual(ud.returncode, 0)

        # now all packages should be installed, so it should not do anything
        ud = subprocess.Popen([self.tool_path, 'autoinstall'],
                universal_newlines=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertFalse('bcmwl-kernel-source' in out, out)
        self.assertTrue('already installed' in out, out)
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

if __name__ == '__main__':
    unittest.main()
