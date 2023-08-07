"""
The unittest integration traces test executions.


Enabling
~~~~~~~~

The unittest integration is enabled automatically when using
:ref:`ddtrace-run<ddtracerun>` or :func:`patch_all()<ddtrace.patch_all>`.

Or use :func:`patch()<ddtrace.patch>` to manually enable the integration::

    from ddtrace import patch
    patch(unittest=True)
"""

from unittest import TestCase

from ddtrace import config
from .patch import patch, unpatch

__all__ = ["patch", "unpatch", "TestCase"]

if config.get_from("_ci_visibility_unittest_enabled"):
    patch()