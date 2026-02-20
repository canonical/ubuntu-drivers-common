"""D-Bus service for ubuntu-drivers-common."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import UbuntuDrivers.detect

import apt_pkg
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import os

sys_path = os.environ.get("UBUNTU_DRIVERS_SYS_DIR")


def build_drivers_payload() -> List[Dict[str, Any]]:
    """Return the drivers payload for the D-Bus API."""

    apt_pkg.init_config()
    apt_pkg.init_system()
    try:
        cache = apt_pkg.Cache(None)
    except Exception as ex:
        print(ex)
        return []

    devices = UbuntuDrivers.detect.system_device_drivers(
        apt_cache=cache, sys_path=sys_path, freeonly=False
    )

    if devices is None:
        return []

    payload: List[Dict[str, Any]] = []

    for device_name in sorted(devices):
        info = devices[device_name]
        drivers_info = info.get("drivers", {})
        drivers_list: List[Dict[str, Any]] = []

        for pkg_name, pkg_info in sorted(
            drivers_info.items(),
            key=lambda item: (not item[1].get("recommended", False), item[0]),
        ):
            drivers_list.append(
                {
                    "name": pkg_name,
                    "source": "distro"
                    if pkg_info.get("from_distro", False)
                    else "third-party",
                    "free": bool(pkg_info.get("free", False)),
                    "builtin": bool(pkg_info.get("builtin", False)),
                }
            )

        payload.append(
            {
                "sys_path": device_name,
                "modalias": info.get("modalias", ""),
                "vendor": info.get("vendor", ""),
                "model": info.get("model", ""),
                "drivers": drivers_list,
            }
        )

    return payload


def _to_dbus_value(value: Any) -> Any:
    if isinstance(value, dict):
        return dbus.Dictionary(
            {str(k): _to_dbus_value(v) for k, v in value.items()},
            signature="sv",
        )
    if isinstance(value, list):
        if not value:
            return dbus.Array([], signature="a{sv}")
        if all(isinstance(item, dict) for item in value):
            return dbus.Array(
                [_to_dbus_value(item) for item in value], signature="a{sv}"
            )
        return dbus.Array([_to_dbus_value(item) for item in value], signature="v")
    if isinstance(value, bool):
        return dbus.Boolean(value)
    if isinstance(value, str):
        return dbus.String(value)
    return value


def _to_dbus_payload(payload: List[Dict[str, Any]]) -> dbus.Array:
    return dbus.Array([_to_dbus_value(item) for item in payload], signature="a{sv}")


class DriversService(dbus.service.Object):
    """D-Bus service exposing driver detection results."""

    BUS_NAME = "org.ubuntu.Drivers"
    OBJ_PATH = "/org/ubuntu/Drivers"

    def __init__(
        self,
        bus: "dbus.Bus",
        idle_timeout_seconds: int = 300,
        mainloop: Optional["GLib.MainLoop"] = None,
    ) -> None:
        self._idle_timeout_seconds = idle_timeout_seconds
        self._last_activity = time.time()
        self._mainloop = mainloop

        super().__init__(bus, self.OBJ_PATH)

        if self._mainloop is not None:
            GLib.timeout_add_seconds(60, self._check_idle)

    def _touch(self) -> None:
        self._last_activity = time.time()

    def _check_idle(self) -> bool:
        if self._mainloop is None:
            return True

        if time.time() - self._last_activity >= self._idle_timeout_seconds:
            self._mainloop.quit()
            return False

        return True

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="aa{sv}")
    def drivers(self) -> List[Dict[str, Any]]:
        """Return the list of devices and their available drivers."""

        self._touch()
        return _to_dbus_payload(build_drivers_payload())


def main() -> None:
    """Run the D-Bus service main loop."""

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    dbus.service.BusName(DriversService.BUS_NAME, bus)

    loop = GLib.MainLoop()
    DriversService(bus, mainloop=loop)
    loop.run()
