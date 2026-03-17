"""Compatibility package that aliases legacy imports to app."""

from app import *  # noqa: F401,F403
from app import __path__ as _app_path

__path__ = list(_app_path)
