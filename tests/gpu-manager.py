# Author: Alberto Milone
#
# Copyright (C) 2014 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import unittest
import sys
import tempfile
import shutil
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
                 radeon_loaded=False,
                 radeon_unloaded=False,
                 amdgpu_loaded=False,
                 amdgpu_unloaded=False,
                 has_nvidia=False,
                 nouveau_loaded=False,
                 nouveau_unloaded=False,
                 nvidia_loaded=False,
                 nvidia_unloaded=False,
                 nvidia_blacklisted=False,
                 has_changed=False,
                 has_removed_xorg=False,
                 has_regenerated_xorg=False,
                 has_created_xorg_conf_d=False,
                 has_selected_driver=False,
                 has_not_acted=True,
                 has_skipped_hybrid=False,
                 has_added_gpu_from_file=False,
                 proprietary_installer=False,
                 matched_quirk=False,
                 loaded_with_args=False,
                 module_is_versioned=False,
                 amdgpu_pro_powersaving=False,
                 amdgpu_pro_performance=False,
                 amdgpu_pro_reset=False):
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
        self.has_nvidia = has_nvidia
        self.nouveau_loaded = nouveau_loaded
        self.nouveau_unloaded = nouveau_unloaded
        self.nvidia_loaded = nvidia_loaded
        self.nvidia_unloaded = nvidia_unloaded
        self.nvidia_blacklisted = nvidia_blacklisted
        self.has_changed = has_changed
        self.has_removed_xorg = has_removed_xorg
        self.has_regenerated_xorg = has_regenerated_xorg
        self.has_created_xorg_conf_d = has_created_xorg_conf_d
        self.has_selected_driver = has_selected_driver
        self.has_not_acted = has_not_acted
        self.has_skipped_hybrid = has_skipped_hybrid
        self.has_added_gpu_from_file = has_added_gpu_from_file
        self.proprietary_installer = proprietary_installer
        self.matched_quirk = matched_quirk
        self.loaded_with_args = loaded_with_args
        self.module_is_versioned = module_is_versioned
        self.amdgpu_pro_powersaving = amdgpu_pro_powersaving
        self.amdgpu_pro_performance = amdgpu_pro_performance
        self.amdgpu_pro_reset = amdgpu_pro_reset


class GpuManagerTest(unittest.TestCase):

    @classmethod
    def setUpClass(klass):
        klass.last_boot_file = tempfile.NamedTemporaryFile(
            mode='w', prefix='last_boot_file_', dir=tests_path, delete=False)
        klass.last_boot_file.close()
        klass.new_boot_file = tempfile.NamedTemporaryFile(
            mode='w', prefix='new_boot_file_', dir=tests_path, delete=False)
        klass.new_boot_file.close()

        klass.amdgpu_pro_px_file = tempfile.NamedTemporaryFile(
            mode='w', prefix='amdgpu_pro_px_file_', dir=tests_path, delete=False)

        klass.amd_pcsdb_file = tempfile.NamedTemporaryFile(
            mode='w', prefix='amd_pcsdb_file_', dir=tests_path, delete=False)
        klass.amd_pcsdb_file.close()
        klass.fake_lspci = tempfile.NamedTemporaryFile(
            mode='w', prefix='fake_lspci_', dir=tests_path, delete=False)
        klass.fake_lspci.close()
        klass.fake_modules = tempfile.NamedTemporaryFile(
            mode='w', prefix='fake_modules_', dir=tests_path, delete=False)
        klass.fake_modules.close()
        klass.gpu_detection_path = tests_path or "/tmp"
        klass.module_detection_file = tests_path or "/tmp"
        klass.gpu_detection_file = tests_path or "/tmp"
        klass.prime_settings = tempfile.NamedTemporaryFile(
            mode='w', prefix='prime_settings_', dir=tests_path, delete=False)
        klass.prime_settings.close()
        klass.dmi_product_version_path = tempfile.NamedTemporaryFile(
            mode='w', prefix='dmi_product_version_path_', dir=tests_path, delete=False)
        klass.dmi_product_version_path.close()
        klass.dmi_product_name_path = tempfile.NamedTemporaryFile(
            mode='w', prefix='dmi_product_name_path_', dir=tests_path, delete=False)
        klass.dmi_product_name_path.close()
        klass.nvidia_driver_version_path = tempfile.NamedTemporaryFile(
            mode='w', prefix='nvidia_driver_version_path_', dir=tests_path, delete=False)
        klass.nvidia_driver_version_path.close()
        klass.modprobe_d_path = tempfile.NamedTemporaryFile(
            mode='w', prefix='modprobe_d_path_', dir=tests_path, delete=False)
        klass.modprobe_d_path.close()

        klass.xorg_conf_d_path = tempfile.NamedTemporaryFile(
            mode='w', prefix='xorg_conf_d_path_', dir=tests_path, delete=False)
        klass.xorg_conf_d_path.close()

        klass.log = tempfile.NamedTemporaryFile(mode='w', prefix='log_', dir=tests_path, delete=False)
        klass.log.close()

        klass.valgrind_log = tempfile.NamedTemporaryFile(mode='w', prefix='valgrind_log_', dir=tests_path, delete=False)
        klass.valgrind_log.close()

        # Patterns
        klass.is_driver_loaded_pt = re.compile('Is (.+) loaded\? (.+)')
        klass.is_driver_unloaded_pt = re.compile('Was (.+) unloaded\? (.+)')
        klass.is_driver_blacklisted_pt = re.compile('Is (.+) blacklisted\? (.+)')
        klass.is_driver_versioned_pt = re.compile('Is (.+) versioned\? (.+)')
        klass.has_card_pt = re.compile('Has (.+)\? (.+)')
        klass.single_card_pt = re.compile('Single card detected.*')
        klass.requires_offloading_pt = re.compile('Does it require offloading\? (.+)')
        klass.no_change_stop_pt = re.compile('No change - nothing to do')
        klass.has_changed_pt = re.compile('Has the system changed\? (.+)')

        klass.selected_driver_pt = re.compile('Selecting (.+)')
        klass.removed_xorg_pt = re.compile('Removing xorg.conf. Path: .+')
        klass.regenerated_xorg_pt = re.compile('Regenerating xorg.conf. Path: .+')
        klass.not_modified_xorg_pt = re.compile('No need to modify xorg.conf. Path .+')
        klass.created_xorg_conf_d_pt = re.compile('Creating (.+)')
        klass.no_action_pt = re.compile('Nothing to do')
        klass.has_skipped_hybrid_pt = re.compile('Lightdm is not the default display manager. Nothing to do')
        klass.matched_quirk_pt = re.compile('Found matching quirk.*')
        klass.loaded_with_args_pt = re.compile('Loading (.+) with \"(.+)\" parameters.*')
        klass.has_added_gpu_from_file = re.compile('Adding GPU from file: (.+)')
        klass.amdgpu_pro_powersaving_pt = re.compile('Enabling power saving mode for amdgpu-pro.*')
        klass.amdgpu_pro_performance_pt = re.compile('Enabling performance mode for amdgpu-pro.*')
        klass.amdgpu_pro_reset_pt = re.compile('Resetting the script changes for amdgpu-pro.*')

        klass.vendors = {'amd': 0x1002, 'nvidia': 0x10de,
                         'intel': 0x8086, 'unknown': 0x1016}

    def setUp(self):
        self.remove_modprobe_d_path()
        self.remove_xorg_conf_d_path()

    def tearDown(self):
        print('%s over\n' % self.this_function_name)
        # Remove all the logs
        self.handle_logs(delete=True)

    def cp_to_target_dir(self, filename):
        try:
            shutil.copy(filename, self.target_dir)
        except:
            pass

    def remove_modprobe_d_path(self):
        try:
            os.unlink(self.modprobe_d_path)
        except:
            pass

    def remove_xorg_conf_d_path(self):
        try:
            os.unlink(self.xorg_conf_d_path)
        except:
            pass

    def remove_amd_pcsdb_file(self):
        try:
            os.unlink(self.amd_pcsdb_file.name)
        except:
            pass

    def remove_prime_files(self):
        for elem in (self.prime_settings,
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
                     self.module_detection_file,
                     self.gpu_detection_file,
                     self.prime_settings,
                     self.dmi_product_version_path,
                     self.dmi_product_name_path,
                     self.nvidia_driver_version_path,
                     self.modprobe_d_path,
                     self.log,
                     self.amdgpu_pro_px_file,
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

    def exec_manager(self, requires_offloading=False, module_is_available=False,
                     module_is_versioned=False):
        fake_requires_offloading = \
            requires_offloading and '--fake-requires-offloading' or '--fake-no-requires-offloading'
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
                   '--amdgpu-pro-px-file',
                   self.amdgpu_pro_px_file.name,
                   '--fake-modules-path',
                   self.fake_modules.name,
                   '--gpu-detection-path',
                   self.gpu_detection_path,
                   '--prime-settings',
                   self.prime_settings.name,
                   '--dmi-product-version-path',
                   self.dmi_product_version_path.name,
                   '--dmi-product-name-path',
                   self.dmi_product_name_path.name,
                   '--nvidia-driver-version-path',
                   self.nvidia_driver_version_path.name,
                   '--modprobe-d-path',
                   self.modprobe_d_path.name,
                   '--xorg-conf-d-path',
                   self.xorg_conf_d_path.name,
                   '--new-boot-file',
                   self.new_boot_file.name,
                   fake_requires_offloading,
                   fake_module_available,
                   '--log',
                   self.log.name]

        if module_is_versioned:
            command.append('--fake-module-is-versioned')

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
            is_driver_versioned = self.is_driver_versioned_pt.match(line)

            matched_quirk = self.matched_quirk_pt.match(line)
            loaded_with_args = self.loaded_with_args_pt.match(line)

            single_card = self.single_card_pt.match(line)
            offloading = self.requires_offloading_pt.match(line)

            no_change_stop = self.no_change_stop_pt.match(line)
            has_changed = self.has_changed_pt.match(line)

            removed_xorg = self.removed_xorg_pt.match(line)
            regenerated_xorg = self.regenerated_xorg_pt.match(line)
            created_xorg_conf_d = self.created_xorg_conf_d_pt.match(line)
            not_modified_xorg = self.not_modified_xorg_pt.match(line)
            selected_driver = self.selected_driver_pt.match(line)
            no_action = self.no_action_pt.match(line)
            has_skipped_hybrid = self.has_skipped_hybrid_pt.match(line)
            has_added_gpu_from_file = self.has_added_gpu_from_file.match(line)
            amdgpu_pro_powersaving = self.amdgpu_pro_powersaving_pt.match(line)
            amdgpu_pro_performance = self.amdgpu_pro_performance_pt.match(line)
            amdgpu_pro_reset = self.amdgpu_pro_reset_pt.match(line)

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
            elif is_driver_blacklisted:
                if is_driver_blacklisted.group(1).strip().lower() == 'nvidia':
                    gpu_test.nvidia_blacklisted = (is_driver_blacklisted.group(2).strip().lower() == 'yes')
            elif is_driver_versioned:
                if is_driver_versioned.group(1).strip().lower() == 'amdgpu':
                    # no driver other than amdgpu pro requires this
                    gpu_test.module_is_versioned = (is_driver_versioned.group(2).strip().lower() == 'yes')
            elif single_card:
                gpu_test.has_single_card = True
            elif offloading:
                gpu_test.requires_offloading = (offloading.group(1).strip().lower() == 'yes')
            elif no_change_stop:
                # gpu_test.has_changed = False
                gpu_test.has_not_acted = True
            elif no_action:
                gpu_test.has_not_acted = True
                # This is an action
                gpu_test.has_not_acted = False
            elif regenerated_xorg:
                gpu_test.has_regenerated_xorg = True
                # This is an action
                gpu_test.has_not_acted = False
            elif created_xorg_conf_d:
                gpu_test.has_created_xorg_conf_d = True
            elif selected_driver:
                gpu_test.has_selected_driver = True
                # This is an action
                gpu_test.has_not_acted = False
            elif has_skipped_hybrid:
                gpu_test.has_skipped_hybrid = True
                gpu_test.has_not_acted = True
            elif has_added_gpu_from_file:
                gpu_test.has_added_gpu_from_file = True
            elif matched_quirk:
                gpu_test.matched_quirk = True
            elif loaded_with_args:
                gpu_test.loaded_with_args = True
            elif amdgpu_pro_powersaving:
                gpu_test.amdgpu_pro_powersaving = True
                gpu_test.has_not_acted = False
            elif amdgpu_pro_performance:
                gpu_test.amdgpu_pro_performance = True
                gpu_test.has_not_acted = False
            elif amdgpu_pro_reset:
                gpu_test.amdgpu_pro_reset = True
                gpu_test.has_not_acted = False

        # Close the log
        log.close()

        # No driver selection and no changes to xorg.conf
        # We deliberately leave the amdgpu-pro settings
        # out of this for now.
        if (not gpu_test.has_selected_driver and not
            (gpu_test.amdgpu_pro_powersaving or
                amdgpu_pro_performance or amdgpu_pro_reset)):
            gpu_test.has_not_acted = True

        # Copy the logs
        if tests_path:
            self.handle_logs(copy=True, delete=True)

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
            card_line = '%04x:%04x;0000:%02d:%02d:0;%d\n' % (
                self.vendors.get(card),
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
        '''Request that discrete be switched on or off'''
        self.prime_settings = open(self.prime_settings.name, 'w')
        self.prime_settings.write(is_on and 'ON' or 'OFF')
        self.prime_settings.close()

    def request_prime_on_demand(self):
        '''Request on-demand mode'''
        self.prime_settings = open(self.prime_settings.name, 'w')
        self.prime_settings.write('on-demand')
        self.prime_settings.close()

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
            elif module == 'amdgpu' or module == 'radeon':
                vendor = self.vendors["amd"]
            else:
                vendor = 0x8086
            self.gpu_detection_file = "%s/u-d-c-gpu-0000:01:00.0-0x%04x-0x1140" % (self.gpu_detection_path, vendor)

            gpu_file = open(self.gpu_detection_file, 'w')
            gpu_file.close()

    def set_params(self, last_boot, current_boot,
                   loaded_modules, available_drivers,
                   unloaded_module='',
                   matched_quirk=False,
                   loaded_with_quirk=False,
                   bump_boot_vga_device_id=False,
                   bump_discrete_device_id=False,
                   first_boot=False,
                   nvidia_version=''):

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

        if nvidia_version:
            self.set_nvidia_version(nvidia_version)

    def run_manager_and_get_data(self,
                                 last_boot, current_boot,
                                 loaded_modules, available_drivers,
                                 unloaded_module='',
                                 requires_offloading=False,
                                 module_is_available=False,
                                 matched_quirk=False,
                                 loaded_with_quirk=False,
                                 bump_boot_vga_device_id=False,
                                 bump_discrete_device_id=False,
                                 first_boot=False,
                                 nvidia_version='',
                                 module_is_versioned=False):

        self.set_params(
            last_boot, current_boot,
            loaded_modules, available_drivers,
            unloaded_module,
            matched_quirk,
            loaded_with_quirk,
            bump_boot_vga_device_id,
            bump_discrete_device_id,
            first_boot,
            nvidia_version)

        # Call the program
        self.exec_manager(requires_offloading=requires_offloading,
                          module_is_available=module_is_available,
                          module_is_versioned=module_is_versioned)

        # Return data
        return self.check_vars()

    def test_one_intel_no_change(self):
        '''intel -> intel'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
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
                                                 requires_offloading=False)

        # Check the variables
        self.assertTrue(gpu_test.has_single_card)

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)

        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nvidia_loaded)
        # No open!
        self.assertFalse(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
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
                                                 ['mesa'])

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        # Open driver only!
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertTrue(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
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
                                                 ['mesa'])

        # Check the variables
        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nouveau_loaded)
        # No change
        self.assertFalse(gpu_test.has_changed)
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
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # We are going to enable nvidia
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_not_acted)

        # Let's try again, only this time it's all
        # already in place
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['nvidia'],
                                                 ['nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # We are going to enable nvidia
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_not_acted)

        # module is not there?
        #
        # The binary driver is not there
        # whereas the open driver is blacklisted

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['nvidia'],
                                                 ['fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        # The open driver is blacklisted
        self.assertFalse(gpu_test.nouveau_loaded)
        # No kenrel module
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_blacklisted)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        # We should switch to mesa
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_intel_to_nvidia_open(self):
        '''intel -> nouveau'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['nvidia'],
                                                 ['nouveau'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

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

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_amd_open_to_intel(self):
        '''radeon -> intel'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        # No need to do anything else
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_amd_open_to_nvidia_open(self):
        '''radeon -> nouveau'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['nouveau'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        # No need to do anything else
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_amd_open_to_nvidia_binary(self):
        '''radeon -> nouveau'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        # Select the driver
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_not_acted)

        # Let's try again, only this time it's all
        # already in place

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        # No need to do anything else
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_not_acted)

        # module is not there?
        #
        # The binary driver is not there
        # whereas the open driver is blacklisted

        # Collect data
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['nvidia'],
                                                 ['fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        # The open driver is blacklisted
        self.assertFalse(gpu_test.nouveau_loaded)
        # No kenrel module
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        # We should switch to mesa
        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_nvidia_open_to_intel(self):
        '''nouveau -> intel'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_nvidia_open_to_amd_open(self):
        '''nouveau -> radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # No AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_nvidia_binary_to_intel(self):
        '''nvidia -> intel'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # Action is required
        # We enable mesa
        self.assertTrue(gpu_test.has_not_acted)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_one_nvidia_binary_to_amd_open(self):
        '''nvidia -> radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # Action is required
        # We enable mesa
        self.assertTrue(gpu_test.has_not_acted)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon', 'fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['nvidia'],
                                                 ['amd'],
                                                 ['radeon', 'fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)
        # No Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_laptop_one_intel_one_amd_open(self):
        '''laptop: intel + radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1: the discrete card is now available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'radeon'],
                                                 ['mesa'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2: the discrete card was already available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'radeon'],
                                                 ['mesa'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has not changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3: the discrete card is no longer available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_desktop_one_intel_one_amd_open(self):
        '''desktop: intel + radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1: the discrete card is now available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'radeon'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2: the discrete card was already available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'radeon'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has not changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3: the discrete card is no longer available (BIOS)

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_laptop_one_intel_one_nvidia_open(self):
        '''laptop: intel + nouveau'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nouveau'],
                                                 ['mesa'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2: the discrete card was already available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nouveau'],
                                                 ['mesa'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has not changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_desktop_one_intel_one_nvidia_open(self):
        '''laptop: intel + nouveau'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nouveau'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2: the discrete card was already available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nouveau'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertTrue(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has not changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_laptop_one_intel_one_nvidia_binary(self):
        '''laptop: intel + nvidia'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)

        # Set dmi product version
        self.set_dmi_product_version('ThinkPad T410s')

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check quirks
        # self.assertTrue(gpu_test.matched_quirk)
        # self.assertTrue(gpu_test.loaded_with_args)

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertTrue(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # What if dmi product version is invalid?

        # Set dmi product version
        self.set_dmi_product_version(' ')

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check quirks
        self.assertFalse(gpu_test.matched_quirk)
        # self.assertTrue(gpu_test.loaded_with_args)

        # What if dmi product version is invalid but dmi product
        # name is not?

        # Set dmi product version
        self.set_dmi_product_version(' ')

        # Set dmi product name
        self.set_dmi_product_name('ThinkPad T410s')

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check quirks
        # self.assertTrue(gpu_test.matched_quirk)
        # self.assertTrue(gpu_test.loaded_with_args)

        # Case 1b: the discrete card is now available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)
        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_unloaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1c: the discrete card is now available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertTrue(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1d: the discrete card is now available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was not created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1e: the discrete card is now available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        # Fall back to mesa
        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1f: the discrete card is now available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertTrue(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1g: the discrete card is now available (BIOS)
        #          the nvidia driver version is too old to support
        #          prime offloading, so we fall back to Mesa.
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False,
                                                 nvidia_version="304.123")

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2a: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed

        # Enable when we support hybrid laptops
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # Check that the xorg.conf.d file was created
        self.assertTrue(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2b: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2c: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertTrue(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2d: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was not created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2e: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        # Fallback
        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was not created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2f: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        # Select PRIME
        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was not created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        # Case 3a: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3b: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=False)
        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3c: the discrete card is no longer available (bbswitch)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 unloaded_module='nvidia',
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was not created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3d: the discrete card is no longer available (bbswitch)
        #          we need to select nvidia for better performance

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 unloaded_module='nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertTrue(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3e: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3f: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 'prime',
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3g: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3h: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertFalse(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 4a: the discrete card is available and we want on-demand mode
        self.request_prime_on_demand()

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # Check that the xorg.conf.d file was created
        self.assertTrue(gpu_test.has_created_xorg_conf_d)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


    def test_laptop_one_intel_one_nvidia_binary_egl(self):
        '''laptop: intel + nvidia - EGL'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)

        # Set dmi product version
        self.set_dmi_product_version('ThinkPad T410s')

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check quirks
        # self.assertTrue(gpu_test.matched_quirk)
        # self.assertTrue(gpu_test.loaded_with_args)

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1b: the discrete card is now available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)
        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        self.assertFalse(gpu_test.nvidia_unloaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1c: the discrete card is now available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1d: the discrete card is now available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1e: the discrete card is now available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        # Fall back to mesa
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1f: the discrete card is now available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1g: the discrete card is now available (BIOS)
        #          the nvidia driver version is too old to support
        #          prime offloading, so we fall back to Mesa.
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False,
                                                 nvidia_version="304.123")

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2a: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed

        # Enable when we support hybrid laptops
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2b: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2c: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2d: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2e: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        # Fallback
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2f: the discrete card was already available (BIOS)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        # Select PRIME
        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3a: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3b: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 'nvidia',
                                                 requires_offloading=False)
        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3c: the discrete card is no longer available (bbswitch)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 unloaded_module='nvidia',
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3d: the discrete card is no longer available (bbswitch)
        #          we need to select nvidia for better performance

        # Request action from bbswitch
        self.request_prime_discrete_on(True)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 unloaded_module='nvidia',
                                                 requires_offloading=True)

        # Check the variables

        # Check if laptop
        self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3e: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3f: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3g: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3h: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'],
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_desktop_one_intel_one_nvidia_binary(self):
        '''desktop: intel + nvidia'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1b: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed

        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1c: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed

        # Enable when we support hybrid laptops
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1d: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1e: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 1f: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2a: the discrete card was already available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2b: the discrete card was already available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2c: the discrete card was already available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2d: the discrete card was already available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2e: the discrete card was already available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel', 'nvidia'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # NVIDIA
        self.assertTrue(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 2f: the discrete card was already available (BIOS)

        # Case 3a: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3b: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3c: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3d: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3e: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Case 3f: the discrete card is no longer available (BIOS)
        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'nvidia'],
                                                 ['mesa', 'nvidia'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertTrue(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

    def test_desktop_two_amd_open(self):
        '''Multiple AMD GPUs radeon'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['radeon', 'fake'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.radeon_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # What if radeon is blacklisted
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        # We'll probably use vesa + llvmpipe
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Same tests, only with amdgpu

        # Case 2a: the discrete card is now available (BIOS)
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['amdgpu', 'fake'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertTrue(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # What if amdgpu is blacklisted
        gpu_test = self.run_manager_and_get_data(['amd'],
                                                 ['amd', 'amd'],
                                                 ['fake_old', 'fake'],
                                                 ['mesa'])

        # Check the variables

        # Check if laptop
        self.assertFalse(gpu_test.requires_offloading)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # AMD
        self.assertTrue(gpu_test.has_amd)
        # self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        # We'll probably use vesa + llvmpipe
        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

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

        self.exec_manager(requires_offloading=False)

        # Return data
        gpu_test = self.check_vars()

        # Has changed
        self.assertFalse(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)

    def test_disabled_gpu_detection(self):
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 3c: the discrete card is no longer available (bbswitch)

        # Request action from bbswitch
        self.request_prime_discrete_on(False)

        gpu_test = self.run_manager_and_get_data(['intel', 'nvidia'],
                                                 ['intel'],
                                                 ['i915', 'fake'],
                                                 ['mesa', 'nvidia'],
                                                 unloaded_module='nvidia',
                                                 requires_offloading=False)

        # Check the variables

        # Check if laptop
        #self.assertTrue(gpu_test.requires_offloading)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # No AMD
        self.assertFalse(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertFalse(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)

        self.assertFalse(gpu_test.has_selected_driver)
        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)

        # Check that the GPU was added from the file
        #self.assertTrue(gpu_test.has_added_gpu_from_file)

    def test_laptop_one_intel_one_amd_amdgpu_pro(self):
        '''laptop: intel + amdgpu-pro'''
        self.this_function_name = sys._getframe().f_code.co_name

        # Case 1a: the discrete card is now available (BIOS)

        # Fake the hybrid script
        amdgpu_pro_px_file = open(self.amdgpu_pro_px_file.name, 'w')
        amdgpu_pro_px_file.write('testing')
        amdgpu_pro_px_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel'],
                                                 ['intel', 'amd'],
                                                 ['i915', 'amdgpu'],
                                                 ['mesa'],
                                                 module_is_available=True,
                                                 module_is_versioned=True)

        # Check the variables

        # Check if pro stack
        self.assertTrue(gpu_test.module_is_versioned)

        self.assertFalse(gpu_test.has_single_card)

        # Intel
        self.assertTrue(gpu_test.has_intel)
        self.assertTrue(gpu_test.intel_loaded)

        # The pro stack does its own thing with
        # the linker
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertTrue(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        # This is pretty irrelevant as they use
        # /etc/X11/xorg.conf.d

        self.assertFalse(gpu_test.has_selected_driver)
        self.assertTrue(gpu_test.amdgpu_pro_powersaving)
        self.assertFalse(gpu_test.amdgpu_pro_performance)
        self.assertFalse(gpu_test.amdgpu_pro_reset)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Case 2a: the integrated card is no longer available (BIOS)

        # Fake the hybrid script
        amdgpu_pro_px_file = open(self.amdgpu_pro_px_file.name, 'w')
        amdgpu_pro_px_file.write('testing')
        amdgpu_pro_px_file.close()

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['amd'],
                                                 ['amdgpu'],
                                                 ['mesa'],
                                                 module_is_available=True,
                                                 module_is_versioned=True)

        # Check the variables

        # Check if pro stack
        self.assertTrue(gpu_test.module_is_versioned)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # The pro stack does its own thing with
        # the linker
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertTrue(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        # This is pretty irrelevant as they use
        # /etc/X11/xorg.conf.d

        self.assertFalse(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.amdgpu_pro_powersaving)
        self.assertFalse(gpu_test.amdgpu_pro_performance)
        self.assertTrue(gpu_test.amdgpu_pro_reset)

        # No further action is required
        self.assertFalse(gpu_test.has_not_acted)

        # Case 2b: no hybrid script is available

        try:
            os.unlink(self.amdgpu_pro_px_file.name)
        except:
            pass

        # Collect data
        gpu_test = self.run_manager_and_get_data(['intel', 'amd'],
                                                 ['amd'],
                                                 ['amdgpu'],
                                                 ['mesa'],
                                                 module_is_available=True,
                                                 module_is_versioned=True)

        # Check the variables

        # Check if pro stack
        self.assertTrue(gpu_test.module_is_versioned)

        self.assertTrue(gpu_test.has_single_card)

        # Intel
        self.assertFalse(gpu_test.has_intel)
        self.assertFalse(gpu_test.intel_loaded)

        # The pro stack does its own thing with
        # the linker
        # AMD
        self.assertTrue(gpu_test.has_amd)
        self.assertFalse(gpu_test.radeon_loaded)
        self.assertTrue(gpu_test.amdgpu_loaded)
        # No NVIDIA
        self.assertFalse(gpu_test.has_nvidia)
        self.assertFalse(gpu_test.nouveau_loaded)
        self.assertFalse(gpu_test.nvidia_loaded)
        # Has changed
        self.assertTrue(gpu_test.has_changed)
        # This is pretty irrelevant as they use
        # /etc/X11/xorg.conf.d

        self.assertFalse(gpu_test.has_selected_driver)
        self.assertFalse(gpu_test.amdgpu_pro_powersaving)
        self.assertFalse(gpu_test.amdgpu_pro_performance)
        self.assertFalse(gpu_test.amdgpu_pro_reset)

        # No further action is required
        self.assertTrue(gpu_test.has_not_acted)


if __name__ == '__main__':
    if '86' not in os.uname()[4]:
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
        if (
                (elem != '--save-logs-to' and elem != args.save_logs_to) and
                (elem != '--with-valgrind' and elem != args.with_valgrind) and
                (elem != '--with-gdb' and elem != args.with_gdb)):
            new_argv.append(elem)
    unittest.main(argv=new_argv)
