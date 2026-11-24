"""Resolve facility-specific NARAD signal edges to simulator-independent ring targets."""

from dataclasses import dataclass
from typing import Literal

import narad_models as narad


@dataclass(frozen=True)
class ControllerVariable:
    controller: str
    variable: str


@dataclass(frozen=True)
class OrbitPosition:
    occurrence_id: str
    axis: Literal["x", "y"]


@dataclass(frozen=True)
class ConstantStatus:
    value: str


@dataclass(frozen=True)
class SignalBinding:
    signal: narad.Signal
    target: ControllerVariable | OrbitPosition | ConstantStatus
    writable: bool


POSITION_AXES: dict[str, Literal["x", "y"]] = {
    "HorizontalBeamPosition": "x",
    "VerticalBeamPosition": "y",
}


def bind_signals(facility: narad.Facility, supplies, statuses=None) -> list[SignalBinding]:
    """Bind the graph returned by build_graph using its explicit supply references."""
    statuses = statuses or {}
    signals = {signal.id: signal for signal in facility.signals}
    if len(signals) != len(facility.signals):
        raise ValueError("Duplicate NARAD signal ID")

    # Facility instrumentation convention: a readout is part of its BPM.
    bpms = {
        component.id
        for component in facility.components
        if isinstance(component, narad.BeamPositionMonitor)
    }
    readout_bpms: dict[str, set[str]] = {}
    for edge in facility.component_relations:
        if isinstance(edge, narad.IsPartOf) and edge.object in bpms:
            readout_bpms.setdefault(edge.subject, set()).add(edge.object)

    bindings = []
    bound_signals = set()
    writable_targets = set()

    for edge in facility.signal_bindings:
        if edge.object not in signals or edge.object in bound_signals:
            raise ValueError(f"Expected one signal record and binding for {edge.object}")

        signal = signals[edge.object]
        writable = isinstance(edge, narad.HasSetpointSignal)
        readback = isinstance(edge, narad.HasReadbackSignal)
        status = isinstance(edge, narad.HasSignal) and signal.signal_role == "Status"
        if not status and (
            not (writable or readback)
            or signal.signal_role != ("Setpoint" if writable else "Readback")
        ):
            raise ValueError(f"Unsupported or inconsistent signal role for {signal.id}")

        if status:
            entry = statuses.get(edge.subject)
            if signal.quantity_kind != "State" or entry is None or entry["id"] != signal.id:
                raise ValueError(f"No configured status for {signal.id}")
            target = ConstantStatus(entry["value"])

        elif signal.quantity_kind == "ElectricCurrent":
            if edge.subject not in supplies:
                raise ValueError(f"No PALS controller reference for supply {edge.subject}")
            knob = supplies[edge.subject]
            target = ControllerVariable(knob["controller"], knob["variable"])

        elif signal.quantity_kind == "BeamPosition" and readback:
            candidates = readout_bpms.get(edge.subject, set())
            axis = POSITION_AXES.get(signal.canonical_signal_type)
            if len(candidates) != 1 or axis is None:
                raise ValueError(
                    f"Expected a BPM and position axis for {signal.id}; "
                    f"found BPMs {sorted(candidates)} and type {signal.canonical_signal_type}"
                )
            target = OrbitPosition(next(iter(candidates)), axis)

        else:
            raise ValueError(f"Unsupported signal quantity or role for {signal.id}")

        if writable:
            if target in writable_targets:
                raise ValueError(f"Multiple setpoints target {target}")
            writable_targets.add(target)

        bindings.append(SignalBinding(signal, target, writable))
        bound_signals.add(signal.id)

    unbound = signals.keys() - bound_signals
    if unbound:
        raise ValueError(f"Signals without binding edges: {sorted(unbound)}")

    return bindings
