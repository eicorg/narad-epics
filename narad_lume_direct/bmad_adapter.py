"""Build a LUMEBmadModel from the ring's resolved signal bindings."""

from pathlib import Path
from tempfile import TemporaryDirectory

from lume_bmad.model import LUMEBmadModel
import palsparserpy as pals
from pytao import Tao
import yaml

from binding import ConstantStatus, ControllerVariable, OrbitPosition, bind_signals
from bmad_actions import ControllerScalar, OrbitCoordinate, StaticStatus
from graph import build_graph, expanded_ring


ORBIT_COMPONENT = {"x": 1, "y": 3}
POSITION_SCALE = {"m": 1.0, "mm": 1000.0}


def tao_occurrences(tao, occurrence_ids, elements):
    """Pair PALS occurrences with Tao branch/index selectors in tracking order."""
    expected = [
        "BEGINNING" if fields["kind"] == "BeginningEle" else name.upper()
        for name, fields in elements
    ]
    names = list(tao.lat_list("0>>*", "ele.name"))
    indices = tao.lat_list("0>>*", "ele.ix_ele")

    if names != expected + ["END"] or len(occurrence_ids) != len(expected):
        raise ValueError("Tao tracking order differs from the expanded PALS ring")

    return {
        occurrence_id: f"0>>{index}"
        for occurrence_id, index in zip(occurrence_ids, indices)
    }


def create_model(bmad_file: Path, bindings, occurrence_ids, elements):
    """Attach the resolved bindings directly to Tao as LUME actions."""
    tao = Tao(lattice_file=str(bmad_file), noinit=True, nostartup=True, noplot=True)
    if tao.branch1(1, 0)["param_geometry"] != "Closed":
        raise ValueError("BPM orbit bindings require a closed Bmad ring")

    occurrences = tao_occurrences(tao, occurrence_ids, elements)
    actions = []

    for binding in bindings:
        signal, target = binding.signal, binding.target
        if isinstance(target, ConstantStatus):
            if signal.native_data_type != "String" or binding.writable:
                raise ValueError(f"Expected a read-only string status for {signal.id}")
            actions.append(StaticStatus(
                name=signal.id, default_value=target.value, read_only=True,
            ))
            continue

        if signal.native_data_type != "Float":
            raise ValueError(f"Expected a scalar float signal for {signal.id}")

        if isinstance(target, ControllerVariable):
            if signal.native_unit != "A":
                raise ValueError(f"Expected current in amperes for {signal.id}")
            controller = target.controller.upper()
            variable = target.variable.upper()
            values = tao.ele_control_var(controller)
            if variable not in values:
                raise ValueError(f"Tao did not expose {controller}.{variable}")

            actions.append(
                ControllerScalar(
                    name=signal.id,
                    unit=signal.native_unit,
                    element_name=controller,
                    property_name=variable,
                    default_value=float(values[variable]),
                    read_only=not binding.writable,
                )
            )
        elif isinstance(target, OrbitPosition):
            if signal.native_unit not in POSITION_SCALE:
                raise ValueError(f"Unsupported orbit position unit for {signal.id}")
            selector = occurrences[target.occurrence_id]
            component = ORBIT_COMPONENT[target.axis]
            scale = POSITION_SCALE[signal.native_unit]
            actions.append(
                OrbitCoordinate(
                    name=signal.id,
                    unit=signal.native_unit,
                    element_name=selector,
                    component=component,
                    scale=scale,
                    default_value=float(tao.lat_list(selector, f"orbit.vec.{component}")[0]) * scale,
                    read_only=True,
                )
            )
        else:
            raise ValueError(f"Unsupported Bmad target for {signal.id}")

    return LUMEBmadModel(tao=tao, action_variables=actions)


def build_model(lattice_file: Path, hardware_file: Path):
    """Construct the Bmad model and retain the NARAD bindings for publication."""
    lattices = pals.parse_and_expand_pals(lattice_file, problems="none")
    hardware = yaml.safe_load(hardware_file.read_text())
    graph, occurrence_ids = build_graph(lattices, hardware)
    bindings = bind_signals(graph.facility, hardware["supplies"], hardware.get("statuses"))
    _, _, elements, _ = expanded_ring(lattices)

    with TemporaryDirectory(prefix="pals-bmad-") as folder:
        bmad_file = Path(folder) / "ring.bmad"
        pals.write_bmad_file(pals.pals_to_bmad(lattices.combined), bmad_file)
        model = create_model(bmad_file, bindings, occurrence_ids, elements)

    return model, bindings
