"""bcgacha: Battle Cats capsule automation for a USB-attached iPhone or iPad."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bcgacha")
except PackageNotFoundError:  # run from a source tree that was never installed
    __version__ = "unknown"
