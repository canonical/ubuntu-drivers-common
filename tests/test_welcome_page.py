#!/usr/bin/python3

# (C) 2026 Canonical Ltd.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import sys
import unittest

# Add parent directory to path to import the ubuntu-drivers script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import the functions from ubuntu-drivers script
# We need to compile and exec the script to access its functions
ubuntu_drivers_path = os.path.join(os.path.dirname(__file__), "..", "ubuntu-drivers")
with open(ubuntu_drivers_path, "r") as f:
    ubuntu_drivers_code = f.read()

# Create a namespace for the script
ubuntu_drivers_ns = {}
exec(compile(ubuntu_drivers_code, ubuntu_drivers_path, "exec"), ubuntu_drivers_ns)

# Extract the functions we want to test
format_welcome_page = ubuntu_drivers_ns["format_welcome_page"]


class TestWelcomePageFormatting(unittest.TestCase):
    """Test welcome page formatting function"""

    def test_format_welcome_page_no_drivers(self):
        """Test formatting with no drivers installed"""
        data = {
            "cache_error": None,
            "nvidia_drivers": [],
            "oem_packages": [],
            "nvidia_status": None,
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIn("Welcome to ubuntu-drivers", output)
        self.assertIn("No OEM or NVIDIA drivers are currently installed", output)
        self.assertIn("ubuntu-drivers --help", output)

    def test_format_welcome_page_with_cache_error(self):
        """Test formatting when cache cannot be loaded"""
        data = {
            "cache_error": "Could not open cache",
            "nvidia_drivers": [],
            "oem_packages": [],
            "nvidia_status": None,
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIn("Welcome to ubuntu-drivers", output)
        self.assertIn("Warning: Could not access package cache", output)
        self.assertIn("Could not open cache", output)

    def test_format_welcome_page_nvidia_only(self):
        """Test formatting with only NVIDIA drivers"""
        data = {
            "cache_error": None,
            "nvidia_drivers": ["nvidia-driver-535", "linux-modules-nvidia-535-generic"],
            "oem_packages": [],
            "nvidia_status": None,
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIn("NVIDIA Drivers:", output)
        self.assertIn("nvidia-driver-535", output)
        self.assertIn("linux-modules-nvidia-535-generic", output)
        self.assertNotIn("OEM Enablement Packages:", output)

    def test_format_welcome_page_oem_only(self):
        """Test formatting with only OEM packages"""
        data = {
            "cache_error": None,
            "nvidia_drivers": [],
            "oem_packages": ["oem-somerville-meta", "oem-stella-meta"],
            "nvidia_status": None,
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIn("OEM Enablement Packages:", output)
        self.assertIn("oem-somerville-meta", output)
        self.assertIn("oem-stella-meta", output)
        self.assertNotIn("NVIDIA Drivers:", output)

    def test_format_welcome_page_nvidia_and_oem(self):
        """Test formatting with both NVIDIA and OEM packages"""
        data = {
            "cache_error": None,
            "nvidia_drivers": ["nvidia-driver-535"],
            "oem_packages": ["oem-somerville-meta"],
            "nvidia_status": None,
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIn("NVIDIA Drivers:", output)
        self.assertIn("nvidia-driver-535", output)
        self.assertIn("OEM Enablement Packages:", output)
        self.assertIn("oem-somerville-meta", output)

    def test_format_welcome_page_nvidia_loaded(self):
        """Test formatting with NVIDIA module loaded"""
        data = {
            "cache_error": None,
            "nvidia_drivers": ["nvidia-driver-535"],
            "oem_packages": [],
            "nvidia_status": {
                "loaded": True,
                "current_module_path": "/lib/modules/5.15.0-97-generic/updates/dkms/nvidia.ko",
                "next_boot_kernel": "5.15.0-97-generic",
                "next_boot_module_path": "/lib/modules/5.15.0-97-generic/updates/dkms/nvidia.ko",
                "needs_reboot": False,
                "module_missing": False,
            },
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIn("NVIDIA Module Status", output)
        self.assertIn("✓ NVIDIA module is currently loaded", output)
        self.assertIn("Module path for current kernel:", output)
        self.assertIn("✓ Current and next boot kernel versions match", output)

    def test_format_welcome_page_nvidia_not_loaded(self):
        """Test formatting with NVIDIA module not loaded"""
        data = {
            "cache_error": None,
            "nvidia_drivers": ["nvidia-driver-535"],
            "oem_packages": [],
            "nvidia_status": {
                "loaded": False,
                "current_module_path": None,
                "next_boot_kernel": "5.15.0-97-generic",
                "next_boot_module_path": "/lib/modules/5.15.0-97-generic/updates/dkms/nvidia.ko",
                "needs_reboot": False,
                "module_missing": False,
            },
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIn("NVIDIA Module Status", output)
        self.assertIn("ℹ️  NVIDIA module is not currently loaded", output)
        self.assertIn("📍 The NVIDIA module should load on next boot", output)

    def test_format_welcome_page_module_missing(self):
        """Test formatting when NVIDIA module is missing for next boot"""
        data = {
            "cache_error": None,
            "nvidia_drivers": ["nvidia-driver-535"],
            "oem_packages": [],
            "nvidia_status": {
                "loaded": True,
                "current_module_path": "/lib/modules/5.15.0-91-generic/updates/dkms/nvidia.ko",
                "next_boot_kernel": "5.15.0-97-generic",
                "next_boot_module_path": None,
                "needs_reboot": True,
                "module_missing": True,
            },
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIn(
            "❌  ERROR: NVIDIA module is missing for the next boot kernel!", output
        )
        self.assertIn("Next boot kernel: 5.15.0-97-generic", output)
        self.assertIn("Please re-run ubuntu-drivers", output)
        # Should not show reboot instructions when module is missing
        self.assertNotIn("✓ Current and next boot kernel versions match", output)

    def test_format_welcome_page_needs_reboot(self):
        """Test formatting when reboot is needed"""
        data = {
            "cache_error": None,
            "nvidia_drivers": ["nvidia-driver-535"],
            "oem_packages": [],
            "nvidia_status": {
                "loaded": True,
                "current_module_path": "/lib/modules/5.15.0-91-generic/updates/dkms/nvidia.ko",
                "next_boot_kernel": "5.15.0-97-generic",
                "next_boot_module_path": "/lib/modules/5.15.0-97-generic/updates/dkms/nvidia.ko",
                "needs_reboot": True,
                "module_missing": False,
            },
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIn("⚠️  Kernel version difference detected", output)
        self.assertIn("reboot to use the latest kernel", output)
        self.assertIn("Next boot kernel: 5.15.0-97-generic", output)

    def test_format_welcome_page_module_paths_differ(self):
        """Test formatting when module paths differ"""
        data = {
            "cache_error": None,
            "nvidia_drivers": ["nvidia-driver-535"],
            "oem_packages": [],
            "nvidia_status": {
                "loaded": True,
                "current_module_path": "/lib/modules/5.15.0-91-generic/updates/dkms/nvidia.ko",
                "next_boot_kernel": "5.15.0-91-generic",
                "next_boot_module_path": "/lib/modules/5.15.0-91-generic/kernel/nvidia.ko",
                "needs_reboot": False,
                "module_missing": False,
            },
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIn("📍 Module paths differ", output)
        self.assertIn("you should reboot", output)
        self.assertIn("Current:", output)
        self.assertIn("Next boot:", output)

    def test_format_welcome_page_nvidia_status_error(self):
        """Test formatting when NVIDIA status check fails"""
        data = {
            "cache_error": None,
            "nvidia_drivers": ["nvidia-driver-535"],
            "oem_packages": [],
            "nvidia_status": None,
            "nvidia_status_error": "Permission denied",
        }

        output = format_welcome_page(data)

        self.assertIn("NVIDIA Module Status", output)
        self.assertIn("⚠️  Could not check NVIDIA module status", output)
        self.assertIn("Permission denied", output)

    def test_format_welcome_page_next_boot_kernel_unknown(self):
        """Test formatting when next boot kernel cannot be determined"""
        data = {
            "cache_error": None,
            "nvidia_drivers": ["nvidia-driver-535"],
            "oem_packages": [],
            "nvidia_status": {
                "loaded": True,
                "current_module_path": "/lib/modules/5.15.0-91-generic/updates/dkms/nvidia.ko",
                "next_boot_kernel": None,
                "next_boot_module_path": None,
                "needs_reboot": False,
                "module_missing": False,
            },
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIn("⚠️  Could not determine next boot kernel", output)
        self.assertIn("try again with `sudo ubuntu-drivers`", output)

    def test_format_welcome_page_output_is_string(self):
        """Test that formatting returns a string"""
        data = {
            "cache_error": None,
            "nvidia_drivers": [],
            "oem_packages": [],
            "nvidia_status": None,
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        self.assertIsInstance(output, str)

    def test_format_welcome_page_no_empty_lines_at_start(self):
        """Test that output doesn't start with multiple empty lines"""
        data = {
            "cache_error": None,
            "nvidia_drivers": [],
            "oem_packages": [],
            "nvidia_status": None,
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)

        # Should start with one newline, then content
        self.assertTrue(output.startswith("\n==="))

    def test_format_welcome_page_multiline_structure(self):
        """Test that output is properly structured with multiple lines"""
        data = {
            "cache_error": None,
            "nvidia_drivers": ["nvidia-driver-535"],
            "oem_packages": [],
            "nvidia_status": None,
            "nvidia_status_error": None,
        }

        output = format_welcome_page(data)
        lines = output.split("\n")

        # Should have multiple lines
        self.assertGreater(len(lines), 5)
        # Should contain section headers
        self.assertTrue(any("Welcome to ubuntu-drivers" in line for line in lines))
        self.assertTrue(any("Installed OEM / NVIDIA Drivers" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
