# Direct PALS → NARAD → LUME ring

This example uses the upstream NARAD LinkML schema and a pinned PALS parser pair
to turn a PALS lattice and a hardware profile into a Bmad-backed LUME model.
The binder constructs LUME actions in memory from typed NARAD objects.

## Run with Pixi

Run these commands from this directory on Apple Silicon macOS or Linux x86-64.
First use needs network access. On macOS, install the Xcode Command Line Tools
for the C++ build.

```sh
pixi run serve-ring
pixi run verify-ring
```

The server publishes the full ring under `RING:`. Run the verification task
separately when using the standard EPICS ports. It starts and stops a loopback
server and checks all 1,544 signal PVs. To run the two-cell FODO example, use
`pixi run serve-fodo`, with prefix `FODO:`.

Pixi prepares the Python and native dependencies. The setup task builds
PALSParserCpp at `f1f69df` and runs LinkML's `gen-pydantic` against the vendored
NARAD schema from NARAD-DataServices revision `1018824`. Generated build
products and Python models stay local.

## Full-ring signals

| Quantity | Channels | Access |
| --- | ---: | --- |
| Supply current setpoints | 388 | Writable |
| Supply current readbacks | 388 | Read-only, ideal controller current |
| BPM closed-orbit positions | 384 | Read-only, in mm |
| Corrector supply status | 384 | Read-only, legacy placeholder `UNKNOWN` |

`toy_ring.hardware.yaml` selects exact PALS variables for all 388 current
channels and explicitly associates readouts with 192 BPM occurrences. PALS
controller provenance supplies the individual or shared magnet targets.
The profile preserves the legacy signal IDs through explicit aliases.
Legacy status placeholders carry no simulated hardware-state information.
LUME-PVA also exposes its own runner controls, including `RING:RESET`.

## Inspect the graph

After `pixi run setup`, point `PALS_PARSER_CPP_LIB` at the shared library under
`.build/native` to run `graph.py` directly for the FODO example. The full-ring
server builds its typed graph from `toy_ring.no_alias.pals.yaml` and
`toy_ring.hardware.yaml`. Both examples send the lattice physics parameters
directly from PALS to Bmad.

The upstream schema requires a context for `Controls`. This projection uses
`installation_mounting` for installed supply-to-magnet relationships and
`containment` for the BPM readout's `IsPartOf` relationship.
