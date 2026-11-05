from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class NaradSignal:
    id: str
    kind: str
    aliases: tuple[str, ...]
    signal_role: str
    source_system: str
    native_description: str
    canonical_signal_type: str
    quantity_kind: str
    native_data_type: str
    native_unit: str
    access_protocol: str


@dataclass(frozen=True, slots=True)
class SignalBinding:
    id: str
    subject: str
    predicate: str
    object: str

    @property
    def epics_alias(self) -> str:
        return self.id.replace(".", ":")


@dataclass(frozen=True, slots=True)
class EpicsRecord:
    record_type: str
    name: str
    aliases: tuple[str, ...]
    info_items: tuple[tuple[str, str], ...]
    fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class NaradDescription:
    source: Path
    component_ids: frozenset[str]
    signals: tuple[NaradSignal, ...]
    bindings: tuple[SignalBinding, ...]
    signal_by_id: Mapping[str, NaradSignal] = field(repr=False)

    @classmethod
    def create(
        cls,
        *,
        source: Path,
        component_ids: set[str],
        signals: list[NaradSignal],
        bindings: list[SignalBinding],
    ) -> NaradDescription:
        signal_by_id = MappingProxyType({signal.id: signal for signal in signals})
        return cls(
            source=source,
            component_ids=frozenset(component_ids),
            signals=tuple(signals),
            bindings=tuple(bindings),
            signal_by_id=signal_by_id,
        )