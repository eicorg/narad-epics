"""Map validated Narad signals to renderer-neutral EPICS records.

This module owns record-type selection, aliases, metadata, display fields, and
the explicit defaults used by the repository's simulation IOC.
"""

from __future__ import annotations

from collections import defaultdict

from .field_policy import FIELD_POLICIES, RECORD_TYPES
from .models import EpicsRecord, NaradDescription, SignalBinding


_DESCRIPTION_LENGTH = 40
_DEFAULT_PRECISION = "3"
_NUMERIC_SIMULATION_VALUE = "0"
_STRING_SIMULATION_VALUE = "UNKNOWN"


def map_description(description: NaradDescription) -> tuple[EpicsRecord, ...]:
    """Map standalone signals to records and field references to parent fields.

    Binding IDs become EPICS aliases and metadata. Numeric records start at
    zero, string statuses at ``UNKNOWN``, and ``UDF=0`` marks those simulation
    defaults as defined.
    """

    bindings_by_signal: dict[str, list[SignalBinding]] = defaultdict(list)
    for binding in description.bindings:
        bindings_by_signal[binding.object].append(binding)

    fields_by_record = defaultdict(list)
    for signal in description.signals:
        if signal.record_field is not None:
            fields_by_record[signal.record_name].append(signal)

    records: list[EpicsRecord] = []
    for signal in description.signals:
        if signal.record_field is not None:
            continue
        bindings = bindings_by_signal[signal.id]
        fields = [("DESC", signal.native_description[:_DESCRIPTION_LENGTH])]
        if signal.native_data_type == "Float":
            if signal.native_unit != "none":
                fields.append(("EGU", signal.native_unit))
            fields.append(("PREC", _DEFAULT_PRECISION))
            fields.append(("VAL", _NUMERIC_SIMULATION_VALUE))
        else:
            fields.append(("VAL", _STRING_SIMULATION_VALUE))
        fields.append(("UDF", "0"))

        info_items = [
            (f"naradBindingId{index}", binding.id)
            for index, binding in enumerate(bindings)
        ]
        for field_signal in fields_by_record[signal.id]:
            field = field_signal.record_field
            assert field is not None
            fields.append((field, FIELD_POLICIES[field].initial_value))
            info_items.append((f"narad{field}SignalId", field_signal.id))
            info_items.extend(
                (f"narad{field}BindingId{index}", binding.id)
                for index, binding in enumerate(bindings_by_signal[field_signal.id])
            )

        records.append(
            EpicsRecord(
                record_type=RECORD_TYPES[
                    (signal.native_data_type, signal.signal_role)
                ],
                name=signal.id,
                aliases=tuple(binding.epics_alias for binding in bindings),
                info_items=tuple(info_items),
                fields=tuple(fields),
            )
        )
    return tuple(records)