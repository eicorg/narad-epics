"""PV adapter for one persistent Tao model; currents in A, positions in m.

Tao control-variable and element names are exposed as the exact EPICS names
used by the toy-ring database. Tao itself remains the owner of model state.
"""

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_PLANE_BY_OVERLAY = {"steering_h": "H", "steering_v": "V"}


def _epics_device(name: str) -> str:
    """Convert a Tao element/control name to the toy-ring device token."""

    return name.lower().replace("_", "-")


class RingModel:
    """Keep one Tao session alive and expose its controls as EPICS PVs."""

    def __init__(self, lattice: Path | None = None, *, tao: Any | None = None):
        """Open ``lattice`` with PyTao, or use an injected Tao-compatible object."""

        if tao is None:
            if lattice is None:
                raise ValueError("lattice is required when tao is not supplied")
            try:
                from pytao import Tao
            except ImportError as error:
                raise RuntimeError(
                    "PyTao is required; install the simulation dependencies"
                ) from error
            tao = Tao(
                lattice_file=str(lattice.resolve()),
                noinit=True,
                nostartup=True,
                noplot=True,
            )

        self.tao = tao
        self.correctors: dict[str, tuple[str, str]] = {}
        self.epics_setpoints: dict[str, str] = {}
        self.epics_current_readbacks: dict[str, str] = {}
        self.epics_statuses: dict[str, str] = {}
        for overlay in ("steering_h", "steering_v"):
            for variable in self.tao.ele_control_var(overlay):
                model_pv = f"{overlay}:{variable.lower()}"
                self.correctors[model_pv] = (overlay, variable)
                device = _epics_device(variable)
                plane = _PLANE_BY_OVERLAY[overlay]
                prefix = f"inst:{device}:PS:{plane}"
                setpoint = f"{prefix}:Current-SP"
                self.epics_setpoints[setpoint] = model_pv
                self.epics_current_readbacks[f"{prefix}:Current-RB"] = model_pv
                self.epics_statuses[f"{prefix}:Status"] = "READY"

        self.quadrupoles: dict[str, tuple[str, str]] = {}
        for variable in self.tao.ele_control_var("quad_families"):
            self.quadrupoles[f"quad_families:{variable.lower()}"] = ("quad_families", variable)
        self.sextupoles: dict[str, tuple[str, str]] = {}
        for variable in self.tao.ele_control_var("sext_families"):
            self.sextupoles[f"sext_families:{variable.lower()}"] = ("sext_families", variable)
        self.bpms: dict[str, tuple[str, int]] = {}
        self.epics_bpm_readbacks: dict[str, str] = {}
        self._bpm_names = tuple(self.tao.lat_list("monitor::*", "ele.name"))
        for name in self._bpm_names:
            for plane, component in (("x", 1), ("y", 3)):
                model_pv = f"{name.lower()}:{plane}"
                self.bpms[model_pv] = (name, component)
                epics_pv = f"inst:{_epics_device(name)}:{plane.upper()}-RB"
                self.epics_bpm_readbacks[epics_pv] = model_pv

    @property
    def setpoint_pvs(self) -> tuple[str, ...]:
        """Return the EPICS setpoints that the service should monitor."""

        return tuple(self.epics_setpoints)

    def list_pvs(self) -> dict[str, list[str]]:
        """List the physicist-facing Tao keys grouped by quantity."""

        return {"correctors_A": list(self.correctors),
                "quads_A": list(self.quadrupoles),
                "sexts_A": list(self.sextupoles),
                "bpms_m": list(self.bpms)}

    def get(self, pv: str) -> float:
        """Read a Tao-facing current or BPM key."""

        for currents in (self.correctors, self.quadrupoles, self.sextupoles):
            if pv in currents:
                overlay, variable = currents[pv]
                return float(self.tao.ele_control_var(overlay)[variable])
        name, component = self.bpms[pv]
        # Closed-ring model orbit at the downstream end of the finite BPM.
        return float(self.tao.lat_list(name, f"orbit.vec.{component}")[0])

    def set(self, pv: str, value: float) -> float:
        """Set a writable Tao-facing current key and return its model value."""

        if pv in self.bpms:
            raise ValueError("BPM PVs are read-only")
        for currents in (self.correctors, self.quadrupoles, self.sextupoles):
            if pv in currents:
                overlay, variable = currents[pv]
                break
        else:
            raise KeyError(pv)
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Current must be finite")
        # Tao recalculates the closed orbit after this change.
        self.tao.cmd(f"set ele {overlay} {variable} = {value:.17g}")
        return self.get(pv)

    def apply_setpoint(self, pv: str, value: float) -> None:
        """Apply an EPICS setpoint to the corresponding Tao control variable."""

        try:
            model_pv = self.epics_setpoints[pv]
        except KeyError as error:
            raise KeyError(f"unknown EPICS setpoint {pv!r}") from error
        self.set(model_pv, value)

    def apply_setpoints(self, values: Mapping[str, float]) -> None:
        """Apply a startup setpoint snapshot with one Tao lattice recalculation."""

        commands = []
        for pv, value in values.items():
            try:
                overlay, variable = self.correctors[self.epics_setpoints[pv]]
            except KeyError as error:
                raise KeyError(f"unknown EPICS setpoint {pv!r}") from error
            numeric_value = float(value)
            if not math.isfinite(numeric_value):
                raise ValueError(f"setpoint {pv!r} must be finite")
            commands.append(
                f"set ele {overlay} {variable} = {numeric_value:.17g}"
            )

        if commands:
            self.tao.cmds(commands)

    def readbacks(self, changed_setpoint: str | None = None) -> Mapping[str, float | str]:
        """Return EPICS outputs after a change, or a full startup snapshot.

        Every corrector change can alter the closed orbit, so all BPMs are
        returned. Only the affected current readback is returned after a
        change; a startup snapshot includes all currents and statuses.
        """

        values: dict[str, float | str] = {}
        if changed_setpoint is None:
            current_model_pvs = self.epics_current_readbacks.items()
            values.update(self.epics_statuses)
        else:
            changed_model_pv = self.epics_setpoints[changed_setpoint]
            current_model_pvs = (
                (pv, model_pv)
                for pv, model_pv in self.epics_current_readbacks.items()
                if model_pv == changed_model_pv
            )

        values.update(
            (epics_pv, self.get(model_pv))
            for epics_pv, model_pv in current_model_pvs
        )
        for plane, component in (("X", 1), ("Y", 3)):
            orbit = self.tao.lat_list("monitor::*", f"orbit.vec.{component}")
            if len(orbit) != len(self._bpm_names):
                raise RuntimeError(
                    f"Tao returned {len(orbit)} {plane} values for "
                    f"{len(self._bpm_names)} BPMs"
                )
            values.update(
                (f"inst:{_epics_device(name)}:{plane}-RB", float(value))
                for name, value in zip(self._bpm_names, orbit, strict=True)
            )
        return values
