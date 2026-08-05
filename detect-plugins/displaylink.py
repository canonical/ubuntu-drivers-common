# Detect USB devices which may require the DisplayLink driver

import os


DISPLAYLINK_USB_VENDOR_ID = "17e9"
DISPLAYLINK_DRIVER_PACKAGE = "displaylink-driver"
USB_SYSFS_ROOT = "/sys/bus/usb/devices"

# The in-kernel udl driver matches DisplayLink devices using interface
# descriptors: bInterfaceClass=0xff, bInterfaceSubClass=0x00,
# bInterfaceProtocol=0x00. See drivers/gpu/drm/udl/udl_drv.c in the
# Linux kernel source.
_UDL_INTERFACE_CLASS = "ff"
_UDL_INTERFACE_SUBCLASS = "00"
_UDL_INTERFACE_PROTOCOL = "00"


def _read_sysfs_value(path):
    """Read and return a stripped string from a sysfs attribute file."""
    try:
        with open(path, encoding="ascii") as attribute:
            return attribute.read().strip()
    except (OSError, UnicodeError):
        return None


def _matches_udl_interface(device_path):
    """Check if any interface on the device matches the udl driver criteria."""
    device_name = os.path.basename(device_path)
    try:
        entries = os.listdir(device_path)
    except OSError:
        return False

    for entry in entries:
        # Interface directories are named like "<device>:<config>.<iface>"
        if not entry.startswith(device_name + ":"):
            continue
        iface_path = os.path.join(device_path, entry)
        iface_class = _read_sysfs_value(
            os.path.join(iface_path, "bInterfaceClass")
        )
        iface_subclass = _read_sysfs_value(
            os.path.join(iface_path, "bInterfaceSubClass")
        )
        iface_protocol = _read_sysfs_value(
            os.path.join(iface_path, "bInterfaceProtocol")
        )
        if (iface_class == _UDL_INTERFACE_CLASS
                and iface_subclass == _UDL_INTERFACE_SUBCLASS
                and iface_protocol == _UDL_INTERFACE_PROTOCOL):
            return True

    return False


def _detect_displaylink_device(sysfs_root=USB_SYSFS_ROOT):
    """Scan sysfs for a DisplayLink device needing the proprietary driver."""
    try:
        device_names = sorted(os.listdir(sysfs_root))
    except OSError:
        return None

    for device_name in device_names:
        device_path = os.path.join(sysfs_root, device_name)

        vendor = _read_sysfs_value(os.path.join(device_path, "idVendor"))
        if vendor is None or vendor.lower() != DISPLAYLINK_USB_VENDOR_ID:
            continue

        product_id = _read_sysfs_value(
            os.path.join(device_path, "idProduct")
        )
        if product_id is None:
            continue

        # Devices already handled by the in-kernel udl driver should not
        # cause the proprietary DisplayLink package to be recommended.
        # The udl driver matches on interface descriptors (class=ff,
        # subclass=00, protocol=00), so we check for that here
        if _matches_udl_interface(device_path):
            continue

        product_name = _read_sysfs_value(
            os.path.join(device_path, "product")
        )

        if product_name:
            model = product_name
        else:
            model = "USB product {}".format(product_id.lower())

        return {
            "vendor": "DisplayLink",
            "model": model,
        }

    return None


def detect(apt_cache):
    """Return package recommendation if a DisplayLink device is detected."""
    del apt_cache

    device = _detect_displaylink_device()
    if device is None:
        return None

    return {
        "packages": [DISPLAYLINK_DRIVER_PACKAGE],
        "vendor": device["vendor"],
        "model": device["model"],
    }
