"""D-Bus service for ubuntu-drivers-common."""

from __future__ import annotations

from typing import Any, Dict, List

import UbuntuDrivers.detect

import apt_pkg
from gi.repository import Gio, GLib
import os

sys_path = os.environ.get("UBUNTU_DRIVERS_SYS_DIR")


def build_drivers_payload() -> List[Dict[str, Any]]:
    """Build the driver list payload for the D-Bus API.

    Queries the apt cache and system device drivers, returning a list of
    device dicts sorted by sysfs path.     Each device dict has the form::

        {
            "sys_path":  str,   # sysfs path identifying the device
            "modalias":  str,   # modalias string (empty if unavailable)
            "vendor":    str,   # human-readable vendor name (empty if unavailable)
            "model":     str,   # human-readable model name (empty if unavailable)
            "drivers": [        # list of driver dicts, recommended first
                {
                    "name":        str,   # package name
                    "source":      str,   # "distro" or "third-party"
                    "free":        bool,  # whether the driver is free software
                    "builtin":     bool,  # whether the driver is built into the kernel
                    "recommended": bool,  # whether this is the recommended driver
                    "support":     str,   # apt Support field value (e.g. "PB", "NFB", "LTSB", "Legacy"), empty if absent
                },
                ...
            ],
        }

    Raises:
        RuntimeError: if the apt cache cannot be initialized.
    """
    apt_pkg.init_config()
    apt_pkg.init_system()
    try:
        cache = apt_pkg.Cache(None)
    except Exception as ex:
        raise RuntimeError(f"Failed to initialize apt cache: {ex}") from ex

    devices = UbuntuDrivers.detect.system_device_drivers(
        apt_cache=cache, sys_path=sys_path, freeonly=False
    )

    if not devices:
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
                    "source": (
                        "distro"
                        if pkg_info.get("from_distro", False)
                        else "third-party"
                    ),
                    "free": bool(pkg_info.get("free", False)),
                    "builtin": bool(pkg_info.get("builtin", False)),
                    "recommended": bool(pkg_info.get("recommended", False)),
                    "support": pkg_info.get("support") or "",
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


def _to_variant(value: Any) -> GLib.Variant:
    """Recursively convert a Python value to a GLib.Variant for D-Bus serialization.

    Supported types and their D-Bus signatures:
        dict  -> a{sv}  (string-keyed variant dict)
        list  -> aa{sv} if all items are dicts, otherwise av
        bool  -> b
        str   -> s
        int   -> x (int64)

    Raises:
        TypeError: if the value is of an unsupported type.
    """
    if isinstance(value, dict):
        return GLib.Variant("a{sv}", _to_variant_dict(value))
    if isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            return GLib.Variant("aa{sv}", [_to_variant_dict(item) for item in value])
        return GLib.Variant("av", [_to_variant(item) for item in value])
    if isinstance(value, bool):
        return GLib.Variant("b", value)
    if isinstance(value, str):
        return GLib.Variant("s", value)
    if isinstance(value, int):
        return GLib.Variant("x", value)
    raise TypeError(f"Unsupported value for D-Bus serialization: {type(value)!r}")


def _to_dbus_payload(payload: List[Dict[str, Any]]) -> GLib.Variant:
    """Wrap a payload list as a D-Bus return value with signature (aa{sv})."""
    return GLib.Variant("(aa{sv})", ([_to_variant_dict(item) for item in payload],))


def _to_variant_dict(value: Dict[str, Any]) -> Dict[str, GLib.Variant]:
    """Convert a plain Python dict to a dict of GLib.Variants keyed by string."""
    return {str(k): _to_variant(v) for k, v in value.items()}


class _DriversCall:
    """Encapsulates the async lifecycle of a single ``drivers`` method invocation.

    Holds the application open for the duration of the call, runs
    :func:`build_drivers_payload` in a worker thread, then returns the result
    (or a ``CacheFailure`` D-Bus error) to the client on the main thread.

    Args:
        app: The owning application; ``hold()``/``release()`` are called around
             the async work to prevent premature idle-timeout.
        invocation: The pending D-Bus method invocation to reply to.
    """

    def __init__(
        self, app: Gio.Application, invocation: Gio.DBusMethodInvocation
    ) -> None:
        self._app = app
        self._invocation = invocation
        self._task = Gio.Task.new(None, None, None, None)
        self._task.set_return_on_cancel(False)
        self._task.connect("notify::completed", self._on_done)

    def start(self) -> None:
        """Begin the async payload build in a worker thread."""
        self._app.hold()
        self._task.run_in_thread(self._run)

    def _run(self, task: Gio.Task, _obj: None, _data: None, _cancel: None) -> None:
        try:
            task.return_value(_to_dbus_payload(build_drivers_payload()))
        except RuntimeError as ex:
            task.return_error(
                GLib.Error(str(ex), "org.ubuntu.Drivers.Error.CacheFailure", 0)
            )

    def _on_done(self, _source: None, _result: Gio.Task) -> None:
        try:
            value = self._task.propagate_value()
            self._invocation.return_value(value.value)
        except GLib.Error as ex:
            self._invocation.return_dbus_error(
                "org.ubuntu.Drivers.Error.CacheFailure",
                ex.message,
            )
        finally:
            self._app.release()


class DriversService:
    """D-Bus object that exposes driver detection results on org.ubuntu.Drivers.

    This class handles registration of the D-Bus object on a connection and
    dispatches the ``drivers`` method call asynchronously so that the GLib main
    loop is never blocked during apt cache initialization or hardware detection.

    The object exposes a single interface:

        interface org.ubuntu.Drivers
            method drivers() -> aa{sv}

    The returned value is the list produced by :func:`build_drivers_payload`.

    Args:
        app: The owning ``Gio.Application``, used to call ``hold()``/``release()``
             around async work so that the application inactivity timeout is
             correctly suspended while a request is in flight.
    """

    BUS_NAME = "org.ubuntu.Drivers"
    OBJ_PATH = "/org/ubuntu/Drivers"
    _INTROSPECTION_XML = """
<node>
  <interface name="org.ubuntu.Drivers">
    <method name="drivers">
      <arg type="aa{sv}" direction="out"/>
    </method>
  </interface>
</node>
"""

    def __init__(self, app: Gio.Application) -> None:
        self._app = app
        self._object_registration_id: int | None = None
        self._interface_info = Gio.DBusNodeInfo.new_for_xml(
            self._INTROSPECTION_XML
        ).interfaces[0]

    def export(self, connection: Gio.DBusConnection) -> None:
        """Register the D-Bus object on *connection*."""
        if self._object_registration_id is not None:
            return

        if hasattr(connection, "register_object_with_closures2"):
            self._object_registration_id = connection.register_object_with_closures2(
                self.OBJ_PATH,
                self._interface_info,
                self._handle_method_call,
                None,
                None,
            )
        else:
            self._object_registration_id = connection.register_object(
                self.OBJ_PATH,
                self._interface_info,
                self._handle_method_call,
                None,
                None,
            )

    def _handle_method_call(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        method_name: str,
        _parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        """Dispatch an incoming D-Bus method call.

        Only ``drivers`` is supported. The work is run asynchronously in a
        thread via :class:`_DriversCall` so the main loop is never blocked.
        """
        if method_name != "drivers":
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod",
                f"Unknown method: {method_name}",
            )
            return

        _DriversCall(self._app, invocation).start()

    def unexport(self, connection: Gio.DBusConnection) -> None:
        """Unregister the D-Bus object from *connection*."""
        if self._object_registration_id is None:
            return
        connection.unregister_object(self._object_registration_id)
        self._object_registration_id = None


class DriversApplication(Gio.Application):
    """GApplication that owns the org.ubuntu.Drivers bus name and manages lifecycle.

    Registers the service on the session bus via D-Bus activation and exits
    automatically after *idle_timeout_seconds* of inactivity using
    ``GApplication.set_inactivity_timeout``.  Inactivity is defined by GLib as
    the time since the last ``hold()``/``release()`` pair completed; each
    in-flight ``drivers`` call holds the application, preventing premature exit.

    Args:
        idle_timeout_seconds: Seconds of inactivity before the application exits.
            Defaults to 300 (5 minutes).
    """

    def __init__(self, idle_timeout_seconds: int = 300) -> None:
        super().__init__(
            application_id=DriversService.BUS_NAME,
            flags=Gio.ApplicationFlags.IS_SERVICE,
        )
        self.set_inactivity_timeout(idle_timeout_seconds * 1000)
        self._service = DriversService(app=self)

    def do_activate(self) -> None:
        # D-Bus clients activate the service via method calls; no GUI activation.
        return

    def do_dbus_register(
        self, connection: Gio.DBusConnection, object_path: str
    ) -> bool:
        if not Gio.Application.do_dbus_register(self, connection, object_path):
            return False
        self._service.export(connection)
        return True

    def do_dbus_unregister(
        self, connection: Gio.DBusConnection, object_path: str
    ) -> None:
        self._service.unexport(connection)
        Gio.Application.do_dbus_unregister(self, connection, object_path)


def main() -> None:
    """Run the D-Bus service main loop."""
    app = DriversApplication()
    app.run(None)
