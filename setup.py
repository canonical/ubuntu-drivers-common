#!/usr/bin/env python

from setuptools import setup

import subprocess, glob, os.path
import os

scripts = ["nvidia-detector", "quirks-handler", "ubuntu-drivers"]
# Build hybrid-detect on x86
if '86' in os.uname()[4]:
    subprocess.check_call(["make", "-C", "share/hybrid", "all"])
    scripts.append("share/hybrid/hybrid-detect")

# Make the nvidia-installer hooks executable
for x in glob.glob("nvidia-installer-hooks/*"):
    os.chmod(x, 0o755)

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
                ("/usr/share/ubuntu-drivers-common/detect", glob.glob("detect-plugins/*")),
                ("/usr/lib/nvidia/", glob.glob("nvidia-installer-hooks/*")),
                ("/usr/lib/ubiquity/target-config", glob.glob("ubiquity/target-config/*")),
               ],
    scripts=scripts,
    entry_points="""[packagekit.apt.plugins]
what_provides=UbuntuDrivers.PackageKit:what_provides_modalias
""",
)
