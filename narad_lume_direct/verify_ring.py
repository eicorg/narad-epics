"""Exercise the full ring publication using a local-only PVAccess client."""

import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryFile
import time

from p4p.client.thread import Context, RemoteError
import yaml


HERE = Path(__file__).resolve().parent


def main():
    profile = yaml.safe_load((HERE / "toy_ring.hardware.yaml").read_text())
    floating_ids = list(profile["signal_ids"].values())
    status_ids = [entry["id"] for entry in profile["statuses"].values()]
    assert len(set(floating_ids + status_ids)) == 1544

    os.environ.update(
        EPICS_PVA_ADDR_LIST="127.0.0.1",
        EPICS_PVA_AUTO_ADDR_LIST="NO",
        EPICS_PVAS_INTF_ADDR_LIST="127.0.0.1",
    )
    prefix = f"RINGVERIFY{os.getpid()}:"
    setpoint = "inst:es12-t1:PS:H:Current-SP"
    current = "inst:es12-t1:PS:H:Current-RB"
    orbit = "inst:es12-bpm0:X-RB"

    with TemporaryFile(mode="w+") as log, Context("pva") as client:
        server = subprocess.Popen(
            [sys.executable, str(HERE / "serve.py"),
             "--lattice", str(HERE / "toy_ring.no_alias.pals.yaml"),
             "--hardware", str(HERE / "toy_ring.hardware.yaml"),
             "--prefix", prefix],
            stdout=log,
            stderr=subprocess.STDOUT,
        )

        def read(signal, timeout=2):
            return client.get(prefix + signal, timeout=timeout)

        def write(signal, value):
            client.put(prefix + signal, value, timeout=10, wait=True)

        try:
            deadline = time.monotonic() + 120
            while True:
                try:
                    initial_current = float(read(current))
                    break
                except TimeoutError:
                    if server.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        raise RuntimeError(log.read())

            floats = client.get([prefix + name for name in floating_ids], timeout=30)
            assert all(math.isfinite(float(value)) for value in floats)
            assert all(value == "UNKNOWN" for value in
                       client.get([prefix + name for name in status_ids], timeout=30))
            assert read(current).raw["display.units"] == "A"
            assert read(orbit).raw["display.units"] == "mm"

            before = float(read(orbit))
            write(setpoint, initial_current + 1)
            assert math.isclose(float(read(current)), initial_current + 1)
            after = float(read(orbit))
            assert abs(after - before) > 1e-4

            for signal, value in [(current, 0), (orbit, 0), (status_ids[0], "OK")]:
                try:
                    write(signal, value)
                except RemoteError:
                    continue
                raise AssertionError(f"Read-only PV accepted a write: {signal}")

            write("RESET", 1)
            deadline = time.monotonic() + 10
            while True:
                reset_current = float(read(current))
                reset_orbit = float(read(orbit))
                if (math.isclose(reset_current, initial_current, abs_tol=1e-9)
                        and math.isclose(reset_orbit, before, abs_tol=1e-8)):
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError(
                        f"Reset returned {reset_current} A and {reset_orbit} mm; "
                        f"expected {initial_current} A and {before} mm"
                    )
            print(f"Verified 1544 signal PVs. Horizontal orbit response: {after-before:+.6f} mm")
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    main()
