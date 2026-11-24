"""Project the toy ring into objects generated from the upstream NARAD schema."""

from collections import Counter
from pathlib import Path
import re

import palsparserpy as pals
import yaml

# Generated from the upstream LinkML schema. See the README for the command.
import narad_models as narad

HERE = Path(__file__).resolve().parent

# Each PALS kind maps to a NARAD component class and its function for this ring.
PALS_KIND_TO_NARAD = {
    "BeginningEle": (narad.BeginningEle, "Mark"),
    "Drift": (narad.Drift, "DriftSpace"),
    "Bend": (narad.Bend, "Steering"),
    "Quadrupole": (narad.Quadrupole, "Focusing"),
    "Kicker": (narad.Kicker, "Steering"),
    "Sextupole": (narad.Sextupole, "Focusing"),
    "Marker": (narad.Marker, "Mark"),
    "Instrument": (narad.DiagnosticDevice, "Measurement"),
}


def supply_targets(lattices, line, occurrence_ids):
    """Index the ring's directly driven magnetic parameters by PALS knob."""
    targets = {}

    for index, component_id in enumerate(occurrence_ids):
        element = line[index].child(0)
        if "MagneticMultipoleP" not in element:
            continue

        multipoles = element["MagneticMultipoleP"]
        for field in multipoles.keys():
            for expression in pals.controller_expressions(lattices, multipoles[field]):
                controller = pals.get_parent(pals.get_parent(pals.get_parent(expression)))
                controller_id = pals.node_key(controller)
                # Match complete identifiers in the PALS expression.
                identifiers = set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", expression.value))
                for variable in controller["variables"].keys():
                    if variable in identifiers:
                        targets.setdefault((controller_id, variable), {}).setdefault(
                            component_id, None,
                        )

    return targets


def expanded_ring(lattices):
    if lattices.problems:
        raise ValueError(f"PALS expansion failed: {lattices.problems}")

    ((lattice_id, lattice),) = yaml.safe_load(lattices.expanded.to_yaml_string()).items()
    (branch,) = lattice["branches"]
    ((branch_id, layout),) = branch.items()
    elements = [next(iter(entry.items())) for entry in layout["line"]]
    expanded_line = lattices.expanded[lattice_id]["branches"][0][branch_id]["line"]
    return branch_id, layout, elements, expanded_line


def build_graph(lattices, hardware):
    """Return the typed graph and PALS component IDs in tracking order."""
    branch_id, layout, elements, expanded_line = expanded_ring(lattices)
    counts = Counter(name for name, _ in elements)

    # hardware.yaml identifies which PALS Instruments are BPMs.
    bpm_elements = set(hardware["bpm_readouts"].values())
    components = []

    for index, (name, fields) in enumerate(elements):
        kind = fields["kind"]
        if kind == "Instrument" and name in bpm_elements:
            cls, function = narad.BeamPositionMonitor, "BeamPositionMeasurement"
        else:
            cls, function = PALS_KIND_TO_NARAD[kind]

        component_id = name if counts[name] == 1 else f"{name}@{index}"
        components.append(
            cls(
                id=component_id,
                native_types=[kind],
                functions=[function],
                beamline_relation="Inline",
            )
        )

    occurrence_ids = tuple(component.id for component in components)
    targets = supply_targets(lattices, expanded_line, occurrence_ids)
    relations = [
        narad.Precedes(
            id=f"order:{index}",
            subject=left,
            object=right,
            context="beamline_order",
            beamline_context=branch_id,
        )
        for index, (left, right) in enumerate(zip(occurrence_ids, occurrence_ids[1:]))
    ]
    signals = []
    bindings = []
    signal_ids = hardware.get("signal_ids", {})
    statuses = hardware.get("statuses", {})
    if unknown_supplies := statuses.keys() - hardware["supplies"].keys():
        raise ValueError(f"Status signals reference unknown supplies: {sorted(unknown_supplies)}")

    # hardware.yaml selects the knob. PALS supplies its magnet targets.
    for supply, knob in hardware["supplies"].items():
        controller, variable = knob["controller"], knob["variable"]
        magnets = targets.get((controller, variable))
        if not magnets:
            raise ValueError(f"Supply {supply} has no direct magnet targets for {controller}.{variable}")

        components.append(narad.SupportingFacilityComponent(
            id=supply,
            facility_functions=["PowerSupply"],
            beamline_relation="SupportingFacility",
        ))

        for magnet in magnets:
            relations.append(narad.Controls(
                id=f"{supply}:controls:{magnet}",
                subject=supply,
                object=magnet,
                context="installation_mounting",
            ))

        for edge_type, role, suffix in [
            (narad.HasSetpointSignal, "Setpoint", "SP"),
            (narad.HasReadbackSignal, "Readback", "RB"),
        ]:
            default_id = f"{supply}:I:{suffix}"
            signal_id = signal_ids.get(default_id, default_id)
            signals.append(narad.Signal(
                id=signal_id,
                source_system="Simulation",
                signal_role=role,
                canonical_signal_type=f"MagnetCurrent{role}",
                quantity_kind="ElectricCurrent",
                native_data_type="Float",
                native_unit="A",
            ))
            bindings.append(edge_type(id=f"edge:{signal_id}", subject=supply, object=signal_id))

        if supply in statuses:
            status_id = statuses[supply]["id"]
            signals.append(narad.Signal(
                id=status_id,
                source_system="Simulation",
                signal_role="Status",
                canonical_signal_type="Status",
                quantity_kind="State",
                native_data_type="String",
                native_unit="none",
            ))
            bindings.append(narad.HasSignal(
                id=f"edge:{status_id}",
                subject=supply,
                object=status_id,
            ))

    # Each readout owns both position signals and belongs to one BPM occurrence.
    for readout, bpm in hardware["bpm_readouts"].items():
        if bpm not in occurrence_ids:
            raise ValueError(f"Readout {readout} references unknown occurrence {bpm}")
        components.append(narad.SupportingFacilityComponent(
            id=readout,
            facility_functions=["Diagnostics"],
            beamline_relation="SupportingFacility",
        ))
        relations.append(narad.IsPartOf(
            id=f"{readout}:part_of:{bpm}",
            subject=readout,
            object=bpm,
            context="containment",
        ))

        for axis, canonical in [("X", "HorizontalBeamPosition"), ("Y", "VerticalBeamPosition")]:
            default_id = f"{readout}:{axis}:RB"
            signal_id = signal_ids.get(default_id, default_id)
            signals.append(narad.Signal(
                id=signal_id,
                source_system="Simulation",
                signal_role="Readback",
                canonical_signal_type=canonical,
                quantity_kind="BeamPosition",
                native_data_type="Float",
                native_unit="mm",
            ))
            bindings.append(narad.HasReadbackSignal(
                id=f"edge:{signal_id}",
                subject=readout,
                object=signal_id,
            ))

    graph = narad.PALSAccelerator(
        created_date="2026-11-23",
        change_log=[narad.ChangeLogEntryClass(
            change_date="2026-11-23",
            instance_version="0.0.0",
            summary="Initial creation",
        )],
        facility=narad.Facility(
            components=components,
            signals=signals,
            signal_bindings=bindings,
            component_relations=relations,
            beamlines=[narad.BeamLine(
                id=branch_id,
                periodic=layout.get("periodic", False),
                functions=["BeamLineSection"],
                beamline_relation="Inline",
            )],
        ),
    )
    return graph, occurrence_ids


if __name__ == "__main__":
    lattice = pals.parse_and_expand_pals(HERE / "ring.pals.yaml", problems="none")
    hardware = yaml.safe_load((HERE / "hardware.yaml").read_text())
    graph, _ = build_graph(lattice, hardware)
    print(yaml.safe_dump(graph.model_dump(mode="json", exclude_none=True), sort_keys=False))
