#!/usr/bin/python3

import glob
import os

from setuptools import find_packages, setup
from distutils.command.build import build
from distutils.command.clean import clean


class Build(build):
    def run(self):
        self.spawn(["make", "-C", "share/hybrid", "all"])
        super().run()


class Clean(clean):
    def run(self):
        self.spawn(["make", "-C", "share/hybrid", "clean"])
        super().run()


commands = {}
extra_data = []
# Build and install gpu-manager on x86.
if "86" in os.uname()[4]:
    commands = {"build": Build, "clean": Clean}
    extra_data.append(("/usr/bin/", ["share/hybrid/gpu-manager"]))
    extra_data.append(
        ("/usr/lib/systemd/system/", ["share/hybrid/gpu-manager.service"])
    )
    extra_data.append(("/usr/sbin/", ["share/hybrid/u-d-c-print-pci-ids"]))
    extra_data.append(
        ("/usr/lib/udev/rules.d/", ["share/hybrid/71-u-d-c-gpu-detection.rules"])
    )

# Make the nvidia-installer hooks executable
# for x in glob.glob("nvidia-installer-hooks/*"):
#    os.chmod(x, 0o755)

setup(
    name="ubuntu-drivers-common",
    author="Alberto Milone",
    author_email="albertomilone@alice.it",
    maintainer="Alberto Milone",
    maintainer_email="albertomilone@alice.it",
    url="http://www.albertomilone.com",
    license="gpl",
    description="Detect and install additional Ubuntu driver packages",
    cmdclass=commands,
    packages=find_packages(include=["Quirks", "UbuntuDrivers", "UbuntuDrivers.*"]),
    data_files=[
        (
            "/usr/share/ubuntu-drivers-common/",
            ["share/obsolete", "share/fake-devices-wrapper"],
        ),
        ("/var/lib/ubuntu-drivers-common/", []),
        ("/usr/share/ubuntu-drivers-common/quirks", glob.glob("quirks/*")),
        ("/usr/share/ubuntu-drivers-common/detect", glob.glob("detect-plugins/*")),
        ("/usr/share/doc/ubuntu-drivers-common", ["README"]),
        ("/usr/lib/nvidia/", glob.glob("nvidia-installer-hooks/*")),
        ("/usr/lib/systemd/system/", ["systemd/ubuntu-drivers.service"]),
        ("/usr/libexec/", ["ubuntu-drivers-dbus-service"]),
        (
            "/usr/share/dbus-1/system-services/",
            ["systemd/com.ubuntu.Drivers.service"],
        ),
        ("/usr/share/dbus-1/system.d/", ["systemd/com.ubuntu.Drivers.conf"]),
    ]
    + extra_data,
    scripts=["quirks-handler", "ubuntu-drivers"],
)
