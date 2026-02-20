#!/usr/bin/python3

import os
import shutil
import signal
import subprocess
import threading
import unittest
from unittest.mock import patch

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

from service import drivers_service


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


if __name__ == "__main__":
    unittest.main()
