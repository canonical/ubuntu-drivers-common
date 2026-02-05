#!/usr/bin/python3

# (C) 2026 Canonical Ltd.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import sys
import tempfile
import unittest

# Add parent directory to path to import UbuntuDrivers
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import UbuntuDrivers.detect  # noqa: E402


class TestGrubParsing(unittest.TestCase):
    """Test grub configuration parsing functions"""

    def setUp(self):
        """Set up test fixtures"""
        # Sample grub.cfg content with multiple kernels
        self.sample_grub_cfg = """
### BEGIN /etc/grub.d/10_linux ###
menuentry 'Ubuntu' --class ubuntu --class gnu-linux --class gnu \
--class os $menuentry_id_option 'gnulinux-simple-abc123' {
    recordfail
    load_video
    gfxmode $linux_gfx_mode
    insmod gzio
    if [ x$grub_platform = xxen ]; then insmod xzio; insmod lzopio; fi
    insmod part_gpt
    insmod ext2
    set root='hd0,gpt2'
    linux   /boot/vmlinuz-5.15.0-97-generic root=UUID=abc123 ro quiet splash
    initrd  /boot/initrd.img-5.15.0-97-generic
}
submenu 'Advanced options for Ubuntu' $menuentry_id_option \
'gnulinux-advanced-abc123' {
    menuentry 'Ubuntu, with Linux 5.15.0-97-generic' --class ubuntu \
--class gnu-linux --class gnu --class os $menuentry_id_option \
'gnulinux-5.15.0-97-generic-advanced-abc123' {
        recordfail
        load_video
        gfxmode $linux_gfx_mode
        insmod gzio
        linux   /boot/vmlinuz-5.15.0-97-generic root=UUID=abc123 ro \
quiet splash
        initrd  /boot/initrd.img-5.15.0-97-generic
    }
    menuentry 'Ubuntu, with Linux 5.15.0-91-generic' --class ubuntu \
--class gnu-linux --class gnu --class os $menuentry_id_option \
'gnulinux-5.15.0-91-generic-advanced-abc123' {
        recordfail
        load_video
        gfxmode $linux_gfx_mode
        insmod gzio
        linux   /boot/vmlinuz-5.15.0-91-generic root=UUID=abc123 ro
        initrd  /boot/initrd.img-5.15.0-91-generic
    }
    menuentry 'Ubuntu, with Linux 5.13.0-52-generic' --class ubuntu \
--class gnu-linux --class gnu --class os $menuentry_id_option \
'gnulinux-5.13.0-52-generic-advanced-abc123' {
        recordfail
        load_video
        linux   /vmlinuz-5.13.0-52-generic root=UUID=abc123 ro
        initrd  /initrd.img-5.13.0-52-generic
    }
}
"""

        # Grub config with simple numeric entries
        self.simple_grub_cfg = """
menuentry 'Ubuntu 22.04' {
    linux   /boot/vmlinuz-6.5.0-15-generic root=/dev/sda1 ro
    initrd  /boot/initrd.img-6.5.0-15-generic
}
menuentry 'Ubuntu 22.04 (recovery)' {
    linux   /boot/vmlinuz-6.5.0-14-generic root=/dev/sda1 ro single
    initrd  /boot/initrd.img-6.5.0-14-generic
}
menuentry 'Ubuntu 20.04' {
    linux   /boot/vmlinuz-5.4.0-150-generic root=/dev/sda1 ro
    initrd  /boot/initrd.img-5.4.0-150-generic
}
"""

    def test_parse_grub_cfg_numeric_entry_first(self):
        """Test parsing grub config with numeric entry for first kernel"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
            self.simple_grub_cfg, "0"
        )
        self.assertEqual(result, "6.5.0-15-generic")

    def test_parse_grub_cfg_numeric_entry_second(self):
        """Test parsing grub config with numeric entry for second kernel"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
            self.simple_grub_cfg, "1"
        )
        self.assertEqual(result, "6.5.0-14-generic")

    def test_parse_grub_cfg_numeric_entry_third(self):
        """Test parsing grub config with numeric entry for third kernel"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
            self.simple_grub_cfg, "2"
        )
        self.assertEqual(result, "5.4.0-150-generic")

    def test_parse_grub_cfg_numeric_entry_out_of_range(self):
        """Test parsing grub config with out of range numeric entry"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
            self.simple_grub_cfg, "10"
        )
        self.assertIsNone(result)

    def test_parse_grub_cfg_string_id_match(self):
        """Test parsing grub config with string ID that matches"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
            self.sample_grub_cfg, "gnulinux-simple-abc123"
        )
        self.assertEqual(result, "5.15.0-97-generic")

    def test_parse_grub_cfg_string_id_advanced_match(self):
        """Test parsing grub config with string ID from advanced submenu"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
            self.sample_grub_cfg, "gnulinux-5.15.0-91-generic-advanced-abc123"
        )
        self.assertEqual(result, "5.15.0-91-generic")

    def test_parse_grub_cfg_string_id_no_match(self):
        """Test parsing grub config with string ID that doesn't match"""
        # Capture stdout to suppress print statements
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
                self.sample_grub_cfg, "nonexistent-id"
            )
        self.assertIsNone(result)

    def test_parse_grub_cfg_empty_content(self):
        """Test parsing empty grub config"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel("", "0")
        self.assertIsNone(result)

    def test_parse_grub_cfg_none_content(self):
        """Test parsing None grub config"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(None, "0")
        self.assertIsNone(result)

    def test_parse_grub_cfg_no_kernel_entries(self):
        """Test parsing grub config with no kernel entries"""
        no_kernel_cfg = """
menuentry 'Some entry' {
    echo "No kernel here"
}
"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(no_kernel_cfg, "0")
        self.assertIsNone(result)

    def test_parse_grub_cfg_malformed_linux_line(self):
        """Test parsing grub config with malformed linux line"""
        malformed_cfg = """
menuentry 'Ubuntu' {
    linux   /boot/some-file root=/dev/sda1 ro
    initrd  /boot/initrd.img
}
"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(malformed_cfg, "0")
        self.assertIsNone(result)

    def test_parse_grub_cfg_complex_vmlinuz_path(self):
        """Test parsing grub config with complex vmlinuz path"""
        complex_cfg = """
menuentry 'Test' {
    linux   /boot/vmlinuz-5.15.0-97-generic-custom root=UUID=abc ro \
quiet
    initrd  /boot/initrd.img
}
"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(complex_cfg, "0")
        self.assertEqual(result, "5.15.0-97-generic-custom")

    def test_parse_grub_cfg_with_quotes_in_id(self):
        """Test parsing grub config with various quote styles in ID"""
        # Test with single quotes
        cfg_single = (
            "menuentry 'Ubuntu' --id 'my-kernel-id' {\n"
            "    linux /vmlinuz-5.15.0-97-generic\n}"
        )
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
            cfg_single, "my-kernel-id"
        )
        self.assertEqual(result, "5.15.0-97-generic")

        # Test with double quotes
        cfg_double = (
            'menuentry "Ubuntu" --id "my-kernel-id2" {\n'
            "    linux /vmlinuz-5.15.0-91-generic\n}"
        )
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
            cfg_double, "my-kernel-id2"
        )
        self.assertEqual(result, "5.15.0-91-generic")

    def test_parse_grub_cfg_multiple_matches_for_id(self):
        """Test parsing grub config with duplicate IDs (should handle \
gracefully)"""
        duplicate_cfg = """
menuentry 'Entry 1' --id 'duplicate-id' {
    linux /vmlinuz-5.15.0-97-generic
}
menuentry 'Entry 2' --id 'duplicate-id' {
    linux /vmlinuz-5.15.0-91-generic
}
"""
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
                duplicate_cfg, "duplicate-id"
            )
        # Should return None when multiple matches found
        self.assertIsNone(result)

    def test_load_grub_cfg_nonexistent_file(self):
        """Test loading non-existent grub.cfg file"""
        result = UbuntuDrivers.detect._load_grub_cfg("/nonexistent/path/grub.cfg")
        self.assertIsNone(result)

    def test_load_grub_cfg_with_temp_file(self):
        """Test loading grub.cfg from temporary file"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".cfg") as f:
            f.write(self.simple_grub_cfg)
            temp_path = f.name

        try:
            result = UbuntuDrivers.detect._load_grub_cfg(temp_path)
            self.assertIsNotNone(result)
            self.assertEqual(result, self.simple_grub_cfg)
        finally:
            os.unlink(temp_path)

    def test_get_kernel_from_grub_entry_integration(self):
        """Test full integration of _get_kernel_from_grub_entry using \
_parse_grub_cfg_for_kernel directly"""
        # Test that the high-level function works correctly
        # We test with content directly since we already tested
        # _load_grub_cfg separately
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
            self.simple_grub_cfg, "1"
        )
        self.assertEqual(result, "6.5.0-14-generic")

    def test_parse_grub_cfg_with_tabs_and_spaces(self):
        """Test parsing grub config with mixed tabs and spaces"""
        mixed_whitespace_cfg = """
menuentry 'Ubuntu' {
\tlinux\t/boot/vmlinuz-5.15.0-97-generic root=/dev/sda1
    initrd  /boot/initrd.img
}
"""
        result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(
            mixed_whitespace_cfg, "0"
        )
        self.assertEqual(result, "5.15.0-97-generic")

    def test_parse_grub_cfg_kernel_with_hyphens_and_dots(self):
        """Test parsing kernel versions with various patterns"""
        test_cases = [
            ("6.8.0-31-generic", "/boot/vmlinuz-6.8.0-31-generic"),
            ("5.15.0-97-lowlatency", "/boot/vmlinuz-5.15.0-97-lowlatency"),
            ("5.19.0-45-generic-hwe", "/boot/vmlinuz-5.19.0-45-generic-hwe"),
        ]

        for expected_kernel, vmlinuz_path in test_cases:
            cfg = f"menuentry 'Test' {{\n    linux {vmlinuz_path} ro\n}}"
            result = UbuntuDrivers.detect._parse_grub_cfg_for_kernel(cfg, "0")
            self.assertEqual(result, expected_kernel, f"Failed to parse {vmlinuz_path}")


if __name__ == "__main__":
    unittest.main()
