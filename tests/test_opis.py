from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from iocs.opis.generate_opis import build_rows, render_overview
from iocs.parser import load_narad_description


class PhoebusDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.opi_dir = cls.root / "iocs" / "opis"
        cls.source = cls.root / "yaml-descriptions" / "toy_ring_narad_instance.yaml"
        cls.overview = cls.opi_dir / "toy_ring_overview.bob"
        cls.description = load_narad_description(cls.source)
        cls.signal_ids = {signal.id for signal in cls.description.signals}

    def test_displays_are_valid_xml_with_supported_root(self) -> None:
        displays = sorted(self.opi_dir.rglob("*.bob"))
        self.assertEqual(
            {display.relative_to(self.opi_dir).as_posix() for display in displays},
            {
                "rows/bpm_row.bob",
                "rows/kicker_row.bob",
                "toy_ring_overview.bob",
            },
        )

        for display in displays:
            with self.subTest(display=display.name):
                root = ET.parse(display).getroot()
                self.assertEqual(root.tag, "display")
                self.assertEqual(root.get("version"), "2.0.0")

    def test_checked_overview_matches_current_generator_output(self) -> None:
        self.assertEqual(
            self.overview.read_text(encoding="utf-8"),
            render_overview(build_rows(self.source), self.source),
        )

    def test_embedded_rows_expand_to_every_toy_ring_signal_once(self) -> None:
        root = ET.parse(self.overview).getroot()
        embedded = [
            widget for widget in root.iter("widget") if widget.get("type") == "embedded"
        ]
        self.assertEqual(len(embedded), 384)
        self.assertEqual(
            Counter(widget.findtext("file") for widget in embedded),
            Counter({"rows/bpm_row.bob": 192, "rows/kicker_row.bob": 192}),
        )

        expanded_pvs = []
        for widget in embedded:
            target = widget.findtext("file")
            self.assertIsNotNone(target)
            child_path = self.opi_dir / target
            self.assertTrue(child_path.is_file())
            child = ET.parse(child_path).getroot()
            macros = {element.tag: element.text for element in widget.find("macros")}

            for pv_name in child.iter("pv_name"):
                match = re.fullmatch(r"\$\(([^)]+)\)", pv_name.text or "")
                self.assertIsNotNone(match)
                expanded_pvs.append(macros[match.group(1)])

        self.assertEqual(len(expanded_pvs), 1536)
        self.assertEqual(Counter(expanded_pvs), Counter(self.signal_ids))


if __name__ == "__main__":
    unittest.main()