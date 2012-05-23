#!/usr/bin/env python

from setuptools import setup

import subprocess, glob, os.path
import os

# Build hybrid-detect
subprocess.call(["make", "-C", "share/hybrid", "all"])

# Make the nvidia-installer hooks executable
for x in glob.glob("nvidia-installer-hooks/*"):
    os.chmod(x, 0755)

setup(
    name="ubuntu-drivers-common",
    author="Alberto Milone",
    author_email="albertomilone@alice.it",
    maintainer="Alberto Milone",
    maintainer_email="albertomilone@alice.it",
    url="http://www.albertomilone.com",
    license="gpl",
    description="Detect and install additional Ubuntu driver packages",
    packages=["NvidiaDetector", "Quirks", "UbuntuDrivers"],
    data_files=[("/usr/share/ubuntu-drivers-common/", glob.glob("share/obsolete")),
                ("/var/lib/ubuntu-drivers-common/", glob.glob("share/last_gfx_boot")),
                ("/etc/init/", glob.glob("share/hybrid/hybrid-gfx.conf")),
                ("/usr/share/ubuntu-drivers-common/quirks", glob.glob("quirks/*")),
                ("/usr/lib/nvidia/", glob.glob("nvidia-installer-hooks/*")),
               ],# + mo_files,
    scripts=["nvidia-detector", "quirks-handler", "share/hybrid/hybrid-detect",
             "ubuntu-drivers"],
    entry_points="""[packagekit.apt.plugins]
what_provides=UbuntuDrivers.PackageKit:what_provides_modalias
""",
)
