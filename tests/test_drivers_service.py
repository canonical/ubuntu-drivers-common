#!/usr/bin/python3

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import apt_pkg
import gi

from UbuntuDrivers.service import drivers_service

import testarchive

# must precede the gi.repository import, and so must come after every other
# import to keep them all at the top of the file
gi.require_version("UMockdev", "1.0")
from gi.repository import Gio, GLib, UMockdev  # noqa: E402

# Modalias of an NVIDIA card covered by the test nvidia-* packages.
# Same value as used in test_ubuntu_drivers.py.
_MODALIAS_NV = "pci:v000010DEd000010C3sv00003842sd00002670bc03sc03i00"
_MODALIAS_WHITE = "pci:v00001234d00sv00000001sd00bc00sc00i00"


class _AptChroot:
    """Minimal apt chroot backed by a testarchive.Archive.

    Replicates the parts of aptdaemon.test.Chroot that are needed here:
    a dpkg status file and a populated apt lists directory, with apt_pkg
    pointed at the chroot root via Dir=.  No aptdaemon dependency required.
    """

    def __init__(self):
        self.path = tempfile.mkdtemp(prefix="apt-chroot-")
        self._saved_dir = None
        self._saved_status = None

    def setup(self, archive):
        for subdir in [
            "var/lib/dpkg",
            "var/cache/apt/archives/partial",
            "var/lib/apt/lists/partial",
            "etc/apt/apt.conf.d",
            "etc/apt/preferences.d",
        ]:
            os.makedirs(os.path.join(self.path, subdir), exist_ok=True)
        open(os.path.join(self.path, "var/lib/dpkg/status"), "w").close()

        sources_list = os.path.join(self.path, "etc/apt/sources.list")
        with open(sources_list, "w") as f:
            f.write("deb [trusted=yes] file://%s devel main\n" % archive.path)

        subprocess.run(
            [
                "apt-get",
                "update",
                "-o",
                "Dir=%s" % self.path,
                "-o",
                "Dir::Etc::sourcelist=%s" % sources_list,
                "-o",
                "Dir::State::Lists=%s/var/lib/apt/lists" % self.path,
                "-o",
                "Dir::Cache=%s/var/cache/apt" % self.path,
            ],
            check=True,
            capture_output=True,
        )

        apt_pkg.init_config()
        self._saved_dir = apt_pkg.config.get("Dir", "/")
        self._saved_status = apt_pkg.config.get("Dir::State::status", "")
        apt_pkg.config["Dir"] = self.path
        apt_pkg.config["Dir::State::status"] = os.path.join(
            self.path, "var/lib/dpkg/status"
        )
        apt_pkg.init_system()

    def remove(self):
        apt_pkg.init_config()
        if self._saved_dir is not None:
            apt_pkg.config["Dir"] = self._saved_dir
        else:
            apt_pkg.config.clear("Dir")
        if self._saved_status is not None:
            apt_pkg.config["Dir::State::status"] = self._saved_status
        else:
            apt_pkg.config.clear("Dir::State::status")
        apt_pkg.init_system()
        shutil.rmtree(self.path, ignore_errors=True)


def gen_fakehw():
    """Return a UMockdev.Testbed with a representative set of fake devices.

    Mirrors the pattern used in test_ubuntu_drivers.gen_fakehw().
    """
    t = UMockdev.Testbed.new()
    # covered by vanilla.deb (main component, free)
    t.add_device("pci", "white", None, ["modalias", _MODALIAS_WHITE], [])
    # covered by nvidia-driver-* packages (non-free, recommended = highest version)
    t.add_device("pci", "graphics", None, ["modalias", _MODALIAS_NV], [])
    # not covered by any driver package
    t.add_device("pci", "grey", None, ["modalias", "pci:vDEADBEEFd00"], [])
    return t


def gen_fakearchive():
    """Return a testarchive.Archive with driver packages for the fake devices."""
    a = testarchive.Archive()
    a.create_deb(
        "vanilla",
        component="main",
        extra_tags={
            "Modaliases": (
                "vanilla(pci:v00001234d*sv*sd*bc*sc*i*,"
                " pci:v0000BEEFd*sv*sd*bc*sc*i*)"
            ),
        },
    )
    a.create_deb(
        "xserver-xorg-core",
        version="99:1",
        dependencies={"Provides": "xorg-video-abi-4"},
    )
    a.create_deb(
        "nvidia-driver-450",
        dependencies={"Depends": "xorg-video-abi-4"},
        extra_tags={
            "Modaliases": "nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)",
            "Support": "PB",
        },
    )
    a.create_deb(
        "nvidia-driver-390",
        dependencies={"Depends": "xorg-video-abi-4"},
        extra_tags={
            "Modaliases": "nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)",
        },
    )
    a.create_deb(
        "nvidia-driver-350",
        dependencies={"Depends": "xorg-video-abi-4"},
        extra_tags={
            "Modaliases": "nv(pci:v000010DEd000010C3sv*sd*bc03sc*i*)",
            "Prefer-Variant": "Open",
        },
    )
    return a


def _normalize_dbus_value(value):
    """Recursively unpack GLib.Variant values into plain Python types."""
    if isinstance(value, GLib.Variant):
        return _normalize_dbus_value(value.unpack())
    if isinstance(value, list):
        return [_normalize_dbus_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_dbus_value(item) for item in value)
    if isinstance(value, dict):
        return {
            str(k): _normalize_dbus_value(
                v.unpack() if isinstance(v, GLib.Variant) else v
            )
            for k, v in value.items()
        }
    return value


def _write_dbus_system_config(path: str, socket_path: str) -> str:
    """Write a minimal dbus-daemon system-bus config to `path`.

    The config allows any user to own any name and send any message, which
    is appropriate for an isolated test daemon. Returns `path`.
    """
    config = f"""<!DOCTYPE busconfig PUBLIC
 "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>system</type>
  <listen>unix:path={socket_path}</listen>
  <policy context="default">
    <allow user="*"/>
    <allow own="*"/>
    <allow send_destination="*"/>
    <allow receive_sender="*"/>
  </policy>
</busconfig>
"""
    with open(path, "w") as f:
        f.write(config)
    return path


class DriversServiceDbusTests(unittest.TestCase):
    """Integration tests for the D-Bus drivers service.

    A single D-Bus daemon and service instance are shared across all tests in
    this class. Fake hardware is provided via UMockdev and fake packages via a
    testarchive-backed apt chroot, mirroring the pattern used in DetectTest in
    test_ubuntu_drivers.py.
    """

    @classmethod
    def setUpClass(cls):
        if not shutil.which("dbus-daemon"):
            raise unittest.SkipTest("dbus-daemon is required for this test")

        cls._umockdev = gen_fakehw()
        cls._sys_dir = cls._umockdev.get_sys_dir()

        cls._archive = gen_fakearchive()
        cls._chroot = _AptChroot()
        cls._chroot.setup(cls._archive)

        cls._tmpdir = tempfile.mkdtemp(prefix="udc-dbus-test-")
        socket_path = os.path.join(cls._tmpdir, "bus.sock")
        config_path = os.path.join(cls._tmpdir, "test-system-bus.conf")
        _write_dbus_system_config(config_path, socket_path)

        output = subprocess.check_output(
            [
                "dbus-daemon",
                f"--config-file={config_path}",
                "--print-address=1",
                "--print-pid=1",
                "--fork",
                "--nopidfile",
            ]
        )
        lines = output.decode().strip().splitlines()
        if len(lines) < 2:
            raise RuntimeError("Failed to start dbus-daemon for tests")

        cls._dbus_address = lines[0].strip()
        cls._dbus_pid = int(lines[1].strip())

        # Point the GIO system-bus machinery at our private daemon.
        cls._old_system_bus_address = os.environ.get("DBUS_SYSTEM_BUS_ADDRESS")
        os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = cls._dbus_address

        cls._service_ready = threading.Event()
        cls._main_loop = None

        def _run_service() -> None:
            # Obtain a connection to the test daemon directly so we can export
            # our object before any client tries to call it.
            connection = Gio.DBusConnection.new_for_address_sync(
                cls._dbus_address,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None,
                None,
            )
            # Request the well-known bus name so clients can find the service.
            connection.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "RequestName",
                GLib.Variant("(su)", (drivers_service.DriversService.BUS_NAME, 0)),
                GLib.VariantType.new("(u)"),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )

            cls._loop = GLib.MainLoop()
            idle_mgr = drivers_service._IdleManager(cls._loop.quit, timeout_seconds=300)
            cls._service = drivers_service.DriversService(idle_mgr)
            cls._service.export(connection)
            cls._connection = connection
            cls._service_ready.set()
            cls._loop.run()

        cls._loop_thread = threading.Thread(target=_run_service, daemon=True)
        cls._loop_thread.start()
        if not cls._service_ready.wait(timeout=5):
            raise RuntimeError("D-Bus service thread failed to start")

        cls._drivers_proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.NONE,
            None,
            drivers_service.DriversService.BUS_NAME,
            drivers_service.DriversService.OBJ_PATH,
            drivers_service.DriversService.BUS_NAME,
            None,
        )
        cls._introspection_proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.NONE,
            None,
            drivers_service.DriversService.BUS_NAME,
            drivers_service.DriversService.OBJ_PATH,
            "org.freedesktop.DBus.Introspectable",
            None,
        )

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_loop"):
            GLib.idle_add(cls._loop.quit)
        if hasattr(cls, "_loop_thread"):
            cls._loop_thread.join(timeout=2)

        if hasattr(cls, "_dbus_pid"):
            try:
                os.kill(cls._dbus_pid, signal.SIGTERM)
            except OSError:
                pass

        if hasattr(cls, "_old_system_bus_address"):
            if cls._old_system_bus_address is None:
                os.environ.pop("DBUS_SYSTEM_BUS_ADDRESS", None)
            else:
                os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = cls._old_system_bus_address

        if hasattr(cls, "_chroot"):
            cls._chroot.remove()

        if hasattr(cls, "_tmpdir"):
            shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def setUp(self):
        self._service.invalidate_cache()

    def _call_drivers(self):
        result_variant = self._drivers_proxy.call_sync(
            "drivers",
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
        return _normalize_dbus_value(result_variant)[0]

    def test_dbus_drivers_device_fields(self):
        """drivers() returns complete device entries with correct field values."""
        with patch.object(drivers_service, "sys_path", self._sys_dir):
            result = self._call_drivers()

        by_device = {os.path.basename(e["sys_path"]): e for e in result}

        # "grey" has no matching package and must not appear
        self.assertNotIn("grey", by_device)

        # "white" is covered by vanilla; no vendor/model in PCI ID database
        white = by_device["white"]
        self.assertEqual(white["modalias"], _MODALIAS_WHITE)
        self.assertEqual(white["vendor"], "")
        self.assertEqual(white["model"], "")
        self.assertEqual(len(white["drivers"]), 1)
        self.assertEqual(white["drivers"][0]["name"], "vanilla")
        self.assertEqual(white["drivers"][0]["source"], "distro")
        self.assertTrue(white["drivers"][0]["free"])
        self.assertFalse(white["drivers"][0]["builtin"])
        self.assertFalse(white["drivers"][0]["recommended"])

        # "graphics" is the NVIDIA card; PCI IDs provide vendor/model
        graphics = by_device["graphics"]
        self.assertEqual(graphics["modalias"], _MODALIAS_NV)
        self.assertEqual(graphics["vendor"], "NVIDIA Corporation")
        self.assertIn("GeForce", graphics["model"])

    def test_dbus_drivers_signature(self):
        """The drivers method is advertised with the correct D-Bus signature."""
        xml_variant = self._introspection_proxy.call_sync(
            "Introspect",
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
        xml = _normalize_dbus_value(xml_variant)[0]
        root = ET.fromstring(xml)

        method = root.find(
            ".//interface[@name='com.ubuntu.Drivers']/method[@name='drivers']"
        )
        self.assertIsNotNone(method, "drivers method missing from introspection")
        out_args = method.findall("./arg[@direction='out']")
        self.assertEqual(len(out_args), 1)
        self.assertEqual(out_args[0].get("type"), "aa{sv}")

    @patch("UbuntuDrivers.service.drivers_service.apt_pkg.Cache")
    def test_dbus_drivers_cache_failure(self, mock_cache):
        """A D-Bus error with domain CacheFailure is returned when the apt cache fails."""
        mock_cache.side_effect = Exception("apt cache error")

        with self.assertRaises(GLib.Error) as ctx:
            self._drivers_proxy.call_sync(
                "drivers",
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            )

        self.assertIn("CacheFailure", ctx.exception.message)

    def test_dbus_drivers_no_covered_devices(self):
        """drivers() returns an empty list when no device has a matching package."""
        t = UMockdev.Testbed.new()
        t.add_device("pci", "grey", None, ["modalias", "pci:vDEADBEEFd00"], [])
        with patch.object(drivers_service, "sys_path", t.get_sys_dir()):
            result = self._call_drivers()
        del t
        self.assertEqual(result, [])

    def test_dbus_drivers_uncovered_device_excluded(self):
        """drivers() omits devices that have no matching packages."""
        with patch.object(drivers_service, "sys_path", self._sys_dir):
            result = self._call_drivers()

        device_names = {os.path.basename(e["sys_path"]) for e in result}
        self.assertIn("white", device_names)
        self.assertIn("graphics", device_names)
        self.assertNotIn("grey", device_names)

    def test_dbus_drivers_recommended_first(self):
        """The recommended driver is listed first; non-recommended follow."""
        with patch.object(drivers_service, "sys_path", self._sys_dir):
            result = self._call_drivers()

        graphics = next(
            e for e in result if os.path.basename(e["sys_path"]) == "graphics"
        )
        driver_names = [d["name"] for d in graphics["drivers"]]
        self.assertEqual(driver_names[0], "nvidia-driver-450")
        self.assertIn("nvidia-driver-390", driver_names[1:])
        self.assertIn("xserver-xorg-video-nouveau", driver_names[1:])

    def test_dbus_drivers_nvidia_attributes(self):
        """Non-free proprietary driver attributes are mapped correctly."""
        with patch.object(drivers_service, "sys_path", self._sys_dir):
            result = self._call_drivers()

        graphics = next(
            e for e in result if os.path.basename(e["sys_path"]) == "graphics"
        )
        by_name = {d["name"]: d for d in graphics["drivers"]}

        recommended = by_name["nvidia-driver-450"]
        self.assertTrue(recommended["recommended"])
        self.assertFalse(recommended["free"])
        self.assertFalse(recommended["builtin"])
        self.assertEqual(recommended["source"], "distro")
        self.assertEqual(recommended["support"], "PB")
        self.assertFalse(recommended["open_preferred"])

        non_recommended = by_name["nvidia-driver-390"]
        self.assertFalse(non_recommended["recommended"])
        self.assertFalse(non_recommended["free"])
        self.assertFalse(non_recommended["builtin"])
        self.assertEqual(non_recommended["source"], "distro")
        self.assertEqual(non_recommended["support"], "")
        self.assertFalse(non_recommended["open_preferred"])

        prefers_open = by_name["nvidia-driver-350"]
        self.assertFalse(prefers_open["recommended"])
        self.assertFalse(prefers_open["free"])
        self.assertFalse(prefers_open["builtin"])
        self.assertEqual(prefers_open["source"], "distro")
        self.assertEqual(prefers_open["support"], "")
        self.assertTrue(prefers_open["open_preferred"])

    def test_dbus_drivers_nouveau_attributes(self):
        """Built-in free driver (nouveau) attributes are mapped correctly."""
        with patch.object(drivers_service, "sys_path", self._sys_dir):
            result = self._call_drivers()

        graphics = next(
            e for e in result if os.path.basename(e["sys_path"]) == "graphics"
        )
        by_name = {d["name"]: d for d in graphics["drivers"]}

        nouveau = by_name["xserver-xorg-video-nouveau"]
        self.assertFalse(nouveau["recommended"])
        self.assertTrue(nouveau["free"])
        self.assertTrue(nouveau["builtin"])
        self.assertEqual(nouveau["source"], "distro")


def _call_build_drivers():
    """Call _build_drivers_variant() and unpack the result into a plain list."""
    variant = drivers_service._build_drivers_variant()
    return _normalize_dbus_value(variant)[0]


class BuildDriversPayloadTests(unittest.TestCase):
    """Unit tests for _build_drivers_variant().

    Each test gets its own UMockdev testbed so that the fake hardware can be
    tailored per scenario, mirroring DetectTest in test_ubuntu_drivers.py.
    The apt chroot is shared at class level since the package set is fixed.
    """

    @classmethod
    def setUpClass(cls):
        cls._archive = gen_fakearchive()
        cls._chroot = _AptChroot()
        cls._chroot.setup(cls._archive)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_chroot"):
            cls._chroot.remove()

    def setUp(self):
        self._umockdev = gen_fakehw()
        self._plugin_dir = tempfile.mkdtemp()
        self._old_detect_dir = os.environ.get("UBUNTU_DRIVERS_DETECT_DIR")
        os.environ["UBUNTU_DRIVERS_DETECT_DIR"] = self._plugin_dir

    def tearDown(self):
        shutil.rmtree(self._plugin_dir)
        if self._old_detect_dir is None:
            os.environ.pop("UBUNTU_DRIVERS_DETECT_DIR", None)
        else:
            os.environ["UBUNTU_DRIVERS_DETECT_DIR"] = self._old_detect_dir

    def test_build_drivers_payload_graphics_device(self):
        """_build_drivers_variant() returns correct fields for the NVIDIA device."""
        with patch.object(drivers_service, "sys_path", self._umockdev.get_sys_dir()):
            result = _call_build_drivers()

        by_device = {os.path.basename(e["sys_path"]): e for e in result}
        self.assertIn("graphics", by_device)

        entry = by_device["graphics"]
        self.assertEqual(entry["modalias"], _MODALIAS_NV)
        self.assertEqual(entry["vendor"], "NVIDIA Corporation")
        self.assertIn("GeForce", entry["model"])

        by_name = {d["name"]: d for d in entry["drivers"]}
        self.assertIn("nvidia-driver-450", by_name)
        self.assertIn("nvidia-driver-390", by_name)
        self.assertIn("xserver-xorg-video-nouveau", by_name)

    def test_build_drivers_payload_simple_device(self):
        """_build_drivers_variant() returns correct fields for a simple PCI device."""
        with patch.object(drivers_service, "sys_path", self._umockdev.get_sys_dir()):
            result = _call_build_drivers()

        by_device = {os.path.basename(e["sys_path"]): e for e in result}
        self.assertIn("white", by_device)

        entry = by_device["white"]
        self.assertEqual(entry["modalias"], _MODALIAS_WHITE)
        self.assertEqual(entry["vendor"], "")
        self.assertEqual(entry["model"], "")
        self.assertEqual(len(entry["drivers"]), 1)

        vanilla = entry["drivers"][0]
        self.assertEqual(vanilla["name"], "vanilla")
        self.assertTrue(vanilla["free"])
        self.assertFalse(vanilla["builtin"])
        self.assertFalse(vanilla["recommended"])
        self.assertEqual(vanilla["source"], "distro")
        self.assertEqual(vanilla["support"], "")

    def test_build_drivers_payload_uncovered_device_excluded(self):
        """_build_drivers_variant() omits devices with no matching packages."""
        with patch.object(drivers_service, "sys_path", self._umockdev.get_sys_dir()):
            result = _call_build_drivers()

        device_names = {os.path.basename(e["sys_path"]) for e in result}
        self.assertNotIn("grey", device_names)

    def test_build_drivers_payload_empty(self):
        """_build_drivers_variant() returns an empty list when no device has a matching package."""
        t = UMockdev.Testbed.new()
        t.add_device("pci", "grey", None, ["modalias", "pci:vDEADBEEFd00"], [])
        with patch.object(drivers_service, "sys_path", t.get_sys_dir()):
            result = _call_build_drivers()
        del t
        self.assertEqual(result, [])

    def test_build_drivers_payload_recommended_first(self):
        """_build_drivers_variant() places the recommended driver first."""
        t = UMockdev.Testbed.new()
        t.add_device("pci", "graphics", None, ["modalias", _MODALIAS_NV], [])
        with patch.object(drivers_service, "sys_path", t.get_sys_dir()):
            result = _call_build_drivers()
        del t

        self.assertEqual(len(result), 1)
        drivers = result[0]["drivers"]
        self.assertEqual(drivers[0]["name"], "nvidia-driver-450")
        self.assertTrue(drivers[0]["recommended"])
        non_recommended = [d["name"] for d in drivers[1:]]
        self.assertIn("nvidia-driver-390", non_recommended)
        self.assertIn("xserver-xorg-video-nouveau", non_recommended)

    def test_build_drivers_payload_support_field(self):
        """_build_drivers_variant() includes the Support apt field in each driver dict."""
        with patch.object(drivers_service, "sys_path", self._umockdev.get_sys_dir()):
            result = _call_build_drivers()

        by_device = {os.path.basename(e["sys_path"]): e for e in result}
        by_name = {d["name"]: d for d in by_device["graphics"]["drivers"]}

        self.assertEqual(by_name["nvidia-driver-450"]["support"], "PB")
        self.assertEqual(by_name["nvidia-driver-390"]["support"], "")
        self.assertEqual(by_name["xserver-xorg-video-nouveau"]["support"], "")
        self.assertEqual(by_device["white"]["drivers"][0]["support"], "")

    @patch("UbuntuDrivers.service.drivers_service.apt_pkg.Cache")
    def test_build_drivers_payload_cache_failure(self, mock_cache):
        """_build_drivers_variant() raises RuntimeError when the apt cache fails."""
        mock_cache.side_effect = Exception("apt cache error")

        with self.assertRaises(RuntimeError) as ctx:
            drivers_service._build_drivers_variant()

        self.assertIn("apt cache error", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
