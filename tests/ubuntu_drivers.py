# (C) 2012 Canonical Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import unittest
import subprocess
import resource
import sys
import tempfile
import shutil
import logging

# from gi.repository import GLib
from gi.repository import UMockdev
import apt
import aptdaemon.test

import UbuntuDrivers.detect
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
    # covered by stracciatella.deb / universe
    t.add_device('pci', 'orange', None, ['modalias', 'pci:v98761234d00sv00000001sd00bc00sc00i00'], [])
    # covered by neapolitan.deb / restricted
    t.add_device('pci', 'purple', None, ['modalias', 'pci:v67891234d00sv00000001sd00bc00sc00i00'], [])
    # covered by tuttifrutti.deb / multiverse
    t.add_device('usb', 'aubergine', None, ['modalias', 'usb:v1234dABCDsv01sd02bc00sc01i05'], [])

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
                 extra_tags={'Modaliases':
                 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*, pci:v000010DEd000010C4sv*sd*bc03sc*i*,)'})
    a.create_deb('nvidia-old', dependencies={'Depends': 'xorg-video-abi-3'},
                 extra_tags={'Modaliases':
                 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*, pci:v000010DEd000010C2sv*sd*bc03sc*i*,)'})

    # Free package in universe
    a.create_deb('stracciatella',
                 component='universe',
                 extra_tags={
                     'Modaliases': 'stracciatella(pci:v98761234d*sv*sd*bc*sc*i*, pci:v0000BEEFd*sv*sd*bc*sc*i*)'})

    # Non-free packages
    a.create_deb('neapolitan',
                 component='restricted',
                 extra_tags={'Modaliases': 'neapolitan(pci:v67891234d*sv*sd*bc*sc*i*, pci:v0000BEEFd*sv*sd*bc*sc*i*)'})

    a.create_deb('tuttifrutti',
                 component='multiverse',
                 extra_tags={
                     'Modaliases': 'tuttifrutti(usb:v1234dABCDsv*sd*bc00sc*i*, pci:v0000BEEFd*sv*sd*bc*sc*i00)'})

    # packages not covered by modalises, for testing detection plugins
    a.create_deb('special')
    a.create_deb('picky')
    a.create_deb('special-uninst', dependencies={'Depends': 'xorg-video-abi-3'})

    return a


def get_deb_arch():
    proc = subprocess.Popen(['dpkg', '--print-architecture'], stdout=subprocess.PIPE,
                            universal_newlines=True)
    try:
        output = proc.communicate()[0]
        output = output.strip()
    except Exception:
        return None
    return output


class DetectTest(unittest.TestCase):
    '''Test UbuntuDrivers.detect'''

    def setUp(self):
        '''Create a fake sysfs'''

        self.umockdev = gen_fakehw()

        # no custom detection plugins by default
        self.plugin_dir = tempfile.mkdtemp()
        os.environ['UBUNTU_DRIVERS_DETECT_DIR'] = self.plugin_dir
        os.environ['UBUNTU_DRIVERS_SYS_DIR'] = self.umockdev.get_sys_dir()

    def tearDown(self):
        shutil.rmtree(self.plugin_dir)

        # most test cases switch the apt root, so the apt.Cache() cache becomes
        # unreliable; reset it
        UbuntuDrivers.detect.packages_for_modalias.cache_maps = {}

    @unittest.skipUnless(os.path.isdir('/sys/devices'), 'no /sys dir on this system')
    def test_system_modaliases_system(self):
        '''system_modaliases() for current system'''

        # Let's skip the test on s390x
        if 's390x' in os.uname().machine:
            self.assertTrue(True)
        else:
            del self.umockdev
            res = UbuntuDrivers.detect.system_modaliases()
            self.assertGreater(len(res), 3)
            self.assertTrue(':' in list(res)[0])

    def test_system_modalises_fake(self):
        '''system_modaliases() for fake sysfs'''

        res = UbuntuDrivers.detect.system_modaliases(self.umockdev.get_sys_dir())
        self.assertEqual(set(res), set([
            'pci:v00001234d00sv00000001sd00bc00sc00i00',
            'pci:vDEADBEEFd00', 'usb:v9876dABCDsv01sd02bc00sc01i05',
            'usb:v1234dABCDsv01sd02bc00sc01i05',
            'pci:v98761234d00sv00000001sd00bc00sc00i00',
            'pci:v67891234d00sv00000001sd00bc00sc00i00',
            modalias_nv]))
        self.assertTrue(res['pci:vDEADBEEFd00'].endswith('/sys/devices/grey'))

    def test_system_driver_packages_performance(self):
        '''system_driver_packages() performance for a lot of modaliases'''

        # add lots of fake devices/modalises
        for i in range(30):
            self.umockdev.add_device('pci', 'pcidev%i' % i, None, ['modalias', 'pci:s%04X' % i], [])
            self.umockdev.add_device('usb', 'usbdev%i' % i, None, ['modalias', 'usb:s%04X' % i], [])

        start = resource.getrusage(resource.RUSAGE_SELF)
        UbuntuDrivers.detect.system_driver_packages(sys_path=self.umockdev.get_sys_dir())
        stop = resource.getrusage(resource.RUSAGE_SELF)

        sec = (stop.ru_utime + stop.ru_stime) - (start.ru_utime + start.ru_stime)
        sys.stderr.write('[%.2f s] ' % sec)

        if 'arm' in os.uname().machine:
            target = 90.0
        elif 'i386' == get_deb_arch():
            target = 40.0
        else:
            target = 30.0

        self.assertLess(sec, target)

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

            # Overwrite sources list generate by aptdaemon testsuite to add
            # options to apt and ignore unsigned repository
            sources_list = os.path.join(chroot.path, 'etc/apt/sources.list')
            with open(sources_list, 'w') as f:
                f.write(archive.apt_source)

            cache = apt.Cache(rootdir=chroot.path)
            cache.update()
            cache.open()
            res = UbuntuDrivers.detect.system_driver_packages(cache, sys_path=self.umockdev.get_sys_dir())
        finally:
            chroot.remove()
        self.assertEqual(set(res), set(['chocolate', 'vanilla', 'nvidia-current',
                                        'nvidia-current-updates', 'nvidia-123',
                                        'nvidia-34',
                                        'neapolitan',
                                        'tuttifrutti',
                                        'stracciatella',
                                        ]))

        self.assertEqual(res['vanilla']['modalias'], 'pci:v00001234d00sv00000001sd00bc00sc00i00')
        self.assertTrue(res['vanilla']['syspath'].endswith('/devices/white'))
        self.assertTrue(res['vanilla']['from_distro'])
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

        self.assertFalse(res['neapolitan']['free'])

    def test_system_gpgpu_driver_packages_chroot1(self):
        '''system_gpgpu_driver_packages() for test package repository'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            # older applicable driver which is not the recommended one
            archive.create_deb('nvidia-driver-390', dependencies={'Depends': 'xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            # -updates driver which also should not be recommended
            archive.create_deb('nvidia-driver-410', dependencies={'Depends': 'xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            # driver package which supports multiple ABIs
            archive.create_deb('nvidia-340',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            archive.create_deb('nvidia-headless-no-dkms-410',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={})
            archive.create_deb('nvidia-headless-no-dkms-390',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={})

            chroot.add_repository(archive.path, True, False)
            cache = apt.Cache(rootdir=chroot.path)
            res = UbuntuDrivers.detect.system_gpgpu_driver_packages(cache, sys_path=self.umockdev.get_sys_dir())
        finally:
            chroot.remove()
        self.assertTrue('nvidia-driver-410' in res)
        packages = UbuntuDrivers.detect.gpgpu_install_filter(res, 'nvidia')
        self.assertEqual(set(packages), set(['nvidia-driver-410']))
        driver = list(packages.keys())[0]
        self.assertEqual(packages[driver].get('metapackage'), 'nvidia-headless-no-dkms-410')

    def test_system_gpgpu_driver_packages_chroot2(self):
        '''system_gpgpu_driver_packages() for test package repository'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            # older applicable driver which is not the recommended one
            archive.create_deb('nvidia-driver-390', dependencies={'Depends': 'xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            # -updates driver which also should not be recommended
            archive.create_deb('nvidia-driver-410', dependencies={'Depends': 'xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            # driver package which supports multiple ABIs
            archive.create_deb('nvidia-340',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})

            archive.create_deb('nvidia-headless-no-dkms-410',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={})
            archive.create_deb('nvidia-headless-no-dkms-390',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={})

            archive.create_deb('nvidia-dkms-410',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={})
            archive.create_deb('nvidia-dkms-390',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={})

            # Linux nvidia modules
            archive.create_deb('linux-modules-nvidia-410-generic',
                               dependencies={'Depends': 'linux-modules-nvidia-410-5.0.0-27-generic'},
                               extra_tags={})

            archive.create_deb('linux-modules-nvidia-410-5.0.0-27-generic',
                               dependencies={'Depends': 'linux-image-5.0.0-27-generic'},
                               extra_tags={})

            # Image packages
            archive.create_deb('linux-image-4.15.0-20-generic',
                               extra_tags={'Source': 'linux-signed'})
            archive.create_deb('linux-image-5.0.0-27-generic',
                               extra_tags={'Source': 'linux-signed-hwe'})
            archive.create_deb('linux-image-5.0.0-20-generic',
                               extra_tags={'Source':
                                           'linux-signed-hwe-edge'})

            # Image metapackages
            archive.create_deb('linux-image-generic',
                               dependencies={'Depends': 'linux-image-4.15.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-image-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-5.0.0-27-generic'},
                               extra_tags={'Source': 'linux-meta-hwe'})
            archive.create_deb('linux-image-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-5.0.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})
            # Header packages
            archive.create_deb('linux-headers-4.15.0-20-generic',
                               extra_tags={'Source': 'linux'})
            archive.create_deb('linux-headers-5.0.0-27-generic',
                               extra_tags={'Source': 'linux-signed-hwe'})
            archive.create_deb('linux-headers-5.0.0-20-generic',
                               extra_tags={'Source':
                                           'linux-signed-hwe-edge'})

            # Header metapackages
            archive.create_deb('linux-headers-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-headers-5.0.0-27-generic'},
                               extra_tags={'Source': 'linux-meta-hwe'})
            archive.create_deb('linux-headers-generic',
                               dependencies={'Depends': 'linux-headers-4.15.0-20-generic'},
                               extra_tags={'Source': 'linux-signed'})
            archive.create_deb('linux-headers-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-headers-5.0.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})

            # Full metas
            archive.create_deb('linux-generic',
                               dependencies={'Depends': 'linux-image-generic, linux-headers-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04, '
                                                        'linux-headers-generic-hwe-18.04'},
                               extra_tags={'Source':
                                           'linux-meta-hwe'})
            archive.create_deb('linux-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04-edge, '
                                                        'linux-headers-generic-hwe-18.04-edge'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})

            chroot.add_repository(archive.path, True, False)
            cache = apt.Cache(rootdir=chroot.path)

            # Install kernel packages
            for pkg in ('linux-image-4.15.0-20-generic',
                        'linux-image-5.0.0-27-generic',
                        'linux-image-5.0.0-20-generic',
                        'linux-headers-4.15.0-20-generic',
                        'linux-headers-5.0.0-27-generic',
                        'linux-headers-5.0.0-20-generic',
                        'linux-headers-generic-hwe-18.04',
                        'linux-headers-generic',
                        'linux-headers-generic-hwe-18.04-edge',
                        'linux-image-generic-hwe-18.04',
                        'linux-image-generic',
                        'linux-image-generic-hwe-18.04-edge',
                        'linux-generic-hwe-18.04',
                        'linux-generic',
                        'linux-generic-hwe-18.04-edge'):
                cache[pkg].mark_install()

            res = UbuntuDrivers.detect.system_gpgpu_driver_packages(cache, sys_path=self.umockdev.get_sys_dir())
            linux_package = UbuntuDrivers.detect.get_linux(cache)
            modules_package = UbuntuDrivers.detect.get_linux_modules_metapackage(cache, 'nvidia-driver-410')
        finally:
            chroot.remove()

        self.assertTrue('nvidia-driver-410' in res)
        packages = UbuntuDrivers.detect.gpgpu_install_filter(res, 'nvidia')
        self.assertEqual(set(packages), set(['nvidia-driver-410']))
        driver = list(packages.keys())[0]
        self.assertEqual(packages[driver].get('metapackage'), 'nvidia-headless-no-dkms-410')
        self.assertEqual(linux_package, 'linux-generic-hwe-18.04')
        # No linux-modules-nvidia module is available for the kernel
        # So we expect the DKMS package as a fallback
        self.assertEqual(modules_package, 'nvidia-dkms-410')

    def test_system_gpgpu_driver_packages_chroot3(self):
        '''system_gpgpu_driver_packages() for test package repository'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            # older applicable driver which is not the recommended one
            archive.create_deb('nvidia-driver-390', dependencies={'Depends': 'xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            # -updates driver which also should not be recommended
            archive.create_deb('nvidia-driver-410', dependencies={'Depends': 'xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})
            # driver package which supports multiple ABIs
            archive.create_deb('nvidia-340',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={'Modaliases': 'nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)'})

            archive.create_deb('nvidia-headless-no-dkms-410',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={})
            archive.create_deb('nvidia-headless-no-dkms-390',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={})

            archive.create_deb('nvidia-dkms-410',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={})
            archive.create_deb('nvidia-dkms-390',
                               dependencies={'Depends': 'xorg-video-abi-3 | xorg-video-abi-4'},
                               extra_tags={})

            # Linux nvidia modules
            archive.create_deb('linux-modules-nvidia-410-generic',
                               dependencies={'Depends': 'linux-modules-nvidia-410-4.15.0-20-generic'},
                               extra_tags={})

            archive.create_deb('linux-modules-nvidia-410-4.15.0-20-generic',
                               dependencies={'Depends': 'linux-image-4.15.0-20-generic'},
                               extra_tags={})

            # Image packages
            archive.create_deb('linux-image-4.15.0-20-generic',
                               extra_tags={'Source': 'linux-signed'})
            archive.create_deb('linux-image-5.0.0-27-generic',
                               extra_tags={'Source': 'linux-signed-hwe'})
            archive.create_deb('linux-image-5.0.0-20-generic',
                               extra_tags={'Source':
                                           'linux-signed-hwe-edge'})

            # Image metapackages
            archive.create_deb('linux-image-generic',
                               dependencies={'Depends': 'linux-image-4.15.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-image-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-5.0.0-27-generic'},
                               extra_tags={'Source': 'linux-meta-hwe'})
            archive.create_deb('linux-image-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-5.0.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})
            # Header packages
            archive.create_deb('linux-headers-4.15.0-20-generic',
                               extra_tags={'Source': 'linux'})
            archive.create_deb('linux-headers-5.0.0-27-generic',
                               extra_tags={'Source': 'linux-signed-hwe'})
            archive.create_deb('linux-headers-5.0.0-20-generic',
                               extra_tags={'Source':
                                           'linux-signed-hwe-edge'})

            # Header metapackages
            archive.create_deb('linux-headers-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-headers-5.0.0-27-generic'},
                               extra_tags={'Source': 'linux-meta-hwe'})
            archive.create_deb('linux-headers-generic',
                               dependencies={'Depends': 'linux-headers-4.15.0-20-generic'},
                               extra_tags={'Source': 'linux-signed'})
            archive.create_deb('linux-headers-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-headers-5.0.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})

            # Full metas
            archive.create_deb('linux-generic',
                               dependencies={'Depends': 'linux-image-generic, linux-headers-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04, '
                                                        'linux-headers-generic-hwe-18.04'},
                               extra_tags={'Source':
                                           'linux-meta-hwe'})
            archive.create_deb('linux-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04-edge, '
                                                        'linux-headers-generic-hwe-18.04-edge'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})

            chroot.add_repository(archive.path, True, False)
            cache = apt.Cache(rootdir=chroot.path)

            # Install kernel packages
            for pkg in ('linux-image-4.15.0-20-generic',
                        'linux-headers-4.15.0-20-generic',
                        'linux-headers-5.0.0-27-generic',
                        'linux-headers-5.0.0-20-generic',
                        'linux-headers-generic-hwe-18.04',
                        'linux-headers-generic',
                        'linux-headers-generic-hwe-18.04-edge',
                        'linux-image-generic',
                        'linux-generic'):
                cache[pkg].mark_install()

            res = UbuntuDrivers.detect.system_gpgpu_driver_packages(cache,
                                                                    sys_path=self.umockdev.get_sys_dir())
            linux_package = UbuntuDrivers.detect.get_linux(cache)
            modules_package = UbuntuDrivers.detect.get_linux_modules_metapackage(cache,
                                                                                 'nvidia-driver-410')
        finally:
            chroot.remove()

        self.assertTrue('nvidia-driver-410' in res)
        packages = UbuntuDrivers.detect.gpgpu_install_filter(res, 'nvidia')
        self.assertEqual(set(packages), set(['nvidia-driver-410']))
        driver = list(packages.keys())[0]
        self.assertEqual(packages[driver].get('metapackage'), 'nvidia-headless-no-dkms-410')
        self.assertEqual(linux_package, 'linux-generic')
        # Get the linux-modules-nvidia module for the kernel
        # So we expect the DKMS package as a fallback
        self.assertEqual(modules_package, 'linux-modules-nvidia-410-generic')

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
            res = UbuntuDrivers.detect.system_driver_packages(cache, sys_path=self.umockdev.get_sys_dir())
        finally:
            chroot.remove()

        self.assertEqual(
            set(res),
            set(['chocolate', 'vanilla', 'nvidia-current',
                 'neapolitan', 'tuttifrutti', 'stracciatella']))

    def test_system_driver_packages_detect_plugins(self):
        '''system_driver_packages() includes custom detection plugins'''

        with open(os.path.join(self.plugin_dir, 'extra.py'), 'w') as f:
            f.write('def detect(apt): return ["coreutils", "no_such_package"]\n')

        res = UbuntuDrivers.detect.system_driver_packages(sys_path=self.umockdev.get_sys_dir())
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
            res = UbuntuDrivers.detect.system_device_drivers(cache, sys_path=self.umockdev.get_sys_dir())
        finally:
            chroot.remove()

        white = '/sys/devices/white'
        black = '/sys/devices/black'
        graphics = '/sys/devices/graphics'
        self.assertEqual(len(res), 6)  # the three devices above + 3 fake devices
        self.assertEqual(
            set([os.path.basename(d) for d in res]),
            set(['white', 'purple', 'aubergine', 'orange', 'graphics', 'black']))

        white_dict = [value for key, value in res.items() if key.endswith(white)][0]
        black_dict = [value for key, value in res.items() if key.endswith(black)][0]
        graphics_dict = [value for key, value in res.items() if key.endswith(graphics)][0]

        self.assertEqual(white_dict,
                         {'modalias': 'pci:v00001234d00sv00000001sd00bc00sc00i00',
                          'drivers': {'vanilla': {'free': True, 'from_distro': False}}
                          })

        self.assertEqual(black_dict,
                         {'modalias': 'usb:v9876dABCDsv01sd02bc00sc01i05',
                          'drivers': {'chocolate': {'free': True, 'from_distro': False}}
                          })

        self.assertEqual(graphics_dict['modalias'], modalias_nv)
        self.assertTrue('nvidia' in graphics_dict['vendor'].lower())
        self.assertTrue('GeForce' in graphics_dict['model'])

        # should contain nouveau driver; note that free is True here because
        # these come from the fake archive
        self.assertEqual(graphics_dict['drivers']['nvidia-current'],
                         {'free': True, 'from_distro': False, 'recommended': True})
        self.assertEqual(graphics_dict['drivers']['nvidia-current-updates'],
                         {'free': True, 'from_distro': False, 'recommended': False})
        self.assertEqual(graphics_dict['drivers']['nvidia-123'],
                         {'free': True, 'from_distro': False, 'recommended': False})
        self.assertEqual(graphics_dict['drivers']['nvidia-experimental'],
                         {'free': True, 'from_distro': False, 'recommended': False})
        self.assertEqual(graphics_dict['drivers']['xserver-xorg-video-nouveau'],
                         {'free': True, 'from_distro': True, 'recommended': False, 'builtin': True})
        self.assertEqual(len(graphics_dict['drivers']), 5, list(graphics_dict['drivers'].keys()))

    def test_system_device_drivers_detect_plugins(self):
        '''system_device_drivers() includes custom detection plugins'''

        with open(os.path.join(self.plugin_dir, 'extra.py'), 'w') as f:
            f.write('def detect(apt): return ["coreutils", "no_such_package"]\n')

        res = UbuntuDrivers.detect.system_device_drivers(sys_path=self.umockdev.get_sys_dir())
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

            res = UbuntuDrivers.detect.system_device_drivers(cache, sys_path=self.umockdev.get_sys_dir())
        finally:
            chroot.remove()
            os.environ['PATH'] = orig_path

        graphics = '/sys/devices/graphics'
        graphics_dict = [value for key, value in res.items() if key.endswith(graphics)][0]
        self.assertEqual(graphics_dict['modalias'], modalias_nv)
        self.assertTrue(graphics_dict['manual_install'])

        # should still show the drivers
        self.assertGreater(len(graphics_dict['drivers']), 1)

    def test_auto_install_filter(self):
        '''auto_install_filter()'''

        self.assertEqual(UbuntuDrivers.detect.auto_install_filter({}), {})

        pkgs = {'bcmwl-kernel-source': {},
                'nvidia-current': {},
                'fglrx-updates': {},
                'pvr-omap4-egl': {}}

        self.assertEqual(
            set(UbuntuDrivers.detect.auto_install_filter(pkgs)),
            set(['bcmwl-kernel-source', 'pvr-omap4-egl', 'nvidia-current']))

        # should not include non-recommended variants
        pkgs = {'bcmwl-kernel-source': {},
                'nvidia-current': {'recommended': False},
                'nvidia-173': {'recommended': True}}
        self.assertEqual(set(UbuntuDrivers.detect.auto_install_filter(pkgs)),
                         set(['bcmwl-kernel-source', 'nvidia-173']))

    def test_gpgpu_install_filter(self):
        '''gpgpu_install_filter()'''

        # gpgpu driver[:version][,driver[:version]]
        self.assertEqual(UbuntuDrivers.detect.gpgpu_install_filter({}, 'nvidia'), {})

        pkgs = {'nvidia-driver-390': {'recommended': True},
                'nvidia-driver-410': {},
                'nvidia-driver-340': {'recommended': False}}

        # Nothing is specified, we return the recommended driver
        self.assertEqual(
            set(UbuntuDrivers.detect.gpgpu_install_filter(pkgs, 'nvidia')),
            set(['nvidia-driver-390']))

        # We specify that we want nvidia 410
        pkgs = {'nvidia-driver-390': {'recommended': True},
                'nvidia-driver-410': {},
                'nvidia-driver-340': {'recommended': False}}
        self.assertEqual(set(UbuntuDrivers.detect.gpgpu_install_filter(pkgs, '410')),
                         set(['nvidia-driver-410']))

        self.assertEqual(set(UbuntuDrivers.detect.gpgpu_install_filter(pkgs, 'nvidia:410')),
                         set(['nvidia-driver-410']))

        # Now with multiple drivers (to be implemented in the future)
        self.assertEqual(set(UbuntuDrivers.detect.gpgpu_install_filter(pkgs, 'nvidia:410,amdgpu:284')),
                         set(['nvidia-driver-410']))

        # Specify the same nvidia driver twice, just to break things
        self.assertEqual(UbuntuDrivers.detect.gpgpu_install_filter(pkgs, 'nvidia:410,nvidia:390'),
                         {})

        # More incorrect values
        self.assertEqual(UbuntuDrivers.detect.gpgpu_install_filter(pkgs, 'nv:410'), {})

        self.assertEqual(UbuntuDrivers.detect.gpgpu_install_filter(pkgs, ':410'), {})

        self.assertEqual(UbuntuDrivers.detect.gpgpu_install_filter(pkgs, 'nvidia-driver:410'), {})

    def test_system_driver_packages_freeonly(self):
        '''system_driver_packages() returns only free packages'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            archive = gen_fakearchive()
            chroot.add_repository(archive.path, True, False)

            # Overwrite sources list generate by aptdaemon testsuite to add
            # options to apt and ignore unsigned repository
            sources_list = os.path.join(chroot.path, 'etc/apt/sources.list')
            with open(sources_list, 'w') as f:
                f.write(archive.apt_source)

            cache = apt.Cache(rootdir=chroot.path)
            cache.update()
            cache.open()

            res = set(UbuntuDrivers.detect.system_driver_packages(
                cache, sys_path=self.umockdev.get_sys_dir(), freeonly=True))
        finally:
            chroot.remove()

        self.assertEqual(res, set(['stracciatella', 'vanilla', 'chocolate', 'nvidia-current']))

    def test_system_device_drivers_freeonly(self):
        '''system_device_drivers() returns only devices with free drivers'''

        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            archive = gen_fakearchive()
            chroot.add_repository(archive.path, True, False)

            # Overwrite sources list generate by aptdaemon testsuite to add
            # options to apt and ignore unsigned repository
            sources_list = os.path.join(chroot.path, 'etc/apt/sources.list')
            with open(sources_list, 'w') as f:
                f.write(archive.apt_source)

            cache = apt.Cache(rootdir=chroot.path)
            cache.update()
            cache.open()

            res = UbuntuDrivers.detect.system_device_drivers(cache, sys_path=self.umockdev.get_sys_dir(), freeonly=True)
        finally:
            chroot.remove()
        self.assertEqual(
            set([os.path.basename(d) for d in res]),
            set(['black', 'white', 'graphics', 'orange']))

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

            archive.create_deb('linux-headers-3.2.0-23-generic',
                               extra_tags={'Source': 'linux'})
            archive.create_deb('linux-headers-3.2.0-33-generic',
                               extra_tags={'Source': 'linux'})
            archive.create_deb('linux-headers-3.5.0-18-generic',
                               extra_tags={'Source':
                                           'linux-lts-quantal'})
            archive.create_deb('linux-headers-3.5.0-19-generic',
                               extra_tags={'Source':
                                           'linux-lts-quantal'})

            archive.create_deb('linux-image-generic',
                               dependencies={'Depends': 'linux-image-3.2.0-33-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-image-generic-lts-quantal',
                               dependencies={'Depends': 'linux-image-3.5.0-19-generic'},
                               extra_tags={'Source':
                                           'linux-meta-lts-quantal'})

            archive.create_deb('linux-headers-generic',
                               dependencies={'Depends': 'linux-headers-3.2.0-33-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-headers-generic-lts-quantal',
                               dependencies={'Depends': 'linux-headers-3.5.0-19-generic'},
                               extra_tags={'Source':
                                           'linux-meta-lts-quantal'})

            archive.create_deb('linux-generic',
                               dependencies={'Depends': 'linux-image-generic, '
                                                        'linux-headers-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-generic-lts-quantal',
                               dependencies={'Depends': 'linux-image-generic-lts-quantal, '
                                                        'linux-headers-generic-lts-quantal'},
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
                        'linux-headers-3.2.0-23-generic',
                        'linux-headers-3.2.0-33-generic',
                        'linux-headers-3.5.0-18-generic',
                        'linux-headers-3.5.0-19-generic',
                        'linux-image-generic',
                        'linux-image-generic-lts-quantal',
                        'linux-headers-generic',
                        'linux-headers-generic-lts-quantal',
                        'linux-generic',
                        'linux-generic-lts-quantal'):
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

            archive.create_deb('linux-headers-3.2.0-23-generic',
                               extra_tags={'Source': 'linux'})
            archive.create_deb('linux-headers-3.2.0-33-generic',
                               extra_tags={'Source': 'linux'})
            archive.create_deb('linux-headers-3.5.0-18-generic',
                               extra_tags={'Source':
                                           'linux-lts-quantal'})
            archive.create_deb('linux-headers-3.5.0-19-generic',
                               extra_tags={'Source':
                                           'linux-lts-quantal'})

            archive.create_deb('linux-image-generic',
                               dependencies={'Depends': 'linux-image-3.2.0-33-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-image-generic-lts-quantal',
                               dependencies={'Depends': 'linux-image-3.5.0-19-generic'},
                               extra_tags={'Source':
                                           'linux-meta-lts-quantal'})

            archive.create_deb('linux-headers-generic',
                               dependencies={'Depends': 'linux-headers-3.2.0-33-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-headers-generic-lts-quantal',
                               dependencies={'Depends': 'linux-headers-3.5.0-19-generic'},
                               extra_tags={'Source':
                                           'linux-meta-lts-quantal'})

            archive.create_deb('linux-generic',
                               dependencies={'Depends': 'linux-image-generic, '
                                                        'linux-headers-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-generic-lts-quantal',
                               dependencies={'Depends': 'linux-image-generic-lts-quantal, '
                                                        'linux-headers-generic-lts-quantal'},
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
                        'linux-headers-3.2.0-23-generic',
                        'linux-headers-3.2.0-33-generic',
                        'linux-headers-3.5.0-18-generic',
                        'linux-headers-3.5.0-19-generic',
                        'linux-image-generic',
                        'linux-image-generic-lts-quantal',
                        'linux-headers-generic',
                        'linux-headers-generic-lts-quantal',
                        'linux-generic',
                        'linux-generic-lts-quantal'):
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
        os.environ['UBUNTU_DRIVERS_SYS_DIR'] = self.umockdev.get_sys_dir()

    def tearDown(self):
        # some tests install this package
        apt = subprocess.Popen(['apt-get', 'purge', '-y', 'bcmwl-kernel-source'],
                               stdout=subprocess.PIPE)
        apt.communicate()
        self.assertEqual(apt.returncode, 0)

    def test_list_chroot(self):
        '''ubuntu-drivers list for fake sysfs and chroot'''

        ud = subprocess.Popen(
            [self.tool_path, 'list'],
            universal_newlines=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertEqual(set(out.splitlines()),
                         set(['vanilla', 'chocolate', 'bcmwl-kernel-source', 'nvidia-current',
                             'stracciatella', 'tuttifrutti', 'neapolitan']))
        self.assertEqual(ud.returncode, 0)

    def test_list_detect_plugins(self):
        '''ubuntu-drivers list includes custom detection plugins'''

        os.mkdir(self.plugin_dir)
        self.addCleanup(shutil.rmtree, self.plugin_dir)

        with open(os.path.join(self.plugin_dir, 'special.py'), 'w') as f:
            f.write('def detect(apt): return ["special", "special-uninst", "special-unavail", "picky"]\n')

        ud = subprocess.Popen(
            [self.tool_path, 'list'],
            universal_newlines=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertEqual(set(out.splitlines()),
                         set(['vanilla', 'chocolate', 'bcmwl-kernel-source',
                              'nvidia-current', 'special', 'picky',
                              'stracciatella', 'tuttifrutti', 'neapolitan']))
        self.assertEqual(ud.returncode, 0)

    def test_devices_chroot(self):
        '''ubuntu-drivers devices for fake sysfs and chroot'''

        ud = subprocess.Popen(
            [self.tool_path, 'devices'],
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

        ud = subprocess.Popen(
            [self.tool_path, 'devices'],
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

    def test_auto_install_chroot(self):
        '''ubuntu-drivers install for fake sysfs and chroot'''

        ud = subprocess.Popen(
            [self.tool_path, 'install'],
            universal_newlines=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=os.environ)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertTrue('bcmwl-kernel-source' in out, out)
        self.assertFalse('vanilla' in out, out)
        self.assertFalse('noalias' in out, out)
        self.assertEqual(ud.returncode, 0)

        # now all packages should be installed, so it should not do anything
        ud = subprocess.Popen(
            [self.tool_path, 'install'],
            universal_newlines=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=os.environ)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertFalse('bcmwl-kernel-source' in out, out)
        self.assertEqual(ud.returncode, 0)

    def test_auto_install_packagelist(self):
        '''ubuntu-drivers install package list creation'''

        listfile = os.path.join(self.chroot.path, 'pkgs')
        self.addCleanup(os.unlink, listfile)

        ud = subprocess.Popen(
            [self.tool_path, 'install', '--package-list', listfile],
            universal_newlines=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        out, err = ud.communicate()
        self.assertEqual(err, '')
        self.assertEqual(ud.returncode, 0)

        with open(listfile) as f:
            self.assertEqual(f.read(), 'bcmwl-kernel-source\n')

    def test_debug(self):
        '''ubuntu-drivers debug'''

        os.mkdir(self.plugin_dir)
        self.addCleanup(shutil.rmtree, self.plugin_dir)

        with open(os.path.join(self.plugin_dir, 'special.py'), 'w') as f:
            f.write('def detect(apt): return ["special", "special-uninst", "special-unavail"]\n')

        ud = subprocess.Popen(
            [self.tool_path, 'debug'],
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

        ud = subprocess.Popen(
            [os.path.join(ROOT_DIR, 'ubuntu-drivers'), 'debug'],
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
        os.environ['UBUNTU_DRIVERS_SYS_DIR'] = self.umockdev.get_sys_dir()

    def tearDown(self):
        shutil.rmtree(self.plugin_dir)

    def test_linux_headers_detection_chroot(self):
        '''get_linux_headers_metapackage() for test package repository'''
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()

            # Image packages
            archive.create_deb('linux-image-4.15.0-20-generic',
                               extra_tags={'Source': 'linux-signed'})
            archive.create_deb('linux-image-5.0.0-27-generic',
                               extra_tags={'Source': 'linux-signed-hwe'})
            archive.create_deb('linux-image-5.0.0-20-generic',
                               extra_tags={'Source':
                                           'linux-signed-hwe-edge'})

            # Image metapackages
            archive.create_deb('linux-image-generic',
                               dependencies={'Depends': 'linux-image-4.15.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-image-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-5.0.0-27-generic'},
                               extra_tags={'Source': 'linux-meta-hwe'})
            archive.create_deb('linux-image-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-5.0.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})
            # Header packages
            archive.create_deb('linux-headers-4.15.0-20-generic',
                               extra_tags={'Source': 'linux'})
            archive.create_deb('linux-headers-5.0.0-27-generic',
                               extra_tags={'Source': 'linux-signed-hwe'})
            archive.create_deb('linux-headers-5.0.0-20-generic',
                               extra_tags={'Source':
                                           'linux-signed-hwe-edge'})

            # Header metapackages
            archive.create_deb('linux-headers-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-headers-5.0.0-27-generic'},
                               extra_tags={'Source': 'linux-meta-hwe'})
            archive.create_deb('linux-headers-generic',
                               dependencies={'Depends': 'linux-headers-4.15.0-20-generic'},
                               extra_tags={'Source': 'linux-signed'})
            archive.create_deb('linux-headers-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-headers-5.0.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})

            # Full metas
            archive.create_deb('linux-generic',
                               dependencies={'Depends': 'linux-image-generic, '
                                                        'linux-headers-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04, '
                                                        'linux-headers-generic-hwe-18.04'},
                               extra_tags={'Source':
                                           'linux-meta-hwe'})
            archive.create_deb('linux-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04-edge, '
                                                        'linux-headers-generic-hwe-18.04-edge'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux, '')

            # Install kernel packages
            for pkg in ('linux-image-4.15.0-20-generic',
                        'linux-image-5.0.0-27-generic',
                        'linux-image-5.0.0-20-generic',
                        'linux-headers-4.15.0-20-generic',
                        'linux-headers-5.0.0-27-generic',
                        'linux-headers-5.0.0-20-generic',
                        'linux-headers-generic-hwe-18.04',
                        'linux-headers-generic',
                        'linux-headers-generic-hwe-18.04-edge',
                        'linux-image-generic-hwe-18.04',
                        'linux-image-generic',
                        'linux-image-generic-hwe-18.04-edge',
                        'linux-generic-hwe-18.04',
                        'linux-generic',
                        'linux-generic-hwe-18.04-edge'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux, 'linux-headers-generic-hwe-18.04')
        finally:
            chroot.remove()

    def test_linux_headers_detection_names_chroot2(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-powerpc-smp',
                               dependencies={'Depends': 'linux-image-3.8.0-1-powerpc-smp'},
                               extra_tags={'Source':
                                           'linux-ppc'})

            archive.create_deb('linux-image-powerpc-e500',
                               dependencies={'Depends': 'linux-image-3.8.0-3-powerpc-e500'},
                               extra_tags={'Source':
                                           'linux-ppc'})

            archive.create_deb('linux-image-powerpc64-smp',
                               dependencies={'Depends': 'linux-image-3.8.0-2-powerpc64-smp'},
                               extra_tags={'Source':
                                           'linux-ppc'})

            archive.create_deb('linux-headers-powerpc-smp',
                               dependencies={'Depends': 'linux-headers-3.8.0-1-powerpc-smp'},
                               extra_tags={'Source':
                                           'linux-ppc'})

            archive.create_deb('linux-headers-powerpc-e500',
                               dependencies={'Depends': 'linux-headers-3.8.0-3-powerpc-e500'},
                               extra_tags={'Source':
                                           'linux-ppc'})

            archive.create_deb('linux-headers-powerpc64-smp',
                               dependencies={'Depends': 'linux-headers-3.8.0-2-powerpc64-smp'},
                               extra_tags={'Source':
                                           'linux-ppc'})

            archive.create_deb('linux-powerpc-smp',
                               dependencies={'Depends': 'linux-headers-3.8.0-1-powerpc-smp, '
                                                        'linux-image-3.8.0-1-powerpc-smp'},
                               extra_tags={'Source':
                                           'linux-ppc'})

            archive.create_deb('linux-powerpc-e500',
                               dependencies={'Depends': 'linux-headers-3.8.0-3-powerpc-e500, '
                                                        'linux-image-3.8.0-3-powerpc-e500'},
                               extra_tags={'Source':
                                           'linux-ppc'})

            archive.create_deb('linux-powerpc64-smp',
                               dependencies={'Depends': 'linux-headers-3.8.0-2-powerpc64-smp, '
                                                        'linux-image-3.8.0-2-powerpc64-smp'},
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

            archive.create_deb('linux-headers-3.8.0-3-powerpc-e500',
                               extra_tags={'Source':
                                           'linux-ppc'})
            archive.create_deb('linux-headers-3.8.0-1-powerpc-smp',
                               extra_tags={'Source':
                                           'linux-ppc'})
            archive.create_deb('linux-headers-3.5.0-19-powerpc64-smp',
                               extra_tags={'Source':
                                           'linux-ppc'})
            archive.create_deb('linux-headers-3.8.0-2-powerpc64-smp',
                               extra_tags={'Source':
                                           'linux-ppc'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, '')

            # Install kernel packages
            for pkg in ('linux-image-powerpc-smp',
                        'linux-headers-powerpc-smp',
                        'linux-powerpc-smp',
                        'linux-image-powerpc-e500',
                        'linux-headers-powerpc-e500',
                        'linux-powerpc-e500',
                        'linux-image-powerpc64-smp',
                        'linux-headers-powerpc64-smp',
                        'linux-powerpc64-smp',
                        'linux-image-3.8.0-3-powerpc-e500',
                        'linux-image-3.8.0-1-powerpc-smp',
                        'linux-image-3.5.0-19-powerpc64-smp',
                        'linux-image-3.8.0-2-powerpc64-smp',
                        'linux-headers-3.8.0-3-powerpc-e500',
                        'linux-headers-3.8.0-1-powerpc-smp',
                        'linux-headers-3.5.0-19-powerpc64-smp',
                        'linux-headers-3.8.0-2-powerpc64-smp'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, 'linux-headers-powerpc-e500')
        finally:
            chroot.remove()

    def test_linux_headers_detection_names_chroot3(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()

            archive.create_deb('linux-image-3.5.0-19-lowlatency',
                               extra_tags={'Source': 'linux-lowlatency'})
            archive.create_deb('linux-image-3.5.0-19-generic',
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-image-3.8.0-0-generic',
                               extra_tags={'Source':
                                           'linux-lts-quantal'})
            archive.create_deb('linux-headers-3.5.0-19-lowlatency',
                               extra_tags={'Source': 'linux-lowlatency'})
            archive.create_deb('linux-headers-3.5.0-19-generic',
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-headers-3.8.0-0-generic',
                               extra_tags={'Source':
                                           'linux-lts-quantal'})
            archive.create_deb('linux-headers-generic',
                               dependencies={'Depends': 'linux-headers-3.5.0-19-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-image-generic',
                               dependencies={'Depends': 'linux-image-3.5.0-19-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-generic',
                               dependencies={'Depends': 'linux-image-generic, '
                                                        'linux-headers-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-headers-lowlatency',
                               dependencies={'Depends': 'linux-headers-3.5.0-19-lowlatency'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-image-lowlatency',
                               dependencies={'Depends': 'linux-image-3.5.0-19-lowlatency'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-lowlatency',
                               dependencies={'Depends': 'linux-image-lowlatency, '
                                                        'linux-headers-lowlatency'},
                               extra_tags={'Source':
                                           'linux-lowlatency'})
            archive.create_deb('linux-headers-generic-lts-quantal',
                               dependencies={'Depends': 'linux-headers-3.8.0-0-generic'},
                               extra_tags={'Source':
                                           'linux-meta-lts-quantal'})
            archive.create_deb('linux-image-generic-lts-quantal',
                               dependencies={'Depends': 'linux-image-3.8.0-0-generic'},
                               extra_tags={'Source':
                                           'linux-meta-lts-quantal'})
            archive.create_deb('linux-generic-lts-quantal',
                               dependencies={'Depends': 'linux-image-generic-lts-quantal, '
                                                        'linux-headers-generic-lts-quantal'},
                               extra_tags={'Source':
                                           'linux-meta-lts-quantal'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, '')

            # Install kernel packages
            for pkg in ('linux-image-3.5.0-19-lowlatency',
                        'linux-image-3.5.0-19-generic',
                        'linux-image-3.8.0-0-generic',
                        'linux-headers-3.5.0-19-lowlatency',
                        'linux-headers-3.5.0-19-generic',
                        'linux-headers-3.8.0-0-generic',
                        'linux-image-lowlatency',
                        'linux-image-generic',
                        'linux-image-generic-lts-quantal',
                        'linux-headers-lowlatency',
                        'linux-headers-generic',
                        'linux-headers-generic-lts-quantal',
                        'linux-lowlatency',
                        'linux-generic',
                        'linux-generic-lts-quantal'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, 'linux-headers-generic-lts-quantal')
        finally:
            chroot.remove()

    def test_linux_headers_detection_names_chroot4(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()

            # Images
            archive.create_deb('linux-image-5.0.0-27-generic',
                               extra_tags={'Source': 'linux-signed-hwe'})
            archive.create_deb('linux-image-4.15.0-62-generic',
                               extra_tags={'Source': 'linux-signed'})
            archive.create_deb('linux-image-5.0.0-20-generic',
                               extra_tags={'Source': 'linux-signed-hwe-edge'})
            # Headers
            archive.create_deb('linux-headers-5.0.0-27-generic',
                               extra_tags={'Source': 'linux-signed-hwe'})
            archive.create_deb('linux-headers-4.15.0-62-generic',
                               extra_tags={'Source': 'linux-signed'})
            archive.create_deb('linux-headers-5.0.0-20-generic',
                               extra_tags={'Source': 'linux-signed-hwe-edge'})
            # Image meta
            archive.create_deb('linux-image-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-5.0.0-27-generic'},
                               extra_tags={'Source': 'linux-meta-hwe'})

            archive.create_deb('linux-image-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-5.0.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})

            archive.create_deb('linux-image-generic',
                               dependencies={'Depends': 'linux-image-4.15.0-62-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            # Header meta
            archive.create_deb('linux-headers-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-headers-5.0.0-27-generic'},
                               extra_tags={})
            archive.create_deb('linux-headers-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-headers-5.0.0-20-generic'},
                               extra_tags={})

            archive.create_deb('linux-headers-generic',
                               dependencies={'Depends': 'linux-headers-4.15.0-62-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            # Meta
            archive.create_deb('linux-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04, '
                                                        'linux-headers-generic-hwe-18.04'},
                               extra_tags={'Source':
                                           'linux-meta-hwe'})
            archive.create_deb('linux-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04-edge, '
                                                        'linux-headers-generic-hwe-18.04-edge'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})
            archive.create_deb('linux-generic',
                               dependencies={'Depends': 'linux-image-generic, '
                                                        'linux-headers-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, '')

            # Install kernel packages:
            #   Only one kernel will be installed
            #   With some (more recent headers still installed)
            for pkg in ('linux-image-4.15.0-62-generic',
                        'linux-headers-4.15.0-62-generic',
                        'linux-headers-5.0.0-27-generic',
                        'linux-headers-5.0.0-20-generic',
                        'linux-headers-generic-hwe-18.04',
                        'linux-headers-generic-hwe-18.04-edge',
                        'linux-image-generic',
                        'linux-generic'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, 'linux-generic')
            linux_image = kernel_detection.get_linux_image_metapackage()
            self.assertEqual(linux_image, 'linux-image-generic')
            linux_headers = kernel_detection.get_linux_headers_metapackage()
            self.assertEqual(linux_headers, 'linux-headers-generic')

        finally:
            chroot.remove()

    def test_linux_detection_chroot(self):
        '''get_linux_metapackage() for test package repository'''
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()

            # Image packages
            archive.create_deb('linux-image-4.15.0-20-generic',
                               extra_tags={'Source': 'linux-signed'})
            archive.create_deb('linux-image-5.0.0-27-generic',
                               extra_tags={'Source': 'linux-signed-hwe'})
            archive.create_deb('linux-image-5.0.0-20-generic',
                               extra_tags={'Source':
                                           'linux-signed-hwe-edge'})
            # Image metapackages
            archive.create_deb('linux-image-generic',
                               dependencies={'Depends': 'linux-image-4.15.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-image-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-5.0.0-27-generic'},
                               extra_tags={'Source': 'linux-meta-hwe'})
            archive.create_deb('linux-image-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-5.0.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})
            # Header packages
            archive.create_deb('linux-headers-4.15.0-20-generic',
                               extra_tags={'Source': 'linux'})
            archive.create_deb('linux-headers-5.0.0-27-generic',
                               extra_tags={'Source': 'linux-signed-hwe'})
            archive.create_deb('linux-headers-5.0.0-20-generic',
                               extra_tags={'Source':
                                           'linux-signed-hwe-edge'})
            # Header metapackages
            archive.create_deb('linux-headers-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-headers-5.0.0-27-generic'},
                               extra_tags={'Source': 'linux-meta-hwe'})
            archive.create_deb('linux-headers-generic',
                               dependencies={'Depends': 'linux-headers-4.15.0-20-generic'},
                               extra_tags={'Source': 'linux-signed'})
            archive.create_deb('linux-headers-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-headers-5.0.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})
            # Full metas
            archive.create_deb('linux-generic',
                               dependencies={'Depends': 'linux-image-generic, '
                                                        'linux-headers-generic'},
                               extra_tags={'Source':
                                           'linux-meta'})
            archive.create_deb('linux-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04, '
                                                        'linux-headers-generic-hwe-18.04'},
                               extra_tags={'Source':
                                           'linux-meta-hwe'})
            archive.create_deb('linux-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04-edge, '
                                                        'linux-headers-generic-hwe-18.04-edge'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})

            chroot.add_repository(archive.path, True, False)

            cache = apt.Cache(rootdir=chroot.path)

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, '')

            # Install kernel packages
            for pkg in ('linux-image-4.15.0-20-generic',
                        'linux-image-5.0.0-27-generic',
                        'linux-image-5.0.0-20-generic',
                        'linux-headers-4.15.0-20-generic',
                        'linux-headers-5.0.0-27-generic',
                        'linux-headers-5.0.0-20-generic',
                        'linux-headers-generic-hwe-18.04',
                        'linux-headers-generic',
                        'linux-headers-generic-hwe-18.04-edge',
                        'linux-image-generic-hwe-18.04',
                        'linux-image-generic',
                        'linux-image-generic-hwe-18.04-edge',
                        'linux-generic-hwe-18.04',
                        'linux-generic',
                        'linux-generic-hwe-18.04-edge'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, 'linux-generic-hwe-18.04')
        finally:
            chroot.remove()

    def test_linux_detection_names_chroot2(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-powerpc-smp',
                               extra_tags={'Source':
                                           'linux-ppc'})
            archive.create_deb('linux-image-powerpc-e500',
                               dependencies={'Depends': 'linux-image-3.8.0-3-powerpc-e500'},
                               extra_tags={'Source':
                                           'linux-ppc'})
            archive.create_deb('linux-powerpc-e500',
                               dependencies={'Depends': 'linux-image-powerpc-e500'},
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
                        'linux-image-powerpc-e500',
                        'linux-powerpc-e500',
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
            archive.create_deb('linux-lowlatency',
                               dependencies={'Depends': 'linux-image-lowlatency'},
                               extra_tags={'Source': 'linux-lowlatency'})
            archive.create_deb('linux-image-lowlatency',
                               dependencies={'Depends': 'linux-image-3.8.0-0-lowlatency'},
                               extra_tags={'Source': 'linux-lowlatency'})

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
                        'linux-image-generic-lts-quantal',
                        'linux-image-lowlatency',
                        'linux-lowlatency'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, 'linux-lowlatency')
        finally:
            chroot.remove()

    def test_linux_detection_names_chroot6(self):
        chroot = aptdaemon.test.Chroot()
        try:
            chroot.setup()
            chroot.add_test_repository()
            archive = gen_fakearchive()
            archive.create_deb('linux-image-5.0.0-27-generic',
                               extra_tags={'Source': 'linux-signed-hwe'})
            archive.create_deb('linux-image-4.15.0-62-generic',
                               extra_tags={'Source': 'linux-signed'})
            archive.create_deb('linux-image-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-5.0.0-27-generic'},
                               extra_tags={'Source': 'linux-meta-hwe'})
            archive.create_deb('linux-image-5.0.0-20-generic',
                               extra_tags={'Source': 'linux-signed-hwe-edge'})
            archive.create_deb('linux-image-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-5.0.0-20-generic'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})
            archive.create_deb('linux-generic-hwe-18.04',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04, '
                                                        'linux-headers-generic-hwe-18.04'},
                               extra_tags={'Source':
                                           'linux-meta-hwe'})
            archive.create_deb('linux-generic-hwe-18.04-edge',
                               dependencies={'Depends': 'linux-image-generic-hwe-18.04-edge, '
                                                        'linux-headers-generic-hwe-18.04-edge'},
                               extra_tags={'Source':
                                           'linux-meta-hwe-edge'})
            archive.create_deb('linux-headers-generic-hwe-18.04',
                               extra_tags={})
            archive.create_deb('linux-headers-generic-hwe-18.04-edge',
                               extra_tags={})
            archive.create_deb('linux-image-generic',
                               dependencies={'Depends': 'linux-image-4.15.0-62-generic, '
                                                        'linux-headers-4.15.0-62-generic'},
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
            for pkg in ('linux-image-5.0.0-27-generic',
                        'linux-image-5.0.0-20-generic',
                        'linux-image-4.15.0-62-generic',
                        'linux-image-generic-hwe-18.04',
                        'linux-image-generic-hwe-18.04-edge',
                        'linux-headers-generic-hwe-18.04',
                        'linux-headers-generic-hwe-18.04-edge',
                        'linux-generic-hwe-18.04',
                        'linux-generic-hwe-18.04-edge',
                        'linux-image-generic',
                        'linux-image-generic-lts-quantal'):
                cache[pkg].mark_install()

            kernel_detection = UbuntuDrivers.kerneldetection.KernelDetection(cache)
            linux = kernel_detection.get_linux_metapackage()
            self.assertEqual(linux, 'linux-generic-hwe-18.04')
        finally:
            chroot.remove()


if __name__ == '__main__':
    if 'umockdev' not in os.environ.get('LD_PRELOAD', ''):
        sys.stderr.write('This test suite needs to be run under umockdev-wrapper\n')
        sys.exit(1)

    unittest.main()
