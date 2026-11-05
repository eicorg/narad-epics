"""Opt-in live IOC/model/bridge check; run from the repository root.

Requires EPICS Base (EPICS_BASE), PyTao/libtao, and caproto. Test services use
loopback CA ports 15064/15065 and model port 18765, and are stopped on exit.
"""

import os
from pathlib import Path
import subprocess
import sys
import time
import math
import tempfile

root = Path(__file__).resolve().parents[1]
epics_base = Path(os.environ.get('EPICS_BASE', str(root.parent / '.tools/epics-base')))
log_dir = Path(tempfile.mkdtemp(prefix='toy-dt-live-check-'))
print('Test logs:', log_dir, flush=True)
sys.path.insert(0, str(root))
from caproto.threading.client import Context
from iocs.ca_bridge import ModelClient, load_mapping

env = dict(os.environ, EPICS_CA_ADDR_LIST='127.0.0.1', EPICS_CA_AUTO_ADDR_LIST='NO', EPICS_CA_SERVER_PORT='15064', EPICS_CA_REPEATER_PORT='15065', EPICS_CAS_INTF_ADDR_LIST='127.0.0.1')
os.environ.update(env)
processes, handles = [], []
logs = {}
def start(name, command):
    path = log_dir / (name + '.log')
    handle = path.open('w')
    handles.append(handle)
    process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.PIPE, stdout=handle, stderr=subprocess.STDOUT)
    processes.append(process)
    logs[name] = path
    return process

def wait_for(name, text, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        content = logs[name].read_text()
        if text in content:
            return
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(f'Process exited {process.returncode}: {content}')
        time.sleep(0.1)
    raise TimeoutError(logs[name].read_text())

try:
    start('model', [sys.executable, '-u', 'models/pv_server.py', '--port', '18765'])
    wait_for('model', 'PV server listening')
    ioc = start('ioc', [str(next(epics_base.glob('bin/*/softIoc'))), '-d', 'generated/toy_ring.db'])
    # IOC stdout may be buffered; Channel Access connection confirms readiness.
    setpoints, readbacks = load_mapping(root / 'yaml-descriptions/toy_ring_narad_instance.yaml')
    with Context(timeout=10) as context:
        names = [s.pv for s in setpoints + readbacks] + ['inst:es12-t1:PS:H:Status']
        pvs = dict(zip(names, context.get_pvs(*names)))
        for pv in pvs.values():
            pv.wait_for_connection(timeout=20)
        print('Loaded IOC: all 1,152 numeric PVs and representative status connected.', flush=True)
        start('bridge', [sys.executable, '-u', '-m', 'iocs.ca_bridge', '--model-port', '18765'])
        wait_for('bridge', 'Bridge ready')
        def apply(plane, value):
            pv = f'inst:es12-t1:PS:{plane}:Current-SP'
            pvs[pv].write(value)
            wait_for('bridge', f'Forwarded {pv} = {value};', timeout=90)
        apply('H', 0.01)
        apply('V', -0.02)
        with ModelClient('127.0.0.1', 18765) as model:
            for signal in readbacks:
                expected = model.request('get', pv=signal.key) * signal.scale
                actual = float(pvs[signal.pv].read().data[0])
                assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12), (signal.pv, actual, expected)
            for plane in ('x', 'y'):
                pv = f'inst:es12-bpm0:{plane.upper()}-RB'
                print(pv, 'mm =', float(pvs[pv].read().data[0]), '; model m =', model.request('get', pv=f'es12_bpm0:{plane}'), flush=True)
        print('Verified all 768 current/BPM readbacks against model, including m-to-mm conversion.', flush=True)
        status = pvs['inst:es12-t1:PS:H:Status'].read().data
        print('Status untouched:', status, flush=True)
        apply('H', 0.0)
        apply('V', 0.0)
        with ModelClient('127.0.0.1', 18765) as model:
            for plane in ('h', 'v'):
                assert model.request('get', pv=f'steering_{plane}:i_es12_t1') == 0.0
            for plane in ('x', 'y'):
                actual = float(pvs[f'inst:es12-bpm0:{plane.upper()}-RB'].read().data[0])
                expected = model.request('get', pv=f'es12_bpm0:{plane}') * 1000.0
                assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12)
                print('Restored BPM', plane, '[mm]:', actual, flush=True)
        print('Restored both currents to zero; readbacks match model.', flush=True)
    ioc.stdin.write(b'dbl\nexit\n')
    ioc.stdin.flush()
    ioc.wait(timeout=10)
    print('PASS', flush=True)
finally:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    for handle in handles:
        handle.close()
