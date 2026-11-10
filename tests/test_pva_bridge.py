from pathlib import Path
import unittest
from unittest.mock import patch
import math
import random
import threading

from iocs.pva_bridge import (
    MachineService,
    MachineSignal,
    forward_setpoint,
    load_mapping,
    publish_readbacks,
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


class FakeMachine:
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
            MachineSignal("inst:es12-bpm0:X-RB", "es12_bpm0:x", 1000.0, 0.1),
        )
        self.assertTrue(all(s.noise_rms == 0.0 for s in setpoints))
        currents = [s for s in readbacks if s.scale == 1.0]
        bpms = [s for s in readbacks if s.scale == 1000.0]
        self.assertEqual(len(currents), 384)
        self.assertEqual(len(bpms), 384)
        self.assertTrue(all(s.noise_rms == 0.01 for s in currents))
        self.assertTrue(all(s.noise_rms == 0.1 for s in bpms))
        self.assertFalse(
            any(":Status" in signal.pv or "." in signal.pv for signal in setpoints + readbacks)
        )

    def test_confirmed_current_and_bpm_conversion_after_set(self):
        context = FakeContext()
        machine = FakeMachine(
            {"steering_h:i_es12_t1": 0.0, "es12_bpm0:x": -0.002}
        )
        readbacks = [
            MachineSignal("current", "steering_h:i_es12_t1"),
            MachineSignal("bpm", "es12_bpm0:x", 1000.0),
        ]
        forward_setpoint(
            machine,
            MachineSignal("setpoint", "steering_h:i_es12_t1"),
            0.25,
            readbacks,
            context,
            5.0,
        )
        self.assertEqual(machine.sets, [("steering_h:i_es12_t1", 0.25)])
        self.assertEqual(context.puts, [(["current", "bpm"], [0.25, -2.0])])

    def test_failed_set_does_not_publish_readbacks(self):
        class FailingMachine(FakeMachine):
            def set(self, pv, value):
                raise RuntimeError("rejected")

        context = FakeContext()
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            forward_setpoint(
                FailingMachine({"key": 0.0}),
                MachineSignal("sp", "key"),
                1.0,
                [MachineSignal("rb", "key")],
                context,
                5.0,
            )
        self.assertEqual(context.puts, [])

    def test_monitor_update_runs_on_worker_and_publishes_with_p4p(self):
        machine = FakeMachine({"current": 0.0})
        context = FakeContext()
        service = MachineService(
            machine,
            context,
            [MachineSignal("sp", "current")],
            [MachineSignal("rb", "current")],
        )
        try:
            service.start()
            context.callbacks["sp"](0.0)
            context.callbacks["sp"](0.5)
            service.wait_for_idle()
        finally:
            service.close()

        self.assertEqual(machine.sets, [("current", 0.5)])
        self.assertEqual(context.puts, [(["rb"], [0.5])])
        self.assertTrue(context.closed)

    def test_noise_is_added_after_conversion_without_changing_machine(self):
        machine = FakeMachine({'current': 0.25, 'bpm': -0.002})
        context = FakeContext()
        signals = [MachineSignal('current-rb', 'current', noise_rms=0.01),
                   MachineSignal('bpm-rb', 'bpm', 1000.0, 0.1)]
        with patch('iocs.pva_bridge.random.gauss', side_effect=[0.005, -0.025]) as noise:
            publish_readbacks(machine, signals, context, 5.0)
        self.assertEqual(context.puts, [(['current-rb', 'bpm-rb'], [0.255, -2.025])])
        self.assertEqual(noise.call_args_list, [unittest.mock.call(0.0, 0.01),
                                               unittest.mock.call(0.0, 0.1)])
        self.assertEqual(machine.values, {'current': 0.25, 'bpm': -0.002})
        self.assertEqual(machine.sets, [])

    def test_noise_mean_and_rms(self):
        machine = FakeMachine({'current': 0.25, 'bpm': -0.002})
        context = FakeContext()
        signals = [MachineSignal('current-rb', 'current', noise_rms=0.01),
                   MachineSignal('bpm-rb', 'bpm', 1000.0, 0.1)]
        samples = [[], []]
        with patch('iocs.pva_bridge.random.gauss', new=random.Random(42).gauss):
            for _ in range(10000):
                publish_readbacks(machine, signals, context, 5.0)
                values = context.puts.pop()[1]
                samples[0].append(values[0] - 0.25)
                samples[1].append(values[1] + 2.0)
        for noise, expected_rms in zip(samples, [0.01, 0.1]):
            mean = sum(noise) / len(noise)
            rms = math.sqrt(sum(x*x for x in noise) / len(noise))
            self.assertLess(abs(mean), 0.04 * expected_rms)
            self.assertAlmostEqual(rms, expected_rms, delta=0.03 * expected_rms)
        self.assertNotEqual(samples[0][0], samples[0][1])

    def test_return_to_initial_current_is_not_dropped_while_worker_is_busy(self):
        entered, release = threading.Event(), threading.Event()
        class SlowMachine(FakeMachine):
            def set(self, pv, value):
                if value == 0.5:
                    entered.set()
                    if not release.wait(3):
                        raise TimeoutError('test worker did not release')
                return super().set(pv, value)
        machine = SlowMachine({'current': 0.0})
        context = FakeContext()
        service = MachineService(machine, context, [MachineSignal('sp', 'current')],
                                 [MachineSignal('rb', 'current')])
        try:
            service.start()
            context.callbacks['sp'](0.0)
            context.callbacks['sp'](0.5)
            self.assertTrue(entered.wait(3))
            context.callbacks['sp'](0.0)
            release.set()
            service.wait_for_idle()
        finally:
            release.set()
            service.close()
        self.assertEqual(machine.sets, [('current', 0.5), ('current', 0.0)])
        self.assertEqual(machine.get('current'), 0.0)


if __name__ == "__main__":
    unittest.main()