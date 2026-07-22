#!/usr/bin/env python3
"""latido_camera_test.py — LIVE camera → weaver → Latido readout (macOS / CPU-friendly).

Runs the REAL weaver engine + REAL shaper manifest, activates the Latido scene,
receives a LIVE HarMoCAP OSC stream from `run_realtime.py` (via the real
HarMoCAPDriver on UDP :9100), and runs a built-in ~72 bpm ECG simulator. Prints a
live readout of the values the engine would send to the shaper, so you can watch
the figure parameters respond as you move in front of the camera.

No GPU, no SuperCollider, no laser — this proves the dance -> pose -> driver ->
mapping path with a real camera and a real body on CPU (the piece the synthetic
latido_smoke.py could not exercise). To also HEAR it, run the shaper separately
on CoreAudio and it will receive /digital/* on :9002.

Two terminals:

  A) HarMoCAP (its own venv):
       .venv/bin/python scripts/run_realtime.py --source <cam> \
           --host 127.0.0.1 --port 9100 --show

  B) this harness (the weaver venv):
       <weaver>/.venv/bin/python scripts/latido_camera_test.py

Ctrl-C to stop.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LATIDO = HERE.parent
BEACON = LATIDO.parent
WEAVER = Path(sys.argv[1]) if len(sys.argv) > 1 else BEACON / "harmonic-weaver"
SHAPER_CONTRACT = BEACON / "harmonic-shaper" / "contracts" / "shaper.contract.json"
SCENE = LATIDO / "scenes" / "latido.scene.json"
HARMOCAP_PORT = 9100
BPM = 72

sys.path.insert(0, str(HERE))            # for latido_smoke (idempotent safety helper)
sys.path.insert(0, str(WEAVER / "src"))
sys.path.insert(0, str(WEAVER))          # for the `rehearsal` package

from harmonic_weaver.engine import WeaverEngine                       # noqa: E402
from harmonic_weaver.contract_codec import contract_id_from_manifest  # noqa: E402
from harmonic_weaver.drivers.harmocap_driver import HarMoCAPDriver    # noqa: E402
from rehearsal.weaver_runtime import harmocap_manifest, ecg_manifest  # noqa: E402
from latido_smoke import latido_shaper_safety                         # noqa: E402

OBSERVED = "observed"
_STOP = threading.Event()


class LiveTransport:
    """Keeps the latest value the engine emitted per instrument address."""

    def __init__(self) -> None:
        self.latest: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def send_capability(self, record) -> None:  # OutputTransport protocol
        if record.address is not None and record.value is not None:
            with self._lock:
                self.latest[record.address] = (float(record.value), record.reason)

    def snapshot(self) -> dict[str, tuple[float, str]]:
        with self._lock:
            return dict(self.latest)


def build() -> tuple[WeaverEngine, LiveTransport, list[int]]:
    tx = LiveTransport()
    engine = WeaverEngine(transport=tx)
    shaper = json.loads(SHAPER_CONTRACT.read_text(encoding="utf-8"))
    scid = contract_id_from_manifest(shaper)
    engine.install_instrument(shaper, latido_shaper_safety(scid))
    assert engine.instrument_hello("shaper", "a" * 16, scid)
    assert engine.instrument_sync_complete("shaper", "a" * 16, scid)
    hcid = engine.install_source(harmocap_manifest())
    assert engine.source_hello("harmocap", "b" * 16, hcid)
    ecid = engine.install_source(ecg_manifest())
    assert engine.source_hello("ecg", "c" * 16, ecid)
    scene = json.loads(SCENE.read_text(encoding="utf-8"))
    engine.upsert_scene(scene, engine.stage_revision)
    engine.switch_scene("latido", 1, engine.stage_revision)

    hm_count = [0]

    def hm_on_frame(source_id, channel_values):
        hm_count[0] += 1
        engine.driver_callback(source_id, channel_values)

    driver = HarMoCAPDriver(on_frame=hm_on_frame)
    threading.Thread(
        target=driver.serve_udp,
        kwargs={"host": "0.0.0.0", "port": HARMOCAP_PORT},
        daemon=True,
    ).start()
    return engine, tx, hm_count


def ecg_simulator(engine: WeaverEngine) -> None:
    period = 60.0 / BPM
    last = time.monotonic() - period
    while not _STOP.is_set():
        now = time.monotonic()
        beat = 1.0 if (now - last) >= period else 0.0
        if beat:
            last = now
        engine.driver_callback("ecg", {
            "beat": (beat, OBSERVED, 1.0),
            "bpm": (float(BPM), OBSERVED, 1.0),
            "signal_quality": (1.0, OBSERVED, 1.0),
        })
        time.sleep(1.0 / 30.0)


def readout(tx: LiveTransport, hm_count: list[int]) -> None:
    def g(addr: str) -> float:
        return tx.snapshot().get(addr, (0.0, "-"))[0]

    print(f"Listening for HarMoCAP OSC on :{HARMOCAP_PORT}, ECG simulated at {BPM} bpm.")
    print("Move in front of the camera — envelopes should rise with energy, phases "
          "should drift, master should pulse.\n")
    header = "  hm_frames | env H1..H5                    | phase H2..H5                  | master"
    print(header)
    while not _STOP.is_set():
        env = " ".join(f"{g(f'/digital/harmonic/{n}/envelope'):4.2f}" for n in range(1, 6))
        pha = " ".join(f"{g(f'/digital/harmonic/{n}/phase'):5.0f}" for n in range(2, 6))
        mas = g("/digital/master")
        live = "LIVE" if hm_count[0] else "waiting for camera…"
        print(f"\r  {hm_count[0]:>8} | {env} | {pha} | {mas:4.2f}  [{live}]   ", end="", flush=True)
        time.sleep(0.3)


def main() -> int:
    print(f"weaver: {WEAVER}")
    print(f"shaper: {SHAPER_CONTRACT}  ({'found' if SHAPER_CONTRACT.exists() else 'MISSING'})")
    engine, tx, hm_count = build()
    threading.Thread(target=ecg_simulator, args=(engine,), daemon=True).start()
    try:
        readout(tx, hm_count)
    except KeyboardInterrupt:
        _STOP.set()
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
