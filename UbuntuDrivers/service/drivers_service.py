"""D-Bus service for ubuntu-drivers-common."""

from __future__ import annotations

from typing import List, Optional

import UbuntuDrivers.detect

import apt_pkg
from gi.repository import Gio, GLib
import os

sys_path = os.environ.get("UBUNTU_DRIVERS_SYS_DIR")

# D-Bus signature for the drivers() return value.
_DRIVERS_SIGNATURE = "aa{sv}"


def _build_drivers_variant() -> GLib.Variant:
    """Build the driver list as a D-Bus ``(aa{sv})`` GLib.Variant.

    Queries the apt cache and system device drivers, returning a D-Bus
    return variant with signature ``(aa{sv})`` — a tuple wrapping an array
    of string-to-variant dicts.  Each dict represents one device::

        sys_path  s     sysfs path identifying the device
        modalias  s     modalias string (empty if unavailable)
        vendor    s     human-readable vendor name (empty if unavailable)
        model     s     human-readable model name (empty if unavailable)
        drivers   av    array of driver a{sv} dicts (recommended first)

    Each driver dict (``a{sv}``) contains::

        name        s   package name
        source      s   "distro" or "third-party"
        free        b   whether the driver is free software
        builtin     b   whether the driver is built into the kernel
        recommended b   whether this is the recommended driver
        support     s   apt Support field value (e.g. "PB"), empty if absent

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

    device_list = []

    for device_name in sorted(devices):
        info = devices[device_name]
        drivers_info = info.get("drivers", {})

        driver_list = []
        for pkg_name, pkg_info in sorted(
            drivers_info.items(),
            key=lambda item: (not item[1].get("recommended", False), item[0]),
        ):
            driver_list.append(
                GLib.Variant(
                    "a{sv}",
                    {
                        "name": GLib.Variant("s", pkg_name),
                        "source": GLib.Variant(
                            "s",
                            "distro"
                            if pkg_info.get("from_distro", False)
                            else "third-party",
                        ),
                        "free": GLib.Variant("b", bool(pkg_info.get("free", False))),
                        "builtin": GLib.Variant(
                            "b", bool(pkg_info.get("builtin", False))
                        ),
                        "recommended": GLib.Variant(
                            "b", bool(pkg_info.get("recommended", False))
                        ),
                        "support": GLib.Variant(
                            "s", pkg_info.get("support") or ""
                        ),
                    },
                )
            )

        device_list.append(
            {
                "sys_path": GLib.Variant("s", device_name),
                "modalias": GLib.Variant("s", info.get("modalias", "")),
                "vendor": GLib.Variant("s", info.get("vendor", "")),
                "model": GLib.Variant("s", info.get("model", "")),
                "drivers": GLib.Variant("av", driver_list),
            }
        )

    return GLib.Variant(f"({_DRIVERS_SIGNATURE})", (device_list,))


class DriversService:
    """D-Bus object that exposes driver detection results on org.ubuntu.Drivers.

    This class handles registration of the D-Bus object on a connection and
    dispatches the ``drivers`` method call asynchronously so that the GLib main
    loop is never blocked during apt cache initialization or hardware detection.

    Results are cached: the first call triggers detection; subsequent concurrent
    calls are queued and all receive the same result when detection completes.
    After a result is cached it is returned immediately to callers.

    The object exposes a single interface:

        interface org.ubuntu.Drivers
            method drivers() -> aa{sv}

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

        self._cached_result: Optional[GLib.Variant] = None
        self._pending_invocations: List[Gio.DBusMethodInvocation] = []
        self._task_running = False

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

        Only ``drivers`` is supported. If detection is already cached the result
        is returned immediately. If detection is in progress, the invocation is
        queued. Otherwise, a new worker task is started.
        """
        if method_name != "drivers":
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod",
                f"Unknown method: {method_name}",
            )
            return

        if self._cached_result is not None:
            invocation.return_value(self._cached_result)
            return

        self._pending_invocations.append(invocation)

        if not self._task_running:
            self._task_running = True
            self._app.hold()
            task = Gio.Task.new(None, None, self._on_done, None)
            task.set_return_on_cancel(True)
            task.run_in_thread(self._run)

    def _run(self, task: Gio.Task, _obj: None, _data: None, _cancel: None) -> None:
        try:
            task.return_value(_build_drivers_variant())
        except RuntimeError as ex:
            task.return_error(
                GLib.Error(str(ex), "org.ubuntu.Drivers.Error.CacheFailure", 0)
            )

    def _on_done(
        self, _source: None, result: Gio.Task, _data: None
    ) -> None:
        try:
            value = result.propagate_value()
            self._cached_result = value.value
            for invocation in self._pending_invocations:
                invocation.return_value(self._cached_result)
        except GLib.Error as ex:
            for invocation in self._pending_invocations:
                invocation.return_dbus_error(
                    "org.ubuntu.Drivers.Error.CacheFailure",
                    ex.message,
                )
        finally:
            self._pending_invocations.clear()
            self._task_running = False
            self._app.release()

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
