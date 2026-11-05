# Local softIoc and PyTao bridge

EPICS Base R7.0.11 was built in `../../.tools/epics-base` relative to this
file's directory (the Toy_DT workspace's `.tools/epics-base`). The local
executable is `../../.tools/epics-base/bin/darwin-aarch64/softIoc`.
The build also supplies `caget` and `caput` in that directory. No global
installation or shell configuration was changed.

All commands below run from the `narad-epics` repository root.

## Python dependencies

A local `.venv` was created using the existing Bmad Python environment with
`--system-site-packages`; caproto 1.3.0 is installed there. For another
environment, install the project with its bridge extra and the model requirements:

```sh
python -m pip install -e '.[bridge]'
python -m pip install -r models/requirements-pv.txt
```

Bmad/libtao must also be installed. The existing local library can be selected
explicitly, which is needed when running PyTao from this `.venv`:

```sh
export PYTAO_LIB_PATH=/Users/Hamwi/.local/share/mamba/envs/bmad/lib/libtao.dylib
```

## Run

In the IOC terminal:

```sh
export EPICS_CAS_INTF_ADDR_LIST=127.0.0.1
../.tools/epics-base/bin/darwin-aarch64/softIoc -d generated/toy_ring.db
```

In the model terminal:

```sh
export PYTAO_LIB_PATH=/Users/Hamwi/.local/share/mamba/envs/bmad/lib/libtao.dylib
.venv/bin/python models/pv_server.py
```

In the bridge terminal:

```sh
export EPICS_CA_ADDR_LIST=127.0.0.1
export EPICS_CA_AUTO_ADDR_LIST=NO
.venv/bin/python -m iocs.ca_bridge
```

Wait for `Bridge ready: 384 setpoints, 768 readbacks`. The installed package also
exposes `narad-epics-bridge`. Options are `--source`, `--model-host`, and
`--model-port`; defaults select the checked toy-ring YAML and 127.0.0.1:8765.

From a fourth terminal, with the same CA client environment:

```sh
export EPICS_CA_ADDR_LIST=127.0.0.1
export EPICS_CA_AUTO_ADDR_LIST=NO
../.tools/epics-base/bin/darwin-aarch64/caput inst:es12-t1:PS:H:Current-SP 0.01
# Wait for the bridge's "Forwarded ...; published 768 readbacks" message.
../.tools/epics-base/bin/darwin-aarch64/caget inst:es12-t1:PS:H:Current-RB inst:es12-bpm0:X-RB
../.tools/epics-base/bin/darwin-aarch64/caput inst:es12-t1:PS:H:Current-SP 0
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

The local softIoc loaded `generated/toy_ring.db` successfully. A live test
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
export PYTAO_LIB_PATH=/Users/Hamwi/.local/share/mamba/envs/bmad/lib/libtao.dylib
.venv/bin/python tests/check_live_bridge.py
```

Set `EPICS_BASE` if the EPICS installation is elsewhere. Test logs are retained
in the temporary directory printed by the checker.
