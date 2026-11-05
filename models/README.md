# PyTao toy-ring model

This directory contains the PyTao adapter (`pv_model.py`) and self-contained
lattice (`toy_ring.bmad`). The lattice models an illustrative 18 GeV electron
ring with ideal closed-orbit BPMs and linear magnet-current calibrations, not
measured hardware behavior.

The supported EPICS runtime starts the adapter through the p4p service in
`../iocs/pva_bridge.py`:

```sh
softIocPVA -d generated/toy_ring.db
pixi run -e simulation narad-epics-model-service
```

PowerShell uses the same commands with Windows path separators when a path is
provided:

```powershell
softIocPVA -d generated\toy_ring.db
pixi run -e simulation narad-epics-model-service
```

Run those commands in separate terminals from the repository root. PyTao must
locate `libtao`; configure `PYTAO_LIB_PATH` when the Bmad installation is not
discovered automatically.

## Model API

`RingModel` keeps one Tao instance in memory. Its API is deliberately small:

- `list_pvs()` returns writable currents and read-only BPM model keys.
- `get(key)` reads a current or closed-orbit coordinate.
- `set(key, value)` applies a finite current and lets Tao recalculate.

There are 384 steering currents, two quadrupole family currents, two sextupole
family currents (all A), and 384 read-only BPM coordinates (m). Each current
write triggers Tao's normal recalculation. Values persist in memory until exit.

## PVAccess connection

The event-driven model service is implemented in `../iocs/pva_bridge.py`. It
uses p4p to monitor 384 steering setpoints from `softIocPVA`, serializes Tao
updates through one worker, publishes 384 current readbacks and 384 BPM
coordinates, and converts BPM meters to EPICS millimeters. See
[the service run guide](../iocs/BRIDGE.md) for startup commands, exact behavior,
network discovery, and live validation.

Quadrupole and sextupole family currents are exposed by the model but have no
signals in the checked database. The bridge leaves status records untouched.
