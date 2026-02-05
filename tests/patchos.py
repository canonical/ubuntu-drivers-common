import runpy
import sys

_real_os = __import__("os")


class FakeOS:
    def __getattr__(self, name):
        if name == "geteuid":
            return lambda: 0
        return getattr(_real_os, name)


sys.modules["os"] = FakeOS()
sys.argv.pop(0)
runpy.run_path("ubuntu-drivers", run_name="__main__")
