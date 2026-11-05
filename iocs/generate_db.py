"""Command-line orchestration for Narad-to-EPICS database generation.

The command composes the package APIs without adding mapping behavior. Use
``--check`` to run parsing and mapping without writing a database.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .errors import NaradValidationError
from .mapper import map_description
from .parser import load_narad_description
from .renderer import render_database, write_database


def main(arguments: Sequence[str] | None = None) -> int:
    """Run validation or generation and return a process-style status code."""

    parser = _argument_parser()
    options = parser.parse_args(arguments)
    if not options.check and options.output is None:
        parser.error("--output is required unless --check is used")

    try:
        description = load_narad_description(options.input)
        records = map_description(description)
        if options.check:
            print(
                f"Valid: {len(description.signals)} signals, "
                f"{len(description.bindings)} bindings, {len(records)} records"
            )
            return 0

        content = render_database(records, source=description.source)
        destination = write_database(options.output, content)
    except (NaradValidationError, OSError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Generated {len(records)} records in {destination}")
    return 0


def _argument_parser() -> argparse.ArgumentParser:
    """Build the CLI parser shared by the console script and module entry."""

    parser = argparse.ArgumentParser(
        description="Translate explicit Narad signals into an EPICS database."
    )
    parser.add_argument("input", type=Path, help="Narad YAML description")
    parser.add_argument("--output", "-o", type=Path, help="destination .db file")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and map the input without writing a database",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())