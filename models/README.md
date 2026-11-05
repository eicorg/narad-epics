# PyTao toy-ring model

This directory contains the PyTao adapter (`pv_model.py`), JSON TCP server
(`pv_server.py`), lattice (`toy_ring.bmad`), and Python requirements.
The lattice is self-contained; no parent-directory files are needed at runtime.
It models an illustrative 18 GeV electron ring with ideal closed-orbit BPMs and
linear magnet-current calibrations, not measured hardware behavior.

From the repository root, in an environment with Bmad/libtao installed:

```sh
python -m pip install -r models/requirements-pv.txt
python models/pv_server.py
```

The server defaults to `127.0.0.1:8765` and the adjacent `toy_ring.bmad`.
Options: `--host`, `--port`, `--lattice`. PyTao must locate `libtao`; activate
your Bmad environment and configure its library paths as required. The project's
base translation-toolkit environment does not install Bmad or PyTao.

## Protocol

UTF-8 JSON, one request and response per newline. Examples:

```json
{"op":"list"}
{"op":"get","pv":"steering_h:i_es12_t1"}
{"op":"set","pv":"steering_h:i_es12_t1","value":0.01}
{"op":"get","pv":"es12_bpm0:x"}
```

Success: `{"ok":true,"result":...}`. Failure:
`{"ok":false,"error":"..."}`. Names are lowercase and case-sensitive.
There are 384 steering currents, two quadrupole family currents, two sextupole
family currents (all A), and 384 read-only BPM coordinates (m). Each current
write triggers Tao's normal recalculation. Values persist in memory until exit.

This is a custom TCP server, not an EPICS IOC. It serves one connection at a
time; a bridge should serialize requests and close connections between batches
so another client can connect. There are no subscriptions, authentication,
current limits, transactions, or persistent settings. Keep it on loopback.

## Channel Access connection

The event-driven bridge is implemented in `../iocs/ca_bridge.py`. It forwards
384 steering setpoints, publishes 384 current readbacks and 384 BPM coordinates,
and converts BPM meters to EPICS millimeters. It uses the existing database
without changes. See [the bridge run guide](../iocs/BRIDGE.md) for
softIoc setup, startup commands, exact behavior, and live validation.

Quadrupole and sextupole family currents are exposed by the model but have no
signals in the checked database. The bridge leaves status records untouched.
