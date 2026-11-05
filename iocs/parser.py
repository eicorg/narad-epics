from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .errors import NaradValidationError, ValidationIssue
from .models import NaradDescription, NaradSignal, SignalBinding


_EPICS_NAME = re.compile(r"^[A-Za-z0-9_+\-:\[\]<>;]+$")
_MAX_EPICS_NAME_LENGTH = 60
_RECORD_TYPES = {
    ("Float", "Readback"): "ai",
    ("Float", "Setpoint"): "ao",
    ("String", "Status"): "stringin",
}
_PREDICATE_ROLES = {
    "pals:has_readback_signal": "Readback",
    "pals:has_setpoint_signal": "Setpoint",
    "pals:has_signal": "Status",
}


def load_narad_description(path: str | Path) -> NaradDescription:
    source = Path(path).resolve()
    issues: list[ValidationIssue] = []

    try:
        raw_document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise NaradValidationError(
            source, [ValidationIssue("document", f"invalid YAML: {error}")]
        ) from error

    document = _mapping(raw_document, "document", issues)
    facility = _mapping(document.get("facility"), "facility", issues)
    component_ids = _parse_component_ids(facility.get("components"), issues)
    signals = _parse_signals(facility.get("signals"), issues)
    bindings = _parse_bindings(facility.get("signal_bindings"), issues)

    _validate_description(component_ids, signals, bindings, issues)
    if issues:
        raise NaradValidationError(source, issues)

    return NaradDescription.create(
        source=source,
        component_ids=component_ids,
        signals=signals,
        bindings=bindings,
    )


def _parse_component_ids(value: Any, issues: list[ValidationIssue]) -> set[str]:
    components = _list(value, "facility.components", issues)
    component_ids: set[str] = set()
    for index, value in enumerate(components):
        location = f"facility.components[{index}]"
        component = _mapping(value, location, issues)
        component_id = _text(component, "id", location, issues)
        if component_id:
            component_ids.add(component_id)
    return component_ids


def _parse_signals(value: Any, issues: list[ValidationIssue]) -> list[NaradSignal]:
    raw_signals = _list(value, "facility.signals", issues)
    signals: list[NaradSignal] = []
    for index, value in enumerate(raw_signals):
        location = f"facility.signals[{index}]"
        signal = _mapping(value, location, issues)
        aliases = _text_list(signal.get("alias"), f"{location}.alias", issues)
        fields = {
            name: _text(signal, name, location, issues)
            for name in (
                "id",
                "kind",
                "signal_role",
                "source_system",
                "native_description",
                "canonical_signal_type",
                "quantity_kind",
                "native_data_type",
                "native_unit",
                "access_protocol",
            )
        }
        if not all(fields.values()):
            continue
        if fields["kind"] != "Signal":
            issues.append(
                ValidationIssue(
                    f"{location}.kind",
                    f"expected 'Signal', got {fields['kind']!r}",
                )
            )
        signals.append(
            NaradSignal(
                id=fields["id"],
                kind=fields["kind"],
                aliases=tuple(aliases),
                signal_role=fields["signal_role"],
                source_system=fields["source_system"],
                native_description=fields["native_description"],
                canonical_signal_type=fields["canonical_signal_type"],
                quantity_kind=fields["quantity_kind"],
                native_data_type=fields["native_data_type"],
                native_unit=fields["native_unit"],
                access_protocol=fields["access_protocol"],
            )
        )
    return signals


def _parse_bindings(value: Any, issues: list[ValidationIssue]) -> list[SignalBinding]:
    raw_bindings = _list(value, "facility.signal_bindings", issues)
    bindings: list[SignalBinding] = []
    for index, value in enumerate(raw_bindings):
        location = f"facility.signal_bindings[{index}]"
        binding = _mapping(value, location, issues)
        fields = {
            name: _text(binding, name, location, issues)
            for name in ("id", "subject", "predicate", "object")
        }
        if all(fields.values()):
            bindings.append(SignalBinding(**fields))
    return bindings


def _validate_description(
    component_ids: set[str],
    signals: list[NaradSignal],
    bindings: list[SignalBinding],
    issues: list[ValidationIssue],
) -> None:
    signal_by_id: dict[str, NaradSignal] = {}
    for index, signal in enumerate(signals):
        location = f"facility.signals[{index}].id"
        if signal.id in signal_by_id:
            issues.append(ValidationIssue(location, f"duplicate signal ID {signal.id!r}"))
        else:
            signal_by_id[signal.id] = signal
        _validate_epics_name(signal.id, location, "record name", issues)
        combination = (signal.native_data_type, signal.signal_role)
        if combination not in _RECORD_TYPES:
            issues.append(
                ValidationIssue(
                    f"facility.signals[{index}]",
                    "unsupported signal mapping "
                    f"native_data_type={signal.native_data_type!r}, "
                    f"signal_role={signal.signal_role!r}",
                )
            )

    binding_ids: set[str] = set()
    namespace = set(signal_by_id)
    for index, binding in enumerate(bindings):
        location = f"facility.signal_bindings[{index}]"
        if binding.id in binding_ids:
            issues.append(
                ValidationIssue(f"{location}.id", f"duplicate binding ID {binding.id!r}")
            )
        binding_ids.add(binding.id)

        if binding.subject not in component_ids:
            issues.append(
                ValidationIssue(
                    f"{location}.subject",
                    f"component {binding.subject!r} does not exist",
                )
            )

        signal = signal_by_id.get(binding.object)
        if signal is None:
            issues.append(
                ValidationIssue(
                    f"{location}.object",
                    f"signal {binding.object!r} does not exist",
                )
            )

        expected_role = _PREDICATE_ROLES.get(binding.predicate)
        if expected_role is None:
            issues.append(
                ValidationIssue(
                    f"{location}.predicate",
                    f"unsupported binding predicate {binding.predicate!r}",
                )
            )
        elif signal is not None and signal.signal_role != expected_role:
            issues.append(
                ValidationIssue(
                    f"{location}.predicate",
                    f"{binding.predicate!r} requires signal role "
                    f"{expected_role!r}, got {signal.signal_role!r}",
                )
            )

        alias = binding.epics_alias
        _validate_epics_name(alias, f"{location}.id", "normalized alias", issues)
        if alias in namespace:
            issues.append(
                ValidationIssue(
                    f"{location}.id",
                    f"EPICS alias collision after normalization: {alias!r}",
                )
            )
        namespace.add(alias)


def _validate_epics_name(
    value: str,
    location: str,
    label: str,
    issues: list[ValidationIssue],
) -> None:
    if len(value) > _MAX_EPICS_NAME_LENGTH:
        issues.append(
            ValidationIssue(
                location,
                f"EPICS {label} exceeds {_MAX_EPICS_NAME_LENGTH} characters: {value!r}",
            )
        )
    if not _EPICS_NAME.fullmatch(value):
        issues.append(
            ValidationIssue(location, f"invalid EPICS {label} characters in {value!r}")
        )


def _mapping(
    value: Any, location: str, issues: list[ValidationIssue]
) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    issues.append(ValidationIssue(location, "expected a mapping"))
    return {}


def _list(value: Any, location: str, issues: list[ValidationIssue]) -> list[Any]:
    if isinstance(value, list):
        return value
    issues.append(ValidationIssue(location, "expected a list"))
    return []


def _text(
    mapping: Mapping[str, Any],
    name: str,
    location: str,
    issues: list[ValidationIssue],
) -> str:
    value = mapping.get(name)
    if isinstance(value, str) and value:
        return value
    issues.append(ValidationIssue(f"{location}.{name}", "expected a non-empty string"))
    return ""


def _text_list(value: Any, location: str, issues: list[ValidationIssue]) -> list[str]:
    values = _list(value, location, issues)
    result: list[str] = []
    for index, item in enumerate(values):
        if isinstance(item, str) and item:
            result.append(item)
        else:
            issues.append(
                ValidationIssue(f"{location}[{index}]", "expected a non-empty string")
            )
    return result