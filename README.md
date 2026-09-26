# ubuntu-drivers-common

This package aggregates and abstracts Ubuntu specific logic and knowledge
about third-party driver packages, and provides APIs for installers and driver
configuration GUIs. It also contains some NVidia specific support code to find
the most appropriate driver version (as we usually ship several), as well as
setting up the alternatives symlinks that the proprietary NVidia and FGLRX
packages use.

## Development Setup

After cloning the repository, configure git to use the project's git hooks:

```bash
git config core.hooksPath git-hooks
```

This enables pre-commit hooks that run static analysis (pycodestyle, pyflakes) and mypy type checking.

## Command line interface

The simplest frontend is the `ubuntu-drivers` command line tool. You can use
it to show the available driver packages which apply to the current system
(`ubuntu-drivers list`), or to install all drivers which are appropriate for
automatic installation (`sudo ubuntu-drivers autoinstall`), which is mostly
useful for integration into installers.

Please see `ubuntu-drivers --help` for details.

## Python API

The `UbuntuDrivers.detect` Python module provides some functions to detect the
system's hardware, matching driver packages, and packages which are eligible
for automatic installation.

The three main functions are:

1. Which driver packages apply to this system?

   `packages = UbuntuDrivers.detect.system_driver_packages()`

2. Which devices need drivers, and which packages do they need?

   `driver_info = UbuntuDrivers.detect.system_device_drivers()`

3. Which driver package(s) applies to this piece of hardware?

    ```python
    import apt
    apt_cache = apt.Cache
    apt_packages = UbuntuDrivers.detect.packages_for_modalias(apt_cache, modalias)
    ```

These functions only use python-apt. They do not need any other dependencies,
root privileges, D-BUS calls, etc.

## D-Bus API

This project also provides a system-bus D-Bus service that exposes driver
information. The service registers as `com.ubuntu.Drivers` on the system bus
with the object path `/com/ubuntu/Drivers` and exposes a single method:

* `drivers`: Returns a list of devices and their available drivers. The first
  driver entry in each list is the recommended one.

The returned structure is a list of dictionaries like:

```python
[
   {
      "sys_path": "/sys/devices/...",
      "modalias": "pci:...",
      "vendor": "NVIDIA Corporation",
      "model": "GP107M [GeForce GTX 1050 Mobile]",
      "drivers": [
         {
            "name": "nvidia-driver-570",
            "source": "distro",
            "free": False,
            "builtin": False,
            "recommended": True,
            "support": "PB",
            "open_preferred": False,
            "packages": ["nvidia-driver-570", "linux-modules-nvidia-570-generic"],
            "gpgpu_packages": ["nvidia-headless-no-dkms-570", "linux-modules-nvidia-570-generic"],
         },
         ...
      ],
   },
   ...
]
```

`source` is either `"distro"` or `"third-party"`, and `support` carries the
package's apt `Support` field (`"PB"`, `"NFB"`, `"LTSB"` or `"Legacy"`), empty
when the package does not declare one. `open_preferred` is `True` when Ubuntu's
driver-selection logic prefers the "open" kernel module variant over the
closed-source variant for this driver.

`packages` is what `ubuntu-drivers install <name>` would install for this
driver: the complete install set, not filtered by installed state.
`gpgpu_packages` is the equivalent for `ubuntu-drivers install --gpgpu
<name>`. Either list may be empty when the driver would require DKMS.

The D-Bus service implementation lives in
`UbuntuDrivers/service/drivers_service.py`. It is activated on demand by
`dbus-daemon` and exits after a short period of inactivity, so results are
never more than one idle period stale.

## Detection logic

Hardware detection uses three complementary mechanisms:

* **Modaliases:** match device identifiers from sysfs against package
   `Modaliases` patterns
* **MIDR:** match ARM CPU identification fields against package `Midr`
   fields
* **Plugins:** run custom checks for hardware that needs additional detection
   logic (see below)

### Modaliases

The principal method of mapping hardware to driver packages is to use modalias
patterns. Hardware devices export a "modalias" sysfs attribute, for example

```shell
$ cat /sys/devices/pci0000:00/0000:00:1b.0/modalias
pci:v00008086d00003B56sv000017AAsd0000215Ebc04sc03i00
```

Kernel modules declare which hardware they can handle with modalias patterns
(globs), e. g.:

```shell
$ modinfo snd_hda_intel
[...]
alias:          pci:v00008086d*sv*sd*bc04sc03i00*
```

Driver packages which are not installed by default (e. g. backports of drivers
from newer Linux packages, or the proprietary NVidia driver package
`nvidia-current`) have a `Modaliases:` package header which includes all
modalias patterns from all kernel modules that they ship. It is recommended to
add these headers to the package with `dh_modaliases(1)`.

`ubuntu-drivers-common` uses these package headers to map a particular piece of
hardware (identified by a modalias) to the driver packages which cover that
hardware.

### ARM CPU MIDR matching

MIDR detection reads `/sys/devices/system/cpu/cpu*/regs/identification/midr_el1`
and considers every distinct CPU type. Packages can declare constraints such as:

```text
Midr: implementer:0x41,part_number:0xd05
```

(Note: Within your source package, declare this field as `XB-Midr`. The `XB-` will be stripped in the deb.)

Supported fields: `implementer`, `variant`, `architecture`, `part_number`,
and `revision`. All specified fields must match at least one CPU's MIDR; omitted fields
are unconstrained. Missing or invalid MIDR data is ignored.

## Custom NVIDIA configuration (`custom_supported_gpus.json`)

For NVIDIA GPUs, the modalias-based detection can be overridden by a custom
configuration file, which pins a specific driver series to a given PCI device
ID and declares extra device features. This is mainly used by OEM enablement
to ship a validated driver for a particular platform.

The file is looked up in this order, and the first one found wins:

1. `/etc/custom_supported_gpus.json`
2. `/usr/share/oem-*-meta/custom_supported_gpus.json` (first match in sorted
   order)

### Format

```json
{
  "chips": [
    {
      "devid": "0x25BA",
      "name": "TEST 25BA",
      "branch": "580",
      "features": [
        "runtimepm"
      ]
    }
  ]
}
```

* `devid`: the PCI device ID of the GPU, as an uppercase hexadecimal string
  with a `0x` prefix (this is the `d0000....` part of the modalias).
* `name`: a human-readable name, only used for logging.
* `branch`: the pinned driver series. Anything after the first `.` is ignored,
  so both `"580"` and `"580.1234"` select the `580` series.
* `features`: a list of feature flags. `runtimepm` marks the device as
  supporting runtime power management for the pinned series, which makes
  `ubuntu-drivers` enable runtime PM for the NVIDIA driver during
  installation.

### Behaviour

`branch` is mapped to the exact package name `nvidia-driver-<branch>`, which
must exist in the apt package pool; otherwise the entry is ignored and normal
detection applies. Because the match is on the exact package name, a `branch`
of `"580"` pins `nvidia-driver-580` and never the `nvidia-driver-580-open`
variant, even when the open variant would otherwise be preferred. To pin the
open variant, set `"branch": "580-open"`.

The pinned driver is used as follows:

* `ubuntu-drivers list` and `ubuntu-drivers devices` still show every
  applicable driver, but the pinned one is flagged as `recommended`.
* `ubuntu-drivers list --recommended`, `ubuntu-drivers autoinstall` and
  `ubuntu-drivers install` without an explicit driver argument collapse the
  NVIDIA alternatives to the pinned driver only.
* `ubuntu-drivers install <driver>` with an explicit driver argument still
  honors the user's choice.

## Custom detection plugins

For some kinds of drivers the modalias detection approach does not work. For
example, the "sl-modem-daemon" driver requires some checks in
`/proc/asound/cards` and `aplay -l` to decide whether or not it applies to the
system. These special cases can be put into a `detection plugin`, by adding a
small piece of Python code to `/usr/share/ubuntu-drivers-common/detect/NAME.py`
(shipped in `./detect-plugins/` in the `ubuntu-drivers-common` source). They need
to export a method

```python
   def detect(apt_cache):
      # do detection logic here
      return ['driver_package', ...]
```

which can do any kind of detection and then return the resulting set of
packages that apply to the current system. Please note that this cannot rely on
having root privileges.

## Autopkgtest

For the autopkgtest of ubuntu-drivers, the following command can be used when
developing test cases:

```shell
PYTHONPATH=. tests/run test_ubuntu_drivers
```

Testing in a clean environment is always recommended. Using a pbuilder chroot,
an sbuild chroot, or a direct upload to a PPA, will reduce the chances of tests
failing due to your specific system.
