"""Tao actions for controller current and closed-orbit position."""

import math

from lume.actions import ReadOnlyActionMixin, WritableActionMixin
from lume.variables import ScalarVariable, StrVariable


class ControllerScalar(ScalarVariable, WritableActionMixin):
    element_name: str
    property_name: str

    def validate_value(self, value, config=None):
        super().validate_value(value, config)
        if not math.isfinite(value):
            raise ValueError("Control value must be finite")

    def _get(self, simulator):
        return float(simulator.ele_control_var(self.element_name)[self.property_name])

    def _set(self, simulator, value):
        simulator.cmd(f"set ele {self.element_name} {self.property_name} = {float(value):.17g}")


class OrbitCoordinate(ScalarVariable, ReadOnlyActionMixin):
    element_name: str
    component: int
    scale: float

    def _get(self, simulator):
        orbit = simulator.lat_list(self.element_name, f"orbit.vec.{self.component}")
        return float(orbit[0]) * self.scale


class StaticStatus(StrVariable, ReadOnlyActionMixin):
    def _get(self, simulator):
        return self.default_value
