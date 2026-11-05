from __future__ import annotations

from collections import defaultdict

from .models import EpicsRecord, NaradDescription, SignalBinding


_RECORD_TYPES = {
    ("Float", "Readback"): "ai",
    ("Float", "Setpoint"): "ao",
    ("String", "Status"): "stringin",
}
_DESCRIPTION_LENGTH = 40
_DEFAULT_PRECISION = "3"
_NUMERIC_SIMULATION_VALUE = "0"
_STRING_SIMULATION_VALUE = "UNKNOWN"


def map_description(description: NaradDescription) -> tuple[EpicsRecord, ...]:
    bindings_by_signal: dict[str, list[SignalBinding]] = defaultdict(list)
    for binding in description.bindings:
        bindings_by_signal[binding.object].append(binding)

    records: list[EpicsRecord] = []
    for signal in description.signals:
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

        records.append(
            EpicsRecord(
                record_type=_RECORD_TYPES[
                    (signal.native_data_type, signal.signal_role)
                ],
                name=signal.id,
                aliases=tuple(binding.epics_alias for binding in bindings),
                info_items=tuple(
                    (f"naradBindingId{index}", binding.id)
                    for index, binding in enumerate(bindings)
                ),
                fields=tuple(fields),
            )
        )
    return tuple(records)