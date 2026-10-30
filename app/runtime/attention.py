"""Compatibility import; implementation belongs to app.runtime.policy.attention."""

from importlib import import_module as _import_module
from sys import modules as _modules

_modules[__name__] = _import_module(".policy.attention", __package__)
