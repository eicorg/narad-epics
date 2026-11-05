from pathlib import Path
import unittest

from iocs.ca_bridge import ModelSignal, forward_setpoint, load_mapping

ROOT = Path(__file__).resolve().parents[1]


class BridgeTests(unittest.TestCase):
    def test_reference_signal_inventory_and_units(self):
        setpoints, readbacks = load_mapping(ROOT / 'yaml-descriptions/toy_ring_narad_instance.yaml')
        self.assertEqual(len(setpoints), 384)
        self.assertEqual(len(readbacks), 768)
        by_name = {s.pv: s for s in setpoints + readbacks}
        self.assertEqual(by_name['inst:es12-t1:PS:V:Current-SP'].key, 'steering_v:i_es12_t1')
        self.assertEqual(by_name['inst:es12-t1:PS:H:Current-RB'].scale, 1.0)
        self.assertEqual(by_name['inst:es12-bpm0:X-RB'], ModelSignal('inst:es12-bpm0:X-RB', 'es12_bpm0:x', 1000.0))
        self.assertFalse(any(':Status' in s.pv for s in setpoints + readbacks))

    def test_confirmed_current_and_bpm_conversion_after_set(self):
        calls, writes = [], {}
        class Client:
            def request(self, operation, **kwargs):
                calls.append((operation, kwargs))
                return {'steering_h:i_es12_t1': 0.25, 'es12_bpm0:x': -0.002}[kwargs['pv']]
        class PV:
            def __init__(self, name):
                self.name = name
            def write(self, value):
                writes[self.name] = value
        readbacks = [ModelSignal('current', 'steering_h:i_es12_t1'), ModelSignal('bpm', 'es12_bpm0:x', 1000.0)]
        forward_setpoint(Client(), ModelSignal('setpoint', 'steering_h:i_es12_t1'), 0.25,
                         readbacks, {s.pv: PV(s.pv) for s in readbacks})
        self.assertEqual(calls[0], ('set', {'pv': 'steering_h:i_es12_t1', 'value': 0.25}))
        self.assertEqual(writes, {'current': 0.25, 'bpm': -2.0})

    def test_failed_set_does_not_publish_a_readback(self):
        class Client:
            def request(self, *args, **kwargs):
                raise RuntimeError('rejected')
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            forward_setpoint(Client(), ModelSignal('sp', 'key'), 1, [ModelSignal('rb', 'key')], {})
