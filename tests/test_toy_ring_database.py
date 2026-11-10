from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path

from iocs.mapper import map_description
from iocs.models import EpicsRecord
from iocs.parser import load_narad_description
from iocs.renderer import render_database


class ToyRingDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.source = root / "yaml-descriptions" / "toy_ring_narad_instance.yaml"
        cls.artifact = root / "generated" / "toy_ring.db"
        cls.description = load_narad_description(cls.source)
        cls.records = map_description(cls.description)
        cls.record_by_name = {record.name: record for record in cls.records}

    def test_record_inventory_matches_explicit_signals(self) -> None:
        self.assertEqual(len(self.records), sum(signal.record_field is None for signal in self.description.signals))
        self.assertEqual(
            Counter(record.record_type for record in self.records),
            Counter({"ai": 768, "ao": 384, "stringin": 384}),
        )
        self.assertEqual(
            sum(len(record.aliases) for record in self.records),
            sum(self.description.signal_by_id[b.object].record_field is None for b in self.description.bindings),
        )

    def test_representative_records_preserve_mapping_and_binding_metadata(self) -> None:
        self.assertRecord(
            "inst:es12-bpm0:X-RB",
            "ai",
            ("DESC", "Measured horizontal beam position."),
            ("EGU", "mm"),
            ("VAL", "0"),
            ("UDF", "0"),
            alias="inst:ES12_BPM0:horizontal_position_binding",
            binding_id="inst:ES12_BPM0.horizontal_position_binding",
        )
        self.assertRecord(
            "inst:es12-t1:PS:H:Current-SP",
            "ao",
            ("DESC", "Desired magnet current command."),
            ("EGU", "A"),
            ("VAL", "0"),
            ("UDF", "0"),
            alias="inst:ES12_T1:horizontal_current_setpoint_binding",
            binding_id="inst:ES12_T1.horizontal_current_setpoint_binding",
        )
        self.assertRecord(
            "inst:es12-t1:PS:H:Current-RB",
            "ai",
            ("DESC", "Measured magnet current."),
            ("EGU", "A"),
            ("VAL", "0"),
            ("UDF", "0"),
            alias="inst:ES12_T1:horizontal_current_readback_binding",
            binding_id="inst:ES12_T1.horizontal_current_readback_binding",
        )
        self.assertRecord(
            "inst:es12-t1:PS:H:Status",
            "stringin",
            ("DESC", "Power-supply or device state summary."),
            ("VAL", "UNKNOWN"),
            ("UDF", "0"),
            alias="inst:ES12_T1:horizontal_magnet_status_binding",
            binding_id="inst:ES12_T1.horizontal_magnet_status_binding",
        )

    def test_all_current_setpoints_have_simulation_range_defaults(self) -> None:
        setpoints = [r for r in self.records if r.record_type == "ao"]
        self.assertEqual(len(setpoints), 384)
        for record in setpoints:
            self.assertIn(("DRVL", "-50"), record.fields)
            self.assertIn(("DRVH", "50"), record.fields)
            self.assertNotIn(".", record.name)
            for field in ("DRVL", "DRVH"):
                self.assertIn((f"narad{field}SignalId", f"{record.name}.{field}"), record.info_items)

    def test_checked_database_matches_current_renderer_output(self) -> None:
        self.assertTrue(self.artifact.is_file(), "generate generated/toy_ring.db")
        self.assertEqual(
            self.artifact.read_text(encoding="utf-8"),
            render_database(self.records, source=self.source),
        )

    def assertRecord(
        self,
        name: str,
        record_type: str,
        *fields: tuple[str, str],
        alias: str,
        binding_id: str,
    ) -> None:
        record: EpicsRecord = self.record_by_name[name]
        self.assertEqual(record.record_type, record_type)
        for field in fields:
            self.assertIn(field, record.fields)
        self.assertIn(alias, record.aliases)
        self.assertIn(("naradBindingId0", binding_id), record.info_items)


if __name__ == "__main__":
    unittest.main()