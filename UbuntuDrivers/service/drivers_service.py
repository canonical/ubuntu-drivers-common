"""D-Bus service for ubuntu-drivers-common."""

from __future__ import annotations

import signal
import sys
from typing import Callable, List, Optional

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
            source = "distro" if pkg_info.get("from_distro", False) else "third-party"
            driver_list.append(
                GLib.Variant(
                    "a{sv}",
                    {
                        "name": GLib.Variant("s", pkg_name),
                        "source": GLib.Variant("s", source),
                        "free": GLib.Variant("b", bool(pkg_info.get("free", False))),
                        "builtin": GLib.Variant(
                            "b", bool(pkg_info.get("builtin", False))
                        ),
                        "recommended": GLib.Variant(
                            "b", bool(pkg_info.get("recommended", False))
                        ),
                        "support": GLib.Variant("s", pkg_info.get("support") or ""),
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


class _IdleManager:
    """Inactivity manager that invokes a callback after a period of idle. Used
    for shutting down the `DriversService` after a period of inactivity.

    Callers call :meth:`hold` when async work begins and :meth:`release` when
    it ends. The timeout is only active while no work is in progress.

    Args:
        on_timeout: Callable invoked when the inactivity timeout fires.
        timeout_seconds: Seconds of inactivity before invoking `on_timeout`.
    """

    def __init__(
        self, on_timeout: Callable[[], object], timeout_seconds: int = 300
    ) -> None:
        self._on_timeout_cb = on_timeout
        self._timeout_seconds = timeout_seconds
        self._held: bool = False
        self._timeout_id: Optional[int] = None

    def start(self) -> None:
        """Begin the inactivity countdown. Call once after the bus name is acquired."""
        self._schedule()

    def hold(self) -> None:
        """Mark work as in-progress and cancel any pending quit timeout."""
        self._held = True
        self._cancel()

    def release(self) -> None:
        """Mark work as complete and schedule the quit timeout."""
        self._held = False
        self._schedule()

    def cancel(self) -> None:
        """Cancel any pending timeout permanently (used during shutdown)."""
        self._cancel()

    def _schedule(self) -> None:
        self._cancel()
        self._timeout_id = GLib.timeout_add_seconds(
            self._timeout_seconds, self._on_timeout
        )

    def _cancel(self) -> None:
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None

    def _on_timeout(self) -> bool:
        self._timeout_id = None
        if not self._held:
            self._on_timeout_cb()
        return GLib.SOURCE_REMOVE


class DriversService:
    """D-Bus object that exposes driver detection results on com.ubuntu.Drivers.

    This class handles registration of the D-Bus object on a connection and
    dispatches the ``drivers`` method call asynchronously so that the GLib main
    loop is never blocked during apt cache initialization or hardware detection.

    Results are cached: the first call triggers detection; subsequent concurrent
    calls are queued and all receive the same result when detection completes.
    After a result is cached it is returned immediately to callers.

    The object exposes a single interface:

        interface com.ubuntu.Drivers
            method drivers() -> aa{sv}

    Args:
        idle_manager: Instance of _IdleManager to manage inactivity timeouts.
    """

    BUS_NAME = "com.ubuntu.Drivers"
    OBJ_PATH = "/org/ubuntu/Drivers"
    _INTROSPECTION_XML = """
<node>
  <interface name="com.ubuntu.Drivers">
    <method name="drivers">
      <arg type="aa{sv}" direction="out"/>
    </method>
  </interface>
</node>
"""

    def __init__(
        self,
        idle_manager: _IdleManager,
    ) -> None:
        self._hold = idle_manager.hold
        self._release = idle_manager.release
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
        """Dispatch an incoming D-Bus method call."""
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
            self._hold()
            task = Gio.Task.new(None, None, self._on_done, None)
            task.set_return_on_cancel(True)
            task.run_in_thread(self._run)

    def _run(self, task: Gio.Task, _obj: None, _data: None, _cancel: None) -> None:
        try:
            task.return_value(_build_drivers_variant())
        except RuntimeError as ex:
            task.return_error(
                GLib.Error(str(ex), "com.ubuntu.Drivers.Error.CacheFailure", 0)
            )

    def _on_done(self, _source: None, result: Gio.Task, _data: None) -> None:
        try:
            value = result.propagate_value()
            self._cached_result = value.value
            for invocation in self._pending_invocations:
                invocation.return_value(self._cached_result)
        except GLib.Error as ex:
            for invocation in self._pending_invocations:
                invocation.return_dbus_error(
                    "com.ubuntu.Drivers.Error.CacheFailure",
                    ex.message,
                )
        finally:
            self._pending_invocations.clear()
            self._task_running = False
            self._release()

    def unexport(self, connection: Gio.DBusConnection) -> None:
        """Unregister the D-Bus object from *connection*."""
        if self._object_registration_id is None:
            return
        connection.unregister_object(self._object_registration_id)
        self._object_registration_id = None


class _ServiceRunner:
    """Owns the bus name and manages the service lifecycle.

    Args:
        loop: The GLib main loop to quit once the bus name is released.
        timeout_seconds: Seconds of inactivity before initiating shutdown.
    """

    def __init__(self, loop: GLib.MainLoop, timeout_seconds: int = 300) -> None:
        self._loop = loop
        self._idle_mgr = _IdleManager(
            on_timeout=self._begin_shutdown,
            timeout_seconds=timeout_seconds,
        )
        self._service: Optional[DriversService] = None
        self._connection: Optional[Gio.DBusConnection] = None
        self._owner_id: int = 0

    def run(self) -> None:
        """Acquire the bus name, install signal handling, and run the main loop."""
        # Block the default SIGTERM action so the kernel does not kill us
        # mid-drain.  GLib's Unix signal source delivers it safely on the
        # next main-loop iteration instead.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        GLib.unix_signal_add(
            GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._begin_shutdown
        )

        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SYSTEM,
            DriversService.BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self.on_bus_acquired,
            self.on_name_acquired,
            self.on_name_lost,
        )

        try:
            self._loop.run()
        finally:
            if self._service is not None and self._connection is not None:
                self._service.unexport(self._connection)

    def on_bus_acquired(self, connection: Gio.DBusConnection, _name: str) -> None:
        self._service = DriversService(self._idle_mgr)
        self._service.export(connection)
        self._connection = connection

    def on_name_acquired(self, _connection: Gio.DBusConnection, _name: str) -> None:
        self._idle_mgr.start()

    def on_name_lost(self, connection: Optional[Gio.DBusConnection], name: str) -> None:
        if connection is None:
            print(
                "ubuntu-drivers-dbus-service: fatal: cannot connect to system bus",
                file=sys.stderr,
            )
        elif self._owner_id != 0:
            # owner_id is zeroed in _begin_shutdown before unowning, so a
            # non-zero value here is unexpected
            print(
                f"ubuntu-drivers-dbus-service: fatal: cannot own '{name}' on system bus",
                file=sys.stderr,
            )
        self._idle_mgr.cancel()
        self._loop.quit()

    def _begin_shutdown(self) -> bool:
        """Release the bus name; on_name_lost will quit the loop once dbus-daemon acks."""
        self._idle_mgr.cancel()
        owner_id = self._owner_id
        self._owner_id = 0
        Gio.bus_unown_name(owner_id)
        return GLib.SOURCE_REMOVE


def main() -> None:
    """Run the D-Bus system service main loop."""
    DEFAULT_IDLE_TIMEOUT_SECONDS = 300
    loop = GLib.MainLoop()
    _ServiceRunner(loop, timeout_seconds=DEFAULT_IDLE_TIMEOUT_SECONDS).run()
