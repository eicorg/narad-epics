"""Connect one persistent Tao model to a softIocPVA database with p4p."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import logging
import math
from pathlib import Path
from queue import Queue
import re
import signal
import threading
from typing import Any, Protocol

from .parser import load_narad_description


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSignal:
    """Map one EPICS PV to a Tao-facing model key and unit scale."""

    pv: str
    key: str
    scale: float = 1.0


@dataclass(frozen=True)
class ModelUpdate:
    signal: ModelSignal
    value: float


class SimulationModel(Protocol):
    """Tao model operations required by :class:`ModelService`."""

    def list_pvs(self) -> dict[str, list[str]]: ...

    def get(self, pv: str) -> float: ...

    def set(self, pv: str, value: float) -> float: ...


class PVAContext(Protocol):
    """Subset of the threaded p4p client API used by the service."""

    def get(self, names: list[str], *, timeout: float) -> list[Any]: ...

    def monitor(
        self, name: str, callback: Any, *, notify_disconnect: bool
    ) -> Any: ...

    def put(
        self,
        names: list[str],
        values: list[float],
        *,
        timeout: float,
        wait: bool,
    ) -> Any: ...

    def close(self) -> None: ...


def load_mapping(source: Path) -> tuple[list[ModelSignal], list[ModelSignal]]:
    """Map explicit Narad numeric signals to Tao model keys."""

    description = load_narad_description(source)
    subjects: dict[str, set[str]] = {}
    for binding in description.bindings:
        subjects.setdefault(binding.object, set()).add(binding.subject)

    setpoints: list[ModelSignal] = []
    readbacks: list[ModelSignal] = []
    for narad_signal in description.signals:
        if narad_signal.signal_role == "Status":
            continue
        bound = subjects.get(narad_signal.id, set())
        if len(bound) != 1:
            raise ValueError(f"Expected one model device for {narad_signal.id}")
        device = next(iter(bound)).removeprefix("inst:").lower()
        current = re.fullmatch(
            r"inst:[^:]+:PS:([HV]):Current-(SP|RB)", narad_signal.id
        )
        bpm = re.fullmatch(r"inst:[^:]+:([XY])-RB", narad_signal.id)
        if current and narad_signal.native_unit == "A":
            item = ModelSignal(
                narad_signal.id,
                f"steering_{current[1].lower()}:i_{device}",
            )
            target = setpoints if current[2] == "SP" else readbacks
        elif (
            bpm
            and narad_signal.native_unit == "mm"
            and narad_signal.signal_role == "Readback"
        ):
            item = ModelSignal(
                narad_signal.id,
                f"{device}:{bpm[1].lower()}",
                1000.0,
            )
            target = readbacks
        else:
            raise ValueError(f"Unsupported model signal: {narad_signal.id}")
        target.append(item)
    return setpoints, readbacks


def publish_readbacks(
    model: SimulationModel,
    readbacks: list[ModelSignal],
    context: PVAContext,
    timeout: float,
) -> None:
    """Read all model outputs and publish them with one p4p put."""

    context.put(
        [signal.pv for signal in readbacks],
        [model.get(signal.key) * signal.scale for signal in readbacks],
        timeout=timeout,
        wait=True,
    )


def forward_setpoint(
    model: SimulationModel,
    signal: ModelSignal,
    value: float,
    readbacks: list[ModelSignal],
    context: PVAContext,
    timeout: float,
) -> None:
    """Apply one setpoint and publish model-confirmed readbacks."""

    model.set(signal.key, value)
    publish_readbacks(model, readbacks, context, timeout)


class ModelService:
    """Serialize PVA setpoint monitors through one persistent Tao model."""

    def __init__(
        self,
        model: SimulationModel,
        context: PVAContext,
        setpoints: list[ModelSignal],
        readbacks: list[ModelSignal],
        *,
        timeout: float = 10.0,
    ) -> None:
        self.model = model
        self.context = context
        self.setpoints = setpoints
        self.readbacks = readbacks
        self.timeout = timeout
        self._updates: Queue[ModelUpdate | None] = Queue()
        self._subscriptions: list[Any] = []
        self._initialized: set[str] = set()
        self._last_setpoints: dict[str, float] = {}
        self._worker = threading.Thread(
            target=self._run_worker,
            name="tao-model-worker",
            daemon=True,
        )
        self._started = False
        self._closed = False

    def start(self) -> None:
        """Validate inventories, connect to softIocPVA, and start monitors."""

        if self._started:
            raise RuntimeError("model service is already started")
        if self._closed:
            raise RuntimeError("model service is closed")

        model_keys = {
            key for group in self.model.list_pvs().values() for key in group
        }
        for model_signal in self.setpoints + self.readbacks:
            if model_signal.key not in model_keys:
                raise ValueError(f"Model key missing: {model_signal.key}")

        epics_names = [
            model_signal.pv for model_signal in self.setpoints + self.readbacks
        ]
        self.context.get(epics_names, timeout=self.timeout)
        self._worker.start()
        try:
            for model_signal in self.setpoints:
                subscription = self.context.monitor(
                    model_signal.pv,
                    lambda value, monitored=model_signal: self._on_update(
                        monitored, value
                    ),
                    notify_disconnect=True,
                )
                self._subscriptions.append(subscription)
        except Exception:
            self.close()
            raise
        self._started = True

    def wait_for_idle(self) -> None:
        """Wait until every setpoint already received has been processed."""

        self._updates.join()

    def close(self) -> None:
        """Stop PVA monitors and the model worker, then close p4p."""

        if self._closed:
            return
        self._closed = True
        for subscription in self._subscriptions:
            subscription.close()
        self._subscriptions.clear()
        if self._worker.is_alive():
            self._updates.put(None)
            self._worker.join()
        self.context.close()

    def _on_update(self, model_signal: ModelSignal, value: Any) -> None:
        if self._closed:
            return
        if isinstance(value, Exception):
            LOGGER.warning("PVA monitor for %s: %s", model_signal.pv, value)
            return
        try:
            numeric_value = _numeric_value(value)
        except (TypeError, ValueError):
            LOGGER.exception("Ignoring invalid setpoint update for %s", model_signal.pv)
            return

        if model_signal.pv not in self._initialized:
            self._initialized.add(model_signal.pv)
            self._last_setpoints[model_signal.pv] = numeric_value
            if len(self._initialized) == len(self.setpoints):
                LOGGER.info(
                    "Model service ready: %d setpoints, %d readbacks",
                    len(self.setpoints),
                    len(self.readbacks),
                )
            return
        if self._last_setpoints.get(model_signal.pv) == numeric_value:
            return
        self._updates.put(ModelUpdate(model_signal, numeric_value))

    def _run_worker(self) -> None:
        while True:
            update = self._updates.get()
            try:
                if update is None:
                    return
                forward_setpoint(
                    self.model,
                    update.signal,
                    update.value,
                    self.readbacks,
                    self.context,
                    self.timeout,
                )
                self._last_setpoints[update.signal.pv] = update.value
                LOGGER.info(
                    "Forwarded %s = %s; published %d readbacks",
                    update.signal.pv,
                    update.value,
                    len(self.readbacks),
                )
            except Exception:
                LOGGER.exception("Failed to process model setpoint update")
            finally:
                self._updates.task_done()


def _numeric_value(value: Any) -> float:
    """Coerce an auto-unwrapped p4p scalar and reject non-finite values."""

    if isinstance(value, Exception):
        raise value
    numeric_value = float(getattr(value, "value", value))
    if not math.isfinite(numeric_value):
        raise ValueError("setpoint must be finite")
    return numeric_value


def _pva_context(provider: str) -> PVAContext:
    try:
        from p4p.client.thread import Context
    except ImportError as error:
        raise RuntimeError(
            "p4p is required; install the simulation dependencies"
        ) from error
    return Context(provider)


def _argument_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Connect the persistent Tao model to softIocPVA."
    )
    parser.add_argument(
        "lattice",
        type=Path,
        nargs="?",
        default=project_root / "models/toy_ring.bmad",
        help="Bmad lattice file (default: models/toy_ring.bmad)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=project_root / "yaml-descriptions/toy_ring_narad_instance.yaml",
        help="Narad description used to map EPICS PVs to Tao keys",
    )
    parser.add_argument("--provider", default="pva", help="p4p provider name")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the PVA model service until interrupted."""

    options = _argument_parser().parse_args(arguments)
    logging.basicConfig(
        level=getattr(logging, options.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stop = threading.Event()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_name, lambda *_: stop.set())

    try:
        from models.pv_model import RingModel

        setpoints, readbacks = load_mapping(options.source)
        service = ModelService(
            RingModel(options.lattice),
            _pva_context(options.provider),
            setpoints,
            readbacks,
            timeout=options.timeout,
        )
        service.start()
        LOGGER.info(
            "PVA model service running with %d setpoint monitors",
            len(setpoints),
        )
        stop.wait()
    except (OSError, RuntimeError, ValueError) as error:
        LOGGER.error("Model service failed: %s", error)
        return 1
    finally:
        if "service" in locals():
            service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())