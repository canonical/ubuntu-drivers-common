"""Exercise the native build and clean steps without requiring GPU libraries."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

# Run the real setup command while selecting an architecture for the test.
SETUP_LAUNCHER = """
import os
import runpy
import sys

uname = os.uname()
machine = sys.argv.pop(1)
os.uname = lambda: os.uname_result((*uname[:4], machine))
sys.argv[0] = "setup.py"
runpy.run_path("setup.py", run_name="__main__")
"""


class TestSetup(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = Path(__file__).resolve().parents[1]
        for filename in ("setup.py", "quirks-handler", "ubuntu-drivers"):
            shutil.copy(source / filename, self.root)

        self.gpu_manager = self.root / "share/hybrid/gpu-manager"
        self.gpu_manager.parent.mkdir(parents=True)

        make = self.root / "bin/make"
        make.parent.mkdir()
        make.write_text(
            """#!/bin/sh
set -eu
printf '%s\n' "$3" >> make-calls
case "$3" in
    all) touch "$2/gpu-manager" ;;
    clean) rm -f "$2/gpu-manager" ;;
    *) exit 1 ;;
esac
""",
            encoding="utf-8",
        )
        make.chmod(0o755)
        self.environment = {
            **os.environ,
            "PATH": os.pathsep.join((str(make.parent), os.environ["PATH"])),
        }

    def run_setup(self, machine, *args):
        result = subprocess.run(
            [sys.executable, "-c", SETUP_LAUNCHER, machine, *args],
            cwd=self.root,
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def make_calls(self):
        path = self.root / "make-calls"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def test_x86_metadata_does_not_run_make(self):
        for args in (("--name",), ("--help",), ("egg_info",)):
            with self.subTest(args=args):
                self.run_setup("x86_64", *args)
                self.assertEqual(self.make_calls(), [])
                self.assertFalse(self.gpu_manager.exists())

    def test_x86_clean_removes_gpu_manager_without_building(self):
        self.gpu_manager.touch()
        self.run_setup("x86_64", "clean", "--all")
        self.assertEqual(self.make_calls(), ["clean"])
        self.assertFalse(self.gpu_manager.exists())

    def test_x86_build_runs_make(self):
        self.run_setup("x86_64", "build")
        self.assertEqual(self.make_calls(), ["all"])
        self.assertTrue(self.gpu_manager.is_file())

    def test_non_x86_build_and_clean_do_not_run_make(self):
        self.run_setup("aarch64", "build", "clean")
        self.assertEqual(self.make_calls(), [])
        self.assertFalse(self.gpu_manager.exists())
