"""Compatibility import; implementation belongs to app.runtime.policy.proactive."""

from importlib import import_module as _import_module
from sys import modules as _modules

_modules[__name__] = _import_module(".policy.proactive", __package__)
