# Narad EPICS translation toolkit

This repository translates explicit control-system signals from Narad YAML
descriptions into EPICS record instance (`.db`) files. The first reference
input is [`yaml-descriptions/toy_ring_narad_instance.yaml`](yaml-descriptions/toy_ring_narad_instance.yaml),
a hypothetical EIC toy ring enriched with fictional EPICS controls.

The translator is intentionally signal-driven. It creates records only for
entries in `facility.signals`; lattice properties such as Twiss parameters,
magnetic multipoles, and longitudinal placement remain machine-description
context and do not become PVs automatically.

## Repository structure

```text
narad-epics/
|-- yaml-descriptions/  # Narad YAML lattice descriptions
|-- iocs/               # Narad-to-EPICS translation and IOC utilities
|   `-- opis/            # Phoebus Display Builder operator displays
|-- machines/          # Accelerator machines and lattice data
|-- generated/          # Checked reference EPICS databases
|-- tests/              # Translation-toolkit tests and reference validation
|-- pyproject.toml      # Python metadata, dependencies, and Pixi tasks
|-- README.md
`-- .gitignore
```

- `yaml-descriptions/` contains Narad YAML files that describe accelerator
	lattices. A description can include beamlines, components, physics
	properties, explicit control-system signals, and bindings between lattice
	components and those signals.
- `iocs/` is the home of the Python toolkit that validates Narad YAML, maps
	Narad signals to EPICS record types, and generates the `.db` files used by
	EPICS IOCs. Its parser, mapping contract, renderer, and command-line utility
	are documented below. `iocs/opis/toy_ring_overview.bob` is the entry point
	for the Phoebus Display Builder screens. It contains one embedded row for
	each signal-bearing component and supplies exact PV names to reusable BPM
	and kicker row displays through macros.
- `machines/` contains accelerator simulation code and lattice data. It is separate
	from IOC translation so lattice and beam-physics logic do not become coupled
	to EPICS database generation.
- `generated/` contains reproducible `.db` output for reference descriptions.
  `generated/toy_ring.db` is generated from the toy-ring YAML and checked by
  the integration tests.
- `tests/` verifies the translation toolkit with compact fixtures and the full
	toy-ring description.

## Development environment

The project uses [Pixi](https://pixi.sh/) to provide a reproducible Linux Python
environment. Install the environment and run all checks from the repository
root:

```sh
pixi install
pixi run check
```

Run only the tests with:

```sh
pixi run test
```

The direct Python equivalent is:

```sh
python -m unittest discover -s tests -v
```

## Run the PVA simulation

Run the IOC and persistent Tao machine service in separate terminals from the
repository root:

```sh
softIocPVA -d generated/toy_ring.db
pixi run -e simulation narad-epics-machine-service
```

After `python -m pip install -e ".[simulation]"`, the machine service can also be
started without Pixi:

```sh
python -m iocs.pva_bridge
```

The service uses p4p to monitor all 384 setpoint PVs over PVAccess and publishes
768 machine-derived current and BPM readbacks, with 10 mA RMS current noise
and 0.1 mm RMS BPM noise. See
[`iocs/BRIDGE.md`](iocs/BRIDGE.md) for the full startup, discovery, behavior,
and live-validation guide.

Regenerate the checked toy-ring database with:

```sh
pixi run generate-toy-ring
```

Regenerate the top-level Phoebus display from the same description with:

```sh
pixi run generate-toy-ring-opis
```

Open `iocs/opis/toy_ring_overview.bob` in Phoebus Display Builder. Its 384
rows follow lattice source order and use Embedded Display widgets to load
`rows/bpm_row.bob` or `rows/kicker_row.bob`. Each embedded instance passes the
component label, type, and exact PV names as macros. Start an IOC that loads
`generated/toy_ring.db` with `softIocPVA` before opening the display. Generated
PV macros use the explicit `pva://` provider.

Dependencies and routine development commands belong in `pyproject.toml`. The
generated `pixi.lock` file should be committed so local development and CI use
the same resolved packages.

## Toy ring description

The toy-ring document is a `PALSAccelerator` instance containing four relevant
layers:

- `facility.components` describes accelerator elements such as beam-position
	monitors, kickers, quadrupoles, sextupoles, bends, and drifts.
- `facility.beamlines` describes the periodic ring that contains those
	components.
- `facility.signals` declares the control-system signals that should be
	exposed as EPICS records or record fields.
- `facility.signal_bindings` associates components with signals.

The current document contains 2,304 signals and 2,304 signal bindings, mapped
to 1,536 records. Its signal inventory is:

| Narad data type | Narad role | Unit | Count | Example |
| --- | --- | --- | ---: | --- |
| `Float` | `Readback` | `mm` or `A` | 768 | `inst:es12-bpm0:X-RB` |
| `Float` | `Setpoint` | `A` | 384 | `inst:es12-t1:PS:H:Current-SP` |
| `String` | `Status` | `none` | 384 | `inst:es12-t1:PS:H:Status` |
| `Float` | `RangeLimit` | `A` | 768 | `inst:es12-t1:PS:H:Current-SP.DRVL` |

These names and controls are illustrative. They do not represent operational
EIC controls.

## Narad signal schema

A signal carries its EPICS-facing name, role, data type, engineering unit, and
description. For example:

```yaml
- id: inst:es12-bpm0:X-RB
	kind: Signal
	alias:
	- horizontal_position
	signal_role: Readback
	source_system: EPICS
	native_description: Measured horizontal beam position.
	canonical_signal_type: HorizontalBeamPosition
	quantity_kind: BeamPosition
	native_data_type: Float
	native_unit: mm
	access_protocol: EPICS PVAccess
```

A binding connects a component (`subject`) to a signal (`object`). The
`predicate` states whether the relationship is a readback, setpoint, or general
signal relationship:

```yaml
- id: inst:ES12_BPM0.horizontal_position_binding
	subject: inst:ES12_BPM0
	predicate: pals:has_readback_signal
	object: inst:es12-bpm0:X-RB
```

The binding is also the source of the generated EPICS alias. The signal-local
`alias` list is retained as Narad metadata but is not used as an EPICS alias;
labels such as `horizontal_position` repeat across devices and are not globally
unique.

## EPICS record mapping

The first translator version uses this closed mapping table:

| `native_data_type` | `signal_role` | EPICS record | Rationale |
| --- | --- | --- | --- |
| `Float` | `Readback` | `ai` | Analog measured value |
| `Float` | `Setpoint` | `ao` | Analog writable command |
| `String` | `Status` | `stringin` | Text state with no declared enumeration |
| `Float` | `RangeLimit` | Parent `ao` field | `.DRVL` or `.DRVH`, not a separate record |

Any other combination is a validation error. In particular, status signals do
not map to `bi` or `mbbi` because the YAML does not define finite states or
numeric state values.

### Record names and aliases

For standalone signals, `id` is preserved exactly as the EPICS record name, including the
`inst:` prefix:

```text
inst:es12-bpm0:X-RB
```

Each standalone signal binding `id` becomes an alias for the record referenced by its `object`.
EPICS reserves `.` as the separator between a record and one of its fields, so
the translator replaces every `.` in a binding ID with `:`:

```text
Narad binding ID: inst:ES12_BPM0.horizontal_position_binding
EPICS alias:      inst:ES12_BPM0:horizontal_position_binding
EPICS record:     inst:es12-bpm0:X-RB
```

The exact binding ID is retained in indexed record information items. This
makes the normalization reversible and supports more than one binding per
record:

```db
record(ai, "inst:es12-bpm0:X-RB") {
		alias("inst:ES12_BPM0:horizontal_position_binding")
		info(naradBindingId0, "inst:ES12_BPM0.horizontal_position_binding")
		field(DESC, "Measured horizontal beam position.")
		field(EGU, "mm")
		field(PREC, "3")
}
```

Record names and aliases must contain only EPICS-supported record-name
characters, must be no longer than 60 characters, and must be globally unique
within the IOC namespace. Alias uniqueness is checked after normalization.

### Field mapping

| Narad field | EPICS output | Policy |
| --- | --- | --- |
| Standalone signal `id` | Record name | Preserved exactly |
| Standalone signal binding `id` | `alias(...)` | Replace `.` with `:` |
| Standalone signal binding `id` | `info(naradBindingIdN, ...)` | Preserve exactly in source order |
| `native_description` | `DESC` | Truncate to EPICS' 40-character limit |
| `native_unit` | `EGU` | Emit for analog records unless value is `none` |
| `native_data_type: Float` | `PREC` | Default to `3` |
| `native_data_type: Float` | `VAL` | Simulation default `0` |
| `native_data_type: String` | `VAL` | Simulation default `UNKNOWN` |
| Standalone signals | `UDF` | Set to `0` so the simulation default is defined |

`RangeLimit` signals with `pals:has_limit_signal` bindings address `.DRVL` or
`.DRVH` on an existing `Float` magnet-current setpoint in amperes. They do not
create separate records. The mapper initializes declared fields to -50 A
(`DRVL`) and +50 A (`DRVH`), using the shared `FIELD_POLICIES` registry in
`iocs/field_policy.py`. The +/-50 A values are arbitrary guesses for the toy
simulation, not values derived from YAML, Tao, calibration, or equipment
specifications. They are not validated operating or safety limits. The YAML
currently supplies no numeric limit values, and per-device overrides are not
implemented.

Requiring these range signals to belong to current setpoints is the current
policy for `.DRVL`/`.DRVH`, not a general rule for `RangeLimit`. Other range
meanings, parent record types, and fields need explicit policies.
Undeclared limit fields are left at EPICS defaults.

Limit signal IDs and binding IDs are preserved on the parent record as
`naradDRVLSignalId` / `naradDRVHSignalId` and indexed
`naradDRVLBindingIdN` / `naradDRVHBindingIdN` info items. Limit bindings do not
create record aliases: access the fields through `record.DRVL` / `record.DRVH`.
The existing OPI displays continue to show standalone signals, and the Tao
bridge skips all field references. See [bridge mapping behavior](iocs/BRIDGE.md#signals-excluded-from-tao-mapping).

No display-range, alarm, or conversion fields are inferred (`HOPR`, `LOPR`,
`HIHI`, `HIGH`, `LOW`, `LOLO`, or their severities).

### Extending EPICS field support

Address parsing is independent of `signal_role`: `record.FIELD` identifies a
field reference; an ID without a dot identifies a standalone record. Field
suffixes must use uppercase EPICS identifier syntax. The parser validates that
the parent exists and that the field has a registered policy.

To support another field, add a `FieldPolicy` in `iocs/field_policy.py` with
compatible parent record types, signal and parent metadata requirements, and
an initialization value. The parser and mapper share that registry. Unsupported
fields fail validation rather than receiving guessed defaults. Binding predicate
roles remain validated separately; new semantic roles may require a predicate
entry in the parser. The Tao bridge skips all field references independently of
role. Add policy tests when introducing a field; EPICS device support and runtime
behavior still need to be considered for that field.

### Soft-record behavior

The initial generated database contains standalone soft records:

- No `INP` or `OUT` links are generated.
- No hardware device support is selected.
- Records retain the default passive scan behavior.
- Analog records initialize to `0`; string status records initialize to
	`UNKNOWN`.
- `UDF` initializes to `0`, preventing a startup `UDF/INVALID` alarm for these
	explicit simulation values.
- No simulated relationship between setpoints and readbacks is created.

Device support, hardware addressing, scan policy, and simulation behavior are
separate configuration concerns. The generated defaults are placeholders for
this standalone soft IOC, not measurements or values supplied by Narad.

## Validation contract

Generation must fail with an actionable error when any of these invariants is
violated:

1. Signal IDs are not unique.
2. Binding IDs are not unique.
3. A binding `subject` does not resolve to a component.
4. A binding `object` does not resolve to exactly one signal.
5. A binding predicate conflicts with the signal role:
	 - `pals:has_readback_signal` requires `Readback`.
	 - `pals:has_setpoint_signal` requires `Setpoint`.
	 - `pals:has_signal` is used for `Status` in the reference machine.
6. A signal data-type/role combination is not in the mapping table.
7. A record name or normalized alias violates EPICS naming or length rules.
8. A record name or normalized alias collides with any other record or alias.

The translator preserves source order so repeated generation from the same
input produces stable output.

## Command-line interface

Generate a database from a Narad description with the installed command:

```sh
pixi run narad-epics-generate \
	yaml-descriptions/toy_ring_narad_instance.yaml \
	--output generated/toy_ring.db
```

Validate parsing, references, mappings, record names, and aliases without
writing a file:

```sh
pixi run narad-epics-generate \
	yaml-descriptions/toy_ring_narad_instance.yaml \
	--check
```

### Direct Python

Pixi is not required at runtime. From the repository root, install the project
and its dependencies into the active Python environment:

```sh
python -m pip install -e .
```

For the PVAccess Tao machine service, install the optional simulation
dependencies as well:

```sh
python -m pip install -e ".[simulation]"
```

This installs p4p and PyTao. EPICS Base (`softIocPVA`) and Bmad's native
`libtao` shared library must still be installed separately.

Generate the database through the Python module entry point:

```sh
python -m iocs.generate_db \
	yaml-descriptions/toy_ring_narad_instance.yaml \
	--output generated/toy_ring.db
```

Run validation without writing a database:

```sh
python -m iocs.generate_db \
	yaml-descriptions/toy_ring_narad_instance.yaml \
	--check
```

Generation creates parent directories as needed and atomically replaces the
destination file only after rendering succeeds. YAML parsing, cross-reference
validation, EPICS mapping, and `.db` rendering remain separate testable stages.

## References

- [EPICS fields common to all record types](https://docs.epics-controls.org/projects/base/en/latest/dbCommonRecord.html)
- [EPICS analog input record](https://docs.epics-controls.org/projects/base/en/latest/aiRecord.html)
- [EPICS analog output record](https://docs.epics-controls.org/projects/base/en/latest/aoRecord.html)
- [EPICS string input record](https://docs.epics-controls.org/projects/base/en/latest/stringinRecord.html)
- [EPICS database definition syntax](https://docs.epics-controls.org/en/latest/appdevguide/databaseDefinition.html)
