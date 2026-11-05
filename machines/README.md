# PyTao toy-ring machine

This directory contains the PyTao adapter (`pv_machine.py`) and self-contained
lattice (`toy_ring.bmad`). The lattice represents an illustrative 18 GeV electron
ring with ideal closed-orbit BPMs and linear magnet-current calibrations, not
measured hardware behavior.

The supported EPICS runtime starts the adapter through the p4p service in
`../iocs/pva_bridge.py`:

```sh
pixi install -e simulation
```

When using a Python environment supplied by Bmad instead of Pixi:

```sh
python -m pip install -e ".[simulation]"
```

```sh
softIocPVA -d generated/toy_ring.db
pixi run -e simulation narad-epics-machine-service
```

With `.[simulation]` installed in the active Python environment, the equivalent
machine-service command is:

```sh
python -m iocs.pva_bridge
```

Run those commands in separate terminals from the repository root. PyTao must
locate `libtao`; configure `PYTAO_LIB_PATH` when the Bmad installation is not
discovered automatically.

## Machine API

`RingMachine` keeps one Tao instance in memory. Its API is deliberately small:

- `list_pvs()` returns writable currents and read-only BPM machine keys.
- `get(key)` reads a current or closed-orbit coordinate.
- `set(key, value)` applies a finite current and lets Tao recalculate.

There are 384 steering currents, two quadrupole family currents, two sextupole
family currents (all A), and 384 read-only BPM coordinates (m). Each current
write triggers Tao's normal recalculation. Values persist in memory until exit.

## PVAccess connection

The event-driven machine service is implemented in `../iocs/pva_bridge.py`. It
uses p4p to monitor 384 steering setpoints from `softIocPVA`, serializes Tao
updates through one worker, publishes 384 current readbacks and 384 BPM
coordinates, and converts BPM meters to EPICS millimeters. See
[the service run guide](../iocs/BRIDGE.md) for startup commands, exact behavior,
network discovery, and live validation.

Quadrupole and sextupole family currents are exposed by the machine but have no
signals in the checked database. The bridge leaves status records untouched.

Published readbacks include independent, zero-mean Gaussian noise: 0.1 mm RMS
for each BPM coordinate and 0.01 A (10 mA) RMS for each current readback. Noise
is added after unit conversion on each publication, leaving `RingMachine.get`
and the underlying Tao currents/orbit deterministic. It does not change
setpoints or status records and does not introduce periodic updates.
