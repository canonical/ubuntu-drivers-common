"""Tests for X.Org video ABI checks against the APT cache."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from UbuntuDrivers.detect import _check_video_abi_compat


class VideoAbiTest(unittest.TestCase):
    @patch("apt_pkg.DepCache")
    def test_driver_without_candidate(self, depcache):
        """A detection plugin may name a package that APT cannot install."""
        driver = SimpleNamespace(name="video-driver")
        get_candidate_ver = depcache.return_value.get_candidate_ver
        get_candidate_ver.return_value = None

        self.assertFalse(_check_video_abi_compat({driver.name: driver}, driver))

    @patch("apt_pkg.DepCache")
    def test_xorg_counterpart_without_candidate(self, depcache):
        """A name in the cache can exist without an installable version."""
        driver = SimpleNamespace(name="nvidia-driver-580")
        xorg_driver = SimpleNamespace(name="xserver-xorg-video-nvidia-580")
        cache = {xorg_driver.name: xorg_driver}
        candidates = {
            driver.name: SimpleNamespace(depends_list_str={}),
            xorg_driver.name: None,
        }
        depcache.return_value.get_candidate_ver.side_effect = (
            lambda package: candidates[package.name]
        )

        self.assertTrue(_check_video_abi_compat(cache, driver))

    @patch("apt_pkg.DepCache")
    def test_xorg_core_without_candidate(self, depcache):
        """An unavailable X.Org server leaves its ABI unknown."""
        driver = SimpleNamespace(name="video-driver")
        xorg_core = SimpleNamespace(name="xserver-xorg-core")
        cache = {xorg_core.name: xorg_core}
        driver_version = SimpleNamespace(
            depends_list_str={"Depends": [[("xorg-video-abi-25", "", "")]]}
        )
        candidates = {driver.name: driver_version, xorg_core.name: None}
        depcache.return_value.get_candidate_ver.side_effect = (
            lambda package: candidates[package.name]
        )

        self.assertTrue(_check_video_abi_compat(cache, driver))
