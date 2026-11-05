"""PV access to one persistent Tao machine; currents in A, positions in m."""

from pathlib import Path
import math

from pytao import Tao


class RingMachine:
    def __init__(self, lattice: Path):
        self.tao = Tao(lattice_file=str(lattice.resolve()), noinit=True,
                       nostartup=True, noplot=True)

        self.correctors = {}
        for overlay in ("steering_h", "steering_v"):
            for variable in self.tao.ele_control_var(overlay):
                self.correctors[f"{overlay}:{variable.lower()}"] = (overlay, variable)

        self.quadrupoles = {}
        for variable in self.tao.ele_control_var("quad_families"):
            self.quadrupoles[f"quad_families:{variable.lower()}"] = ("quad_families", variable)

        self.sextupoles = {}
        for variable in self.tao.ele_control_var("sext_families"):
            self.sextupoles[f"sext_families:{variable.lower()}"] = ("sext_families", variable)

        self.bpms = {}
        for name in self.tao.lat_list("monitor::*", "ele.name"):
            for plane, component in (("x", 1), ("y", 3)):
                self.bpms[f"{name.lower()}:{plane}"] = (name, component)

    def list_pvs(self):
        return {"correctors_A": list(self.correctors),
                "quads_A": list(self.quadrupoles),
                "sexts_A": list(self.sextupoles),
                "bpms_m": list(self.bpms)}

    def get(self, pv: str) -> float:
        for currents in (self.correctors, self.quadrupoles, self.sextupoles):
            if pv in currents:
                overlay, variable = currents[pv]
                return float(self.tao.ele_control_var(overlay)[variable])
        name, component = self.bpms[pv]
        # Closed-ring machine orbit at the downstream end of the finite BPM.
        return float(self.tao.lat_list(name, f"orbit.vec.{component}")[0])

    def set(self, pv: str, value: float) -> float:
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
