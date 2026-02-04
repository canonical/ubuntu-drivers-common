#! /usr/bin/python

# Copyright (C) 2013-2019 Canonical Ltd.
# Author: Colin Watson <cjwatson@ubuntu.com>
#         Jean-Baptiste Lallement <jean-baptiste@ubuntu.com>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Test compliance with various static analysis tools."""

from __future__ import print_function

import os
import re
import subprocess
import sys
import unittest

pycodestyle_cmd = "pycodestyle"
if sys.version < "3":
    pyflakes_cmd = "pyflakes"
else:
    pyflakes_cmd = "pyflakes3"

PEP8_MAX_LINE_LENGTH = 120


def find_on_path(command):
    """Is command on the executable search path?"""
    if "PATH" not in os.environ:
        return False
    path = os.environ["PATH"]
    for element in path.split(os.pathsep):
        if not element:
            continue
        filename = os.path.join(element, command)
        if os.path.isfile(filename) and os.access(filename, os.X_OK):
            return True
    return False


class TestStatic(unittest.TestCase):
    def all_paths(self):
        """Returns a list of python files of the project"""

        ignore_dirs = [
            ".bzr",
            ".git",
            "__pycache__",
            "debian",
            # Project dirs ignored for the moment
            "Quirks",
        ]
        # List of files to ignore with ../ stripped from the beginning of the path
        ignore_files = [
            "settings.py",
            "setup.py",
            # Project files ignores for the moment
            "tests/gpu-manager.py",
        ]

        paths = []
        basedir = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
        for dirpath, dirnames, filenames in os.walk(basedir):
            dirpath = dirpath.replace(basedir, "")
            for ignore in ignore_dirs:
                if ignore in dirnames:
                    dirnames.remove(ignore)
            filenames = [
                n for n in filenames if not n.startswith(".") and not n.endswith("~")
            ]
            for filename in filenames:
                filepath = os.path.join(dirpath, filename).lstrip("/")
                if filepath.endswith(".py") and filepath not in ignore_files:
                    paths.append(filepath)
        return paths

    @unittest.skipUnless(
        find_on_path(pycodestyle_cmd), "%s not found on this system" % pycodestyle_cmd
    )
    def test_pycodestyle_clean(self):
        """pycodestyle - Python style guide checker"""

        subp = subprocess.Popen(
            [pycodestyle_cmd, "--max-line-length=%d" % PEP8_MAX_LINE_LENGTH]
            + self.all_paths(),
            stdout=subprocess.PIPE,
            universal_newlines=True,
        )
        output = subp.communicate()[0].splitlines()
        for line in output:
            print(line)
        self.assertEqual(0, len(output))

    @unittest.skipUnless(
        find_on_path(pyflakes_cmd), "%s not found on this system" % pyflakes_cmd
    )
    def test_pyflakes_clean(self):
        """pyflakes passive checker"""
        # Exclude handling based on run-pyflakes.py from reviewboard,
        # licensed under the MIT License.
        cur_dir = os.path.dirname(__file__)
        exclusions_path = os.path.join(cur_dir, "%s.exclude" % pyflakes_cmd)
        exclusions = set()
        if os.path.exists(exclusions_path):
            with open(exclusions_path, "r") as f:
                for line in f:
                    if not line.startswith("#"):
                        exclusions.add(line.rstrip())

        error = False
        subp = subprocess.Popen(
            [pyflakes_cmd] + self.all_paths(),
            stdout=subprocess.PIPE,
            universal_newlines=True,
        )
        output = subp.communicate()[0].splitlines()
        for line in output:
            if line.startswith("#"):
                continue
            line = line.rstrip()
            canon_line = re.sub(r":[0-9]+:", ":*:", line, 1)
            canon_line = re.sub(r"line [0-9]+", "line *", canon_line)
            if canon_line not in exclusions:
                print(line)
                error = True

        self.assertFalse(error)
