"""Shared record mappings and field compatibility/initialization policies.

Field addresses are parsed independently of roles. The registry below describes
only the mappings currently implemented by this repository; it is not a complete
EPICS field catalog or a universal interpretation of Narad signal roles.

Current assumptions:
- Only DRVL/DRVH are registered, for Float magnet-current RangeLimit signals in A.
- Their parent must currently map to ao and describe a MagnetCurrentSetpoint in A.
  This is our present drive-limit policy, not a rule that every RangeLimit must
  belong to a setpoint. Other range meanings/parent types need their own policy.
- The -50/+50 A initialization values are arbitrary guesses chosen for the toy
  simulation. They are not derived from YAML, Tao, calibration, or equipment
  specifications, and are not validated operating or safety limits.
- Only fields explicitly declared in YAML receive these values. There is no
  per-device override or numeric limit-value parsing from YAML yet.
"""
from dataclasses import dataclass
from types import MappingProxyType

from .models import NaradSignal


RECORD_TYPES = MappingProxyType({
    ("Float", "Readback"): "ai",
    ("Float", "Setpoint"): "ao",
    ("String", "Status"): "stringin",
})


@dataclass(frozen=True, slots=True)
class FieldPolicy:
    """Repository policy for a supported field, not an EPICS schema definition.

    Requirements pair Narad attributes with expected values. These equality
    checks express current mapping assumptions. ``initial_value`` is the fixed
    value emitted by the mapper; its physical validity is not checked here.
    """

    parent_record_types: tuple[str, ...]
    signal_requirements: tuple[tuple[str, str], ...]
    parent_requirements: tuple[tuple[str, str], ...]
    initial_value: str

    def validation_errors(self, signal: NaradSignal, parent: NaradSignal) -> tuple[str, ...]:
        errors = []
        record_type = RECORD_TYPES.get((parent.native_data_type, parent.signal_role))
        if parent.record_field is not None or record_type not in self.parent_record_types:
            errors.append(f"field requires parent record type in {self.parent_record_types}")
        for label, item, requirements in (
            ("field signal", signal, self.signal_requirements),
            ("parent", parent, self.parent_requirements),
        ):
            for attribute, expected in requirements:
                if getattr(item, attribute) != expected:
                    errors.append(f"{label} requires {attribute}={expected!r}")
        return tuple(errors)


# Current supported interpretation of drive limits; extend for other meanings.
_CURRENT_LIMIT_REQUIREMENTS = (
    ("native_data_type", "Float"),
    ("signal_role", "RangeLimit"),
    ("canonical_signal_type", "MagnetCurrentRange"),
    ("quantity_kind", "ElectricCurrent"),
    ("native_unit", "A"),
)
_CURRENT_PARENT_REQUIREMENTS = (
    ("canonical_signal_type", "MagnetCurrentSetpoint"),
    ("quantity_kind", "ElectricCurrent"),
    ("native_unit", "A"),
)
# Arbitrary toy-simulation guesses in A, shared by all matching declared fields.
FIELD_POLICIES = MappingProxyType({
    field: FieldPolicy(
        parent_record_types=("ao",),
        signal_requirements=_CURRENT_LIMIT_REQUIREMENTS,
        parent_requirements=_CURRENT_PARENT_REQUIREMENTS,
        initial_value=value,
    )
    for field, value in (("DRVL", "-50"), ("DRVH", "50"))
})
