# softIocPVA and PyTao machine service

The IOC owns the EPICS records. A separate Python process uses p4p to monitor
setpoints over PVAccess, applies changes to one persistent Tao machine, and writes
machine-derived readbacks back through PVAccess. There is no Channel Access or
intermediate TCP machine server in this runtime.

## Prerequisites

- EPICS Base with `softIocPVA`, `pvget`, and `pvput` on `PATH`.
- Pixi and the checked `simulation` environment, which contains p4p and PyTao.
- A Bmad/libtao installation usable by PyTao.

If PyTao cannot locate Tao, set `PYTAO_LIB_PATH` to the actual `libtao` shared
library supplied by the Bmad installation.

Install the locked Pixi environment with:

```sh
pixi install -e simulation
```

Alternatively, when Bmad supplies the active Python environment, install this
project and its simulation extra into that environment:

```sh
python -m pip install -e ".[simulation]"
```

`pyproject.toml` is the single source for Python dependencies: the base project
requires PyYAML, and the `simulation` extra adds p4p and PyTao. `softIocPVA` and
the native `libtao` shared library are external prerequisites; pip and Pixi do
not install those EPICS Base and Bmad runtime components for this project.

If PyTao cannot locate Tao, set `PYTAO_LIB_PATH` to the actual `libtao` shared
library supplied by the Bmad installation.

For a source installation of EPICS Base, add its platform-specific binary
directory to `PATH`:

```sh
export EPICS_BASE="/path/to/epics-base"
export PATH="$EPICS_BASE/bin/<host-architecture>:$PATH"
```

## Run on Linux

Open two terminals in the `narad-epics` repository root.

If needed, make the Bmad shared library explicit in both the machine-service and
live-check shells:

```sh
export PYTAO_LIB_PATH="/path/to/bmad/lib/libtao.so"
```

Use the corresponding `libtao.so` path. Make this environment variable
available in the machine terminal and when running the live check.

```sh
softIocPVA -d generated/toy_ring.db
```

Terminal 2, start the persistent Tao machine service:

```sh
pixi run -e simulation narad-epics-machine-service
```

Or, from an active environment where `.[simulation]` was installed:

```sh
python -m iocs.pva_bridge
```

To use another lattice:

```sh
pixi run -e simulation narad-epics-machine-service /path/to/ring.bmad
```

Pure Python:

```sh
python -m iocs.pva_bridge /path/to/ring.bmad
```

From the parent directory, identify the project manifest explicitly:

```sh
pixi run -e simulation --manifest-path narad-epics/pyproject.toml \
	narad-epics-machine-service
```

Wait for `Machine service ready: 384 setpoints, 768 readbacks`.

## Verify

From another terminal:

```sh
pvput inst:es12-t1:PS:H:Current-SP 0.01
pvget inst:es12-t1:PS:H:Current-RB inst:es12-bpm0:X-RB
pvput inst:es12-t1:PS:H:Current-SP 0
```

`pvput` confirms the IOC write. Wait for the service's `Forwarded ...;
published 768 readbacks` log or read the output PVs to confirm that Tao has
processed the update.

## Runtime behavior

The service derives its mapping from the Narad YAML component bindings. It
connects to all 1,152 numeric IOC PVs and creates p4p monitors for 384 current
setpoints. p4p callbacks only enqueue updates; one worker serializes all access
to the single Tao instance.

For each changed setpoint, the worker:

1. Sets the matching Tao steering current.
2. Lets Tao recalculate the closed orbit.
3. Reads all 384 machine current values and all 384 BPM coordinates.
4. Adds independent zero-mean Gaussian readback noise and publishes all 768
   EPICS readbacks with one p4p batch put.

Current units remain A. Tao BPM positions are in meters, so the service
multiplies them by 1000 before writing EPICS records declared in millimeters.
After conversion, each BPM coordinate receives 0.1 mm RMS noise, and each
current readback receives 0.01 A (10 mA) RMS noise. A fresh independent sample
is drawn for every PV on each publication. Noise does not change setpoints,
Tao calculations, or status records. Readbacks can fluctuate around zero;
there is no clipping and no periodic noise refresh.

The first value delivered by each monitor is ignored. Existing IOC setpoints
are not replayed into Tao at startup, and readbacks remain at database defaults
until a setpoint changes. Status records remain `UNKNOWN`. There is no polling,
status generation, alarm handling, persistence, or current-limit enforcement.
An individual failed update is logged and the service continues monitoring.

## Network discovery

Localhost normally requires no extra configuration. For an IOC on another
host, configure the usual PVA discovery variables before starting the service:

```sh
export EPICS_PVA_ADDR_LIST="127.0.0.1"
export EPICS_PVA_AUTO_ADDR_LIST=YES
```

## Validation

The live check loads `generated/toy_ring.db` in `softIocPVA`, connects all
1,152 numeric PVs and a representative status PV, and forwards horizontal
0.01 A and vertical -0.02 A setpoints. It compares all 768 readbacks against
an independent, deterministic Tao reference machine, checking the mean and
RMS of the added noise separately for the 384 current and 384 BPM readbacks.
It repeats these checks after restoring both setpoints to zero.

Unit coverage verifies the full signal inventory, p4p callback-to-worker flow,
machine-confirmed readback publication, failed-set behavior, BPM conversion,
noise mean/RMS, and rapid setpoint changes while the worker is busy.
Run it with:

```sh
pixi run check
```

Without Pixi, compile and run the same standard-library test suite from the
repository root:

```sh
python -m compileall -q iocs machines tests
python -m unittest discover -s tests -v
```

The opt-in live check starts and stops its own `softIocPVA` and machine-service
processes, then compares all 768 noisy EPICS readbacks with an independent Tao machine:

```sh
pixi run -e simulation python tests/check_live_pva.py
```

From an active Python environment with `.[simulation]` installed, invoke the
checker directly:

```sh
python tests/check_live_pva.py
```

Set `EPICS_BASE` to your EPICS installation before running the checker; it
locates `softIocPVA` under `$EPICS_BASE/bin/`. Run it in the Python environment
with PyTao and the bridge dependencies installed. Test logs are retained in
the temporary directory printed by the checker.
