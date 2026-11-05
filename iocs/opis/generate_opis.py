"""Generate a Phoebus overview from signal-bearing Narad components.

Each component becomes an Embedded Display that supplies exact PV names as
macros to a reusable row display selected by component kind.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

from iocs.parser import load_narad_description
from iocs.renderer import write_database


ROW_HEIGHT = 44
CONTENT_WIDTH = 1160
COLUMN_HEADINGS = (
    ("Component", "Component", 30, 200, 0),
    ("Type", "Type", 235, 130, 0),
    ("Horizontal Status", "H / X status", 370, 120, 1),
    ("Horizontal Setpoint", "H setpoint", 495, 130, 1),
    ("Horizontal Readback", "H readback", 630, 130, 1),
    ("Vertical Status", "V / Y status", 770, 120, 1),
    ("Vertical Setpoint", "V setpoint", 895, 130, 1),
    ("Vertical Readback", "V readback", 1030, 130, 1),
)
SUPPORTED_COMPONENTS = {
    "BeamPositionMonitor": (
        "rows/bpm_row.bob",
        {
            "X_PV": ":X-RB",
            "Y_PV": ":Y-RB",
        },
    ),
    "Kicker": (
        "rows/kicker_row.bob",
        {
            "H_STATUS_PV": ":PS:H:Status",
            "H_SETPOINT_PV": ":PS:H:Current-SP",
            "H_READBACK_PV": ":PS:H:Current-RB",
            "V_STATUS_PV": ":PS:V:Status",
            "V_SETPOINT_PV": ":PS:V:Current-SP",
            "V_READBACK_PV": ":PS:V:Current-RB",
        },
    ),
}


@dataclass(frozen=True)
class EmbeddedRow:
    """One reusable child display plus the macros for a component instance."""

    component_id: str
    component_kind: str
    child_display: str
    macros: tuple[tuple[str, str], ...]


def build_rows(source: Path) -> tuple[EmbeddedRow, ...]:
    """Build source-ordered embedded rows for all signal-bearing components.

    Unsupported component kinds or incomplete expected signal sets raise
    ``ValueError`` rather than generating a partially wired display.
    """

    description = load_narad_description(source)
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    component_kinds = {
        component["id"]: component["kind"]
        for component in raw["facility"]["components"]
    }
    signals_by_component: dict[str, list[str]] = defaultdict(list)
    for binding in description.bindings:
        signals_by_component[binding.subject].append(binding.object)

    rows = []
    for component_id, signal_ids in signals_by_component.items():
        component_kind = component_kinds[component_id]
        try:
            child_display, macro_suffixes = SUPPORTED_COMPONENTS[component_kind]
        except KeyError as error:
            raise ValueError(
                f"no Phoebus row display for component kind {component_kind!r}"
            ) from error

        signal_by_suffix = {
            suffix: next(
                (signal_id for signal_id in signal_ids if signal_id.endswith(suffix)),
                None,
            )
            for suffix in macro_suffixes.values()
        }
        missing = [
            suffix for suffix, signal_id in signal_by_suffix.items() if signal_id is None
        ]
        if missing:
            raise ValueError(
                f"{component_id} is missing expected signals: {', '.join(missing)}"
            )

        macros = (
            ("COMPONENT", component_id.removeprefix("inst:")),
            ("KIND", component_kind),
            *(
                (macro_name, signal_by_suffix[suffix])
                for macro_name, suffix in macro_suffixes.items()
            ),
        )
        rows.append(
            EmbeddedRow(
                component_id=component_id,
                component_kind=component_kind,
                child_display=child_display,
                macros=macros,
            )
        )

    return tuple(rows)


def render_overview(rows: tuple[EmbeddedRow, ...], source: Path) -> str:
    """Render embedded rows as a deterministic Phoebus ``.bob`` document."""

    header_height = 112
    display_height = header_height + len(rows) * ROW_HEIGHT + 20
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<display version="2.0.0">',
        "  <name>EIC Toy Ring Components</name>",
        f"  <width>{CONTENT_WIDTH + 40}</width>",
        f"  <height>{display_height}</height>",
        "  <background_color>",
        '    <color red="239" green="243" blue="245">',
        "    </color>",
        "  </background_color>",
        '  <widget type="label" version="2.0.0">',
        "    <name>Title</name>",
        "    <text>EIC Toy Ring Components</text>",
        "    <x>20</x>",
        "    <y>14</y>",
        f"    <width>{CONTENT_WIDTH}</width>",
        "    <height>42</height>",
        "    <font>",
        '      <font family="Liberation Sans" style="BOLD" size="25.0">',
        "      </font>",
        "    </font>",
        "    <transparent>true</transparent>",
        "  </widget>",
        '  <widget type="label" version="2.0.0">',
        "    <name>Source</name>",
        f"    <text>Generated from {escape(source.name)}</text>",
        "    <x>22</x>",
        "    <y>54</y>",
        "    <width>700</width>",
        "    <height>24</height>",
        "    <transparent>true</transparent>",
        "  </widget>",
    ]

    for name, text, x_position, width, alignment in COLUMN_HEADINGS:
        lines.extend(
            [
                '  <widget type="label" version="2.0.0">',
                f"    <name>{name} Heading</name>",
                f"    <text>{text}</text>",
                f"    <x>{x_position}</x>",
                "    <y>82</y>",
                f"    <width>{width}</width>",
                "    <height>26</height>",
                "    <font>",
                '      <font family="Liberation Sans" style="BOLD" size="13.0">',
                "      </font>",
                "    </font>",
                f"    <horizontal_alignment>{alignment}</horizontal_alignment>",
                "    <transparent>true</transparent>",
                "  </widget>",
            ]
        )

    for index, row in enumerate(rows):
        y_position = header_height + index * ROW_HEIGHT
        lines.extend(
            [
                '  <widget type="embedded" version="2.0.0">',
                f"    <name>{escape(row.component_id)} row</name>",
                "    <macros>",
            ]
        )
        for macro_name, macro_value in row.macros:
            lines.append(f"      <{macro_name}>{escape(macro_value)}</{macro_name}>")
        lines.extend(
            [
                "    </macros>",
                f"    <file>{row.child_display}</file>",
                "    <x>20</x>",
                f"    <y>{y_position}</y>",
                f"    <width>{CONTENT_WIDTH}</width>",
                f"    <height>{ROW_HEIGHT}</height>",
                "    <resize>2</resize>",
                "    <transparent>true</transparent>",
                "  </widget>",
            ]
        )

    lines.append("</display>")
    return "\n".join(lines) + "\n"


def generate_overview(source: Path, output: Path) -> int:
    """Build and atomically write an overview, returning its row count."""

    rows = build_rows(source)
    write_database(output, render_overview(rows, source))
    return len(rows)


def main(arguments: list[str] | None = None) -> int:
    """Run the OPI generator CLI and return a process-style status code."""

    parser = argparse.ArgumentParser(
        description="Generate a macro-driven Phoebus component overview."
    )
    parser.add_argument("source", type=Path, help="Narad YAML description")
    parser.add_argument("--output", "-o", required=True, type=Path)
    options = parser.parse_args(arguments)

    try:
        count = generate_overview(options.source.resolve(), options.output.resolve())
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(f"Generated {count} embedded component rows in {options.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())