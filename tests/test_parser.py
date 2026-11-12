from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from iocs.errors import NaradValidationError
from iocs.parser import load_narad_description


VALID_DESCRIPTION = """
kind: PALSAccelerator
facility:
  components:
  - id: inst:BPM1
    kind: BeamPositionMonitor
  signals:
  - id: inst:bpm1:X-RB
    kind: Signal
    alias:
    - horizontal_position
    signal_role: Readback
    source_system: EPICS
    native_description: Measured horizontal beam position.
    canonical_signal_type: HorizontalBeamPosition
    quantity_kind: BeamPosition
    native_data_type: Float
    native_unit: mm
    access_protocol: EPICS PVAccess
  signal_bindings:
  - id: inst:BPM1.horizontal_position_binding
    subject: inst:BPM1
    predicate: pals:has_readback_signal
    object: inst:bpm1:X-RB
"""


class ParserTests(unittest.TestCase):
    def write_description(self, content: str) -> Path:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        path = Path(temporary_directory.name) / "description.yaml"
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        return path

    def test_loads_typed_signals_and_bindings(self) -> None:
        path = self.write_description(VALID_DESCRIPTION)

        description = load_narad_description(path)

        self.assertEqual(description.source, path.resolve())
        self.assertEqual(description.component_ids, frozenset({"inst:BPM1"}))
        self.assertEqual(len(description.signals), 1)
        self.assertEqual(len(description.bindings), 1)
        signal = description.signal_by_id["inst:bpm1:X-RB"]
        self.assertEqual(signal.aliases, ("horizontal_position",))
        self.assertEqual(signal.native_data_type, "Float")
        binding = description.bindings[0]
        self.assertEqual(binding.subject, "inst:BPM1")
        self.assertEqual(binding.object, signal.id)

    def test_reports_cross_reference_and_role_errors_together(self) -> None:
        invalid_description = VALID_DESCRIPTION.replace(
            "subject: inst:BPM1", "subject: inst:MISSING"
        ).replace(
            "predicate: pals:has_readback_signal",
            "predicate: pals:has_setpoint_signal",
        )
        invalid_description += """
  - id: inst:BPM1.missing_signal_binding
    subject: inst:BPM1
    predicate: pals:has_readback_signal
    object: inst:missing:X-RB
"""
        path = self.write_description(invalid_description)

        with self.assertRaises(NaradValidationError) as raised:
            load_narad_description(path)

        message = str(raised.exception)
        self.assertIn("inst:MISSING", message)
        self.assertIn("inst:missing:X-RB", message)
        self.assertIn("has_setpoint_signal", message)
        self.assertGreaterEqual(len(raised.exception.issues), 3)

    def test_rejects_duplicate_signal_ids(self) -> None:
        duplicate = textwrap.dedent(VALID_DESCRIPTION).replace(
            "  signal_bindings:",
            textwrap.dedent(VALID_DESCRIPTION).split("  signals:\n", 1)[1].split(
                "  signal_bindings:\n", 1
            )[0]
            + "  signal_bindings:",
        )
        path = self.write_description(duplicate)

        with self.assertRaisesRegex(NaradValidationError, "duplicate signal ID"):
            load_narad_description(path)

    def test_rejects_alias_collisions_after_normalization(self) -> None:
        second_binding = """
  - id: inst:BPM1:horizontal_position_binding
    subject: inst:BPM1
    predicate: pals:has_readback_signal
    object: inst:bpm1:X-RB
"""
        path = self.write_description(VALID_DESCRIPTION + second_binding)

        with self.assertRaisesRegex(NaradValidationError, "alias collision"):
            load_narad_description(path)

    def test_loads_reference_toy_ring(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "yaml-descriptions"
            / "toy_ring_narad_instance.yaml"
        )

        description = load_narad_description(source)

        self.assertEqual(len(description.signals), 2304)
        self.assertEqual(len(description.bindings), 2304)
        self.assertEqual(
            description.signal_by_id["inst:es12-bpm0:X-RB"].native_unit,
            "mm",
        )
        binding = next(
            binding
            for binding in description.bindings
            if binding.id == "inst:ES12_BPM0.horizontal_position_binding"
        )
        self.assertEqual(binding.object, "inst:es12-bpm0:X-RB")


if __name__ == "__main__":
    unittest.main()