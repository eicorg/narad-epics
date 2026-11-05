from pathlib import Path
import unittest

from iocs.pva_bridge import (
    ModelService,
    ModelSignal,
    forward_setpoint,
    load_mapping,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeSubscription:
    def close(self):
        pass


class FakeContext:
    def __init__(self):
        self.callbacks = {}
        self.puts = []
        self.closed = False

    def get(self, names, *, timeout):
        return [0.0] * len(names)

    def monitor(self, name, callback, *, notify_disconnect):
        self.callbacks[name] = callback
        return FakeSubscription()

    def put(self, names, values, *, timeout, wait):
        self.puts.append((names, values))

    def close(self):
        self.closed = True


class FakeModel:
    def __init__(self, values):
        self.values = values
        self.sets = []

    def list_pvs(self):
        return {"values": list(self.values)}

    def get(self, pv):
        return self.values[pv]

    def set(self, pv, value):
        self.sets.append((pv, value))
        self.values[pv] = value
        return value


class PVABridgeTests(unittest.TestCase):
    def test_reference_signal_inventory_and_units(self):
        setpoints, readbacks = load_mapping(
            ROOT / "yaml-descriptions/toy_ring_narad_instance.yaml"
        )
        self.assertEqual(len(setpoints), 384)
        self.assertEqual(len(readbacks), 768)
        by_name = {signal.pv: signal for signal in setpoints + readbacks}
        self.assertEqual(
            by_name["inst:es12-t1:PS:V:Current-SP"].key,
            "steering_v:i_es12_t1",
        )
        self.assertEqual(
            by_name["inst:es12-t1:PS:H:Current-RB"].scale,
            1.0,
        )
        self.assertEqual(
            by_name["inst:es12-bpm0:X-RB"],
            ModelSignal("inst:es12-bpm0:X-RB", "es12_bpm0:x", 1000.0),
        )
        self.assertFalse(
            any(":Status" in signal.pv for signal in setpoints + readbacks)
        )

    def test_confirmed_current_and_bpm_conversion_after_set(self):
        context = FakeContext()
        model = FakeModel(
            {"steering_h:i_es12_t1": 0.0, "es12_bpm0:x": -0.002}
        )
        readbacks = [
            ModelSignal("current", "steering_h:i_es12_t1"),
            ModelSignal("bpm", "es12_bpm0:x", 1000.0),
        ]
        forward_setpoint(
            model,
            ModelSignal("setpoint", "steering_h:i_es12_t1"),
            0.25,
            readbacks,
            context,
            5.0,
        )
        self.assertEqual(model.sets, [("steering_h:i_es12_t1", 0.25)])
        self.assertEqual(context.puts, [(["current", "bpm"], [0.25, -2.0])])

    def test_failed_set_does_not_publish_readbacks(self):
        class FailingModel(FakeModel):
            def set(self, pv, value):
                raise RuntimeError("rejected")

        context = FakeContext()
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            forward_setpoint(
                FailingModel({"key": 0.0}),
                ModelSignal("sp", "key"),
                1.0,
                [ModelSignal("rb", "key")],
                context,
                5.0,
            )
        self.assertEqual(context.puts, [])

    def test_monitor_update_runs_on_worker_and_publishes_with_p4p(self):
        model = FakeModel({"current": 0.0})
        context = FakeContext()
        service = ModelService(
            model,
            context,
            [ModelSignal("sp", "current")],
            [ModelSignal("rb", "current")],
        )
        try:
            service.start()
            context.callbacks["sp"](0.0)
            context.callbacks["sp"](0.5)
            service.wait_for_idle()
        finally:
            service.close()

        self.assertEqual(model.sets, [("current", 0.5)])
        self.assertEqual(context.puts, [(["rb"], [0.5])])
        self.assertTrue(context.closed)


if __name__ == "__main__":
    unittest.main()