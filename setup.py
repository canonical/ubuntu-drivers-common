#!/usr/bin/env python

from setuptools import setup

import subprocess, glob, os.path
import os

#mo_files = []
## HACK: make sure that the mo files are generated and up-to-date
#subprocess.call(["make", "-C", "po", "build-mo"])
#for filepath in glob.glob("po/mo/*/LC_MESSAGES/*.mo"):
#    lang = filepath[len("po/mo/"):]
#    targetpath = os.path.dirname(os.path.join("share/locale",lang))
#    mo_files.append((targetpath, [filepath]))

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
    scripts=["nvidia-detector", "quirks-handler", "share/hybrid/hybrid-detect"],
    entry_points="""[packagekit.apt.plugins]
what_provides=UbuntuDrivers.packagekit_plugin:what_provides_modalias
""",
)
