# softIoc and PyTao bridge

Install EPICS Base with `softIoc`, `caget`, and `caput` available on `PATH`.
For a source installation, add its platform-specific `bin` directory to `PATH`:

```sh
export EPICS_BASE="/path/to/epics-base"
export PATH="$EPICS_BASE/bin/<host-architecture>:$PATH"
```

Replace the placeholders with your installation directory and EPICS host
architecture. The examples below use POSIX shell syntax and run from the
`narad-epics` repository root.

## Python dependencies

Activate a Python environment with Bmad/libtao available, then install the
project with its bridge extra and the model requirements:

```sh
python -m pip install -e '.[bridge]'
python -m pip install -r models/requirements-pv.txt
```

If PyTao cannot discover libtao automatically, set `PYTAO_LIB_PATH` to the
shared library in your Bmad installation. For example, on macOS:

```sh
export PYTAO_LIB_PATH="/path/to/bmad/lib/libtao.dylib"
```

On Linux, use the corresponding `libtao.so` path. Make this environment variable
available in the model terminal and when running the live check.

## Run

In the IOC terminal:

```sh
export EPICS_CAS_INTF_ADDR_LIST=127.0.0.1
softIoc -d generated/toy_ring.db
```

In the model terminal:

```sh
python models/pv_server.py
```

In the bridge terminal:

```sh
export EPICS_CA_ADDR_LIST=127.0.0.1
export EPICS_CA_AUTO_ADDR_LIST=NO
python -m iocs.ca_bridge
```

Wait for `Bridge ready: 384 setpoints, 768 readbacks`. The installed package also
exposes `narad-epics-bridge`. Options are `--source`, `--model-host`, and
`--model-port`; defaults select the checked toy-ring YAML and 127.0.0.1:8765.

From a fourth terminal, with the same CA client environment:

```sh
export EPICS_CA_ADDR_LIST=127.0.0.1
export EPICS_CA_AUTO_ADDR_LIST=NO
caput inst:es12-t1:PS:H:Current-SP 0.01
# Wait for the bridge's "Forwarded ...; published 768 readbacks" message.
caget inst:es12-t1:PS:H:Current-RB inst:es12-bpm0:X-RB
caput inst:es12-t1:PS:H:Current-SP 0
```

## Current behavior

The bridge maps the YAML's explicit numeric signals through their component
bindings. It subscribes to 384 current setpoints. Each subsequent setpoint
change sends a JSON `set` to the model, then reads and publishes all 384 current
readbacks and all 384 BPM coordinates through Channel Access. Current units
remain A; BPM meters are multiplied by 1000 for EPICS mm. Readbacks use actual
model `get` results rather than copying the command. The model TCP connection
is released after each event's readbacks so other model clients can connect.

The initial CA subscription value is ignored. There is no initial setpoint
replay or readback refresh; IOC values remain their database defaults until a
setpoint change is handled. Readbacks update only after a setpoint event;
changes made directly to the model are visible after the next such event.
A completed `caput` confirms the IOC write; use the bridge completion message
or readbacks to check that model processing has finished.

No polling, startup synchronization, status generation, alarm handling, or
custom reconnection logic is implemented. The 384 status records are untouched.
An exception in model forwarding/readback publication terminates the bridge.
The checked database and its generator are unchanged.

## Validation

Validation with EPICS Base R7.0.11 and caproto 1.3.0 loaded `generated/toy_ring.db` successfully. A live test
connected all 1,152 numeric PVs and a representative status PV, forwarded
horizontal 0.01 A and vertical -0.02 A, and compared all 768 readbacks with
PyTao. Example values with both currents applied:

| BPM | Model m | EPICS mm |
| --- | ---: | ---: |
| es12_bpm0 x | -2.522531436569165e-7 | -0.0002522531436569165 |
| es12_bpm0 y | 1.5533675266691317e-7 | 0.00015533675266691318 |

Both currents were restored to zero and the resulting readbacks again matched
the model. Status remained `UNKNOWN`. Test services were stopped afterward.
All 18 unit tests passed, including mapping, conversion, and failed-set checks.

To repeat the opt-in live check (starts and stops its own processes on loopback
CA ports 15064/15065 and model port 18765):

```sh
python tests/check_live_bridge.py
```

Set `EPICS_BASE` to your EPICS installation before running the checker; it
locates `softIoc` under `$EPICS_BASE/bin/`. Run it in the Python environment
with PyTao and the bridge dependencies installed. Test logs are retained in
the temporary directory printed by the checker.
