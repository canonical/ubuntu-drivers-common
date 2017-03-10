# Author: Alberto Milone
#
# Copyright (C) 2014 Canonical Ltd
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
import re
import argparse
import copy

# Global path to save logs
tests_path = None
# Global path to use valgrind
with_valgrind = False
# Global path to use gdb
with_gdb = False

class GpuTest(object):

    def __init__(self,
                 has_single_card=False,
                 requires_offloading=False,
                 has_intel=False,
                 intel_loaded=False,
                 intel_unloaded=False,
                 has_amd=False,
                 fglrx_loaded=False,
                 fglrx_unloaded=False,
                 radeon_loaded=False,
                 radeon_unloaded=False,
                 amdgpu_loaded=False,
                 amdgpu_unloaded=False,
                 has_nvidia=False,
                 nouveau_loaded=False,
                 nouveau_unloaded=False,
                 nvidia_loaded=False,
                 nvidia_unloaded=False,
                 nvidia_enabled=False,
                 nvidia_egl_enabled=False,
                 nvidia_blacklisted=False,
                 fglrx_enabled=False,
                 fglrx_blacklisted=False,
                 mesa_enabled=False,
                 mesa_egl_enabled=False,
                 prime_enabled=False,
                 prime_egl_enabled=False,
                 pxpress_enabled=False,
                 has_changed=False,
                 has_removed_xorg=False,
                 has_regenerated_xorg=False,
                 has_selected_driver=False,
                 has_not_acted=True,
                 has_skipped_hybrid=False,
                 has_added_gpu_from_file=False,
                 proprietary_installer=False,
                 matched_quirk=False,
                 loaded_with_args=False,
                 has_custom_xorg_non_hybrid=False,
                 has_custom_xorg_hybrid_performance=False,
                 has_custom_xorg_hybrid_power_saving=False,
                 copied_custom_xorg=False):
        self.has_single_card = has_single_card
        self.requires_offloading = requires_offloading
        self.has_intel = has_intel
        self.intel_loaded = intel_loaded
        self.intel_unloaded = intel_unloaded
        self.has_amd = has_amd
        self.radeon_loaded = radeon_loaded
        self.radeon_unloaded = radeon_unloaded
        self.amdgpu_loaded = amdgpu_loaded
        self.amdgpu_unloaded = amdgpu_unloaded
        self.fglrx_loaded = fglrx_loaded
        self.fglrx_unloaded = fglrx_unloaded
        self.has_nvidia = has_nvidia
        self.nouveau_loaded = nouveau_loaded
        self.nouveau_unloaded = nouveau_unloaded
        self.nvidia_loaded = nvidia_loaded
        self.nvidia_unloaded = nvidia_unloaded
        self.nvidia_enabled = nvidia_enabled
        self.nvidia_egl_enabled = nvidia_egl_enabled
        self.nvidia_blacklisted = nvidia_blacklisted
        self.fglrx_enabled = fglrx_enabled
        self.fglrx_blacklisted = fglrx_blacklisted
        self.mesa_enabled = mesa_enabled
        self.mesa_egl_enabled = mesa_egl_enabled
        self.prime_enabled = prime_enabled
        self.prime_egl_enabled = prime_egl_enabled
        self.pxpress_enabled = pxpress_enabled
        self.has_changed = has_changed
        self.has_removed_xorg = has_removed_xorg
        self.has_regenerated_xorg = has_regenerated_xorg
        self.has_selected_driver = has_selected_driver
        self.has_not_acted = has_not_acted
        self.has_skipped_hybrid = has_skipped_hybrid
        self.has_added_gpu_from_file = has_added_gpu_from_file
        self.proprietary_installer = proprietary_installer
        self.matched_quirk = matched_quirk
        self.loaded_with_args = loaded_with_args
        self.has_custom_xorg_non_hybrid = has_custom_xorg_non_hybrid
        self.has_custom_xorg_hybrid_performance = has_custom_xorg_hybrid_performance
        self.has_custom_xorg_hybrid_power_saving = has_custom_xorg_hybrid_power_saving
        self.copied_custom_xorg = copied_custom_xorg


class GpuManagerTest(unittest.TestCase):

    @classmethod
    def setUpClass(klass):
        klass.last_boot_file = tempfile.NamedTemporaryFile(mode='w', prefix='last_boot_file_', dir=tests_path, delete=False)
        klass.last_boot_file.close()
        klass.new_boot_file = tempfile.NamedTemporaryFile(mode='w', prefix='new_boot_file_', dir=tests_path, delete=False)
        klass.new_boot_file.close()
        klass.xorg_file = tempfile.NamedTemporaryFile(mode='w', prefix='xorg_file_', dir=tests_path, delete=False)
        klass.xorg_file.close()

        klass.xorg_non_hybrid_file = tempfile.NamedTemporaryFile(mode='w', prefix='non-hybrid_', dir=tests_path, delete=False)
        klass.xorg_non_hybrid_file.close()
        klass.xorg_hybrid_performance_file = tempfile.NamedTemporaryFile(mode='w', prefix='hybrid-performance_', dir=tests_path, delete=False)
        klass.xorg_hybrid_performance_file.close()
        klass.xorg_hybrid_power_saving_file = tempfile.NamedTemporaryFile(mode='w', prefix='hybrid-power-saving_', dir=tests_path, delete=False)
        klass.xorg_hybrid_power_saving_file.close()
        klass.custom_xorg_path = tests_path or "/tmp"

        klass.amd_pcsdb_file = tempfile.NamedTemporaryFile(mode='w', prefix='amd_pcsdb_file_', dir=tests_path, delete=False)
        klass.amd_pcsdb_file.close()
        klass.fake_lspci = tempfile.NamedTemporaryFile(mode='w', prefix='fake_lspci_', dir=tests_path, delete=False)
        klass.fake_lspci.close()
        klass.fake_modules = tempfile.NamedTemporaryFile(mode='w', prefix='fake_modules_', dir=tests_path, delete=False)
        klass.fake_modules.close()
        klass.fake_alternatives = tempfile.NamedTemporaryFile(mode='w', prefix='fake_alternatives_', dir=tests_path, delete=False)
        klass.fake_alternatives.close()
        klass.fake_egl_alternatives = tempfile.NamedTemporaryFile(mode='w', prefix='fake_egl_alternatives_', dir=tests_path, delete=False)
        klass.fake_egl_alternatives.close()
        klass.fake_core_alternatives = tempfile.NamedTemporaryFile(mode='w', prefix='fake_core_alternatives_', dir=tests_path, delete=False)
        klass.fake_core_alternatives.close()
        klass.gpu_detection_path = tests_path or "/tmp"
        klass.module_detection_file = tests_path or "/tmp"
        klass.gpu_detection_file = tests_path or "/tmp"
        klass.prime_settings = tempfile.NamedTemporaryFile(mode='w', prefix='prime_settings_', dir=tests_path, delete=False)
        klass.prime_settings.close()
        klass.bbswitch_path = tempfile.NamedTemporaryFile(mode='w', prefix='bbswitch_path_', dir=tests_path, delete=False)
        klass.bbswitch_path.close()
        klass.bbswitch_quirks_path = tempfile.NamedTemporaryFile(mode='w', prefix='bbswitch_quirks_path_', dir=tests_path, delete=False)
        klass.bbswitch_quirks_path.close()
        klass.dmi_product_version_path = tempfile.NamedTemporaryFile(mode='w', prefix='dmi_product_version_path_', dir=tests_path, delete=False)
        klass.dmi_product_version_path.close()
        klass.dmi_product_name_path = tempfile.NamedTemporaryFile(mode='w', prefix='dmi_product_name_path_', dir=tests_path, delete=False)
        klass.dmi_product_name_path.close()
        klass.nvidia_driver_version_path = tempfile.NamedTemporaryFile(mode='w', prefix='nvidia_driver_version_path_', dir=tests_path, delete=False)
        klass.nvidia_driver_version_path.close()
        klass.modprobe_d_path = tempfile.NamedTemporaryFile(mode='w', prefix='modprobe_d_path_', dir=tests_path, delete=False)
        klass.modprobe_d_path.close()

        klass.log = tempfile.NamedTemporaryFile(mode='w', prefix='log_', dir=tests_path, delete=False)
        klass.log.close()

        klass.valgrind_log = tempfile.NamedTemporaryFile(mode='w', prefix='valgrind_log_', dir=tests_path, delete=False)
        klass.valgrind_log.close()

        # Patterns
        klass.is_driver_loaded_pt = re.compile('Is (.+) loaded\? (.+)')
        klass.is_driver_unloaded_pt = re.compile('Was (.+) unloaded\? (.+)')
        klass.is_driver_blacklisted_pt = re.compile('Is (.+) blacklisted\? (.+)')
        klass.is_driver_enabled_pt = re.compile('Is (.+) enabled\? (.+)')
        klass.is_egl_driver_enabled_pt = re.compile('Is (.+) egl enabled\? (.+)')
        klass.has_card_pt = re.compile('Has (.+)\? (.+)')
        klass.single_card_pt = re.compile('Single card detected.*')
        klass.requires_offloading_pt = re.compile('Does it require offloading\? (.+)')
        klass.no_change_stop_pt = re.compile('No change - nothing to do')
        klass.has_changed_pt = re.compile('Has the system changed\? (.+)')

        klass.selected_driver_pt = re.compile('Selecting (.+)')
        klass.removed_xorg_pt = re.compile('Removing xorg.conf. Path: .+')
        klass.regenerated_xorg_pt = re.compile('Regenerating xorg.conf. Path: .+')
        klass.not_modified_xorg_pt = re.compile('No need to modify xorg.conf. Path .+')
        klass.no_action_pt = re.compile('Nothing to do')
        klass.has_skipped_hybrid_pt = re.compile('Lightdm is not the default display manager. Nothing to do')
        klass.loaded_and_enabled_pt = re.compile('Driver is already loaded and enabled')
        klass.proprietary_installer_pt = re.compile('Proprietary driver installer detected.*')
        klass.matched_quirk_pt = re.compile('Found matching quirk.*')
        klass.loaded_with_args_pt = re.compile('Loading (.+) with \"(.+)\" parameters.*')
        klass.has_added_gpu_from_file = re.compile('Adding GPU from file: (.+)')
        klass.copied_custom_xorg_pt = re.compile('(.+) was copied successfully to.*')
        klass.has_custom_xorg_pt = re.compile('Custom (.+) xorg.conf detected.*')

        klass.vendors = {'amd': 0x1002, 'nvidia': 0x10de,
                        'intel': 0x8086, 'unknown': 0x1016}

        klass.fake_alternative = 'null'
        klass.fake_egl_alternative = 'null'
        klass.fake_core_alternative = 'null'


    def setUp(self):
        '''
        self.last_boot_file = open(self.last_boot_file.name, 'w')
        self.fake_lspci = open(self.fake_lspci.name, 'w')
        self.fake_modules = open(self.fake_modules.name, 'w')
        self.fake_alternatives = open(self.fake_alternatives.name, 'w')
        '''
        self.remove_xorg_conf()
        self.remove_modprobe_d_path()
        #self.remove_amd_pcsdb_file()

    def tearDown(self):
        print('%s over\n' % self.this_function_name)
        # Remove all the logs
        self.handle_logs(delete=True)

    def cp_to_target_dir(self, filename):
        try:
            shutil.copy(filename, self.target_dir)
        except:
            pass

    def remove_xorg_conf(self):
        try:
            os.unlink(self.xorg_file.name)
        except:
            pass

    def remove_modprobe_d_path(self):
        try:
            os.unlink(self.modprobe_d_path)
        except:
            pass

    def remove_amd_pcsdb_file(self):
        try:
            os.unlink(self.amd_pcsdb_file.name)
        except:
            pass

    def remove_prime_files(self):
        for elem in (self.prime_settings,
                     self.bbswitch_path,
                     self.bbswitch_quirks_path,
                     self.dmi_product_version_path,
                     self.dmi_product_name_path,
                     self.nvidia_driver_version_path):
            try:
                os.unlink(elem.name)
            except:
                pass

    def remove_gpu_detection_file(self):
        try:
            os.unlink(self.module_detection_file)
            os.unlink(self.gpu_detection_file)
        except:
            pass

    def remove_valgrind_log(self):
        try:
            os.unlink(self.valgrind_log.name)
        except:
            pass

    def handle_logs(self, delete=False, copy=False):
        if tests_path:
            self.target_dir = os.path.join(tests_path, self.this_function_name)
            try:
                os.mkdir(self.target_dir)
            except:
                pass

        for file in (self.last_boot_file,
            self.new_boot_file,
            self.fake_lspci,
            self.fake_modules,
            self.fake_alternatives,
            self.fake_egl_alternatives,
            self.fake_core_alternatives,
            self.module_detection_file,
            self.gpu_detection_file,
            self.prime_settings,
            self.bbswitch_path,
            self.bbswitch_quirks_path,
            self.dmi_product_version_path,
            self.dmi_product_name_path,
            self.nvidia_driver_version_path,
            self.modprobe_d_path,
            self.log,
            self.xorg_file,
            self.xorg_non_hybrid_file,
            self.xorg_hybrid_performance_file,
            self.xorg_hybrid_power_saving_file,
            self.amd_pcsdb_file,
            self.valgrind_log):
            try:
                file.close()
            except:
                pass

            if copy:
                try:
                    # Copy to target dir
                    self.cp_to_target_dir(file.name)
                except AttributeError:
                    # If it's just a file path
                    self.cp_to_target_dir(file)

            if delete:
                try:
                    # Remove
                    os.unlink(file.name)
                except:
                    pass

    def exec_manager(self, requires_offloading=False, module_is_available=False, uses_lightdm=True):
        fake_requires_offloading = requires_offloading and '--fake-requires-offloading' or '--fake-no-requires-offloading'
        fake_module_available = module_is_available and '--fake-module-is-available' or '--fake-module-is-not-available'
        if with_valgrind:
            valgrind = ['valgrind', '--tool=memcheck', '--leak-check=full',
                        '--show-reachable=yes', '--log-file=%s' % self.valgrind_log.name,
                        '--']
        else:
            valgrind = []

        if with_gdb:
            gdb = ['gdb', '-batch', '--args']
        else:
            gdb = []


        command = ['share/hybrid/gpu-manager',
                   '--dry-run',
                   '--last-boot-file',
                   self.last_boot_file.name,
                   '--fake-lspci',
                   self.fake_lspci.name,
                   '--xorg-conf-file',
                   self.xorg_file.name,
                   '--custom-xorg-conf-path',
                   self.custom_xorg_path,
                   '--amd-pcsdb-file',
                   self.amd_pcsdb_file.name,
                   '--fake-alternative',
                   self.fake_alternative,
                   '--fake-egl-alternative',
                   self.fake_egl_alternative,
                   '--fake-core-alternative',
                   self.fake_core_alternative,
                   '--fake-modules-path',
                   self.fake_modules.name,
                   '--fake-alternatives-path',
                   self.fake_alternatives.name,
                   '--fake-egl-alternatives-path',
                   self.fake_egl_alternatives.name,
                   '--fake-core-alternatives-path',
                   self.fake_core_alternatives.name,
                   '--gpu-detection-path',
                   self.gpu_detection_path,
                   '--prime-settings',
                   self.prime_settings.name,
                   '--bbswitch-path',
                   self.bbswitch_path.name,
                   '--bbswitch-quirks-path',
                   self.bbswitch_quirks_path.name,
                   '--dmi-product-version-path',
                   self.dmi_product_version_path.name,
                   '--dmi-product-name-path',
                   self.dmi_product_name_path.name,
                   '--nvidia-driver-version-path',
                   self.nvidia_driver_version_path.name,
                   '--modprobe-d-path',
                   self.modprobe_d_path.name,
                   '--new-boot-file',
                   self.new_boot_file.name,
                   fake_requires_offloading,
                   fake_module_available,
                   '--log',
                   self.log.name]

        if uses_lightdm:
            command.append('--fake-lightdm')

        if valgrind:
            # Prepend the valgrind arguments
            command[:0] = valgrind
        elif gdb:
            command_ = copy.deepcopy(command)
            command_[:0] = gdb
            print("\n%s" % self.this_function_name)
            print(' '.join(command_))

        os.system(' '.join(command))

        if valgrind:
            self.valgrind_log = open(self.valgrind_log.name, 'r')
            errors_pt = re.compile('(.+) ERROR SUMMARY: (.+) errors from (.+) '
                       'contexts (suppressed: .+ from .+).*')
            for line in self.valgrind_log.readlines():
                errors = errors_pt.match(line)
                if errors:
                    if errors.group(2) != 0:
                        self.valgrind_log = open(self.valgrind_log.name, 'w')
                        self.valgrind_log.write(''.join(c, '\n'))
                        self.valgrind_log.close()
                        # Copy the logs
                        self.handle_logs(copy=True)
                        return False
            self.valgrind_log.close()
        return True

    def check_vars(self, *args, **kwargs):
        gpu_test = GpuTest(**kwargs)

        # Open the log for reading
        log = open(self.log.name, 'r')

        # Look for clues in the log
        for line in log.readlines():
            has_card = self.has_card_pt.match(line)
            is_driver_loaded = self.is_driver_loaded_pt.match(line)
            is_driver_unloaded = self.is_driver_unloaded_pt.match(line)
            is_driver_blacklisted = self.is_driver_blacklisted_pt.match(line)
            is_driver_enabled = self.is_driver_enabled_pt.match(line)
            is_egl_driver_enabled = self.is_egl_driver_enabled_pt.match(line)
            loaded_and_enabled = self.loaded_and_enabled_pt.match(line)

            matched_quirk = self.matched_quirk_pt.match(line)
            loaded_with_args = self.loaded_with_args_pt.match(line)

            single_card = self.single_card_pt.match(line)
            offloading = self.requires_offloading_pt.match(line)

            no_change_stop = self.no_change_stop_pt.match(line)
            has_changed = self.has_changed_pt.match(line)

            removed_xorg = self.removed_xorg_pt.match(line)
            regenerated_xorg = self.regenerated_xorg_pt.match(line)
            not_modified_xorg = self.not_modified_xorg_pt.match(line)
            selected_driver = self.selected_driver_pt.match(line)
            no_action = self.no_action_pt.match(line)
            has_skipped_hybrid = self.has_skipped_hybrid_pt.match(line)
            proprietary_installer = self.proprietary_installer_pt.match(line)
            has_added_gpu_from_file = self.has_added_gpu_from_file.match(line)
            copied_custom_xorg = self.copied_custom_xorg_pt.match(line)
            has_custom_xorg = self.has_custom_xorg_pt.match(line)

            # Detect the vendor
            if has_changed:
                gpu_test.has_changed = (has_changed.group(1).strip().lower() == 'yes')
            elif has_card:
                if has_card.group(1).strip().lower() == 'nvidia':
                    gpu_test.has_nvidia = (has_card.group(2).strip().lower() == 'yes')
                elif has_card.group(1).strip().lower() == 'intel':
                    gpu_test.has_intel = (has_card.group(2).strip().lower() == 'yes')
                elif has_card.group(1).strip().lower() == 'amd':
                    gpu_test.has_amd = (has_card.group(2).strip().lower() == 'yes')
            # Detect the kernel modules
            elif is_driver_loaded:
                if is_driver_loaded.group(1).strip().lower() == 'nouveau':
                    gpu_test.nouveau_loaded = (is_driver_loaded.group(2).strip().lower() == 'yes')
                elif is_driver_loaded.group(1).strip().lower() == 'nvidia':
                    gpu_test.nvidia_loaded = (is_driver_loaded.group(2).strip().lower() == 'yes')
                elif is_driver_loaded.group(1).strip().lower() == 'intel':
                    gpu_test.intel_loaded = (is_driver_loaded.group(2).strip().lower() == 'yes')
                elif is_driver_loaded.group(1).strip().lower() == 'radeon':
                    gpu_test.radeon_loaded = (is_driver_loaded.group(2).strip().lower() == 'yes')
                elif is_driver_loaded.group(1).strip().lower() == 'amdgpu':
                    gpu_test.amdgpu_loaded = (is_driver_loaded.group(2).strip().lower() == 'yes')
                elif is_driver_loaded.group(1).strip().lower() == 'fglrx':
                    gpu_test.fglrx_loaded = (is_driver_loaded.group(2).strip().lower() == 'yes')
            elif is_driver_unloaded:
                if is_driver_unloaded.group(1).strip().lower() == 'nouveau':
                    gpu_test.nouveau_unloaded = (is_driver_unloaded.group(2).strip().lower() == 'yes')
                elif is_driver_unloaded.group(1).strip().lower() == 'nvidia':
                    gpu_test.nvidia_unloaded = (is_driver_unloaded.group(2).strip().lower() == 'yes')
                elif is_driver_unloaded.group(1).strip().lower() == 'intel':
                    gpu_test.intel_unloaded = (is_driver_unloaded.group(2).strip().lower() == 'yes')
                elif is_driver_unloaded.group(1).strip().lower() == 'radeon':
                    gpu_test.radeon_unloaded = (is_driver_unloaded.group(2).strip().lower() == 'yes')
                elif is_driver_unloaded.group(1).strip().lower() == 'amdgpu':
                    gpu_test.amdgpu_unloaded = (is_driver_unloaded.group(2).strip().lower() == 'yes')
                elif is_driver_unloaded.group(1).strip().lower() == 'fglrx':
                    gpu_test.fglrx_unloaded = (is_driver_unloaded.group(2).strip().lower() == 'yes')
            # Detect the egl alternative
            elif is_egl_driver_enabled:
                if is_egl_driver_enabled.group(1).strip().lower() == 'nvidia':
                    gpu_test.nvidia_egl_enabled = (is_egl_driver_enabled.group(2).strip().lower() == 'yes')
                elif is_egl_driver_enabled.group(1).strip().lower() == 'mesa':
                    gpu_test.mesa_egl_enabled = (is_egl_driver_enabled.group(2).strip().lower() == 'yes')
                elif is_egl_driver_enabled.group(1).strip().lower() == 'prime':
                    gpu_test.prime_egl_enabled = (is_egl_driver_enabled.group(2).strip().lower() == 'yes')
            # Detect the gl alternative
            elif is_driver_enabled:
                if is_driver_enabled.group(1).strip().lower() == 'nvidia':
                    gpu_test.nvidia_enabled = (is_driver_enabled.group(2).strip().lower() == 'yes')
                elif is_driver_enabled.group(1).strip().lower() == 'fglrx':
                    gpu_test.fglrx_enabled = (is_driver_enabled.group(2).strip().lower() == 'yes')
                elif is_driver_enabled.group(1).strip().lower() == 'mesa':
                    gpu_test.mesa_enabled = (is_driver_enabled.group(2).strip().lower() == 'yes')
                elif is_driver_enabled.group(1).strip().lower() == 'prime':
                    gpu_test.prime_enabled = (is_driver_enabled.group(2).strip().lower() == 'yes')
                elif is_driver_enabled.group(1).strip().lower() == 'pxpress':
                    gpu_test.pxpress_enabled = (is_driver_enabled.group(2).strip().lower() == 'yes')
            elif is_driver_blacklisted:
                if is_driver_blacklisted.group(1).strip().lower() == 'nvidia':
                    gpu_test.nvidia_blacklisted = (is_driver_blacklisted.group(2).strip().lower() == 'yes')
                elif is_driver_blacklisted.group(1).strip().lower() == 'fglrx':
                    gpu_test.fglrx_blacklisted = (is_driver_blacklisted.group(2).strip().lower() == 'yes')
            elif single_card:
                gpu_test.has_single_card = True
            elif offloading:
                gpu_test.requires_offloading = (offloading.group(1).strip().lower() == 'yes')
            elif no_change_stop:
                #gpu_test.has_changed = False
                gpu_test.has_not_acted = True
            elif no_action:
                gpu_test.has_not_acted = True
            elif removed_xorg:
                gpu_test.has_removed_xorg = True
                # This is an action
                gpu_test.has_not_acted = False
            elif regenerated_xorg:
                gpu_test.has_regenerated_xorg = True
                # This is an action
                gpu_test.has_not_acted = False
            elif not_modified_xorg:
                gpu_test.has_removed_xorg = False
                gpu_test.has_regenerated_xorg = False
            elif selected_driver:
                gpu_test.has_selected_driver = True
                # This is an action
                gpu_test.has_not_acted = False
            elif has_skipped_hybrid:
                gpu_test.has_skipped_hybrid = True
                gpu_test.has_not_acted = True
            elif has_added_gpu_from_file:
                gpu_test.has_added_gpu_from_file = True
            elif loaded_and_enabled:
                gpu_test.has_selected_driver = False
            elif proprietary_installer:
                gpu_test.proprietary_installer = True
            elif matched_quirk:
                gpu_test.matched_quirk = True
            elif loaded_with_args:
                if (loaded_with_args.group(1) == 'bbswitch' and
                    loaded_with_args.group(2) != 'no'):
                    gpu_test.loaded_with_args = True
            elif copied_custom_xorg:
                gpu_test.copied_custom_xorg = True
            elif has_custom_xorg:
                if has_custom_xorg.group(1) == 'hybrid performance':
                    gpu_test.has_custom_xorg_hybrid_performance = True
                elif has_custom_xorg.group(1) == 'hybrid power saving':
                    gpu_test.has_custom_xorg_hybrid_power_saving = True
                elif has_custom_xorg.group(1) == 'non-hybrid':
                    gpu_test.has_custom_xorg_non_hybrid = True


        # Close the log
        log.close()

        # No driver selection and no changes to xorg.conf
        if (not gpu_test.has_selected_driver and
           (not gpu_test.has_removed_xorg and
            not gpu_test.has_regenerated_xorg)):
            gpu_test.has_not_acted = True

        # Copy the logs
        if tests_path:
            self.handle_logs(copy=True, delete=True)

        # Remove xorg.conf
        self.remove_xorg_conf()

        # Remove fake gpu detection file
        self.remove_gpu_detection_file()

        # Remove amd_pcsdb_file
        self.remove_amd_pcsdb_file()

        # Remove files for PRIME
        self.remove_prime_files()

        # Remove the valgrind log
        self.remove_valgrind_log()

        # Remove the modprobe.d path
        self.remove_modprobe_d_path()

        return gpu_test

    def _add_pci_ids(self, ids):
        if ids:
            self.fake_lspci = open(self.fake_lspci.name, 'w')
            for item in ids:
                self.fake_lspci.write(item)
            self.fake_lspci.close()

    def _add_pci_ids_from_last_boot(self, ids):
        if ids:
            self.last_boot_file = open(self.last_boot_file.name, 'w')
            for item in ids:
                self.last_boot_file.write(item)
            self.last_boot_file.close()

    def _get_cards_from_list(self, cards,
                             bump_boot_vga_device_id=False,
                             bump_discrete_device_id=False):
        cards_list = []
        it = 0
        boot_vga_device_id = 0x68d8
        discrete_device_id = 0x28e8
        for card in cards:
            card_line = '%04x:%04x;0000:%02d:%02d:0;%d\n' % (self.vendors.get(card),
                                           ((it == 0) and
                                            (bump_boot_vga_device_id and
                                             boot_vga_device_id + 1 or
                                             boot_vga_device_id) or
                                            (bump_discrete_device_id and
                                             discrete_device_id + 1 or
                                             discrete_device_id)),
                                           (it == 0) and 0 or it,
                                           (it == 0) and 1 or 0,
                                           (it == 0) and 1 or 0)
            cards_list.append(card_line)
            it += 1
        return cards_list

    def set_current_cards(self, cards,
                          bump_boot_vga_device_id=False,
                          bump_discrete_device_id=False):
        '''Set the current cards in the system

        cards is a list of cards such as ["intel", "nvidia"].
        The first cards on the list gets to be the boot_vga
        one.'''
        cards_list = self._get_cards_from_list(cards,
                                               bump_boot_vga_device_id,
                                               bump_discrete_device_id)
        self._add_pci_ids(cards_list)

    def set_cards_from_last_boot(self, cards):
        '''Set the cards in the system from last boot

        cards is a list of cards such as ["intel", "nvidia"].
        The first cards on the list gets to be the boot_vga
        one.'''
        cards_list = self._get_cards_from_list(cards)
        self._add_pci_ids_from_last_boot(cards_list)


    def add_kernel_modules(self, modules):
        if modules:
            self.fake_modules = open(self.fake_modules.name, 'w')
            for item in modules:
                line = '%s 1447330 3 - Live 0x0000000000000000\n' % item
                self.fake_modules.write(line)
            self.fake_modules.close()

    def request_prime_discrete_on(self, is_on=True):
        '''Request that discrete is switched on or off'''
        self.prime_settings = open(self.prime_settings.name, 'w')
        self.prime_settings.write(is_on and 'ON' or 'OFF')
        self.prime_settings.close()

    def set_prime_discrete_default_status_on(self, is_on=True):
        '''Sets the default status of the discrete card in bbswitch'''
        self.bbswitch_path = open(self.bbswitch_path.name, 'w')
        self.bbswitch_path.write('0000:01:00.0 %s\n' % (is_on and 'ON' or 'OFF'))
        self.bbswitch_path.close()

    def set_dmi_product_version(self, label):
        '''Set dmi product version'''
        self.dmi_product_version_path = open(self.dmi_product_version_path.name, 'w')
        self.dmi_product_version_path.write('%s\n' % label)
        self.dmi_product_version_path.close()

    def set_dmi_product_name(self, label):
        '''Set dmi product name'''
        self.dmi_product_name_path = open(self.dmi_product_name_path.name, 'w')
        self.dmi_product_name_path.write('%s\n' % label)
        self.dmi_product_name_path.close()

    def set_bbswitch_quirks(self):
        '''Set bbswitch quirks'''
        self.bbswitch_quirks_path = open(self.bbswitch_quirks_path.name, 'w')
        self.bbswitch_quirks_path.write('''
"ThinkPad T410" "skip_optimus_dsm=1"
"ThinkPad T410s" "skip_optimus_dsm=1"
        ''')
        self.bbswitch_quirks_path.close()

    def set_nvidia_version(self, nvidia_version):
        '''Set the nvidia kernel module version'''
        self.nvidia_driver_version_path = open(self.nvidia_driver_version_path.name, 'w')
        self.nvidia_driver_version_path.write('%s\n' % nvidia_version)
        self.nvidia_driver_version_path.close()

    def blacklist_module(self, module):
        '''Set the nvidia kernel module version'''
        self.modprobe_d_path = open(self.modprobe_d_path.name, 'a')
        self.modprobe_d_path.write('blacklist %s\n' % module)
        self.modprobe_d_path.close()

    def set_unloaded_module(self, module):
        if module:
            self.module_detection_file = "%s/u-d-c-%s-was-loaded" % (self.gpu_detection_path, module)
            module_file = open(self.module_detection_file, 'w')
            module_file.close()

            if module == 'nvidia':
                vendor = self.vendors["nvidia"]
            elif module == 'fglrx':
                vendor = self.vendors["amd"]
            else:
                vendor = 0x8086
            self.gpu_detection_file = "%s/u-d-c-gpu-0000:01:00.0-0x%04x-0x1140" % (self.gpu_detection_path, vendor)

            gpu_file = open(self.gpu_detection_file, 'w')
            gpu_file.close()


    def set_params(self, last_boot, current_boot,
                   loaded_modules, available_drivers,
                   enabled_driver,
                   enabled_egl_driver='',
                   unloaded_module='',
                   proprietary_installer=False,
                   matched_quirk=False,
                   loaded_with_quirk=False,
                   bump_boot_vga_device_id=False,
                   bump_discrete_device_id=False,
                   first_boot=False,
                   nvidia_version='',
                   core_alternatives=False,
                   egl_alternatives=False):

        # Last boot
        if first_boot:
            try:
                os.unlink(self.last_boot_file)
            except:
                pass
        else:
            self.set_cards_from_last_boot(last_boot)

        # Current boot
        self.set_current_cards(current_boot,
                          bump_boot_vga_device_id,
                          bump_discrete_device_id)

        # Kernel modules
        self.add_kernel_modules(loaded_modules)
        # Optional unloaded kernel module
        if unloaded_module:
            self.set_unloaded_module(unloaded_module)

        # Available alternatives
        self.fake_alternatives = open(self.fake_alternatives.name, 'w')

        if 'mesa' in available_drivers:
            self.fake_alternatives.write('/usr/lib/x86_64-linux-gnu/mesa/ld.so.conf\n')

        # Only one of these at a time
        if 'nvidia' in available_drivers:
            self.fake_alternatives.write('/usr/lib/nvidia-331-updates-prime/ld.so.conf\n')
            self.fake_alternatives.write('/usr/lib/nvidia-331-updates/ld.so.conf\n')
        elif 'fglrx' in available_drivers:
            self.fake_alternatives.write('/usr/lib/fglrx/ld.so.conf\n')
            self.fake_alternatives.write('/usr/lib/pxpress/ld.so.conf\n')
        else:
            for driver in available_drivers:
                self.fake_alternatives.write('/usr/lib/x86_64-linux-gnu/%s/ld.so.conf\n' % (driver))
        self.fake_alternatives.close()

        # The selected alternative
        if enabled_driver == 'mesa':
            self.fake_alternative = '/usr/lib/x86_64-linux-gnu/mesa/ld.so.conf'
        elif enabled_driver == 'nvidia':
            self.fake_alternative = '/usr/lib/nvidia-331-updates/ld.so.conf'
        elif enabled_driver == 'fglrx':
            self.fake_alternative = '/usr/lib/fglrx/ld.so.conf'
        elif enabled_driver == 'prime':
            self.fake_alternative = '/usr/lib/nvidia-331-updates-prime/ld.so.conf'
        elif enabled_driver == 'pxpress':
            self.fake_alternative = '/usr/lib/pxpress/ld.so.conf'
        else:
            self.fake_alternative = '/usr/lib/x86_64-linux-gnu/%s/ld.so.conf' % (enabled_driver)


        if egl_alternatives:
            self.fake_egl_alternatives = open(self.fake_egl_alternatives.name, 'w')

            if 'mesa' in available_drivers:
                self.fake_egl_alternatives.write('/usr/lib/x86_64-linux-gnu/mesa-egl/ld.so.conf\n')

            # Only one of these at a time
            if 'nvidia' in available_drivers:
                self.fake_egl_alternatives.write('/usr/lib/nvidia-331-updates-prime/ld.so.conf\n')
                self.fake_egl_alternatives.write('/usr/lib/nvidia-331-updates/ld.so.conf\n')
            elif 'fglrx' in available_drivers:
                self.fake_egl_alternatives.write('/usr/lib/pxpress/ld.so.conf\n')
            else:
                for driver in available_drivers:
                    self.fake_egl_alternatives.write('/usr/lib/x86_64-linux-gnu/%s/ld.so.conf\n' % (driver))
            self.fake_egl_alternatives.close()

            if enabled_egl_driver == 'mesa':
                self.fake_egl_alternative = '/usr/lib/x86_64-linux-gnu/mesa-egl/ld.so.conf'
            elif enabled_egl_driver == 'nvidia':
                self.fake_egl_alternative = '/usr/lib/nvidia-331-updates/ld.so.conf'
            elif enabled_egl_driver == 'fglrx':
                self.fake_egl_alternative = '/usr/lib/fglrx/ld.so.conf'
            elif enabled_egl_driver == 'prime':
                self.fake_egl_alternative = '/usr/lib/nvidia-331-updates-prime/ld.so.conf'
            elif enabled_egl_driver == 'pxpress':
                self.fake_egl_alternative = '/usr/lib/pxpress/ld.so.conf'
            else:
                self.fake_egl_alternative = '/usr/lib/x86_64-linux-gnu/%s/ld.so.conf' % (enabled_egl_driver)

        if nvidia_version:
            self.set_nvidia_version(nvidia_version)

        # Core alternatives
        if core_alternatives:
            self.fake_core_alternatives = open(self.fake_core_alternatives.name, 'w')
            if 'fglrx' in available_drivers:
                self.fake_core_alternatives.write('/usr/lib/fglrx-core/ld.so.conf\n')
                self.fake_core_alternatives.write('/usr/lib/fglrx-core/unblacklist_ld.so.conf\n')
                # Set the current alternative
                self.fake_core_alternative = '/usr/lib/fglrx-core/ld.so.conf'
            #else:
            #    for driver in available_drivers:
            #        self.fake_alternatives.write('/usr/lib/x86_64-linux-gnu/%s/ld.so.conf\n' % (driver))
            self.fake_core_alternatives.close()

    def run_manager_and_get_data(self, last_boot, current_boot,
                   loaded_modules, available_drivers,
                   enabled_driver,
                   enabled_egl_driver='',
                   unloaded_module='',
                   requires_offloading=False,
                   module_is_available=False,
                   proprietary_installer=False,
                   matched_quirk=False,
                   loaded_with_quirk=False,
                   bump_boot_vga_device_id=False,
                   bump_discrete_device_id=False,
                   first_boot=False,
                   nvidia_version='',
                   core_alternatives=False,
                   egl_alternatives=False):

        self.set_params(last_boot, current_boot,
                   loaded_modules, available_drivers,
                   enabled_driver,
                   enabled_egl_driver,
                   unloaded_module,
                   proprietary_installer,
                   matched_quirk,
                   loaded_with_quirk,
                   bump_boot_vga_device_id,
                   bump_discrete_device_id,
                   first_boot,
                   nvidia_version,
                   core_alternatives,
                   egl_alternatives)

        # Call the program
        self.exec_manager(requires_offloading=requires_offloading,
                          module_is_available=module_is_available)

        # Return data
        return self.check_vars()

    def test_one_intel_no_change(self):
        '''intel -> intel'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                      ['intel'],
                                      ['i915-brw'],
                                      ['mesa'],
                                      'mesa')


        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # No change
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_nvidia_binary_no_change(self):
        '''nvidia -> nvidia'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                      ['nvidia'],
                                      ['nvidia'],
                                      ['mesa', 'nvidia'],
                                      'nvidia',
                                      requires_offloading=True)

        # Check the variables
        self.assertTrue(gpu_test.has_single_card)

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # No open!
        self.assertFalse(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_nvidia_open_no_change(self):
        '''nvidia (nouveau) -> nvidia (nouveau)'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                      ['nvidia'],
                                      ['nouveau'],
                                      ['mesa'],
                                      'mesa')

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Open driver only!
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.mesa_enabled)
        # No change
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_amd_binary_no_change(self):
        '''fglrx -> fglrx'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                      ['amd'],
                                      ['fglrx'],
                                      ['mesa', 'fglrx'],
                                      'fglrx')

        # Check the variables
        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        # No radeon
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action
        self.assertTrue(gpu_test.has_not_acted)


        # What if the kernel module wasn't built
        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                      ['amd'],
                                      ['fake'],
                                      ['mesa', 'fglrx'],
                                      'fglrx')


        # Check the variables
        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        # No radeon
        self.assertFalse(gpu_test.radeon_loaded)
        # fglrx is not loaded
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
        # Select fallback and remove xorg.conf
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # Fallback action
        self.assertFalse(gpu_test.has_not_acted)


    def test_one_amd_binary_from_radeon(self):
        '''radeon -> fglrx'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Let's try to enable fglrx when fglrx is blacklisted
        self.blacklist_module('fglrx')

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                      ['amd'],
                                      ['fglrx', 'radeon'],
                                      ['mesa', 'fglrx'],
                                      'fglrx')

        # Check the variables
        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        # No radeon
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No action
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_amd_binary_from_radeon_lp1310489(self):
        '''radeon -> fglrx LP: #1310489'''
        self.this_function_name = sys._getframe().f_code.co_name

        # This simultates the test case where users install
        # fglrx and reboot. No changes should happen before
        # reboot.

        # Blacklist radeon
        self.blacklist_module('radeon')

        # The module is not loaded but it's available
        self.remove_xorg_conf()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                      ['amd'],
                                      ['radeon'],
                                      ['mesa', 'fglrx'],
                                      'fglrx',
                                      module_is_available=True)

        # Check the variables
        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        # No radeon
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action
        self.assertTrue(gpu_test.has_not_acted)


        # Let's do the same only with the added core alternatives
        # this time
        # Blacklist radeon
        self.blacklist_module('radeon')

        # The module is not loaded but it's available
        self.remove_xorg_conf()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                      ['amd'],
                                      ['radeon'],
                                      ['mesa', 'fglrx'],
                                      'fglrx',
                                      module_is_available=True,
                                      core_alternatives=True)

        # Check the variables
        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        # No radeon
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action
        self.assertTrue(gpu_test.has_not_acted)


        # Two AMD GPUs and the xorg.conf generated by
        # aticonfig
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "ServerLayout"
    Identifier     "aticonfig Layout"
    Screen      0  "aticonfig-Screen[0]-0" 0 0
    Screen         "aticonfig-Screen[1]-0" RightOf "aticonfig-Screen[0]-0"
EndSection

Section "Module"
EndSection

Section "Monitor"
    Identifier   "aticonfig-Monitor[0]-0"
    Option      "VendorName" "ATI Proprietary Driver"
    Option      "ModelName" "Generic Autodetecting Monitor"
    Option      "DPMS" "true"
EndSection

Section "Monitor"
    Identifier   "aticonfig-Monitor[1]-0"
    Option      "VendorName" "ATI Proprietary Driver"
    Option      "ModelName" "Generic Autodetecting Monitor"
    Option      "DPMS" "true"
EndSection

Section "Device"
    Identifier  "aticonfig-Device[0]-0"
    Driver      "fglrx"
    BusID       "PCI:1:0:0"
EndSection

Section "Device"
    Identifier  "aticonfig-Device[1]-0"
    Driver      "fglrx"
    BusID       "PCI:0:1:0"
EndSection

Section "Screen"
    Identifier "aticonfig-Screen[0]-0"
    Device     "aticonfig-Device[0]-0"
    Monitor    "aticonfig-Monitor[0]-0"
    DefaultDepth     24
    SubSection "Display"
        Viewport   0 0
        Depth     24
    EndSubSection
EndSection

Section "Screen"
    Identifier "aticonfig-Screen[1]-0"
    Device     "aticonfig-Device[1]-0"
    Monitor    "aticonfig-Monitor[1]-0"
    DefaultDepth     24
    SubSection "Display"
        Viewport   0 0
        Depth     24
    EndSubSection
EndSection

''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


    def test_one_amd_binary_from_radeon_lp1363675(self):
        '''false positives with blacklisted modules LP: #1363675'''
        self.this_function_name = sys._getframe().f_code.co_name

        # This simultates the test case where a driver whose
        # name is similar to the one of the binary driver is
        # blacklisted.

        # Blacklist nvidiafb
        self.blacklist_module('nvidiafb')

        # The module is not loaded but it's available
        self.remove_xorg_conf()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                      ['nvidia'],
                                      ['nvidia'],
                                      ['mesa', 'nvidia'],
                                      'nvidia',
                                      module_is_available=True)

        # Check the variables
        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertFalse(gpu_test.has_amd)
        # No radeon
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_blacklisted)
        self.assertFalse(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action
        self.assertTrue(gpu_test.has_not_acted)


        # Let's do the same only with the added core alternatives
        # this time
        # Blacklist fglrxsomething
        self.blacklist_module('fglrxsomething')

        # The module is not loaded but it's available
        self.remove_xorg_conf()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                      ['amd'],
                                      ['fglrx'],
                                      ['mesa', 'fglrx'],
                                      'fglrx',
                                      module_is_available=True,
                                      core_alternatives=True)

        # Check the variables
        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        # No radeon
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.fglrx_blacklisted)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action
        self.assertTrue(gpu_test.has_not_acted)


    def test_one_amd_open_no_change(self):
        '''radeon -> radeon'''
        self.this_function_name = sys._getframe().f_code.co_name
        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd'],
                                                 ['radeon'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables
        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        # No fglrx
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_intel_to_nvidia_binary(self):
        '''intel -> nvidia'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['nvidia'],
                                                 ['nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # We are going to enable nvidia
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # Action is required
        # We enable nvidia
        self.assertFalse(gpu_test.has_not_acted)


        # Let's try again, only this time it's all
        # already in place
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['nvidia'],
                                                 ['nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # We are going to enable nvidia
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # Action is required
        # We enable nvidia
        self.assertFalse(gpu_test.has_not_acted)


        # What if the driver is enabled but the kernel
        # module is not there?
        #
        # The binary driver is not there
        # whereas the open driver is blacklisted

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['nvidia'],
                                                 ['fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        #The open driver is blacklisted
        self.assertFalse(gpu_test.nouveau_loaded)
        # No kenrel module
        self.assertFalse(gpu_test.nvidia_loaded)
        # The driver is enabled
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_blacklisted)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # We should switch to mesa
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_intel_to_nvidia_open(self):
        '''intel -> nouveau'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['nvidia'],
                                                 ['nouveau'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_intel_to_amd_open(self):
        '''intel -> radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['amd'],
                                                 ['radeon'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_intel_to_amd_binary(self):
        '''intel -> fglrx'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['amd'],
                                                 ['fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # We are going to enable fglrx
        self.assertFalse(gpu_test.fglrx_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # Action is required
        # We enable fglrx
        self.assertFalse(gpu_test.has_not_acted)


        # Let's try again, only this time it's all
        # already in place

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['amd'],
                                                 ['fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # We don't need to enable fglrx again
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.fglrx_blacklisted)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # Action is not required
        self.assertFalse(gpu_test.has_not_acted)



        # What if the driver is enabled but the kernel
        # module is not there?
        #
        # The binary driver is not there
        # whereas the open driver is blacklisted

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['amd'],
                                                 ['fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        #The open driver is blacklisted
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No kernel module
        self.assertFalse(gpu_test.fglrx_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.fglrx_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # We should switch to mesa
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_amd_open_to_intel(self):
        '''radeon -> intel'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # No need to do anything else
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_amd_open_to_nvidia_open(self):
        '''radeon -> nouveau'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['nouveau'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # No need to do anything else
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


    def test_one_amd_open_to_nvidia_binary(self):
        '''radeon -> nouveau'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # Let's try again, only this time it's all
        # already in place

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # No need to do anything else
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # What if the driver is enabled but the kernel
        # module is not there?
        #
        # The binary driver is not there
        # whereas the open driver is blacklisted

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        #The open driver is blacklisted
        self.assertFalse(gpu_test.nouveau_loaded)
        # No kenrel module
        self.assertFalse(gpu_test.nvidia_loaded)
        # The driver is enabled
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # We should switch to mesa
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_amd_binary_to_intel(self):
        '''fglrx -> intel'''
        self.this_function_name = sys._getframe().f_code.co_name

        # User removed the discrete card without
        # uninstalling the binary driver and somehow
        # the kernel module is still loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['intel'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # The binary driver is loaded and enabled
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # User removed the discrete card without
        # uninstalling the binary driver
        # the kernel module is no longer loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # The kernel module of the binary driver
        # is not loaded
        self.assertFalse(gpu_test.fglrx_loaded)
        # The binary driver is still enabled
        self.assertTrue(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_amd_binary_to_nvidia_open(self):
        '''fglrx -> nouveau'''
        self.this_function_name = sys._getframe().f_code.co_name

        # User swapped the discrete card with
        # a discrete card from another vendor
        # without uninstalling the binary driver
        # the kernel module is still loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['nouveau', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # The binary driver is loaded and enabled
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # User swapped the discrete card with
        # a discrete card from another vendor
        # without uninstalling the binary driver
        # the kernel module is no longer loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # The kernel module of the binary driver
        # is not loaded
        self.assertFalse(gpu_test.fglrx_loaded)
        # The binary driver is still enabled
        self.assertTrue(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_amd_binary_to_nvidia_binary(self):
        '''fglrx -> nvidia'''
        self.this_function_name = sys._getframe().f_code.co_name

        # User swapped the discrete card with
        # a discrete card from another vendor
        # and installed the new binary driver
        # however the kernel module wasn't built

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['fake', 'fake_alt'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # User swapped the discrete card with
        # a discrete card from another vendor
        # and installed the new binary driver
        # correctly

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['fake', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # No need to select the driver
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_amd_open_to_amd_binary(self):
        '''radeon -> fglrx'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake_alt'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_not_acted)


        # Different card

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake_alt'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 bump_boot_vga_device_id=True)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        # We remove the xorg.conf
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # What if the module was not built?

        # Same card

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd'],
                                                 ['fake', 'fake_alt'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has not changed
        self.assertFalse(gpu_test.has_changed)
        # Move away xorg.conf if falling back
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver (fallback)
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # Different card

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd'],
                                                 ['fake', 'fake_alt'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 bump_boot_vga_device_id=True)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        # We remove the xorg.conf
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver (fallback)
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


    def test_one_amd_binary_to_amd_open(self):
        '''fglrx -> radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Same card

        # Case 1: fglrx is still installed and in use
        # the user switched to mesa without
        # uninstalling fglrx

        # The module was built

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake_alt'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        # We switch back to fglrx
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # Different card

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake_alt'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 bump_boot_vga_device_id=True)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        # We remove the xorg.conf
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2: fglrx was removed

        # Same card

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd'],
                                                 ['radeon', 'fake_alt'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has not changed
        self.assertFalse(gpu_test.has_changed)
        # Don't touch xorg.conf
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Nothing to select
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_not_acted)

        # Same card supported by amdgpu

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd'],
                                                 ['amdgpu', 'fake_alt'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has not changed
        self.assertFalse(gpu_test.has_changed)
        # Don't touch xorg.conf
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Nothing to select
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_not_acted)


        # Different card

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd'],
                                                 ['radeon', 'fake_alt'],
                                                 ['mesa'],
                                                 'mesa',
                                                 bump_boot_vga_device_id=True)
        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        # We remove the xorg.conf
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Nothing to select
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)

        # Different card supported by amdgpu

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd'],
                                                 ['amdgpu', 'fake_alt'],
                                                 ['mesa'],
                                                 'mesa',
                                                 bump_boot_vga_device_id=True)
        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        # We remove the xorg.conf
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Nothing to select
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


    def test_one_nvidia_open_to_intel(self):
        '''nouveau -> intel'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_nvidia_open_to_amd_open(self):
        '''nouveau -> radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)

        # No AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_nvidia_open_to_amd_binary(self):
        '''nouveau -> fglrx'''
        self.this_function_name = sys._getframe().f_code.co_name

        # No kernel module

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['fake'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # What if fglrx is enabled? (no kernel module)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the fallback
        self.assertTrue(gpu_test.has_selected_driver)
        # Action is required
        self.assertFalse(gpu_test.has_not_acted)


        # What if kernel module is available and mesa is enabled?

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        self.assertTrue(gpu_test.has_selected_driver)
        # Action is required
        self.assertFalse(gpu_test.has_not_acted)


        # What if kernel module is available and fglrx is enabled?
        # fglrx enabled

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertFalse(gpu_test.mesa_enabled)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_one_nvidia_binary_to_intel(self):
        '''nvidia -> intel'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1: nvidia loaded and enabled

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # nvidia is still enabled
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # Action is required
        # We enable mesa
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2: nvidia loaded and not enabled

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # nvidia is not enabled
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3: nvidia not loaded and enabled

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # nvidia is still enabled
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 4: nvidia not loaded and not enabled

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # nvidia is not enabled
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


    def test_one_nvidia_binary_to_amd_open(self):
        '''nvidia -> radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1: nvidia loaded and enabled

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # nvidia is still enabled
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # Action is required
        # We enable mesa
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2: nvidia loaded and not enabled

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # nvidia is not enabled
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3: nvidia not loaded and enabled

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # nvidia is still enabled
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 4: nvidia not loaded and not enabled

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        #No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # nvidia is not enabled
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


    def test_one_nvidia_binary_to_amd_binary(self):
        '''nvidia -> fglrx'''
        self.this_function_name = sys._getframe().f_code.co_name

        # User swapped the discrete card with
        # a discrete card from another vendor
        # and installed the new binary driver
        # however the kernel module wasn't built

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['fake', 'fake_alt'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # User swapped the discrete card with
        # a discrete card from another vendor
        # and installed the new binary driver
        # correctly

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['fake', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # No need to select the driver
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # User swapped the discrete card with
        # a discrete card from another vendor
        # but did not install the new binary driver
        # The kernel module is still loaded.

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver (fallback)
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)


        # User swapped the discrete card with
        # a discrete card from another vendor
        # but did not install the new binary driver
        # The kernel module is no longer loaded.

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon', 'fake_alt'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select the driver (fallback)
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.has_not_acted)

    def test_laptop_one_intel_one_amd_open(self):
        '''laptop: intel + radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1: the discrete card is now available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'radeon'],
                                                 ['mesa'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2: the discrete card was already available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'radeon'],
                                                 ['mesa'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has not changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action is required
        self.assertTrue(gpu_test.has_not_acted)


        # Case 3: the discrete card is no longer available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_desktop_one_intel_one_amd_open(self):
        '''desktop: intel + radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1: the discrete card is now available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'radeon'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2: the discrete card was already available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'radeon'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has not changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action is required
        self.assertTrue(gpu_test.has_not_acted)


        # Case 3: the discrete card is no longer available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


    def test_laptop_one_intel_one_amd_binary(self):
        '''laptop: intel + fglrx'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Let's create an amdpcsdb file where the discrete
        # GPU is enabled
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V4''')
        self.amd_pcsdb_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Let's create an amdpcsdb file where the discrete
        # GPU is enabled, only this time xorg.conf is wrong
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V4''')
        self.amd_pcsdb_file.close()

        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "ServerLayout"
    Identifier     "aticonfig Layout"
    Screen      0  "aticonfig-Screen[0]-0" 0 0
EndSection

Section "Module"
EndSection

Section "Monitor"
    Identifier   "aticonfig-Monitor[0]-0"
    Option      "VendorName" "ATI Proprietary Driver"
    Option      "ModelName" "Generic Autodetecting Monitor"
    Option      "DPMS" "true"
EndSection

Section "Device"
    Identifier  "aticonfig-Device[0]-0"
    Driver      "fglrx"
    BusID       "PCI:1:0:0"
EndSection

Section "Device"
    Identifier  "intel"
    Driver      "intel"
    Option      "AccelMethod" "uxa"
EndSection

Section "Screen"
    Identifier "aticonfig-Screen[0]-0"
    Device     "aticonfig-Device[0]-0"
    Monitor    "aticonfig-Monitor[0]-0"
    DefaultDepth     24
    SubSection "Display"
        Viewport   0 0
        Depth     24
    EndSubSection
EndSection
        ''')
        self.xorg_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Let's create an amdpcsdb file where the discrete
        # GPU is enabled, only this time xorg.conf is correct
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V4''')
        self.amd_pcsdb_file.close()

        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "ServerLayout"
    Identifier     "aticonfig Layout"
    Screen      0  "aticonfig-Screen[0]-0" 0 0
EndSection

Section "Module"
EndSection

Section "Monitor"
    Identifier   "aticonfig-Monitor[0]-0"
    Option      "VendorName" "ATI Proprietary Driver"
    Option      "ModelName" "Generic Autodetecting Monitor"
    Option      "DPMS" "true"
EndSection

Section "Device"
    Identifier  "aticonfig-Device[0]-0"
    Driver      "fglrx"
    BusID       "PCI:1:0:0"
EndSection

Section "Device"
    Identifier  "intel"
    Driver      "intel"
    Option      "AccelMethod" "uxa"
    BusID       "PCI:0@0:1:0"
EndSection

Section "Screen"
    Identifier "aticonfig-Screen[0]-0"
    Device     "aticonfig-Device[0]-0"
    Monitor    "aticonfig-Monitor[0]-0"
    DefaultDepth     24
    SubSection "Display"
        Viewport   0 0
        Depth     24
    EndSubSection
EndSection
        ''')
        self.xorg_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


        # Let's create an amdpcsdb file where the discrete
        # GPU is disabled, and xorg.conf is correct
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V0''')
        self.amd_pcsdb_file.close()

        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "ServerLayout"
    Identifier     "aticonfig Layout"
    Screen      0  "aticonfig-Screen[0]-0" 0 0
EndSection

Section "Module"
EndSection

Section "Monitor"
    Identifier   "aticonfig-Monitor[0]-0"
    Option      "VendorName" "ATI Proprietary Driver"
    Option      "ModelName" "Generic Autodetecting Monitor"
    Option      "DPMS" "true"
EndSection

Section "Device"
    Identifier  "aticonfig-Device[0]-0"
    Driver      "fglrx"
    BusID       "PCI:1:0:0"
EndSection

Section "Device"
    Identifier  "intel"
    Driver      "intel"
    Option      "AccelMethod" "sna"
    BusID       "PCI:0@0:1:0"
EndSection

Section "Screen"
    Identifier "aticonfig-Screen[0]-0"
    Device     "aticonfig-Device[0]-0"
    Monitor    "aticonfig-Monitor[0]-0"
    DefaultDepth     24
    SubSection "Display"
        Viewport   0 0
        Depth     24
    EndSubSection
EndSection
        ''')
        self.xorg_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # We should select pxpress here
        self.assertTrue(gpu_test.has_selected_driver)

        self.assertFalse(gpu_test.has_not_acted)


        # Let's create a case where the discrete
        # GPU is disabled, fglrx was unloaded, and xorg.conf
        # is correct
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V0''')
        self.amd_pcsdb_file.close()

        # Only intel should show up

        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "ServerLayout"
    Identifier     "aticonfig Layout"
    Screen      0  "aticonfig-Screen[0]-0" 0 0
EndSection

Section "Module"
EndSection

Section "Monitor"
    Identifier   "aticonfig-Monitor[0]-0"
    Option      "VendorName" "ATI Proprietary Driver"
    Option      "ModelName" "Generic Autodetecting Monitor"
    Option      "DPMS" "true"
EndSection

Section "Device"
    Identifier  "aticonfig-Device[0]-0"
    Driver      "fglrx"
    BusID       "PCI:1:0:0"
EndSection

Section "Device"
    Identifier  "intel"
    Driver      "intel"
    Option      "AccelMethod" "uxa"
    BusID       "PCI:0@0:1:0"
EndSection

Section "Screen"
    Identifier "aticonfig-Screen[0]-0"
    Device     "aticonfig-Device[0]-0"
    Monitor    "aticonfig-Monitor[0]-0"
    DefaultDepth     24
    SubSection "Display"
        Viewport   0 0
        Depth     24
    EndSubSection
EndSection
        ''')
        self.xorg_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 unloaded_module='fglrx',
                                                 requires_offloading=True)

        # Check that fglrx was unloaded
        self.assertTrue(gpu_test.fglrx_unloaded)

        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.intel_loaded)

        # Has changed
        self.assertFalse(gpu_test.has_changed)
        # Selecting a different alternative
        # triggers a xorg.conf rewrite
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        # We should select pxpress here
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Let's create a case where the discrete
        # GPU is disabled, fglrx was unloaded, and xorg.conf
        # is incorrect
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V0''')
        self.amd_pcsdb_file.close()

        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "ServerLayout"
    Identifier     "aticonfig Layout"
    Screen      0  "aticonfig-Screen[0]-0" 0 0
EndSection

Section "Module"
EndSection

Section "Monitor"
    Identifier   "aticonfig-Monitor[0]-0"
    Option      "VendorName" "ATI Proprietary Driver"
    Option      "ModelName" "Generic Autodetecting Monitor"
    Option      "DPMS" "true"
EndSection

Section "Device"
    Identifier  "intel"
    Driver      "intel"
    Option      "AccelMethod" "uxa"
    BusID       "PCI:0@0:1:0"
EndSection

Section "Screen"
    Identifier "aticonfig-Screen[0]-0"
    Device     "aticonfig-Device[0]-0"
    Monitor    "aticonfig-Monitor[0]-0"
    DefaultDepth     24
    SubSection "Display"
        Viewport   0 0
        Depth     24
    EndSubSection
EndSection
        ''')
        self.xorg_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 unloaded_module='fglrx',
                                                 requires_offloading=True)

        # Check that fglrx was unloaded
        self.assertTrue(gpu_test.fglrx_unloaded)

        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.intel_loaded)

        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)

        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1b: the discrete card is now available (BIOS)
        #          the driver is enabled but the module is not loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1c: the discrete card is now available (BIOS)
        #          the driver is not enabled but the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        # We should select the driver here
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1d: the discrete card is now available (BIOS)
        #          pxpress is enabled and the module is loaded
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V4''')
        self.amd_pcsdb_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        # Select fglrx, as the discrete GPU
        # is not disabled
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1e: the discrete card is now available (BIOS)
        #          pxpress is enabled but the module is not loaded
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V0''')
        self.amd_pcsdb_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1f: the discrete card is now available (BIOS)
        #          pxpress is not enabled but the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        # We should select the driver here
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2a: the discrete card was already available (BIOS)
        #          the driver is enabled and the module is loaded
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V4''')
        self.amd_pcsdb_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2b: the discrete card was already available (BIOS)
        #          the driver is enabled but the module is not loaded
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V4''')
        self.amd_pcsdb_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2c: the discrete card was already available (BIOS)
        #          the driver is not enabled but the module is loaded
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V4''')
        self.amd_pcsdb_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        # We should select the driver here
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2d: the discrete card was already available (BIOS)
        #          pxpress is enabled and the module is loaded
        self.amd_pcsdb_file = open(self.amd_pcsdb_file.name, 'w')
        self.amd_pcsdb_file.write('''
FAKESETTINGS=BLAH
FAKEGPUSETTINGS=BLAHBLAH
EnabledFlags=V4''')
        self.amd_pcsdb_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        # We should select the driver here
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2e: the discrete card was already available (BIOS)
        #          pxpress is enabled but the module is not loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2f: the discrete card was already available (BIOS)
        #          pxpress is not enabled but the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        # We should select the driver here
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3a: the discrete card is no longer available (BIOS)
        #          the driver is enabled and the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3b: the discrete card is no longer available (BIOS)
        #          the driver is enabled but the module is not loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3c: the discrete card is no longer available (BIOS)
        #          the driver is not enabled but the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # We should select the driver here
        # but we won't for now
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3d: the discrete card is no longer available (BIOS)
        #          pxpress is enabled and the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)


        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3e: the discrete card is no longer available (BIOS)
        #          pxpress is enabled but the module is not loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3f: the discrete card is no longer available (BIOS)
        #          pxpress is not enabled but the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_desktop_one_intel_one_amd_binary(self):
        '''desktop: intel + fglrx'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1b: the discrete card is now available (BIOS)
        #          the driver is enabled but the module is not loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1c: the discrete card is now available (BIOS)
        #          the driver is not enabled but the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1d: the discrete card is now available (BIOS)
        #          pxpress is enabled and the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        # Select fglrx, as the discrete GPU
        # is not disabled
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1e: the discrete card is now available (BIOS)
        #          pxpress is enabled but the module is not loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1f: the discrete card is now available (BIOS)
        #          pxpress is not enabled but the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2a: the discrete card was already available (BIOS)
        #          the driver is enabled and the module is loaded

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2b: the discrete card was already available (BIOS)
        #          the driver is enabled but the module is not loaded
        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2c: the discrete card was already available (BIOS)
        #          the driver is not enabled but the module is loaded

        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2d: the discrete card was already available (BIOS)
        #          pxpress is enabled and the module is loaded

        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2e: the discrete card was already available (BIOS)
        #          pxpress is enabled but the module is not loaded

        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2f: the discrete card was already available (BIOS)
        #          pxpress is not enabled but the module is loaded

        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3a: the discrete card is no longer available (BIOS)
        #          the driver is enabled and the module is loaded

        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3b: the discrete card is no longer available (BIOS)
        #          the driver is enabled but the module is not loaded

        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3c: the discrete card is no longer available (BIOS)
        #          the driver is not enabled but the module is loaded

        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3d: the discrete card is no longer available (BIOS)
        #          pxpress is enabled and the module is loaded

        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3e: the discrete card is no longer available (BIOS)
        #          pxpress is enabled but the module is not loaded

        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3f: the discrete card is no longer available (BIOS)
        #          pxpress is not enabled but the module is loaded

        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915', 'fglrx'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_laptop_one_intel_one_nvidia_open(self):
        '''laptop: intel + nouveau'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nouveau'],
                                                 ['mesa'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2: the discrete card was already available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nouveau'],
                                                 ['mesa'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has not changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action is required
        self.assertTrue(gpu_test.has_not_acted)


        # Case 3: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_desktop_one_intel_one_nvidia_open(self):
        '''laptop: intel + nouveau'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nouveau'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2: the discrete card was already available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nouveau'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has not changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No action is required
        self.assertTrue(gpu_test.has_not_acted)


        # Case 3: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is still enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_laptop_one_intel_one_nvidia_binary(self):
        '''laptop: intel + nvidia'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded

        # Set dmi product version
        self.set_dmi_product_version('ThinkPad T410s')

        # Set default quirks
        self.set_bbswitch_quirks()

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check quirks
        self.assertTrue(gpu_test.matched_quirk)
        self.assertTrue(gpu_test.loaded_with_args)

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # What if dmi product version is invalid?

        # Set dmi product version
        self.set_dmi_product_version(' ')

        # Set default quirks
        self.set_bbswitch_quirks()

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check quirks
        self.assertFalse(gpu_test.matched_quirk)
        self.assertTrue(gpu_test.loaded_with_args)


        # What if dmi product version is invalid but dmi product
        # name is not?

        # Set dmi product version
        self.set_dmi_product_version(' ')

        # Set dmi product name
        self.set_dmi_product_name('ThinkPad T410s')

        # Set default quirks
        self.set_bbswitch_quirks()

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check quirks
        self.assertTrue(gpu_test.matched_quirk)
        self.assertTrue(gpu_test.loaded_with_args)


        # Case 1b: the discrete card is now available (BIOS)
        #          the driver is enabled but the module is not loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True)
        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_unloaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1c: the discrete card is now available (BIOS)
        #          the driver is not enabled but the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1d: the discrete card is now available (BIOS)
        #          prime is enabled and the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1e: the discrete card is now available (BIOS)
        #          prime is enabled but the module is not loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Fall back to mesa
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1f: the discrete card is now available (BIOS)
        #          prime is not enabled but the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1g: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        #          the nvidia driver version is too old to support
        #          prime offloading, so we fall back to Mesa.
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True,
                                                 nvidia_version="304.123")

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.prime_enabled)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2a: the discrete card was already available (BIOS)
        #          the driver is enabled and the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed

        # Enable when we support hybrid laptops
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2b: the discrete card was already available (BIOS)
        #          the driver is enabled but the module is not loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2c: the discrete card was already available (BIOS)
        #          the driver is not enabled but the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2d: the discrete card was already available (BIOS)
        #          prime is enabled and the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2e: the discrete card was already available (BIOS)
        #          prime is enabled but the module is not loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Fallback
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2f: the discrete card was already available (BIOS)
        #          prime is not enabled but the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select PRIME
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3a: the discrete card is no longer available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3b: the discrete card is no longer available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True)
        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3c: the discrete card is no longer available (bbswitch)
        #          prime is enabled and the module is not loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(False)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 unloaded_module='nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3d: the discrete card is no longer available (bbswitch)
        #          prime is enabled and the module is not loaded and
        #          we need to select nvidia for better performance

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(False)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 unloaded_module='nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3e: the discrete card is no longer available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3f: the discrete card is no longer available (BIOS)
        #          prime is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3g: the discrete card is no longer available (BIOS)
        #          prime is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3h: the discrete card is no longer available (BIOS)
        #          prime is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


    def test_laptop_one_intel_one_nvidia_binary_egl(self):
        '''laptop: intel + nvidia - EGL'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded

        # Set dmi product version
        self.set_dmi_product_version('ThinkPad T410s')

        # Set default quirks
        self.set_bbswitch_quirks()

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='nvidia',
                                                 egl_alternatives=True)

        # Check the variables

        # Check quirks
        self.assertTrue(gpu_test.matched_quirk)
        self.assertTrue(gpu_test.loaded_with_args)

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1b: the discrete card is now available (BIOS)
        #          the driver is enabled but the module is not loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='nvidia',
                                                 egl_alternatives=True)
        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_unloaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1c: the discrete card is now available (BIOS)
        #          the driver is not enabled but the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='mesa',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        self.assertTrue(gpu_test.mesa_egl_enabled)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1d: the discrete card is now available (BIOS)
        #          prime is enabled and the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='prime',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        self.assertTrue(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1e: the discrete card is now available (BIOS)
        #          prime is enabled but the module is not loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='prime',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        self.assertTrue(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Fall back to mesa
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1f: the discrete card is now available (BIOS)
        #          prime is not enabled but the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='mesa',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        self.assertTrue(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1g: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        #          the nvidia driver version is too old to support
        #          prime offloading, so we fall back to Mesa.
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True,
                                                 nvidia_version="304.123",
                                                 enabled_egl_driver='nvidia',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2a: the discrete card was already available (BIOS)
        #          the driver is enabled and the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='nvidia',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed

        # Enable when we support hybrid laptops
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2b: the discrete card was already available (BIOS)
        #          the driver is enabled but the module is not loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='nvidia',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2c: the discrete card was already available (BIOS)
        #          the driver is not enabled but the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='mesa',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        self.assertTrue(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2d: the discrete card was already available (BIOS)
        #          prime is enabled and the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='prime',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        self.assertTrue(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2e: the discrete card was already available (BIOS)
        #          prime is enabled but the module is not loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='prime',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        self.assertTrue(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Fallback
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2f: the discrete card was already available (BIOS)
        #          prime is not enabled but the module is loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='mesa',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        self.assertTrue(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # Select PRIME
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3a: the discrete card is no longer available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='nvidia',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3b: the discrete card is no longer available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='nvidia',
                                                 egl_alternatives=True)
        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3c: the discrete card is no longer available (bbswitch)
        #          prime is enabled and the module is not loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(False)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 unloaded_module='nvidia',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='prime',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        self.assertTrue(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3d: the discrete card is no longer available (bbswitch)
        #          prime is enabled and the module is not loaded and
        #          we need to select nvidia for better performance

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(False)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 unloaded_module='nvidia',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='prime',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        self.assertTrue(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3e: the discrete card is no longer available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='mesa',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        self.assertTrue(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3f: the discrete card is no longer available (BIOS)
        #          prime is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='prime',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        self.assertTrue(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3g: the discrete card is no longer available (BIOS)
        #          prime is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='prime',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        self.assertTrue(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3h: the discrete card is no longer available (BIOS)
        #          prime is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='mesa',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        self.assertTrue(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        self.assertFalse(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_desktop_one_intel_one_nvidia_binary(self):
        '''desktop: intel + nvidia'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1b: the discrete card is now available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed

        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1c: the discrete card is now available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed

        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1d: the discrete card is now available (BIOS)
        #          prime is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1e: the discrete card is now available (BIOS)
        #          prime is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1f: the discrete card is now available (BIOS)
        #          prime is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2a: the discrete card was already available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # See if it still regenerates xorg.conf if the
        # file is in place and correct
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    Driver "nvidia"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


        # See if it still regenerates xorg.conf if the
        # file is in place and incorrect
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    Driver "fglrx"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2b: the discrete card was already available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2c: the discrete card was already available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2d: the discrete card was already available (BIOS)
        #          prime is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2e: the discrete card was already available (BIOS)
        #          prime is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2f: the discrete card was already available (BIOS)
        #          prime is not enabled but the module is loaded



        # Case 3a: the discrete card is no longer available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3b: the discrete card is no longer available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3c: the discrete card is no longer available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3d: the discrete card is no longer available (BIOS)
        #          prime is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3e: the discrete card is no longer available (BIOS)
        #          prime is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3f: the discrete card is no longer available (BIOS)
        #          prime is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_desktop_two_amd_binary(self):
        '''Multiple AMD GPUs fglrx'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1b: the discrete card is now available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['old_fake', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1c: the discrete card is now available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed

        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1d: the discrete card is now available (BIOS)
        #          pxpress is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1e: the discrete card is now available (BIOS)
        #          pxpress is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1f: the discrete card is now available (BIOS)
        #          pxpress is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2a: the discrete card was already available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # See if it still regenerates xorg.conf if the
        # file is in place and correct
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 0"
    Driver "fglrx"
    BusID "PCI:0@0:1:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


        # See if it still regenerates xorg.conf if the
        # file is in place and unsupported (multiple xscreens)
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    Driver "fglrx"
    BusID "PCI:1@0:0:0"
EndSection

Section "Device"
    Identifier "Default Card 1"
    Driver "fglrx"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


        # Case 2b: the discrete card was already available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2c: the discrete card was already available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2d: the discrete card was already available (BIOS)
        #          pxpress is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2e: the discrete card was already available (BIOS)
        #          pxpress is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2f: the discrete card was already available (BIOS)
        #          pxpress is not enabled but the module is loaded



        # Case 3a: the discrete card is no longer available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3b: the discrete card is no longer available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3c: the discrete card is no longer available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3d: the discrete card is no longer available (BIOS)
        #          pxpress is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3e: the discrete card is no longer available (BIOS)
        #          pxpress is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3f: the discrete card is no longer available (BIOS)
        #          pxpress is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


    def test_laptop_two_amd_binary(self):
        '''laptop Multiple AMD GPUs fglrx'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1b: the discrete card is now available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1c: the discrete card is now available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed

        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1d: the discrete card is now available (BIOS)
        #          pxpress is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1e: the discrete card is now available (BIOS)
        #          pxpress is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1f: the discrete card is now available (BIOS)
        #          pxpress is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2a: the discrete card was already available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # See if it still regenerates xorg.conf if the
        # file is in place and correct
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 0"
    Driver "fglrx"
    BusID "PCI:0@0:1:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


        # See if it still regenerates xorg.conf if the
        # file is in place and unsupported (multiple xscreens)
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    Driver "fglrx"
    BusID "PCI:1@0:0:0"
EndSection

Section "Device"
    Identifier "Default Card 1"
    Driver "fglrx"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


        # Case 2b: the discrete card was already available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2c: the discrete card was already available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2d: the discrete card was already available (BIOS)
        #          pxpress is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2e: the discrete card was already available (BIOS)
        #          pxpress is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2f: the discrete card was already available (BIOS)
        #          pxpress is not enabled but the module is loaded



        # Case 3a: the discrete card is no longer available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3b: the discrete card is no longer available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3c: the discrete card is no longer available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3d: the discrete card is no longer available (BIOS)
        #          pxpress is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3e: the discrete card is no longer available (BIOS)
        #          pxpress is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 3f: the discrete card is no longer available (BIOS)
        #          pxpress is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'amd'],
                                                 ['amd'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_desktop_two_amd_open(self):
        '''Multiple AMD GPUs radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['radeon', 'fake'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # What if radeon is blacklisted
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # We'll probably use vesa + llvmpipe
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Same tests, only with amdgpu

        # Case 2a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['amdgpu', 'fake'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # What if amdgpu is blacklisted
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        #self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # We'll probably use vesa + llvmpipe
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_laptop_two_amd_open(self):
        '''laptop Multiple AMD GPUs radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['radeon', 'fake'],
                                                 ['mesa'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # What if radeon is blacklisted
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # We'll probably use vesa + llvmpipe
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Now with amdgpu

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['amdgpu', 'fake'],
                                                 ['mesa'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # What if amdgpu is blacklisted
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa'],
                                                 'mesa',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        #self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        # We'll probably use vesa + llvmpipe
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_desktop_one_amd_open_one_nvidia_binary(self):
        self.this_function_name = sys._getframe().f_code.co_name
        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Let's try again with a good xorg.conf
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    Driver "nvidia"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Let's try again with a good xorg.conf
        # this time with the driver specified
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    Driver "nvidia"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Let's try again with an incorrect xorg.conf
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    BusID "PCI:1@0:0:0"
    Driver "fglrx"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Let's try again with an incorrect xorg.conf
        # Wrong BusID
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    BusID "PCI:0@0:1:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1b: the discrete card is now available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1c: the discrete card is now available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed

        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Let's try again with a good xorg.conf
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    Driver "nvidia"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Let's try again with a good xorg.conf
        # this time with the driver specified
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    Driver "nvidia"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Let's try again with an incorrect xorg.conf
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    BusID "PCI:1@0:0:0"
    Driver "fglrx"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Let's try again with an incorrect xorg.conf
        # Wrong BusID
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    BusID "PCI:0@0:1:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1d: the discrete card is now available (BIOS)
        #          prime is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Let's try again with a good xorg.conf
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    Driver "nvidia"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Let's try again with a good xorg.conf
        # this time with the driver specified
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    Driver "nvidia"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Let's try again with an incorrect xorg.conf
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    BusID "PCI:1@0:0:0"
    Driver "fglrx"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Let's try again with an incorrect xorg.conf
        # Wrong BusID
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    BusID "PCI:0@0:1:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1e: the discrete card is now available (BIOS)
        #          prime is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1f: the discrete card is now available (BIOS)
        #          prime is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2a: the discrete card was already available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2b: the discrete card was already available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2c: the discrete card was already available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2d: the discrete card was already available (BIOS)
        #          prime is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2e: the discrete card was already available (BIOS)
        #          prime is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['radeon', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

    def test_desktop_one_amd_binary_one_nvidia_open(self):
        '''Multiple AMD GPUs'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['fglrx', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1b: the discrete card is now available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['fake_old', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1c: the discrete card is now available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['fglrx', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # No AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed

        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1d: the discrete card is now available (BIOS)
        #          pxpress is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['fglrx', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1e: the discrete card is now available (BIOS)
        #          pxpress is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['fake_old', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 1f: the discrete card is now available (BIOS)
        #          pxpress is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'nvidia'],
                                                 ['fglrx', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2a: the discrete card was already available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['fglrx', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # See if it still regenerates xorg.conf if the
        # file is in place and correct
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 0"
    Driver "fglrx"
    BusID "PCI:0@0:1:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['fglrx', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


        # See if it still regenerates xorg.conf if the
        # file is in place and incorrect
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    Driver "fglrx"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['fglrx', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2b: the discrete card was already available (BIOS)
        #          the driver is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['fake_old', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'fglrx')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertTrue(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2c: the discrete card was already available (BIOS)
        #          the driver is not enabled but the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['fglrx', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'mesa')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2d: the discrete card was already available (BIOS)
        #          pxpress is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['fglrx', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertTrue(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertTrue(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2e: the discrete card was already available (BIOS)
        #          pxpress is enabled but the module is not loaded
        gpu_test = self.run_manager_and_get_data(['amd', 'nvidia'],
                                                 ['amd', 'nvidia'],
                                                 ['fake_old', 'nouveau'],
                                                 ['mesa', 'fglrx'],
                                                 'pxpress')

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertTrue(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.prime_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertTrue(gpu_test.has_selected_driver)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


        # Case 2f: the discrete card was already available (BIOS)
        #          pxpress is not enabled but the module is loaded

    def test_proprietary_installer(self):
        '''detect proprietary installer'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        gpu_test = self.run_manager_and_get_data(['amd',],
                                                 ['amd', 'nvidia'],
                                                 ['fglrx', 'fake'],
                                                 ['mesa'],
                                                 'mesa')

        self.assertTrue(gpu_test.proprietary_installer)

        # Let try with nvidia
        gpu_test = self.run_manager_and_get_data(['amd',],
                                                 ['amd', 'nvidia'],
                                                 ['nvidia', 'fake'],
                                                 ['mesa'],
                                                 'mesa')

        self.assertTrue(gpu_test.proprietary_installer)


    def test_valid_boot_files(self):
        self.this_function_name = sys._getframe().f_code.co_name

        # Invalid boot file
        self.last_boot_file = open(self.last_boot_file.name, 'w')

        it = 0
        while it < 16:
            item = 'a' * 200
            self.last_boot_file.write(item)
            it += 1

        self.last_boot_file.close()

        # No Kernel modules
        self.add_kernel_modules([])

        # No available alternatives
        self.fake_alternatives = open(self.fake_alternatives.name, 'w')

        self.fake_alternatives.write('')

        self.fake_alternatives.close()

        # no selected alternative
        self.fake_alternative = 'null'

        self.exec_manager(requires_offloading=False)

        # Return data
        gpu_test = self.check_vars()

        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)


        # What if there are no graphics cards in the system?
        self.fake_lspci = open(self.fake_lspci.name, 'w')
        it = 0
        while it < 16:
            item = 'a' * 200
            self.fake_lspci.write(item)
            it += 1
        self.fake_lspci.close()

        # Invalid boot file
        self.last_boot_file = open(self.last_boot_file.name, 'w')

        it = 0
        while it < 16:
            item = 'a' * 200
            self.last_boot_file.write(item)
            it += 1

        self.last_boot_file.close()

        # No Kernel modules
        self.add_kernel_modules([])

        # No available alternatives
        self.fake_alternatives = open(self.fake_alternatives.name, 'w')

        self.fake_alternatives.write('')

        self.fake_alternatives.close()

        # no selected alternative
        self.fake_alternative = ''

        self.exec_manager(requires_offloading=False)

        # Return data
        gpu_test = self.check_vars()

        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)


    def test_desktop_one_nvidia_binary_preserve_xorg_conf(self):
        self.this_function_name = sys._getframe().f_code.co_name

        # Make sure that xorg.conf is not removed on first boot
        # i.e. the first time (ever) gpu-manager runs
        self.xorg_file = open(self.xorg_file.name, 'w')
        self.xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    BusID "PCI:1@0:0:0"
EndSection
''');
        self.xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['nvidia'],
                                                 ['nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 first_boot=True)


        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_desktop_one_nvidia_binary_preserve_custom_xorg_conf(self):
        self.this_function_name = sys._getframe().f_code.co_name

        # Make sure the custom xorg.conf is not removed on first boot
        # i.e. the first time (ever) gpu-manager runs
        #
        # Note the system won't detect the non-hybrid xorg.conf in this case
        custom_xorg_file_path = os.path.join(self.custom_xorg_path, 'non-hybrid')
        custom_xorg_file = open(self.xorg_non_hybrid_file.name, 'w')
        custom_xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    BusID "PCI:1@0:0:0"
EndSection
''');
        custom_xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['nvidia'],
                                                 ['nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 first_boot=True)


        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_custom_xorg_hybrid_power_saving)
        self.assertFalse(gpu_test.has_custom_xorg_hybrid_performance)
        # The system won't check the xorg.conf
        #self.assertTrue(gpu_test.has_custom_xorg_non_hybrid)
        self.assertFalse(gpu_test.copied_custom_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


        # A configuration change is needed, as the system was using mesa
        # instead of nvidia.
        #
        # Check that the custom xorg.conf is actually copied.
        custom_xorg_file_path = os.path.join(self.custom_xorg_path, 'non-hybrid')
        custom_xorg_file = open(self.xorg_non_hybrid_file.name, 'w')
        custom_xorg_file.write('''
Section "Device"
    Identifier "Default Card 1"
    BusID "PCI:1@0:0:0"
    Option "ConstrainCursor" "off"
EndSection
''');
        custom_xorg_file.close()

        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['nvidia'],
                                                 ['nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'mesa',
                                                 first_boot=True)


        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # Mesa is enabled
        self.assertTrue(gpu_test.mesa_enabled)
        # AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_custom_xorg_hybrid_power_saving)
        self.assertFalse(gpu_test.has_custom_xorg_hybrid_performance)
        self.assertTrue(gpu_test.has_custom_xorg_non_hybrid)
        self.assertTrue(gpu_test.copied_custom_xorg)
        self.assertTrue(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


    def test_disabled_gpu_detection(self):
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 3c: the discrete card is no longer available (bbswitch)
        #          prime is enabled and the module is not loaded

        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(False)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 unloaded_module='nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Check that the GPU was added from the file
        self.assertTrue(gpu_test.has_added_gpu_from_file)


    def test_laptop_one_intel_one_nvidia_binary_custom_xorg_conf(self):
        '''laptop: intel + nvidia'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        #          the driver is enabled and the module is loaded
        #          HYBRID PERFORMANCE MODE

        # Set dmi product version
        self.set_dmi_product_version('ThinkPad T410s')

        # Set default quirks
        self.set_bbswitch_quirks()

        custom_xorg_file = open(self.xorg_hybrid_performance_file.name, 'w')

        custom_xorg_file.write('''
Section "ServerLayout"
    Identifier "layout"
    Screen 0 "nvidia"
    Inactive "intel"
EndSection

Section "Device"
    Identifier "intel"
    Driver "modesetting"
    BusID "PCI:0@0:2:0"
    Option "AccelMethod" "None"
EndSection

Section "Screen"
    Identifier "intel"
    Device "intel"
EndSection

Section "Device"
    Identifier "nvidia"
    Driver "nvidia"
    BusID "PCI:1@0:0:0"
    Option "ConstrainCursor" "off"
EndSection

Section "Screen"
    Identifier "nvidia"
    Device "nvidia"
    Option "AllowEmptyInitialConfiguration" "on"
    Option "IgnoreDisplayDevices" "CRT"
EndSection
        ''')
        custom_xorg_file.close()


        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check quirks
        self.assertTrue(gpu_test.matched_quirk)
        self.assertTrue(gpu_test.loaded_with_args)

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nvidia_enabled)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        self.assertFalse(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_custom_xorg_hybrid_power_saving)
        self.assertTrue(gpu_test.has_custom_xorg_hybrid_performance)
        self.assertFalse(gpu_test.has_custom_xorg_non_hybrid)
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


        # Case 1b: the discrete card was already available (BIOS)
        #          prime is enabled and the module is loaded
        #          HYBRID POWER SAVING MODE

        custom_xorg_file_path = os.path.join(self.custom_xorg_path, 'hybrid-power-saving')
        custom_xorg_file = open(self.xorg_hybrid_power_saving_file.name, 'w')

        custom_xorg_file.write('''
Section "Device"
    Identifier "intel"
    Driver "modesetting"
    BusID "PCI:0@0:2:0"
    Option "AccelMethod" "UXA"
EndSection
        ''')
        custom_xorg_file.close()


        # Set default bbswitch status
        self.set_prime_discrete_default_status_on(True)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=True,
                                                 enabled_egl_driver='prime',
                                                 egl_alternatives=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # Mesa is not enabled
        self.assertFalse(gpu_test.mesa_enabled)
        self.assertFalse(gpu_test.mesa_egl_enabled)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        self.assertFalse(gpu_test.fglrx_loaded)
        self.assertFalse(gpu_test.fglrx_enabled)
        self.assertFalse(gpu_test.pxpress_enabled)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_enabled)
        self.assertFalse(gpu_test.nvidia_egl_enabled)
        self.assertTrue(gpu_test.prime_enabled)
        self.assertTrue(gpu_test.prime_egl_enabled)
        # Has changed
        self.assertFalse(gpu_test.has_changed)
        self.assertTrue(gpu_test.has_removed_xorg)
        self.assertFalse(gpu_test.has_regenerated_xorg)
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_custom_xorg_hybrid_power_saving)
        self.assertFalse(gpu_test.has_custom_xorg_hybrid_performance)
        self.assertFalse(gpu_test.has_custom_xorg_non_hybrid)
        self.assertTrue(gpu_test.copied_custom_xorg)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)


if __name__ == '__main__':
    if not '86' in os.uname()[4]:
        exit(0)
    # unittest.main() does its own parsing, therefore we
    # do our own parsing, then we create a copy of sys.argv where
    # we remove our custom and unsupported arguments, so that
    # unittest doesn't complain
    parser = argparse.ArgumentParser()
    parser.add_argument('--save-logs-to', help='Path to save logs to')
    parser.add_argument('--with-valgrind', action="store_true", help='Run the app within valgrind')
    parser.add_argument('--with-gdb', action="store_true", help='Run the app within gdb')

    args = parser.parse_args()
    tests_path = args.save_logs_to
    with_valgrind = args.with_valgrind
    with_gdb = args.with_gdb

    new_argv = []
    for elem in sys.argv:
        if ((elem != '--save-logs-to' and elem != args.save_logs_to) and
            (elem != '--with-valgrind' and elem != args.with_valgrind) and
            (elem != '--with-gdb' and elem != args.with_gdb)):
            new_argv.append(elem)
    unittest.main(argv=new_argv)


