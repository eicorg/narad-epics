"""Run an accelerator model as an independent EPICS PVA client service.

The service reads and monitors setpoint PVs, serializes model updates through
one worker, and writes model-derived readbacks back to the IOC with p4p.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from queue import Queue
from typing import Any, Protocol

from .pv_model import RingModel


LOGGER = logging.getLogger(__name__)
_STOP = object()


class SimulationModel(Protocol):
    """Model operations required by :class:`ModelService`."""

    @property
    def setpoint_pvs(self) -> tuple[str, ...]: ...

    def apply_setpoint(self, pv: str, value: float) -> None: ...

    def apply_setpoints(self, values: Mapping[str, float]) -> None: ...

    def readbacks(
        self, changed_setpoint: str | None = None
    ) -> Mapping[str, float | str]: ...


class PVAContext(Protocol):
    """Subset of the threaded p4p client API used by the service."""

    def get(self, names: list[str], *, timeout: float) -> list[Any]: ...

    def monitor(
        self, name: str, callback: Any, *, notify_disconnect: bool
    ) -> Any: ...

    def put(
        self,
        names: list[str],
        values: list[float | str],
        *,
        timeout: float,
        wait: bool,
    ) -> Any: ...

    def close(self) -> None: ...


class ModelService:
    """Bridge setpoint monitors to one serialized simulation model."""

    def __init__(
        self,
        model: SimulationModel,
        context: PVAContext,
        *,
        timeout: float = 5.0,
    ) -> None:
        self.model = model
        self.context = context
        self.timeout = timeout
        self._updates: Queue[object] = Queue()
        self._subscriptions: list[Any] = []
        self._last_setpoints: dict[str, float] = {}
        self._worker = threading.Thread(
            target=self._run_worker,
            name="tao-model-worker",
            daemon=True,
        )
        self._started = False
        self._closed = False

    def start(self) -> None:
        """Synchronize current setpoints, publish outputs, and start monitors."""

        if self._started:
            raise RuntimeError("model service is already started")
        if self._closed:
            raise RuntimeError("model service is closed")

        setpoints = list(self.model.setpoint_pvs)
        values = self.context.get(setpoints, timeout=self.timeout)
        if len(values) != len(setpoints):
            raise RuntimeError("PVA get returned the wrong number of setpoint values")

        initial_values = {
            pv: _numeric_value(value)
            for pv, value in zip(setpoints, values, strict=True)
        }
        self.model.apply_setpoints(initial_values)
        self._last_setpoints.update(initial_values)
        self._publish(self.model.readbacks())

        self._worker.start()
        try:
            for pv in setpoints:
                subscription = self.context.monitor(
                    pv,
                    lambda value, monitored_pv=pv: self._on_update(
                        monitored_pv, value
                    ),
                    notify_disconnect=True,
                )
                self._subscriptions.append(subscription)
        except Exception:
            self.close()
            raise
        self._started = True

    def wait_for_idle(self) -> None:
        """Wait until all setpoint updates already received are processed."""

        self._updates.join()

    def close(self) -> None:
        """Stop monitors and the worker, then release the p4p context."""

        if self._closed:
            return
        self._closed = True
        for subscription in self._subscriptions:
            subscription.close()
        self._subscriptions.clear()
        if self._worker.is_alive():
            self._updates.put(_STOP)
            self._worker.join()
        self.context.close()

    def _on_update(self, pv: str, value: Any) -> None:
        if self._closed:
            return
        if isinstance(value, Exception):
            LOGGER.warning("PVA monitor for %s: %s", pv, value)
            return
        try:
            numeric_value = _numeric_value(value)
        except (TypeError, ValueError):
            LOGGER.exception("Ignoring invalid setpoint update for %s", pv)
            return
        if self._last_setpoints.get(pv) == numeric_value:
            return
        self._updates.put((pv, numeric_value))

    def _run_worker(self) -> None:
        while True:
            update = self._updates.get()
            try:
                if update is _STOP:
                    return
                pv, value = update
                self.model.apply_setpoint(pv, value)
                self._last_setpoints[pv] = value
                self._publish(self.model.readbacks(pv))
            except Exception:
                LOGGER.exception("Failed to process model setpoint update")
            finally:
                self._updates.task_done()

    def _publish(self, values: Mapping[str, float | str]) -> None:
        if not values:
            return
        self.context.put(
            list(values),
            list(values.values()),
            timeout=self.timeout,
            wait=True,
        )


def _numeric_value(value: Any) -> float:
    """Coerce an auto-unwrapped p4p scalar, rejecting disconnect errors."""

    if isinstance(value, Exception):
        raise value
    return float(getattr(value, "value", value))


def _pva_context(provider: str) -> PVAContext:
    try:
        from p4p.client.thread import Context
    except ImportError as error:
        raise RuntimeError(
            "p4p is required; install the simulation dependencies"
        ) from error
    return Context(provider)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the persistent Tao model as an EPICS PVA service."
    )
    parser.add_argument("lattice", type=Path, help="Bmad lattice file")
    parser.add_argument("--provider", default="pva", help="p4p provider name")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Run until interrupted, closing monitors and the PVA context cleanly."""

    options = _argument_parser().parse_args(arguments)
    logging.basicConfig(
        level=getattr(logging, options.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    stop = threading.Event()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_name, lambda *_: stop.set())

    try:
        model = RingModel(options.lattice)
        service = ModelService(
            model,
            _pva_context(options.provider),
            timeout=options.timeout,
        )
        service.start()
        LOGGER.info(
            "Model service running with %d setpoint monitors",
            len(model.setpoint_pvs),
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