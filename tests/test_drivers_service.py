#!/usr/bin/python3

import os
import shutil
import signal
import subprocess
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch, MagicMock

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

from UbuntuDrivers.service import drivers_service


def _normalize_dbus_value(value):
    if isinstance(value, dbus.Array):
        return [_normalize_dbus_value(item) for item in value]
    if isinstance(value, dbus.Dictionary):
        return {str(k): _normalize_dbus_value(v) for k, v in value.items()}
    if isinstance(value, (dbus.String, dbus.ObjectPath)):
        return str(value)
    if isinstance(value, dbus.Boolean):
        return bool(value)
    if isinstance(value, (dbus.Int32, dbus.Int64, dbus.UInt32, dbus.UInt64)):
        return int(value)
    return value


class DriversServiceDbusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("dbus-daemon"):
            raise unittest.SkipTest("dbus-daemon is required for this test")

        output = subprocess.check_output(
            [
                "dbus-daemon",
                "--session",
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
        cls._old_dbus_address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = cls._dbus_address

        cls._service_ready = threading.Event()

        def _run_service() -> None:
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            cls._bus = dbus.bus.BusConnection(cls._dbus_address)
            cls._loop = GLib.MainLoop()
            cls._bus_name = dbus.service.BusName(
                drivers_service.DriversService.BUS_NAME, cls._bus
            )
            cls._service = drivers_service.DriversService(
                cls._bus, mainloop=cls._loop, idle_timeout_seconds=300
            )
            cls._service_ready.set()
            cls._loop.run()

        cls._loop_thread = threading.Thread(target=_run_service, daemon=True)
        cls._loop_thread.start()
        if not cls._service_ready.wait(timeout=5):
            raise RuntimeError("D-Bus service thread failed to start")

        cls._client_bus = dbus.bus.BusConnection(cls._dbus_address)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_loop"):
            cls._loop.quit()
        if hasattr(cls, "_loop_thread"):
            cls._loop_thread.join(timeout=2)

        if hasattr(cls, "_bus"):
            try:
                cls._bus.release_name(drivers_service.DriversService.BUS_NAME)
            except dbus.DBusException:
                pass

        if hasattr(cls, "_bus_name"):
            del cls._bus_name

        if hasattr(cls, "_bus"):
            cls._bus.close()

        if hasattr(cls, "_client_bus"):
            cls._client_bus.close()

        if hasattr(cls, "_dbus_pid"):
            try:
                os.kill(cls._dbus_pid, signal.SIGTERM)
            except OSError:
                pass

        if hasattr(cls, "_old_dbus_address"):
            if cls._old_dbus_address is None:
                os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
            else:
                os.environ["DBUS_SESSION_BUS_ADDRESS"] = cls._old_dbus_address

    @patch(
        "UbuntuDrivers.service.drivers_service.UbuntuDrivers.detect.system_device_drivers"
    )
    def test_dbus_drivers_method(self, mock_detect):
        device_path = "/sys/devices/pci0000:00/0000:00:01.0/0000:01:00.0"
        mock_detect.return_value = {
            device_path: {
                "modalias": "pci:v000010DEd00001C8Dsv00001558sd0000852Bbc03sc00i00",
                "vendor": "NVIDIA Corporation",
                "model": "GP107M [GeForce GTX 1050 Mobile]",
                "drivers": {
                    "xserver-xorg-video-nouveau": {
                        "free": True,
                        "from_distro": True,
                        "builtin": True,
                        "recommended": False,
                    },
                    "nvidia-driver-570": {
                        "free": False,
                        "from_distro": False,
                        "builtin": False,
                        "recommended": True,
                    },
                },
            }
        }

        proxy = self._client_bus.get_object(
            drivers_service.DriversService.BUS_NAME,
            drivers_service.DriversService.OBJ_PATH,
        )
        iface = dbus.Interface(proxy, drivers_service.DriversService.BUS_NAME)

        # Call the dbus method
        result = iface.drivers(timeout=5)

        result = _normalize_dbus_value(result)

        self.assertEqual(result[0]["sys_path"], device_path)
        self.assertEqual(
            [driver["name"] for driver in result[0]["drivers"]],
            ["nvidia-driver-570", "xserver-xorg-video-nouveau"],
        )
        self.assertEqual(result[0]["drivers"][0]["source"], "third-party")
        self.assertEqual(result[0]["drivers"][1]["source"], "distro")
        self.assertTrue(result[0]["drivers"][1]["builtin"])

    def test_dbus_drivers_signature(self):
        proxy = self._client_bus.get_object(
            drivers_service.DriversService.BUS_NAME,
            drivers_service.DriversService.OBJ_PATH,
        )
        introspect_iface = dbus.Interface(proxy, "org.freedesktop.DBus.Introspectable")
        xml = introspect_iface.Introspect()
        root = ET.fromstring(xml)

        method = root.find(
            ".//interface[@name='org.ubuntu.Drivers']/method[@name='drivers']"
        )
        self.assertIsNotNone(method, "drivers method missing from introspection")
        out_args = method.findall("./arg[@direction='out']")
        self.assertTrue(out_args, "drivers method has no out args")
        # D-Bus introspection uses "type" for argument signature.
        self.assertEqual(out_args[0].get("type"), "aa{sv}")

    @patch(
        "UbuntuDrivers.service.drivers_service.UbuntuDrivers.detect.system_device_drivers"
    )
    def test_dbus_drivers_empty_devices(self, mock_detect):
        """Test drivers method with no devices."""
        mock_detect.return_value = {}

        proxy = self._client_bus.get_object(
            drivers_service.DriversService.BUS_NAME,
            drivers_service.DriversService.OBJ_PATH,
        )
        iface = dbus.Interface(proxy, drivers_service.DriversService.BUS_NAME)

        result = iface.drivers(timeout=5)
        result = _normalize_dbus_value(result)

        self.assertEqual(result, [])

    @patch(
        "UbuntuDrivers.service.drivers_service.UbuntuDrivers.detect.system_device_drivers"
    )
    def test_dbus_drivers_no_drivers_for_device(self, mock_detect):
        """Test device with no available drivers."""
        device_path = "/sys/devices/pci0000:00/0000:00:02.0"
        mock_detect.return_value = {
            device_path: {
                "modalias": "pci:v00008086d000012B9sv00008086sd0000FFFABC03sc00i00",
                "vendor": "Intel Corporation",
                "model": "Test Device",
                "drivers": {},
            }
        }

        proxy = self._client_bus.get_object(
            drivers_service.DriversService.BUS_NAME,
            drivers_service.DriversService.OBJ_PATH,
        )
        iface = dbus.Interface(proxy, drivers_service.DriversService.BUS_NAME)

        result = iface.drivers(timeout=5)
        result = _normalize_dbus_value(result)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sys_path"], device_path)
        self.assertEqual(result[0]["drivers"], [])

    @patch(
        "UbuntuDrivers.service.drivers_service.UbuntuDrivers.detect.system_device_drivers"
    )
    def test_dbus_drivers_multiple_devices(self, mock_detect):
        """Test with multiple devices."""
        mock_detect.return_value = {
            "/sys/devices/pci0000:00/0000:00:01.0": {
                "modalias": "pci:v000010DEd00001C8Dsv00001558sd0000852Bbc03sc00i00",
                "vendor": "NVIDIA",
                "model": "GPU 1",
                "drivers": {
                    "nvidia-driver-570": {
                        "free": False,
                        "from_distro": False,
                        "builtin": False,
                        "recommended": True,
                    }
                },
            },
            "/sys/devices/pci0000:00/0000:00:02.0": {
                "modalias": "pci:v00008086d000012B9sv00008086sd0000FFFABC03sc00i00",
                "vendor": "Intel",
                "model": "iGPU",
                "drivers": {
                    "i915": {
                        "free": True,
                        "from_distro": True,
                        "builtin": True,
                        "recommended": True,
                    }
                },
            },
        }

        proxy = self._client_bus.get_object(
            drivers_service.DriversService.BUS_NAME,
            drivers_service.DriversService.OBJ_PATH,
        )
        iface = dbus.Interface(proxy, drivers_service.DriversService.BUS_NAME)

        result = iface.drivers(timeout=5)
        result = _normalize_dbus_value(result)

        self.assertEqual(len(result), 2)
        # Devices should be sorted by sys_path
        self.assertEqual(result[0]["sys_path"], "/sys/devices/pci0000:00/0000:00:01.0")
        self.assertEqual(result[1]["sys_path"], "/sys/devices/pci0000:00/0000:00:02.0")

    @patch(
        "UbuntuDrivers.service.drivers_service.UbuntuDrivers.detect.system_device_drivers"
    )
    def test_dbus_drivers_sorting(self, mock_detect):
        """Test that drivers are sorted with recommended first."""
        device_path = "/sys/devices/pci0000:00/0000:00:01.0"
        mock_detect.return_value = {
            device_path: {
                "modalias": "pci:v000010DEd00001C8D",
                "vendor": "NVIDIA",
                "model": "GPU",
                "drivers": {
                    "xserver-xorg-video-nouveau": {
                        "free": True,
                        "from_distro": True,
                        "builtin": True,
                        "recommended": False,
                    },
                    "nouveau-firmware": {
                        "free": True,
                        "from_distro": True,
                        "builtin": False,
                        "recommended": False,
                    },
                    "nvidia-driver-570": {
                        "free": False,
                        "from_distro": False,
                        "builtin": False,
                        "recommended": True,
                    },
                },
            }
        }

        proxy = self._client_bus.get_object(
            drivers_service.DriversService.BUS_NAME,
            drivers_service.DriversService.OBJ_PATH,
        )
        iface = dbus.Interface(proxy, drivers_service.DriversService.BUS_NAME)

        result = iface.drivers(timeout=5)
        result = _normalize_dbus_value(result)

        driver_names = [driver["name"] for driver in result[0]["drivers"]]
        # Recommended driver should be first
        self.assertEqual(driver_names[0], "nvidia-driver-570")
        # Non-recommended drivers should be sorted alphabetically
        self.assertIn("nouveau-firmware", driver_names[1:])
        self.assertIn("xserver-xorg-video-nouveau", driver_names[1:])

    @patch(
        "UbuntuDrivers.service.drivers_service.UbuntuDrivers.detect.system_device_drivers"
    )
    def test_dbus_drivers_driver_attributes(self, mock_detect):
        """Test that driver attributes are correctly mapped."""
        device_path = "/sys/devices/pci0000:00/0000:00:01.0"
        mock_detect.return_value = {
            device_path: {
                "modalias": "pci:v000010DEd00001C8D",
                "vendor": "NVIDIA",
                "model": "GPU",
                "drivers": {
                    "distro-free": {
                        "free": True,
                        "from_distro": True,
                        "builtin": True,
                        "recommended": False,
                    },
                    "distro-nonfree": {
                        "free": False,
                        "from_distro": True,
                        "builtin": False,
                        "recommended": False,
                    },
                    "third-party-free": {
                        "free": True,
                        "from_distro": False,
                        "builtin": False,
                        "recommended": False,
                    },
                },
            }
        }

        proxy = self._client_bus.get_object(
            drivers_service.DriversService.BUS_NAME,
            drivers_service.DriversService.OBJ_PATH,
        )
        iface = dbus.Interface(proxy, drivers_service.DriversService.BUS_NAME)

        result = iface.drivers(timeout=5)
        result = _normalize_dbus_value(result)

        drivers_by_name = {d["name"]: d for d in result[0]["drivers"]}

        # Test distro free driver
        self.assertEqual(drivers_by_name["distro-free"]["source"], "distro")
        self.assertTrue(drivers_by_name["distro-free"]["free"])
        self.assertTrue(drivers_by_name["distro-free"]["builtin"])

        # Test distro non-free driver
        self.assertEqual(drivers_by_name["distro-nonfree"]["source"], "distro")
        self.assertFalse(drivers_by_name["distro-nonfree"]["free"])
        self.assertFalse(drivers_by_name["distro-nonfree"]["builtin"])

        # Test third-party driver
        self.assertEqual(drivers_by_name["third-party-free"]["source"], "third-party")
        self.assertTrue(drivers_by_name["third-party-free"]["free"])
        self.assertFalse(drivers_by_name["third-party-free"]["builtin"])


class BuildDriversPayloadTests(unittest.TestCase):
    """Tests for the build_drivers_payload helper function."""

    @patch(
        "UbuntuDrivers.service.drivers_service.UbuntuDrivers.detect.system_device_drivers"
    )
    def test_build_drivers_payload_empty(self, mock_detect):
        """Test with no devices."""
        mock_detect.return_value = {}
        result = drivers_service.build_drivers_payload()
        self.assertEqual(result, [])

    @patch(
        "UbuntuDrivers.service.drivers_service.UbuntuDrivers.detect.system_device_drivers"
    )
    def test_build_drivers_payload_single_device(self, mock_detect):
        """Test with a single device."""
        mock_detect.return_value = {
            "/sys/devices/pci0000:00/0000:00:01.0": {
                "modalias": "pci:v000010DEd00001C8D",
                "vendor": "NVIDIA",
                "model": "GPU",
                "drivers": {
                    "nvidia-driver-570": {
                        "free": False,
                        "from_distro": False,
                        "builtin": False,
                        "recommended": True,
                    }
                },
            }
        }

        result = drivers_service.build_drivers_payload()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sys_path"], "/sys/devices/pci0000:00/0000:00:01.0")
        self.assertEqual(result[0]["vendor"], "NVIDIA")
        self.assertEqual(result[0]["model"], "GPU")
        self.assertEqual(len(result[0]["drivers"]), 1)
        self.assertEqual(result[0]["drivers"][0]["name"], "nvidia-driver-570")

    @patch(
        "UbuntuDrivers.service.drivers_service.UbuntuDrivers.detect.system_device_drivers"
    )
    def test_build_drivers_payload_missing_optional_fields(self, mock_detect):
        """Test handling of devices with missing optional fields."""
        mock_detect.return_value = {
            "/sys/devices/pci0000:00/0000:00:01.0": {
                # modalias, vendor, model are optional
                "drivers": {}
            }
        }

        result = drivers_service.build_drivers_payload()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sys_path"], "/sys/devices/pci0000:00/0000:00:01.0")
        self.assertEqual(result[0]["modalias"], "")
        self.assertEqual(result[0]["vendor"], "")
        self.assertEqual(result[0]["model"], "")


class DriversServiceUnitTests(unittest.TestCase):
    """Unit tests for DriversService class methods."""

    def test_drivers_service_initialization(self):
        """Test DriversService initialization without mainloop."""
        bus = MagicMock(spec=dbus.Bus)
        service = drivers_service.DriversService(bus)

        self.assertEqual(service.BUS_NAME, "org.ubuntu.Drivers")
        self.assertEqual(service.OBJ_PATH, "/org/ubuntu/Drivers")
        self.assertEqual(service._idle_timeout_seconds, 300)
        self.assertIsNone(service._mainloop)

    def test_drivers_service_initialization_with_timeout(self):
        """Test DriversService initialization with custom timeout."""
        bus = MagicMock(spec=dbus.Bus)
        service = drivers_service.DriversService(bus, idle_timeout_seconds=60)

        self.assertEqual(service._idle_timeout_seconds, 60)

    def test_drivers_service_touch(self):
        """Test that _touch updates last activity time."""
        bus = MagicMock(spec=dbus.Bus)
        service = drivers_service.DriversService(bus)

        initial_time = service._last_activity
        time.sleep(0.01)  # Small delay to ensure time difference
        service._touch()

        self.assertGreater(service._last_activity, initial_time)

    def test_drivers_service_check_idle_no_mainloop(self):
        """Test _check_idle returns True when no mainloop."""
        bus = MagicMock(spec=dbus.Bus)
        service = drivers_service.DriversService(bus)

        result = service._check_idle()
        self.assertTrue(result)

    def test_drivers_service_check_idle_not_expired(self):
        """Test _check_idle returns True when timeout not reached."""
        bus = MagicMock(spec=dbus.Bus)
        mainloop = MagicMock(spec=GLib.MainLoop)
        service = drivers_service.DriversService(
            bus, idle_timeout_seconds=300, mainloop=mainloop
        )

        result = service._check_idle()
        self.assertTrue(result)
        mainloop.quit.assert_not_called()

    def test_drivers_service_check_idle_expired(self):
        """Test _check_idle quits mainloop when timeout expired."""
        bus = MagicMock(spec=dbus.Bus)
        mainloop = MagicMock(spec=GLib.MainLoop)
        service = drivers_service.DriversService(
            bus,
            idle_timeout_seconds=0,
            mainloop=mainloop,  # Immediate timeout
        )

        # Immediately call _check_idle should detect timeout
        result = service._check_idle()
        self.assertFalse(result)
        mainloop.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
