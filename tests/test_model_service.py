from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from iocs.parser import load_narad_description
from models.pv_model import RingModel
from models.service import ModelService


class FakeTao:
    def __init__(
        self,
        *,
        correctors: tuple[str, ...] = ("ES12_T1",),
        bpms: tuple[str, ...] = ("ES12_BPM0",),
    ) -> None:
        self.controls = {
            "steering_h": dict.fromkeys(correctors, 0.0),
            "steering_v": dict.fromkeys(correctors, 0.0),
            "quad_families": {},
            "sext_families": {},
        }
        self.bpms = bpms
        self.commands: list[str] = []

    def ele_control_var(self, overlay: str) -> dict[str, float]:
        return self.controls[overlay]

    def lat_list(self, name: str, field: str) -> list[str] | list[float]:
        if field == "ele.name":
            return list(self.bpms)
        component = int(field.rsplit(".", 1)[1])
        horizontal = sum(self.controls["steering_h"].values()) * 0.001
        vertical = sum(self.controls["steering_v"].values()) * 0.001
        value = horizontal if component == 1 else vertical
        return [value] * len(self.bpms)

    def cmd(self, command: str) -> None:
        self._apply(command)

    def cmds(self, commands: list[str]) -> None:
        for command in commands:
            self._apply(command)

    def _apply(self, command: str) -> None:
        self.commands.append(command)
        _, _, overlay, variable, _, value = command.split()
        self.controls[overlay][variable] = float(value)


class FakeSubscription:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self, initial: Mapping[str, float]) -> None:
        self.initial = initial
        self.callbacks: dict[str, Any] = {}
        self.subscriptions: list[FakeSubscription] = []
        self.puts: list[dict[str, float | str]] = []
        self.closed = False

    def get(self, names: list[str], *, timeout: float) -> list[float]:
        return [self.initial[name] for name in names]

    def monitor(
        self, name: str, callback: Any, *, notify_disconnect: bool
    ) -> FakeSubscription:
        self.callbacks[name] = callback
        subscription = FakeSubscription()
        self.subscriptions.append(subscription)
        return subscription

    def put(
        self,
        names: list[str],
        values: list[float | str],
        *,
        timeout: float,
        wait: bool,
    ) -> None:
        self.puts.append(dict(zip(names, values, strict=True)))

    def close(self) -> None:
        self.closed = True

    def emit(self, pv: str, value: float | Exception) -> None:
        self.callbacks[pv](value)


class RingModelTests(unittest.TestCase):
    def test_maps_tao_names_to_exact_epics_pvs(self) -> None:
        model = RingModel(tao=FakeTao())

        self.assertEqual(
            model.setpoint_pvs,
            (
                "inst:es12-t1:PS:H:Current-SP",
                "inst:es12-t1:PS:V:Current-SP",
            ),
        )
        model.apply_setpoint("inst:es12-t1:PS:H:Current-SP", 2.5)
        self.assertEqual(
            model.readbacks("inst:es12-t1:PS:H:Current-SP"),
            {
                "inst:es12-t1:PS:H:Current-RB": 2.5,
                "inst:es12-bpm0:X-RB": 0.0025,
                "inst:es12-bpm0:Y-RB": 0.0,
            },
        )

    def test_maps_complete_toy_ring_signal_inventory(self) -> None:
        root = Path(__file__).resolve().parents[1]
        description = load_narad_description(
            root / "yaml-descriptions" / "toy_ring_narad_instance.yaml"
        )
        correctors = {
            binding.subject.removeprefix("inst:")
            for binding in description.bindings
            if description.signal_by_id[binding.object].signal_role == "Setpoint"
        }
        bpms = {
            binding.subject.removeprefix("inst:")
            for binding in description.bindings
            if description.signal_by_id[binding.object].native_unit == "mm"
        }
        model = RingModel(
            tao=FakeTao(
                correctors=tuple(sorted(correctors)),
                bpms=tuple(sorted(bpms)),
            )
        )

        expected_setpoints = {
            signal.id
            for signal in description.signals
            if signal.signal_role == "Setpoint"
        }
        expected_outputs = {
            signal.id
            for signal in description.signals
            if signal.signal_role in {"Readback", "Status"}
        }
        self.assertEqual(set(model.setpoint_pvs), expected_setpoints)
        self.assertEqual(set(model.readbacks()), expected_outputs)


class ModelServiceTests(unittest.TestCase):
    def test_syncs_startup_then_processes_changed_setpoints(self) -> None:
        model = RingModel(tao=FakeTao())
        context = FakeContext(
            {
                "inst:es12-t1:PS:H:Current-SP": 1.0,
                "inst:es12-t1:PS:V:Current-SP": -2.0,
            }
        )
        service = ModelService(model, context)

        service.start()
        self.assertEqual(len(context.callbacks), 2)
        self.assertEqual(
            context.puts[0],
            {
                "inst:es12-t1:PS:H:Status": "READY",
                "inst:es12-t1:PS:V:Status": "READY",
                "inst:es12-t1:PS:H:Current-RB": 1.0,
                "inst:es12-t1:PS:V:Current-RB": -2.0,
                "inst:es12-bpm0:X-RB": 0.001,
                "inst:es12-bpm0:Y-RB": -0.002,
            },
        )

        context.emit("inst:es12-t1:PS:H:Current-SP", 3.0)
        service.wait_for_idle()
        self.assertEqual(
            context.puts[-1],
            {
                "inst:es12-t1:PS:H:Current-RB": 3.0,
                "inst:es12-bpm0:X-RB": 0.003,
                "inst:es12-bpm0:Y-RB": -0.002,
            },
        )

        put_count = len(context.puts)
        context.emit("inst:es12-t1:PS:H:Current-SP", 3.0)
        service.wait_for_idle()
        self.assertEqual(len(context.puts), put_count)

        service.close()
        self.assertTrue(context.closed)
        self.assertTrue(all(item.closed for item in context.subscriptions))


if __name__ == "__main__":
    unittest.main()