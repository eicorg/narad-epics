# softIocPVA and PyTao model service

The IOC owns the EPICS records. A separate Python process uses p4p to monitor
setpoints over PVAccess, applies changes to one persistent Tao model, and writes
model-derived readbacks back through PVAccess. There is no Channel Access or
intermediate TCP model server in this runtime.

## Prerequisites

- EPICS Base with `softIocPVA`, `pvget`, and `pvput` on `PATH`.
- Pixi and the checked `simulation` environment, which contains p4p and PyTao.
- A Bmad/libtao installation usable by PyTao.

If PyTao cannot locate Tao, set `PYTAO_LIB_PATH` to the actual `libtao` shared
library supplied by the Bmad installation.

For a source installation of EPICS Base on Linux or macOS, add its
platform-specific binary directory to `PATH`:

```sh
export EPICS_BASE="/path/to/epics-base"
export PATH="$EPICS_BASE/bin/<host-architecture>:$PATH"
```

## Run on Windows

Open two PowerShell terminals in the `narad-epics` repository root.

Terminal 1, start the PVA-enabled IOC:

```powershell
softIocPVA -d generated\toy_ring.db
```

Wait for `iocRun: All initialization complete` and leave it running.

Terminal 2, start the persistent Tao model service:

```powershell
pixi run -e simulation narad-epics-model-service
```

The default lattice is `models/toy_ring.bmad`. To use another Bmad lattice,
pass its path as the positional argument:

```powershell
pixi run -e simulation narad-epics-model-service C:\path\to\ring.bmad
```

From `C:\git\eic-accelerator`, identify the project manifest explicitly:

```powershell
pixi run -e simulation --manifest-path narad-epics\pyproject.toml `
	narad-epics-model-service
```

Wait for the service to report:

```text
Model service ready: 384 setpoints, 768 readbacks
```

## Run on Linux or macOS

Open two terminals in the `narad-epics` repository root.

If needed, make the Bmad shared library explicit in both the model-service and
live-check shells:

```sh
export PYTAO_LIB_PATH="/path/to/bmad/lib/libtao.so"
```

On macOS, use the corresponding `libtao.dylib` path.

Terminal 1, start the PVA-enabled IOC:

```sh
softIocPVA -d generated/toy_ring.db
```

Terminal 2, start the persistent Tao model service:

```sh
pixi run -e simulation narad-epics-model-service
```

To use another lattice:

```sh
pixi run -e simulation narad-epics-model-service /path/to/ring.bmad
```

From the parent directory, identify the project manifest explicitly:

```sh
pixi run -e simulation --manifest-path narad-epics/pyproject.toml \
	narad-epics-model-service
```

Wait for `Model service ready: 384 setpoints, 768 readbacks`.

## Verify

From another PowerShell terminal:

```powershell
pvput inst:es12-t1:PS:H:Current-SP 0.01
pvget inst:es12-t1:PS:H:Current-RB inst:es12-bpm0:X-RB
pvput inst:es12-t1:PS:H:Current-SP 0
```

The same client commands work from `sh`:

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
3. Reads all 384 model current values and all 384 BPM coordinates.
4. Publishes all 768 EPICS readbacks with one p4p batch put.

Current units remain A. Tao BPM positions are in meters, so the service
multiplies them by 1000 before writing EPICS records declared in millimeters.

The first value delivered by each monitor is ignored. Existing IOC setpoints
are not replayed into Tao at startup, and readbacks remain at database defaults
until a setpoint changes. Status records remain `UNKNOWN`. There is no polling,
status generation, alarm handling, persistence, or current-limit enforcement.
An individual failed update is logged and the service continues monitoring.

## Network discovery

Localhost normally requires no extra configuration. For an IOC on another
host, configure the usual PVA discovery variables before starting the service,
for example:

```powershell
$env:EPICS_PVA_ADDR_LIST = "192.0.2.10"
$env:EPICS_PVA_AUTO_ADDR_LIST = "NO"
```

For `sh`:

```sh
export EPICS_PVA_ADDR_LIST="192.0.2.10"
export EPICS_PVA_AUTO_ADDR_LIST=NO
```

## Validation

Unit coverage verifies the full signal inventory, p4p callback-to-worker flow,
model-confirmed readback publication, failed-set behavior, and BPM conversion.
Run it with:

```powershell
pixi run check
```

From `sh`, the command is the same:

```sh
pixi run check
```

The opt-in live check starts and stops its own `softIocPVA` and model-service
processes, then compares all 768 EPICS readbacks with an independent Tao model:

```powershell
pixi run -e simulation python tests\check_live_pva.py
```

For `sh`:

```sh
pixi run -e simulation python tests/check_live_pva.py
```

Set `EPICS_BASE` to the EPICS Base installation before running the checker. Test
logs are retained in the temporary directory printed by the script.
