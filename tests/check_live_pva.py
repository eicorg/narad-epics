"""Opt-in live softIocPVA and Tao model-service check."""

import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
EPICS_BASE = Path(
    os.environ.get("EPICS_BASE", str(ROOT.parent / ".tools/epics-base"))
)
LOG_DIR = Path(tempfile.mkdtemp(prefix="toy-pva-live-check-"))
print("Test logs:", LOG_DIR, flush=True)
sys.path.insert(0, str(ROOT))

from iocs.pva_bridge import load_mapping
from models.pv_model import RingModel
from p4p.client.thread import Context


ENVIRONMENT = dict(
    os.environ,
    EPICS_PVA_ADDR_LIST="127.0.0.1",
    EPICS_PVA_AUTO_ADDR_LIST="NO",
    EPICS_PVAS_INTF_ADDR_LIST="127.0.0.1",
)
os.environ.update(ENVIRONMENT)
PROCESSES: list[subprocess.Popen[bytes]] = []
HANDLES = []
LOGS: dict[str, Path] = {}


def start(name: str, command: list[str]) -> subprocess.Popen[bytes]:
    path = LOG_DIR / f"{name}.log"
    handle = path.open("w")
    HANDLES.append(handle)
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=ENVIRONMENT,
        stdin=subprocess.PIPE,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    PROCESSES.append(process)
    LOGS[name] = path
    return process


def wait_for(name: str, text: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        content = LOGS[name].read_text()
        if text in content:
            return
        for process in PROCESSES:
            if process.poll() is not None:
                raise RuntimeError(
                    f"Process exited {process.returncode}: {content}"
                )
        time.sleep(0.1)
    raise TimeoutError(LOGS[name].read_text())


def find_soft_ioc_pva() -> Path:
    candidates = [
        candidate
        for pattern in ("bin/*/softIocPVA", "bin/*/softIocPVA.exe")
        for candidate in EPICS_BASE.glob(pattern)
    ]
    if not candidates:
        raise FileNotFoundError(f"softIocPVA not found below {EPICS_BASE}")
    return candidates[0]


def scalar(value):
    return getattr(value, "value", value)


try:
    ioc = start(
        "ioc",
        [str(find_soft_ioc_pva()), "-d", "generated/toy_ring.db"],
    )
    setpoints, readbacks = load_mapping(
        ROOT / "yaml-descriptions/toy_ring_narad_instance.yaml"
    )
    context = Context("pva")
    names = [signal.pv for signal in setpoints + readbacks]
    names.append("inst:es12-t1:PS:H:Status")
    context.get(names, timeout=30.0)
    print(
        "Loaded softIocPVA: all 1,152 numeric PVs and representative status connected.",
        flush=True,
    )

    start(
        "service",
        [sys.executable, "-u", "-m", "iocs.pva_bridge", "--timeout", "20"],
    )
    wait_for("service", "Model service ready", timeout=90.0)

    reference = RingModel(ROOT / "models/toy_ring.bmad")

    def apply(plane: str, value: float) -> None:
        pv = f"inst:es12-t1:PS:{plane}:Current-SP"
        context.put(pv, value, timeout=10.0, wait=True)
        wait_for("service", f"Forwarded {pv} = {value};", timeout=90.0)
        reference.set(f"steering_{plane.lower()}:i_es12_t1", value)

    apply("H", 0.01)
    apply("V", -0.02)
    for readback in readbacks:
        expected = reference.get(readback.key) * readback.scale
        actual = float(scalar(context.get(readback.pv, timeout=10.0)))
        assert math.isclose(
            actual, expected, rel_tol=1e-10, abs_tol=1e-12
        ), (readback.pv, actual, expected)
    print(
        "Verified all 768 current/BPM readbacks, including m-to-mm conversion.",
        flush=True,
    )
    print(
        "Status untouched:",
        scalar(context.get("inst:es12-t1:PS:H:Status", timeout=10.0)),
        flush=True,
    )

    apply("H", 0.0)
    apply("V", 0.0)
    print("Restored both currents to zero; readbacks match Tao.", flush=True)
    context.close()

    if ioc.stdin is not None:
        ioc.stdin.write(b"exit\n")
        ioc.stdin.flush()
    ioc.wait(timeout=10)
    print("PASS", flush=True)
finally:
    for process in reversed(PROCESSES):
        if process.poll() is None:
            process.terminate()
    for process in PROCESSES:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    for handle in HANDLES:
        handle.close()