"""Event-driven Channel Access bridge to the toy-ring JSON model server."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from queue import Queue
import re
import socket

from .parser import load_narad_description


@dataclass(frozen=True)
class ModelSignal:
    pv: str
    key: str
    scale: float = 1.0


def load_mapping(source: Path):
    """Map explicit toy-ring signals, using binding subjects as model devices."""
    description = load_narad_description(source)
    subjects = {}
    for binding in description.bindings:
        subjects.setdefault(binding.object, set()).add(binding.subject)
    setpoints, readbacks = [], []
    for signal in description.signals:
        if signal.signal_role == "Status":
            continue
        bound = subjects.get(signal.id, set())
        if len(bound) != 1:
            raise ValueError(f"Expected one model device for {signal.id}")
        device = next(iter(bound)).removeprefix("inst:").lower()
        current = re.fullmatch(r"inst:[^:]+:PS:([HV]):Current-(SP|RB)", signal.id)
        bpm = re.fullmatch(r"inst:[^:]+:([XY])-RB", signal.id)
        if current and signal.native_unit == "A":
            item = ModelSignal(signal.id, f"steering_{current[1].lower()}:i_{device}")
            target = setpoints if current[2] == "SP" else readbacks
        elif bpm and signal.native_unit == "mm" and signal.signal_role == "Readback":
            item = ModelSignal(signal.id, f"{device}:{bpm[1].lower()}", 1000.0)
            target = readbacks
        else:
            raise ValueError(f"Unsupported model signal: {signal.id}")
        target.append(item)
    return setpoints, readbacks


class ModelClient:
    def __init__(self, host, port):
        self.host, self.port = host, port

    def __enter__(self):
        self.connection = socket.create_connection((self.host, self.port), timeout=10)
        self.stream = self.connection.makefile("rwb")
        return self

    def request(self, operation, **kwargs):
        self.stream.write((json.dumps({"op": operation, **kwargs}, allow_nan=False) + "\n").encode())
        self.stream.flush()
        line = self.stream.readline()
        if not line:
            raise ConnectionError("Model server closed the connection")
        response = json.loads(line)
        if not response["ok"]:
            raise RuntimeError(response["error"])
        return response["result"]

    def __exit__(self, *args):
        self.stream.close()
        self.connection.close()


def publish_readbacks(client, readbacks, pvs):
    for signal in readbacks:
        value = client.request("get", pv=signal.key)
        pvs[signal.pv].write(value * signal.scale)


def forward_setpoint(client, signal, value, readbacks, pvs):
    client.request("set", pv=signal.key, value=value)
    publish_readbacks(client, readbacks, pvs)


def main():
    from caproto import SubscriptionType
    from caproto.threading.client import Context

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "yaml-descriptions/toy_ring_narad_instance.yaml")
    parser.add_argument("--model-host", default="127.0.0.1")
    parser.add_argument("--model-port", type=int, default=8765)
    args = parser.parse_args()
    setpoints, readbacks = load_mapping(args.source)
    events = Queue()
    callbacks, subscriptions = [], []  # caproto holds callbacks weakly
    with Context() as context:
        names = [signal.pv for signal in setpoints + readbacks]
        pvs = dict(zip(names, context.get_pvs(*names)))
        for pv in pvs.values():
            pv.wait_for_connection()
        with ModelClient(args.model_host, args.model_port) as client:
            inventory = client.request("list")
        keys = {key for group in inventory.values() for key in group}
        for signal in setpoints + readbacks:
            if signal.key not in keys:
                raise ValueError(f"Model key missing: {signal.key}")

        initialized = set()
        def callback_for(signal):
            def callback(subscription, response):
                # CA sends the existing value on subscription. Do not replay it.
                if signal.pv not in initialized:
                    initialized.add(signal.pv)
                    if len(initialized) == len(setpoints):
                        print(f"Bridge ready: {len(setpoints)} setpoints, {len(readbacks)} readbacks", flush=True)
                    return
                events.put((signal, float(response.data[0])))
            return callback

        for signal in setpoints:
            callback = callback_for(signal)
            callbacks.append(callback)
            subscription = pvs[signal.pv].subscribe(mask=SubscriptionType.DBE_VALUE)
            subscription.add_callback(callback)
            subscriptions.append(subscription)
        try:
            while True:
                signal, value = events.get()
                # Release the single-client server after each event's readbacks.
                with ModelClient(args.model_host, args.model_port) as client:
                    forward_setpoint(client, signal, value, readbacks, pvs)
                print(f"Forwarded {signal.pv} = {value}; published {len(readbacks)} readbacks", flush=True)
        except KeyboardInterrupt:
            pass
        finally:
            for subscription in subscriptions:
                subscription.clear()


if __name__ == "__main__":
    main()
