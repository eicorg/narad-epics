"""Public API for translating Narad descriptions into EPICS databases.

Typical use follows ``load_narad_description`` -> ``map_description`` ->
``render_database``. The parser owns validation, models carry immutable data,
and the renderer has no knowledge of the source YAML schema.
"""

from .errors import NaradValidationError, ValidationIssue
from .mapper import map_description
from .models import EpicsRecord, NaradDescription, NaradSignal, SignalBinding
from .parser import load_narad_description
from .renderer import render_database, write_database

__all__ = [
    "EpicsRecord",
    "NaradDescription",
    "NaradSignal",
    "NaradValidationError",
    "SignalBinding",
    "ValidationIssue",
    "load_narad_description",
    "map_description",
    "render_database",
    "write_database",
]